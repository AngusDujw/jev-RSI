"""Current RGB negative-space and thick-green-interior measurements, not depth."""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_closing, binary_fill_holes, distance_transform_edt, label
from pickup_visual_hull import _green_mask


def measure(observation, directory: Path):
    source = next(row for row in observation['images'] if row['camera']=='cam_right_wrist')
    path=Path(source['path'])
    try:
        mask=_green_mask(path,'cam_right_wrist')
    except ValueError as error:
        return {'available':False,'reason':str(error),'step_id':observation['step_id']},None
    closed=binary_closing(mask,iterations=2)
    holes, count=label(binary_fill_holes(closed)&~closed)
    hole_rows=[]
    for i in range(1,count+1):
        yy,xx=np.nonzero(holes==i)
        if len(xx)>=80:
            hole_rows.append({'area_px':len(xx),'bbox_xyxy':[int(xx.min()),int(yy.min()),int(xx.max()),int(yy.max())],
                              'centroid_uv':[round(float(xx.mean()),2),round(float(yy.mean()),2)]})
    distance=distance_transform_edt(mask)
    threshold=max(3.,.60*float(np.percentile(distance[mask],95)))
    interiors,n=label(mask & (distance>=threshold))
    regions=[]
    for i in range(1,n+1):
        yy,xx=np.nonzero(interiors==i)
        if len(xx)<100:
            continue
        nearest=int(np.argmin((xx-xx.mean())**2+(yy-yy.mean())**2))
        regions.append({'area_px':len(xx),'bbox_xyxy':[int(xx.min()),int(yy.min()),int(xx.max()),int(yy.max())],
            'named_current_green_pixel_uv':[int(xx[nearest]),int(yy[nearest])],
            'minimum_mask_boundary_distance_px':round(float(distance[yy,xx].min()),2),
            'maximum_mask_boundary_distance_px':round(float(distance[yy,xx].max()),2)})
    regions=sorted(regions,key=lambda row:row['area_px'],reverse=True)[:4]
    result={'available':True,'camera':'cam_right_wrist','step_id':observation['step_id'],
        'green_pixel_count':int(mask.sum()),'closed_hole_regions':hole_rows,
        'thick_green_interior_regions':regions,'interior_threshold_px':round(threshold,2),
        'source_mask_touches_image_border':bool(mask[0].any() or mask[-1].any() or mask[:,0].any() or mask[:,-1].any()),
        'scope':'CURRENT original-resolution 2D color-mask measurements. Holes are NEGATIVE SPACE, not material targets. Green interior pixels belong to the mask, but thick rims can also produce candidates: Luna must identify the actual solid handle neck from raw RGB. Two-pixel closing is a stated segmentation hypothesis; clipped loops can lose hole topology. No named cross-view physical correspondence, depth, XYZ error, object pose, contact or holding is inferred.'}
    visual=Image.open(path).convert('RGB');draw=ImageDraw.Draw(visual)
    for row in hole_rows:
        draw.rectangle(row['bbox_xyxy'],outline=(255,170,0),width=2)
    for i,row in enumerate(regions):
        draw.rectangle(row['bbox_xyxy'],outline=(0,220,255),width=2)
        u,v=row['named_current_green_pixel_uv'];draw.ellipse((u-3,v-3,u+3,v+3),fill=(0,220,255))
        draw.text((row['bbox_xyxy'][0],row['bbox_xyxy'][1]),str(i+1),fill=(0,220,255))
    output=directory/'current_material_topology.png';visual.save(output)
    return result,{'camera':'CURRENT right wrist 2D topology: orange negative-space hole boxes; cyan thick-green mask regions, NOT depth/contact','path':str(output)}
