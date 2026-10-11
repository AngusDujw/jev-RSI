"""Measured robot-only convergence for an unchanged bounded primitive target."""
import numpy as np
from scipy.spatial.transform import Rotation


def pose_errors(obs, targets, arm):
    index = ('left', 'right').index(arm)
    desired = targets[arm]
    position = float(np.linalg.norm(np.asarray(obs['eef_positions'][index])-desired['position']))
    q = np.asarray(obs['eef_quaternions_wxyz'][index])
    goal = np.asarray(desired['quaternion_wxyz'])
    rotation = float((Rotation.from_quat(q[[1,2,3,0]]) *
                      Rotation.from_quat(goal[[1,2,3,0]]).inv()).magnitude())
    return dict(position_error_m=position, rotation_error_rad=rotation)


def converged(errors, cfg):
    return (errors['position_error_m'] <= cfg['tracking_position_tolerance_m'] and
            errors['rotation_error_rad'] <= cfg['tracking_rotation_tolerance_rad'])
