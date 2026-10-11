"""Read-only numerical IK diagnostics for a pose chosen by GPT, never a policy."""
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


def probe_pose(fk, root, limits, current, position, quaternion):
    limits = np.asarray(limits, float)
    lower, upper = limits[:, 0]+1e-6, limits[:, 1]-1e-6
    goal_position = np.asarray(position, float)
    goal_rotation = Rotation.from_quat(np.asarray(quaternion)[[1, 2, 3, 0]])
    def residual(q):
        predicted = root @ fk.matrix(q)
        translation = predicted[:3, 3]-goal_position
        angular = (goal_rotation*Rotation.from_matrix(predicted[:3, :3]).inv()).as_rotvec()
        return np.r_[translation/.01, angular/.1]
    seeds = [np.asarray(current), (lower+upper)/2, lower+.25*(upper-lower), lower+.75*(upper-lower)]
    solutions = []
    for seed in seeds:
        solution = least_squares(residual, np.clip(seed, lower, upper), bounds=(lower, upper),
                                 max_nfev=120, ftol=1e-7, xtol=1e-7, gtol=1e-7)
        error = residual(solution.x)
        p_error, r_error = float(np.linalg.norm(error[:3])*.01), float(np.linalg.norm(error[3:])*.1)
        solutions.append((p_error/.01+r_error/.1, p_error, r_error))
        if p_error < .003 and r_error < .04:
            break
    _, p_error, r_error = min(solutions)
    return dict(numerical_candidate_found=p_error < .012 and r_error < .12,
                position_residual_m=p_error, rotation_residual_rad=r_error,
                interpretation='numerical robot-only IK; failure is not an impossibility proof; no collision or grasp validation',
                physical_steps=0)
