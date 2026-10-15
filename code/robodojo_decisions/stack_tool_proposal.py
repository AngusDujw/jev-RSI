"""Public robot orientation proposals under a CURRENT uncertain RGB top plane.

These are algorithmic OPEN programs, not planner actions or grasp evidence.
The caller must independently check native first IK before offering one.
"""
import numpy as np
import os
from scipy.spatial.transform import Rotation
from camera_geometry import propagate_wrist_calibration, project
from pickup_tool_alignment import build as tool_hypotheses


def build(obs, geometry):
    if (geometry.get('status') != 'current_conditional_top_hypothesis' or
            geometry.get('step_id') != obs['step_id'] or
            obs['current_eef']['right']['gripper_opening_command'] < .95):
        return {}, {}, {'available': False, 'reason': 'Current OPEN stack top hypothesis required'}
    lo, hi = geometry['fit']['near_best_z_m_at_iou_within_0p05']
    plane = {'current_step_id': obs['step_id'],
             'estimated_green_plane_height_m': (lo+hi)/2,
             'declared_green_height_halfwidth_m': (hi-lo)/2+.002}
    descriptions, targets, evidence = tool_hypotheses(obs, plane, None)
    evidence['source_plane_adapter_scope'] = (
        'The legacy helper field names refer here to the CURRENT stack RGB '
        'top-height interval plus2mm sensitivity, not green material or an object pose.')
    point = geometry['fit']['top_interior_material_candidate']['camera_derived_world_hypothesis_m']
    accepted = {}
    max_mrad=int(os.environ.get('ROBODOJO_RGB_STAGE_TOOL_MAX_MRAD','300'))
    if max_mrad not in (100,200,300):
        raise ValueError('Stack tool increment cap must be100,200 or300mrad')
    evidence['maximum_offered_rotation_mrad']=max_mrad
    for name, target in targets.items():
        current_q=np.asarray(obs['current_eef']['right']['quaternion_wxyz'])
        target_q=np.asarray(target['right']['quaternion_wxyz'])
        delta=(Rotation.from_quat(target_q[[1,2,3,0]])*
               Rotation.from_quat(current_q[[1,2,3,0]]).inv()).magnitude()
        if delta>max_mrad*.001+1e-8:
            continue
        future = propagate_wrist_calibration(
            obs['camera_calibration'], obs['current_eef'], target, obs['step_id'])
        camera = future['cameras']['cam_right_wrist']
        uv = project(camera, np.asarray(point))
        width, height = camera['size']
        margin = None if uv is None else min(uv[0], width-1-uv[0], uv[1], height-1-uv[1])
        row = evidence['candidate_diagnostics'][name]
        row['source_top_wrist_projection_uv'] = uv
        row['source_top_wrist_edge_margin_px'] = margin
        row['source_top_projection_supported'] = margin is not None and margin >= 24
        if row['source_top_projection_supported']:
            accepted[name] = target
    if accepted:
        best = min(accepted, key=lambda name: evidence['candidate_diagnostics'][name]['remaining_axis_angle_deg'])
        accepted = {best: accepted[best]}
    return {k: descriptions[k] for k in accepted}, accepted, evidence
