"""Same task execution infrastructure with or without frozen historical advice."""
import copy
from pathlib import Path
import numpy as np
from base_controller import Controller as Base,tool_quaternion,EvidenceError
from multiview import MultiView
from experience import Experience

class Controller(Base):
    def __init__(self,task,settings):
        super().__init__(task,settings)
        self.vision=MultiView(settings)
        self.memory=Experience(Path(__file__).resolve().parents[2]/'experience/press_focus',settings['run_dir'],task,settings.get('experience_enabled',False))
        self.rules=self.memory.rules();self.feedback=None;self.press_stall=0;self.fixture_map={}
    def step(self,observation,ask_jev,perceive):
        self.vision.stage=self.stage
        if self.plan:self.vision.active_arm=self.plan['arms'][0];self.vision.active_id=self.plan['source']
        def query(state,questions):
            used=self.memory.retrieve(state['stage'])
            if used:state['experience_memory']=[dict(id=r['id'],lesson=r['content'],sha256=r['sha256']) for r in used]
            self.memory.record(state,used)
            return ask_jev(state,questions)
        def perception(prompt,payload):
            measured=perceive(prompt,payload)
            if self.task=='match_and_pick_from_conveyor' and self.rules.get('appearance_match') and self.first_object is not None:
                self._appearance_candidates(payload,measured)
            return measured
        result=super().step(observation,query,perception)
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
        if self.task=='press_by_number' and not self.fixture_map:
            self.fixture_map={k:copy.deepcopy(v) for k,v in self.current.items() if v['category']=='button' and v['observed']}
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
        if self.stage.startswith('press_') and self.rules.get('occluded_fixture_map'):
            u=min(u,.008)
            self.debug['fixture_map_uncertainty']=dict(value_m=u,assumption='fixed fixture established this episode; not fresh geometry',calibrated=False)
        if self.task=='stack_bowls' and self.rules.get('rim_circle') and self.stage in ('approach','contact'):
            a=self.plan['arms'][0];targets={a:self.plan['initial_grasp']+np.array([0,0,.055 if self.stage=='approach' else 0])}
        if self.task=='fold_clothes' and self.rules.get('cloth_keypoint_anchor') and self.stage in ('approach','contact'):
            self._get(self.plan['source'],fresh=True)
            targets={a:p+np.array([0,0,.045 if self.stage=='approach' else 0]) for a,p in self.plan['fold_source'].items()}
            self.debug['experience_reference']='initial garment landmark, not new centroid; fresh cloth required'
        return targets,u,g

    def _select_fold(self,cloth):
        if not self.rules.get('cloth_keypoint_anchor') or len(cloth.get('corners',[]))!=4:
            return super()._select_fold(cloth)
        corners=np.asarray(cloth['corners']); names=cloth['corner_names']; candidates=[]
        mid=.5*(self.robot['left']['link6'][0]+self.robot['right']['link6'][0])
        for k in range(4):
            src=[k,(k+1)%4]; dst=[(k+3)%4,(k+2)%4]
            for arms in [('left','right'),('right','left')]:
                travel=0.; penalty=0.
                for a,i,j in zip(arms,src,dst):
                    travel+=np.linalg.norm(self.robot[a]['grasp']-corners[i])+np.linalg.norm(corners[j]-corners[i])
                    for point in [corners[i],corners[j]]:
                        excess=point[0]-mid if a=='left' else mid-point[0]
                        penalty+=max(0.,excess-.015)
                candidates.append((10*penalty+travel,penalty,arms,src,dst))
        _,penalty,arms,si,di=min(candidates,key=lambda x:x[0])
        if penalty>.04: raise EvidenceError('paired garment fold requires unreachable cross-arm workspace')
        src=corners[si];dst=corners[di];spans=np.linalg.norm(dst-src,axis=1)
        self.plan=dict(source=cloth['id'],arms=list(arms),fold_mode='outline_half_fold',
            fold_source=dict(zip(arms,src)),fold_destination=dict(zip(arms,dst)),
            source_names=dict(zip(arms,[names[i] for i in si])),destination_names=dict(zip(arms,[names[i] for i in di])),
            landmark_view=cloth['landmark_view'],source_initial=cloth['center'].copy(),
            initial_extent=(cloth['high']-cloth['low']).copy(),baseline=None,grasp_verified=False,
            quaternions={a:tool_quaternion([0,0,-1],dst[i]-src[i]) for i,a in enumerate(arms)},
            fold_height=min(.14,max(.05,float(max(spans))*.35)),rule='observed opposite garment edges with bilateral workspace gate')
        self.grasp_evidence=[];self.release_evidence=[]
        self._transition('approach',dict(memory='cloth-reference',workspace_penalty_m=penalty,source_points=src,destination_points=dst))

    def _get(self,oid,fresh=False):
        row=self.current.get(oid)
        if self.task=='press_by_number' and self.rules.get('occluded_fixture_map') and oid in self.fixture_map:
            if row is None or not row['observed'] or row['uncertainty_m']>.012:
                remembered=copy.deepcopy(self.fixture_map[oid]); remembered.update(observed=False,
                    fixture_map=True,source='initial_observed_stationary_button_reference_NOT_current',
                    age_steps=max(0,self.step_index-remembered['measurement_index']),uncertainty_m=.008)
                self.debug.setdefault('fixture_references',[]).append(dict(id=oid,initial_native_step=remembered['native_step'],current_native_step=self.last_native,observed_now=False))
                return remembered
        return super()._get(oid,fresh=fresh)

    def _appearance_candidates(self,observation,measured):
        import cv2
        ref=np.asarray(self.first_object['color'],float); proto=ref/max(1.,ref.sum())
        for name,view in observation['cameras'].items():
            image=np.asarray(view['rgb'],float); chroma=image/np.maximum(1.,image.sum(-1,keepdims=True))
            mask=(np.linalg.norm(chroma-proto,axis=-1)<.07)&(image.mean(-1)>.5*ref.mean())
            count,labels,stats,_=cv2.connectedComponentsWithStats(mask.astype(np.uint8))
            h,w=mask.shape
            for i in range(1,count):
                area=stats[i,cv2.CC_STAT_AREA]
                if not 30<=area<=.03*h*w:continue
                contours,_=cv2.findContours((labels==i).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                contour=max(contours,key=cv2.contourArea);contour=cv2.approxPolyDP(contour,.01*cv2.arcLength(contour,True),True).reshape(-1,2)
                if len(contour)<3:continue
                measured['views'][name]['objects'].append(dict(category=self.first_object['category'],label=self.first_object['label'],
                    appearance=self.first_object['appearance'],text=self.first_object['text'],confidence=.8,
                    polygon_uv01=(contour/[w-1,h-1]).tolist(),keypoints={},
                    source='current RGB chroma segmentation against first-observed appearance; requires subsequent metric gate'))
