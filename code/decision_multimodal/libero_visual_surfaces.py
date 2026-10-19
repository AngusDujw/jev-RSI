"""Current RGB colour components and RGB-D samples, never scene model state.

The initial identity window only seeds image-space tracking. Each observation
must independently contain matching pixels; occlusion never propagates old XYZ.
These are visible-surface candidates, not object centres or grasp targets.
"""
import numpy as np
from scipy import ndimage


class SurfaceTracker:
    def __init__(self, kind, initial_box, sparse=False, anchor_stationary=False, track_selected=False):
        self.kind=kind
        self.box=np.asarray(initial_box,float)
        self.initial_box=self.box.copy()
        self.sparse=sparse
        self.anchor_stationary=anchor_stationary
        self.track_selected=track_selected
        self.selected_pixel=None
        self.previous_gray=None
        self.current_samples={}

    def select(self,label):
        sample=self.current_samples.get(label)
        if sample is not None and self.track_selected:
            self.selected_pixel=np.array(sample["pixel_uv"],np.float32).reshape(1,1,2)

    def follow(self,gray,allowed,depth,K,T):
        """A current RGB correspondence, never a propagated historical XYZ."""
        import cv2
        old=self.previous_gray;point=self.selected_pixel
        self.previous_gray=gray.copy()
        self.selected_pixel=None
        if old is None or point is None:return None
        params=dict(winSize=(21,21),maxLevel=3,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,30,.01))
        new,ok,_=cv2.calcOpticalFlowPyrLK(old,gray,point,None,**params)
        if new is None or not ok[0,0] or not np.isfinite(new).all():return None
        back,valid,_=cv2.calcOpticalFlowPyrLK(gray,old,new,None,**params)
        if back is None or not valid[0,0] or np.linalg.norm(back-point)>2:return None
        u,v=np.rint(new[0,0]).astype(int)
        if not (0<=v<gray.shape[0] and 0<=u<gray.shape[1]) or not allowed[v,u]:return None
        z=float(depth[v,u])
        xyz=T@np.r_[np.linalg.solve(K,[u,v,1])*z,1]
        if z<=0 or not np.isfinite(xyz).all():return None
        self.selected_pixel=new
        return dict(label="S",pixel_uv=[int(u),int(v)],visible_surface_world_mm=np.round(xyz[:3]*1000,1).tolist(),
            meaning="Current forward/backward-checked RGB match of your previously selected source feature, with current depth. Not a guaranteed material landmark or contact evidence.")

    def observe(self, rgb, depth, K, T, reject_own=None):
        h,w=rgb.shape[:2]
        self.current_samples={}
        if self.track_selected:
            import cv2
            gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
        r,g,b=np.asarray(rgb,float).transpose(2,0,1)
        if self.kind=='bottle':
            # Green glass is distinguishable from grey/black robot parts.
            mask=(g>r*1.12+1)&(g>b*1.10+1)&(g<100)&(r<85)
            margin=85
        elif self.kind=='knob':
            mask=np.max(rgb,axis=2)<65
            margin=18
        else:raise ValueError(self.kind)
        x0,y0,x1,y1=self.initial_box if self.anchor_stationary else self.box
        if self.anchor_stationary:margin=8
        search=np.zeros((h,w),bool)
        search[max(0,int(y0-margin)):min(h,int(y1+margin)),
               max(0,int(x0-margin)):min(w,int(x1+margin))]=True
        excluded=0
        if reject_own is not None:
            py,px=np.nonzero(mask&search)
            z=depth[py,px]
            rays=np.linalg.solve(K,np.stack((px,py,np.ones(len(px)))))
            points=(T[:3,:3]@(rays*z)+T[:3,3,None]).T
            own=reject_own(points);mask[py[own],px[own]]=False;excluded=int(own.sum())
        labels,n=ndimage.label(mask&search)
        candidates=[];old_c=(self.box[:2]+self.box[2:])/2
        for i in range(1,n+1):
            ys,xs=np.nonzero(labels==i)
            if len(xs)<18:continue
            box=np.array([xs.min(),ys.min(),xs.max()+1,ys.max()+1],float)
            width,height=box[2:]-box[:2]
            if len(xs)>4500 or max(width,height)>150:continue
            if self.kind=='knob' and (len(xs)>1600 or width>70 or height>70):continue
            if self.anchor_stationary and (box[0]<=max(0,x0-margin) or box[1]<=max(0,y0-margin) or box[2]>=min(w,x1+margin) or box[3]>=min(h,y1+margin)):continue
            score=np.linalg.norm((box[:2]+box[2:])/2-old_c)-.008*len(xs)
            candidates.append((score,i,box))
        if not candidates:
            if self.track_selected:self.follow(gray,np.zeros((h,w),bool),depth,K,T)
            return dict(status='unknown',reason='No isolated current matching RGB component; no stale geometry reused.',own_bound_excluded_pixels=excluded),[]
        _,i,box=min(candidates,key=lambda v:v[0]);self.box=box
        ys,xs=np.nonzero(labels==i)
        # Select actual component pixels at quantiles, not silhouette-box centres.
        pixels=[]
        for f in (.15,.5,.85):
            y=float(np.quantile(ys,f));band=np.flatnonzero(abs(ys-y)<=max(2,(box[3]-box[1])*.08))
            if not len(band):continue
            for fx in ((.5,) if self.sparse else (.25,.5,.75)):
                j=band[np.argmin(abs(xs[band]-np.quantile(xs[band],fx)))]
                pixel=(int(xs[j]),int(ys[j]))
                if pixel not in pixels:pixels.append(pixel)
        samples=[]
        for u,v in pixels:
            z=float(depth[v,u]);xyz=T@np.r_[np.linalg.solve(K,[u,v,1])*z,1]
            if not np.isfinite(xyz).all() or z<=0:continue
            samples.append(dict(label='C'+str(len(samples)),pixel_uv=[u,v],
                visible_surface_world_mm=np.round(xyz[:3]*1000,1).tolist()))
        if self.track_selected:
            followed=self.follow(gray,labels==i,depth,K,T)
            if followed is not None:samples.append(followed)
            self.current_samples={sample["label"]:sample for sample in samples}
        return dict(status='candidate',bbox_xyxy=box.astype(int).tolist(),pixels=int(len(xs)),own_bound_excluded_pixels=excluded,
            meaning='Current colour component only. Use RGB to verify identity. Samples are visible surfaces, not the centre, grasp point, desired pose or contact evidence.',
            uncertainty='Colour segmentation may miss or merge parts. Occlusion invalidates identity; depth edges may mix surfaces. No precision guarantee.'),samples
