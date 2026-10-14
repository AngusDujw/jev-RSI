"""Proposed visible metal-contour check in a fixed RGB view; never a grasp point."""
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import label,distance_transform_edt
from pickup_visual_hull import _green_mask


def check(reference,current):
    if reference['episode_id']!=current['episode_id']:
        raise ValueError('Source anchor must be same episode')
    def path(obs):return Path(next(x['path'] for x in obs['images'] if x['camera']=='cam_high'))
    old=np.asarray(Image.open(path(reference)).convert('RGB'))
    now=np.asarray(Image.open(path(current)).convert('RGB'))
    green=_green_mask(path(reference),'cam_high');parts,n=label(green)
    sizes=np.bincount(parts.ravel(),minlength=n+1);sizes[0]=0
    green &= sizes[parts]>=max(3,.1*sizes.max())
    yy,xx=np.nonzero(green);height=int(yy.max()-yy.min()+1);width=int(xx.max()-xx.min()+1)
    x0=max(0,int(xx.mean()-width*.6));x1=min(old.shape[1],int(xx.mean()+width*.6)+1)
    y0=min(old.shape[0],int(yy.max())+2);y1=min(old.shape[0],int(yy.max()+height*1.8)+1)
    roi=np.zeros(green.shape,bool);roi[y0:y1,x0:x1]=True
    neutral=(old.min(2)>100)&((old.max(2).astype(int)-old.min(2))<35)&roi
    components,n=label(neutral);areas=np.bincount(components.ravel(),minlength=n+1);areas[0]=0
    if n==0 or areas.max()<40:
        return {'passed':False,'reason':'No sufficiently large proposed neutral blade component'}
    material=components==int(areas.argmax());my,mx=np.nonzero(material)
    if (my.max()-my.min())<15 or (my.max()-my.min())<1.5*(mx.max()-mx.min()+1):
        return {'passed':False,'reason':'Neutral region not a sufficiently elongated source-blade proposal'}
    current_neutral=(now.min(2)>60)&((now.max(2).astype(int)-now.min(2))<45)
    neutral_fraction=float(current_neutral[material].mean())
    old_edge=cv2.Canny(cv2.cvtColor(old,cv2.COLOR_RGB2GRAY),40,100)>0
    now_edge=cv2.Canny(cv2.cvtColor(now,cv2.COLOR_RGB2GRAY),40,100)>0
    band=cv2.dilate(material.astype(np.uint8),np.ones((3,3),np.uint8))>0
    source_edges=old_edge&band
    edge_count=int(source_edges.sum())
    edge_fraction=float((distance_transform_edt(~now_edge)[source_edges]<=2).mean()) if edge_count else 0
    return {'passed':bool(neutral_fraction>=.60 and edge_fraction>=.60 and edge_count>=20),
        'reference_step_id':reference['step_id'],'current_step_id':current['step_id'],
        'reference_proposed_metal_pixels':int(material.sum()),'reference_proposed_edge_pixels':edge_count,
        'current_neutral_fraction_at_reference_metal_pixels':round(neutral_fraction,4),
        'current_edge_fraction_within_2px_reference_source_edges':round(edge_fraction,4),
        'source_roi_xyxy':[x0,y0,x1,y1],
        'scope':'CURRENT fixed-high neutral elongated contour proposed below the earlier green handles. Heuristic source-appearance consistency under a rigid/static-source assumption ONLY; not a named 3D point, object pose, material identity truth, current contact or grasp target. Partial occlusion/other neutral objects can confound it; current RGB identity and uncertain wrist fit remain necessary.'}
