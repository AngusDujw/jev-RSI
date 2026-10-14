"""Current raw wrist crop with PUBLIC measured finger-facet outlines."""
from pathlib import Path
import cv2
import numpy as np
from gripper_pad_projection import inspect


def build(obs,output):
    if obs.get('measured_gripper_joint_state') is None:
        raise ValueError('Actual current finger encoders required for capture pad crop')
    projection=inspect(obs,obs['camera_calibration'])
    path=Path(next(x['path'] for x in obs['images'] if x['camera']=='cam_right_wrist'))
    image=cv2.imread(str(path));boxes=[]
    for (name,row),colour in zip(projection['rows'].items(),[(255,120,0),(0,180,255)]):
        uv=np.asarray(row['inner_facet_right_wrist_uv'],np.float32)
        cv2.polylines(image,[cv2.convexHull(np.rint(uv).astype(np.int32))],True,colour,2)
        box=row['projected_bbox_xyxy'];boxes.append(box)
        cv2.putText(image,'PUBLIC '+name,(max(0,int(box[0])),max(15,int(box[1])-5)),cv2.FONT_HERSHEY_SIMPLEX,.4,colour,1)
    x0=max(0,int(min(b[0] for b in boxes))-70);x1=min(image.shape[1],int(max(b[2] for b in boxes))+71)
    y0=max(0,int(min(b[1] for b in boxes))-70);y1=min(image.shape[0],int(max(b[3] for b in boxes))+71)
    if x1<=x0 or y1<=y0:raise ValueError('Projected pad crop outside current wrist frame')
    crop=cv2.resize(image[y0:y1,x0:x1],None,fx=2,fy=2,interpolation=cv2.INTER_LINEAR)
    target=output/f'capture_public_pad_crop_step_{obs["step_id"]:03d}.png'
    if not cv2.imwrite(str(target),crop):raise ValueError('Could not write current pad crop')
    facts={'current_step_id':obs['step_id'],'original_camera':'cam_right_wrist','crop_original_xyxy':[x0,y0,x1,y1],
        'projected_public_inner_facet_bbox_xyxy':{n:r['projected_bbox_xyxy'] for n,r in projection['rows'].items()},
        'scope':'CURRENT raw RGB crop, 2x display, with PUBLIC URDF/STL facet projections from ACTUAL measured finger joints/LINK6. Outlines may include occluded surfaces; they are not observed contacts, scene depth or holding truth. Original current three RGB remain supplied separately.'}
    return {'camera':f'CURRENT public measured inner-facet projection close-up step{obs["step_id"]}; NOT contact proof','path':str(target)},facts
