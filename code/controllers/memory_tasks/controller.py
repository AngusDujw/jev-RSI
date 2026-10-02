"""Same task execution infrastructure with or without frozen historical advice."""
from pathlib import Path
import numpy as np
from base_controller import Controller as Base,tool_quaternion,EvidenceError
from multiview import MultiView
from experience import Experience

class Controller(Base):
    def __init__(self,task,settings):
        super().__init__(task,settings)
        self.vision=MultiView(settings)
        self.memory=Experience(Path(__file__).resolve().parents[2]/'experience/task_transfer',settings['run_dir'],task,settings.get('experience_enabled',False))
        self.rules=self.memory.rules();self.feedback=None;self.press_stall=0
    def step(self,observation,ask_jev,perceive):
        self.vision.stage=self.stage
        if self.plan:self.vision.active_arm=self.plan['arms'][0];self.vision.active_id=self.plan['source']
        def query(state,questions):
            used=self.memory.retrieve(state['stage'])
            if used:state['experience_memory']=[dict(id=r['id'],lesson=r['content'],sha256=r['sha256']) for r in used]
            self.memory.record(state,used)
            return ask_jev(state,questions)
        result=super().step(observation,query,perceive)
        if result['stage'].startswith('conveyor_wait_') and not result['stop']:
            result['ticks']=min(self.remaining,int(self.rules.get('wait_ticks',3)))
        return result
    def _after_motion(self):
        self.feedback=None
        if self.last_motion:
            self.feedback=dict(stage=self.last_motion['stage'],arms={a:dict(actual=self.robot[a]['grasp']-before,command=self.last_motion['delta'][a]) for a,before in self.last_motion['grasp'].items()})
        super()._after_motion()
    def _movement(self,targets,uncertainty,opening,obs,ask_jev):
        if self.rules.get('contact_endstop') and self.stage=='press_stroke' and self.feedback and self.feedback['stage']=='press_stroke':
            a=self.plan['arms'][0];f=self.feedback['arms'][a];normal=self.plan['normal']
            actual=abs(float(np.dot(f['actual'],normal)));command=abs(float(np.dot(f['command'],normal)))
            self.press_stall=self.press_stall+1 if command>.002 and actual<.0015 else 0
            if self.press_stall>=2:
                self._transition('press_retract',dict(memory='press-feedback',normal_actual_m=actual,normal_command_m=command,activation_verified=False))
                self.press_stall=0;targets,uncertainty,opening=self._targets()
        result=super()._movement(targets,uncertainty,opening,obs,ask_jev)
        if result and self.stage=='press_stroke' and result.get('arms') and self.rules.get('stroke_ticks'):
            result['ticks']=min(self.remaining,int(self.rules['stroke_ticks']))
        return result
    def _press_sequence(self,instruction,rows):
        # Current episode OCR instruction is not historical experience.
        if self.sequence is not None:return self.sequence
        return super()._press_sequence(instruction,rows)
    def _select(self):
        super()._select()
        if self.plan and self.task=='stack_bowls' and self.rules.get('rim_circle'):
            arm=self.plan['arms'][0];r=self.current[self.plan['source']]
            radial=self.plan['initial_grasp']-r['center'];radial[2]=0
            if np.linalg.norm(radial)>.005:self.plan['quaternions'][arm]=tool_quaternion([0,0,-1],radial)
    def _grasp_point(self,row,arm):
        p=super()._grasp_point(row,arm)
        if row['category']=='bowl' and self.rules.get('rim_circle'):
            rim=row.get('measured_rim')
            if rim:
                center=np.array(rim['center_xy']);direction=self.robot[arm]['grasp'][:2]-center;direction/=max(np.linalg.norm(direction),1e-9)
                p=np.r_[center+direction*rim['radius_m'],rim['height_m']-self.rules['rim_insertion_m']]
                self.debug['rim_grasp_evidence']=rim
        return p
    def _targets(self):
        targets,u,g=super()._targets()
        if self.task=='stack_bowls' and self.rules.get('rim_circle') and self.stage in ('approach','contact'):
            a=self.plan['arms'][0];targets={a:self.plan['initial_grasp']+np.array([0,0,.055 if self.stage=='approach' else 0])}
        if self.task=='fold_clothes' and self.rules.get('cloth_keypoint_anchor') and self.stage in ('approach','contact'):
            self._get(self.plan['source'],fresh=True)
            targets={a:p+np.array([0,0,.045 if self.stage=='approach' else 0]) for a,p in self.plan['fold_source'].items()}
            self.debug['experience_reference']='initial garment landmark, not new centroid; fresh cloth required'
        return targets,u,g
