"""Jev owns XYZ, gripper and phase transitions. Sensor-only structured state.
Task scaffold defines phase vocabulary and candidate geometric goals, not choices.
"""
import json,hashlib,time
from pathlib import Path
import cv2
import numpy as np
from run_position_pilot import Jev,dump,append,direction_metrics,serial
from libero_generic_vision import GenericVision

PHASES=['approach','align','descend','grasp','lift','carry','lower','release','retreat']
NOTES={
'approach':'Approach above source with gripper open. Advance when the target is reached.',
'align':'Align to refreshed grasp site at clearance height, gripper open. Advance when aligned.',
'descend':'Descend to the supplied grasp site, gripper open. Advance to grasp when within tolerance; if stalled, reobserve rather than repeat.',
'grasp':'Hold TCP still and close gripper. Continue until close commands executed for at least 16 native ticks. Then advance to test lift; closure alone is not proof of holding.',
'lift':'Lift with gripper closed. Advance only after reaching lift target AND valid fresh visual co-motion evidence. If evidence unavailable request reobserve or stop.',
'carry':'Move held source above receiver; keep gripper closed. Advance after arrival and valid visual holding evidence.',
'lower':'Lower held object to release pose, keep gripper closed. Advance after arrival; never open during transit.',
'release':'Hold TCP still and open gripper. Continue until opening is at least 70mm and open commands executed for at least 24 native ticks, then advance.',
'retreat':'Withdraw upward with gripper open. Advance after arrival to finish attempt. This is not a task success claim.'}

class DecisionModel(Jev):
    def decide(self,state):
        self.rec.check_budget();i=len(self.rec.decisions)
        if i>=self.rec.cfg['max_jev_decisions']:raise RuntimeError('Jev decision budget')
        folder=self.rec.folder/f'decision-{i:04d}';folder.mkdir()
        questions={a:dict(type='choice',instructions=f'Select {a.upper()} direction toward current phase goal using observed error. Hold within tolerance. During gripper-only phases grasp/release always hold all XYZ.',criteria=dict(negative='Decrease coordinate',hold='No displacement',positive='Increase coordinate')) for a in 'xyz'}
        if state.get('rotation_control'):
            for a in ['rx','ry','rz']:
                questions[a]=dict(type='choice',instructions=f'For {a} read required_rotation_world_rad[{a}]. This is target relative to current (NOT current minus target). Positive value means choose positive rotation; negative value means negative rotation. hold if magnitude below 0.03 radians. Do NOT negate the supplied required rotation. Only this axis, not other axes.',criteria=dict(negative='Negative world-axis rotation',hold='No rotation',positive='Positive world-axis rotation'))
        questions['gripper']=dict(type='choice',instructions='You control the gripper. Open during approach/align/descend; close during grasp/lift/carry/lower; open during release/retreat. keep preserves last motor command. Choose based on current phase and feedback, not the next phase.',criteria=dict(open='Command open',close='Command close',keep='Keep prior commanded gripper state'))
        questions['transition']=dict(type='choice',instructions='You own the phase switch. Use the phase contract and measured feedback. Continue while target not reached or required gripper ticks incomplete. Advance only when the current contract is met. For stalled motion or missing visual holding evidence reobserve; if recovery budget unavailable stop. This choice is applied AFTER current actions, and does not declare task success.',criteria=dict(continue_phase='Remain in this phase and execute selected motion/gripper',advance='Finish current phase and enter next predefined phase',reobserve='Remain, refresh permitted visual measurement once if budget allows',stop='Terminate incomplete attempt'))
        payload=dict(model=self.api.cfg['model'],state=state,questions=questions)
        dump(folder/'request.json',payload)
        row=dict(decision_id=f'decision-{i:04d}',stage=state['stage'],observation=state,prompt_version='supervisor-'+self.rec.cfg['schema'],request_sha256=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest())
        self.rec.decisions.append(row);start=time.monotonic()
        try:
            raw=self.api.post('/systemone',payload);dump(folder/'response.json',raw)
            answers=raw['answers']
            for name,q in questions.items():
                a=answers[name];p=a['probabilities']
                if a['choice'] not in q['criteria'] or set(p)!=set(q['criteria']) or not all(np.isfinite(x) and 0<=x<=1 for x in [a['confidence'],*p.values()]) or abs(sum(p.values())-1)>.02:raise ValueError('Invalid Jev decision')
            signs=[dict(negative=-1,hold=0,positive=1)[answers[a]['choice']] for a in 'xyz']
            row.update(rotation_signs=[dict(negative=-1,hold=0,positive=1)[answers[a]['choice']] for a in ['rx','ry','rz']] if state.get('rotation_control') else [0,0,0],answers=answers,signs=signs,model=raw.get('model'),gripper=answers['gripper']['choice'],transition=answers['transition']['choice'],metrics=direction_metrics(state['position_m'],state['target_position_m'],signs,state['hold_tolerance_m']))
        except Exception as exc:
            row['error']=str(exc).replace(self.api.credential,'[redacted]');self.rec.errors.append(dict(type=type(exc).__name__));raise
        finally:
            row['request_seconds']=time.monotonic()-start;dump(folder/'decision.json',row);append(self.rec.folder/'decisions.jsonl',row)
        return row


def run_supervisor(env,obs,rec,task,depth_fn,k_fn,t_fn):
    vision=GenericVision(rec);model=DecisionModel(rec)
    from scipy.spatial.transform import Rotation
    side=rec.cfg.get('approach_mode')=='side'
    phases=list(PHASES)
    if side:phases.insert(phases.index('grasp'),'insert')
    notes=dict(NOTES,insert='Insert horizontally at the observed grasp height with gripper open; advance when target reached. Do not close before arrival.')
    initial_source_extent=None
    orientation_goal=(Rotation.from_rotvec([0,np.pi/2,0])*Rotation.from_quat(obs['robot0_eef_quat'])).as_matrix() if side else None
    ticks=0;phase=0;stage_ticks=0;stage_decisions=0;gripper=-1;gripper_ticks=0
    history=[];stalls=0;last_progress=None;error_message=None;holding=dict(valid=False,reason='not yet tested')
    src=dst=sem=None;grasp=None;hover=None;offset=None;place=None;tcp_grasp=None;source_grasp=None
    last_verification_tick=-1;reobserved=False;start_tcp=obs['robot0_eef_pos'].copy();finished=False
    def views():
        return {c:dict(rgb=np.ascontiguousarray(obs[c+'_image'][::-1]),depth=depth_fn(env.sim,obs[c+'_depth'])[::-1].squeeze(),K=k_fn(env.sim,c,obs[c+'_image'].shape[0],obs[c+'_image'].shape[1]),T=t_fn(env.sim,c)) for c in ['agentview','robot0_eye_in_hand']}
    def save(label):
        for cam,v in views().items():cv2.imwrite(str(rec.folder/f'{ticks:04d}-{label}-{cam}.png'),cv2.cvtColor(v['rgb'],cv2.COLOR_RGB2BGR))
    def locate(reason):
        vv=views();ss=vision.recognize(vv,task.language,reason);gg={}
        for role in ['source','destination']:
            x=ss[role];gg[role]=vision.measure(vv[x['camera']],x['bbox'],x['label'],reason+'-'+role)
        dump(rec.folder/(reason+'-geometry.json'),gg);return ss,gg['source'],gg['destination']
    def grasp_target():
        # Only robot geometry, public/proprioceptive; never object sim geom.
        robot=env.robots[0];names=robot.gripper.important_geoms
        pads=[np.mean([env.sim.data.geom_xpos[env.sim.model.geom_name2id(n)] for n in names[key]],axis=0) for key in ['left_fingerpad','right_fingerpad']]
        axis=(pads[1]-pads[0])[:2];axis=axis/max(np.linalg.norm(axis),1e-9)
        extent=src['high']-src['low'];p=src['center'].copy();width=float(abs(axis)@extent[:2])
        if width>.065:p[:2]+=(1 if (start_tcp[:2]-p[:2])@axis>0 else -1)*.9*width/2*axis
        p[2]=src['low'][2]+rec.cfg.get('grasp_fraction',.4)*extent[2]
        if rec.cfg.get('geometry_profile')=='observed_surfaces' and extent[2]<.025 and (initial_source_extent is None or initial_source_extent[2]<.025) and not side:
            p[2]=src['high'][2]+.023  # empirical own gripper low-object clearance; visible estimate only
        if side:p[2]=src['high'][2]+.004
        dump(rec.folder/f'grasp-{vision.calls}.json',dict(target=p,axis=axis,width=width,source='visible geometry + own gripper span'))
        return p
    def measure_held():
        nonlocal holding,offset,last_verification_tick
        if last_verification_tick==ticks:return
        last_verification_tick=ticks
        vv=views();cam='robot0_eye_in_hand';v=vv[cam]
        expected=source_grasp+(obs['robot0_eef_pos']-tcp_grasp)
        cp=v['T'][:3,:3].T@(expected-v['T'][:3,3])
        try:
            if rec.cfg.get('lift_check') and 'lift_check' not in vision.reasons and vision.calls<3:
                ss=vision.recognize(vv,task.language,'lift_check');o=ss['source'];cam=o['camera'];v=vv[cam]
                h=vision.measure(v,o['bbox'],o['label'],'semantic-held-validation')
            else:
                h=None
            if cp[2]<=.02:raise RuntimeError('projected object behind camera')
            uv=(v['K']@cp)[:2]/cp[2];size=np.clip(max(src['high']-src['low'])*v['K'][0,0]/cp[2],30,250)
            b=np.r_[uv-size*.65,uv+size*.65].clip(0,v['rgb'].shape[0]-1).tolist()
            if h is None:h=vision.measure(v,b,sem['source']['label'],'held-validation')
            valid=bool(h['low'][2]-source_grasp[2]>.015 and h['high'][2]-h['low'][2]<max(.06,1.8*(src['high'][2]-src['low'][2])) and np.linalg.norm(h['center']-expected)<.06)
            holding=dict(valid=valid,source='RGB-D co-motion proxy, not ground truth',measured=h,expected=expected,observed_tick=ticks)
            if valid:offset=h['center']-obs['robot0_eef_pos']
        except Exception as e:holding=dict(valid=False,reason=str(e),observed_tick=ticks)
        dump(rec.folder/f'holding-{ticks:04d}.json',holding)
    try:
        sem,src,dst=locate('initial');initial_source_extent=src['high']-src['low'];grasp=grasp_target();hover=max(src['high'][2],dst['high'][2])+.14
        while phase<len(phases):
            stage=phases[phase];rec.check_budget()
            if ticks>=550 or stage_decisions>=45:raise RuntimeError('Stage/native budget: '+stage)
            if stage=='approach':target=np.r_[src['center'][:2]+(np.array([.13,0]) if side else 0),hover]
            elif stage=='align':target=np.r_[grasp[:2]+(np.array([.13,0]) if side else 0),hover]
            elif stage=='descend':target=grasp+(np.array([.13,0,0]) if side else 0)
            elif stage=='insert':target=grasp
            elif stage in ['grasp','release']:target=obs['robot0_eef_pos'].copy()
            elif stage=='lift':target=np.r_[tcp_grasp[:2],hover]
            elif stage in ['carry','retreat']:target=np.r_[dst['center'][:2]-(offset[:2] if offset is not None else 0),hover]
            elif stage=='lower':
                height=(src['high'][2]-src['low'][2])/2
                target=np.r_[dst['center'][:2]-offset[:2],dst['high'][2]+height+.012-offset[2]]
            position=obs['robot0_eef_pos'].copy();error=target-position
            if stage in ['lift','carry'] and np.max(abs(error))<.008:measure_held()
            state=dict(task=task.language,stage=stage,next_phase=phases[phase+1] if phase+1<len(phases) else 'finish_attempt',phase_contract=notes[stage],
                position_m=position.tolist(),target_position_m=target.tolist(),error_m=error.tolist(),hold_tolerance_m=.004,arrival_tolerance_m=.008,
                gripper_qpos_m=obs['robot0_gripper_qpos'].tolist(),last_gripper_command='open' if gripper==-1 else 'close',
                current_phase_gripper_ticks=gripper_ticks,gripper_aperture_mm=float(np.sum(abs(obs['robot0_gripper_qpos']))*1000),phase_native_ticks=stage_ticks,phase_decisions=stage_decisions,
                holding_evidence=holding if stage in ['lift','carry','lower','release','retreat'] else dict(valid=None,reason='not tested before lift'),
                geometry_source='RGB-D visible masks, not true object poses',source_label=sem['source']['label'],destination_label=sem['destination']['label'],
                recovery_remaining=not reobserved and vision.calls<3,last_progress_m=last_progress,stalls=stalls)
            if rec.cfg['schema']=='feedback':
                observed=holding.get('observed_tick') is not None
                check_status=('passed' if holding.get('valid') else 'failed') if observed else 'not_checked_yet'
                if not observed:state['holding_evidence']=dict(valid=None,status=check_status,reason='Co-motion test becomes available on arrival at lift height, not before')
                state['measurement_status']=dict(target_arrival=bool(np.max(abs(error))<.008),holding_check=check_status,
                    gripper_actuation_complete=bool(gripper_ticks>=16),reobserve_available=state['recovery_remaining'],
                    observation_age_native_steps=ticks-(holding.get('observed_tick') or ticks))
                state['decision_protocol']='At lift while still far from lift target, holding check not_checked_yet is normal: keep closed and move, not a failure. Reobserve only after at least 3 stalled actions or an actual failed visual check; do not reobserve because a future check is pending. Never request reobserve when unavailable. At grasp/release continue chosen close/open until the phase contract duration and aperture requirements are met. Advance is your choice when the current phase contract is met.'
                state.update(error_mm=np.round(error*1000,2).tolist(),axis_relations={a:('within tolerance' if abs(e)<.004 else 'target higher coordinate' if e>0 else 'target lower coordinate') for a,e in zip('xyz',error)},
                    max_error_mm=float(np.max(abs(error))*1000),phase_goal_distance_mm=float(np.linalg.norm(error)*1000),
                    recent_actions=history[-3:],gripper_aperture_mm=float(np.sum(abs(obs['robot0_gripper_qpos']))*1000),
                    feedback_note='valid=False holding is NOT success; gripper tick count is measured execution, not a recommended answer')
            rotation_error=np.zeros(3)
            if side:
                rotation_error=Rotation.from_matrix(orientation_goal@Rotation.from_quat(obs['robot0_eef_quat']).as_matrix().T).as_rotvec()
                state.update(rotation_control=True,required_rotation_world_rad=dict(zip(['rx','ry','rz'],rotation_error.tolist())),rotation_relations={a:('hold' if abs(e)<.03 else 'target needs positive rotation' if e>0 else 'target needs negative rotation') for a,e in zip(['rx','ry','rz'],rotation_error)},rotation_tolerance_rad=.03,
                    orientation_arrived=bool(np.max(abs(rotation_error))<.03))
                state['phase_contract']+=' Before advancing any positioning phase, also require orientation_arrived. Rotation is commanded by your rx/ry/rz choices.'
            state=json.loads(json.dumps(state,default=serial,allow_nan=False))
            d=model.decide(state);stage_decisions+=1
            if d['transition']=='stop':raise RuntimeError('Jev elected stop')
            selected=d['gripper'];newgrip=gripper if selected=='keep' else -1 if selected=='open' else 1
            if newgrip!=gripper:gripper_ticks=0
            gripper=newgrip
            delta=np.asarray(d['signs'])*np.minimum(.02,.5*abs(error))
            # Gripper phase targets equal current TCP -> zero amplitude irrespective of signs.
            before=position.copy()
            for _ in range(3):
                if ticks>=550:raise RuntimeError('native budget')
                rotation=np.array(d['rotation_signs'])*np.minimum(.12,.5*abs(rotation_error))
                obs,_,_,_=env.step(np.r_[delta/.05,rotation/.5,gripper]);ticks+=1;stage_ticks+=1;gripper_ticks+=1
            after=obs['robot0_eef_pos'].copy();last_progress=float(np.linalg.norm(error)-np.linalg.norm(target-after));stalls=stalls+1 if np.linalg.norm(after-before)<.0008 and np.linalg.norm(error)>.015 else 0
            event=dict(stage=stage,decision_id=d['decision_id'],delta=delta,before=before,after=after,native_steps=ticks,
                       selected_gripper=selected,executed_gripper=gripper,rotation_signs=d['rotation_signs'],rotation_error_rad=rotation_error,selected_transition=d['transition'],progress_m=last_progress)
            rec.branch(event);history.append(dict(gripper=selected,transition=d['transition'],progress_mm=round(last_progress*1000,2),actual_displacement_mm=np.round((after-before)*1000,2).tolist()));save(stage)
            if d['transition']=='reobserve':
                if reobserved or vision.calls>=3:raise RuntimeError('Jev requested exhausted reobserve budget')
                reobserved=True;sem,src,dst=locate('stalled');grasp=grasp_target();stalls=0
            if d['transition']=='advance':
                # No distance-driven automatic transitions: log every actual Jev-authorized edge.
                rec.event(dict(kind='phase_transition',from_stage=stage,to_stage=state['next_phase'],decision_id=d['decision_id']))
                if stage=='approach':sem,src,dst=locate('pregrasp');grasp=grasp_target()
                if stage=='grasp':tcp_grasp=obs['robot0_eef_pos'].copy();source_grasp=src['center'].copy()
                if stage=='lift' and offset is None:raise RuntimeError('Jev advanced without usable held-object geometry')
                phase+=1;stage_ticks=0;stage_decisions=0;gripper_ticks=0;stalls=0
        finished=True
    except Exception as e:
        error_message=str(e);rec.event(dict(kind='stop',reason=error_message))
    finally:
        # Evaluation only; hidden success never sent to decision maker.
        success=bool(env.check_success())
        dump(rec.folder/'result.json',dict(success=success,program_finished=finished,error=error_message,native_steps=ticks,jev_calls=len(rec.decisions),semantic_calls=vision.calls,deepseek_calls=0,schema=rec.cfg['schema'],ownership='Jev XYZ + gripper + transitions',stage=phases[phase] if phase<len(PHASES) else 'finished'))
        rec.finish('success' if success else 'failed');model.close();vision.close()
