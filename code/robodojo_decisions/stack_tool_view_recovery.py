"""Coupled tool/view proposals from current RGB uncertainty and public cameras.

This operator never reads scene state or grants permission. The caller still
checks native first IK and requests one independent fresh-RGB action judgment.
"""
import copy
import itertools
import numpy as np
from camera_geometry import (eef_transform, ray, project,
                             propagate_wrist_calibration,
                             gripper_height_above_landmark)
from robot_path_preview import preview


def projected_source_margin(obs, geometry, target):
    future=propagate_wrist_calibration(obs['camera_calibration'],obs['current_eef'],target,obs['step_id'])
    camera=future['cameras']['cam_right_wrist'];width,height=camera['size']
    fit=geometry['fit'];uv=fit['top_interior_material_candidate']['high_pixel_uv']
    lo,hi=fit['near_best_z_m_at_iou_within_0p05'];rows=[]
    for du,dv,z in itertools.product((-2,2),(-2,2),(lo-.002,hi+.002)):
        origin,direction=ray(obs['camera_calibration']['cameras']['cam_high'],[uv[0]+du,uv[1]+dv])
        distance=(z-origin[2])/direction[2]
        if distance<=0:return None
        pixel=project(camera,origin+distance*direction)
        if pixel is None:return None
        rows.append(min(pixel[0],width-1-pixel[0],pixel[1],height-1-pixel[1]))
    return min(rows)


def supported_xy_direction(residual, intervals):
    """Hold an uncertain component while using a separately supported one."""
    residual=np.asarray(residual,float)
    intervals=np.asarray(intervals,float)
    supported=((residual>0)&(intervals[:,0]>0))|((residual<0)&(intervals[:,1]<0))
    usable=np.where(supported,residual,0)
    length=float(np.linalg.norm(usable))
    return (usable/length,length) if length>=5 else (None,length)


def build(obs, geometry, base_targets, maximum_mrad):
    residual=np.asarray(geometry['top_minus_pad_midpoint_world_xyz_mm'],float)[:2]
    intervals=np.asarray(geometry['top_minus_pad_midpoint_xyz_interval_mm'],float)[:2]
    direction,length=supported_xy_direction(residual,intervals)
    if direction is None:
        return {},{}, {'available':False,'reason':'No individually supported XY component for coupled recovery'}
    descriptions={};targets={};diagnostics={}
    upper=geometry['fit']['near_best_z_m_at_iou_within_0p05'][1]+.002
    start=eef_transform(obs['current_eef']['right'])[:3,3]
    for name,base in base_targets.items():
        try:size=int(name.rsplit('_',1)[1].replace('mrad',''))
        except ValueError:continue
        if size>maximum_mrad:continue
        for mm in (0,5,10,15,20,25,30):
            if mm>=length:continue
            xy=direction*mm
            minimum_dot=float(np.sum(np.where(xy>=0,intervals[:,0],intervals[:,1])*xy))
            minimum_squared_gain=2*minimum_dot-float(xy@xy)
            if mm and minimum_squared_gain<=0:continue
            target=copy.deepcopy(base)
            target['right']['position'][:2]=(np.asarray(target['right']['position'][:2])+direction*mm*.001).tolist()
            margin=projected_source_margin(obs,geometry,target)
            if margin is None or margin<24:continue
            if np.linalg.norm(np.asarray(target['right']['position'])-start)>.05:continue
            path=preview(obs,target['right'],None,steps=5)
            if not(path['public_path_gate'] and path['native_eef_single_action_legal']):continue
            gap=min(gripper_height_above_landmark(
                {'position':row['predicted_link6_position_m'],'quaternion_wxyz':row['predicted_link6_quaternion_wxyz']},
                [0,0,upper],0)['hand_above_landmark_plane_after_m']
                for row in path['predicted_joint_path'])
            if gap<.010:continue
            key=name+f'_with_source_xy_{mm}mm'
            targets[key]=target
            diagnostics[key]={'rotation_mrad':size,'additional_source_directed_xy_mm':mm,
                'supported_xy_unit_direction':direction.tolist(),
                'minimum_conditional_horizontal_squared_error_decrease_mm2':minimum_squared_gain,
                'minimum_uncertain_source_wrist_margin_px':margin,
                'minimum_public_hand_source_upper_gap_m':gap,'public_path':path}
            descriptions[key]=(
                f'ONE complete five-step OPEN pose: bounded tool rotation {size}mrad combined with {mm}mm '
                'horizontal displacement along the interval-supported CURRENT source-minus-pad XY direction; '
                'left arm held. Execute the exact complete_programs target, not separate axes. '
                f'Public-camera endpoint projection has minimum {margin:.2f}px wrist margin across the declared '
                '+/-2px and current height-range sensitivity samples. This is a conditional feature-visibility '
                'prediction, not full-object visibility, collision clearance, contact or holding. '
                'CURRENT RGB must independently support the whole short corridor; choose STOP if unsupported.')
            break  # Smallest checked extra XY displacement for this angle.
    if not targets:return {},{}, {'available':False,'reason':'No combined pose passed current view/source/public-path gates','candidate_diagnostics':diagnostics}
    best=min(targets,key=lambda k:(-diagnostics[k]['rotation_mrad'],diagnostics[k]['additional_source_directed_xy_mm']))
    return {best:descriptions[best]},{best:targets[best]}, {
        'available':True,'policy':'Largest checked bounded angle, then smallest extra XY restoring24px margin; no motion permission.',
        'candidate_diagnostics':diagnostics}
