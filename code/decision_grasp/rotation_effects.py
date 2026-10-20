"""Enumerate robot-only rotation consequences; never choose or repair an action."""
import numpy as np
from scipy.spatial.transform import Rotation


def rotation_effects(robot):
    result = {}
    for arm in ('left', 'right'):
        measured = np.asarray(robot[arm]['tool_rotation_world_from_local'], dtype=float)
        if measured.shape != (3, 3) or not np.isfinite(measured).all():
            raise ValueError('Expected a finite measured tool rotation')
        options = {'hold': measured}
        for name, index in (('yaw', 2), ('pitch', 0), ('roll', 1)):
            for direction, sign in (('negative', -1), ('positive', 1)):
                vector = np.zeros(3)
                vector[index] = sign * 0.10
                options[name + '_' + direction] = Rotation.from_rotvec(vector).as_matrix() @ measured
        result[arm] = {name: {
            'predicted_finger_extension_axis_world': matrix[:, 0].tolist(),
            'predicted_jaw_sliding_axis_world': matrix[:, 1].tolist(),
        } for name, matrix in options.items()}
    return result
