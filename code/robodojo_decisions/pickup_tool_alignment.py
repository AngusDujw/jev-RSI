"""Public-robot orientation hypotheses for a camera-derived horizontal source.

No planner action, simulator object pose, contact or outcome enters this module.
The horizontal source-plane assumption remains explicitly uncertain.
"""
from __future__ import annotations

import numpy as np
import os
from scipy.spatial.transform import Rotation

from camera_geometry import eef_transform, gripper_height_above_landmark
from gripper_pad_projection import inspect as inspect_pads
from pickup_rgb_axes import _targets
from robot_path_preview import preview


def build(observation: dict, green_plane: dict | None, table: dict | None):
    if green_plane is not None and green_plane['current_step_id'] != observation['step_id']:
        return {}, {}, {'unavailable': 'Stale RGB plane hypothesis'}
    current = eef_transform(observation['current_eef']['right'])
    axis = current[:3, 0]
    desired = np.array([0., 0., -1.])
    angle = float(np.arccos(np.clip(axis @ desired, -1, 1)))
    evidence = {
        'current_public_finger_extension_axis_world': axis.round(5).tolist(),
        'assumed_source_plane_normal_world': [0, 0, 1],
        'finger_extension_vs_downward_normal_angle_deg': round(np.degrees(angle), 2),
        'source_plane_step_id': green_plane['current_step_id'] if green_plane else None,
        'source_plane_height_halfwidth_m': green_plane['declared_green_height_halfwidth_m'] if green_plane else None,
        'plane_evidence_mode': 'validated_current_RGB_height_horizontal_hypothesis' if green_plane else 'horizontal_tabletop_hypothesis_from_CURRENT_RGB_only; no measured plane height or normal',
        'interpretation': 'Public URDF finger extension local +X is compared with the downward normal of the RGB HORIZONTAL-plane hypothesis. This is an above-source pinch-orientation hypothesis, not a measured object normal or a planner action. A sideways approach may hit the table before the small opposing finger faces reach flat material.',
        'candidate_diagnostics': {}}
    if angle < .05:
        return {}, {}, evidence
    rotation_axis = np.cross(axis, desired)
    if np.linalg.norm(rotation_axis) < 1e-6:
        return {}, {}, evidence
    rotation_axis /= np.linalg.norm(rotation_axis)
    pads = inspect_pads(observation, observation['camera_calibration'])
    pivot = np.mean([np.asarray(pads['rows'][name]['inner_facet_world_xyz_m']).mean(axis=0)
                     for name in ('link7', 'link8')], axis=0)
    local_pivot = current[:3, :3].T @ (pivot-current[:3, 3])
    if table is not None and table['current_step_id'] == observation['step_id']:
        reference_z = table['upper_height_for_robot_check_m']
        reference_kind = 'CURRENT RGB table upper reference'
        margin = .006
    elif green_plane is not None:
        reference_z = green_plane['estimated_green_plane_height_m'] + green_plane['declared_green_height_halfwidth_m']
        reference_kind = 'CURRENT RGB source-plane upper height hypothesis; NOT table pose'
        margin = .010
    else:
        reference_z = None
        reference_kind = 'UNKNOWN source/table height: no numerical scene-clearance claim; mandatory current RGB whole-hand review'
        margin = None
    options, targets = {}, {}
    sizes = (.05, .10, .20, .30) if os.environ.get('ROBODOJO_PICKUP_PROGRAM_PAIR') == '1' else (.10, .20, .30)
    if os.environ.get('ROBODOJO_PICKUP_TIGHTER_GRASP_ALIGNMENT')=='1' and np.degrees(angle)<20:
        sizes=(.05,)  # Native run317 overshot the 2mm tracking gate with .10rad here.
        evidence['fine_orientation_increment_rad']=.05
        evidence['fine_orientation_reason']='Near-vertical .10rad public prediction underestimated actual tracking error; use a smaller target, never relax the native 2mm gate.'
    for size in sizes:
        size = min(size, angle)
        rotated = Rotation.from_rotvec(rotation_axis*size).as_matrix() @ current[:3, :3]
        target = _targets(observation, 'x', 1, 0.0)
        target['right']['position'] = (pivot-rotated @ local_pivot).tolist()
        q = Rotation.from_matrix(rotated).as_quat()
        target['right']['quaternion_wxyz'] = q[[3, 0, 1, 2]].tolist()
        path = preview(observation, target['right'], None, steps=5)
        poses = [observation['current_eef']['right']] + [
            {'position': row['predicted_link6_position_m'],
             'quaternion_wxyz': row['predicted_link6_quaternion_wxyz']}
            for row in path['predicted_joint_path']]
        gap = (min(gripper_height_above_landmark(pose, [0, 0, reference_z], descent_m=0)['hand_above_landmark_plane_after_m']
                  for pose in poses) if reference_z is not None else None)
        key = f'orient_finger_extension_down_{int(round(size*1000))}mrad'
        accepted = bool(path['public_path_gate'] and path['native_eef_single_action_legal'] and (gap is None or gap >= margin))
        evidence['candidate_diagnostics'][key] = {
            'target': target, 'public_path': path,
            'minimum_public_hand_gap_to_declared_reference_m': gap,
            'height_reference_kind': reference_kind,
            'declared_reference_z_m': reference_z,
            'candidate_filter_passed': accepted,
            'remaining_axis_angle_deg': round(np.degrees(max(0,angle-size)), 2)}
        if not accepted:
            continue
        targets[key] = target
        delta = (np.asarray(target['right']['position'])-current[:3, 3])*1000
        height_text = (f'Public five-step hand mesh gap to {reference_kind} stays at least {gap*1000:.2f}mm. ' if gap is not None else reference_kind+'. ')
        options[key] = (
            f'ONE complete FIVE-step OPEN right-hand pose action: world XYZ delta {delta.round(2).tolist()}mm AND world rotation vector {(rotation_axis*size).round(5).tolist()}rad occur together; left held. '
            f'Public finger-extension/downward-source-plane angle {np.degrees(angle):.1f}→{np.degrees(max(0,angle-size)):.1f}deg. '
            'Keeps the PUBLIC open-facet midpoint approximately at its current world position while turning the finger extension toward the assumed horizontal source; LINK6 itself moves. '
            + height_text +
            'This is NOT source contact, scene clearance, object-normal ground truth or a grasp. Judge fresh THREE RGB, whole hand/arm swept corridor and camera change; select another complete action or STOP if unsupported. Reobserve before any close.')
    return options, targets, evidence
