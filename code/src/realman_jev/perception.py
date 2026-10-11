"""RGB-derived masks / marker / VLM boxes -> measured depth -> textual scene graph.

Only CameraFrame and Observation enter this module, never a MuJoCo model/data.
All identities, segmentation thresholds and physical offsets are operator config.
"""
import itertools
import time
import cv2
import numpy as np


def transform_points(T, points):
    return points @ T[:3, :3].T + T[:3, 3]


def mask_record(label, mask, frame, score=None):
    ys, xs = np.where(mask)
    if len(xs) < 12:
        return None
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour = max(contours, key=cv2.contourArea)
    contour = cv2.approxPolyDP(contour, .015 * cv2.arcLength(contour, True), True)
    record = {"label": label, "camera": frame.name, "pixels": len(xs),
              "bbox_xyxy": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
              "centroid_uv": [round(float(xs.mean()), 2), round(float(ys.mean()), 2)],
              "contour_uv": contour.reshape(-1, 2)[::max(1, len(contour)//24)].tolist(),
              "mask_grid_8x8": cv2.resize(mask.astype(np.float32), (8,8), interpolation=cv2.INTER_AREA).round(3).tolist(),
              "confidence": score, "source": "RGB mask + aligned sensor depth",
              "clipped": bool(xs.min()==0 or ys.min()==0 or xs.max()==mask.shape[1]-1 or ys.max()==mask.shape[0]-1),
              "position_m": None, "bounds_m": None}
    z = frame.depth[ys, xs]
    good = np.isfinite(z) & (z > .03) & (z < 3)
    record["depth_valid_fraction"] = round(float(good.mean()), 3)
    if good.sum() < 12 or frame.T_base_camera is None:
        return record
    x, y, z = xs[good], ys[good], z[good]
    xyz = np.column_stack(((x-frame.K[0,2])*z/frame.K[0,0], (y-frame.K[1,2])*z/frame.K[1,1], z))
    xyz = transform_points(frame.T_base_camera, xyz)
    lo, hi = np.quantile(xyz, [.05, .95], axis=0)
    record.update(position_m=np.median(xyz,axis=0).round(4).tolist(),
                  bounds_m=[lo.round(4).tolist(), hi.round(4).tolist()],
                  depth_spread_m=round(float(np.quantile(z,.9)-np.quantile(z,.1)),4))
    return record


class HSV:
    def __init__(self, cfg):
        self.cfg = cfg

    def masks(self, frame):
        hsv = cv2.cvtColor(frame.rgb, cv2.COLOR_RGB2HSV)
        result = []
        for obj in self.cfg["objects"]:
            mask = np.zeros(hsv.shape[:2], np.uint8)
            for lo, hi in obj["hsv_ranges"]:
                mask |= cv2.inRange(hsv, np.array(lo), np.array(hi))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3,3),np.uint8))
            n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
            if n > 1:
                i = 1 + np.argmax(stats[1:,cv2.CC_STAT_AREA])
                if stats[i, cv2.CC_STAT_AREA] >= obj.get("min_pixels", 20):
                    result.append((obj["label"], labels == i, None))
        return result


class Aruco:
    def __init__(self, cfg):
        self.objects = cfg["objects"]
        dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, cfg.get("dictionary", "DICT_4X4_50")))
        self.detector = cv2.aruco.ArucoDetector(dictionary)

    def masks(self, frame):
        corners, ids, _ = self.detector.detectMarkers(frame.rgb)
        out = []
        for poly, id_ in zip(corners, ids.flatten() if ids is not None else []):
            matches = [o for o in self.objects if o.get("marker_id") == int(id_)]
            if matches:
                m = np.zeros(frame.rgb.shape[:2], np.uint8)
                cv2.fillConvexPoly(m, np.rint(poly[0]).astype(np.int32), 1)
                out.append((matches[0]["label"], m.astype(bool), None))
        return out


class GroundedSAM:
    """HF GroundingDINO + SAM2, CPU default; weights stored under project cache."""
    def __init__(self, cfg):
        import torch
        from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection, Sam2Model, Sam2Processor
        self.torch, self.cfg = torch, cfg
        self.device = cfg.get("device", "cpu")
        cache = cfg["cache_dir"]
        self.detector_processor = AutoProcessor.from_pretrained(cfg["detector_model"], cache_dir=cache)
        self.detector = AutoModelForZeroShotObjectDetection.from_pretrained(cfg["detector_model"], cache_dir=cache).to(self.device).eval()
        self.sam_processor = Sam2Processor.from_pretrained(cfg["sam_model"], cache_dir=cache)
        self.sam = Sam2Model.from_pretrained(cfg["sam_model"], cache_dir=cache).to(self.device).eval()

    def masks(self, frame):
        from PIL import Image
        im = Image.fromarray(frame.rgb)
        result = []
        # Separate phrases preserve application identities without fuzzy label mapping.
        for obj in self.cfg["objects"]:
            inputs = self.detector_processor(images=im, text=obj.get("prompt", obj["label"])+".", return_tensors="pt").to(self.device)
            with self.torch.inference_mode():
                outputs = self.detector(**inputs)
            detections = self.detector_processor.post_process_grounded_object_detection(outputs, inputs.input_ids, threshold=.3, text_threshold=.25, target_sizes=[im.size[::-1]])[0]
            if len(detections["boxes"]) == 0:
                continue
            best = int(detections["scores"].argmax())
            box = detections["boxes"][best].detach().cpu().tolist()
            sam_inputs = self.sam_processor(images=im, input_boxes=[[box]], return_tensors="pt").to(self.device)
            with self.torch.inference_mode():
                pred = self.sam(**sam_inputs, multimask_output=False)
            masks = self.sam_processor.post_process_masks(pred.pred_masks.cpu(), sam_inputs["original_sizes"].cpu())[0]
            mask = masks.reshape(-1, *frame.rgb.shape[:2])[0].numpy().astype(bool)
            result.append((obj["label"], mask, float(detections["scores"][best])))
        return result


class VLM:
    """A separate vision service translates pixels; its calls are separately metered."""
    def __init__(self, cfg, api):
        self.cfg, self.api = cfg, api

    def masks(self, frame):
        labels = [o["label"] for o in self.cfg["objects"]]
        reply = self.api.chat(
            "Describe only visible objects, no robot actions or task plan. Return JSON {objects:[{label: exact requested label,bbox:[x0,y0,x1,y1],description:string}]}. Coordinates are normalized 0..1; omit invisible objects. Do not hallucinate depth or contact.",
            {"requested_labels": labels}, {frame.name: frame})
        result = []
        h,w = frame.rgb.shape[:2]
        for o in reply["objects"]:
            box = np.asarray(o["bbox"],float)
            if o["label"] not in labels or box.shape != (4,) or not np.isfinite(box).all() or (box<0).any() or (box>1).any():
                raise ValueError("Invalid VLM detection")
            x0,y0,x1,y1 = np.rint(box * [w,h,w,h]).astype(int)
            if x0>=x1 or y0>=y1:
                continue
            # GrabCut refines the language model box using actual RGB boundaries.
            gc = np.zeros((h,w),np.uint8)
            cv2.grabCut(frame.rgb,gc,(x0,y0,min(w-1,x1)-x0,min(h-1,y1)-y0),np.zeros((1,65),np.float64),np.zeros((1,65),np.float64),3,cv2.GC_INIT_WITH_RECT)
            mask = (gc==cv2.GC_FGD)|(gc==cv2.GC_PR_FGD)
            result.append((o["label"],mask,None))
        return result


class Perception:
    def __init__(self, cfg, vision_api=None):
        self.cfg = cfg
        kind = cfg["mode"]
        self.engine = {"hsv": HSV, "aruco": Aruco, "grounded_sam": GroundedSAM}.get(kind, lambda c: VLM(c,vision_api))(cfg)
        if kind not in {"hsv", "aruco", "grounded_sam", "vlm"}:
            raise ValueError("Unknown perception mode")
        self.previous = {}
        self.initial = {}

    def observe(self, obs):
        records = []
        for frame in obs.cameras.values():
            for label, mask, confidence in self.engine.masks(frame):
                record = mask_record(label,mask,frame,confidence)
                if record:
                    record["source"] = self.cfg["mode"] + ": " + record["source"]
                    records.append(record)
        objects = {}
        for label in {r["label"] for r in records}:
            candidates = [r for r in records if r["label"]==label]
            valid = [r for r in candidates if r["position_m"] is not None]
            best = max(valid or candidates, key=lambda r:(not r["clipped"],r["pixels"]))
            objects[label] = dict(best)
            if best["position_m"] is not None:
                p = np.array(best["position_m"])
                self.initial.setdefault(label,p.copy())
                objects[label]["delta_from_first_seen_m"] = (p-self.initial[label]).round(4).tolist()
                objects[label]["delta_from_previous_m"] = (p-self.previous[label]).round(4).tolist() if label in self.previous else None
                objects[label]["relative_to_grasp_m"] = (p-obs.grasp_point).round(4).tolist()
                self.previous[label] = p.copy()
        relations = []
        for a,b in itertools.combinations(objects,2):
            pa,pb = objects[a]["position_m"],objects[b]["position_m"]
            if pa is not None and pb is not None:
                delta = np.subtract(pb,pa)
                relations.append({"from":a,"to":b,"delta_m":delta.round(4).tolist()})
        return {"source": "camera RGB/depth + calibration + robot proprioception only", "sequence":obs.sequence,
                "captured_monotonic":obs.captured, "perception_finished":time.monotonic(),
                "robot":{"tcp_m":obs.tcp.round(4).tolist(),"grasp_point_m":obs.grasp_point.round(4).tolist(),
                         "aperture":round(obs.aperture,3),"joints_rad":obs.joints.round(4).tolist()},
                "objects":objects,"views":records,"relations":relations}


class Facts:
    """Conservative measurement predicates. Unknown is never treated as false success."""
    def __init__(self, cfg):
        self.cfg=cfg
        self.closed_seen=False
        self.release_seen=False
        self.counters={}

    def update(self, evidence, object_label, destination_label):
        robot=evidence["robot"]
        p=np.array(robot["grasp_point_m"])
        aperture=robot["aperture"]
        self.closed_seen |= aperture < .85
        self.release_seen |= self.closed_seen and aperture > .9
        obj=evidence["objects"].get(object_label,{})
        dst=evidence["objects"].get(destination_label,{})
        a=obj.get("position_m")
        b=dst.get("position_m")
        align=self.cfg.get("alignment_m",.009)
        f={k:None for k in ("visible","aligned","at_grasp_height","gripper_closed","holding","lifted","above_destination","lowered","released","retreated","object_in_destination")}
        f["visible"]=a is not None and b is not None
        f["gripper_closed"]=aperture < .85
        f["released"]=self.release_seen and aperture > .9
        if a is not None:
            a=np.array(a)
            lo,hi=np.asarray(obj["bounds_m"])
            # A visible, interior grasp patch is valid even when a finger occludes
            # one side and shifts the remaining-mask centroid. No hidden centre.
            in_patch=bool(np.all(p[:2]>lo[:2]+.002) and np.all(p[:2]<hi[:2]-.002))
            f["aligned"]=bool(np.linalg.norm(p[:2]-a[:2]) < align or in_patch)
            grasp_z=a[2]+self.cfg.get("surface_to_grasp_m",-.015)
            grasp_tolerance=self.cfg.get("grasp_tolerance_m",.009)
            f["at_grasp_height"]=bool(f["aligned"] and abs(p[2]-grasp_z)<grasp_tolerance)
            f["lifted"]=bool(aperture < .85 and obj["delta_from_first_seen_m"][2]>self.cfg.get("lift_m",.09))
            obstacles=self.cfg.get("obstacle_labels",[])
            if obstacles:
                bounds=[evidence["objects"].get(label,{}).get("bounds_m") for label in obstacles]
                if any(bound is None for bound in bounds):
                    f["lifted"]=None
                else:
                    clearance=max(bound[1][2] for bound in bounds)+self.cfg.get("obstacle_clearance_m",.06)
                    evidence["observed_obstacle_clearance_z_m"]=round(clearance,4)
                    f["lifted"]=f["lifted"] and bool(p[2]>clearance)
            f["holding"]=bool(aperture < .85 and np.linalg.norm(p[:2]-a[:2])<.04 and abs(p[2]-a[2])<.06)
            evidence["object_grasp_height_m"]=round(grasp_z,4)
            evidence["grasp_tolerance_m"]=grasp_tolerance
        if b is not None:
            b=np.array(b)
            aligned=bool(np.linalg.norm(p[:2]-b[:2])<align*1.5)
            f["above_destination"]=aligned and bool(p[2]-b[2]>.07)
            f["lowered"]=aligned and bool(.01 < p[2]-b[2] < .05)
            f["retreated"]=bool(self.release_seen and aperture>.9 and p[2]-b[2]>.14)
            if a is not None:
                lo,hi=np.array(dst["bounds_m"])
                contained=bool(np.all(a[:2]>lo[:2]+.008) and np.all(a[:2]<hi[:2]-.008))
                delta=obj.get("delta_from_previous_m")
                f["object_in_destination"]=bool(self.release_seen and contained and abs(a[2]-b[2])<.055 and delta is not None and np.linalg.norm(delta)<.006)
        for k,v in f.items():
            self.counters[k]=self.counters.get(k,0)+1 if v is True else 0
        evidence["facts_raw"]=f
        evidence["facts"]={k:(v if v is None else self.counters[k]>=2) for k,v in f.items()}
        evidence["predicate_notes"]="facts require two consecutive observations; closed is aperture only; lifted requires visually observed object rise; unseen is unknown."
        return evidence
