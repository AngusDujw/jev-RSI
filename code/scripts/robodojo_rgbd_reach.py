"""Bounded RGB-D approach-only rollout; no oracle object access in policy."""
import json
from pathlib import Path
import sys
import cv2
import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation
from probe_rgbd_jev import lift
from run_position_pilot import Jev, dump, state_for


def run(rec, rpc, reset):
    cfg = rec.cfg
    root = Path(cfg['existing_root'])
    sys.path.insert(0, str(root/'controller/src'))
    from realman_jev.robodojo_rgb import RGBEvidence
    vcfg = json.loads((root/'controller/config/company-stack-study.json').read_text())['vision']
    vcfg.update(device=f"cuda:{cfg['gpu']}", phrases=['block'], include_instruction=False, max_instances=8)
    detector = RGBEvidence(vcfg)
    dump(rec.folder/'perception_config.json', vcfg)
    episode, tick = reset['episode_id'], reset['step_id']
    model = Jev(rec)
    selected_id = None
    rows = []
    status = 'decision_budget'

    def call(op, **kw):
        return rpc.request(op, episode_id=episode, step_id=tick, **kw)

    try:
        for index in range(cfg['max_jev_decisions']+1):
            rec.check_budget()
            captured = call('rgbd_observation')
            folder = rec.folder/f'frame-{index:03d}'
            folder.mkdir()
            obs = dict(captured['robot'], instruction=captured['instruction'])
            for name, v in captured['cameras'].items():
                obs[name] = v['rgb']
                Image.fromarray(v['rgb']).save(folder/f'{name}.png')
                np.save(folder/f'{name}-depth.npy', v['depth_m'])
            evidence = detector.observe(obs)
            dump(folder/'evidence.json', evidence)
            head = captured['cameras']['cam_high']
            h,w = head['depth_m'].shape
            choices = []
            for d in evidence['views']['cam_high']['objects']:
                polygon = np.rint(np.asarray(d['contour_uv01'])*[w,h]).astype(np.int32)
                mask = np.zeros((h,w), np.uint8)
                cv2.fillPoly(mask, [polygon], 1)
                mask = cv2.erode(mask, np.ones((3,3), np.uint8)).astype(bool)
                points = lift(head['depth_m'], np.asarray(head['intrinsic']),
                    np.asarray(head['camera_to_world_opengl']), np.asarray(captured['env_origin']), mask)
                z = float(np.quantile(points[:,2], .9))
                top = points[np.abs(points[:,2]-z)<.005]
                if len(top)<8:
                    top = points
                xy = (np.quantile(top[:,:2],.1,axis=0)+np.quantile(top[:,:2],.9,axis=0))/2
                choices.append(dict(id=d['id'], score=d['confidence'], target=np.r_[xy,z+.05].tolist()))
            if selected_id is None and choices:
                selected_id = max(choices, key=lambda d:d['score'])['id']
            chosen = next((d for d in choices if d['id']==selected_id), None)
            dump(folder/'visual_targets.json', choices)
            # Save sensor calibration/robot state, never simulator object fields.
            dump(folder/'sensor_metadata.json', dict(native_step=tick, robot=captured['robot'],
                calibration={n:{k:v for k,v in c.items() if k not in ('rgb','depth_m')}
                             for n,c in captured['cameras'].items()},
                env_origin=captured['env_origin'], gripper_bias_m=captured['gripper_bias_m']))
            if chosen is None:
                status='visual_identity_lost'; break
            target = np.asarray(chosen['target'])
            arm_i = int(target[0]>=0)
            arm = ('left','right')[arm_i]
            q = np.asarray(obs['eef_quaternions_wxyz'][arm_i])
            offset = Rotation.from_quat(q[[1,2,3,0]]).apply([captured['gripper_bias_m'][arm_i],0,0])
            position = np.asarray(obs['eef_positions'][arm_i])+offset
            error = target-position
            row = dict(index=index, native_step=tick, selected_id=selected_id,
                       position_m=position.tolist(), estimated_target_m=target.tolist(),
                       estimated_error_norm_m=float(np.linalg.norm(error)))
            rows.append(row)
            dump(rec.folder/'visual_trajectory.json', rows)
            if np.max(np.abs(error)) <= cfg['axis_tolerance_m']:
                status='estimated_target_reached'; break
            if index>=cfg['max_jev_decisions']:
                break
            state = state_for(position, target, 'approach', cfg, visual_id=selected_id,
                gripper_opening=float(obs['states'][arm_i*7+6]))
            state.update(observation_source='RGB_D_estimated_surface_plus_robot_feedback',
                         coordinate_frame='environment_origin_nominal_grasp_m')
            decision = model.choose(state, dict(stage='approach', environment='robodojo',
                trajectory_id=episode, observation_mode='rgbd', native_step=tick))
            call('audit_before', decision=index, declaration=dict(decision_id=decision['decision_id'],
                 visual_id=selected_id, stage='approach', target=target.tolist()))
            vector = np.asarray(decision['signs'],float)
            if np.linalg.norm(vector):
                vector /= np.linalg.norm(vector)
            amplitude = min(.04, .7*np.linalg.norm(error))
            targets = {}
            for i,name in enumerate(('left','right')):
                targets[name] = dict(position=np.asarray(obs['eef_positions'][i]).tolist(),
                    quaternion_wxyz=np.asarray(obs['eef_quaternions_wxyz'][i]).tolist(),
                    gripper_opening=float(obs['states'][i*7+6]), gripper_closed=bool(obs['states'][i*7+6]<.5))
            targets[arm]['position'] = (position+amplitude*vector-offset).tolist()
            acks=[]
            for _ in range(3):
                proposal = call('eef_joint_target', targets=targets)
                action=np.asarray(proposal['action'],np.float32)
                other=0 if arm=='right' else 7
                action[other:other+7]=obs['states'][other:other+7]
                ack=call('chunk_step',actions=action.reshape(1,14),controller='jev_rsi_rgbd_approach')
                tick=ack['step_id'];acks.append(dict(ik=proposal,ack=ack,action=action))
                if any(s['terminated'] or s['truncated'] for s in ack['steps']):
                    status='native_ended';break
            call('audit_after', execution=dict(amplitude_m=float(amplitude), native_step=tick))
            rec.branch(dict(kind='rgbd_approach',decision_id=decision['decision_id'],
                            amplitude_m=float(amplitude), targets=targets, acks=acks))
            if status=='native_ended':
                break
        dump(rec.folder/'rgbd_reach_result.json', dict(status=status, decisions=len(rec.decisions),
             final=rows[-1] if rows else None, scope='visual approach only, not grasp or whole-task success'))
        dump(rec.folder/'native_finish.json', call('finish_pilot',reason='RGBD_approach_diagnostic'))
    finally:
        model.close()
