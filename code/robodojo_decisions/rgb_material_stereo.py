"""Current calibrated RGB feature correspondences; uncertain material hypotheses.

No simulator depth/object state. Callers supply current semantic material masks.
Descriptor and epipolar checks do not certify physical feature identity.
"""
from pathlib import Path
import cv2
import numpy as np


def _ray(camera, uv, convention):
    k = np.asarray(camera['intrinsic'], float)
    t = np.asarray(camera['camera_to_environment'], float)
    d = np.linalg.solve(k, np.r_[uv, 1.])
    if convention == 'render_to_optical_diag_1_minus1_minus1':
        d = d * [1., -1., -1.]
    d = t[:3, :3] @ d
    return t[:3, 3], d / np.linalg.norm(d)


def _point(a, b, ua, ub, convention):
    oa, da = _ray(a, ua, convention)
    ob, db = _ray(b, ub, convention)
    distance = np.linalg.lstsq(np.column_stack([da, -db]), ob-oa, rcond=None)[0]
    pa, pb = oa+da*distance[0], ob+db*distance[1]
    angle = np.degrees(np.arccos(np.clip(np.dot(da, db), -1., 1.)))
    return (pa+pb)/2, float(np.linalg.norm(pa-pb)), distance, min(angle, 180-angle)


def _project(camera, point, convention):
    k = np.asarray(camera['intrinsic'], float)
    t = np.asarray(camera['camera_to_environment'], float)
    local = t[:3, :3].T @ (point-t[:3, 3])
    if convention == 'render_to_optical_diag_1_minus1_minus1':
        local = local * [1., -1., -1.]
    if local[2] <= 0:
        return None
    p = k @ local
    return p[:2]/p[2]


def match(obs, calibration, masks, cameras=('cam_high', 'cam_right_wrist'), pixel_radius=1.5):
    if obs['step_id'] != calibration['step_id']:
        raise ValueError('Same-step actual RGB and public calibration required')
    if not 0 < pixel_radius <= 3:
        raise ValueError('Explicit pixel radius must be within (0,3]')
    files = {x['camera']: Path(x['path']) for x in obs['images']}
    sift = cv2.SIFT_create(nfeatures=500, contrastThreshold=.012)
    keypoints, descriptors = [], []
    for camera in cameras:
        rgb = cv2.imread(str(files[camera]))
        if rgb is None or masks[camera].shape != rgb.shape[:2]:
            raise ValueError('Current RGB and semantic material mask mismatch')
        kp, desc = sift.detectAndCompute(cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY),
                                         np.asarray(masks[camera], np.uint8)*255)
        keypoints.append(kp); descriptors.append(desc)
    result = {'step_id': obs['step_id'], 'cameras': list(cameras),
              'keypoint_counts': [len(x) for x in keypoints], 'hypotheses': [],
              'pixel_uncertainty_radius_px': pixel_radius,
              'scope': 'CURRENT semantic-mask SIFT correspondences, reciprocal descriptor ratio<0.65; explicit camera-convention, positive-depth, ray-angle, gap and reprojection checks. Same physical feature identity remains a hypothesis. Pixel perturbation spread excludes unknown calibration/material identity systematics; no contact/holding/object truth or action approval.'}
    if any(d is None or len(d) < 2 for d in descriptors):
        result['status'] = 'UNKNOWN_insufficient_material_texture'
        return result
    bf = cv2.BFMatcher()
    def pairs(a, b):
        return {m.queryIdx:m.trainIdx for rows in bf.knnMatch(a,b,k=2)
                if len(rows)==2 for m,n in [rows] if m.distance < .65*n.distance}
    forward, reverse = pairs(*descriptors), pairs(*descriptors[::-1])
    matched = [(i,j) for i,j in forward.items() if reverse.get(j)==i]
    result['reciprocal_matches'] = len(matched)
    ca, cb = [calibration['cameras'][c] for c in cameras]
    for i,j in matched:
        ua,ub = [np.asarray(kp[index].pt,float) for kp,index in zip(keypoints,[i,j])]
        for convention in ['direct_optical', 'render_to_optical_diag_1_minus1_minus1']:
            point,gap,depths,angle = _point(ca,cb,ua,ub,convention)
            if min(depths)<=0 or angle<5 or gap>.005:
                continue
            projected = [_project(c,p,convention) for c,p in [(ca,point),(cb,point)]]
            if any(p is None for p in projected):
                continue
            errors = [float(np.linalg.norm(p-u)) for p,u in zip(projected,[ua,ub])]
            if max(errors)>pixel_radius:
                continue
            samples=[]
            for du in [[pixel_radius,0],[-pixel_radius,0],[0,pixel_radius],[0,-pixel_radius]]:
                for dv in [[pixel_radius,0],[-pixel_radius,0],[0,pixel_radius],[0,-pixel_radius]]:
                    p,_,ds,_ = _point(ca,cb,ua+du,ub+dv,convention)
                    if min(ds)>0:samples.append(p)
            if len(samples)!=16:
                continue
            samples=np.asarray(samples)
            result['hypotheses'].append({'pixel_uv': [ua.tolist(),ub.tolist()],
                'camera_convention':convention, 'camera_derived_material_point_xyz_m':point.tolist(),
                'ray_gap_mm':gap*1000, 'ray_intersection_angle_deg':angle,
                'reprojection_residual_px':errors,
                'pixel_perturbation_xyz_min_max_m':[samples.min(0).tolist(),samples.max(0).tolist()],
                'identity_verified':False, 'calibration_systematic_uncertainty':'UNKNOWN'})
    result['status'] = 'uncertain_correspondence_hypotheses' if result['hypotheses'] else 'UNKNOWN_no_geometric_match'
    return result
