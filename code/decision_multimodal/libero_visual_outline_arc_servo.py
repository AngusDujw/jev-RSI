"""Version9: reject short rim fragments before declaring outline ambiguity."""
import hashlib
import json
from pathlib import Path
import sys

import libero_visual_outline_servo as runner


def outline_center(rgb,appearance):
    import cv2
    import numpy as np
    from PIL import Image
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    mask=cv2.inRange(hsv,np.array([18,70,80]),np.array([45,255,255]))
    contours,_=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_NONE)
    candidates=[]
    for c in contours:
        if len(c)<60:continue
        (x,y),(w,h),a=cv2.fitEllipse(c)
        if not (80<min(w,h)<250 and max(w,h)/min(w,h)<1.35):continue
        if np.linalg.norm(np.array([x,y])-appearance['pixel'])>60:continue
        t=np.deg2rad(a);rotation=np.array([[np.cos(t),np.sin(t)],[-np.sin(t),np.cos(t)]])
        q=((c[:,0,:]-[x,y])@rotation.T)/[w/2,h/2]
        p95=float(np.percentile(np.abs(np.linalg.norm(q,axis=1)-1)*min(w,h)/2,95))
        bins=np.floor((np.arctan2(q[:,1],q[:,0])+np.pi)/(2*np.pi)*36).astype(int)
        coverage=len(set(bins))/36
        if p95>4 or coverage<.65:continue
        candidates.append(dict(pixel=[float(x),float(y)],score=appearance['score'],
            rim_fit_p95_px=p95,arc_coverage=coverage,appearance_pixel=appearance['pixel']))
    candidates.sort(key=lambda r:r['arc_coverage'],reverse=True)
    folder=Path(sys.argv[sys.argv.index('--output')+1])
    valid=bool(candidates) and all(np.linalg.norm(np.array(c['pixel'])-candidates[0]['pixel'])<=8 for c in candidates)
    with (folder/'rim-evaluation.jsonl').open('a') as f:
        f.write(json.dumps(dict(valid=valid,candidates=candidates))+'\n')
    if not valid:
        Image.fromarray(rgb).save(folder/'rim-rejection.png')
        raise RuntimeError('No unambiguous long bowl-rim arc; rejection RGB preserved')
    return candidates[0]


original_save=runner.save


def save(path,value):
    if path.name=='manifest.json':
        # Call the frozen v8 writer first, then append v9 provenance.
        original_save(path,value)
        value=json.loads(path.read_text());value['profile']='libero-image-relation-outline-arc-v9'
        value['source_sha256'][Path(__file__).name]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    path.write_text(json.dumps(value,indent=2)+'\n')


runner.outline_center=outline_center
runner.save=save
if __name__=='__main__':runner.main()
