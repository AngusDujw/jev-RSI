"""Public five-step reachable programs and stage-specific progress scores."""
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from camera_geometry import eef_transform, gripper_height_above_landmark
from pickup_rgb_axes import _targets
from pickup_green_material_support import predict_feature_residuals
from robot_path_preview import preview


def propose(obs, targets, material, green_plane, table, stage):
    targets = dict(targets)
    diagnostics = {}
    if material is not None and float(obs['current_eef']['right']['gripper_opening_command'])>.95:
        error = np.asarray(material['representative_material_point']['nearest_opposing_surface_midpoint_delta_xyz_mm'])/1000
        size = float(np.linalg.norm(error))
        seeds = []
        for amount in (.03,.04):
            if size > amount*1.05:
                t = _targets(obs,'x',1,0)
                t['right']['position']=(np.asarray(t['right']['position'])+error/size*amount).tolist()
                seeds.append((f'rgb_xyz_{int(amount*1000)}mm',t))
        for axis in ('x','y','z'):
            sign = 1 if error['xyz'.index(axis)]>0 else -1
            if abs(error['xyz'.index(axis)])>.03:
                seeds.append((f'world_{axis}_{sign}_30mm',_targets(obs,axis,sign,.03)))
        for name,seed in seeds:
            first = preview(obs,seed['right'],None,5)
            adapted = seed
            passes = []
            for attempt in range(3):
                endpoint = first['predicted_joint_path'][-1]
                adapted = {'left':dict(seed['left']),'right':dict(seed['right'])}
                adapted['right']['position']=endpoint['predicted_link6_position_m']
                adapted['right']['quaternion_wxyz']=endpoint['predicted_link6_quaternion_wxyz']
                first = preview(obs,adapted['right'],None,5)
                passes.append(first)
                if first['public_path_gate']:
                    break
            accepted = first['public_path_gate'] and first['native_eef_single_action_legal']
            reference = (table['upper_height_for_robot_check_m'] if table else
                         green_plane['estimated_green_plane_height_m']+green_plane['declared_green_height_halfwidth_m'] if green_plane else None)
            gap = None
            if reference is not None:
                gap = min(gripper_height_above_landmark({'position':row['predicted_link6_position_m'],
                    'quaternion_wxyz':row['predicted_link6_quaternion_wxyz']},[0,0,reference],descent_m=0)['hand_above_landmark_plane_after_m']
                    for row in first['predicted_joint_path'])
                accepted = accepted and gap>=.006
            key=name+'_public_reachable_endpoint'
            diagnostics[key]={'desired_seed':seed,'five_step_retarget_previews':passes,
                              'accepted':bool(accepted),'hand_reference_gap_m':gap,
                              'scope':'PUBLIC ROBOT FK only; no future physics/object pose/contact. Endpoint is independently revalidated for a single legal five-step action.'}
            if accepted:
                targets[key]=adapted
    predictions = predict_feature_residuals(obs,material,targets)
    scores = {}
    current_axis = eef_transform(obs['current_eef']['right'])[:3,0]
    angle = np.degrees(np.arccos(np.clip(current_axis@[0,0,-1],-1,1)))
    current_error = (np.asarray(material['representative_material_point']['nearest_opposing_surface_midpoint_delta_xyz_mm']) if material else None)
    for name,target in targets.items():
        desired=eef_transform(target['right'])
        newangle=np.degrees(np.arccos(np.clip(desired[:3,0]@[0,0,-1],-1,1)))
        delta=(desired[:3,3]-np.asarray(obs['current_eef']['right']['position']))*1000
        if name.startswith('close_'):
            score=1000.0  # Only existing RGB-volume/precision gated closure is eligible.
        elif name.startswith('open_empty_'):
            score=-1000.0
        elif stage=='closed_gripper_visual_test':
            score=float(delta[2])
        elif name in predictions and current_error is not None:
            after=np.asarray(predictions[name]['same_rgb_feature_minus_predicted_surface_span_xyz_mm'])
            score=(float(np.linalg.norm(current_error[:2])-np.linalg.norm(after[:2]))
                   if stage=='coarse_directional_alignment_review' else
                   float(angle-newangle) if stage=='strict_tool_geometry_review' else
                   float(np.linalg.norm(current_error)-np.linalg.norm(after)))
        else:
            score=float(angle-newangle)
        scores[name]={'stage_progress_score':round(score,3),'predicted_axis_angle_deg':round(float(newangle),2),
                     'prediction':predictions.get(name),'scope':'A current controller proposal score under stated RGB/static-source/robot-model hypotheses, not task completion or observed contact.'}
    if not scores:
        return None,targets,diagnostics,scores
    selected=max(scores,key=lambda key:scores[key]['stage_progress_score'])
    if selected.startswith('open_empty_'):
        return None,targets,diagnostics,scores
    return selected,targets,diagnostics,scores
