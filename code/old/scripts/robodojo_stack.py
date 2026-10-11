"""Oracle staged stack: Jev XYZ signs, explicit operator geometry/phase scaffold.

Rotation, grasp geometry, phase gates and gripper are rule controlled and logged.
No reward is provided to Jev. Only native success counts as task completion.
"""
import numpy as np
from scipy.spatial.transform import Rotation
from run_position_pilot import Jev, dump, state_for


def run_stack(rec, rpc, reset):
    cfg = rec.cfg
    episode, tick = reset['episode_id'], reset['step_id']
    ended = False
    model = Jev(rec)
    history = []
    status = 'running'

    def call(op, **kw):
        return rpc.request(op, episode_id=episode, step_id=tick, **kw)

    def obs():
        return call('oracle_observation')

    def objects(e):
        return {o['id']: o for o in e['objects'] if o.get('category') == 'block'}

    def center(o):
        g = o['geometry']
        return (np.array(g['world_bbox_min_m'])+g['world_bbox_max_m'])/2

    def execute(arm, position=None, quaternion=None, gripper=None, ticks=None, stage='', decision_id=None, joints=None):
        nonlocal tick, ended
        before = obs()
        robot = before['robot']
        targets = {}
        for i, name in enumerate(('left','right')):
            targets[name] = dict(position=robot['eef_positions_m'][i],
                quaternion_wxyz=robot['eef_quaternions_wxyz'][i],
                gripper_opening=robot['states'][i*7+6], gripper_closed=robot['states'][i*7+6]<.5)
        if arm is not None:
            targets[arm].update(position=np.asarray(position).tolist(), quaternion_wxyz=np.asarray(quaternion).tolist())
            if gripper is not None:
                targets[arm].update(gripper_opening=gripper, gripper_closed=gripper<.5)
        acks = []
        for _ in range(ticks or cfg['stack_motion_ticks']):
            rec.check_budget()
            if ended:
                break
            proposal = call('eef_joint_target', targets=targets) if joints is None else None
            command = np.asarray(proposal['action'] if proposal else joints, np.float32)
            if arm is not None:
                other = 0 if arm == 'right' else 7
                command[other:other+7] = robot['states'][other:other+7]
            ack = call('chunk_step', actions=command.reshape(1,14), controller='jev_rsi_oracle_staged_stack')
            tick = ack['step_id']
            acks.append(dict(step_id=tick, action=command, ik=proposal, steps=ack['steps']))
            ended = any(r['terminated'] or r['truncated'] for r in ack['steps'])
        after = obs()
        row = dict(kind='stack_action', stage=stage, decision_id=decision_id, arm=arm,
                   native_step=tick, before=before, after=after, targets=targets, acks=acks,
                   stable=None, settling_protocol='fixed_ticks_NOT_certified_stable', paired=False)
        rec.branch(row)
        return after

    initial = obs()
    dump(rec.folder/'stack_initial.json', initial)
    home = initial['robot']['states']
    blocks = objects(initial)
    if len(blocks) != 3:
        raise RuntimeError(f'Expected three observed blocks, got {len(blocks)}')
    # Largest footprint supports the remaining objects; native reward is untouched.
    ids = sorted(blocks, key=lambda k: -float(np.prod(np.array(blocks[k]['geometry']['world_bbox_max_m'])[:2]-np.array(blocks[k]['geometry']['world_bbox_min_m'])[:2])))
    support = ids[0]
    plan = dict(version=cfg['stack_plan_version'], objects=ids,
        stages=['approach','descend','close','lift','carry','lower','release','retreat','return_home'],
        source='operator_defined_geometry_scaffold', observation='privileged_pose_and_asset_bbox',
        rule_controlled=['object_order','local_targets','orientation','gripper','stage_transitions'],
        model_controlled=['x_sign','y_sign','z_sign'], native_step_budget=550)
    dump(rec.folder/'stack_plan.json', plan)
    rec.event(dict(kind='stack_plan', plan=plan))
    try:
        for object_index, oid in enumerate(ids[1:]):
            entry = obs()
            block = objects(entry)[oid]
            start_center = center(block)
            arm_index = int(start_center[0] >= 0)
            arm = ('left','right')[arm_index]
            # Align closing Y with the block's local Y; approach X points down.
            oq = np.asarray(block['quaternion_wxyz'])[[1,2,3,0]]
            yaw = Rotation.from_quat(oq).as_euler('xyz')[2]
            desired = Rotation.from_euler('z', yaw)*Rotation.from_euler('y', np.pi/2)
            quat = desired.as_quat()[[3,0,1,2]]
            robot = entry['robot']
            bias = np.linalg.norm(np.asarray(robot['nominal_grasp_points_m'][arm_index])-robot['eef_positions_m'][arm_index])
            offset = desired.apply([bias,0,0])
            height = block['geometry']['world_bbox_max_m'][2]-block['geometry']['world_bbox_min_m'][2]
            top = objects(entry)[support]['geometry']['world_bbox_max_m'][2]
            travel_z = max(start_center[2]+cfg['stack_clearance_m'], top+height/2+cfg['stack_clearance_m'])
            held_offset = np.zeros(3)
            for stage in ['approach','descend','close','lift','carry','lower','release','retreat']:
                if ended:
                    status='native_episode_ended'; break
                current = obs()
                b = objects(current)
                c = center(b[oid]); dst = center(b[support])
                hand = np.asarray(current['robot']['nominal_grasp_points_m'][arm_index])
                rec.event(dict(kind='stack_stage_enter', stage=stage, object_id=oid, support_id=support,
                               native_step=tick, observation=current))
                if stage in ('close','release'):
                    eef = current['robot']['eef_positions_m'][arm_index]
                    execute(arm,eef,quat,0. if stage=='close' else 1., ticks=cfg['stack_gripper_ticks'],stage=stage)
                    continue
                if stage == 'approach': target=np.r_[c[:2],travel_z]
                elif stage == 'descend': target=c.copy()
                elif stage == 'lift': target=np.r_[hand[:2],travel_z]
                elif stage == 'carry': target=np.r_[dst[:2]-held_offset[:2],travel_z]
                elif stage == 'lower': target=np.r_[dst[:2],b[support]['geometry']['world_bbox_max_m'][2]+height/2+cfg['stack_release_gap_m']]-held_offset
                else: target=hand+[0,0,cfg['stack_clearance_m']]
                target = np.asarray(target)
                reached=False
                for attempt in range(cfg['stack_stage_max_decisions']):
                    if ended or len(rec.decisions)>=cfg['max_jev_decisions']:
                        break
                    current=obs(); hand=np.asarray(current['robot']['nominal_grasp_points_m'][arm_index])
                    error=target-hand
                    if np.max(np.abs(error)) <= cfg['axis_tolerance_m']:
                        reached=True; break
                    state=state_for(hand,target,stage,cfg,arm=arm,object_id=oid,destination_id=support,
                        object_index=object_index,complete_plan=plan,
                        object_center_m=center(objects(current)[oid]).tolist(),
                        gripper_opening=current['robot']['states'][arm_index*7+6],
                        stage_objective=f'{stage}: reach the supplied nominal finger-center target; external phase logic controls grasp and release.')
                    state.update(coordinate_frame='environment_origin_nominal_grasp_m',history=history[-3:],
                                 orientation_instruction='external rule aligns the gripper for top-down grasp; choose XYZ only')
                    decision=model.choose(state,dict(stage=stage,environment='robodojo',trajectory_id=episode,
                        native_step=tick,object_id=oid,layout_id=cfg['robodojo_layout_id'],plan_version=cfg['stack_plan_version']))
                    dump(rec.folder/decision['decision_id']/'native_state.json',current)
                    vector=np.asarray(decision['signs'],float)
                    norm=np.linalg.norm(vector)
                    if norm: vector/=norm
                    amplitude=min(cfg['stack_step_m'],np.linalg.norm(error)*cfg['stack_gain'])
                    nominal=hand+amplitude*vector
                    after=execute(arm,nominal-offset,quat,1. if stage in ('approach','descend','retreat') else 0.,stage=stage,decision_id=decision['decision_id'])
                    history.append(dict(stage=stage,signs=decision['signs'],amplitude_m=amplitude,
                        error_before_m=float(np.linalg.norm(error)),error_after_m=float(np.linalg.norm(target-np.asarray(after['robot']['nominal_grasp_points_m'][arm_index])))))
                    print(f'{oid} {stage} decision={len(rec.decisions)} tick={tick} error={history[-1]["error_after_m"]:.5f}',flush=True)
                if not reached:
                    current=obs()
                    reached=np.max(np.abs(target-np.asarray(current['robot']['nominal_grasp_points_m'][arm_index]))) <= cfg['axis_tolerance_m']
                rec.event(dict(kind='stack_stage_end',stage=stage,object_id=oid,reached=bool(reached),native_step=tick))
                if not reached:
                    status=f'stage_not_reached:{stage}'; break
                if stage=='lift':
                    current=obs(); lifted=center(objects(current)[oid])-start_center
                    held_offset=center(objects(current)[oid])-np.asarray(current['robot']['nominal_grasp_points_m'][arm_index])
                    rec.event(dict(kind='grasp_lift_evidence',object_id=oid,object_delta_m=lifted,object_minus_hand_m=held_offset))
                    if lifted[2]<.025 or np.linalg.norm(held_offset)>.05:
                        status='grasp_not_verified'; break
            if status!='running': break
            support=oid
        if status=='running':
            execute(None,ticks=cfg['stack_home_ticks'],stage='return_home',joints=home)
            status='stages_finished'
    finally:
        model.close()
        final=call('finish_pilot',reason=status)
        dump(rec.folder/'native_finish.json',final)
        dump(rec.folder/'stack_result.json',dict(status=status,native=final,decisions=len(rec.decisions),steps=tick,
            plan_version=cfg['stack_plan_version'],interpretation='oracle staged XYZ model policy; phase/orientation/gripper supplied by rules'))
