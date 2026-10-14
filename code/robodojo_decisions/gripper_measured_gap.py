"""Public finger geometry from actual robot encoders, never contact/force."""
import numpy as np
from camera_geometry import eef_transform
from gripper_pad_projection import inspect


def evidence(obs, previous=None):
    if obs.get('measured_gripper_joint_state') is None:
        return {'available':False,'reason':'No current actual finger encoders'}
    def gap(o):
        pads=inspect(o,o['camera_calibration'])['rows']
        centres=[np.asarray(pads[n]['inner_facet_world_xyz_m']).mean(0) for n in ('link7','link8')]
        axis=eef_transform(o['current_eef']['right'])[:3,1]
        return float(abs((centres[0]-centres[1])@axis)*1000)
    current=gap(obs);old=None
    if previous is not None and previous.get('measured_gripper_joint_state') is not None:
        if previous['episode_id']!=obs['episode_id'] or previous['step_id']>=obs['step_id']:
            raise ValueError('Finger-gap change requires ordered same-episode robot state')
        old=gap(previous)
    joints=obs['measured_gripper_joint_state']['arms']['right']
    return {'available':True,'current_step_id':obs['step_id'],
        'actual_finger_prismatic_displacements_mm':[round(x*1000,3) for x in joints['joint_positions_m']],
        'public_opposing_facet_gap_along_closing_axis_mm':round(current,3),
        'previous_actual_gap_mm':round(old,3) if old is not None else None,
        'actual_gap_change_mm':round(current-old,3) if old is not None else None,
        'meaning':'joint7/joint8 are opening displacements: larger means fingers farther open; zero is the joint closed limit. CLOSED is a requested command, not measured closure. A nonzero measured gap under CLOSED may mean enclosed material or incomplete settling, not automatically failed grasp. A stable gap plus CURRENT real material/fingers and SAME-source motion can support a grasp hypothesis, but encoders/mesh alone do NOT prove contact, force, holding or source height.'}
