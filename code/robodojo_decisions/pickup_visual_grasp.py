"""Current image evidence for an explicitly uncertain simulated grasp attempt."""
from pathlib import Path
import os
import numpy as np
from scipy.ndimage import distance_transform_edt
from pickup_visual_hull import _green_mask
from gripper_pad_projection import inspect
from pickup_rgb_axes import _targets
from robot_path_preview import preview


def propose(obs,material,orientation):
    if material is None or float(obs['current_eef']['right']['gripper_opening_command'])<.95:
        return None,{'eligible':False,'reason':'Current material or open hand unavailable'}
    error=material['representative_material_point']['nearest_opposing_surface_midpoint_delta_xyz_mm']
    norm=float(np.linalg.norm(error))
    angle=(orientation or {}).get('finger_extension_vs_downward_normal_angle_deg',180)
    tighter=os.environ.get('ROBODOJO_PICKUP_TIGHTER_GRASP_ALIGNMENT')=='1'
    max_error,max_angle=(12,10) if tighter else (35,30)
    if tighter and os.environ.get('ROBODOJO_PICKUP_CONTACT_POSITIONING_ATTEMPT')=='1':max_error=5
    if os.environ.get('ROBODOJO_PICKUP_CLOSE_ERROR_3MM')=='1':
        max_error=min(max_error,3)
    interval=material['representative_material_point'].get('same_named_pixel_height_hypothesis_region_error_xyz_mm',{})
    all_below=bool(tighter and interval and interval['q95'][2]<-5)
    if norm>max_error or angle>max_angle or all_below:
        return None,{'eligible':False,'reason':'Not a near-source, approximately downward attempt; a projected material band alone is insufficient',
            'uncertain_error_norm_mm':norm,'robot_axis_angle_deg':angle,
            'maximum_attempt_error_mm':max_error,'maximum_attempt_axis_angle_deg':max_angle,
            'entire_same_pixel_height_interval_below_public_surface_by_over_5mm':all_below}
    pads=inspect(obs,obs['camera_calibration'])['rows']
    boxes=sorted([row['projected_bbox_xyxy'] for row in pads.values()],key=lambda box:(box[0]+box[2])/2)
    left=max(0,int(np.ceil(boxes[0][2])));right=min(639,int(np.floor(boxes[1][0])))
    top=max(0,int(np.ceil(max(boxes[0][1],boxes[1][1])))-12)
    bottom=min(479,int(np.floor(min(boxes[0][3],boxes[1][3])))+12)
    image=next(row['path'] for row in obs['images'] if row['camera']=='cam_right_wrist')
    mask=_green_mask(Path(image),'cam_right_wrist');distance=distance_transform_edt(mask)
    interior=mask & (distance>=max(3.,.6*float(np.percentile(distance[mask],95))))
    count=int(interior[top:bottom+1,left:right+1].sum()) if right>left and bottom>top else 0
    evidence={'eligible':count>=100,'current_step_id':obs['step_id'],
        'current_thick_green_pixels_between_projected_faces':count,
        'public_projected_band_xyxy':[left,top,right,bottom],
        'declared_projection_margin_px':12,'uncertain_error_norm_mm':round(norm,3),
        'maximum_attempt_error_mm':max_error,
        'robot_axis_angle_deg':angle,
        'scope':'SIMULATED qualitative grasp ATTEMPT hypothesis. Current thick green pixels are between projected PUBLIC faces in 2D, not verified true opposing-pad enclosure. Depth remains uncertain; this does NOT pass or replace the strict metric precision/3D closing-volume certificate. Luna must inspect actual current fingers/material and may choose further alignment or STOP. Closing never establishes holding; require next RGB and independent source-following.'}
    if count<100:return None,evidence
    target=_targets(obs,'x',1,0);target['right']['gripper_closed']=True
    path=preview(obs,target['right'],None,5)
    evidence['public_path']=path
    if not(path['public_path_gate'] and path['native_eef_single_action_legal']):
        evidence['eligible']=False
        return None,evidence
    return target,evidence
