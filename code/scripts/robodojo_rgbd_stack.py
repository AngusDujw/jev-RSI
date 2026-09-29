"""Development visual stacking: RGB-D memory + operator stages + Jev XYZ.

No oracle RPC, object asset geometry, native reward, or audit file is a policy
input. Native termination ends execution; final native success is evaluator-only.
"""
import copy
import json
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation
from run_position_pilot import Jev, dump, state_for
from reliability_step import ReliabilityStep, distance_step
from rgbd_memory import BlockMemory


def run(rec, rpc, reset):
    from realman_jev.robodojo_rgb import RGBEvidence
    cfg = rec.cfg
    episode, tick = reset['episode_id'], reset['step_id']
    ended, frame_index = False, 0
    model = Jev(rec)
    optimizer = ReliabilityStep(cfg['optimizer'])
    mode = cfg['step_controller']
    history = []
    status = 'running'
    memory = None
    moving_id = None
    predicted_center = None
    stage = 'initialize'

    def call(op, **kw):
        return rpc.request(op, episode_id=episode, step_id=tick, **kw)

    def observe():
        nonlocal frame_index
        rec.check_budget()
        c = call('rgbd_observation')
        folder = rec.folder/f'frame-{frame_index:04d}'
        folder.mkdir()
        for name, view in c['cameras'].items():
            Image.fromarray(np.asarray(view['rgb'])).save(folder/f'{name}.png')
            np.save(folder/f'{name}-depth.npy', view['depth_m'])
        dump(folder/'sensor_metadata.json', dict(native_step=tick, stage=stage, robot=c['robot'],
            gripper_bias_m=c['gripper_bias_m'], env_origin=c['env_origin'],
            calibration={n:{k:v for k,v in x.items() if k not in ('rgb','depth_m')} for n,x in c['cameras'].items()}))
        if memory is not None:
            predictions = {moving_id: predicted_center} if moving_id is not None and predicted_center is not None else {}
            memory.update(c, predictions)
            dump(folder/'visual_memory.json', memory.objects)
        frame_index += 1
        return c

    def hand(c, i):
        robot = c['robot']
        q = np.asarray(robot['eef_quaternions_wxyz'][i])
        return np.asarray(robot['eef_positions'][i])+Rotation.from_quat(q[[1,2,3,0]]).apply([c['gripper_bias_m'][i],0,0])

    def execute(c, arm_i, nominal, quat, grip, ticks, stage_name, decision_id=None, joints=None):
        nonlocal tick, ended, predicted_center
        robot = c['robot']
        targets = {name:dict(position=robot['eef_positions'][i],
                   quaternion_wxyz=robot['eef_quaternions_wxyz'][i],
                   gripper_opening=robot['states'][i*7+6], gripper_closed=robot['states'][i*7+6]<.5)
                   for i,name in enumerate(('left','right'))}
        if arm_i is not None:
            offset = Rotation.from_quat(np.asarray(quat)[[1,2,3,0]]).apply([c['gripper_bias_m'][arm_i],0,0])
            targets[('left','right')[arm_i]].update(position=(np.asarray(nominal)-offset).tolist(),
                quaternion_wxyz=np.asarray(quat).tolist(), gripper_opening=grip, gripper_closed=grip<.5)
        acks = []
        for _ in range(ticks):
            rec.check_budget()
            if ended:
                break
            proposal = call('eef_joint_target', targets=targets) if joints is None else None
            command = np.asarray(proposal['action'] if proposal else joints, np.float32)
            if arm_i is not None:
                other = 0 if arm_i else 7
                command[other:other+7] = robot['states'][other:other+7]
            ack = call('chunk_step', actions=command.reshape(1,14), controller='jev_rsi_rgbd_stack')
            tick = ack['step_id']
            acks.append(dict(step_id=tick, action=command, ik=proposal, steps=ack['steps']))
            ended = any(s['terminated'] or s['truncated'] for s in ack['steps'])
        # Prediction is a search gate only. Do not call it a measured block pose.
        if moving_id is not None and arm_i is not None and predicted_center is not None:
            last_robot = call('rgbd_observation')['robot']
            q = np.asarray(last_robot['eef_quaternions_wxyz'][arm_i])
            new_hand = np.asarray(last_robot['eef_positions'][arm_i])+Rotation.from_quat(q[[1,2,3,0]]).apply([c['gripper_bias_m'][arm_i],0,0])
            predicted_center = predicted_center+new_hand-hand(c,arm_i)
        after = observe()
        rec.branch(dict(kind='rgbd_stack_action', stage=stage_name, decision_id=decision_id,
            native_step=tick, before_robot=robot, after_robot=after['robot'], targets=targets, acks=acks,
            stable=None, settling_protocol='fixed_3_native_ticks_NOT_certified_stable'))
        return after

    try:
        current = observe()
        vcfg = json.loads((Path(cfg['existing_root'])/'controller/config/company-stack-study.json').read_text())['vision']
        vcfg.update(device=f"cuda:{cfg['gpu']}", phrases=['block'], include_instruction=False, max_instances=8)
        detector = RGBEvidence(vcfg)
        rgb = dict(current['robot'], instruction=current['instruction'])
        rgb.update({k:v['rgb'] for k,v in current['cameras'].items()})
        evidence = detector.observe(rgb)
        dump(rec.folder/'initial_rgb_evidence.json', evidence)
        dump(rec.folder/'perception_config.json', vcfg)
        memory = BlockMemory(current, evidence)
        dump(rec.folder/'initial_visual_geometry.json', dict(table_z=memory.table_z, objects=memory.objects))
        home = current['robot']['states']
        # Deterministic observable order: brightest block supports other colors.
        ids = sorted(memory.objects, key=lambda k:-float(np.mean(memory.objects[k]['rgb'])))
        support = ids[0]
        plan = dict(objects=ids, instruction=current['instruction'], source='operator_defined_RGBD_cuboid_scaffold',
            stages=['approach','descend','close','lift','carry','lower','release','retreat','return_home'],
            assumptions=['upright cuboids on dominant horizontal plane','uncontacted objects stationary',
                         'occluded static visual memory max90_native_ticks','attached prediction is search gate only'],
            model_controlled=['x_sign','y_sign','z_sign'],
            rule_controlled=['visual geometry','order','orientation','gripper','stages'], controller=mode)
        dump(rec.folder/'stack_plan.json', plan)
        for oid in ids[1:]:
            obj = memory.objects[oid]
            start_center = np.asarray(obj['center']).copy()
            i = int(start_center[0]>=0)
            desired = Rotation.from_euler('z', obj['yaw'])*Rotation.from_euler('y', np.pi/2)
            quat = desired.as_quat()[[3,0,1,2]]
            travel_z = max(start_center[2]+cfg['stack_clearance_m'], memory.objects[support]['top'][2]+obj['height']/2+cfg['stack_clearance_m'])
            held_offset = np.zeros(3)
            moving_id = None
            predicted_center = None
            for stage in plan['stages'][:-1]:
                if ended:
                    status='native_episode_ended'; break
                optimizer.reset()
                current=observe()
                obj=memory.objects[oid]
                dst=memory.objects[support]
                p=hand(current,i)
                rec.event(dict(kind='visual_stage_enter',stage=stage,object_id=oid,support_id=support,
                    native_step=tick,visual_objects=memory.objects,controller=mode))
                if stage in ('approach','descend','close') and tick-obj['last_seen_tick']>cfg['visual_max_age_ticks']:
                    status='visual_memory_expired'; break
                if stage in ('close','release'):
                    current=execute(current,i,p,quat,0. if stage=='close' else 1.,cfg['stack_gripper_ticks'],stage)
                    if stage=='close':
                        moving_id=oid
                        predicted_center=np.asarray(obj['center']).copy()
                    continue
                if stage=='approach': target=np.r_[obj['center'][:2],travel_z]
                elif stage=='descend': target=np.asarray(obj['center']).copy()
                elif stage=='lift': target=np.r_[p[:2],travel_z]
                elif stage=='carry': target=np.r_[np.asarray(dst['center'])[:2]-held_offset[:2],travel_z]
                elif stage=='lower': target=np.r_[dst['center'][:2],dst['top'][2]+obj['height']/2+cfg['stack_release_gap_m']]-held_offset
                else:
                    target=p+[0,0,cfg['stack_clearance_m']]
                    # Released object is stationary; stop attachment extrapolation.
                    moving_id=None
                target=np.asarray(target)
                target_source=dict(object_id=oid,support_id=support,visual_objects=copy.deepcopy(memory.objects),
                    uncertainty='empirical floor, not certified error bound')
                dump(rec.folder/f'target-{oid.replace(":","_")}-{stage}.json',dict(target=target,source=target_source))
                reached=False
                for attempt in range(cfg['stack_stage_max_decisions']):
                    p=hand(current,i)
                    error=target-p
                    if np.max(np.abs(error))<=cfg['axis_tolerance_m']:
                        reached=True; break
                    if ended or len(rec.decisions)>=cfg['max_jev_decisions']:
                        break
                    if stage in ('approach','descend') and tick-memory.objects[oid]['last_seen_tick']>cfg['visual_max_age_ticks']:
                        status='visual_memory_expired'; break
                    state=state_for(p,target,stage,cfg,arm=('left','right')[i],visual_id=oid,
                        gripper_opening=float(current['robot']['states'][i*7+6]),
                        target_source='RGBD_visual_memory_and_operator_stage_geometry',
                        visual_last_seen_native_step=memory.objects[oid]['last_seen_tick'])
                    state.update(observation_source='RGB_D_plus_robot_feedback_NO_object_truth',
                        coordinate_frame='environment_origin_nominal_grasp_m',history=history[-3:])
                    decision=model.choose(state,dict(stage=stage,environment='robodojo',trajectory_id=episode,
                        native_step=tick,object_id=oid,controller=mode))
                    floor=cfg['optimizer']['noise_floor_m']
                    # Fixed stage target: only its source-frame uncertainty applies.
                    uncertainty=[min(.004,max(floor,target_source['visual_objects'][oid]['spread_m']))]*3
                    proposal=(optimizer.propose(error.tolist(),decision['signs'],uncertainty)
                              if mode=='reliability_axis' else distance_step(error,decision['signs'],cfg['stack_step_m'],cfg['stack_gain']))
                    delta=np.asarray(proposal['delta_m'])
                    call('audit_before',decision=len(rec.decisions)-1,declaration=dict(stage=stage,
                        decision_id=decision['decision_id'],visual_id=oid,target=target.tolist()))
                    after=execute(current,i,p+delta,quat,1. if stage in ('approach','descend','retreat') else 0.,
                        cfg['stack_motion_ticks'],stage,decision['decision_id'])
                    call('audit_after',execution=dict(delta_m=delta.tolist(),native_step=tick))
                    feedback=optimizer.update(p.tolist(),hand(after,i).tolist(),target.tolist(),delta.tolist())
                    row=dict(stage=stage,decision_id=decision['decision_id'],native_step=tick,
                        error_before_m=float(np.linalg.norm(error)),error_after_m=float(np.linalg.norm(target-hand(after,i))),
                        proposal=proposal,feedback=feedback)
                    dump(rec.folder/decision['decision_id']/'step.json',row)
                    history.append(row)
                    current=after
                    print(f"{mode} {oid} {stage} calls={len(rec.decisions)} tick={tick} error={row['error_after_m']:.5f}",flush=True)
                if not reached:
                    reached=bool(np.max(np.abs(target-hand(current,i)))<=cfg['axis_tolerance_m'])
                rec.event(dict(kind='visual_stage_end',stage=stage,object_id=oid,reached=reached,native_step=tick))
                if not reached:
                    if status=='running': status=f'stage_not_reached:{stage}'
                    break
                if stage=='lift':
                    obj=memory.objects[oid]
                    measured=np.asarray(obj['last_measurement'])
                    evidence_ok=(obj['observed'] and measured[2]-start_center[2]>.025
                                 and np.linalg.norm(measured-hand(current,i))<.055)
                    rec.event(dict(kind='visual_grasp_check',observed=obj['observed'],passed=bool(evidence_ok),
                        measured=measured,initial=start_center,views=obj['views'],native_step=tick))
                    if not evidence_ok:
                        status='visual_grasp_not_verified'; break
                    held_offset=measured-hand(current,i)
                if stage=='retreat':
                    # Fresh release geometry required before using it as support.
                    memory.update(current,{oid:predicted_center})
                    if not memory.objects[oid]['observed']:
                        status='released_object_not_visible'; break
            if status!='running': break
            support=oid
        if status=='running':
            stage='return_home'
            execute(current,None,None,None,None,cfg['stack_home_ticks'],stage,joints=home)
            status='stages_finished'
    finally:
        model.close()
        final=call('finish_pilot',reason=status)
        dump(rec.folder/'native_finish.json',final)
        dump(rec.folder/'stack_result.json',dict(status=status,native=final,decisions=len(rec.decisions),
            steps=tick,controller=mode,frames=frame_index,
            interpretation='RGBD empirical visual memory; operator stage/orientation/gripper; native success only'))
