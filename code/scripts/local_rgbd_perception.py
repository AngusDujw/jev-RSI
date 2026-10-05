"""Runtime GroundingDINO+SAM2 perception adapter for structured Jev control.

This module never calls a language model. It converts the existing RGBEvidence
output into the JSON-compatible visible-facts schema expected by the generated
controller; depth and calibration remain handled by VisualEvidence.
"""
import json
from pathlib import Path
import numpy as np


def overhead_robot_base_region(contour):
    """Fixed overhead view: bottom-center robot base, outside tabletop ROI."""
    center_uv = np.mean(np.asarray(contour, dtype=float), axis=0)
    return bool(.33 <= center_uv[0] <= .67 and center_uv[1] >= .875)


def build_detector(cfg, device):
    import sys
    root = Path(cfg['existing_root'])
    sys.path.insert(0, str(root / 'controller/src'))
    from realman_jev.robodojo_rgb import RGBEvidence
    source = json.loads((root / 'controller/config/company-stack-study.json').read_text())
    vcfg = dict(source['vision'])
    vcfg.update(device=f'cuda:{device}', include_instruction=True,
                calibrated_robot_projection=False, max_instances=18)
    cache = Path(vcfg['cache_dir'])
    dino = next((p for p in (cache/'models--IDEA-Research--grounding-dino-tiny'/'snapshots').iterdir() if p.is_dir()), None)
    sam = next((p for p in (cache/'models--facebook--sam2.1-hiera-tiny'/'snapshots').iterdir() if p.is_dir()), None)
    if dino is None or sam is None:
        raise FileNotFoundError('GroundingDINO/SAM2 local snapshot is missing')
    vcfg['detector_model'] = str(dino)
    vcfg['sam_model'] = str(sam)
    return RGBEvidence(vcfg), vcfg


def visible_schema(detector, observation):
    payload = dict(observation.get('robot', {}))
    payload['instruction'] = observation.get('instruction', '')
    for name, view in observation['cameras'].items():
        payload[name] = np.asarray(view['rgb'], dtype=np.uint8)
    import re
    instruction=payload['instruction']
    match=re.search(r'pick up (.+?)(?: by |$)',instruction,re.I)
    if 'fold' in instruction.lower():
        detector.cfg['phrases']=['clothes','shirt','cloth']; detector.cfg['include_instruction']=False
    elif 'bowl' in instruction.lower():
        detector.cfg['phrases']=['bowl']; detector.cfg['include_instruction']=False
    elif 'button' in instruction.lower():
        detector.cfg['phrases']=['red button','blue button','number card']; detector.cfg['include_instruction']=False
    elif 'conveyor' in instruction.lower():
        detector.cfg['phrases']=['conveyor belt','object','toy','bottle','box']; detector.cfg['include_instruction']=False
    if match:
        target=match.group(1).strip().rstrip('.')
        detector.cfg['phrases']=[target]
        detector.cfg['include_instruction']=False
    import realman_jev.robodojo_rgb as rgb_module
    old_cameras = rgb_module.CAMERAS
    rgb_module.CAMERAS = tuple(observation['cameras'])
    try:
        evidence = detector.observe(payload)
    finally:
        rgb_module.CAMERAS = old_cameras
    views = {}
    if not hasattr(detector,'digit_ocr'):
        from local_digit_ocr import DigitOCR
        detector.digit_ocr=DigitOCR()
    for name, view in evidence.get('views', {}).items():
        rows = []; accepted_masks=[]
        for item in view.get('objects', []):
            contour = item.get('contour_uv01', [])
            if len(contour) < 3:
                continue
            # The fixed overhead camera also sees the robot's black base at
            # the bottom center, beyond the table edge. A language detector
            # can label it as a black target. This measured image ROI excludes
            # that self region for pickup, without consulting scene objects.
            if match and name == 'cam_high' and overhead_robot_base_region(contour):
                continue
            label = str(item.get('label', 'object'))
            low = label.lower()
            if 'gripper' in low or 'robot' in low: continue
            if 'number' in low or 'card' in low or 'sign' in low or 'placard' in low:
                category = 'number_card'
            elif 'bowl' in low:
                category = 'bowl'
            elif 'cloth' in low or 'shirt' in low or 'garment' in low or 'clothes' in low or 'clothing' in low:
                category = 'cloth'
            elif 'conveyor' in low or 'belt' in low:
                category = 'conveyor'
            elif 'button' in low:
                category = 'button'
            elif 'container' in low or 'bin' in low or 'basket' in low:
                category = 'container'
            else:
                category = 'object'
            printed=''
            if category=='number_card':
                printed,_=detector.digit_ocr.read(observation['cameras'][name]['rgb'],contour)
            # Suppress duplicate masks even if detector emitted synonymous labels.
            import cv2
            shape=observation['cameras'][name]['rgb'].shape[:2]
            mask=np.zeros(shape,np.uint8); cv2.fillPoly(mask,[np.rint(np.asarray(contour)*[shape[1],shape[0]]).astype(np.int32)],1)
            if any(prev_category==category and (mask&prev_mask).sum()/max(1,(mask|prev_mask).sum())>.65 for prev_category,prev_mask in accepted_masks): continue
            accepted_masks.append((category,mask))
            rows.append(dict(category=category, label=label,
                appearance=label, text=printed, confidence=float(item.get('confidence', .5)),
                polygon_uv01=contour, keypoints={}))
        belts=[r for r in rows if r['category']=='conveyor']
        if len(belts)>1:
            largest=max(belts,key=lambda r:abs(cv2.contourArea(np.asarray(r['polygon_uv01'],np.float32))))
            rows=[r for r in rows if r['category']!='conveyor' or r is largest]
        views[name] = dict(objects=rows)
    return dict(views=views, source='GroundingDINO+SAM2_RGB_only_no_runtime_GPT6',
                detector_text=evidence.get('detector_text', ''),
                perception_seconds=evidence.get('perception_seconds'))
