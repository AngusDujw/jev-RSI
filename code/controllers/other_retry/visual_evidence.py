"""RGB semantics, finite visual memory, image tracking and calibrated depth.

No simulator imports, online file reads, network transport or hidden state.
Metric records describe visible surfaces, never complete object poses.
"""
import time
import re
from collections import deque
import cv2
import numpy as np


class EvidenceError(RuntimeError):
    pass


def plain(value):
    if isinstance(value,np.ndarray): return plain(value.tolist())
    if isinstance(value,np.generic): return plain(value.item())
    if isinstance(value,dict): return {str(k):plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple,deque)): return [plain(v) for v in value]
    if isinstance(value,float) and not np.isfinite(value): return None
    return value


def tokens(s):
    return set(re.findall(r'[a-z0-9]+',str(s).lower()))


def lift(view,origin):
    d=np.asarray(view['depth_m'],float); rgb=np.asarray(view['rgb'])
    k=np.asarray(view['intrinsic'],float); t=np.asarray(view['camera_to_world_opengl'],float)
    if d.ndim!=2 or rgb.shape!=(*d.shape,3) or k.shape!=(3,3) or t.shape!=(4,4):
        raise EvidenceError('invalid camera array shapes')
    if not np.isfinite(k).all() or not np.isfinite(t).all(): raise EvidenceError('nonfinite calibration')
    y,x=np.indices(d.shape)
    rays=np.stack([x,y,np.ones_like(x)],-1)@np.linalg.inv(k).T
    p=(rays*d[...,None]*[1,-1,-1])@t[:3,:3].T+t[:3,3]-origin
    p[(~np.isfinite(d))|(d<=0)]=np.nan
    return p


def patch_point(cloud,uv):
    h,w=cloud.shape[:2]; u,v=np.asarray(uv,float)
    if not np.isfinite([u,v]).all() or not (0<=u<=1 and 0<=v<=1):
        raise EvidenceError('invalid normalized keypoint')
    x,y=int(round(u*(w-1))),int(round(v*(h-1)))
    p=cloud[max(0,y-2):min(h,y+3),max(0,x-2):min(w,x+3)].reshape(-1,3)
    p=p[np.isfinite(p).all(1)]
    if len(p)<5: raise EvidenceError('keypoint has insufficient depth')
    median=np.median(p,axis=0); near=p[np.linalg.norm(p-median,axis=1)<.015]
    if len(near)<5: raise EvidenceError('keypoint straddles depth discontinuity')
    return np.median(near,axis=0)


PROMPT='''You are a restricted visual measurement service. Inspect ONLY the supplied reference-camera RGB image.
Return visible measurements only. NEVER output actions, goals, task roles, waypoints, directions,
stages, gripper decisions, solution sequences, hidden surfaces, object XYZ or physical truth.
Task language is provided only to disambiguate visible nouns and printed text.
Report manipulable items, bowls/containers, buttons, number cards, garment outlines, receptacles,
support/conveyor surfaces. Exclude robot links and grippers. Trace only visible outlines.
Separate every visible button and every number card. Transcribe card text exactly, even if it is
near a button. Do not put a card's number in a button's text unless printed on that button.
Describe the visible button color and object color/shape in appearance. Do not assign a card to a
button, infer a required count/order, or identify the object to pick. Those are policy decisions.
Omit unreadable text/landmarks; never guess missing digits. At most 24 records per camera.
For garments optionally mark visible left_cuff, right_cuff, left_shoulder, right_shoulder,
left_hem, right_hem; left/right refer to the garment as drawn in the image. For other objects
optional center/rim_center and visible corner keypoints are allowed. Do not infer occluded points.
Button polygons must lie inside the face, excluding the panel. Bowl polygons follow visible rim.
Confidence is a subjective visibility rating, not a calibrated probability.
Exact JSON (no extra fields):
{"views":{"CAMERA_NAME":{"objects":[
 {"category":"object|bowl|container|button|number_card|cloth|support|conveyor|reference",
  "label":"visible noun","appearance":"visible color/shape/pattern only",
  "text":"visible printed text or empty string","confidence":0.0,
  "polygon_uv01":[[0.0,0.0],[0.0,0.0],[0.0,0.0]],
  "keypoints":{"VISIBLE_LANDMARK_NAME":[0.0,0.0]}}
]}}}
Coordinates: normalized x right/y down in [0,1], first/last pixel centers at 0/1.
Use the actual supplied camera name; an empty objects list is valid when the scene is empty.
'''


class VisualEvidence:
    def __init__(self,settings):
        self.refresh=max(1,min(10,int(settings.get('semantic_refresh_steps',5))))
        self.ttl=max(1,min(8,int(settings.get('memory_ttl_steps',3))))
        self.max_calls=max(1,min(100,int(settings.get('max_perception_calls',45))))
        self.calls=0; self.seconds=0.; self.frames={}; self.image_records={}; self.tracks={}
        self.next_id=0; self.last_semantic=-1000; self.last_native=None; self.call_index=0
        self.events=[]; self.last_cost={}
        self.reference_camera=settings.get('reference_camera'); self.camera_history=[]

    def _parse(self,response,cameras):
        if not isinstance(response,dict) or not isinstance(response.get('views'),dict):
            raise EvidenceError('perception response missing views')
        records={}; categories={'object','bowl','container','button','number_card','cloth','support','conveyor','reference'}
        for name in cameras:
            view=response['views'].get(name)
            if not isinstance(view,dict) or not isinstance(view.get('objects'),list):
                raise EvidenceError('perception missing selected camera objects: '+str(name))
            rows=view['objects']; records[name]=[]
            for row in rows[:24]:
                try:
                    poly=np.asarray(row['polygon_uv01'],float); confidence=float(row['confidence'])
                    if poly.ndim!=2 or poly.shape[1]!=2 or not 3<=len(poly)<=96: continue
                    if not np.isfinite(poly).all() or np.any(poly<0) or np.any(poly>1): continue
                    if not np.isfinite(confidence) or not .25<=confidence<=1 or row['category'] not in categories: continue
                    keys={}
                    for k,v in row.get('keypoints',{}).items():
                        p=np.asarray(v,float)
                        if p.shape==(2,) and np.isfinite(p).all() and np.all((p>=0)&(p<=1)):
                            keys[str(k)[:40]]=p
                    records[name].append(dict(category=row['category'],label=str(row['label'])[:100],
                        appearance=str(row.get('appearance',''))[:180],text=str(row.get('text',''))[:80],
                        confidence=confidence,polygon=poly,keypoints=keys,
                        source='restricted_RGB_semantics_plus_current_depth',tracking_error_px=0.))
                except (TypeError,ValueError,KeyError,AttributeError): continue
            if rows and not records[name]: raise EvidenceError('all visible records malformed or below visibility threshold')
        return records

    @staticmethod
    def _inside(uv,poly,shape):
        h,w=shape
        return cv2.pointPolygonTest((poly*[w-1,h-1]).astype(np.float32),tuple((np.asarray(uv)*[w-1,h-1]).tolist()),False)>=0

    def _flow(self,name,gray,row):
        old=self.frames.get(name)
        if old is None or old.shape!=gray.shape: return None
        h,w=gray.shape; mask=np.zeros_like(gray)
        cv2.fillPoly(mask,[np.rint(row['polygon']*[w-1,h-1]).astype(np.int32)],255)
        features=cv2.goodFeaturesToTrack(old,maxCorners=60,qualityLevel=.01,minDistance=3,mask=mask)
        if features is None or len(features)<6: return None
        nxt,ok,_=cv2.calcOpticalFlowPyrLK(old,gray,features,None)
        if nxt is None: return None
        back,bok,_=cv2.calcOpticalFlowPyrLK(gray,old,nxt,None)
        if back is None: return None
        fb=np.linalg.norm(back-features,axis=2).ravel()
        good=ok.ravel().astype(bool)&bok.ravel().astype(bool)&(fb<1.2)
        if good.sum()<6: return None
        a,b=features[good].reshape(-1,2),nxt[good].reshape(-1,2)
        matrix,inliers=cv2.estimateAffinePartial2D(a,b,method=cv2.RANSAC,ransacReprojThreshold=2.)
        if matrix is None or inliers is None or inliers.sum()<6 or inliers.mean()<.65: return None
        if not .85<np.linalg.norm(matrix[:,0])<1.18: return None
        polygon=(row['polygon']*[w-1,h-1]@matrix[:,:2].T+matrix[:,2])/[w-1,h-1]
        if np.any(polygon<0) or np.any(polygon>1): return None
        # Landmark motion is measured locally, not copied from the rigid mask affine transform.
        keys={}; names=list(row['keypoints'])
        if names:
            p=np.asarray([row['keypoints'][k]*[w-1,h-1] for k in names],np.float32).reshape(-1,1,2)
            f,good1,_=cv2.calcOpticalFlowPyrLK(old,gray,p,None)
            if f is not None:
                back,good2,_=cv2.calcOpticalFlowPyrLK(gray,old,f,None)
                if back is not None:
                    for i,key in enumerate(names):
                        uv=f[i,0]/[w-1,h-1]
                        if good1[i,0] and good2[i,0] and np.linalg.norm(back[i,0]-p[i,0])<1.:
                            if np.isfinite(uv).all() and np.all((uv>=0)&(uv<=1)):
                                keys[key]=uv
        return dict(row,polygon=polygon,keypoints=keys,source='RGB_forward_backward_flow_plus_current_depth',
                    tracking_error_px=float(np.median(fb[good])))

    def _seed_corners(self,row,shape):
        if row['category']!='cloth' or any(k.startswith('tracked_corner_') for k in row['keypoints']): return
        h,w=shape; polygon=(row['polygon']*[w-1,h-1]).astype(np.float32)
        rectangle=cv2.boxPoints(cv2.minAreaRect(polygon))
        # Use observed outline vertices closest to fitted rectangle corners, inset toward the visible polygon center.
        chosen=[]; middle=np.mean(polygon,axis=0)
        for corner in rectangle:
            p=polygon[np.argmin(np.linalg.norm(polygon-corner,axis=1))]
            direction=middle-p; distance=np.linalg.norm(direction)
            p=p+direction*min(1.,3./max(distance,1e-6))
            chosen.append(p/[w-1,h-1])
        if min(np.linalg.norm(a-b) for i,a in enumerate(chosen) for b in chosen[i+1:])<.015: return
        for i,p in enumerate(chosen): row['keypoints'][f'tracked_corner_{i}']=p

    def _measure(self,name,row,cloud,rgb):
        # Keep the organized image: a 3-D quantile cannot distinguish an occluder.
        # No erosion: a visible one-pixel-wide surface may still have enough samples.
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        h,w=cloud.shape[:2]; mask=np.zeros((h,w),np.uint8)
        cv2.fillPoly(mask,[np.rint(row['polygon']*[w-1,h-1]).astype(np.int32)],1)
        mask=mask.astype(bool)&np.isfinite(cloud).all(-1)
        # Segment supports against its own previous measured appearance, never
        # an externally supplied object color. Reject foreground robot pixels.
        if row['category'] in ('cloth','bowl'):
            priors=[r for r in self.tracks.values() if r['category']==row['category'] and r['landmark_view']==name
                and self.call_index-r['measurement_index']<=self.ttl
                and np.linalg.norm(np.asarray(r['image_center_uv01'])-np.mean(row['polygon'],axis=0))<.12]
            if len(priors)==1:
                proto=np.asarray(priors[0]['color'],float); image=np.asarray(rgb,float)
                if row['category']=='cloth':
                    chroma=image/np.maximum(1.,image.sum(-1,keepdims=True)); ref=proto/max(1.,proto.sum())
                    mask &= np.linalg.norm(chroma-ref,axis=-1)<.14
                else:
                    mask &= image.mean(-1)>.4*proto.mean()
        before_robot=int(mask.sum())
        if hasattr(self,'robot_feedback'):
            from self_mask import robot_pixels
            mask &= ~robot_pixels(cloud,self.robot_feedback)
        robot_removed=before_robot-int(mask.sum())
        total=int(mask.sum())
        diagnostics=dict(camera=name,label=row['label'],category=row['category'],
                         appearance=row['appearance'],text=row['text'],
                         image_center_uv01=np.mean(row['polygon'],axis=0).tolist(),
                         polygon_samples=total,robot_pixels_removed=robot_removed,
                         method='organized_8_neighbor_metric_discontinuity_components')
        def reject(reason):
            self.surface_reobserve=True
            self.events.append(dict(kind='surface_rejected',reason=reason,observed=False,
                uncertainty_m=max(.05,float(diagnostics.get('surface_jump_m',0.))),
                **diagnostics))
            return None
        if total<12: return reject('insufficient current depth support')
        ids=np.full((h,w),-1,np.int32); ids[mask]=np.arange(total)
        points_all=cloud[mask]
        edges=[]; distances=[]
        # Eight neighbors preserve narrow diagonal outlines. Invalid pixels never bridge gaps.
        for dy,dx in ((0,1),(1,0),(1,1),(1,-1)):
            ya=slice(0,h-dy); yb=slice(dy,h)
            xa=slice(max(0,-dx),w-max(0,dx)); xb=slice(max(0,dx),w-max(0,-dx))
            a,b=ids[ya,xa],ids[yb,xb]; valid=(a>=0)&(b>=0)
            a,b=a[valid],b[valid]
            distance=np.linalg.norm(points_all[a]-points_all[b],axis=1)
            edges.append((a,b)); distances.append(distance)
        all_distances=np.concatenate(distances)
        if not len(all_distances): return reject('no organized surface neighbors')
        # This bounds local sample separation, not object height or tabletop distance.
        gap=float(np.clip(3.*np.median(all_distances),.006,.015))
        aa=np.concatenate([a[d<=gap] for (a,b),d in zip(edges,distances)])
        bb=np.concatenate([b[d<=gap] for (a,b),d in zip(edges,distances)])
        graph=coo_matrix((np.ones(len(aa),np.uint8),(aa,bb)),shape=(total,total)).tocsr()
        n,labels=connected_components(graph,directed=False)
        sizes=np.bincount(labels,minlength=n)
        if row['category']=='cloth':
            supported=sizes[labels]>=12
            labels=np.where(supported,0,1)
            sizes=np.bincount(labels,minlength=2);n=2
            diagnostics['garment_union_of_visible_components']=True
        components=np.flatnonzero(sizes>=12)
        diagnostics.update(neighbor_gap_m=gap,component_count=int(n),
            supported_component_sizes=sorted(sizes[components].tolist(),reverse=True)[:24])
        if not len(components): return reject('no connected component has 12 samples')
        # Associate a bounded prior using visible semantics and image location only.
        # It gates a CURRENT component; it is never returned as a new measurement.
        image_center=np.mean(row['polygon'],axis=0)
        prior_candidates=[]
        current_color=np.median(rgb[mask],axis=0).astype(float)
        current_chroma=current_color/max(1.,current_color.sum())
        for t in self.tracks.values():
            age=self.call_index-t['measurement_index']
            if age>self.ttl or t.get('landmark_view')!=name: continue
            if t['category']!=row['category'] or t['text'].strip().lower()!=row['text'].strip().lower(): continue
            if not tokens(t['label'])&tokens(row['label']): continue
            old_color=np.asarray(t['color'],float)
            if np.linalg.norm(current_chroma-old_color/max(1.,old_color.sum()))>.16:continue
            distance=float(np.linalg.norm(image_center-t['image_center_uv01']))
            if distance<.12: prior_candidates.append((distance,t['id'],t))
        prior_candidates.sort(key=lambda x:(x[0],x[1]))
        prior=None
        if prior_candidates:
            if len(prior_candidates)>1 and prior_candidates[1][0]-prior_candidates[0][0]<.02:
                return reject('ambiguous prior surface association')
            prior=prior_candidates[0][2]
        elif row['source'].startswith('RGB_forward_backward'):
            return reject('flow polygon has no unexpired measured surface; fresh RGB required')
        candidates=[]
        for component in components:
            p=points_all[labels==component]; center=np.median(p,axis=0)
            low,high=np.quantile(p,[.05,.95],axis=0)
            # Compute top only AFTER separating organized surfaces.
            topz=float(np.quantile(p[:,2],.90)); upper=p[p[:,2]>=topz-.004]
            top=upper[np.argmin(np.linalg.norm(upper-np.median(upper,axis=0),axis=1))].copy()
            shift=0.; shape_jump=0.
            if prior is not None:
                shift=float(np.linalg.norm(center-prior['center']))
                shape_jump=max(abs(float((top-center)[2]-(prior['top']-prior['center'])[2])),
                    float(np.max(np.maximum(0.,(high-low)-(prior['high']-prior['low'])))))
                # Finite observed dimensions allow tall bowls/cloth at acquisition and
                # coherent translation later. No absolute object-height assumption.
                age=self.call_index-prior['measurement_index']
                # Scale shape tolerance from previously VISIBLE dimensions. Large
                # garments may deform; thin objects retain a tight height gate.
                extent=np.asarray(prior['high'])-prior['low']
                shape_limit=.035+.20*float(np.linalg.norm(extent))
                height_growth=float((high[2]-low[2])-extent[2])
                height_limit=.025+.25*float(extent[2])
                if row['category']=='cloth': height_limit=shape_limit
                if shift>min(.09,.05+.012*age) or shape_jump>shape_limit or height_growth>height_limit:
                    diagnostics['surface_jump_m']=max(diagnostics.get('surface_jump_m',0.),shift,shape_jump,height_growth)
                    continue
            candidates.append((int(component),len(p),center,low,high,top,shift,shape_jump))
        if not candidates: return reject('all current surfaces violate finite observed position/shape gates')
        candidates.sort(key=lambda c:-c[1])
        selected=candidates[0]
        if prior is None:
            if selected[1]<.60*total:
                return reject('fresh polygon has no dominant coherent surface')
        elif len(candidates)>1 and candidates[1][1]>=.40*selected[1]:
            return reject('multiple prior-compatible surfaces; identity unresolved')
        component,count,center,lo,hi,top,shift,shape_jump=selected
        if count<max(12,.15*total): return reject('too little current surface remains visible')
        selected_mask=np.zeros((h,w),bool); selected_mask[mask]=labels==component
        points=cloud[selected_mask]; colors=rgb[selected_mask]
        _,_,v=np.linalg.svd((points-center)[::max(1,len(points)//1500)],full_matrices=False)
        normal=v[-1]
        if normal[2]<0: normal=-normal
        residual=np.abs((points-center)@normal)
        excluded=1.-count/total
        # Occlusion contributes error even when the retained surface is perfectly planar.
        # This is a conservative heuristic, not a calibrated confidence interval.
        error=max(.003,float(np.quantile(residual,.7))*.3+.002)+.025*excluded
        if prior is not None:
            diagnostics['shape_innovation_m']=float(shape_jump)
            diagnostics['shape_innovation_is_not_measurement_noise']=True
        diagnostics.update(selected_component=component,selected_samples=count,
            excluded_fraction=excluded,prior_id=None if prior is None else prior['id'],
            prior_age_steps=None if prior is None else self.call_index-prior['measurement_index'],
            uncertainty_m=float(error),uncertainty_is_calibrated=False)
        if error>.025:
            diagnostics.pop('uncertainty_m')
            return reject('retained surface uncertainty exceeds controller limit')
        keys={}
        # Landmarks must land on this same component, including the central pixel.
        # Neighboring robot depth cannot supply a missing/occluded cloth landmark.
        component_cloud=np.where(selected_mask[...,None],cloud,np.nan)
        for k,uv in row['keypoints'].items():
            x,y=np.rint(np.asarray(uv)*[w-1,h-1]).astype(int)
            if not selected_mask[y,x]: continue
            try: keys[k]=patch_point(component_cloud,uv)
            except EvidenceError: pass
        topz=float(np.quantile(points[:,2],.90)); top_points=points[points[:,2]>=topz-.004]
        measured_rim=None
        rim=[]
        if row['category']=='bowl':
            for axis,sign in ((0,-1),(0,1),(1,-1),(1,1)):
                rim.append(top_points[np.argmax(top_points[:,axis]*sign)].copy())
        if row['category']=='bowl' and len(points)>=30:
            xy=points[:,:2]; center_xy=np.median(xy,axis=0); radius=np.linalg.norm(xy-center_xy,axis=1)
            edge=xy[radius>=np.quantile(radius,.80)]
            matrix=np.c_[2*edge,np.ones(len(edge))]; rhs=np.sum(edge*edge,axis=1)
            fit=np.linalg.lstsq(matrix,rhs,rcond=None)[0]; rr=np.sqrt(max(0,fit[2]+np.sum(fit[:2]**2)))
            residual=float(np.median(np.abs(np.linalg.norm(edge-fit[:2],axis=1)-rr)))
            if .015<rr<.12 and residual<.008:
                measured_rim=dict(center_xy=fit[:2].tolist(),radius_m=float(rr),height_m=float(np.quantile(points[:,2],.96)),residual_m=residual,source='current RGB-D outer visible contour fit')
        corner_names=[f'tracked_corner_{i}' for i in range(4)]
        corners=[keys[k] for k in corner_names] if all(k in keys for k in corner_names) else []
        if row['category']=='cloth' and len(corners)!=4:
            rectangle=cv2.boxPoints(cv2.minAreaRect(points[:,:2].astype(np.float32)))
            middle=rectangle.mean(0); targets=.8*rectangle+.2*middle
            corners=[points[np.argmin(np.linalg.norm(points[:,:2]-xy,axis=1))].copy() for xy in targets]
            corner_names=['tracked_corner_%d'%i for i in range(4)]
            keys.update(dict(zip(corner_names,corners)))
        self.events.append(dict(kind='surface_component_measured',observed=True,**diagnostics))
        return dict(category=row['category'],label=row['label'],appearance=row['appearance'],text=row['text'],
            confidence=row['confidence'],image_center_uv01=image_center,
            image_polygon_uv01=row['polygon'].copy(),center=center,top=top,low=lo,high=hi,
            normal=normal,plane_residual_m=float(np.median(residual)),principal_axis=v[0],keypoints=keys,
            measured_rim=measured_rim,surface_samples_m=points[::max(1,len(points)//500)].tolist(),corners=corners,corner_names=corner_names if corners else [],rim_candidates=rim,color=np.median(colors,axis=0),
            uncertainty_m=error,views=[name],landmark_view=name,source=row['source']+'_coherent_surface_component',tracking_error_px=row['tracking_error_px'],
            samples=len(points),observed=True,measurement_index=self.call_index,native_step=self.last_native,
            semantic_age=self.call_index-self.last_semantic,surface_evidence=diagnostics)

    @staticmethod
    def _compatible(a,b):
        if a['category']!=b['category'] or a['text'].strip().lower()!=b['text'].strip().lower(): return False
        if not (tokens(a['label'])&tokens(b['label'])): return False
        ca,cb=np.asarray(a['color']),np.asarray(b['color'])
        return np.linalg.norm(ca/max(ca.sum(),1)-cb/max(cb.sum(),1))<.18

    def update(self,observation,perceive,force=False):
        self.call_index+=1; self.last_native=int(observation['native_step']); self.events=[]
        self.robot_feedback=observation['robot']
        available=observation['cameras']
        if not available: raise EvidenceError('no cameras')
        # One view for the entire measurement path, including forced semantic refresh.
        # A missing camera may trigger a documented fresh-view restart, never centroid fusion.
        if self.reference_camera not in available:
            previous=self.reference_camera
            self.reference_camera=min(available,key=lambda n:(
                0 if any(w in str(n).lower() for w in ('head','front','overhead')) else
                2 if any(w in str(n).lower() for w in ('wrist','hand')) else 1,str(n)))
            self.camera_history.append(dict(previous=previous,selected=self.reference_camera,
                native_step=self.last_native,reason='initial reference selection' if previous is None else 'reference unavailable; secondary reacquisition'))
            self.camera_history=self.camera_history[-4:]
            self.frames={}; self.image_records={}; self.tracks={}; force=True
        cameras={self.reference_camera:available[self.reference_camera]}
        self.events.append(dict(kind='reference_camera',selected=self.reference_camera,
            secondary_policy='only if reference unavailable; clear tracks; active identity must be re-established',
            history=self.camera_history))
        origin=np.asarray(observation['env_origin'],float)
        if origin.shape!=(3,) or not np.isfinite(origin).all(): raise EvidenceError('invalid environment origin')
        grays={}; clouds={}
        for name,view in cameras.items():
            clouds[name]=lift(view,origin)
            grays[name]=cv2.cvtColor(np.asarray(view['rgb'],np.uint8),cv2.COLOR_RGB2GRAY)
        flowed={}
        for name,gray in grays.items():
            flowed[name]=[]
            for row in self.image_records.get(name,[]):
                f=self._flow(name,gray,row)
                if f is not None: flowed[name].append(f)
        count=sum(map(len,self.image_records.values()))
        refresh=force or getattr(self,'surface_reobserve',False) or self.call_index-self.last_semantic>=self.refresh or count==0 or sum(map(len,flowed.values()))<max(1,count*.65)
        self.surface_reobserve=False
        records=flowed
        self.last_cost=dict(called=False,seconds=0.,total_calls=self.calls,total_seconds=self.seconds)
        if refresh:
            if self.calls>=self.max_calls: raise EvidenceError('restricted perception call budget exhausted')
            if perceive is None: raise EvidenceError('restricted RGB perception callback required for visible semantics')
            started=time.monotonic(); self.calls+=1
            try:
                payload={'instruction':str(observation.get('instruction',''))[:1500],
                         'cameras':{n:{'rgb':v['rgb']} for n,v in cameras.items()}}
                try:
                    response=perceive(PROMPT,payload)
                    records=self._parse(response,cameras)
                except Exception as exc:
                    # No JSON repair, missing-value fabrication, or reuse of old polygons.
                    self.frames={}; self.image_records={}
                    raise EvidenceError('restricted perception unavailable/malformed: '+type(exc).__name__+': '+str(exc)[:180]) from exc
            finally:
                elapsed=time.monotonic()-started; self.seconds+=elapsed
                self.last_cost=dict(called=True,seconds=elapsed,total_calls=self.calls,total_seconds=self.seconds,
                                    purpose='visible_2D_semantics_only',token_cost='callback_runner_accounting')
            self.last_semantic=self.call_index
            for name,rows in records.items():
                for row in rows:
                    if row['category']!='cloth': continue
                    # Preserve only locally tracked corner labels that still lie inside the fresh cloth mask.
                    center=np.mean(row['polygon'],axis=0)
                    matches=[r for r in flowed.get(name,[]) if r['category']=='cloth' and
                             np.linalg.norm(center-np.mean(r['polygon'],axis=0))<.08]
                    if len(matches)==1:
                        for key,uv in matches[0]['keypoints'].items():
                            if key.startswith('tracked_corner_') and self._inside(uv,row['polygon'],grays[name].shape):
                                row['keypoints'][key]=uv
                    # Only seed identities on the first observation; do not silently recreate lost corners later.
                    if not self.tracks: self._seed_corners(row,grays[name].shape)
        self.frames=grays; self.image_records=records
        measurements=[]
        for name,rows in records.items():
            for row in rows:
                m=self._measure(name,row,clouds[name],np.asarray(cameras[name]['rgb']))
                if m is not None: measurements.append(m)
        merged=[]
        # Prefer the previous landmark camera for a cloth identity; never mix camera-relative left/right names.
        def priority(r):
            preferred=any(t['category']=='cloth' and t.get('landmark_view')==r['landmark_view'] for t in self.tracks.values())
            return (0 if preferred else 1,r['uncertainty_m'])
        for m in sorted(measurements,key=priority):
            matches=[r for r in merged if not set(r['views'])&set(m['views']) and self._compatible(r,m)
                     and np.linalg.norm(r['center']-m['center'])<.025]
            if len(matches)==1:
                r=matches[0]; r['uncertainty_m']=max(r['uncertainty_m'],float(np.linalg.norm(r['center']-m['center'])))
                r['views']+=m['views']
            else: merged.append(m)
        old=self.tracks; proposals={}
        for i,m in enumerate(merged):
            candidates=[]
            for oid,t in old.items():
                if self.call_index-t['measurement_index']>self.ttl or not self._compatible(t,m): continue
                distance=float(np.linalg.norm(m['center']-t['center']))
                if distance<.10: candidates.append((distance,oid))
            candidates.sort()
            if candidates and (len(candidates)==1 or candidates[1][0]-candidates[0][0]>.018):
                proposals[i]=candidates[0][1]
            elif candidates:
                self.events.append(dict(kind='identity_ambiguous',candidates=[p[1] for p in candidates]))
        counts={oid:list(proposals.values()).count(oid) for oid in proposals.values()}; current={}
        for i,m in enumerate(merged):
            oid=proposals.get(i)
            if oid is None or counts[oid]!=1:
                self.next_id+=1; oid=f'visual_{self.next_id}'
            prev=old.get(oid); m['id']=oid; m['age_steps']=0
            m['velocity_m_per_native_step']=np.zeros(3); m['velocity_observed']=False
            if prev is not None and self.last_native>prev['native_step']:
                m['velocity_m_per_native_step']=(m['center']-prev['center'])/(self.last_native-prev['native_step'])
                m['velocity_observed']=prev['observed']
            current[oid]=m
        for oid,t in old.items():
            if oid not in current and self.call_index-t['measurement_index']<=self.ttl:
                age=self.call_index-t['measurement_index']
                current[oid]=dict(t,observed=False,age_steps=age,
                    uncertainty_m=max(.026,float(t['uncertainty_m'])+.006),
                    source='finite_visual_memory_NOT_current_observation')
                self.surface_reobserve=True
                self.events.append(dict(kind='surface_memory_only',id=oid,observed=False,
                    age_steps=age,ttl_steps=self.ttl,measurement_index=t['measurement_index'],
                    uncertainty_m=current[oid]['uncertainty_m'],
                    reason='no accepted current component; existing controller uncertainty guard holds/reobserves'))
        self.tracks=current
        return current

    def support_height(self,near):
        surfaces=[r for r in self.tracks.values() if r['observed'] and r['category'] in ('support','conveyor')
                  and abs(r['normal'][2])>.85 and r['plane_residual_m']<.012
                  and np.all(np.asarray(near)[:2]>=r['low'][:2]-.03) and np.all(np.asarray(near)[:2]<=r['high'][:2]+.03)]
        if not surfaces: return None
        return float(min(surfaces,key=lambda r:abs(r['center'][2]-near[2]))['center'][2])
