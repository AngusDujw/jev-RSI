"""Jev owns translation signs, grippers and EVERY phase transition.

Task-specific RGB-D helpers only prepare candidates and measured evidence.
No simulator evaluation, object truth, contacts, segmentation IDs or asset poses.
"""
import copy
import time
import numpy as np
from geometry_controller import Controller as Geometry
from base_controller import bounded_quaternion, tool_quaternion, quat_matrix, EvidenceError, AXES
from visual_evidence import plain

MOVING={'approach':'contact','contact':'close','lift':'verify_grasp',
        'transport':'lower','lower':'release','retreat':'verify_release',
        'press_approach':'press_contact','press_contact':'press_stroke',
        'press_stroke':'press_verify','press_retract':'select','return_home':'done'}
CONTRACTS={
 'select':'Identify the instruction-relevant visible object(s) and a feasible prepared plan before advancing.',
 'approach':'Reach the clearance waypoint AND align tool orientation. Keep the gripper open for grasp tasks; closed for button pressing.',
 'contact':'Reach the current contact waypoint with aligned orientation and usable visual/reference evidence. Keep gripper open until contact is reached; then close and advance.',
 'close':'Command close and observe its response. Advance to a lift PROBE when opening is near closed (<=0.15) OR has stabilized for two observations under a close command. An object may prevent full closure. This is not grasp success; verify after lifting.',
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
        self.phase_decisions=[];self.last_grip={};self.prepared_stage=None;self.gripper_observations=[];self.grasp_retries=0;self.contact_stalls=0
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
        if self.stage=='lift' and self.plan.get('baseline'):
            distance=self.plan['fold_height'] if self.task=='fold_clothes' else self.plan['lift_distance_m']
            self.debug['waypoint_reference']='bounded lift probe from recorded ROBOT position; no assertion of current object pose or attachment'
            return {a:np.asarray(self.plan['baseline']['robot'][a])+[0,0,distance] for a in self.plan['arms']},0.,0.
        if self.stage=='return_home':
            return {a:r['grasp'].copy() for a,r in self.initial_robot.items()},0.,1.
        targets,u,g=super()._targets()
        if self.task=='general_pickup' and self.processing in ('anchored','precision') and self.stage in ('approach','contact'):
            targets={self.plan['arms'][0]:self.plan['initial_grasp']+np.array([0,0,.004+(.055 if self.stage=='approach' else 0)])}
        if self.processing=='precision' and self.stage in ('approach','contact') and self.task=='fold_clothes':
            center=self.plan['source_initial']
            targets={a:np.asarray(p).copy() for a,p in targets.items()}
            for a,p in targets.items():
                v=center[:2]-p[:2];p[:2]+=.010*v/max(np.linalg.norm(v),1e-9)
                if self.stage=='contact':p[2]-=.004
            self.debug['cloth_contact_processing']=dict(inset_m=.010,depth_offset_m=-.004,source='initial visual landmarks plus bounded contact hypothesis; no hidden geometry')
        if self.task=='press_by_number' and self.stage=='press_stroke':
            a=self.plan['arms'][0];targets={a:np.asarray(self.plan['button_surface'])-np.asarray(self.plan['normal'])*.016}
            self.debug['bounded_probe']=dict(depth_m=.016,reference='initial visible button surface; actual activation unknown')
        return targets,u,g

    def _deadzone(self,uncertainty):
        if self.processing=='precision' and self.stage in ('contact','lower','press_contact','press_stroke'):
            return .002  # waypoint tracking tolerance; perception uncertainty remains disclosed separately
        return super()._deadzone(uncertainty)

    def _orientation_goal(self,a):
        if self.stage=='return_home':return self.initial_robot[a]['quaternion']
        if self.task=='stack_bowls' and self.stage in ('transport','lower','release','retreat'):
            self.debug['orientation_contract']='vertical approach axis; yaw is free for rotationally symmetric bowls'
            return tool_quaternion([0,0,-1],quat_matrix(self.robot[a]['quaternion'])[:,1])
        return self.plan['quaternions'].get(a,self.robot[a]['quaternion']) if self.plan else tool_quaternion([0,0,-1])

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
            else:
                next_stage=None
                if self.task=='match_and_pick_from_conveyor' and self.first_object is not None:
                    if self.stage in ('select','conveyor_wait_first'):next_stage='conveyor_wait_departure'
                    elif self.stage=='conveyor_wait_departure' and self.conveyor_departed:next_stage='conveyor_wait_repeat'
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
            input_variant=self.variant,processing_variant=self.processing,native_step=self.last_native,frame='world axes relative to environment origin; geometry/robot metres; relation error millimetres',
            remaining_steps=self.remaining,stage_age=self.stage_age,active_arms=arms,
            recent_gripper_feedback=self.gripper_observations[-4:],last_gripper_commands=self.last_grip,
            observation_permissions='RGB-D, calibrated cameras, robot feedback, public instruction; no object truth or native success',
            decision_owners=dict(translation_sign='Jev',gripper='Jev',phase_transition='Jev',target_candidates_orientation_amplitude='external'),
            stage_goal=CONTRACTS.get(self.stage,'Observe current evidence before advancing'),
            next_stage_candidate=next_stage,phase_evidence=evidence,perception_error=error,
            robot=self.robot,history=list(self.history)[-8:],feedback=self.feedback,
            waypoint_reference=self.debug.get('waypoint_reference','desired robot waypoint estimated from RGB-D; not an object truth claim'),grasp_retries=self.grasp_retries,consecutive_contact_stalls=self.contact_stalls,
            contact_stall_meaning='commanded translation >2mm but measured response <0.5mm; may be contact OR IK limitation, not a contact sensor',
            visibility={k:{f:v.get(f) for f in ('observed','age_steps','uncertainty_m','label','source','views')} for k,v in self.current.items()},
            constraints=dict(max_delta_norm_m=self.max_step,dead_zone_m=self._deadzone(u),uncertainty_m=u),
            interpretation='Targets are desired robot waypoints from vision, not true object poses. Evidence is an estimate. Stage names/candidates do not assert completion.')
        geometry={a:dict(current_grasp_xyz_m=self.robot[a]['grasp'],target_xyz_m=p,target_minus_grasp_m=p-self.robot[a]['grasp']) for a,p in targets.items()}
        if self.variant=='relations':
            state['relations']={a:{axis:dict(relation='within_tolerance' if abs(e)<=self._deadzone(u) else 'target_higher' if e>0 else 'target_lower',
                target_minus_current_grasp_mm=float(e*1000)) for axis,e in zip(AXES,p-self.robot[a]['grasp'])} for a,p in targets.items()}
        else:state['geometry']=geometry
        angles={}
        for a in arms:
            q=self._orientation_goal(a)
            _,angles[a]=bounded_quaternion(self.robot[a]['quaternion'],q)
        state['orientation_error_rad']=angles
        state['alignment_facts']={a:dict(error_mm=(1000*(p-self.robot[a]['grasp'])).tolist(),tolerance_mm=1000*self._deadzone(u),
            axes_outside_tracking_band=[axis for axis,e in zip(AXES,p-self.robot[a]['grasp']) if abs(e)>self._deadzone(u)],
            orientation_outside_tracking_band=angles[a]>.15) for a,p in targets.items()}
        state['fact_provenance']='Band comparisons are computed from the SAME disclosed measured/reference coordinates, not simulator truth or an instruction to advance.'

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
                questions[f'{a}_{axis}']=choice(f'Choose next {a} world {axis} translation direction toward this phase waypoint. Use target minus CURRENT GRASP: positive difference means positive motion; negative means negative. In relations, target_minus_current_grasp_mm uses millimetres; dead_zone_m uses metres (multiply by 1000). Hold inside dead zone or when evidence is unusable. Phase/gripper are decided separately.',
                    dict(negative='decrease coordinate',hold='zero translation',positive='increase coordinate'))
        for a in arms:
            questions[f'{a}_gripper']=choice(f'Decide {a} gripper action from current phase goal, geometry and actual opening. open/close command the endpoint; keep preserves the LAST commanded endpoint, avoiding half-closed stalls. Close at supported contact, remain closed during lift/carry; release only at placement. For buttons use closed fingers as tool.',
                dict(open='command fully open',close='command fully closed',keep='preserve previous gripper command'))
        criteria=dict(stay='Continue current stage; execute selected movement/gripper command.',
            reobserve='Stay in stage, hold translation and gripper command; acquire another observation.',abort='Stop unsuccessful because available evidence cannot support safe progress.')
        if next_stage and not error:criteria['advance']=f'Enter {next_stage}; current stage requirements are satisfied by available evidence. No translation in the transition action; selected gripper command still executes.'
        questions['phase']=choice('YOU decide WHEN to change phase. The candidate is a possible next goal, NOT an instruction to advance now. Compare measured errors/opening/orientation and stage_goal. Advance only after current stage completion. In contact use current contact error if supplied. Missing evidence: reobserve; never use hidden simulation outcome. A verification requires at least two supporting observations. Select/temporal phases advance when candidate evidence is supported.',criteria)
        if self.stage=='select' and next_stage in ('approach','press_approach') and not error:
            questions['phase']=choice('Decide whether to finish SELECT and begin APPROACH. Selection is complete if an instruction-relevant source and a feasible candidate plan are available from observed RGB-D. This phase requires NO robot movement, grasp, lift, or task success. Lack of grasp/lift evidence is irrelevant at SELECT.',
                dict(advance='A source and a usable candidate plan are available: begin approaching it.',reobserve='A source or usable plan is missing or ambiguous: obtain another observation.'))
        elif self.stage in ('select','conveyor_wait_first','conveyor_wait_departure','conveyor_wait_repeat') and self.task=='match_and_pick_from_conveyor' and next_stage:
            questions['phase']=choice('Decide only the current temporal observation phase. If candidate is conveyor_wait_departure: a unique first object appearance is already remembered, advance to WAIT for departure (do not require it to have left yet). If candidate is conveyor_wait_repeat: evaluate repeated absence and boundary evidence. If candidate is approach: evaluate returned appearance and reachability. No grasp is required in these observation phases.',dict(advance='Current observation/memory supports entering the explicitly named NEXT observation or approach phase.',reobserve='Current observation or identity evidence is ambiguous; stay and observe.'))
        elif self.stage in MOVING:
            questions['phase']['instructions']='Decide ONLY if the CURRENT robot waypoint has been reached: compare geometry/relations with constraints.dead_zone_m and orientation_error_rad (<=0.15 rad). If outside tolerance, stay and execute motion. If inside tolerance, advance to the named next phase. Do not require future grasp/lift/release success. At contact on conveyor, use current_contact_error_m instead of the lead waypoint. '+CONTRACTS.get(self.stage,'')
        elif self.stage in ('close','release'):
            questions['phase']['instructions']='Decide if the CURRENT gripper operation has been executed using recent_gripper_feedback and last_gripper_commands. '+CONTRACTS[self.stage]+' For close, nonzero stable opening under close command may mean object resistance: proceed to lift probe instead of waiting forever for zero. For release, require opening >=0.85. If still moving toward its command, stay; grasp verification is a later phase.'
        if self.task=='press_by_number' and self.stage=='select' and next_stage:
            questions['phase']['instructions']='Decide only whether the next prescribed button has been identified and a candidate approach exists. A previously observed, explicitly marked STATIONARY fixture reference is usable when the hand occludes the face. Do not require a fresh detection of that same fixture, or proof of previous activation, to select it. The sequence tracks attempted presses, not certified activations.'
            questions['phase']['criteria']['advance']='The next prescribed button identity and its current OR stored stationary fixture reference support an approach candidate.'
        if self.stage.startswith('press_'):
            questions['phase']['instructions']='Judge ONLY the current bounded robot operation, not whether the button was activated. '+CONTRACTS.get(self.stage,'')+' The geometry target is a requested ROBOT waypoint anchored to a measured fixture, not an assertion of true/current button pose. At stroke: compare maximum robot waypoint error with dead_zone_m; once reached, ADVANCE to verification/retraction. At press_verify: choose advance to retract and expose the button after the stroke; activation remains unknown. Do not demand hidden activation information to retract. At retract: advance when robot reaches clearance; this records an ATTEMPT only.'
        if self.stage=='verify_grasp' and self.grasp_retries<2:
            questions['phase']['criteria']['retry']='Fresh visual evidence shows empty/failed grasp after robot lift: reopen and return to a revised visible contact candidate.'
            questions['phase']['instructions']+=' Repeated evidence of object staying on its support while the robot rises is NEGATIVE grasp evidence, not merely missing evidence. Choose retry (and gripper open) to reattempt, or abort. Reobserve only if a new view could resolve missing evidence.'
            for key,q in questions.items():
                if key.endswith('_gripper'):q['instructions']+=' If selecting phase retry, choose open to release before reapproaching.'
        if self.stage=='contact' and self.task=='fold_clothes':
            questions['phase']['instructions']+=' If XY is aligned within 5mm and repeated commanded descent has stalled within 12mm of the requested surface waypoint (consecutive_contact_stalls >=2), you may advance to a CLOSE-and-lift probe instead of waiting for an unreachable exact Z. This could be support contact or IK limitation; it does not prove grasp. Inspect visible cloth after lifting.'
            for key,q in questions.items():
                if key.endswith('_gripper'):q['instructions']+=' At contact with XY alignment and repeated descent stall near the surface, closing is a permitted grasp probe; it is not proof of attachment.'
        if targets:
            questions['phase']['instructions']+=' IMPORTANT: alignment_facts lists every axis outside the required robot tracking band. Any listed axis means the waypoint is NOT reached. A phase name (contact/lift/etc.) names the current OBJECTIVE, not an achieved fact. Do not advance while listed axes remain, except an explicitly described bounded contact-stall probe.'
        phase_q=questions['phase']
        phase_q['instructions']=dict(question='What should happen to the CURRENT phase now?',current_phase=self.stage,
            focus_paths=['alignment_facts','phase_evidence','recent_gripper_feedback','last_gripper_commands','waypoint_reference'],
            policy=phase_q['instructions'],warning='A phase name is an objective, not an observation that it has happened. Future-stage goals are not completion evidence.')
        for option,description in list(phase_q['criteria'].items()):
            phase_q['criteria'][option]=dict(meaning=description)
        if 'advance' in phase_q['criteria']:
            phase_q['criteria']['advance']['not_when']=['a motion waypoint still has axes listed in alignment_facts.*.axes_outside_tracking_band (except a described contact probe)', 'the gripper operation has not yet executed', 'only a future objective or prior-stage history supports completion']
        phase_q['criteria'].setdefault('stay',dict(meaning='Continue the current unfinished objective.'))
        phase_q['criteria']['stay']['when']='Usable current/reference evidence is available and work toward the current objective remains.'
        if 'reobserve' in phase_q['criteria']:
            phase_q['criteria']['reobserve']['when']='A necessary observation is unavailable or ambiguous, and another observation could resolve it.'
            phase_q['criteria']['reobserve']['not_when']='The reference waypoint is usable and simply has not yet been reached.'
        for a in arms:
            q=questions[a+'_gripper']
            q['instructions']=dict(question=f'What command should the {a} gripper execute NOW in the current unfinished stage?',
                current_stage=self.stage,focus_paths=[f'robot.{a}.opening',f'alignment_facts.{a}',f'last_gripper_commands.{a}','stage_goal'],
                rule='Judge actual alignment and the current objective. The word contact does not mean the jaws have reached the object.',
                example='During descent with 50mm contact error, keep jaws OPEN. At an established close/probe location, CLOSE. During lift/carry maintain the close command.')
            q['criteria']=dict(
                open=dict(action='fully open',when=['approaching or descending to the grasp site; jaws must straddle the object','releasing or retreating after release','recovering from a failed grasp'],not_when=['carrying a held object before placement','using closed fingertips to press a button']),
                close=dict(action='fully close',when=['executing the close phase at the grasp site','a specifically supported near-surface grasp probe','using fingertips as a button-press tool'],not_when=['approach clearance waypoint','centimetres above the contact waypoint','release/retreat after placement']),
                keep=dict(action='keep the last Jev-commanded endpoint',when=['that endpoint remains appropriate to the CURRENT objective'],not_when=['last command closed the jaws prematurely during approach or unfinished descent','current objective requires changing the previous endpoint']))
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
            self.gripper_observations.append(dict(native_step=self.last_native,stage=self.stage,opening={a:r['opening'] for a,r in self.robot.items()},previous_commands=dict(self.last_grip)))
            if self.initial_robot is None:self.initial_robot=copy.deepcopy(self.robot)
            self._after_motion();self.step_index+=1;self.stage_age+=1
            stalled=self.stage=='contact' and self.feedback and self.feedback['stage']=='contact' and any(np.linalg.norm(f['command'])>.002 and np.linalg.norm(f['actual'])<.0005 for f in self.feedback['arms'].values())
            self.contact_stalls=self.contact_stalls+1 if stalled else 0
            if self.stage_age>40 and not self.stage.startswith('conveyor_wait_'):
                return self._result(stop=True,reason='external phase observation budget exhausted (40 decisions)',ticks=1)
            if self.perception_failures>=6:
                return self._result(stop=True,reason='external unavailable-observation budget exhausted (6 observations)',ticks=1)
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
            all_questions=self._questions(targets,arms,next_stage,error)
            phase_state=copy.deepcopy(state);phase_state['decision_role']='phase_only; no physical action in this query'
            questions={'phase':all_questions['phase']}
            started=time.monotonic();self.jev_calls+=1
            phase_raw=ask_jev(phase_state,questions)
            answers=dict(phase_raw.get('answers',{}));raw=dict(composed=True,phase_response=phase_raw)
            phase_choice=answers.get('phase',{}).get('choice')
            if phase_choice=='stay':
                action_questions={k:copy.deepcopy(v) for k,v in all_questions.items() if k!='phase'}
                action_state={k:copy.deepcopy(state[k]) for k in ('task','instruction','stage','native_step','remaining_steps','active_arms','frame','stage_goal','robot','geometry','relations','alignment_facts','constraints','visibility','orientation_error_rad','recent_gripper_feedback','last_gripper_commands','feedback','phase_evidence','waypoint_reference','consecutive_contact_stalls') if k in state}
                action_state.update(decision_role='current_stage_action_only',phase_decision='Jev chose STAY; current objective is not confirmed complete',
                    interpretation='No future-stage action. Current contact stage can still be centimetres above the object: examine alignment_facts, not the stage name.')
                for key,q in action_questions.items():
                    if key.endswith('_gripper'):
                        q['instructions']['phase_dependency']='Jev already chose STAY in the first request; choose an action for this CURRENT unfinished phase, not a future phase.'
                self.jev_calls+=1
                action_raw=ask_jev(action_state,action_questions)
                if set(action_raw.get('answers',{}))!=set(action_questions):raise ValueError('missing action answers')
                answers.update(action_raw['answers']);questions.update(action_questions);raw['action_response']=action_raw
            self.jev_seconds+=time.monotonic()-started
            raw['answers']=answers
            if set(answers)!=set(questions):raise ValueError('missing or extra Jev answers')
            decisions={}
            for k,v in answers.items():
                if v.get('type')!='choice' or v.get('choice') not in questions[k]['criteria']:raise ValueError('invalid Jev choice '+k)
                decisions[k]=v['choice']
            phase=decisions['phase'];commands={};amplitudes={}
            if phase=='abort':return self._result(stop=True,reason='Jev abort from observed evidence',ticks=1)
            # Freeze candidate geometry before transitioning; never move using an old-stage sign after a phase change.
            for a in arms:
                qgoal=self._orientation_goal(a)
                q,_=bounded_quaternion(self.robot[a]['quaternion'],qgoal)
                opening=self.last_grip.get(a,self.robot[a]['opening'])
                grip=decisions.get(a+'_gripper','keep')  # no new gripper choice on a phase-only transition; persist previous Jev command
                if phase!='reobserve':opening={'open':1.,'close':0.,'keep':opening}[grip]
                self.last_grip[a]=opening
                delta=np.zeros(3)
                if phase=='stay' and a in targets:
                    e=targets[a]-self.robot[a]['grasp'];amp=np.minimum(.025,.7*np.abs(e));amp[np.abs(e)<=self._deadzone(u)]=0
                    amp*=min(1.,self.max_step/max(np.linalg.norm(amp),1e-12))
                    delta=amp*np.array([{'positive':1.,'negative':-1.,'hold':0.}[decisions[a+'_'+x]] for x in AXES]);amplitudes[a]=amp
                    if self.stage=='approach' and angles[a]>.15 and self.stage_age<=8:delta*=0
                    elif self.stage=='approach' and angles[a]>.5:delta[2]=0
                    self.debug.setdefault('orientation_motion_masks',{})[a]=dict(initial_rotation_only=self.stage=='approach' and angles[a]>.15 and self.stage_age<=8,descent_suppressed=self.stage=='approach' and angles[a]>.5,rule='at most 8 orientation-only observations, then Jev horizontal motion; Z waits below 0.5rad')
                if phase!='stay':q=self.robot[a]['quaternion']
                commands[a]=dict(delta_xyz_m=delta,quaternion_wxyz=q,gripper_opening=opening)
            if self.stage=='close' and self.plan.get('baseline') is None and any(c['gripper_opening']<.5 for c in commands.values()):self.plan['baseline']=self._baseline()
            if self.stage=='release' and any(c['gripper_opening']>.5 for c in commands.values()):self.plan['release_robot']={a:self.robot[a]['grasp'].copy() for a in self.plan['arms']}
            self.debug.update(jev_request=dict(composed_summary=True,state=state,questions=questions,actual_requests_saved_separately=True),jev_response=raw,jev_choices=decisions,axis_amplitudes=amplitudes,
                phase_candidate=next_stage,phase_evidence=evidence,orientation_safety_gate=self.debug.get('orientation_motion_masks',{}))
            self.history.append(dict(event='Jev_decision',stage=self.stage,choices=decisions,native_step=self.last_native))
            if targets and phase=='stay':self.last_motion=dict(stage=self.stage,grasp={a:self.robot[a]['grasp'].copy() for a in targets},target=copy.deepcopy(targets),delta={a:commands[a]['delta_xyz_m'].copy() for a in targets})
            blocked=self._motion_guard(commands)
            if blocked:return self._result(stop=True,reason='external motion safety veto: '+blocked,ticks=1)
            if phase=='retry':
                self.grasp_retries+=1;self.grasp_evidence=[]
                self.plan['baseline']=None;self.plan['grasp_verified']=False
                self.rules['grasp_depth_adjust_m']=-.003*self.grasp_retries
                self._accept_phase('approach',dict(Jev_selected_retry=True,attempt=self.grasp_retries,previous_evidence=evidence,depth_adjust_m=self.rules['grasp_depth_adjust_m']))
            if phase=='advance':self._accept_phase(next_stage,evidence)
            if self.stage=='done':return self._result(stop=True,reason='Jev declared task complete; native evaluator remains independent',ticks=1)
            ticks=2 if self.task=='match_and_pick_from_conveyor' or phase in ('advance','retry','reobserve') else 3
            if self.stage.startswith('conveyor_wait_'):ticks=10
            return self._result(commands,reason='Jev phase/gripper/sign decision',ticks=ticks)
        except Exception as exc:
            return self._result(stop=True,reason='controller error: '+type(exc).__name__+': '+str(exc)[:300],ticks=1)
