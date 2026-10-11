"""RGB-only evidence. Never accepts depth, camera extrinsics or simulator bodies."""
import time
import cv2
import numpy as np
from PIL import Image

CAMERAS = ("cam_high", "cam_left_wrist", "cam_right_wrist")


class RGBEvidence:
    def __init__(self, cfg):
        import torch
        from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection, Sam2Model, Sam2Processor
        self.torch, self.cfg = torch, cfg
        self.device = cfg.get("device", "cpu")
        torch.set_num_threads(cfg.get("cpu_threads", 4))
        common = dict(cache_dir=cfg["cache_dir"], local_files_only=cfg.get("offline", True))
        self.processor = AutoProcessor.from_pretrained(cfg["detector_model"], **common)
        self.detector = AutoModelForZeroShotObjectDetection.from_pretrained(cfg["detector_model"], **common).to(self.device).eval()
        self.sam_processor = Sam2Processor.from_pretrained(cfg["sam_model"], **common)
        self.sam = Sam2Model.from_pretrained(cfg["sam_model"], **common).to(self.device).eval()
        self.previous = {}
        self.next_id = 0

    def observe(self, obs):
        started = time.monotonic()
        views = {}
        caption = ". ".join(self.cfg["phrases"])+"."
        if self.cfg.get("include_instruction", False):
            # Public task language is allowed; never obtain nouns from scene truth.
            caption += " " + str(obs["instruction"])[:500]
        for name in CAMERAS:
            rgb = obs[name]
            h, w = rgb.shape[:2]
            im = Image.fromarray(rgb)
            inputs = self.processor(images=im, text=caption, return_tensors="pt").to(self.device)
            with self.torch.inference_mode():
                pred = self.detector(**inputs)
            detections = self.processor.post_process_grounded_object_detection(
                pred, inputs.input_ids, threshold=self.cfg.get("threshold", .25), text_threshold=.25,
                target_sizes=[(h, w)])[0]
            # NMS per label; retain multiple objects, not just the largest bottle.
            selected = []
            labels = detections.get("text_labels", detections.get("labels"))
            for idx in detections["scores"].argsort(descending=True).tolist():
                box = detections["boxes"][idx].detach().cpu().numpy()
                label = str(labels[idx])
                if not any(label == s[1] and iou(box, s[2]) > .5 for s in selected):
                    selected.append((idx, label, box))
                if len(selected) >= self.cfg.get("max_instances", 10):
                    break
            records = []
            used = set()
            if selected:
                sam_in = self.sam_processor(images=im, input_boxes=[[s[2].tolist() for s in selected]], return_tensors="pt").to(self.device)
                with self.torch.inference_mode():
                    pred = self.sam(**sam_in, multimask_output=False)
                masks = self.sam_processor.post_process_masks(pred.pred_masks.cpu(), sam_in["original_sizes"].cpu())[0]
                masks = masks.reshape(-1, h, w).numpy().astype(bool)
                for (idx, label, box), mask in zip(selected, masks):
                    ys, xs = np.where(mask)
                    if len(xs) < 12:
                        continue
                    normalized = (box / [w, h, w, h]).clip(0, 1).round(4).tolist()
                    old = sorted((p for p in self.previous.get(name, []) if p["label"] == label and p["id"] not in used),
                                 key=lambda p: iou(normalized, p["bbox_uv01"]), reverse=True)
                    match = old[0] if old and iou(normalized, old[0]["bbox_uv01"]) > .15 else None
                    if match:
                        identity = match["id"]
                    else:
                        self.next_id += 1
                        identity = f"{name}:{self.next_id}"
                    used.add(identity)
                    center = [float(xs.mean()/w), float(ys.mean()/h)]
                    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    contour = max(contours, key=cv2.contourArea)
                    contour = cv2.approxPolyDP(contour, .02*cv2.arcLength(contour, True), True).reshape(-1, 2)
                    records.append(dict(id=identity, label=label, confidence=round(float(detections["scores"][idx]), 3),
                        bbox_uv01=normalized, center_uv01=np.round(center, 4).tolist(),
                        area_fraction=round(len(xs)/(w*h), 5),
                        contour_uv01=np.round(contour/[w,h], 3).tolist(),
                        mask_grid_8x8=cv2.resize(mask.astype(np.float32), (8,8), interpolation=cv2.INTER_AREA).round(2).tolist(),
                        median_rgb=np.median(rgb[mask], axis=0).astype(int).tolist(),
                        delta_center_uv01=None if match is None else np.round(np.subtract(center,match["center_uv01"]),4).tolist(),
                        tracking="same-camera IoU association; identity may fail under occlusion",
                        position_m=None))
            views[name] = dict(size=[w,h], objects=records)
            self.previous[name] = records
        return dict(source="GroundingDINO + SAM2 on RGB only", coordinate_convention="uv01: x right, y down; each camera separate; no measured object XYZ or depth",
                    detector_text=caption,
                    views=views, robot=dict(frame="environment_origin", eef_link="link6 (NOT fingertip center)",
                    eef_positions_m=np.round(obs["eef_positions"],5).tolist(),
                    eef_quaternions_wxyz=np.round(obs["eef_quaternions_wxyz"],5).tolist(),
                    states=np.round(obs["states"],5).tolist(), arm_order=["left","right"],
                    gripper_opening=[float(obs["states"][6]),float(obs["states"][13])]),
                    perception_seconds=round(time.monotonic()-started,3))


def iou(a,b):
    a,b=np.asarray(a),np.asarray(b)
    intersection=np.maximum(0,np.minimum(a[2:],b[2:])-np.maximum(a[:2],b[:2])).prod()
    union=np.maximum(0,a[2:]-a[:2]).prod()+np.maximum(0,b[2:]-b[:2]).prod()-intersection
    return float(intersection/max(float(union),1e-12))
