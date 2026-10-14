"""Shared-pixel fixed-high RGB pair for visible source-following review."""
from pathlib import Path
import cv2
import numpy as np
from pickup_visual_hull import _green_mask


def build(previous, current, output):
    if previous['task']!=current['task'] or previous['step_id']>=current['step_id']:
        raise ValueError('Ordered same-task observations required')
    for key in ('intrinsic','camera_to_environment'):
        a=previous['camera_calibration']['cameras']['cam_high'][key]
        b=current['camera_calibration']['cameras']['cam_high'][key]
        if not np.allclose(a,b,rtol=0,atol=1e-9):
            raise ValueError('High camera is not fixed across this image pair')
    images=[];masks=[];failures=[]
    for obs in (previous,current):
        path=Path(next(row['path'] for row in obs['images'] if row['camera']=='cam_high'))
        image=cv2.imread(str(path))
        if image is None:raise ValueError('Missing high RGB frame')
        images.append(image)
        try:masks.append(_green_mask(path,'cam_high'));failures.append(None)
        except ValueError as error:masks.append(None);failures.append(str(error))
    if images[0].shape!=images[1].shape:raise ValueError('High frame sizes differ')
    usable=[mask for mask in masks if mask is not None]
    if not usable:raise ValueError('No current or preceding source-region proposal')
    yy,xx=np.nonzero(np.logical_or.reduce(usable))
    height,width=images[0].shape[:2]
    x0=max(0,int(xx.min())-40);x1=min(width,int(xx.max())+41)
    y0=max(0,int(yy.min())-60);y1=min(height,int(yy.max())+91)
    scale=min(4.,360/max(x1-x0,y1-y0))
    panels=[]
    for obs,image,label in zip((previous,current),images,('PREVIOUS','CURRENT')):
        crop=cv2.resize(image[y0:y1,x0:x1],(round((x1-x0)*scale),round((y1-y0)*scale)),interpolation=cv2.INTER_NEAREST)
        panel=cv2.copyMakeBorder(crop,30,0,0,0,cv2.BORDER_CONSTANT,value=(30,30,30))
        cv2.putText(panel,f'{label} fixed high step {obs["step_id"]}',(5,20),cv2.FONT_HERSHEY_SIMPLEX,.40,(255,255,255),1)
        panels.append(panel)
    target=Path(output)/f'capture_fixed_high_pair_step_{current["step_id"]:03d}.png'
    if not cv2.imwrite(str(target),np.hstack(panels)):
        raise ValueError('Could not write fixed-high comparison crop')
    facts={'previous_step_id':previous['step_id'],'current_step_id':current['step_id'],
           'fixed_public_high_camera_verified':True,'same_original_pixel_bbox_xyxy':[x0,y0,x1,y1],
           'display_scale':scale,'source_mask_pixel_counts':[int(m.sum()) if m is not None else None for m in masks],
           'mask_failures':failures,'measured_robot_delta_xyz_mm':(
               (np.asarray(current['current_eef']['right']['position'])-
                np.asarray(previous['current_eef']['right']['position']))*1000).round(3).tolist(),
           'scope':'Both panels show actual RGB at the SAME fixed-high pixel coordinates, only resized and English-labelled. The colour-mask union selects context; it is not confirmed source identity or a physical same-point match. Mask overlap/centroid shifts may reflect occlusion, illumination or deformation. Judge material and robot motion separately; no object height, true pose, contacts or holding is supplied. Compare actual fingers and all original views.'}
    if all(m is not None for m in masks):
        a,b=masks;overlap=int((a&b).sum())
        facts.update(previous_mask_retained_at_identical_pixels=round(overlap/max(int(a.sum()),1),6),
                     current_mask_overlapping_previous_pixels=round(overlap/max(int(b.sum()),1),6))
        centres=[np.column_stack(np.nonzero(m)[::-1]).mean(axis=0) for m in masks]
        facts['mask_centroid_current_minus_previous_uv_px']=(centres[1]-centres[0]).round(3).tolist()
    return {'camera':f'FIXED HIGH same-pixel source-context pair steps {previous["step_id"]} and {current["step_id"]}; image comparison, NOT holding truth',
            'path':str(target)},facts
