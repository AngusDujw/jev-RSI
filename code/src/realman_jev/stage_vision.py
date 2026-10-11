"""Camera-derived stage objects; never reads scene instances, depth or rewards."""
from __future__ import annotations
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image
from .stage_vision_method import VisionMethodPlan, METHOD_PROMPT


CAMERAS = ('cam_high', 'cam_left_wrist', 'cam_right_wrist')
LOCALIZER_PROMPT = '''You are the visual perception component of a robot controller.
Use ONLY the supplied RGB images and public instruction. Identify only objects
that the task requires manipulating, comparing or using as destinations. Give
each a short,
stable, semantic Python-identifier id such as conch_shell or white_bowl; these
are NEW visual IDs, never simulator instance names. Return JSON:
{"objects":[{"id":"conch_shell","category":"conch shell",
"description":"short appearance and grasp-relevant shape",
"boxes":{"cam_high":[x1,y1,x2,y2],"cam_left_wrist":[x1,y1,x2,y2]}}]}.
All boxes are PIXEL xyxy in the stated original image dimensions, not normalized.
Use a tight box only when most of the same physical object's contour is visible.
Omit a view if a robot finger hides most of it, only a sliver is visible, or its
identity is uncertain. Never include the gripper in an object box. If a target
is hidden in every view, omit it from objects; do not substitute a nearby item.
IDs refer to physical objects, not classes. Reuse an ID only with continuous
visual identity evidence. If a moving item leaves every current view and a
visually similar item appears later without continuous tracking, give the new
item a new ID, even when it matches a historical appearance. Images labeled
reference_* are historical RGB crops. Compare them for appearance only; never
assign a CURRENT box from a reference image.
No world coordinates, hidden state, asset IDs, rewards or control actions.'''
LOCALIZER_PROMPT += '''\nIf visual_method is supplied in the request, detect ONLY its declared entities.
Use each declared id verbatim, its query and distinguishing cues to identify a
physical instance across current views. Its preferred_views are priorities,
not permission to invent a box in an occluded view. The method's silhouette
and metric operators run locally after your boxes; do not claim they succeeded.'''


def pixel_ray(calibration, uv, origin):
    k = np.asarray(calibration['intrinsic'], float)
    transform = np.asarray(calibration['camera_to_world'], float)
    u, v = uv
    direction = transform[:3, :3] @ np.array([(u-k[0, 2])/k[0, 0],
        -(v-k[1, 2])/k[1, 1], -1.], float)
    direction /= np.linalg.norm(direction)
    return transform[:3, 3]-np.asarray(origin, float), direction


def _metric_uv(record):
    box = record['bbox_xyxy']
    return record.get('metric_uv') or ((box[0]+box[2])/2, (box[1]+box[3])/2)


def triangulate(boxes, calibration, origin, max_ray_gap_m=.015):
    """Intersect image-center rays; report gap rather than fabricating accuracy."""
    rays = []
    for camera, record in boxes.items():
        if camera in calibration and record.get('observed'):
            rays.append((camera, *pixel_ray(calibration[camera], _metric_uv(record), origin)))
    candidates = []
    for i, (name_a, point_a, ray_a) in enumerate(rays):
        for name_b, point_b, ray_b in rays[i+1:]:
            matrix = np.column_stack((ray_a, -ray_b))
            if np.linalg.cond(matrix) > 30:
                continue
            t = np.linalg.lstsq(matrix, point_b-point_a, rcond=None)[0]
            if np.any(t <= 0):
                continue
            a, b = point_a+t[0]*ray_a, point_b+t[1]*ray_b
            gap = float(np.linalg.norm(a-b))
            candidates.append((gap, (a+b)/2, [name_a, name_b]))
    if not candidates:
        return None
    gap, point, pair = min(candidates, key=lambda row: row[0])
    if gap > max_ray_gap_m or not np.isfinite(point).all():
        return None
    return dict(position_m=point.round(5).tolist(), ray_gap_m=round(gap, 5), views=pair)


def project_single_view_to_height(boxes, calibration, origin, height):
    """Coarse monocular XY from a visual depth reference; never measures Z motion."""
    for camera in ('cam_high', 'cam_left_wrist', 'cam_right_wrist'):
        record = boxes.get(camera)
        if not record or not record.get('observed') or camera not in calibration:
            continue
        eye, ray = pixel_ray(calibration[camera], _metric_uv(record), origin)
        if abs(ray[2]) < .05:
            continue
        distance = (height-eye[2])/ray[2]
        if distance <= 0:
            continue
        point = eye+distance*ray
        return dict(position_m=point.round(5).tolist(), ray_gap_m=None,
            views=[camera], vertical_valid=False,
            depth_reference_m=round(float(height), 5))
    return None


def _box(raw, shape):
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    h, w = shape[:2]
    try:
        x1, y1, x2, y2 = map(float, raw)
    except (TypeError, ValueError):
        return None
    if not all(np.isfinite([x1, y1, x2, y2])) or not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
        return None
    return [round(x1), round(y1), round(x2), round(y2)]


def _iou(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    overlap = max(0, right-left)*max(0, bottom-top)
    area_a = (a[2]-a[0])*(a[3]-a[1])
    area_b = (b[2]-b[0])*(b[3]-b[1])
    return overlap/max(1, area_a+area_b-overlap)


def _query_label_match(query, label):
    ignored = {'a', 'an', 'the', 'small', 'large', 'pale', 'light', 'dark',
               'white', 'black', 'purple', 'red', 'blue', 'wooden', 'on'}
    nouns = set(re.findall(r'[a-z]+', query.lower()))-ignored
    detected = set(re.findall(r'[a-z]+', label.lower()))
    return bool(nouns & detected)


def _identity(raw):
    stem = re.sub(r'\W+', '_', str(raw).lower()).strip('_')[:40]
    if not stem:
        return None
    return stem if stem.startswith('v_') else 'v_'+stem


def _appearance(rgb, box):
    x1, y1, x2, y2 = box
    crop = rgb[y1:y2, x1:x2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    histogram = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256])
    return cv2.normalize(histogram, histogram)


def _grabcut_centroid(rgb, box):
    """Estimate an RGB foreground point; reject ambiguous masks, never use depth."""
    x1, y1, x2, y2 = box
    if x2-x1 < 9 or y2-y1 < 9:
        return None
    h, w = rgb.shape[:2]
    pad = max(8, round(.2*max(x2-x1, y2-y1)))
    xx1, yy1 = max(0, x1-pad), max(0, y1-pad)
    xx2, yy2 = min(w, x2+pad), min(h, y2+pad)
    crop_rgb = np.ascontiguousarray(rgb[yy1:yy2, xx1:xx2])
    mask = np.zeros(crop_rgb.shape[:2], np.uint8)
    background = np.zeros((1, 65), np.float64)
    foreground = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2BGR), mask,
                    (x1-xx1, y1-yy1, x2-x1, y2-y1), background, foreground,
                    2, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None
    crop = np.isin(mask[y1-yy1:y2-yy1, x1-xx1:x2-xx1],
                   [cv2.GC_FGD, cv2.GC_PR_FGD])
    area = int(crop.sum())
    if not .08 <= area/crop.size <= .92:
        return None
    ys, xs = np.nonzero(crop)
    return dict(uv=[round(float(x1+xs.mean()), 2), round(float(y1+ys.mean()), 2)],
                foreground_area_px=area)


def _static_head_match(anchor, rgb, box, max_appearance_distance):
    """Reject a new semantic label that jumps to a different tabletop object."""
    old_box, old_histogram = anchor
    old_center = np.array([(old_box[0]+old_box[2])/2, (old_box[1]+old_box[3])/2])
    new_center = np.array([(box[0]+box[2])/2, (box[1]+box[3])/2])
    old_size = np.array([old_box[2]-old_box[0], old_box[3]-old_box[1]])
    new_size = np.array([box[2]-box[0], box[3]-box[1]])
    displacement = float(np.linalg.norm(new_center-old_center))
    area_ratio = float(np.prod(new_size)/np.prod(old_size))
    appearance = float(cv2.compareHist(old_histogram, _appearance(rgb, box),
                                      cv2.HISTCMP_BHATTACHARYYA))
    accepted = (displacement <= max(30., .8*float(np.linalg.norm(old_size)))
                and .45 <= area_ratio <= 2.0
                and appearance <= max_appearance_distance)
    return accepted, dict(head_displacement_px=round(displacement, 2),
                          head_area_ratio=round(area_ratio, 3),
                          head_appearance_distance=round(appearance, 3))


class VisionScene:
    def __init__(self, cfg, model, log, infer):
        self.cfg, self.model, self.log, self.infer = cfg, model, log, infer
        self.objects = {}
        self.previous_images = None
        self.cached_tick = None
        self.cached_evidence = None
        self.last_localization_decision = -10**9
        self.sequence = 0
        self.head_anchors = {}
        self.static_position_anchors = {}
        self.possibly_mobile = set()
        self.visually_mobile = set()
        self.head_motion = {}
        self.reference_crops = {}
        self.stereo_streaks = {}
        self.method = None
        self.method_by_id = {}
        self.local_detector = None
        self.local_detector_unavailable = False
        self.local_detector_calls = 0
        self.local_detector_seconds = 0.

    def _plan_method(self, obs, robot_state):
        operators = ['gpt_rgb_boxes', 'grabcut_rgb', 'rgb_template_tracking',
                     'calibrated_center_ray_triangulation', 'robot_proprioception']
        if self.cfg.get('local_detector'):
            operators.append('grounding_dino_sam2_rgb')
        request = dict(instruction=obs['instruction'], available_operators=operators,
            camera_calibration=robot_state['cameras'],
            robot_own_feedback=dict(eef_positions_m=robot_state['robot']['eef_positions_m'],
                                    eef_quaternions_wxyz=robot_state['robot']['eef_quaternions_wxyz'],
                                    states=robot_state['robot']['states']),
            image_sizes={name:[obs[name].shape[1], obs[name].shape[0]] for name in CAMERAS})
        (self.log.folder/'visual-method-input.json').write_text(json.dumps(request, indent=2))
        cameras = {name: SimpleNamespace(rgb=obs[name]) for name in CAMERAS}
        last_error = None
        for attempt in range(2):
            if last_error:
                request['validation_error'] = last_error
            raw = self.infer(self.model.chat, self.log, METHOD_PROMPT, request,
                             cameras, VisionMethodPlan.model_json_schema())
            (self.log.folder/f'visual-method-response-{attempt:02d}.json').write_text(
                json.dumps(raw, indent=2))
            try:
                method = VisionMethodPlan.model_validate(raw)
                if (not self.cfg.get('local_detector') and any(
                        entity.redetection_operator == 'grounding_dino_sam2_rgb'
                        for entity in method.entities)):
                    raise ValueError('Local DINO+SAM2 is not configured for this episode')
            except ValueError as exc:
                last_error = str(exc)[:1200]
                self.log(dict(kind='visual_method_rejected', attempt=attempt, detail=last_error))
                continue
            self.method = method
            self.method_by_id = {entity.id:entity for entity in method.entities}
            (self.log.folder/'visual-method.json').write_text(method.model_dump_json(indent=2))
            self.log(dict(kind='visual_method_accepted', entities=list(self.method_by_id),
                          sensor_source='public_RGB_calibration_robot_only'))
            return
        raise ValueError('GPT visual method failed validation twice: '+str(last_error))

    def _localize_with_local_detector(self, obs, decision):
        """Match local RGB proposals to GPT-established visual identities."""
        methods = [entity for entity in self.method.entities
                   if entity.redetection_operator == 'grounding_dino_sam2_rgb']
        if not methods or self.local_detector_unavailable:
            return False
        if self.local_detector is None:
            try:
                from .robodojo_rgb import RGBEvidence
                detector_cfg = dict(self.cfg['local_detector'])
                detector_cfg['phrases'] = [entity.local_detector_query_en for entity in methods]
                detector_cfg['include_instruction'] = False
                self.local_detector = RGBEvidence(detector_cfg)
            except Exception as exc:
                self.local_detector_unavailable = True
                self.log(dict(kind='visual_local_detector_unavailable',
                              error_type=type(exc).__name__, detail=str(exc)[:300]))
                return False
        started = time.monotonic()
        try:
            candidates = self.local_detector.observe(obs)
        except Exception as exc:
            self.local_detector_unavailable = True
            self.log(dict(kind='visual_local_detector_unavailable',
                          error_type=type(exc).__name__, detail=str(exc)[:300]))
            return False
        elapsed = time.monotonic()-started
        self.local_detector_calls += 1
        self.local_detector_seconds += elapsed
        updates = {}
        used = {name:set() for name in CAMERAS}
        for entity in methods:
            item = self.objects.get(entity.id)
            if item is None:
                return False
            matches = {}
            for name in CAMERAS:
                previous = item['boxes'].get(name)
                if previous is None:
                    continue
                old_box = previous['bbox_xyxy']
                choices = []
                h, w = obs[name].shape[:2]
                for index, candidate in enumerate(candidates['views'][name]['objects']):
                    if index in used[name]:
                        continue
                    uv = candidate['bbox_uv01']
                    box = _box([uv[0]*w, uv[1]*h, uv[2]*w, uv[3]*h], obs[name].shape)
                    if box is None:
                        continue
                    overlap = _iou(old_box, box)
                    if overlap < .18:
                        continue
                    label_match = _query_label_match(entity.local_detector_query_en,
                                                     candidate['label'])
                    if overlap < .55 and not label_match:
                        continue
                    prior_rgb = self.previous_images[name] if self.previous_images else obs[name]
                    appearance = float(cv2.compareHist(
                        _appearance(prior_rgb, old_box), _appearance(obs[name], box),
                        cv2.HISTCMP_BHATTACHARYYA))
                    if appearance > .38:
                        continue
                    if name == 'cam_high' and entity.id in self.head_anchors and entity.id not in self.possibly_mobile:
                        accepted, _ = _static_head_match(
                            self.head_anchors[entity.id], obs[name], box,
                            self.cfg.get('static_head_appearance_distance', .33))
                        if not accepted:
                            continue
                    score = overlap+.12*float(candidate['confidence'])-.2*appearance
                    choices.append((score,index,box,candidate))
                if choices:
                    _, index, box, candidate = max(choices, key=lambda row: row[0])
                    matches[name] = dict(index=index, box=box, candidate=candidate)
            required_views = 2 if 'fresh_stereo' in entity.verification else 1
            if len(matches) < required_views:
                self.log(dict(kind='visual_local_detector_miss', tick=self.cached_tick,
                              id=entity.id, matched_views=list(matches),
                              required_views=required_views, local_detector_s=round(elapsed,3)))
                return False
            updates[entity.id] = matches
            for name, match in matches.items():
                used[name].add(match['index'])
        for identity, matches in updates.items():
            item = self.objects[identity]
            for name, match in matches.items():
                item['boxes'][name] = dict(bbox_xyxy=match['box'], observed=True,
                    source='grounding_dino_sam2_rgb_associated_to_gpt_id',
                    confidence=float(match['candidate']['confidence']))
            item['last_seen_tick'] = self.cached_tick
        self.last_localization_decision = decision
        self.log(dict(kind='visual_local_detector', tick=self.cached_tick,
                      seconds=round(elapsed,3), associations={identity:list(matches)
                      for identity,matches in updates.items()},
                      provenance='RGB model proposals + prior GPT identity + image overlap/appearance'))
        return True

    def _apply_metric_points(self, obs):
        for item in self.objects.values():
            entity = self.method_by_id.get(item['id'])
            for name, record in item['boxes'].items():
                record.pop('metric_uv', None)
                record.pop('silhouette_area_px', None)
                if not record.get('observed') or entity is None or entity.metric_point != 'silhouette_centroid':
                    continue
                estimate = _grabcut_centroid(obs[name], record['bbox_xyxy'])
                if estimate is None:
                    record['metric_source'] = 'box_center_fallback_mask_unavailable'
                else:
                    record['metric_uv'] = estimate['uv']
                    record['silhouette_area_px'] = estimate['foreground_area_px']
                    record['metric_source'] = 'grabcut_rgb_foreground_centroid'

    def _register_head_motion(self, identity, previous_box, current_box, quality, diagnostics):
        """Recognize sustained object motion in the fixed head RGB camera."""
        if identity in self.possibly_mobile:
            return
        old = np.asarray([(previous_box[0]+previous_box[2])/2,
                          (previous_box[1]+previous_box[3])/2], float)
        new = np.asarray([(current_box[0]+current_box[2])/2,
                          (current_box[1]+current_box[3])/2], float)
        delta = new-old
        distance = float(np.linalg.norm(delta))
        if (quality < .7 or distance < 2.5 or
                diagnostics['head_appearance_distance'] > .22 or
                not .7 <= diagnostics['head_area_ratio'] <= 1.4):
            self.head_motion.pop(identity, None)
            return
        direction = delta/distance
        prior = self.head_motion.get(identity)
        streak = (prior['streak']+1 if prior is not None and
                  float(np.dot(direction, prior['direction'])) >= .7 else 1)
        self.head_motion[identity] = dict(streak=streak, direction=direction)
        anchor_box = self.head_anchors[identity][0]
        anchor_center = np.asarray([(anchor_box[0]+anchor_box[2])/2,
                                    (anchor_box[1]+anchor_box[3])/2], float)
        from_anchor = float(np.linalg.norm(new-anchor_center))
        if streak >= 2 and from_anchor >= 10:
            self.possibly_mobile.add(identity)
            self.visually_mobile.add(identity)
            self.log(dict(kind='visual_motion_confirmed', tick=self.cached_tick,
                          id=identity, source='fixed_head_RGB_tracking',
                          consecutive_shifts=streak, displacement_from_anchor_px=round(from_anchor, 2)))

    def _localize(self, obs, decision):
        rejected = False
        folder = self.log.folder/'visual-localizations'
        folder.mkdir(exist_ok=True)
        prefix = f'{self.sequence:03d}-tick-{self.cached_tick}'
        for name in CAMERAS:
            Image.fromarray(obs[name]).save(folder/f'{prefix}-{name}.jpg', quality=90)
        cameras = {name: SimpleNamespace(rgb=obs[name]) for name in CAMERAS}
        references = []
        for identity in sorted(self.visually_mobile):
            crop = self.reference_crops.get(identity)
            if crop is None or len(references) >= 3:
                continue
            name = 'reference_'+identity
            cameras[name] = SimpleNamespace(rgb=crop)
            Image.fromarray(crop).save(folder/f'{prefix}-{name}.jpg', quality=90)
            references.append(dict(image=name, visual_id=identity,
                                   meaning='historical RGB appearance, not a current view'))
        request = dict(instruction=obs['instruction'],
            image_sizes={name:[obs[name].shape[1], obs[name].shape[0]] for name in CAMERAS},
            previous_visual_ids=[dict(id=o['id'], category=o['category'],
                description=o['descriptions'][0], last_seen_tick=o.get('last_seen_tick'),
                currently_visible=any(b.get('observed') for b in o['boxes'].values()),
                motion_confirmed=o['id'] in self.visually_mobile)
                for o in self.objects.values()], reference_images=references)
        if self.method is not None:
            request['visual_method'] = [entity.model_dump() for entity in self.method.entities]
        (folder/f'{prefix}-input.json').write_text(json.dumps(request, indent=2))
        raw = self.infer(self.model.chat, self.log, LOCALIZER_PROMPT, request, cameras)
        (folder/f'{prefix}-output.json').write_text(json.dumps(raw, indent=2))
        if not isinstance(raw, dict) or not isinstance(raw.get('objects'), list):
            raise ValueError('Vision model did not return objects list')
        for old in self.objects.values():
            for record in old['boxes'].values():
                record['observed'] = False
                record['source'] = 'not_relocalized'
        found = 0
        for item in raw['objects']:
            if not isinstance(item, dict):
                continue
            identity = _identity(item.get('id'))
            if identity is None:
                continue
            if self.method is not None and identity not in self.method_by_id:
                self.log(dict(kind='visual_identity_rejected', tick=self.cached_tick,
                              id=identity, reason='undeclared_visual_method_id'))
                continue
            boxes = {}
            for name, candidate in item.get('boxes', {}).items():
                if name not in CAMERAS:
                    continue
                box = _box(candidate, obs[name].shape)
                if box is not None:
                    boxes[name] = dict(bbox_xyxy=box, observed=True, source='gpt_rgb', confidence=1.)
            if not boxes:
                continue
            head = boxes.get('cam_high')
            if head is not None and identity in self.head_anchors and identity not in self.possibly_mobile:
                accepted, diagnostics = _static_head_match(
                    self.head_anchors[identity], obs['cam_high'], head['bbox_xyxy'],
                    self.cfg.get('static_head_appearance_distance', .33))
                if not accepted:
                    self.log(dict(kind='visual_identity_rejected', tick=self.cached_tick,
                                  id=identity, reason='static_head_inconsistent', **diagnostics))
                    for record in self.objects.get(identity, {}).get('boxes', {}).values():
                        record['source'] = 'identity_rejected'
                    rejected = True
                    continue
            if head is not None and identity not in self.head_anchors:
                self.head_anchors[identity] = (
                    head['bbox_xyxy'], _appearance(obs['cam_high'], head['bbox_xyxy']))
            old = self.objects.get(identity, {})
            if identity not in self.reference_crops:
                camera = next((name for name in CAMERAS if name in boxes), None)
                if camera is not None:
                    x1, y1, x2, y2 = boxes[camera]['bbox_xyxy']
                    crop = obs[camera][y1:y2, x1:x2]
                    self.reference_crops[identity] = cv2.resize(
                        crop, (max(128, crop.shape[1]), max(128, crop.shape[0])))
            self.objects[identity] = dict(id=identity,
                category=str(item.get('category', identity))[:100],
                descriptions=[str(item.get('description', 'visual detection'))[:200]],
                boxes=boxes, last_position=old.get('last_position'),
                last_stereo=old.get('last_stereo'),
                last_seen_tick=old.get('last_seen_tick'),
                last_head_xy=old.get('last_head_xy'),
                visual_xy_velocity_m_per_s=old.get('visual_xy_velocity_m_per_s'),
                last_velocity_tick=old.get('last_velocity_tick'))
            found += 1
        self.log(dict(kind='visual_localization', tick=self.cached_tick,
            detected=found, visual_ids=list(self.objects)))
        self.last_localization_decision = (decision-self.cfg.get('relocalize_every_decisions', 8)+2
                                           if rejected else decision)
        self.sequence += 1

    def _track(self, obs):
        if self.previous_images is None:
            return
        for item in self.objects.values():
            for name, record in item['boxes'].items():
                if record.get('source') == 'identity_rejected':
                    continue
                prior = cv2.cvtColor(self.previous_images[name], cv2.COLOR_RGB2GRAY)
                current = cv2.cvtColor(obs[name], cv2.COLOR_RGB2GRAY)
                x1, y1, x2, y2 = record['bbox_xyxy']
                template = prior[y1:y2, x1:x2]
                if template.size == 0 or min(template.shape) < 5:
                    record['observed'] = False
                    continue
                radius = int(self.cfg.get('search_radius_px', 110))
                xx1, yy1 = max(0, x1-radius), max(0, y1-radius)
                xx2, yy2 = min(current.shape[1], x2+radius), min(current.shape[0], y2+radius)
                search = current[yy1:yy2, xx1:xx2]
                if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
                    record['observed'] = False
                    continue
                score = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
                _, quality, _, location = cv2.minMaxLoc(score)
                if quality < self.cfg.get('tracking_threshold', .58):
                    record.update(observed=False, source='tracking_lost', confidence=round(float(quality), 3))
                    continue
                nx1, ny1 = xx1+location[0], yy1+location[1]
                new_box = [nx1, ny1, nx1+x2-x1, ny1+y2-y1]
                if name == 'cam_high' and item['id'] in self.head_anchors and item['id'] not in self.possibly_mobile:
                    accepted, diagnostics = _static_head_match(
                        self.head_anchors[item['id']], obs[name], new_box,
                        self.cfg.get('static_head_appearance_distance', .33))
                    if not accepted:
                        record.update(observed=False, source='identity_rejected',
                                      confidence=round(float(quality), 3))
                        self.last_localization_decision -= self.cfg.get('relocalize_every_decisions', 8)
                        self.log(dict(kind='visual_tracking_rejected', tick=self.cached_tick,
                                      id=item['id'], reason='static_head_inconsistent', **diagnostics))
                        continue
                    self._register_head_motion(item['id'], record['bbox_xyxy'], new_box,
                                               float(quality), diagnostics)
                record.update(bbox_xyxy=new_box,
                    observed=True, source='template_tracking', confidence=round(float(quality), 3))

    def observe(self, obs, robot_state, decision):
        if self.cfg.get('method_plan_enabled', False) and self.method is None:
            self._plan_method(obs, robot_state)
        tick = robot_state['tick']
        if tick == self.cached_tick:
            return self.cached_evidence
        self.cached_tick = tick
        grasp_points = robot_state['robot']['nominal_grasp_points_m']
        states = robot_state['robot']['states']
        for item in self.objects.values():
            if item['last_position'] is None:
                continue
            if any(float(states[i*7+6]) < .5 and
                   np.linalg.norm(np.asarray(item['last_position'])-np.asarray(grasp_points[i])) < .12
                   for i in range(2)):
                self.possibly_mobile.add(item['id'])
        need_localize = not self.objects or decision-self.last_localization_decision >= self.cfg.get('relocalize_every_decisions', 8)
        if need_localize:
            if self.method is not None and self.objects and self.cfg.get('local_detector'):
                self._track(obs)
                if not self._localize_with_local_detector(obs, decision):
                    self._localize(obs, decision)
            else:
                self._localize(obs, decision)
        else:
            self._track(obs)
        self._apply_metric_points(obs)
        for item in self.objects.values():
            if any(record.get('observed') for record in item['boxes'].values()):
                item['last_seen_tick'] = tick
        self.previous_images = {name:np.asarray(obs[name]).copy() for name in CAMERAS}
        stereo = {}
        for item in self.objects.values():
            method = self.method_by_id.get(item['id'])
            boxes = item['boxes']
            if method is not None:
                preferred = {name:boxes[name] for name in method.preferred_views
                             if name in boxes and boxes[name].get('observed')}
                if len(preferred) >= 2:
                    boxes = preferred
            stereo[item['id']] = triangulate(
                boxes, robot_state['cameras'], robot_state['env_origin'],
                method.max_ray_gap_m if method is not None else
                self.cfg.get('max_triangulation_ray_gap_m', .015))
        rejected_stereo = set()
        for item in self.objects.values():
            estimate = stereo[item['id']]
            anchor = self.static_position_anchors.get(item['id'])
            if (estimate is None or anchor is None
                    or item['id'] in self.possibly_mobile):
                continue
            displacement = float(np.linalg.norm(
                np.asarray(estimate['position_m'])-np.asarray(anchor)))
            if displacement > self.cfg.get('static_stereo_jump_m', .018):
                self.log(dict(kind='visual_stereo_rejected', tick=tick, id=item['id'],
                              reason='ungrasped_object_jump', displacement_m=round(displacement, 5),
                              candidate=estimate))
                stereo[item['id']] = None
                rejected_stereo.add(item['id'])
        known_heights = [value['position_m'][2] for value in stereo.values() if value is not None]
        peer_height = float(np.median(known_heights)) if known_heights else None
        objects = []
        for item in self.objects.values():
            estimate = stereo[item['id']]
            # A partial wrist view cannot update an ungrasped target after
            # failing cross-view consistency. The head view may still supply XY
            # at the previous, explicitly unverified Z.
            if item['id'] in rejected_stereo:
                head_box = ({'cam_high':item['boxes']['cam_high']}
                            if item['boxes'].get('cam_high', {}).get('observed') else {})
            else:
                head_box = item['boxes']
            if estimate is None:
                prior = item['last_position']
                depth = float(prior[2]) if prior is not None else peer_height
                if depth is not None:
                    estimate = project_single_view_to_height(head_box, robot_state['cameras'],
                        robot_state['env_origin'], depth)
            anchor = self.static_position_anchors.get(item['id'])
            if (estimate is not None and len(estimate['views']) == 1 and anchor is not None
                    and item['id'] not in self.possibly_mobile):
                displacement = float(np.linalg.norm(
                    np.asarray(estimate['position_m'])[:2]-np.asarray(anchor)[:2]))
                if displacement > self.cfg.get('static_monocular_jump_m', .018):
                    self.log(dict(kind='visual_monocular_rejected', tick=tick, id=item['id'],
                                  reason='ungrasped_object_XY_jump', displacement_m=round(displacement, 5)))
                    estimate = None
            if estimate is not None:
                item['last_position'] = estimate['position_m']
                self.static_position_anchors.setdefault(item['id'], estimate['position_m'])
            head_record = item['boxes'].get('cam_high')
            if (head_record and head_record.get('observed') and
                    item['last_position'] is not None):
                head_point = project_single_view_to_height(
                    {'cam_high': head_record}, robot_state['cameras'],
                    robot_state['env_origin'], item['last_position'][2])
                if head_point is not None:
                    prior_head = item.get('last_head_xy')
                    dt = ((tick-prior_head['tick'])*self.cfg.get('control_dt_s', .04)
                          if prior_head else 0)
                    if item['id'] in self.visually_mobile and dt > 0:
                        velocity = ((np.asarray(head_point['position_m'][:2])-
                                     np.asarray(prior_head['position_m'][:2]))/dt)
                        if np.isfinite(velocity).all() and float(np.linalg.norm(velocity)) <= 1.:
                            previous_velocity = item.get('visual_xy_velocity_m_per_s')
                            if previous_velocity is not None:
                                velocity = .4*velocity+.6*np.asarray(previous_velocity)
                            item['visual_xy_velocity_m_per_s'] = velocity.round(4).tolist()
                            item['last_velocity_tick'] = tick
                    item['last_head_xy'] = dict(position_m=head_point['position_m'], tick=tick)
            stereo_valid = bool(estimate is not None and len(estimate['views']) >= 2)
            if stereo_valid:
                item['last_stereo'] = dict(position_m=estimate['position_m'], tick=tick,
                                           ray_gap_m=estimate['ray_gap_m'], views=estimate['views'])
            self.stereo_streaks[item['id']] = (self.stereo_streaks.get(item['id'], 0)+1
                                                if stereo_valid else 0)
            if item['last_position'] is None:
                continue
            point = np.asarray(item['last_position'], float)
            # Coarse visual bounds: these are not asset metadata or exact mesh extents.
            half = np.asarray(self.cfg.get('default_half_extent_m', [.025, .025, .018]), float)
            obj = dict(id=item['id'], kind='VisualDetection', category=item['category'],
                descriptions=item['descriptions'], position_m=point.tolist(),
                quaternion_wxyz=[1., 0., 0., 0.],
                orientation_provenance='unknown; neutral placeholder for stage expression compatibility',
                geometry=dict(world_bbox_min_m=(point-half).round(5).tolist(),
                    world_bbox_max_m=(point+half).round(5).tolist(),
                    provenance='coarse uncertainty envelope around camera triangulated center, not mesh bbox'),
                grasp_point_m=point.tolist(), grasp_point_provenance='camera box center only, not grasp proof',
                visual_boxes=item['boxes'], position_provenance=(
                    'stereo_RGB_triangulation' if estimate and len(estimate['views']) >= 2 else
                    'single_view_XY_depth_proxy_Z_UNVERIFIED' if estimate else 'last_visual_estimate_STALE'),
                position_measurement=estimate, stereo_streak=self.stereo_streaks[item['id']],
                last_seen_tick=item.get('last_seen_tick'),
                last_stereo=item.get('last_stereo'),
                last_stereo_age_ticks=(tick-item['last_stereo']['tick']
                                       if item.get('last_stereo') else None),
                possibly_mobile=item['id'] in self.possibly_mobile,
                visual_motion_confirmed=item['id'] in self.visually_mobile,
                visual_xy_velocity_m_per_s=item.get('visual_xy_velocity_m_per_s'),
                visual_xy_velocity_age_ticks=(tick-item['last_velocity_tick']
                                              if item.get('last_velocity_tick') is not None else None))
            objects.append(obj)
        evidence = dict(source='RGB-only GPT detection + RGB tracking + calibrated camera triangulation',
            frame='environment_origin', tick=tick, objects=objects, robot=robot_state['robot'],
            feature_errors=robot_state.get('feature_errors', []),
            caution='Object orientation and bbox thickness are unmeasured; stale positions are not success evidence.')
        self.cached_evidence = evidence
        self.log(dict(kind='visual_stage_evidence', tick=tick, objects=[dict(id=o['id'],
            position_m=o['position_m'], position_provenance=o['position_provenance'],
            measurement=o['position_measurement'], boxes=o['visual_boxes']) for o in objects]))
        return evidence
