"""Three-task bounded retries, with shared approach and association improvements."""
import copy
import numpy as np
from task_controller import Controller as TaskController
from base_controller import bounded_quaternion,tool_quaternion
from visual_evidence import plain

class Controller(TaskController):
    def __init__(self,task,settings):
        super().__init__(task,settings)
        self.anchor_records={};self.preorient_count=0
    def _select(self):
        super()._select()
        if self.plan:
            oid=self.plan['source'];row=self.current.get(oid)
            if row and row['observed']:self.anchor_records[oid]=copy.deepcopy(row)
    def _get(self,oid,fresh=False):
        row=self.current.get(oid)
        if row and row['observed'] and row['uncertainty_m']<=.012:
            self.anchor_records[oid]=copy.deepcopy(row)
        ttl=self.rules.get('contact_anchor_ttl',0)
        if self.stage in ('contact','close') and oid in self.anchor_records:
            reference=self.anchor_records[oid];age=self.last_native-reference['native_step']
            if (row is None or not row['observed'] or row['uncertainty_m']>.025) and age<=ttl*5:
                result=copy.deepcopy(reference);result.update(observed=False,contact_reference=True,
                    source='short_lived_precontact_reference_NOT_current',age_steps=max(1,age//5))
                self.debug['contact_reference']=dict(id=oid,age_native_steps=age,ttl_native_steps=ttl*5,observed_now=False)
                return plain(result)
        return super()._get(oid,fresh=fresh)
    def _movement(self,targets,uncertainty,opening,obs,ask_jev):
        if self.stage=='approach' and self.rules.get('orient_before_approach'):
            commands={};angles={}
            for a in targets:
                q,angle=bounded_quaternion(self.robot[a]['quaternion'],self.plan['quaternions'][a]);angles[a]=angle
                commands[a]=dict(delta_xyz_m=[0.,0.,0.],quaternion_wxyz=q,gripper_opening=opening)
            if max(angles.values())>.12 and self.preorient_count<8:
                self.preorient_count+=1
                self.debug['preapproach_orientation']=dict(angles=angles,translation='none')
                return self._result(commands,reason='orient before descending toward observed target',ticks=3)
        return super()._movement(targets,uncertainty,opening,obs,ask_jev)
    def _targets(self):
        targets,u,g=super()._targets()
        if self.stage=='approach':
            old=.045 if self.task=='fold_clothes' else .055
            targets={a:np.asarray(p)+[0,0,self.rules['approach_clearance_m']-old] for a,p in targets.items()}
        if self.stage=='contact':targets={a:np.asarray(p)+[0,0,self.rules.get('grasp_depth_adjust_m',0.)] for a,p in targets.items()}
        return targets,u,g

    def step(self,observation,ask_jev,perceive):
        result=super().step(observation,ask_jev,perceive)
        if self.task=='match_and_pick_from_conveyor' and result['stage'].startswith('conveyor_wait_') and not result['stop']:
            arms={}
            for arm,r in self.robot.items():
                q,angle=bounded_quaternion(r['quaternion'],tool_quaternion([0,0,-1]))
                if angle>.10:arms[arm]=dict(delta_xyz_m=[0.,0.,0.],quaternion_wxyz=q,gripper_opening=1.)
            if arms:
                result['arms']=arms;result['reason']='observe conveyor while orienting at initial safe height'
        return plain(result)

    def _appearance_candidates(self,observation,measured):
        import cv2
        super()._appearance_candidates(observation,measured)
        for name,view in observation['cameras'].items():
            h,w=view['rgb'].shape[:2];rows=measured['views'][name]['objects']
            rows.sort(key=lambda r:0 if str(r.get('source','')).startswith('current RGB chroma') else 1)
            kept=[];masks=[]
            for row in rows:
                mask=np.zeros((h,w),np.uint8);poly=np.rint(np.asarray(row['polygon_uv01'])*[w-1,h-1]).astype(np.int32)
                cv2.fillPoly(mask,[poly],1)
                if any(row['category']==old['category'] and (mask&other).sum()/max(1,min(mask.sum(),other.sum()))>.65 for old,other in zip(kept,masks)):continue
                kept.append(row);masks.append(mask)
            measured['views'][name]['objects']=kept
