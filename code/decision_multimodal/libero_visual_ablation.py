"""Actor XYZ-input ablations; original frontend and motor scaling stay intact."""
from copy import deepcopy
import hashlib
import io
import math
import re

from legacy_decisions import english
from libero_multimodal import MultimodalAPI

GOALS = {
    'observe': 'Identify the task-specified source, destination or articulated control in the current views.',
    'select_handle': 'Select the task-specified visible drawer handle.',
    'select': 'Select an offered grasp candidate for the task-specified source.',
    'prepare': 'Prepare the gripper as required for the current manipulation while keeping its control point still.',
    'approach': 'Reach the predefined approach or clearance waypoint for the source or control named by the task.',
    'align': 'Align the hand with the selected visible grasp site or control at its approach clearance.',
    'descend': 'Bring the open fingers to the task-prescribed source grasp site.',
    'insert': 'Bring the open fingers into the selected task-prescribed grasp configuration.',
    'contact': 'Establish the task-prescribed hand configuration at the visible handle or control.',
    'grasp': 'Keep the control point still and complete the prescribed closure trial; holding is tested later.',
    'lift': 'Raise the closed hand toward the prescribed lift-test waypoint and then assess the retained holding check.',
    'test_lift': 'Complete the prescribed small lift test for the current source grasp.',
    'carry': 'Carry the source toward the predefined receiver approach or transfer waypoint.',
    'carry_lateral': 'Carry the source through the predefined receiver approach waypoint.',
    'lower': 'Bring the held source toward its task-prescribed placement configuration, or the prepared pusher toward its plate contact site.',
    'orient_receiver': 'Orient the held source for the task-prescribed receiver configuration.',
    'settle_receiver': 'Complete the current receiver-settling operation using the retained stage feedback.',
    'push': 'Move the supported plate toward the task-prescribed stove-front destination.',
    'pull': 'Open the task-specified drawer by pulling its handle outward.',
    'turn': 'Turn the task-specified stove control in its prescribed direction.',
    'release': 'Keep the control point still and complete opening at the task-prescribed destination or control.',
    'retreat': 'Withdraw the hand to reveal the manipulated object and verify the requested visible relation.',
    'verify': 'Complete the prescribed visual verification of the task relation or articulated control.',
    'clear_opening': 'Withdraw the empty hand clear of the opened drawer before manipulating the source.',
    'recover_up': 'Withdraw the hand to its predefined recovery clearance while preserving the current grip until clear.',
    'clear_receiver': 'Withdraw from the receiver through the predefined clearance waypoint.',
    'recover_open': 'Keep the control point still and open the fingers for the next permitted grasp attempt.'}
FEEDBACK = {
    'target_arrival', 'position_arrived', 'orientation_arrived', 'contract_satisfied',
    'holding_check', 'holding_status', 'gripper_actuation_complete', 'reobserve_available',
    'visible_contact_candidate', 'support_stall_release_candidate', 'carry_support_transfer_candidate',
    'blocked_visible_contact_trial', 'one_sided_rim_trial', 'passed', 'valid', 'status'}


def mask_xyz(request):
    """Whitelist retained evidence: never recursively copy arbitrary geometry."""
    result = deepcopy(request)
    old = request['state']
    stage = old.get('stage', old.get('operation'))
    name = stage.split(':')[-1]
    kept = {key: deepcopy(old[key]) for key in (
        'task', 'stage', 'operation', 'next_phase', 'next_stage', 'next_operation',
        'required_rotation_world_rad', 'rotation_tolerance_rad',
        'orientation_arrived', 'allowed_transitions', 'stalls', 'blocked_action_count',
        'phase_decisions', 'grasp_attempts', 'failed_candidates', 'selected_candidate',
        'segment_index', 'segment_count', 'axis_hold_tolerance_mm', 'hold_tolerance_m',
        'arrival_tolerance_mm', 'arrival_tolerance_m', 'residual_correction_available') if key in old}
    if isinstance(old.get('gripper'), dict):
        kept['gripper'] = {key:deepcopy(old['gripper'][key]) for key in (
            'aperture_mm', 'last_command', 'required_state', 'needed_for_contract',
            'phase_ticks', 'command_ticks', 'executed_command_ticks', 'closure_nearly_empty',
            'advance_action_block_native_ticks', 'next_action_block_native_ticks') if key in old['gripper']}
    for key in ('measurement_status', 'completion_evidence', 'holding_evidence', 'visible_goal_evidence'):
        if isinstance(old.get(key), dict):
            kept[key] = {k:v for k,v in old[key].items() if k in FEEDBACK and (v is None or isinstance(v,(bool,str)))}
    if isinstance(old.get('public_entity_slots'), dict):
        kept['public_entity_slots'] = {k:v for k,v in old['public_entity_slots'].items() if isinstance(v,str)}
    kept['current_stage_semantic_goal'] = GOALS.get(name,
        'Complete the existing '+name.replace('_',' ')+' operation for the task entities at its prescribed waypoint.')
    kept['semantic_goal_specific'] = name in GOALS
    # Gripper-only original contracts do not require a camera-derived XYZ target.
    if name in ('grasp', 'release', 'prepare', 'recover_open', 'settle_receiver'):
        contract = old.get('phase_contract', old.get('operation_contract', old.get('stage_contract','')))
        durations = re.findall(r'(?:at least|>=)\s*(\d+(?:\.\d+)?)\s*(?:executed\s*)?(?:native\s*)?ticks', contract, re.I)
        apertures = re.findall(r'(?:opening|aperture).{0,30}?(?:at least|>=)\s*(\d+(?:\.\d+)?)\s*mm', contract, re.I)
        apertures += re.findall(r'(?:at least|>=)\s*(\d+(?:\.\d+)?)\s*mm\s*(?:aperture|opening)', contract, re.I)
        kept['robot_actuation_requirements'] = dict(minimum_command_ticks=[float(x) for x in durations],
            minimum_open_aperture_mm=[float(x) for x in apertures])
        kept['robot_actuation_contract'] = ('Keep the robot control reference still and complete the '
            'current gripper operation using the supplied original duration/aperture requirements '
            'and retained completion feedback. A later holding test is not a prerequisite.')
    kept['input_scope'] = ('Current RGB, measured robot state, public camera calibration, semantic stage goal, '
        'original output permissions, original rotation residuals and retained visual holding/completion flags. No XYZ residuals, '
        'axis-relative relations, absolute frontend target coordinates or residual-scaled command history.')
    result['state'] = kept
    for axis in 'xyz':
        if axis in result['questions']:
            result['questions'][axis]['instructions'] = (
                f'For world {axis.upper()}, which existing categorical direction brings the measured '
                'control reference toward the current stage goal? Use the current camera evidence, '
                'public calibration and measured robot state. Keep the control point still in '
                'gripper-only stages. Image up/right is not a fixed world direction. '
                'Use the original tolerance and output categories; no numeric residual is supplied.')
    if 'transition' in result['questions']:
        result['questions']['transition']['instructions'] = (
            'Decide the current stage edge from retained completion/holding feedback, output permissions '
            'and current semantic goal. Advance when the current contract is complete, including any '
            'explicitly retained bounded-trial candidate. A future holding test does not delay a '
            'completed closure trial. Before arrival at a lift-test point an unperformed test is not '
            'failed. Preserve the robot_actuation_contract duration and aperture when supplied. '
            'Reobserve only when available and justified by a failed check or the original stall '
            'condition. A current bounded-trial flag permits its original exception to arrival; '
            'it is not confirmed holding or placement. Stop if a genuine failure is unrecoverable.')
    for key, question in result['questions'].items():
        if key not in ('x','y','z','rx','ry','rz','gripper','transition'):
            question['instructions'] = 'Select one offered category using the current source identity and camera evidence. Numeric candidate geometry is not supplied.'
            question['criteria'] = {value:'Available category '+value for value in question['criteria']}
    english(result)
    return result


def control_points(state, robot):
    axes = state.get('translation_axes', {})
    current, target = [], []
    for i, axis in enumerate('xyz'):
        row = axes.get(axis, {})
        position = row.get('current_coordinate_m', robot['robot0_eef_pos'][i])
        goal = row.get('goal_coordinate_m')
        if goal is None and 'goal_minus_current_mm' in row:
            goal = position + row['goal_minus_current_mm']/1000
        if goal is None or not all(math.isfinite(float(v)) for v in (position, goal)):
            return None, None
        current.append(position)
        target.append(goal)
    return current, target


class VisualAblationAPI(MultimodalAPI):
    condition = 'no_xyz_raw'
    profile = 'libero-rgb-raw'

    def revise(self, original):
        self.unmasked_state = deepcopy(original['state'])
        return mask_xyz(super().revise(original))


class WaypointAPI(VisualAblationAPI):
    condition = 'no_xyz_waypoint'
    profile = 'libero-rgb-waypoint'

    def transform_views(self, views, robot):
        import numpy as np
        from PIL import Image, ImageDraw
        current, target = control_points(self.unmasked_state, robot)
        output = self.asset_root/'overlays'
        output.mkdir(exist_ok=True)
        for view in views:
            picture = Image.open(io.BytesIO(view['raw'])).convert('RGB')
            draw = ImageDraw.Draw(picture)
            matrix = np.linalg.inv(np.asarray(view['camera_to_world'],float))
            K = np.asarray(view['K'],float)
            flags = {}
            for label, point, color in [('current',current,'white'),('target',target,'yellow')]:
                pixel = None
                if point is not None:
                    camera = matrix @ np.r_[point,1.]
                    if camera[2] > 0:
                        uv = K @ camera[:3]
                        u,v = uv[:2]/uv[2]
                        if 0 <= u < view['width'] and 0 <= v < view['height']:
                            pixel = (float(u),float(v))
                flags[label+'_marker_visible'] = pixel is not None
                if pixel is not None:
                    u,v = pixel
                    if label == 'current':
                        draw.ellipse((u-5,v-5,u+5,v+5), outline=color, width=2)
                    else:
                        draw.line((u-9,v,u+9,v),fill=color,width=3)
                        draw.line((u,v-9,u,v+9),fill=color,width=3)
            buffer = io.BytesIO()
            picture.save(buffer,format='PNG')
            path = output/f'{view["native_observation_counter"]:06d}-{self.calls:04d}-{view["camera"]}.png'
            path.write_bytes(buffer.getvalue())
            view.update(original_rgb_path=view['rgb_path'], rgb_path=str(path), raw=buffer.getvalue(),
                sha256=hashlib.sha256(buffer.getvalue()).hexdigest(), **flags)
            view['description'] += (' White circle: measured robot control reference. Yellow cross: '
                'the original frontend active positional target. These are projected annotations '
                'and may lie behind scene surfaces; they do not establish clearance or contact. '
                'Off-image or behind-camera points are omitted, never clamped to an image edge.')
        return views
