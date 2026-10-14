"""Image-only blade-feature displacement; robot motion is reported separately."""
from pathlib import Path
import cv2
import numpy as np
from pickup_fixed_blade_anchor import check


def measure(previous, current):
    if previous['episode_id'] != current['episode_id'] or previous['step_id'] >= current['step_id']:
        raise ValueError('Following evidence requires ordered same-episode RGB')
    old_camera=previous['camera_calibration']['cameras']['cam_high']
    new_camera=current['camera_calibration']['cameras']['cam_high']
    if not np.allclose(old_camera['camera_to_environment'],new_camera['camera_to_environment'],atol=1e-6,rtol=0):
        raise ValueError('Fixed-high camera moved; raw flow cannot measure source change')
    anchor=check(previous,current)
    if 'source_roi_xyxy' not in anchor:
        return {'available':False,'reason':'No earlier RGB-derived elongated blade-region proposal'}
    def read(obs):
        return cv2.imread(str(Path(next(x['path'] for x in obs['images'] if x['camera']=='cam_high'))))
    a,b=read(previous),read(current)
    x0,y0,x1,y1=anchor['source_roi_xyxy']
    neutral=(a.min(2)>100)&((a.max(2).astype(int)-a.min(2))<35)
    mask=np.zeros(a.shape[:2],np.uint8);mask[y0:y1,x0:x1]=255
    mask[~neutral]=0
    gray_a,gray_b=cv2.cvtColor(a,cv2.COLOR_BGR2GRAY),cv2.cvtColor(b,cv2.COLOR_BGR2GRAY)
    points=cv2.goodFeaturesToTrack(gray_a,50,.01,3,mask=mask)
    if points is None:return {'available':False,'reason':'No image features in proposed blade region'}
    future,ok,_=cv2.calcOpticalFlowPyrLK(gray_a,gray_b,points,None)
    back,ok2,_=cv2.calcOpticalFlowPyrLK(gray_b,gray_a,future,None)
    good=(ok.ravel()>0)&(ok2.ravel()>0)&(np.linalg.norm(back-points,axis=2).ravel()<.5)
    delta=(future-points).reshape(-1,2)[good]
    result={'available':len(delta)>=6,'previous_step_id':previous['step_id'],'current_step_id':current['step_id'],
        'source_roi_xyxy':anchor['source_roi_xyxy'],'tracked_forward_backward_consistent_features':len(delta),
        'measured_robot_LINK6_delta_xyz_mm':((np.array(current['current_eef']['right']['position'])-np.array(previous['current_eef']['right']['position']))*1000).round(3).tolist(),
        'scope':'CURRENT/previous actual fixed-high RGB texture flow in an earlier green-handle-derived neutral elongated blade REGION proposal. Heuristic material identity; background, aperture ambiguity and occlusion may confound it. Pixel displacement is NOT object XYZ, contact, height or holding. Robot motion is separate; inspect original current RGB and do not infer holding from either alone.'}
    if len(delta):
        distance=np.linalg.norm(delta,axis=1)
        result.update(median_feature_flow_xy_px=np.median(delta,axis=0).round(4).tolist(),
            median_feature_displacement_px=round(float(np.median(distance)),4),
            p95_feature_displacement_px=round(float(np.percentile(distance,95)),4))
    return result
