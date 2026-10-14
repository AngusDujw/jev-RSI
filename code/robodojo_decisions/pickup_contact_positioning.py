"""Explicit uncertain near-contact positioning, distinct from free-space clearance."""
import numpy as np
from pickup_rgb_axes import _targets
from robot_path_preview import preview
from camera_geometry import gripper_height_above_landmark


def build(obs, material, orientation, plane, table):
    evidence={'eligible':False,'scope':'Uncertain simulated OPEN near-contact positioning attempt, NOT certified scene clearance/contact. Original strict grasp certificate is separate. Current RGB Luna review, native first IK and five-step tracking remain mandatory.'}
    if material is None or table is None or plane is None:
        return {},{},evidence
    if (table['current_step_id']!=obs['step_id'] or plane['current_step_id']!=obs['step_id'] or
            not plane.get('contact_precision_eligible') or
            obs['current_eef']['right']['gripper_opening_command']<.95):
        return {},{},evidence
    error=np.asarray(material['representative_material_point']['nearest_opposing_surface_midpoint_delta_xyz_mm'])
    angle=(orientation or {}).get('finger_extension_vs_downward_normal_angle_deg',180)
    if angle>10 or np.linalg.norm(error)>35 or np.linalg.norm(error[:2])>15 or error[2]>=-3:
        return {},{},evidence
    coefficients=table['near_horizontal_plane_z_ax_by_c']
    options,targets={},{}
    evidence.update(eligible=False,current_source_minus_public_surface_xyz_mm=error.tolist(),
        current_axis_angle_deg=angle,current_rgb_table_plane=coefficients,
        rgb_table_upper_reference_m=table['upper_height_for_robot_check_m'],programs={})
    for amount in (.001,.003,.005):
        target=_targets(obs,'z',-1,amount)
        path=preview(obs,target['right'],None,5)
        nominal_gaps=[];upper_gaps=[]
        for row in path['predicted_joint_path']:
            pose={'position':row['predicted_link6_position_m'],'quaternion_wxyz':row['predicted_link6_quaternion_wxyz']}
            x,y,_=pose['position'];height=coefficients[0]*x+coefficients[1]*y+coefficients[2]
            gap=gripper_height_above_landmark(pose,[0,0,height],descent_m=0)['hand_above_landmark_plane_after_m']
            nominal_gaps.append(gap);upper_gaps.append(gap-(table['upper_height_for_robot_check_m']-height))
        name=f'contact_positioning_open_down_{int(amount*1000)}mm'
        accepted=bool(path['public_path_gate'] and path['native_eef_single_action_legal'] and min(nominal_gaps)>=.001)
        evidence['programs'][name]={'accepted':accepted,'delta_world_xyz_mm':[0,0,-amount*1000],
            'minimum_hand_gap_to_nominal_RGB_table_mm':round(min(nominal_gaps)*1000,3),
            'minimum_hand_gap_to_uncertain_upper_RGB_reference_mm':round(min(upper_gaps)*1000,3),
            'strict_upper_reference_6mm_free_space_gate_passed':min(upper_gaps)>=.006,
            'public_robot_five_step_gate_passed':bool(path['public_path_gate'])}
        if accepted:
            targets[name]=target
            options[name]=f'ONE complete five-step OPEN world-Z {-amount*1000:g}mm uncertain near-contact positioning attempt, orientation/left held. No certified free-space/contact claim. Judge CURRENT actual fingers/source and short corridor; choose STOP if unsupported.'
    evidence['eligible']=bool(targets)
    return options,targets,evidence
