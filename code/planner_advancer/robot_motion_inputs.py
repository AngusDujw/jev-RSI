"""Optional current-robot IK comparisons; no scene information or action selection."""
from itertools import product
import time

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

from kinematics import solve_tcp


def compare_motion_paths(forward, seed, limits, translation_step=.02, rotation_step=.10):
    """Enumerate all 27 translations x 7 allowed rotations using the native IK gate."""
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
    passed, diagnostics = [], []
    for xyz in translations:
        row, details = [], []
        for axis, sign in rotations:
            target = start.copy()
            target[:3, 3] += np.asarray(xyz) * translation_step
            rv = np.zeros(3)
            if axis != 'hold':
                rv[{'pitch': 0, 'roll': 1, 'yaw': 2}[axis]] = sign * rotation_step
            target[:3, :3] = Rotation.from_rotvec(rv).as_matrix() @ start[:3, :3]
            interpolation = Slerp([0., 1.], Rotation.from_matrix(np.array([start[:3, :3], target[:3, :3]])))
            q = seed.copy()
            steps = []
            for fraction in fractions:
                position = start[:3, 3] + fraction * (target[:3, 3] - start[:3, 3])
                q, diagnostic = solve_tcp(forward, position, interpolation(fraction).as_matrix(), q, limits)
                steps.append(dict(fraction=float(fraction), **diagnostic))
                if not diagnostic['passed']:
                    break
            row.append(bool(len(steps) == 5 and all(s['passed'] for s in steps)))
            details.append(dict(waypoints_tested=len(steps),
                first_failed_fraction=next((s['fraction'] for s in steps if not s['passed']), None),
                max_position_error_m=max(s['position_error_m'] for s in steps),
                max_rotation_error_rad=max(s['rotation_error_rad'] for s in steps)))
        passed.append(row)
        diagnostics.append(details)
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
                 candidate_count=len(translations) * len(rotations), diagnostics=diagnostics)
    return information, audit
