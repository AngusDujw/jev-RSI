"""Task adapter + reusable observation memory; no runtime GPT-6."""
from pathlib import Path
import numpy as np
from base_controller import Controller as Base
from multiview import MultiView
from experience import Experience

class Controller(Base):
    def __init__(self,task,settings):
        if task!='general_pickup': raise ValueError('This evaluation adapter supports pickup only; core generality unproven')
        super().__init__(task,settings)
        self.vision=MultiView(settings)
        self.memory=Experience(Path(__file__).resolve().parents[2]/'experience',settings['run_dir'])
        self.recipe=self.memory.parameters()
    def step(self,observation,ask_jev,perceive):
        self.vision.stage=self.stage
        if self.plan:
            self.vision.active_arm=self.plan['arms'][0]
            self.plan['allow_grasp_retry']=self.recipe['retry_count']>0
        stage=self.stage; loaded=self.memory.retrieve(stage)
        def query(state,questions):
            relevant=self.memory.retrieve(state['stage'])
            state['experience_memory']=[dict(id=r['id'],sha256=r['sha256'],lesson=r['content']) for r in relevant]
            state['memory_role']='historical advice, not current observation or simulator truth; follow current evidence'
            return ask_jev(state,questions)
        result=super().step(observation,query,perceive)
        result['debug']['loaded_experience']=[dict(id=r['id'],sha256=r['sha256']) for r in loaded]
        self.memory.save_step(stage,loaded,result)
        return result
    def _targets(self):
        targets,uncertainty,opening=super()._targets()
        if self.stage in ('approach','contact'):
            anchor=np.asarray(self.plan['initial_grasp']).copy()+[0,0,self.recipe['anchor_offset_m']]
            if self.plan.get('grasp_retry_used'):anchor[2]-=self.recipe['retry_depth_m']
            targets={self.plan['arms'][0]:anchor+[0,0,self.recipe['approach_clearance_m'] if self.stage=='approach' else 0]}
            self.debug['target_provenance']=dict(reference='initial observed grasp, not current centroid',recipe='pick_lift',parameters=self.recipe)
        return targets,uncertainty,opening
