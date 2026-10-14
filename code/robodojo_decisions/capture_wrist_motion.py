"""Current green-source and brown-reference image motion; no scene truth."""
from pathlib import Path
import cv2
import numpy as np
from pickup_visual_hull import _green_mask


def _flow(a,b,mask,current_mask):
    gray_a,gray_b=cv2.cvtColor(a,cv2.COLOR_BGR2GRAY),cv2.cvtColor(b,cv2.COLOR_BGR2GRAY)
    points=cv2.goodFeaturesToTrack(gray_a,100,.005,3,mask=mask.astype(np.uint8)*255)
    if points is None:return {'available':False,'matched_features':0}
    future,ok,err=cv2.calcOpticalFlowPyrLK(gray_a,gray_b,points,None,winSize=(25,25),maxLevel=3)
    if future is None:return {'available':False,'matched_features':0}
    back,ok2,_=cv2.calcOpticalFlowPyrLK(gray_b,gray_a,future,None,winSize=(25,25),maxLevel=3)
    if back is None or ok2 is None:return {'available':False,'matched_features':0}
    pixels=np.rint(future.reshape(-1,2)).astype(int)
    valid=(ok.ravel()>0)&(ok2.ravel()>0)&(np.linalg.norm(back-points,axis=2).ravel()<.7)&(err.ravel()<30)
    valid &= (pixels[:,0]>=0)&(pixels[:,0]<b.shape[1])&(pixels[:,1]>=0)&(pixels[:,1]<b.shape[0])
    padded=cv2.dilate(current_mask.astype(np.uint8),np.ones((5,5),np.uint8))>0
    membership=np.zeros(len(pixels),bool);membership[valid]=padded[pixels[valid,1],pixels[valid,0]];valid &= membership
    delta=(future-points).reshape(-1,2)[valid];distance=np.linalg.norm(delta,axis=1)
    result={'available':len(delta)>=6,'matched_features':len(delta),'forward_backward_limit_px':.7}
    if len(delta):result.update(median_flow_xy_px=np.median(delta,axis=0).round(3).tolist(),
        median_displacement_px=round(float(np.median(distance)),3),p95_displacement_px=round(float(np.percentile(distance,95)),3))
    return result


def measure(previous,current):
    if previous['episode_id']!=current['episode_id'] or previous['step_id']>=current['step_id']:
        raise ValueError('Wrist motion needs ordered same-episode actual RGB')
    for obs in [previous,current]:
        if obs['camera_calibration']['step_id']!=obs['step_id']:raise ValueError('Current camera/state synchronization required')
    def path(obs):return Path(next(x['path'] for x in obs['images'] if x['camera']=='cam_right_wrist'))
    a,b=cv2.imread(str(path(previous))),cv2.imread(str(path(current)))
    if a is None or b is None or a.shape!=b.shape:raise ValueError('Actual wrist RGB shape/read mismatch')
    source_a,source_b=_green_mask(path(previous),'cam_right_wrist'),_green_mask(path(current),'cam_right_wrist')
    def brown(image,source):
        blue,green,red=cv2.split(image.astype(float))
        mask=(red>40)&(green>20)&(blue>8)&(red>green*1.08)&(green>blue*1.08)
        yy,xx=np.nonzero(source)
        # Exclude the whole source column band, including its holes and metal
        # extension, rather than treating source reflections as background.
        mask[:,max(0,int(xx.min())-30):min(mask.shape[1],int(xx.max())+31)]=False
        return mask
    source=_flow(a,b,source_a,source_b);background=_flow(a,b,brown(a,source_a),brown(b,source_b))
    ratio=None
    if source['available'] and background['available'] and background.get('median_displacement_px',0)>=3:
        ratio=round(source['median_displacement_px']/background['median_displacement_px'],3)
    return {'previous_step_id':previous['step_id'],'current_step_id':current['step_id'],
        'green_source_feature_motion':source,'brown_reference_feature_motion':background,
        'source_to_brown_median_motion_ratio':ratio,
        'brown_reference_selection':'Brown features outside the entire current source-image column band plus30px; excludes candidate source holes/metal reflections. Still a heuristic image reference, not scene truth.',
        'actual_robot_LINK6_delta_xyz_mm':((np.asarray(current['current_eef']['right']['position'])-np.asarray(previous['current_eef']['right']['position']))*1000).round(3).tolist(),
        'meaning':'The wrist camera rides with the measured robot. Compare ACTUAL green-source feature motion with ACTUAL brown-reference motion, not image region centres. Relatively small source motion while brown references move can support a tool-relative source hypothesis; similar motion can support a static-world/left-behind hypothesis. Depth/parallax, material reflection, rotation, occlusion and uncertain feature identity can confound both. These are pixel diagnostics, NOT source XYZ/height, contact, force or holding truth. Null ratio is UNKNOWN; near-zero robot/view motion is not an informative following test. Inspect CURRENT raw RGB and other evidence independently.'}
