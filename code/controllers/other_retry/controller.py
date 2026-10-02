"""Three-task bounded retries, with shared approach and association improvements."""
import copy
import numpy as np
from task_controller import Controller as TaskController
from base_controller import bounded_quaternion,tool_quaternion
from visual_evidence import plain

class Controller(TaskController):
    def __init__(self,task,settings):
        super().__init__(task,settings)
        self.anchor_records={};self.anchor_poses={};self.preorient_count=0
        self.vision.settings['cloth_keypoint_inset_px']=self.rules.get('cloth_keypoint_inset_px',3.)
    def _select(self):
        self.preorient_count=0
        super()._select()
        if self.plan:
            for key,r in self.current.items():
                if r['observed']:self.anchor_records[key]=copy.deepcopy(r)
            oid=self.plan['source'];row=self.current.get(oid)
            if row and row['observed']:self.anchor_records[oid]=copy.deepcopy(row)
            if self.task in ('match_and_pick_from_conveyor','stack_bowls'):self.plan['lift_distance_m']=self.rules.get('lift_clearance_m',.12)
            if self.task=='match_and_pick_from_conveyor' and row is not None:
                size=row['high'][:2]-row['low'][:2]
                if min(size)/max(max(size),.001)>.8:
                    a=self.plan['arms'][0];self.plan['quaternions'][a]=tool_quaternion([0,0,-1])
    def _get(self,oid,fresh=False):
        row=self.current.get(oid)
        if row and row['observed'] and row['uncertainty_m']<=.012:
            self.anchor_records[oid]=copy.deepcopy(row)
            if self.plan and oid==self.plan['source']:
                a=self.plan['arms'][0];self.anchor_poses[oid]=copy.deepcopy(self.robot[a])
        if self.task=='stack_bowls' and self.plan and oid in (self.plan.get('destination'),self.plan.get('stack_base')) and oid in self.anchor_records:
            if row is None or not row['observed'] or row['uncertainty_m']>.025:
                ref=copy.deepcopy(self.anchor_records[oid]);ref.update(observed=False,source='last_observed_stationary_stack_target_NOT_current',age_steps=max(0,self.last_native-ref['native_step']))
                self.debug.setdefault('stack_target_memory',[]).append(dict(id=oid,observed_now=False,reference_native_step=ref['native_step']))
                return ref
        if self.task=='stack_bowls' and self.plan and self.plan.get('grasp_verified') and self.stage in ('transport','lower') and oid==self.plan['source'] and oid in self.anchor_poses:
            reference=self.anchor_records[oid];age=self.last_native-reference['native_step']
            if (row is None or not row['observed'] or row['uncertainty_m']>.025) and age<=20:
                from scipy.spatial.transform import Rotation
                a=self.plan['arms'][0];before=self.anchor_poses[oid];now=self.robot[a]
                q0=np.asarray(before['quaternion']);q1=np.asarray(now['quaternion'])
                rot=(Rotation.from_quat(q1[[1,2,3,0]])*Rotation.from_quat(q0[[1,2,3,0]]).inv()).as_matrix()
                ref=copy.deepcopy(reference)
                for key in ('center','top','low','high'):
                    ref[key]=rot@(np.asarray(reference[key])-before['grasp'])+now['grasp']
                ref.update(observed=False,age_steps=max(1,age//5),uncertainty_m=.01,source='brief_rigid_carry_prediction_NOT_current',carry_prediction=True)
                self.debug['carry_prediction']=dict(id=oid,age_native_steps=age,limit_native_steps=20,assumption='previously visually verified grasp remains attached')
                return ref
        ttl=self.rules.get('contact_anchor_ttl',0)
        if self.stage in ('contact','close') and oid in self.anchor_records:
            reference=self.anchor_records[oid];age=self.last_native-reference['native_step']
            if (row is None or not row['observed'] or row['uncertainty_m']>.025) and age<=ttl*5:
                result=copy.deepcopy(reference);result.update(observed=False,contact_reference=True,
                    source='short_lived_precontact_reference_NOT_current',age_steps=max(1,age//5))
                self.debug['contact_reference']=dict(id=oid,age_native_steps=age,ttl_native_steps=ttl*5,observed_now=False)
                return result
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
        if self.stage in ('approach','contact'):g=self.rules.get('pregrasp_opening',g)
        if self.task=='stack_bowls' and self.plan.get('grasp_verified') and self.stage in ('transport','lower'):
            arm=self.plan['arms'][0];source=self._get(self.plan['source'],fresh=True)
            measured=np.asarray(source['center']).copy()
            rim=source.get('measured_rim')
            if rim:measured[:2]=rim['center_xy']
            offset=self.robot[arm]['grasp']-measured
            targets={arm:np.asarray(targets[arm])+offset-self.plan['carry_offset']}
            self.plan['carry_offset']=offset
            self.plan['quaternions'][arm]=self.robot[arm]['quaternion'].copy()
            self.debug['carry_control']=dict(source='current visible object-to-grasp offset',keep_achieved_orientation=True,assumption='already visually verified grasp')
        if self.stage=='approach':
            old=.045 if self.task=='fold_clothes' else .055
            targets={a:np.asarray(p)+[0,0,self.rules['approach_clearance_m']-old] for a,p in targets.items()}
        if self.task=='fold_clothes' and self.stage in ('transport','lower'):
            height=self.plan['fold_height'] if self.stage=='transport' else .006
            targets={a:np.asarray(p)+[0,0,height] for a,p in self.plan['fold_destination'].items()}
            self.debug['fold_target_reference']='initial observed intended fold destination, not re-numbered live rectangle'
        if self.stage=='contact':targets={a:np.asarray(p)+[0,0,self.rules.get('grasp_depth_adjust_m',0.)] for a,p in targets.items()}
        return targets,u,g

    def step(self,observation,ask_jev,perceive):
        if self.stage=='return_home':return self._home(observation,ask_jev)
        result=super().step(observation,ask_jev,perceive)
        if self.task=='match_and_pick_from_conveyor' and result['stage'].startswith('conveyor_wait_') and not result['stop']:
            arms={}
            for arm,r in self.robot.items():
                q,angle=bounded_quaternion(r['quaternion'],tool_quaternion([0,0,-1]))
                if angle>.10:arms[arm]=dict(delta_xyz_m=[0.,0.,0.],quaternion_wxyz=q,gripper_opening=1.)
            if arms:
                result['arms']=arms;result['reason']='observe conveyor while orienting at initial safe height'
        if self.task in ('stack_bowls','fold_clothes') and result['stop'] and self.stage=='observed_operation_complete':
            self.stopped=False;self.stop_reason='';self.stage='return_home'
            return self._home(observation,ask_jev)
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

    def _fixed(self,opening,reason,ticks=5):
        if self.stage=='close' and self.rules.get('contact_dwell_ticks',0)>0 and not self.plan.get('contact_dwell_done'):
            self.plan['contact_dwell_done']=True;self.pending=None
            return super()._fixed(self.rules.get('pregrasp_opening',1.),'settle at depth-supported contact before closing',self.rules['contact_dwell_ticks'])
        if self.stage=='close':ticks=int(self.rules.get('close_ticks',ticks))
        return super()._fixed(opening,reason,ticks)
    def _verify_grasp(self):
        if self.task=='stack_bowls':
            row=self._get(self.plan['source'],fresh=True);base=self.plan['baseline'];arm=self.plan['arms'][0]
            points=np.asarray(row.get('surface_samples_m',[]));distance=float(np.min(np.linalg.norm(points-self.robot[arm]['grasp'],axis=1))) if points.size else 1.
            low_rise=float(row['low'][2]-base['low'][2]);robot_rise=float(self.robot[arm]['grasp'][2]-base['robot'][arm][2])
            evidence=dict(visible_bottom_rise_m=low_rise,robot_rise_m=robot_rise,visible_surface_to_grasp_m=distance,source='fresh depth above original support; allows rigid rotation')
            if low_rise>.020 and robot_rise>.030 and distance<.07:self.grasp_evidence.append(dict(native_step=self.last_native))
            else:self.grasp_evidence=[]
            return len(self.grasp_evidence)>=2,evidence
        if self.task!='fold_clothes':return super()._verify_grasp()
        row=self._get(self.plan['source'],fresh=True);points=np.asarray(row.get('surface_samples_m',[]));base=self.plan['baseline']
        if points.size==0:return False,dict(reason='no current garment depth samples')
        evidence={}
        for arm in self.plan['arms']:
            grasp=self.robot[arm]['grasp'];near=points[np.linalg.norm(points-grasp,axis=1)<.045]
            rise=float(np.quantile(near[:,2],.8)-base['center'][2]) if len(near)>=3 else None
            evidence[arm]=dict(current_cloth_samples_near_grasp=len(near),visible_rise_m=rise,
                robot_rise_m=float(grasp[2]-base['robot'][arm][2]),source='current segmented garment depth; no re-numbered corners')
        ok=all(e['visible_rise_m'] is not None and e['visible_rise_m']>.015 and e['robot_rise_m']>.02 for e in evidence.values())
        if ok:self.grasp_evidence.append(dict(native_step=self.last_native))
        else:self.grasp_evidence=[]
        return len(self.grasp_evidence)>=2,evidence

    def _deadzone(self,uncertainty):
        base=super()._deadzone(uncertainty)
        if self.task=='match_and_pick_from_conveyor' and self.stage=='approach' and self.plan:
            row=self.current.get(self.plan['source'])
            if row and row['observed']:
                width=float(min(row['high'][:2]-row['low'][:2]))
                return max(base,min(.020,.35*width))
        return base

    def _read_robot(self,observation):
        super()._read_robot(observation)
        if not hasattr(self,'initial_home'):
            self.initial_home={a:dict(position=r['grasp'].copy(),quaternion=r['quaternion'].copy()) for a,r in self.robot.items()}
    def _home(self,observation,ask_jev):
        self._read_robot(observation);self.last_native=observation['native_step'];self.remaining=observation['remaining_steps']
        geometry={a:dict(current_grasp_xyz_m=r['grasp'],target_xyz_m=self.initial_home[a]['position'],
            target_minus_grasp_m=self.initial_home[a]['position']-r['grasp'],uncertainty_m=0.) for a,r in self.robot.items()}
        quats={};angles={}
        for a,r in self.robot.items():quats[a],angles[a]=bounded_quaternion(r['quaternion'],self.initial_home[a]['quaternion'])
        aligned=all(np.max(np.abs(g['target_minus_grasp_m']))<.012 for g in geometry.values())
        if aligned and max(angles.values())<.12:return self._result(stop=True,reason='open-gripper initial pose reached; native evaluation only',ticks=1)
        answers={}
        if not aligned:
            state=plain(dict(task=self.task,stage='return_home',frame='environment_origin world axes',geometry=geometry,
                constraints=dict(dead_zone_m=.012,max_delta_norm_m=.04),reference_source='initial robot proprioception; no object truth'))
            questions={f'{a}_{x}':dict(type='choice',instructions=f'Choose the sign of {x} target minus current for {a} robot home waypoint; hold inside 0.012m.',criteria=dict(negative='decrease coordinate',hold='within dead zone',positive='increase coordinate')) for a in geometry for x in 'xyz'}
            answers=ask_jev(state,questions)['answers']
        commands={}
        for a,g in geometry.items():
            e=g['target_minus_grasp_m'];amp=np.minimum(.025,.7*np.abs(e));amp[np.abs(e)<.012]=0;delta=np.zeros(3)
            if not aligned:delta=amp*np.array([{'negative':-1,'hold':0,'positive':1}[answers[f'{a}_{x}']['choice']] for x in 'xyz'])
            delta*=min(1.,.04/max(np.linalg.norm(delta),1e-9))
            commands[a]=dict(delta_xyz_m=delta,quaternion_wxyz=quats[a],gripper_opening=1.)
        return self._result(commands,reason='return to own initial pose with open grippers',ticks=3)
