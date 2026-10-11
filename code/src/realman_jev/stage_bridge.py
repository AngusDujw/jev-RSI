"""Generic, explicitly privileged physical features without task labels/rewards."""
import os
import numpy as np
from scipy.spatial.transform import Rotation
from .company_bridge import array


def install():
    from .company_bridge import install as install_parent
    install_parent()
    from hybrid_rollout.robodojo.robodojo_server import session as upstream
    Parent = upstream.RoboDojoSession
    class StageSession(Parent):
        def reset(self, seed, source, policy_version):
            # Native reset includes hundreds of uncounted settling steps. Log
            # their progress so a slow camera path is distinguishable from a
            # blocked reset without changing any physics or observations.
            import json
            step = 0
            original = self.env.sim_step
            def observed_sim_step(*args, **kwargs):
                nonlocal step
                result = original(*args, **kwargs)
                step += 1
                if step % 50 == 0:
                    print(json.dumps(dict(event='native_reset_progress', steps=step)), flush=True)
                return result
            self.env.sim_step = observed_sim_step
            try:
                return super().reset(seed, source, policy_version)
            finally:
                self.env.sim_step = original

        def dispatch(self, op, args):
            if op == 'reset':
                self._stage_previous_positions = None
                self._stage_velocities = {}
                self._stage_material_vertices = {}
            if op == 'stage_ik_probe':
                from .stage_kinematics import probe_pose
                self._check_identity(args['episode_id'], args['step_id'])
                self.kinematics.check()
                diagnostics = {}
                for arm, target in args['targets'].items():
                    robot = self.kinematics.robots[arm]
                    key = self.kinematics.manager.robot_key[self.kinematics.manager.robot_list.index(robot)]
                    limits = key.data.soft_joint_pos_limits[0, robot.arm_joint_indices].cpu().numpy()
                    diagnostics[arm] = probe_pose(self.kinematics.fk[arm], self.kinematics.root(arm), limits,
                        self.kinematics.manager.get_joint(robot)[0], target['position'], target['quaternion_wxyz'])
                return dict(arms=diagnostics, physical_steps=0)
            if op == 'vision_stage_state':
                # The policy can obtain calibrated cameras and its own robot
                # geometry, but this path never visits LayoutManager objects.
                self._check_identity(args['episode_id'], args['step_id'])
                if self.input_mode != 'vision':
                    raise PermissionError('Vision robot state requires vision mode')
                cm = self.env.camera_manager
                calibration = {}
                for camera_id, name in enumerate(cm.camera_names[0]):
                    alias = 'cam_high' if name in ('cam_head', 'head_camera', 'top_camera') else name
                    if alias not in ('cam_high', 'cam_left_wrist', 'cam_right_wrist'):
                        continue
                    h, w = self.obs[alias].shape[:2]
                    calibration[alias] = dict(
                        intrinsic=array(cm.get_camera_intrinsics(camera_id, 0)),
                        camera_to_world=array(cm.get_camera_extrinsics(camera_id, 0)),
                        size=[w, h])
                positions = np.asarray(self.obs['eef_positions'])
                quaternions = np.asarray(self.obs['eef_quaternions_wxyz'])
                grasp_points = []
                robot_state = dict(eef_positions_m=array(positions),
                    eef_quaternions_wxyz=array(quaternions), states=array(self.obs['states']),
                    nominal_grasp_points_m=grasp_points,
                    grasp_reference='robot gripper_bias and measured wrist pose, not observed contact',
                    reference='link6, not fingertip center', kinematic_specs={},
                    finger_geometry={}, measured_gripper_frames={})
                errors = []
                for i, arm in enumerate(('left', 'right')):
                    robot = self.kinematics.robots[arm]
                    q = quaternions[i]
                    measured_rotation = Rotation.from_quat(q[[1, 2, 3, 0]])
                    grasp_points.append((positions[i]+measured_rotation.apply([float(robot.gripper_bias), 0., 0.])).tolist())
                    robot_state['measured_gripper_frames'][arm] = dict(
                        approach_world=measured_rotation.apply([1., 0., 0.]).tolist(),
                        closing_world=measured_rotation.apply([0., 1., 0.]).tolist(),
                        provenance='robot wrist orientation')
                    key = self.kinematics.manager.robot_key[self.kinematics.manager.robot_list.index(robot)]
                    limits = key.data.soft_joint_pos_limits[0, robot.arm_joint_indices].cpu().numpy()
                    root = self.kinematics.root(arm)
                    chain = self.kinematics.fk[arm].chain
                    robot_state['kinematic_specs'][arm] = dict(
                        base_position_m=root[:3, 3].tolist(), joint_names=list(robot.arm_joints_name),
                        joint_limits_rad=limits.tolist(),
                        wrist_distance_upper_bound_m=float(sum(np.linalg.norm(t[:3, 3]) for _, _, t, _ in chain)),
                        chain=[dict(joint=n, type=k, origin_translation_m=t[:3, 3].tolist(), axis=a.tolist())
                               for n, k, t, a in chain])
                    try:
                        from .stage_geometry import observed_fingers
                        geometry = observed_fingers(self.kinematics.manager, robot, positions[i], q)
                        if geometry:
                            robot_state['finger_geometry'][arm] = geometry
                    except (ImportError, OSError, ValueError, KeyError, AttributeError) as exc:
                        errors.append(dict(arm=arm, feature_error='finger_geometry_'+type(exc).__name__))
                return dict(tick=self.step_id, frame='environment_origin', robot=robot_state,
                    cameras=calibration, env_origin=array(self.env.scene_manager.env_origins[0]),
                    feature_errors=errors,
                    source='RGB camera calibration and robot proprioception/kinematics only')
            if op != 'stage_observation':
                return super().dispatch(op, args)
            self._check_identity(args['episode_id'], args['step_id'])
            if self.input_mode != 'oracle':
                raise PermissionError('Stage physical features require explicit oracle mode')
            snap = self.physical_snapshot()
            manager = self.env.scene_manager.layout_manager
            errors = []
            previous = getattr(self, '_stage_previous_positions', None)
            velocities = getattr(self, '_stage_velocities', {})
            material_meshes={}
            dt = (self.step_id-previous['tick'])*self.metadata['control_dt'] if previous else 0
            for obj in snap['objects']:
                obj.pop('audit_label', None)
                try:
                    points = manager.get_instance_bbox_vertices(obj['id'], 0)
                    if points is not None:
                        # Metadata bbox vertices are LOCAL, while get_bbox() fallback
                        # may be world-space. Transform metadata geometry explicitly.
                        metadata = manager.get_instance_metadata(0, inst_name=obj['id']) or {}
                        points = np.asarray(array(points), float)
                        if metadata.get('geometry', {}).get('oriented_bbox', {}).get('vertices') is not None:
                            q = np.asarray(obj['quaternion_wxyz'])
                            points = Rotation.from_quat(q[[1,2,3,0]]).apply(points)+obj['position_m']
                        obj['geometry'] = dict(world_bbox_min_m=points.min(0).tolist(), world_bbox_max_m=points.max(0).tolist())
                        obj['grasp_point_m'] = ((points.min(0)+points.max(0))/2).tolist()
                        obj['grasp_point_provenance'] = 'world bounding-box center ONLY; not a measured contact or validated grasp; hollow/concave objects may require a rim or other offset'
                    scene_obj = manager.get_scene_object(0, obj['id'])
                    if previous is None and hasattr(scene_obj, 'get_linear_velocity'):
                        measured_velocity = np.asarray(array(scene_obj.get_linear_velocity()), float).ravel()
                        if measured_velocity.shape == (3,) and np.isfinite(measured_velocity).all():
                            velocities[obj['id']] = measured_velocity.tolist()
                    metadata = manager.get_instance_metadata(0, inst_name=obj['id']) or {}
                    keypoints = {}
                    mesh = None
                    if obj['kind'] == 'Garment' and hasattr(scene_obj, 'sample_mesh_vertices'):
                        mesh = np.asarray(array(scene_obj.sample_mesh_vertices()[0]))
                        mesh = mesh-np.asarray(array(self.env.scene_manager.env_origins[0]))
                        obj['geometry'] = dict(world_bbox_min_m=mesh.min(0).tolist(), world_bbox_max_m=mesh.max(0).tolist(),
                                               provenance='current deformed mesh, not reset asset bbox')
                        obj['grasp_point_m'] = ((mesh.min(0)+mesh.max(0))/2).tolist()
                        if args.get('track_material_points',False):material_meshes[obj['id']]=mesh[:,:3]
                    for kind in ('active', 'passive'):
                        for tag, info in metadata.get(kind, {}).get('functional', {}).items():
                            if not tag.isidentifier():
                                continue
                            if mesh is not None and 'id' in info:
                                indices = info['id']
                                if indices:
                                    keypoints[tag] = mesh[indices, :3].mean(0).tolist()
                            else:
                                pts = manager.get_functional_points(tag=tag, type=kind, config=metadata,
                                    ret='list', obj_name=obj['id'], env_idx=0)
                                if pts:
                                    # Functional poses contain XYZ plus WXYZ, not
                                    # a flat sequence of three-dimensional points.
                                    keypoints[tag] = np.asarray(array(pts))[:, :3].mean(0).tolist()
                            joints = info.get('parent_joint', [])
                            if isinstance(joints, str):
                                joints = [joints]
                            for joint in joints:
                                data = scene_obj.get_joint_info(joint)
                                if joint.isidentifier() and data.get('position') is not None:
                                    obj.setdefault('joints', {})[joint] = float(data['position'])
                                    lo, hi = data.get('lower'), data.get('upper')
                                    if lo is not None and hi is not None and hi != lo:
                                        obj['joints'][joint+'_ratio'] = (float(data['position'])-lo)/(hi-lo)
                    if keypoints:
                        obj['keypoints'] = keypoints
                    state = scene_obj.get_state(is_relative=True) if hasattr(scene_obj, 'get_state') else None
                    # Garment named points are real current mesh observations,
                    # not reward booleans or target labels.
                    if isinstance(state, dict):
                        for field in ('keypoints', 'key_points', 'functional_points'):
                            if isinstance(state.get(field), dict):
                                obj['keypoints'] = {k: array(v) for k, v in state[field].items()}
                        if 'joint_pos' in state:
                            positions = np.asarray(array(state['joint_pos'])).ravel()
                            obj['joints'] = {'j'+str(i): float(v) for i, v in enumerate(positions)}
                except (AttributeError, KeyError, ValueError, TypeError) as exc:
                    errors.append(dict(object=obj['id'], feature_error=type(exc).__name__))
                if previous and dt > 0 and obj['id'] in previous['objects']:
                    velocities[obj['id']] = ((np.asarray(obj['position_m'])-previous['objects'][obj['id']])/dt).tolist()
                if obj['id'] in velocities:
                    obj['velocity_m_per_s'] = velocities[obj['id']]
            if previous is None or self.step_id != previous['tick']:
                self._stage_previous_positions = dict(tick=self.step_id,
                    objects={o['id']:o['position_m'] for o in snap['objects']})
                self._stage_velocities = velocities
            snap['robot']['kinematic_specs'] = {}
            snap['robot']['finger_geometry'] = {}
            snap['robot']['measured_gripper_frames'] = {}
            for arm, robot in self.kinematics.robots.items():
                key = self.kinematics.manager.robot_key[self.kinematics.manager.robot_list.index(robot)]
                limits = key.data.soft_joint_pos_limits[0, robot.arm_joint_indices].cpu().numpy()
                root = self.kinematics.root(arm)
                chain = self.kinematics.fk[arm].chain
                index = ('left', 'right').index(arm)
                measured_rotation = Rotation.from_quat(np.asarray(snap['robot']['eef_quaternions_wxyz'][index])[[1,2,3,0]])
                snap['robot']['measured_gripper_frames'][arm] = dict(
                    approach_world=measured_rotation.apply([1.,0.,0.]).tolist(),
                    closing_world=measured_rotation.apply([0.,1.,0.]).tolist(),
                    provenance='measured wrist orientation: local +X approach and local +Y jaw translation')
                snap['robot']['kinematic_specs'][arm] = dict(base_position_m=root[:3, 3].tolist(),
                    joint_names=list(robot.arm_joints_name), joint_limits_rad=limits.tolist(),
                    wrist_distance_upper_bound_m=float(sum(np.linalg.norm(t[:3,3]) for _,_,t,_ in chain)),
                    chain=[dict(joint=n, type=k, origin_translation_m=t[:3,3].tolist(), axis=a.tolist()) for n,k,t,a in chain])
                try:
                    from .stage_geometry import observed_fingers
                    index = ('left', 'right').index(arm)
                    geometry = observed_fingers(self.kinematics.manager, robot,
                        snap['robot']['eef_positions_m'][index], snap['robot']['eef_quaternions_wxyz'][index])
                    if geometry:
                        snap['robot']['finger_geometry'][arm] = geometry
                except (ImportError, OSError, ValueError, KeyError, AttributeError) as exc:
                    errors.append(dict(arm=arm, feature_error='finger_geometry_'+type(exc).__name__))
            if args.get('track_material_points',False):
                from .stage_geometry import material_reference
                pinned=getattr(self,'_stage_material_vertices',{})
                commands=args.get('gripper_commands',[snap['robot']['states'][6],snap['robot']['states'][13]])
                settled=args.get('gripper_settled',[False,False])
                if len(commands)!=2 or any(not np.isfinite(c) or not 0<=c<=1 for c in commands):
                    raise ValueError('Material tracking requires two normalized gripper commands')
                if len(settled)!=2 or any(type(value) is not bool for value in settled):
                    raise ValueError('Material tracking requires two observed settling flags')
                for obj in snap['objects']:
                    if obj['id'] not in material_meshes:continue
                    obj['material_references']={}
                    for i,arm in enumerate(('left','right')):
                        key=(obj['id'],arm)
                        closed=commands[i]<.5
                        if not closed:pinned.pop(key,None)
                        tip=snap['robot']['finger_geometry'].get(arm,{}).get('distal_midpoint_m',snap['robot']['nominal_grasp_points_m'][i])
                        try:
                            reference=material_reference(material_meshes[obj['id']],tip,pinned.get(key))
                            if closed and (key in pinned or settled[i]):pinned[key]=reference['vertex_id']
                            reference.update(identity_frozen=key in pinned,commanded_opening=float(commands[i]),
                                provenance='Nearest currently observed deformable-mesh vertex after commanded closure physically settles; retain that material ID until an open command. Before settling this is a changing nearest point. Pure geometric reference, NOT contact, grasp, force or capture evidence.')
                            obj['material_references'][arm]=reference
                        except ValueError as exc:
                            errors.append(dict(object=obj['id'],arm=arm,feature_error='material_reference_'+type(exc).__name__))
                self._stage_material_vertices=pinned
            return dict(source='privileged_physical_features_NO_task_labels_or_rewards', frame=snap['frame'],
                        objects=snap['objects'], robot=snap['robot'], feature_errors=errors)
    upstream.RoboDojoSession = StageSession


def serve_with_planner_wait(session, port):
    """Keep the native episode open while a remote planner is thinking.

    The upstream RPC server closes its only connection after 900 seconds of
    inactivity. A GPT planning request can exceed that during a service
    interruption. The campaign supervisor owns the episode's wall-time limit.
    """
    import json
    import socket
    import traceback
    from hybrid_rollout.robodojo.robodojo_server.protocol import VERSION, receive_packet, send_packet

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', port))
        listener.listen(1)
        print(json.dumps(dict(event='ready', port=port, metadata=session.metadata)), flush=True)
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(None)
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                while True:
                    request = receive_packet(connection)
                    response = dict(version=VERSION, request_id=request.get('request_id'))
                    try:
                        if request.get('version') != VERSION:
                            raise ValueError('Unsupported protocol version')
                        result = session.dispatch(request['op'], request.get('args', {}))
                        response.update(ok=True, result=result)
                    except Exception as exc:
                        session.poisoned = True
                        traceback.print_exc()
                        response.update(ok=False, error=f'{type(exc).__name__}: {exc}')
                    send_packet(connection, response)
            except (EOFError, ConnectionError, TimeoutError):
                session._write_summary('terminal' if session.terminated or session.truncated else 'controller_disconnect')


def main():
    from pathlib import Path
    from env.global_configs import ROOT_DIR
    import utils
    utils.__path__ = [str(Path(ROOT_DIR).resolve()/'utils')]
    import utils.load_file
    install()
    from hybrid_rollout.robodojo.robodojo_server import rpc
    rpc.serve = serve_with_planner_wait
    from hybrid_rollout.robodojo.robodojo_server.server import main as launch
    launch()


if __name__ == '__main__':
    main()
