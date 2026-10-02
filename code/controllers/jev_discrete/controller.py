"""Jev owns translation signs, grippers and EVERY phase transition.

Task-specific RGB-D helpers only prepare candidates and measured evidence.
No simulator evaluation, object truth, contacts, segmentation IDs or asset poses.
"""
import copy
import time
import numpy as np
from geometry_controller import Controller as Geometry
from base_controller import bounded_quaternion, tool_quaternion, EvidenceError, AXES
from visual_evidence import plain

MOVING={'approach':'contact','contact':'close','lift':'verify_grasp',
        'transport':'lower','lower':'release','retreat':'verify_release',
        'press_approach':'press_contact','press_contact':'press_stroke',
        'press_stroke':'press_verify','press_retract':'select','return_home':'done'}
CONTRACTS={
 'select':'Identify the instruction-relevant visible object(s) and a feasible prepared plan before advancing.',
 'approach':'Reach the clearance waypoint AND align tool orientation. Keep the gripper open for grasp tasks; closed for button pressing.',
 'contact':'Reach the current contact waypoint with aligned orientation and usable visual/reference evidence. Keep gripper open until contact is reached; then close and advance.',
 'close':'Close the gripper. Advance to lift after actual robot opening is near closed (<=0.15). Closure alone is NOT grasp success.',
 'lift':'Keep closed while reaching the lift waypoint. Advance to visual verification once the robot reaches it.',
 'verify_grasp':'Require repeated visual object/cloth rise and attachment evidence; an empty robot lift is not success. Keep closed. Advance only when evidence supports carrying.',
 'transport':'Keep closed and reach the destination clearance waypoint.',
 'lower':'Keep closed until the placement waypoint is reached, then advance to release.',
 'release':'Open the gripper; advance only after actual opening is near open (>=0.85).',
 'retreat':'Keep open and move to the retreat waypoint before verifying the placement.',
 'verify_release':'Require repeated visible placement/fold geometry and settling evidence; advance when supported.',
 'press_approach':'Close the gripper as a pressing tool, orient to measured face normal, reach clearance waypoint.',
 'press_contact':'Keep closed, reach the measured button-face contact waypoint.',
 'press_stroke':'Keep closed and apply bounded normal stroke; use actual movement/stall evidence, never infer activation from a command alone.',
 'press_verify':'Use visible face displacement and proprioceptive stroke evidence to decide whether to retract; native activation is unavailable.',
 'press_retract':'Keep closed, retract to clearance and allow spring return. Advancing records an attempted press, NOT verified activation.',
 'return_home':'Open both grippers and return to recorded initial robot positions AND orientations before advancing to done.',
 'conveyor_wait_first':'Observe the first uniquely visible belt object; remember its appearance before advancing.',
 'conveyor_wait_departure':'Wait for repeated absence plus observed motion toward/past belt boundary, not a single missed detection.',
 'conveyor_wait_repeat':'Wait for matching appearance to return in a reachable downstream region, then advance to approach.',
}


def choice(text,criteria):
    return dict(type='choice',instructions=text,criteria=criteria)

class Controller(Geometry):
    def __init__(self,task,settings):
        super().__init__(task,settings)
        self.variant=settings.get('input_variant','numeric')
        self.processing=settings.get('processing_variant','anchored')
        self.proposal=None;self.initial_robot=None;self.perception_failures=0
        self.phase_decisions=[];self.last_grip={};self.prepared_stage=None
        self.rules.setdefault('approach_clearance_m',.055)

    def _transition(self,new,evidence):
        # Legacy geometry helpers can propose, but cannot change stage.
        self.proposal=dict(to_stage=new,evidence=plain(evidence),owner='external_candidate_only')

    def _nearest_arm(self,point):
        if self.initial_robot:
            l=self.initial_robot['left']['grasp'];r=self.initial_robot['right']['grasp'];v=r-l
            n=np.linalg.norm(v)
            if n>.1:
                side=np.dot(np.asarray(point)-.5*(r+l),v/n)
                if abs(side)>.04:return 'right' if side>0 else 'left'
        return super()._nearest_arm(point)

    def _targets(self):
        if self.stage=='return_home':
            return {a:r['grasp'].copy() for a,r in self.initial_robot.items()},0.,1.
        targets,u,g=super()._targets()
        if self.task=='general_pickup' and self.processing=='anchored' and self.stage in ('approach','contact'):
            targets={self.plan['arms'][0]:self.plan['initial_grasp']+np.array([0,0,.004+(.055 if self.stage=='approach' else 0)])}
        return targets,u,g

    def _result(self,*args,**kwargs):
        result=super()._result(*args,**kwargs)
        result['debug'].pop('rotation_gripper_arm_stage_owner',None)
        result['debug']['decision_owners']=dict(translation_sign='Jev',gripper='Jev',phase_transition='Jev',
            perception_targets_orientation_amplitude='external task-specific algorithms')
        return result

    def _prepare(self):
        evidence={};targets={};uncertainty=0.
        self.proposal=None
        if self.stage=='select' or self.stage.startswith('conveyor_wait_'):
            self._select()
            evidence['candidate_plan']=self.plan
            evidence['temporal_observations']=self.debug
            if self.proposal: next_stage=self.proposal['to_stage'];evidence['candidate_basis']=self.proposal['evidence']
            else:next_stage=None
        elif self.stage in MOVING:
            targets,uncertainty,_=self._targets();next_stage=MOVING[self.stage]
            if self.stage=='contact' and self.task=='match_and_pick_from_conveyor':
                row=self._get(self.plan['source'],fresh=True);a=self.plan['arms'][0]
                evidence['current_contact_error_m']=self._grasp_point(row,a)-self.robot[a]['grasp']
                evidence['prediction_note']='Tracking waypoint may lead moving object; closure must use current contact error.'
            if self.stage=='press_retract':
                next_stage='done' if self.press_index+1>=len(self.sequence) else 'select'
            if self.stage=='press_stroke':
                a=self.plan['arms'][0]
                evidence['normal_advancement_m']=float(np.dot(self.plan['button_surface']-self.robot[a]['grasp'],self.plan['normal']))
        elif self.stage=='close':next_stage='lift'
        elif self.stage=='release':next_stage='retreat'
        elif self.stage=='verify_grasp':
            _,evidence=self._verify_grasp()
            evidence['consecutive_supporting_observations']=len(self.grasp_evidence)
            if self.task=='fold_clothes':next_stage='transport'
            else:next_stage='done' if self.plan.get('destination') is None else 'transport'
        elif self.stage=='verify_release':
            _,evidence=self._verify_release()
            evidence['consecutive_observations']=len(self.release_evidence)
            next_stage='return_home'
            if self.task.startswith('stack_') and len(self.stack_members)+1<self.required_stack_count:next_stage='select'
            if self.task=='fold_clothes' and self.plan.get('fold_mode')=='visible_sleeve_fold':next_stage='select'
        elif self.stage=='press_verify':
            row=self._get(self.plan['source'],fresh=True)
            displacement=float(np.dot(self.plan['button_before']-row['center'],self.plan['normal']))
            self.plan['press_displacements'].append(displacement)
            evidence=dict(visible_face_displacement_m=displacement,peak_visible_displacement_m=max(self.plan['press_displacements']),
                          uncertainty_m=row['uncertainty_m'],activation_observed='unknown',robot_feedback=self.feedback)
            next_stage='press_retract'
        else:raise EvidenceError('unsupported phase '+self.stage)
        return targets,uncertainty,next_stage,plain(evidence)

    def _input(self,targets,u,next_stage,evidence,observation,error):
        arms=list(targets) or (self.plan['arms'] if self.plan else [])
        if self.stage.startswith('conveyor_wait_') or self.stage=='select':arms=list(self.robot)
        state=dict(version='jev_discrete_v1',task=self.task,instruction=self.instruction,stage=self.stage,
            input_variant=self.variant,processing_variant=self.processing,native_step=self.last_native,
            remaining_steps=self.remaining,stage_age=self.stage_age,active_arms=arms,
            observation_permissions='RGB-D, calibrated cameras, robot feedback, public instruction; no object truth or native success',
            decision_owners=dict(translation_sign='Jev',gripper='Jev',phase_transition='Jev',target_candidates_orientation_amplitude='external'),
            stage_goal=CONTRACTS.get(self.stage,'Observe current evidence before advancing'),
            next_stage_candidate=next_stage,phase_evidence=evidence,perception_error=error,
            robot=self.robot,history=list(self.history)[-8:],feedback=self.feedback,
            visibility={k:{f:v.get(f) for f in ('observed','age_steps','uncertainty_m','label','source','views')} for k,v in self.current.items()},
            constraints=dict(max_delta_norm_m=self.max_step,dead_zone_m=self._deadzone(u),uncertainty_m=u),
            interpretation='Targets are desired robot waypoints from vision, not true object poses. Evidence is an estimate. Stage names/candidates do not assert completion.')
        geometry={a:dict(current_grasp_xyz_m=self.robot[a]['grasp'],target_xyz_m=p,target_minus_grasp_m=p-self.robot[a]['grasp']) for a,p in targets.items()}
        if self.variant=='relations':
            state['relations']={a:{axis:dict(relation='within_tolerance' if abs(e)<=self._deadzone(u) else 'target_higher' if e>0 else 'target_lower',
                signed_distance_mm=float(e*1000)) for axis,e in zip(AXES,p-self.robot[a]['grasp'])} for a,p in targets.items()}
        else:state['geometry']=geometry
        angles={}
        for a in arms:
            q=self.initial_robot[a]['quaternion'] if self.stage=='return_home' else self.plan['quaternions'].get(a,self.robot[a]['quaternion']) if self.plan else tool_quaternion([0,0,-1])
            _,angles[a]=bounded_quaternion(self.robot[a]['quaternion'],q)
        state['orientation_error_rad']=angles
        if self.variant=='evidence':
            state['evidence_card']=dict(waypoint_max_abs_error_mm={a:float(np.max(np.abs(p-self.robot[a]['grasp']))*1000) for a,p in targets.items()},
                tolerance_mm=self._deadzone(u)*1000,orientation_error_rad=angles,gripper_opening={a:self.robot[a]['opening'] for a in arms},
                phase_observations=evidence,warning='Computed summaries of available measurements; not simulator truth, not a forced transition decision.')
        used=self.memory.retrieve(self.stage)
        # Existing lessons are hints only. No old instructions assigning gripper/phase to external program.
        state['experience_memory']=[dict(id=r['id'],lesson=r['content'],sha256=r['sha256']) for r in used]
        self.memory.record(state,used)
        return plain(state),arms,angles

    def _questions(self,targets,arms,next_stage,error):
        questions={}
        for a in targets:
            for axis in AXES:
                questions[f'{a}_{axis}']=choice(f'Choose next {a} world {axis} translation direction toward this phase waypoint. Hold inside dead zone or when evidence is unusable. Phase/gripper are decided separately.',
                    dict(negative='decrease coordinate',hold='zero translation',positive='increase coordinate'))
        for a in arms:
            questions[f'{a}_gripper']=choice(f'Decide {a} gripper action from current phase goal, geometry and actual opening. open/close command the endpoint; keep preserves the LAST commanded endpoint, avoiding half-closed stalls. Close at supported contact, remain closed during lift/carry; release only at placement. For buttons use closed fingers as tool.',
                dict(open='command fully open',close='command fully closed',keep='preserve previous gripper command'))
        criteria=dict(stay='Continue current stage; execute selected movement/gripper command.',
            reobserve='Stay in stage, hold translation and gripper command; acquire another observation.',abort='Stop unsuccessful because available evidence cannot support safe progress.')
        if next_stage and not error:criteria['advance']=f'Enter {next_stage}; current stage requirements are satisfied by available evidence. No translation in the transition action; selected gripper command still executes.'
        questions['phase']=choice('YOU decide WHEN to change phase. The candidate is a possible next goal, NOT an instruction to advance now. Compare measured errors/opening/orientation and phase_goal. Advance only after current stage completion. In contact use current contact error if supplied. Missing evidence: reobserve; never use hidden simulation outcome. A verification requires at least two supporting observations. Select/temporal phases advance when candidate evidence is supported.',criteria)
        return questions

    def _accept_phase(self,new,evidence):
        old=self.stage
        if old=='close' and self.plan.get('baseline') is None:self.plan['baseline']=self._baseline()
        if old=='release':self.plan['release_robot']={a:self.robot[a]['grasp'].copy() for a in self.plan['arms']}
        if old=='verify_grasp' and new=='transport':
            self.plan['grasp_verified']=True
            if self.task!='fold_clothes':
                a=self.plan['arms'][0];self.plan['carry_offset']=self.robot[a]['grasp']-self._get(self.plan['source'])['center']
        if old=='verify_release':
            self.completed.append(self.plan['source'])
            if self.task.startswith('stack_'):self.stack_members.add(self.plan['source']);self.plan['stack_base']=self.plan['source']
            if self.task=='fold_clothes':self.fold_index+=1
        if old=='press_retract':self.completed.append(dict(attempted_press=self.plan['count_entry'],activation='unknown'));self.press_index+=1
        event=dict(from_stage=old,to_stage=new,owner='Jev',evidence=evidence,native_step=self.last_native)
        self.transitions.append(event);self.history.append(dict(event='phase_transition',**event))
        self.stage=new;self.stage_age=0;self.stage_native=self.last_native;self.stall_count=0

    def step(self,observation,ask_jev,perceive):
        self.debug={};self.transitions=[]
        if self.stopped:return self._result(stop=True,reason=self.stop_reason,ticks=1)
        try:
            self.last_native=int(observation['native_step']);self.remaining=int(observation['remaining_steps'])
            self.instruction=str(observation['instruction']);self._read_robot(observation)
            if self.initial_robot is None:self.initial_robot=copy.deepcopy(self.robot)
            self._after_motion();self.step_index+=1;self.stage_age+=1
            if self.remaining<=0 or self.jev_calls>=240 or time.monotonic()-self.started>19*60:
                return self._result(stop=True,reason='external hard budget reached',ticks=1)
            self.vision.stage=self.stage
            if self.plan:self.vision.active_arm=self.plan['arms'][0];self.vision.active_id=self.plan['source']
            def perception(prompt,payload):
                measured=perceive(prompt,payload)
                if self.task=='match_and_pick_from_conveyor' and self.first_object is not None:self._appearance_candidates(payload,measured)
                return measured
            error=None;targets={};u=0.;next_stage=None;evidence={}
            try:
                self.current=self.vision.update(observation,perception,force=self.perception_failures>0 or self.stage.startswith('verify') or self.stage in ('press_verify','conveyor_wait_departure'))
                self.vision.surface_reobserve=any(not r['observed'] for r in self.current.values())
                targets,u,next_stage,evidence=self._prepare()
                if u>.025:raise EvidenceError('target uncertainty exceeds 25mm')
                self.perception_failures=0
            except EvidenceError as exc:
                error=str(exc);targets={};next_stage=None;self.perception_failures+=1
                evidence=dict(available=False,reason=error)
            state,arms,angles=self._input(targets,u,next_stage,evidence,observation,error)
            questions=self._questions(targets,arms,next_stage,error)
            started=time.monotonic();self.jev_calls+=1
            raw=ask_jev(state,questions);self.jev_seconds+=time.monotonic()-started
            answers=raw.get('answers',{})
            if set(answers)!=set(questions):raise ValueError('missing or extra Jev answers')
            decisions={}
            for k,v in answers.items():
                if v.get('type')!='choice' or v.get('choice') not in questions[k]['criteria']:raise ValueError('invalid Jev choice '+k)
                decisions[k]=v['choice']
            phase=decisions['phase'];commands={};amplitudes={}
            if phase=='abort':return self._result(stop=True,reason='Jev abort from observed evidence',ticks=1)
            # Freeze candidate geometry before transitioning; never move using an old-stage sign after a phase change.
            for a in arms:
                qgoal=self.initial_robot[a]['quaternion'] if self.stage=='return_home' else self.plan['quaternions'].get(a,self.robot[a]['quaternion']) if self.plan else tool_quaternion([0,0,-1])
                q,_=bounded_quaternion(self.robot[a]['quaternion'],qgoal)
                opening=self.last_grip.get(a,self.robot[a]['opening'])
                grip=decisions[a+'_gripper']
                if phase!='reobserve':opening={'open':1.,'close':0.,'keep':opening}[grip]
                self.last_grip[a]=opening
                delta=np.zeros(3)
                if phase=='stay' and a in targets:
                    e=targets[a]-self.robot[a]['grasp'];amp=np.minimum(.025,.7*np.abs(e));amp[np.abs(e)<=self._deadzone(u)]=0
                    amp*=min(1.,self.max_step/max(np.linalg.norm(amp),1e-12))
                    delta=amp*np.array([{'positive':1.,'negative':-1.,'hold':0.}[decisions[a+'_'+x]] for x in AXES]);amplitudes[a]=amp
                    if self.stage=='approach' and angles[a]>.15:delta*=0  # explicitly logged orientation safety gate
                if phase=='reobserve':q=self.robot[a]['quaternion']
                commands[a]=dict(delta_xyz_m=delta,quaternion_wxyz=q,gripper_opening=opening)
            if self.stage=='close' and self.plan.get('baseline') is None and any(c['gripper_opening']<.5 for c in commands.values()):self.plan['baseline']=self._baseline()
            if self.stage=='release' and any(c['gripper_opening']>.5 for c in commands.values()):self.plan['release_robot']={a:self.robot[a]['grasp'].copy() for a in self.plan['arms']}
            self.debug.update(jev_request=dict(state=state,questions=questions),jev_response=raw,jev_choices=decisions,axis_amplitudes=amplitudes,
                phase_candidate=next_stage,phase_evidence=evidence,orientation_safety_gate=self.stage=='approach' and any(x>.15 for x in angles.values()))
            self.history.append(dict(event='Jev_decision',stage=self.stage,choices=decisions,native_step=self.last_native))
            if targets and phase=='stay':self.last_motion=dict(stage=self.stage,grasp={a:self.robot[a]['grasp'].copy() for a in targets},target=copy.deepcopy(targets),delta={a:commands[a]['delta_xyz_m'].copy() for a in targets})
            blocked=self._motion_guard(commands)
            if blocked:return self._result(stop=True,reason='external motion safety veto: '+blocked,ticks=1)
            if phase=='advance':self._accept_phase(next_stage,evidence)
            if self.stage=='done':return self._result(stop=True,reason='Jev declared task complete; native evaluator remains independent',ticks=1)
            ticks=2 if self.task=='match_and_pick_from_conveyor' else 5
            if self.stage.startswith('conveyor_wait_'):ticks=10
            return self._result(commands,reason='Jev phase/gripper/sign decision',ticks=ticks)
        except Exception as exc:
            return self._result(stop=True,reason='controller error: '+type(exc).__name__+': '+str(exc)[:300],ticks=1)
