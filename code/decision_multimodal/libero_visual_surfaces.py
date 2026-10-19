"""Current RGB colour components and RGB-D samples, never scene model state.

The initial identity window only seeds image-space tracking. Each observation
must independently contain matching pixels; occlusion never propagates old XYZ.
These are visible-surface candidates, not object centres or grasp targets.
"""
import numpy as np
from scipy import ndimage


class SurfaceTracker:
    def __init__(self, kind, initial_box):
        self.kind=kind
        self.box=np.asarray(initial_box,float)
        self.initial_box=self.box.copy()

    def observe(self, rgb, depth, K, T):
        h,w=rgb.shape[:2]
        r,g,b=np.asarray(rgb,float).transpose(2,0,1)
        if self.kind=='bottle':
            # Green glass is distinguishable from grey/black robot parts.
            mask=(g>r*1.12+1)&(g>b*1.10+1)&(g<100)&(r<85)
            margin=85
        elif self.kind=='knob':
            mask=np.max(rgb,axis=2)<65
            margin=18
        else:raise ValueError(self.kind)
        x0,y0,x1,y1=self.box
        search=np.zeros((h,w),bool)
        search[max(0,int(y0-margin)):min(h,int(y1+margin)),
               max(0,int(x0-margin)):min(w,int(x1+margin))]=True
        labels,n=ndimage.label(mask&search)
        candidates=[];old_c=(self.box[:2]+self.box[2:])/2
        for i in range(1,n+1):
            ys,xs=np.nonzero(labels==i)
            if len(xs)<18:continue
            box=np.array([xs.min(),ys.min(),xs.max()+1,ys.max()+1],float)
            width,height=box[2:]-box[:2]
            if len(xs)>4500 or max(width,height)>150:continue
            if self.kind=='knob' and (len(xs)>1600 or width>70 or height>70):continue
            score=np.linalg.norm((box[:2]+box[2:])/2-old_c)-.008*len(xs)
            candidates.append((score,i,box))
        if not candidates:
            return dict(status='unknown',reason='No isolated current matching RGB component; no stale geometry reused.'),[]
        _,i,box=min(candidates,key=lambda v:v[0]);self.box=box
        ys,xs=np.nonzero(labels==i)
        # Select actual component pixels at quantiles, not silhouette-box centres.
        pixels=[]
        for f in (.15,.5,.85):
            y=float(np.quantile(ys,f));band=np.flatnonzero(abs(ys-y)<=max(2,(box[3]-box[1])*.08))
            if not len(band):continue
            for fx in (.25,.5,.75):
                j=band[np.argmin(abs(xs[band]-np.quantile(xs[band],fx)))]
                pixel=(int(xs[j]),int(ys[j]))
                if pixel not in pixels:pixels.append(pixel)
        samples=[]
        for u,v in pixels:
            z=float(depth[v,u]);xyz=T@np.r_[np.linalg.solve(K,[u,v,1])*z,1]
            if not np.isfinite(xyz).all() or z<=0:continue
            samples.append(dict(label='C'+str(len(samples)),pixel_uv=[u,v],
                visible_surface_world_mm=np.round(xyz[:3]*1000,1).tolist()))
        return dict(status='candidate',bbox_xyxy=box.astype(int).tolist(),pixels=int(len(xs)),
            meaning='Current colour component only. Use RGB to verify identity. Samples are visible surfaces, not the centre, grasp point, desired pose or contact evidence.',
            uncertainty='Colour segmentation may miss or merge parts. Occlusion invalidates identity; depth edges may mix surfaces. No precision guarantee.'),samples
