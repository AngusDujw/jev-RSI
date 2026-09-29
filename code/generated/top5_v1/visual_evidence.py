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


PROMPT='''You are a restricted visual measurement service. Inspect ONLY supplied camera RGB images.
Return visible measurements only. NEVER output actions, goals, task roles, waypoints, directions,
stages, gripper decisions, solution sequences, hidden surfaces, object XYZ or physical truth.
Task language is provided only to disambiguate visible nouns and printed text.
Report manipulable items, bowls/containers, printed buttons, garment outlines, visible receptacles,
reference pictures/patterns, support/conveyor surfaces. Exclude robot links and grippers.
Each view is independent. Do not invent cross-camera IDs. Trace only visible outlines; omit an
unreadable label/landmark. Separate every visible button and transcribe numbers exactly. Never
infer missing numbers or the required order. At most 24 records per camera.
For garments, optionally mark visible left_cuff, right_cuff, left_shoulder, right_shoulder,
left_hem, right_hem; left/right refer to the garment as drawn in the image. Do not infer occluded
landmarks. For other objects optional center/rim_center and visible corner keypoints are allowed.
Button polygons must lie inside the button face, excluding the panel. Bowl polygons follow visible rim.
Confidence is a subjective visibility rating, not a calibrated probability.
Exact JSON (no extra fields):
{"views":{"CAMERA_NAME":{"objects":[
 {"category":"object|bowl|container|button|cloth|support|conveyor|reference",
  "label":"visible noun","appearance":"visible color/shape/pattern only",
  "text":"visible printed text or empty string","confidence":0.0,
  "polygon_uv01":[[0.0,0.0],[0.0,0.0],[0.0,0.0]],
  "keypoints":{"VISIBLE_LANDMARK_NAME":[0.0,0.0]}}
]}}}
Coordinates: normalized x right/y down in [0,1], first/last pixel centers at 0/1.
Use actual camera names; empty lists are valid.
'''


class VisualEvidence:
    def __init__(self,settings):
        self.refresh=max(1,min(10,int(settings.get('semantic_refresh_steps',5))))
        self.ttl=max(1,min(8,int(settings.get('memory_ttl_steps',3))))
        self.max_calls=max(1,min(100,int(settings.get('max_perception_calls',45))))
        self.calls=0; self.seconds=0.; self.frames={}; self.image_records={}; self.tracks={}
        self.next_id=0; self.last_semantic=-1000; self.last_native=None; self.call_index=0
        self.events=[]; self.last_cost={}

    def _parse(self,response,cameras):
        if not isinstance(response,dict) or not isinstance(response.get('views'),dict):
            raise EvidenceError('perception response missing views')
        records={}; categories={'object','bowl','container','button','cloth','support','conveyor','reference'}
        for name in cameras:
            view=response['views'].get(name,{})
            rows=view.get('objects',[]) if isinstance(view,dict) else []
            if not isinstance(rows,list): raise EvidenceError('perception objects must be lists')
            records[name]=[]
            for row in rows[:24]:
                try:
                    poly=np.asarray(row['polygon_uv01'],float); confidence=float(row['confidence'])
                    if poly.ndim!=2 or poly.shape[1]!=2 or not 3<=len(poly)<=96: continue
                    if not np.isfinite(poly).all() or np.any(poly<0) or np.any(poly>1): continue
                    if not np.isfinite(confidence) or not .5<=confidence<=1 or row['category'] not in categories: continue
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
        h,w=cloud.shape[:2]; mask=np.zeros((h,w),np.uint8)
        cv2.fillPoly(mask,[np.rint(row['polygon']*[w-1,h-1]).astype(np.int32)],1)
        mask=cv2.erode(mask,np.ones((3,3),np.uint8)).astype(bool)&np.isfinite(cloud).all(-1)
        points=cloud[mask]; colors=rgb[mask]
        if len(points)<16: return None
        lo,hi=np.quantile(points,[.05,.95],axis=0)
        keep=((points>=lo-.005)&(points<=hi+.005)).all(1); points,colors=points[keep],colors[keep]
        if len(points)<12: return None
        center=np.median(points,axis=0)
        _,_,v=np.linalg.svd((points-center)[::max(1,len(points)//1500)],full_matrices=False)
        normal=v[-1]
        if normal[2]<0: normal=-normal
        residual=np.abs((points-center)@normal)
        error=max(.003,min(.035,float(np.quantile(residual,.7))*.3+.002))
        keys={}
        for k,uv in row['keypoints'].items():
            try:
                point=patch_point(cloud,uv)
                if np.all(point>=lo-.025) and np.all(point<=hi+.025): keys[k]=point
            except EvidenceError: pass
        topz=float(np.quantile(points[:,2],.90)); top_points=points[points[:,2]>=topz-.004]
        top=np.r_[np.median(top_points[:,:2],axis=0),topz]
        rim=[]
        if row['category']=='bowl':
            for axis,sign in ((0,-1),(0,1),(1,-1),(1,1)):
                rim.append(top_points[np.argmax(top_points[:,axis]*sign)].copy())
        corner_names=[f'tracked_corner_{i}' for i in range(4)]
        corners=[keys[k] for k in corner_names] if all(k in keys for k in corner_names) else []
        return dict(category=row['category'],label=row['label'],appearance=row['appearance'],text=row['text'],
            confidence=row['confidence'],center=center,top=top,low=np.quantile(points,.05,axis=0),high=np.quantile(points,.95,axis=0),
            normal=normal,plane_residual_m=float(np.median(residual)),principal_axis=v[0],keypoints=keys,
            corners=corners,corner_names=corner_names if corners else [],rim_candidates=rim,color=np.median(colors,axis=0),
            uncertainty_m=error,views=[name],landmark_view=name,source=row['source'],tracking_error_px=row['tracking_error_px'],
            samples=len(points),observed=True,measurement_index=self.call_index,native_step=self.last_native,
            semantic_age=self.call_index-self.last_semantic)

    @staticmethod
    def _compatible(a,b):
        if a['category']!=b['category'] or a['text'].strip().lower()!=b['text'].strip().lower(): return False
        if not (tokens(a['label'])&tokens(b['label'])): return False
        ca,cb=np.asarray(a['color']),np.asarray(b['color'])
        return np.linalg.norm(ca/max(ca.sum(),1)-cb/max(cb.sum(),1))<.18

    def update(self,observation,perceive,force=False):
        self.call_index+=1; self.last_native=int(observation['native_step']); self.events=[]
        cameras=observation['cameras']
        if not cameras: raise EvidenceError('no cameras')
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
        refresh=force or self.call_index-self.last_semantic>=self.refresh or count==0 or sum(map(len,flowed.values()))<max(1,count*.65)
        records=flowed
        self.last_cost=dict(called=False,seconds=0.,total_calls=self.calls,total_seconds=self.seconds)
        if refresh:
            if self.calls>=self.max_calls: raise EvidenceError('restricted perception call budget exhausted')
            if perceive is None: raise EvidenceError('restricted RGB perception callback required for visible semantics')
            started=time.monotonic(); self.calls+=1
            try:
                payload={'instruction':str(observation.get('instruction',''))[:1500],
                         'cameras':{n:{'rgb':v['rgb']} for n,v in cameras.items()}}
                records=self._parse(perceive(PROMPT,payload),cameras)
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
                current[oid]=dict(t,observed=False,age_steps=self.call_index-t['measurement_index'],
                                  source='finite_visual_memory_NOT_current_observation')
        self.tracks=current
        return current

    def support_height(self,near):
        surfaces=[r for r in self.tracks.values() if r['observed'] and r['category'] in ('support','conveyor')
                  and abs(r['normal'][2])>.85 and r['plane_residual_m']<.012
                  and np.all(np.asarray(near)[:2]>=r['low'][:2]-.03) and np.all(np.asarray(near)[:2]<=r['high'][:2]+.03)]
        if not surfaces: return None
        return float(min(surfaces,key=lambda r:abs(r['center'][2]-near[2]))['center'][2])
