"""Multiview recovery around the archived controller; no hidden scene inputs."""
import copy
import numpy as np
from base_controller import Controller as Base, tool_quaternion
from visual_evidence import VisualEvidence, tokens


class MultiView:
    def __init__(self, settings):
        self.settings=settings; self.streams={}; self.tracks={}; self.next_id=0
        self.ttl=3; self.events=[]; self.last_cost={}; self.reference_camera='cam_high'
        self.call_index=0; self.last_semantic=0; self.surface_reobserve=False
        self.stage='select'; self.active_arm='right'; self.active_id=None; self.belt_map=None
        self.grasp_verified=False;self.cloth_reference_color=None

    def update(self, observation, perceive, force=False):
        self.call_index+=1; self.events=[]; candidates=[]; calls=0; seconds=0.
        names=list(observation['cameras'])
        if 'conveyor' in observation.get('instruction','').lower() and (self.stage=='select' or self.stage.startswith('conveyor_wait_')): names=['cam_high']
        # At contact both viewpoints are actually measured, not merely saved.
        preferred='cam_'+self.active_arm+'_wrist'
        for name in names:
            if name not in self.streams:
                self.streams[name]=VisualEvidence(dict(self.settings,reference_camera=name,max_perception_calls=100))
            stream=self.streams[name]
            stream.cloth_reference_color=self.cloth_reference_color
            one=dict(observation,cameras={name:observation['cameras'][name]})
            try:
                records=stream.update(one,perceive,force=force)
                calls+=int(stream.last_cost.get('called',False)); seconds+=stream.last_cost.get('seconds',0.)
                candidates.extend(copy.deepcopy(r) for r in records.values() if r['observed'])
                self.events.extend(dict(e,stream=name,kind='per_view_surface_rejected' if e.get('kind')=='surface_rejected' else e.get('kind')) for e in stream.events)
            except Exception as exc:
                self.events.append(dict(kind='view_unavailable',view=name,reason=str(exc)))
        self.last_cost=dict(called=bool(calls),calls=calls,seconds=seconds,source='local_multiview')
        self.last_semantic=self.call_index if calls else self.last_semantic
        old=self.tracks; current={}; consumed=set()
        for oid,prev in sorted(old.items(),key=lambda item:item[0]!=self.active_id):
            eligible=[]
            reference=np.asarray(prev['center'])
            predicted=False
            if oid==self.active_id and self.grasp_verified and self.stage in ('transport','lower') and prev.get('association_robot_grasp') is not None:
                from scipy.spatial.transform import Rotation
                i=0 if self.active_arm=='left' else 1
                q=np.asarray(observation['robot']['eef_quaternions_wxyz'][i])
                rotation=Rotation.from_quat(q[[1,2,3,0]]).as_matrix()
                grasp=np.asarray(observation['robot']['eef_positions'][i])+rotation[:,0]*observation['gripper_bias_m'][i]
                reference=reference+grasp-np.asarray(prev['association_robot_grasp'])
                predicted=True
            for j,row in enumerate(candidates):
                if j in consumed or row['category']!=prev['category']: continue
                noun=(tokens(row['label']) & tokens(prev['label']))-{'the','a','object','small','green'}
                distance=float(np.linalg.norm(row['center']-reference))
                generic={'the','a','object','small','toy'}
                generic_pair=not(tokens(row['label'])-generic) and not(tokens(prev['label'])-generic)
                if (not noun and not generic_pair) or distance>.09: continue
                if row['category']=='button':
                    colors={'red','blue','green','yellow'}
                    if (tokens(row['appearance'])&colors)!=(tokens(prev['appearance'])&colors):continue
                    if distance>.035:continue
                    if row['landmark_view']!=prev['landmark_view']:continue
                ca=np.asarray(row['color']);cb=np.asarray(prev['color'])
                if np.linalg.norm(ca/max(1,ca.sum())-cb/max(1,cb.sum()))>.22:continue
                if prev['category']=='cloth' and row['views']!=['cam_high']: continue
                # Preserve local identity when possible; reference changes are explicit.
                score=row['uncertainty_m'] + .05*distance
                if row['views']==prev['views']:score-=.006  # view hysteresis, no averaging of different surfaces
                if self.stage in ('contact','close','lift','verify_grasp') and preferred in row['views']: score-=.004
                eligible.append((score,j,row,distance))
            eligible.sort(key=lambda x:x[0])
            if eligible:
                _,j,row,distance=eligible[0]; consumed.add(j)
                # Only consume duplicate compatible views within observed bounds.
                for _,k,other,_ in eligible[1:]:
                    if set(other['views'])&set(row['views']): continue
                    consumed.add(k)
                dt=observation['native_step']-prev['native_step']
                if dt>0 and prev['observed'] and row['views']==prev['views']:
                    row['velocity_m_per_native_step']=(row['center']-prev['center'])/dt
                    row['velocity_observed']=True
                # On view changes keep only the per-camera tracker velocity already in row; never differentiate unlike surfaces.
                row.update(id=oid,age_steps=0,observed=True)
                current[oid]=row
                self.events.append(dict(kind='multiview_identity',id=oid,chosen_view=row['views'],
                    previous_view=prev['views'],center_distance_m=distance,other_candidates=len(eligible)-1,
                    association_reference='robot-motion hypothesis after visual grasp verification; CURRENT depth still required' if predicted else 'last visible surface',
                    source='label and calibrated metric gate; no centroid averaging'))
            else:  # preserve symbolic identity; never claim stale geometry is observed
                current[oid]=dict(prev,observed=False,age_steps=self.call_index-prev['global_seen'],
                    uncertainty_m=max(.026,prev['uncertainty_m']+.006),source='multiview_memory_NOT_current')
        for j,row in sorted(enumerate(candidates),key=lambda x:(x[1]['views']!=['cam_high'],x[1]['uncertainty_m'])):
            if j in consumed: continue
            if old and 'conveyor' not in observation.get('instruction','').lower(): continue
            if row['views']!=['cam_high']: continue  # establish identity once from overview
            duplicate=next((r for r in current.values() if r['category']==row['category'] and
                not set(r['views'])&set(row['views']) and (tokens(r['label'])&tokens(row['label']))-{'the','a','object','small'} and
                np.linalg.norm(r['center']-row['center'])<.12),None)
            if duplicate is not None: continue
            self.next_id+=1; oid='mv_%d'%self.next_id; row['id']=oid; current[oid]=row
        for r in current.values():
            if r['observed']:
                r['global_seen']=self.call_index
                if r['category']=='cloth' and r['views']==['cam_high'] and self.cloth_reference_color is None:
                    self.cloth_reference_color=np.asarray(r['color']).copy()
                if r['id']==self.active_id:
                    from scipy.spatial.transform import Rotation
                    i=0 if self.active_arm=='left' else 1
                    q=np.asarray(observation['robot']['eef_quaternions_wxyz'][i])
                    rotation=Rotation.from_quat(q[[1,2,3,0]]).as_matrix()
                    r['association_robot_grasp']=np.asarray(observation['robot']['eef_positions'][i])+rotation[:,0]*observation['gripper_bias_m'][i]
        if 'conveyor' in observation.get('instruction','').lower():
            fresh=[r for r in current.values() if r['category']=='conveyor' and r['observed']]
            if fresh: self.belt_map=copy.deepcopy(max(fresh,key=lambda r:r['samples']))
            elif self.belt_map is not None:
                remembered=dict(self.belt_map,observed=False,static_support_map=True,source='initial_static_belt_map_NOT_fresh',age_steps=self.call_index-self.belt_map['global_seen'])
                current[remembered['id']]=remembered
        self.tracks=current
        return current

    def support_height(self,near):
        values=[s.support_height(near) for s in self.streams.values()]
        values=[v for v in values if v is not None]
        return float(np.median(values)) if values else None
