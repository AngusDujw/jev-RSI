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
        self.stage='select'; self.active_arm='right'; self.active_id=None

    def update(self, observation, perceive, force=False):
        self.call_index+=1; self.events=[]; candidates=[]; calls=0; seconds=0.
        names=list(observation['cameras'])
        # At contact both viewpoints are actually measured, not merely saved.
        preferred='cam_'+self.active_arm+'_wrist'
        for name in names:
            if name not in self.streams:
                self.streams[name]=VisualEvidence(dict(self.settings,reference_camera=name))
            stream=self.streams[name]
            one=dict(observation,cameras={name:observation['cameras'][name]})
            try:
                records=stream.update(one,perceive,force=force)
                calls+=int(stream.last_cost.get('called',False)); seconds+=stream.last_cost.get('seconds',0.)
                candidates.extend(copy.deepcopy(r) for r in records.values() if r['observed'])
                self.events.extend(dict(e,stream=name) for e in stream.events if e.get('kind')!='surface_rejected')
            except Exception as exc:
                self.events.append(dict(kind='view_unavailable',view=name,reason=str(exc)))
        self.last_cost=dict(called=bool(calls),calls=calls,seconds=seconds,source='local_multiview')
        self.last_semantic=self.call_index if calls else self.last_semantic
        old=self.tracks; current={}; consumed=set()
        for oid,prev in old.items():
            eligible=[]
            for j,row in enumerate(candidates):
                if j in consumed or row['category']!=prev['category']: continue
                noun=(tokens(row['label']) & tokens(prev['label']))-{'the','a','object','small','green'}
                distance=float(np.linalg.norm(row['center']-prev['center']))
                if not noun or distance>.12: continue
                if self.active_id is not None and oid!=self.active_id and row['views']!=['cam_high']: continue
                # Preserve local identity when possible; reference changes are explicit.
                score=row['uncertainty_m'] + .05*distance
                if self.stage in ('contact','close','lift','verify_grasp') and preferred in row['views']: score-=.004
                eligible.append((score,j,row,distance))
            eligible.sort(key=lambda x:x[0])
            if eligible:
                _,j,row,distance=eligible[0]; consumed.add(j)
                # Only consume duplicate compatible views within observed bounds.
                for _,k,other,_ in eligible[1:]:
                    if set(other['views'])&set(row['views']): continue
                    consumed.add(k)
                row.update(id=oid,age_steps=0,observed=True)
                current[oid]=row
                self.events.append(dict(kind='multiview_identity',id=oid,chosen_view=row['views'],
                    previous_view=prev['views'],center_distance_m=distance,other_candidates=len(eligible)-1,
                    source='label and calibrated metric gate; no centroid averaging'))
            elif self.call_index-prev.get('global_seen',0)<=self.ttl:
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
            if r['observed']: r['global_seen']=self.call_index
        self.tracks=current
        return current

    def support_height(self,near):
        values=[s.support_height(near) for s in self.streams.values()]
        values=[v for v in values if v is not None]
        return float(np.median(values)) if values else None


class Controller(Base):
    def __init__(self,task,settings):
        super().__init__(task,settings)
        self.vision=MultiView(settings)
    def step(self,observation,ask_jev,perceive):
        self.vision.stage=self.stage
        if self.plan:
            self.vision.active_arm=self.plan['arms'][0]
            self.vision.active_id=self.plan['source']
        return super().step(observation,ask_jev,perceive)

    def _targets(self):
        targets,uncertainty,opening=super()._targets()
        if self.task in ('general_pickup','stack_bowls') and self.stage in ('approach','contact'):
            # Static pregrasp landmark comes from first measured surface, not a
            # changing partial-view top quantile. Current views verify visibility.
            anchor=np.asarray(self.plan['initial_grasp']).copy()
            anchor[2]+=.004
            arm=self.plan['arms'][0]
            targets={arm:anchor+np.array([0,0,.055 if self.stage=='approach' else 0])}
            self.debug['grasp_reference']=dict(source='initial visual grasp landmark; current multiview visibility required',
                point=anchor.tolist(),not_current_surface_centroid=True)
        return targets,uncertainty,opening

    def _select(self):
        super()._select()
        if self.task=='stack_bowls' and self.plan:
            a=self.plan['arms'][0]; r=self.current[self.plan['source']]
            radial=np.asarray(self.plan['initial_grasp'])-r['center']; radial[2]=0.
            if np.linalg.norm(radial)>.005:
                self.plan['quaternions'][a]=tool_quaternion([0,0,-1],radial)

    def _grasp_point(self,row,arm):
        point=super()._grasp_point(row,arm)
        if row['category']=='bowl': point[2]-=min(.015,.25*float(row['high'][2]-row['low'][2]))
        return point
