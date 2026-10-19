"""Current RGB colour components and RGB-D samples, never scene model state.

The initial identity window only seeds image-space tracking. Each observation
must independently contain matching pixels; occlusion never propagates old XYZ.
These are visible-surface candidates, not object centres or grasp targets.
"""
import numpy as np
from scipy import ndimage


class SurfaceTracker:
    def __init__(self, kind, initial_box, sparse=False, anchor_stationary=False, track_selected=False, raised_feature=False, shape_features=False, central_samples=False, prefer_largest=False):
        self.kind=kind
        self.shape_features=shape_features
        self.central_samples=central_samples
        self.prefer_largest=prefer_largest
        self.box=np.asarray(initial_box,float)
        self.initial_box=self.box.copy()
        self.sparse=sparse
        self.anchor_stationary=anchor_stationary
        self.raised_feature=raised_feature
        self.track_selected=track_selected
        self.selected_pixel=None
        self.selected_world=None
        self.reference_origin=None
        self.previous_gray=None
        self.current_samples={}

    def select(self,label):
        sample=self.current_samples.get(label)
        if sample is not None and self.track_selected:
            self.selected_pixel=np.array(sample["pixel_uv"],np.float32).reshape(1,1,2)
            self.selected_world=np.array(sample["visible_surface_world_mm"],float)
            if label!="S":self.reference_origin=self.selected_world.copy()

    def follow(self,gray,allowed,depth,K,T):
        """A current RGB correspondence, never a propagated historical XYZ."""
        import cv2
        old=self.previous_gray;point=self.selected_pixel
        previous_world=self.selected_world;origin=self.reference_origin
        self.previous_gray=gray.copy()
        self.selected_pixel=None
        self.selected_world=None
        self.reference_origin=None
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
        self.selected_world=xyz[:3]*1000
        self.reference_origin=origin
        return dict(matched_feature_change_world_mm=np.round(self.selected_world-previous_world,1).tolist() if previous_world is not None else None,
            matched_feature_change_since_selection_mm=np.round(self.selected_world-origin,1).tolist() if origin is not None else None,
            label="S",pixel_uv=[int(u),int(v)],visible_surface_world_mm=np.round(xyz[:3]*1000,1).tolist(),
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
        elif self.kind=='rack':
            mask=(r>g*1.12)&(r<g*1.8)&(g>b*1.1)&(r>45)&(r<210)
            margin=8
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
            if len(xs)>(25000 if self.kind=='rack' else 4500) or max(width,height)>(300 if self.kind=='rack' else 150):continue
            if self.kind=='knob' and (len(xs)>1600 or width>70 or height>70):continue
            if self.anchor_stationary and (box[0]<=max(0,x0-margin) or box[1]<=max(0,y0-margin) or box[2]>=min(w,x1+margin) or box[3]>=min(h,y1+margin)):continue
            score=np.linalg.norm((box[:2]+box[2:])/2-old_c)-.008*len(xs)
            if self.prefer_largest:score=-len(xs)
            if self.raised_feature:
                z=depth[ys,xs];points=T[:3,:3]@(np.linalg.solve(K,np.stack((xs,ys,np.ones(len(xs)))))*z)+T[:3,3,None]
                valid=np.isfinite(points).all(axis=0)&(z>0)
                if valid.sum()<18:continue
                score=(-float(np.percentile(points[2,valid],95)),score)
            candidates.append((score,i,box))
        if not candidates:
            if self.track_selected:self.follow(gray,np.zeros((h,w),bool),depth,K,T)
            return dict(status='unknown',reason='No isolated current matching RGB component; no stale geometry reused.',own_bound_excluded_pixels=excluded),[]
        _,i,box=min(candidates,key=lambda v:v[0]);self.box=box
        ys,xs=np.nonzero(labels==i)
        component_pixels=len(xs)
        shape=None
        if self.shape_features:
            from libero_visible_shape import describe_visible_shape
            z=depth[ys,xs]
            points=T[:3,:3]@(np.linalg.solve(K,np.stack((xs,ys,np.ones(len(xs)))))*z)+T[:3,3,None]
            valid=np.isfinite(points).all(axis=0)&(z>0)
            shape=describe_visible_shape(points[:,valid].T*1000,self.kind)
        if self.raised_feature:
            z=depth[ys,xs];points=T[:3,:3]@(np.linalg.solve(K,np.stack((xs,ys,np.ones(len(xs)))))*z)+T[:3,3,None]
            valid=np.isfinite(points).all(axis=0)&(z>0)
            height=points[2];upper=valid&(height>=np.percentile(height[valid],90))&(height<=np.percentile(height[valid],99.5))
            if upper.sum()>=3:ys,xs=ys[upper],xs[upper]
        # Select actual component pixels at quantiles, not silhouette-box centres.
        pixels=[]
        for f in ((.5,) if self.raised_feature else (.15,.5,.85)):
            y=float(np.quantile(ys,f));band=np.flatnonzero(abs(ys-y)<=max(2,(box[3]-box[1])*.08))
            if not len(band):continue
            for fx in ((.25,.5,.75) if self.raised_feature else (.5,) if self.sparse else (.25,.5,.75)):
                j=band[np.argmin(abs(xs[band]-np.quantile(xs[band],fx)))]
                pixel=(int(xs[j]),int(ys[j]))
                if pixel not in pixels:pixels.append(pixel)
        central_notes={}
        if self.raised_feature and self.central_samples and len(xs)>=18:
            z=depth[ys,xs]
            xyz=(T[:3,:3]@(np.linalg.solve(K,np.stack((xs,ys,np.ones(len(xs)))))*z)+T[:3,3,None]).T*1000
            valid=np.isfinite(xyz).all(axis=1)&(z>0)
            cloud=xyz[valid];py=ys[valid];px=xs[valid]
            if len(cloud)>=18:
                middle=np.median(cloud,axis=0)
                _,_,axes=np.linalg.svd(cloud-middle,full_matrices=False)
                along=(cloud-middle)@axes[0]
                for fraction,note in ((.5,'Middle of the CURRENT visible upper-fin surface extent, not a known shaft pivot.'),
                                      (.25,'Inner-quarter point of the CURRENT visible upper-fin surface.'),
                                      (.75,'Other inner-quarter point of the CURRENT visible upper-fin surface.')):
                    target=middle+axes[0]*np.quantile(along,fraction)
                    j=int(np.argmin(np.linalg.norm(cloud-target,axis=1)))
                    pixel=(int(px[j]),int(py[j]))
                    if pixel not in pixels:pixels.append(pixel)
                    central_notes.setdefault(pixel,note)
        samples=[]
        for u,v in pixels:
            z=float(depth[v,u]);xyz=T@np.r_[np.linalg.solve(K,[u,v,1])*z,1]
            if not np.isfinite(xyz).all() or z<=0:continue
            samples.append(dict(label='C'+str(len(samples)),pixel_uv=[u,v],
                visible_surface_world_mm=np.round(xyz[:3]*1000,1).tolist(),
                **({'visible_part_note':central_notes[(u,v)]} if (u,v) in central_notes else {})))
        if self.track_selected:
            allowed=labels==i
            if self.raised_feature:
                allowed=np.zeros((h,w),bool);allowed[ys,xs]=True
            followed=self.follow(gray,allowed,depth,K,T)
            if followed is not None:samples.append(followed)
            self.current_samples={sample["label"]:sample for sample in samples}
        return dict(status='candidate',visible_shape=shape,bbox_xyxy=box.astype(int).tolist(),pixels=int(component_pixels),upper_visible_feature_pixels=int(len(xs)) if self.raised_feature else None,own_bound_excluded_pixels=excluded,
            meaning=('Current higher visible black surface proposal inside the knob identity window. Verify raised fin versus base/robot from RGB; only current RGB-D is used, never a true object pose or grasp target.' if self.raised_feature else 'Current colour component only. Use RGB to verify identity. Samples are visible surfaces, not the centre, grasp point, desired pose or contact evidence.'),
            uncertainty='Colour segmentation may miss or merge parts. Occlusion invalidates identity; depth edges may mix surfaces. No precision guarantee.'),samples
