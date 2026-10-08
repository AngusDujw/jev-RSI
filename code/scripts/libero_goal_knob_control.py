"""Jev-owned stove-control trial using only public RGB-D and own robot state."""
import os

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from libero_goal_drawer_control import DrawerModel
from libero_goal_knob_vision import visible_stove_control
from libero_robot_geometry import envelope, gripper_geometry
from libero_ten_task_workflows import decision_request, stages
from run_position_pilot import dump


class KnobModel(DrawerModel):
    prompt_version = 'goal-knob-v1'


def run_knob(env, obs, rec, task, depth_fn, k_fn, t_fn):
    if rec.cfg['suite'] != 'libero_goal' or rec.cfg['task_id'] != 1383:
        raise ValueError('Stove-control workflow requires Goal 1383')
    if os.environ.get('JEV_RSI_MODEL_BACKEND') != 'jev':
        raise ValueError('Stove-control workflow requires runtime Jev')
    model = KnobModel(rec)
    own = gripper_geometry(env, obs)
    sequence = stages(1383)
    ticks = stage_ticks = grip_ticks = 0
    gripper = -1
    phase = 0
    history = []
    initial = turned = None
    turn_orientation = None
    visible_angle_change = None
    verification_error = None
    finished = False
    failure = None

    def frame():
        camera = 'agentview'
        return dict(rgb=np.ascontiguousarray(obs[camera+'_image'][::-1]),
                    depth=depth_fn(env.sim,obs[camera+'_depth'])[::-1].squeeze(),
                    K=k_fn(env.sim,camera,768,768),T=t_fn(env.sim,camera))

    def snapshot(name):
        cv2.imwrite(str(rec.folder/f'{ticks:04d}-{name}-agentview.png'),
                    cv2.cvtColor(frame()['rgb'],cv2.COLOR_RGB2BGR))

    try:
        initial=visible_stove_control(frame())
        dump(rec.folder/'visible-control-initial.json',initial)
        orientation=Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
        own_open=envelope(own,orientation)
        contact=np.r_[initial['center_world_xy_m'],
                      initial['top_world_z_m']-.005]-own_open['pad_center_offset']
        contact[2]=max(contact[2],initial['low_world_z_m']-
                       own_open['finger_low_z_offset']+.002)
        hover=contact.copy();hover[2]+= .12
        dump(rec.folder/'contact-plan.json',dict(contact_tcp_world_m=contact,
            hover_tcp_world_m=hover,own_pad_center_offset=own_open['pad_center_offset'],
            own_finger_low_z_offset=own_open['finger_low_z_offset'],
            declared_turn_world_z_rad=float(np.pi/3),
            source='Visible knob tab and own gripper geometry; Jev owns choices'))
        while phase < len(sequence):
            rec.check_budget()
            if ticks>=550 or stage_ticks>=160:
                raise RuntimeError('Stove-control native/stage budget')
            stage=sequence[phase]
            name=stage['name']
            position=np.asarray(obs['robot0_eef_pos'],float)
            current_rotation=Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
            target=(hover if name in ('approach','align','verify') else
                    contact if name=='contact' else position.copy())
            rotation_error=(Rotation.from_matrix(turn_orientation@current_rotation.T).as_rotvec()
                            if name=='turn' and turn_orientation is not None
                            else np.zeros(3))
            aperture=float(np.sum(abs(obs['robot0_gripper_qpos']))*1000)
            arrived=bool(np.max(abs(target-position))<.007)
            rotated=bool(np.max(abs(rotation_error))<.05)
            if name=='verify' and arrived and turned is None:
                try:
                    turned=visible_stove_control(frame())
                    dump(rec.folder/'visible-control-after.json',turned)
                    angle=turned['tab_axis_angle_rad']-initial['tab_axis_angle_rad']
                    visible_angle_change=float(abs((angle+np.pi/2)%np.pi-np.pi/2))
                except RuntimeError as exc:
                    verification_error=str(exc)
                    turned=dict(status='unavailable',reason=verification_error)
                    dump(rec.folder/'visible-control-after.json',turned)
            gate=dict(observe=True,approach=arrived,align=arrived,
                      contact=arrived,grasp=grip_ticks>=18 and gripper==1 and 3<aperture<50,
                      turn=rotated and gripper==1 and aperture>3,
                      release=grip_ticks>=24 and gripper==-1 and aperture>=70,
                      verify=arrived and visible_angle_change is not None and
                             visible_angle_change>.35)[name]
            evidence=dict(sources=['public_task','agentview_rgbd','camera_calibration',
                                   'robot_proprioception','own_robot_mesh','executed_action_history'],
                          observed_native_tick=ticks,
                          control_visible=bool(initial),
                          control_hover_reached=arrived if name=='approach' else None,
                          orientation_reached=arrived if name=='align' else None,
                          control_contact_pose_reached=arrived if name=='contact' else None,
                          closure_executed=grip_ticks>=18 and gripper==1 and 3<aperture<50,
                          wrist_turn_arrived=rotated and gripper==1 and aperture>3,
                          opening_executed=grip_ticks>=24 and gripper==-1 and aperture>=70,
                          visible_change=gate if name=='verify' else None,
                          visible_control_angle_change_rad=visible_angle_change,
                          verification_error=verification_error,
                          visible_tab_world_xy_m=initial['center_world_xy_m'],
                          target_tcp_world_m=target.tolist(),
                          own_gripper_aperture_mm=aperture,
                          turn_is_proprioceptive_only=name=='turn')
            request=decision_request(1383,stage['id'],tcp_xyz_m=position,
                target_xyz_m=target,rotation_error_world_rad=rotation_error,
                gripper_aperture_mm=aperture,
                last_gripper_command='open' if gripper==-1 else 'close',
                observed_evidence=evidence,recent_actions=history,native_tick=ticks,
                public_language=task.language,reobserve_available=False,
                required_gripper_state=('close' if name in ('grasp','turn') else 'open'))
            if name=='turn':
                request['state']['stage_contract']=(
                    'Keep the measured control clamped and rotate the own wrist '
                    'toward the declared world-Z goal. This stage uses only own '
                    'orientation as a gate; actual visible control rotation is '
                    'checked after opening and withdrawal.')
            if name=='verify':
                request['state']['stage_contract']=(
                    'Withdraw with open gripper, then compare the visible control '
                    'tab axis with its initial public RGB-D axis. Advance only '
                    'when fresh visible rotation exceeds 0.35 rad.')
            request['questions']['transition']['instructions']=(
                f'The completion gate for this stage is completion_evidence.{stage["gate"]}. '
                'If that gate is true, choose advance now; all evidence needed '
                'for this stage is complete, and later-stage evidence belongs '
                'to the next stage. If false, continue_phase or stop. The '
                'selected action executes before the edge. This does not '
                'claim official task success.')
            d=model.decide(request,stage['id'])
            edge=d['transition']
            if edge=='stop':
                raise RuntimeError('Jev elected stop')
            if edge=='reobserve':
                raise RuntimeError('Unexpected reobserve')
            command=d['gripper']
            new_gripper=gripper if command=='keep' else -1 if command=='open' else 1
            if new_gripper!=gripper:
                grip_ticks=0
            gripper=new_gripper
            delta=np.asarray(d['signs'])*np.minimum(.018,.5*abs(target-position))
            rotation_delta=np.asarray(d['rotation_signs'])*np.minimum(.08,.4*abs(rotation_error))
            block=6 if name in ('grasp','release') else 3
            before=position.copy()
            for _ in range(block):
                if ticks>=550:raise RuntimeError('Stove-control native budget')
                obs,_,_,_=env.step(np.r_[delta/.05,rotation_delta/.5,gripper])
                ticks+=1;stage_ticks+=1;grip_ticks+=1
            after=np.asarray(obs['robot0_eef_pos'],float)
            rec.branch(dict(stage=stage['id'],decision_id=d['decision_id'],
                before=before,after=after,delta=delta,rotation_delta=rotation_delta,
                selected_gripper=command,executed_gripper=gripper,
                selected_transition=edge,native_steps=ticks))
            history.append(dict(stage=name,transition=edge,
                actual_displacement_mm=np.round((after-before)*1000,2).tolist()))
            if len(history)>3:history=history[-3:]
            snapshot(name)
            if edge=='advance':
                if not gate:raise RuntimeError('Jev advanced without stage evidence')
                if name=='grasp':
                    turn_orientation=(Rotation.from_rotvec([0,0,np.pi/3]).as_matrix()
                                      @Rotation.from_quat(obs['robot0_eef_quat']).as_matrix())
                rec.event(dict(kind='phase_transition',from_stage=stage['id'],
                               to_stage=request['state']['next_stage'],
                               decision_id=d['decision_id']))
                phase+=1;stage_ticks=grip_ticks=0
        finished=True
    except Exception as exc:
        failure=str(exc)
        rec.event(dict(kind='stop',reason=failure))
    finally:
        snapshot('terminal')
        success=bool(env.check_success())
        dump(rec.folder/'result.json',dict(success=success,program_finished=finished,
            error=failure,native_steps=ticks,jev_calls=len(rec.decisions),
            visible_control_angle_change_rad=visible_angle_change,
            stage=sequence[phase]['name'] if phase<len(sequence) else 'finished',
            ownership='Jev XYZ/rotation/gripper/phase; fixed public RGB-D knob geometry'))
        rec.finish('success' if success else 'failed')
        model.close()
