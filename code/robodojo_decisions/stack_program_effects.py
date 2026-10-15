"""Counterfactual robot/source residuals for each complete OPEN proposal.

The camera-derived source possibility is held fixed only for this prediction.
It is never object ground truth, a contact certificate or execution permission.
"""
import numpy as np
from camera_geometry import eef_transform,project,propagate_wrist_calibration


def build(obs, geometry, programs):
    if (geometry.get('status')!='current_conditional_top_hypothesis'
            or geometry.get('step_id')!=obs['step_id']):
        return {'available':False,'reason':'CURRENT source hypothesis required'}
    current=eef_transform(obs['current_eef']['right'])
    midpoint=np.asarray(geometry['measured_robot_pad_midpoint_world_m'],float)
    local=np.linalg.inv(current)@np.r_[midpoint,1]
    before=np.asarray(geometry['top_minus_pad_midpoint_world_xyz_mm'],float)
    interval=np.asarray(geometry['top_minus_pad_midpoint_xyz_interval_mm'],float)
    point=np.asarray(geometry['fit']['top_interior_material_candidate']['camera_derived_world_hypothesis_m'],float)
    down=np.array([0.,0.,-1.])
    angle=lambda matrix:float(np.degrees(np.arccos(np.clip(matrix[:3,0]@down,-1,1))))
    rows={}
    for name,program in programs.items():
        target=program['target']
        if target['right']['gripper_closed']:
            continue
        pose=eef_transform(target['right'])
        delta=((pose@local)[:3]-midpoint)*1000
        after=before-delta
        future=propagate_wrist_calibration(obs['camera_calibration'],obs['current_eef'],target,obs['step_id'])
        camera=future['cameras']['cam_right_wrist'];uv=project(camera,point)
        width,height=camera['size']
        margin=None if uv is None else min(uv[0],width-1-uv[0],uv[1],height-1-uv[1])
        rows[name]={
            'predicted_public_pad_midpoint_world_delta_mm':delta.round(3).tolist(),
            'same_hypothesis_top_minus_pad_world_xyz_mm_before':before.tolist(),
            'same_hypothesis_top_minus_pad_world_xyz_mm_after':after.round(3).tolist(),
            'same_hypothesis_xyz_interval_mm_after':(interval-delta[:,None]).round(3).tolist(),
            'horizontal_residual_norm_mm_before_after':[round(float(np.linalg.norm(before[:2])),3),round(float(np.linalg.norm(after[:2])),3)],
            'public_finger_downward_angle_deg_before_after':[round(angle(current),3),round(angle(pose),3)],
            'predicted_nominal_source_wrist_uv':uv,
            'predicted_nominal_source_wrist_margin_px':margin,
            'scope':'Endpoint prediction using the SAME conditional source reference and public measured robot geometry; target tracking and source stationarity are assumptions, not observations.'}
    return {'available':bool(rows),'step_id':obs['step_id'],
        'world_axis_meaning':'+X robot-right; +Y away from bases; +Z up. Errors are source hypothesis MINUS actual public pad midpoint, in WORLD mm. Positive error is reduced by positive pad displacement in that axis. Rotations are right-hand fixed WORLD rotations and also translate the pad unless pivot-preserving.',
        'source_basis':geometry.get('high_source_basis','Current uncertain camera fit'),
        'before_xyz_interval_mm':interval.tolist(),
        'offered_programs':rows,
        'interpretation':'A pivot-preserving turn can reduce the public tool angle while leaving XYZ residual unchanged. A coupled XY/turn can improve both. Judge the CURRENT stage objective and visible short corridor separately; this predicts no grasp, contact, full-object visibility or native success. Verify against the next actual robot/RGB observation.'}
