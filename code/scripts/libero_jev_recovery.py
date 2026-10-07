"""Visible geometry, own-pad fit and Jev-owned recovery graph.
No hidden object poses, contact IDs, reward or task predicates enter decisions.
"""
import hashlib
import json
import os
import time
import cv2
import numpy as np
from scipy.spatial.transform import Rotation
from run_position_pilot import Jev, dump, append, serial, direction_metrics
from libero_generic_vision import GenericVision
from libero_robot_geometry import gripper_geometry, envelope

PHASES = ['select', 'approach', 'align', 'descend', 'grasp', 'test_lift', 'lift', 'carry', 'lower', 'release', 'retreat']


def fit_candidates(src, own, position, quaternion, level, points, cfg, failed_candidates):
    extent = src['high']-src['low']
    # Horizontal observed bounding range, no hidden object shape/PCA metadata.
    major = np.array([1.,0.,0.]) if extent[0] >= extent[1] else np.array([0.,1.,0.])
    minor = np.array([-major[1],major[0],0.])
    R = np.column_stack([major, -minor, [0.,0.,-1.]])
    current = Rotation.from_quat(quaternion).as_matrix()
    alternate = R @ Rotation.from_euler('z',np.pi).as_matrix()
    if np.linalg.norm(Rotation.from_matrix(alternate@current.T).as_rotvec()) < np.linalg.norm(Rotation.from_matrix(R@current.T).as_rotvec()):
        R = alternate
    angle = cfg['contact_angle_deg']*np.pi/180
    near = 1 if position[:2]@major[:2] > src['center'][:2]@major[:2] else -1
    R = Rotation.from_rotvec(minor*angle*near).as_matrix() @ R
    ee = envelope(own, R)
    c = []
    for i, extra in enumerate([0., .003, -.003]):
        overlap = cfg['pad_overlap_mm']/1000+extra
        if cfg['grasp_algorithm'] == 'legacy_clearance':
            z = src['high'][2]+.023
        else:
            z = src['high'][2]-overlap-ee['pad_low_offset'][2]
            z = max(z, level-ee['finger_low_z_offset']+cfg['table_margin_mm']/1000)
        target = np.r_[src['center'][:2]-ee['pad_center_offset'][:2], z]
        target[:2] += major[:2] * ([0.,-.012,.012][i])
        pad_low, pad_high = z+ee['pad_low_offset'][2],z+ee['pad_high_offset'][2]
        width = float(abs(minor[:2])@extent[:2])
        c.append(dict(id=f'candidate_{i}', target=target, orientation=R, visible_width_mm=width*1000,
                      estimated_pad_overlap_mm=max(0., min(pad_high,src['high'][2])-max(pad_low,src['low'][2]))*1000,
                      estimated_finger_table_clearance_mm=(z+ee['finger_low_z_offset']-level)*1000,
                      pad_z_interval_m=[pad_low,pad_high],support_z_m=level, support_pixels=points,
                      prior_failed=i in failed_candidates, source='Visible RGB-D bounds/support plane + own robot mesh; geometric estimate only'))
    return c


class RecoveryModel(Jev):
    def decide(self, state):
        self.rec.check_budget()
        i = len(self.rec.decisions)
        if i >= self.rec.cfg['max_jev_decisions']:
            raise RuntimeError('Jev decision budget')
        folder = self.rec.folder / f'decision-{i:04d}'
        folder.mkdir()
        questions = {a: dict(type='choice', instructions=f'Read ONLY translation_axes[{a}]. Compare that axis goal coordinate with its current coordinate: larger goal needs positive, smaller goal needs negative. If relation is within_tolerance choose hold. Do not use another axis. In select/grasp/release/recover_open choose hold.', criteria=dict(negative='Decrease coordinate', hold='No displacement', positive='Increase coordinate')) for a in 'xyz'}
        for a in ['rx', 'ry', 'rz']:
            if abs(state['required_rotation_world_rad'][a]) < .03:
                continue
            questions[a] = dict(type='choice', instructions=f'Read required_rotation_world_rad[{a}], TARGET relative to CURRENT. Do not negate. Hold within 0.03 radians.', criteria=dict(negative='Negative world rotation', hold='No rotation', positive='Positive world rotation'))
        questions['gripper'] = dict(type='choice', instructions='Choose the gripper from the CURRENT operation contract and measured aperture. Opening/closure alone does not prove holding. keep preserves your previous motor command. Hold closed during a carrying operation. Open when explicitly releasing or preparing an unheld source.', criteria=dict(open='Command open', close='Command close', keep='Preserve prior motor command'))
        questions['transition'] = dict(type='choice', instructions='Decide the operation edge from completion_evidence and allowed_transitions. advance only when the current contract is satisfied. A pending test is unknown, not failed. On a failed lift or >=3 blocked actions, choose retry if available to withdraw and prepare another candidate. Do not keep repeating a blocked command. stop if a failure cannot be recovered. The selected actions execute before the edge.', criteria=dict(continue_phase='Execute and remain', advance='Enter supplied next operation', retry='Withdraw and select another visible-geometry candidate', stop='End incomplete attempt'))
        if state['operation'] == 'select':
            choices={c['id']: 'Visible-geometry candidate '+c['id'] for c in state['candidates'] if not c['prior_failed']}
            questions['candidate'] = dict(type='choice', instructions='Select one of the available visible-geometry candidates now. Prefer adequate pad overlap and positive table clearance. This selection and your advance choice apply together. The previously displayed candidate is only a default, not a completed selection. These are geometric estimates, not tested success predictions.', criteria=choices)
        payload = dict(model=self.api.cfg['model'], state=state, questions=questions)
        dump(folder/'request.json', payload)
        row = dict(decision_id=f'decision-{i:04d}', stage=state['operation'], observation=state, prompt_version='recovery-'+self.rec.cfg['input_organization'], request_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
        self.rec.decisions.append(row)
        started = time.monotonic()
        try:
            raw = self.api.post('/systemone', payload)
            dump(folder/'response.json', raw)
            answers = raw['answers']
            if set(answers)!=set(questions):raise ValueError('Unexpected or missing Jev question answer')
            for name, q in questions.items():
                a = answers[name]
                p = a['probabilities']
                if a['choice'] not in q['criteria'] or set(p) != set(q['criteria']) or not all(np.isfinite(x) and 0 <= x <= 1 for x in [a['confidence'], *p.values()]) or abs(sum(p.values())-1) > .02:
                    raise ValueError('Invalid Jev decision')
            mapping = dict(negative=-1, hold=0, positive=1)
            signs = [mapping[answers[a]['choice']] for a in 'xyz']
            row.update(answers=answers, signs=signs, rotation_signs=[mapping[answers[a]['choice']] if a in answers else 0 for a in ['rx', 'ry', 'rz']], model=raw.get('model'), gripper=answers['gripper']['choice'], transition=answers['transition']['choice'], candidate=answers['candidate']['choice'] if 'candidate' in answers else 'not_requested', metrics=direction_metrics([state['translation_axes'][a]['current_coordinate_m'] for a in 'xyz'], [state['translation_axes'][a]['goal_coordinate_m'] for a in 'xyz'], signs, state['axis_hold_tolerance_mm']/1000))
        except Exception as exc:
            row['error'] = str(exc).replace(self.api.credential, '[redacted]') if self.api.credential else str(exc)
            self.rec.errors.append(dict(type=type(exc).__name__))
            raise
        finally:
            row['request_seconds'] = time.monotonic()-started
            dump(folder/'decision.json', row)
            append(self.rec.folder/'decisions.jsonl', row)
        return row


def run_recovery(env, obs, rec, task, depth_fn, k_fn, t_fn):
    vision = GenericVision(rec)
    model = RecoveryModel(rec)
    own = gripper_geometry(env, obs)
    dump(rec.folder/'own-gripper.json', own)
    ticks = stage_ticks = stage_decisions = grip_ticks = 0
    gripper = -1
    stage = 'select'
    selected = 0
    grasp_tries = 0
    failed_candidates = []
    history = []
    stalls = 0
    holding = dict(status='not_checked_yet', valid=None)
    offset = None
    tcp_grasp = source_grasp = test_target = recovery_target = None
    error_message = None
    finished = False
    initial_src = src = dst = identity = None
    cached_external = None

    def views():
        return {c: dict(rgb=np.ascontiguousarray(obs[c+'_image'][::-1]), depth=depth_fn(env.sim, obs[c+'_depth'])[::-1].squeeze(), K=k_fn(env.sim,c,obs[c+'_image'].shape[0],obs[c+'_image'].shape[1]), T=t_fn(env.sim,c)) for c in ['agentview','robot0_eye_in_hand']}

    def cloud(v):
        vv, uu = np.indices(v['depth'].shape)
        d, K, T = v['depth'], v['K'], v['T']
        return np.stack([(uu-K[0,2])*d/K[0,0], (vv-K[1,2])*d/K[1,1], d], -1) @ T[:3,:3].T + T[:3,3]

    def locate(reason):
        nonlocal identity, cached_external
        vv = views()
        identity = vision.recognize(vv, task.language, reason)
        result = {}
        for role in ['source','destination']:
            ob = identity[role]
            v = vv[ob['camera']]
            result[role] = vision.measure(v, ob['bbox'], ob['label'], reason+'-'+role)
            if role == 'source' and ob['camera'] == 'agentview':
                cached_external = dict(ob)
            if role == 'destination' and ob.get('receiver_kind') == 'open_container':
                uv = (np.asarray(ob['bbox'][:2])+ob['bbox'][2:])/2
                ray = v['T'][:3,:3] @ np.linalg.solve(v['K'], np.r_[uv,1.])
                distance = (result[role]['high'][2]-v['T'][2,3])/ray[2]
                if not 0 < distance < 3:
                    raise RuntimeError('Invalid visible receiver plane')
                result[role]['center'] = v['T'][:3,3] + distance*ray
        dump(rec.folder/(reason+'-geometry.json'), result)
        return result['source'], result['destination']

    def fuse(observed):
        if not rec.cfg['preserve_source']:
            return observed
        old_extent = initial_src['high']-initial_src['low']
        new_extent = observed['high']-observed['low']
        if np.any(new_extent[:2] < .7*old_extent[:2]) or new_extent[2] < .5*old_extent[2]:
            merged = dict(initial_src, partial_view=observed, source='Initial full visible bounds retained when fresh view is partial; no hidden dimensions')
            return merged
        return observed

    def support_level():
        v = views()['agentview']
        xyz = cloud(v)
        local = np.linalg.norm(xyz[:,:,:2]-src['center'][:2], axis=2) < .16
        outside = np.any((xyz[:,:,:2] < src['low'][:2]-.01) | (xyz[:,:,:2] > src['high'][:2]+.01), axis=2)
        good = local & outside & np.isfinite(v['depth']) & (abs(xyz[:,:,2]-src['low'][2]) < .06)
        z = xyz[:,:,2][good]
        if len(z) < 100:
            raise RuntimeError('Visible support unavailable')
        hist, edges = np.histogram(z, bins=120, range=(src['low'][2]-.06,src['low'][2]+.06))
        center = (edges[np.argmax(hist)]+edges[np.argmax(hist)+1])/2
        near = z[abs(z-center)<.003]
        return float(np.median(near)), int(len(near))

    def candidates():
        level, points = support_level()
        c = fit_candidates(src, own, obs['robot0_eef_pos'], obs['robot0_eef_quat'], level, points, rec.cfg, failed_candidates)
        dump(rec.folder/f'candidates-{grasp_tries:02d}.json',c)
        return c

    def check_hold():
        nonlocal holding, offset, src
        vv = views()
        expected = source_grasp+(obs['robot0_eef_pos']-tcp_grasp)
        if vision.static_mode:
            # The source can move after grasp. Reproject its expected position
            # instead of reusing the frozen initial image box.
            v = vv['agentview']
            camera = v['T'][:3,:3].T @ (expected-v['T'][:3,3])
            if camera[2] <= .02:
                raise RuntimeError('Expected lifted source behind camera')
            uv = (v['K'] @ camera)[:2] / camera[2]
            size = np.clip(np.max(initial_src['high']-initial_src['low'])*v['K'][0,0]/camera[2],35,220)
            box = np.r_[uv-size*.7,uv+size*.7].clip(0,767).tolist()
            ob = dict(camera='agentview',bbox=box,label=identity['source']['label'])
            dump(rec.folder/f'hold-projection-{ticks:04d}.json',dict(expected=expected,bbox=box))
        elif 'lift_check' not in vision.reasons and vision.calls < 3:
            ids = vision.recognize(vv, task.language, 'lift_check')
            ob = ids['source']
        else:
            ob = cached_external
        if ob is None:
            holding = dict(valid=None,status='unavailable',reason='No cached external source identity')
            return
        h = vision.measure(vv[ob['camera']],ob['bbox'],ob['label'],'test-lift-hold')
        rise = float(h['center'][2]-source_grasp[2])
        mismatch = float(np.linalg.norm(h['center']-expected))
        valid = rise > .015 and mismatch < .065 and h['high'][2]-h['low'][2] < max(.06,1.8*(initial_src['high'][2]-initial_src['low'][2]))
        holding = dict(valid=bool(valid),status='passed' if valid else 'failed',source='Visible RGB-D co-motion proxy',source_rise_mm=rise*1000,co_motion_error_mm=mismatch*1000,measured=h,expected=expected,observed_tick=ticks)
        if valid:
            offset = h['center']-obs['robot0_eef_pos']
        elif rise < .015:
            src = fuse(h)
        dump(rec.folder/f'holding-{ticks:04d}.json',holding)

    try:
        initial_src, dst = locate('initial')
        src = initial_src
        cs = candidates()
        hover = max(src['high'][2],dst['high'][2])+.12
        while True:
            rec.check_budget()
            if ticks >= 550 or stage_decisions >= 45:
                raise RuntimeError('Stage/native budget: '+stage)
            c = cs[selected]
            Rgoal = c['orientation']
            position = obs['robot0_eef_pos'].copy()
            if stage in ['select','grasp','release','recover_open']:
                target = position.copy()
            elif stage in ['approach','align']:
                target = c['target'].copy();target[2]=hover
            elif stage == 'descend':
                target = c['target'].copy()
            elif stage == 'test_lift':
                target = test_target
            elif stage == 'lift':
                target = np.r_[tcp_grasp[:2],hover]
            elif stage in ['carry','retreat']:
                target = np.r_[dst['center'][:2]-(offset[:2] if offset is not None else 0),hover]
            elif stage == 'lower':
                target = np.r_[dst['center'][:2]-offset[:2],dst['high'][2]+(initial_src['high'][2]-initial_src['low'][2])/2+.012-offset[2]]
            elif stage == 'recover_up':
                target = recovery_target
            else:
                raise ValueError(stage)
            error = target-position
            tol = .003 if stage == 'descend' else .006
            arrived = bool(np.max(abs(error)) < tol)
            rot = Rotation.from_matrix(Rgoal@Rotation.from_quat(obs['robot0_eef_quat']).as_matrix().T).as_rotvec()
            oriented = bool(np.max(abs(rot)) < .03)
            aperture = float(np.sum(abs(obs['robot0_gripper_qpos']))*1000)
            if stage == 'test_lift' and arrived and holding['status']=='not_checked_yet':
                check_hold()
                cs = cs  # candidate stays frozen through a grasp attempt
            required_open = stage in ['approach','align','descend','release','retreat','recover_open']
            required_close = stage in ['grasp','test_lift','lift','carry','lower']
            contracts = dict(select='Choose an unfailed candidate, then advance. Hold XYZ. Gripper open.',approach='Reach hover pose above candidate and align orientation with gripper open.',align='Reach refreshed hover pose/orientation with gripper open.',descend='Reach supplied pad-fit contact pose/orientation with gripper open. Retry when blocked.',grasp='Hold TCP, close for at least 18 native ticks, then advance to a short lift test. Closure is not holding proof.',test_lift='Keep closed and reach short lift goal. Advance only if measured holding passed. Retry if failed and budget remains.',lift='Keep closed and reach clearance height with passed holding evidence.',carry='Keep closed and reach pose over receiver with passed holding evidence.',lower='Keep closed and reach supplied release pose.',release='Hold TCP and open for at least 24 native ticks AND aperture >=70mm.',retreat='Withdraw upward with gripper open, then advance to end attempt.',recover_up='Withdraw to supplied clearance pose. Keep current grip until clear.',recover_open='Hold TCP and open for >=24 ticks AND aperture >=70mm, then advance to select another candidate.')
            complete = arrived and oriented
            if stage == 'select':complete=True
            if stage == 'grasp':complete=grip_ticks>=18 and gripper==1
            if stage in ['release','recover_open']:complete=grip_ticks>=24 and aperture>=70 and gripper==-1
            if stage == 'test_lift':complete=complete and holding['status']=='passed'
            can_retry = rec.cfg['allow_retry'] and grasp_tries<3 and stage not in ['select','release','retreat','recover_up','recover_open'] and (stalls>=3 or holding['status']=='failed')
            next_stage = 'select' if stage=='recover_open' else 'recover_open' if stage=='recover_up' else 'finish_attempt' if stage=='retreat' else PHASES[PHASES.index(stage)+1]
            state = dict(task=task.language,operation=stage,next_operation=next_stage,operation_contract=contracts[stage],position_m=position.tolist(),target_position_m=target.tolist(),target_minus_current_mm=np.round(error*1000,2).tolist(),axis_hold_tolerance_mm=2.,arrival_tolerance_mm=tol*1000,required_rotation_world_rad=dict(zip(['rx','ry','rz'],rot.tolist())),gripper=dict(aperture_mm=aperture,last_command='open' if gripper==-1 else 'close',executed_command_ticks=grip_ticks,required_state='open' if required_open else 'closed' if required_close else 'preserve',closure_nearly_empty=bool(aperture<3)),completion_evidence=dict(position_arrived=arrived,orientation_arrived=oriented,contract_satisfied=bool(complete),holding_status=holding['status'],gripper_command_ticks=grip_ticks),holding_evidence=holding,allowed_transitions=dict(continue_phase=True,advance=bool(complete),retry=bool(can_retry),stop=True),selected_candidate=c['id'],candidates=[{k:v for k,v in cc.items() if k not in ['orientation','target']} for cc in cs],failed_candidates=[f'candidate_{i}' for i in failed_candidates],grasp_attempts=grasp_tries,recent_actions=history[-3:],blocked_action_count=stalls,phase_decisions=stage_decisions,information_sources='Public task + rendered RGB-D/calibration + own robot proprioception/mesh. No scene truth/reward/success.')
            adaptive=rec.cfg.get('execution_profile','baseline')=='adaptive'
            block_ticks=6 if adaptive and (stage in ['grasp','release','recover_open'] or np.max(abs(error))>.06) else 3
            state['gripper']['next_action_block_native_ticks']=block_ticks
            state['translation_axes']={a:dict(current_coordinate_m=float(position[i]),goal_coordinate_m=float(target[i]),goal_minus_current_mm=round(float(error[i])*1000,2),relation='within_tolerance' if abs(error[i])<.002 else 'goal_coordinate_larger' if error[i]>0 else 'goal_coordinate_smaller') for i,a in enumerate('xyz')}
            state['rotation_questions']='Only axes outside 0.03rad tolerance are requested; unrequested rotations are zero, not fabricated model choices.'
            if rec.cfg['input_organization']=='local':
                state['local_decision_summary']=dict(operation=stage,xyz_error_mm=np.round(error*1000,2).tolist(),can_finish=bool(complete),holding=holding['status'],blocked=stalls>=3,can_retry=bool(can_retry),gripper_state_to_maintain=state['gripper']['required_state'])
            if rec.cfg['input_organization']=='evidence':
                state['evidence_interpretation']='contract_satisfied is a measured conjunction of the listed tests, not task success. failed holding means the source did not follow the robot; not_checked_yet means continue the pending test. Failed or blocked attempts may use retry. Pick candidates by physical overlap/clearance, never by index alone.'
            if rec.cfg['input_organization']=='focused':
                keep=['task','operation','next_operation','operation_contract','translation_axes','axis_hold_tolerance_mm','arrival_tolerance_mm','required_rotation_world_rad','gripper','completion_evidence','allowed_transitions','blocked_action_count','recent_actions','information_sources','grasp_attempts','failed_candidates','selected_candidate','phase_decisions']
                focused={k:state[k] for k in keep}
                focused['holding_evidence']={k:v for k,v in holding.items() if k in ['status','valid','source','source_rise_mm','co_motion_error_mm','observed_tick','reason']}
                if stage=='select':focused['candidates']=state['candidates']
                else:focused['selected_candidate_geometry']={k:c[k] for k in ['visible_width_mm','estimated_pad_overlap_mm','estimated_finger_table_clearance_mm']}
                state=focused
            state = json.loads(json.dumps(state,default=serial,allow_nan=False))
            d = model.decide(state);stage_decisions+=1
            if d['transition']=='stop':raise RuntimeError('Jev elected stop')
            if stage=='select':
                if d['candidate'].startswith('candidate_'):
                    selected=int(d['candidate'].split('_')[-1]);c=cs[selected]
                elif d['transition']=='advance':raise RuntimeError('Jev advanced without selecting candidate')
            newgrip=gripper if d['gripper']=='keep' else -1 if d['gripper']=='open' else 1
            if newgrip!=gripper:grip_ticks=0
            gripper=newgrip
            cap=(.02 if np.max(abs(error))>.05 else .006 if np.max(abs(error))>.015 else .003) if stage in ['descend','test_lift','lower'] else .02
            gain=.35 if block_ticks==6 else .5
            delta=np.asarray(d['signs'])*np.minimum(cap,gain*abs(error))
            rotation=np.asarray(d['rotation_signs'])*np.minimum(.10,gain*abs(rot))
            before=position.copy()
            if ticks+block_ticks>550:raise RuntimeError('Native block budget')
            for _ in range(block_ticks):
                obs,_,_,_=env.step(np.r_[delta/.05,rotation/.5,gripper]);ticks+=1;stage_ticks+=1;grip_ticks+=1
            after=obs['robot0_eef_pos'].copy()
            progress=float(np.linalg.norm(error)-np.linalg.norm(target-after))
            stalls=stalls+1 if np.linalg.norm(after-before)<.0008 and np.linalg.norm(error)>.008 else 0
            rec.branch(dict(stage=stage,decision_id=d['decision_id'],delta=delta,before=before,after=after,native_steps=ticks,selected_gripper=d['gripper'],executed_gripper=gripper,selected_transition=d['transition'],block_native_ticks=block_ticks,selected_candidate=c['id'],rotation_signs=d['rotation_signs'],rotation_error_rad=rot,progress_m=progress))
            history.append(dict(gripper=d['gripper'],transition=d['transition'],progress_mm=round(progress*1000,2),actual_displacement_mm=np.round((after-before)*1000,2).tolist()))
            for cam,v in views().items():cv2.imwrite(str(rec.folder/f'{ticks:04d}-{stage}-{cam}.png'),cv2.cvtColor(v['rgb'],cv2.COLOR_RGB2BGR))
            transition=d['transition']
            if transition=='retry':
                if not can_retry:raise RuntimeError('Jev requested unavailable retry')
                failed_candidates.append(selected)
                recovery_target=np.r_[after[:2],max(hover,after[2]+.06)]
                to_stage='recover_up'
                holding=dict(status='not_checked_yet',valid=None)
            elif transition=='advance':
                to_stage=next_stage
                if stage=='select':
                    if selected in failed_candidates:raise RuntimeError('Jev repeated failed candidate')
                    grasp_tries+=1
                if stage=='approach' and 'pregrasp' not in vision.reasons:
                    fresh, dst=locate('pregrasp');src=fuse(fresh);cs=candidates()
                if stage=='grasp':
                    tcp_grasp=obs['robot0_eef_pos'].copy();source_grasp=src['center'].copy();test_target=tcp_grasp+np.array([0.,0.,.05]);holding=dict(status='not_checked_yet',valid=None)
                if stage=='test_lift' and offset is None:raise RuntimeError('Jev advanced without holding evidence')
                if stage=='recover_open':cs=candidates()
            else:
                continue
            rec.event(dict(kind='phase_transition',from_stage=stage,to_stage=to_stage,decision_id=d['decision_id'],selected_transition=transition))
            stage=to_stage;stage_decisions=stage_ticks=grip_ticks=stalls=0
            if stage=='finish_attempt':finished=True;break
    except Exception as exc:
        error_message=str(exc);rec.event(dict(kind='stop',reason=error_message))
    finally:
        success=bool(env.check_success())  # Terminal evaluation only.
        backend='gpt-6-sol/xhigh via ChatGPT Codex' if os.environ.get('JEV_RSI_MODEL_BACKEND')=='codex_pro' else 'Jev'
        dump(rec.folder/'result.json',dict(success=success,program_finished=finished,error=error_message,native_steps=ticks,jev_calls=len(rec.decisions),model_control_calls=len(rec.decisions),semantic_calls=vision.calls,deepseek_calls=0,stage=stage,grasp_attempts=grasp_tries,failed_candidates=failed_candidates,ownership=backend+' XYZ/rotation/gripper/candidate/phase/retry',input_organization=rec.cfg['input_organization'],model_backend=backend))
        rec.finish('success' if success else 'failed');model.close();vision.close()
