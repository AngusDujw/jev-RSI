"""Independent rate-instrumented IK enumeration; original numerical builder stays unchanged."""
from itertools import product
import time

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

from kinematics import solve_tcp


def compare_motion_paths_with_rates(forward, seed, limits, control_dt_s, joint_velocity_limit_rad_s, translation_step=.02, rotation_step=.10):
    """Enumerate all 27 translations x 7 allowed rotations using the native IK gate."""
    if not np.isfinite([control_dt_s, joint_velocity_limit_rad_s]).all() or min(control_dt_s, joint_velocity_limit_rad_s) <= 0:
        raise ValueError("Public control interval and joint velocity limit must be finite and positive")
    started = time.monotonic()
    seed, limits = np.asarray(seed, float), np.asarray(limits, float)
    if seed.ndim != 1 or limits.shape != (len(seed), 2) or not np.isfinite(seed).all() or not np.isfinite(limits).all():
        raise ValueError('Invalid current robot joints or public joint bounds')
    if not np.isfinite([translation_step, rotation_step]).all() or min(translation_step, rotation_step) <= 0:
        raise ValueError('Motion increments must be finite and positive')
    start = np.asarray(forward(seed), float)
    if start.shape != (4, 4) or not np.isfinite(start).all():
        raise ValueError('Invalid public-robot forward transform')
    names = {-1: 'negative', 0: 'hold', 1: 'positive'}
    translations = list(product((-1, 0, 1), repeat=3))
    rotations = [('hold', 0)] + [(axis, sign) for axis in ('yaw', 'pitch', 'roll') for sign in (-1, 1)]
    fractions = np.linspace(.2, 1., 5)
    passed, diagnostics, peak_rates, rate_passes = [], [], [], []
    for xyz in translations:
        row, details, rate_row, rate_pass_row = [], [], [], []
        for axis, sign in rotations:
            target = start.copy()
            target[:3, 3] += np.asarray(xyz) * translation_step
            rv = np.zeros(3)
            if axis != 'hold':
                rv[{'pitch': 0, 'roll': 1, 'yaw': 2}[axis]] = sign * rotation_step
            target[:3, :3] = Rotation.from_rotvec(rv).as_matrix() @ start[:3, :3]
            interpolation = Slerp([0., 1.], Rotation.from_matrix(np.array([start[:3, :3], target[:3, :3]])))
            q = seed.copy()
            steps, waypoint_rates = [], []
            for fraction in fractions:
                position = start[:3, 3] + fraction * (target[:3, 3] - start[:3, 3])
                previous_q = q.copy()
                q, diagnostic = solve_tcp(forward, position, interpolation(fraction).as_matrix(), q, limits)
                waypoint_rates.append(float(np.max(np.abs(q - previous_q)) / control_dt_s))
                steps.append(dict(fraction=float(fraction), **diagnostic))
                if not diagnostic['passed']:
                    break
            row.append(bool(len(steps) == 5 and all(s['passed'] for s in steps)))
            rate_row.append(max(waypoint_rates))
            rate_pass_row.append(bool(max(waypoint_rates) <= joint_velocity_limit_rad_s) if row[-1] else None)
            details.append(dict(waypoints_tested=len(steps),
                first_failed_fraction=next((s['fraction'] for s in steps if not s['passed']), None),
                max_position_error_m=max(s['position_error_m'] for s in steps),
                max_rotation_error_rad=max(s['rotation_error_rad'] for s in steps)))
        passed.append(row)
        diagnostics.append(details)
        peak_rates.append(rate_row)
        rate_passes.append(rate_pass_row)
    information = dict(
        frame='Shared world frame; XYZ translations and rotations about the current TCP.',
        translation_step_m=float(translation_step), rotation_step_rad=float(rotation_step),
        translation_axes=['x', 'y', 'z'],
        translation_rows=[[names[v] for v in xyz] for xyz in translations],
        rotation_columns=[{a: names[sign] if a == axis else 'hold' for a in ('yaw', 'pitch', 'roll')}
                          for axis, sign in rotations],
        numerical_ik_path_passes=passed,
        meaning='Each matrix row uses the XYZ choices in translation_rows; each column uses the yaw/pitch/roll choices in rotation_columns. True means all five interpolated waypoints pass the existing numerical robot IK gate for that complete combination. False means at least one waypoint fails that same gate and the current controller would reject the combination before execution. All combinations are listed in fixed order, without ranking or selecting an action.',
        limitations='Current measured joints, public robot FK and joint bounds only. This does not verify physical tracking, velocity limits, self-collision, scene clearance, contact, holding or task completion. A numerical IK pass is not a safe-action certificate. No object state or historical feedback is used. The controller gate remains unchanged.')
    audit = dict(seconds=time.monotonic() - started, waypoint_fractions=fractions.tolist(),
                 candidate_count=len(translations) * len(rotations), diagnostics=diagnostics,
                 joint_rate_details=dict(control_dt_s=float(control_dt_s),
                    joint_velocity_limit_rad_s=float(joint_velocity_limit_rad_s),
                    maximum_tested_joint_rates_rad_s=peak_rates,
                    five_waypoint_rate_passes=rate_passes))
    return information, audit


def present_motion_rate_checks(information, audit):
    """Attach unranked predicted rate comparisons to the named numerical checks."""
    from robot_motion_format import present_motion_checks
    result = present_motion_checks(information, 'named')
    rates = audit['joint_rate_details']
    labels = ['all_rotations_hold'] + [a+'_'+v for a in ('yaw', 'pitch', 'roll') for v in ('negative', 'positive')]
    for index, record in enumerate(result['complete_motion_checks']):
        record['rotation_max_tested_joint_rates_rad_s'] = dict(zip(labels, rates['maximum_tested_joint_rates_rad_s'][index]))
        record['rotation_five_waypoint_rate_passes'] = dict(zip(labels, rates['five_waypoint_rate_passes'][index]))
    result['joint_rate_comparison'] = dict(
        control_dt_s=rates['control_dt_s'], configured_joint_velocity_limit_rad_s=rates['joint_velocity_limit_rad_s'],
        source='Public runtime control interval and public X5 arm actuator velocity_limit_sim configuration.',
        meaning='For each complete motion, the maximum tested joint rate is max(abs(next joint target minus previous joint target))/control_dt, across all arm joints and tested waypoints. The first waypoint is compared with current measured joints. Rates are rad/s. The five-waypoint rate flag is true when all five numerical IK waypoints exist and every target rate is within the configured limit, false when the complete path exceeds that limit, and null when numerical IK failed before a complete path was established. A partial-path maximum is only a lower bound on a missing full path. No combination is selected or ranked.',
        limitations='These are target-waypoint comparisons, not achieved physical velocities or a tracking guarantee. Acceleration, torque, self-collision, scene clearance, contact and holding are not verified. Numerical IK flags and the controller gate remain unchanged. No object state or historical feedback is used.')
    return result
