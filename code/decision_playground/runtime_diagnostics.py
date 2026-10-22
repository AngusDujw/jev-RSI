"""Read-only articulation evidence for outer development review, never a policy input."""
from __future__ import annotations
import copy
import math


def _snapshot(value, env_idx, indices):
    # PhysX getters reuse their buffers. Copy to ordinary values immediately.
    if hasattr(value, "detach"):
        value = value.detach().cpu().tolist()
    elif hasattr(value, "tolist"):
        value = value.tolist()
    row = value[env_idx]
    selected = copy.deepcopy([row[index] for index in indices])
    def check(item):
        if isinstance(item, (list, tuple)):
            for child in item:
                check(child)
        elif not isinstance(item, (int, float)) or not math.isfinite(item):
            raise ValueError("Unavailable or nonfinite runtime numeric value")
    check(selected)
    return selected


def articulation_snapshot(manager, robot, env_idx):
    articulation = manager.robot_key[manager.robot_list.index(robot)]
    indices = list(robot.arm_joint_indices)
    result = {
        "scope": "outer_only_robot_runtime_diagnostic",
        "joint_indices": indices,
        "joint_names": [articulation.joint_names[index] for index in indices],
        "angular_units": "radian",
        "torque_warning": "Implicit drive torque is not directly exposed. Estimated PD and projected joint reactions are not measured motor torque or proof of contact.",
        "contact_pair_evidence": "This articulation snapshot does not read contact pairs. Only a separately validated outer contact-report stream supplies pair evidence; missing data is not zero contact.",
        "data": {}, "physx": {}, "errors": {},
    }
    for field in ("joint_pos", "joint_vel", "joint_pos_target", "joint_vel_target",
                  "joint_pos_limits", "soft_joint_pos_limits", "joint_vel_limits",
                  "joint_effort_limits", "joint_stiffness", "joint_damping",
                  "computed_torque", "applied_torque"):
        try:
            label = "estimated_" + field if field in ("computed_torque", "applied_torque") else field
            result["data"][label] = _snapshot(getattr(articulation.data, field), env_idx, indices)
        except Exception as error:
            result["errors"]["data." + field] = f"{type(error).__name__}: {error}"
    for method in ("get_dof_positions", "get_dof_velocities", "get_dof_position_targets",
                   "get_dof_velocity_targets", "get_dof_limits", "get_dof_stiffnesses",
                   "get_dof_dampings", "get_dof_max_forces", "get_dof_max_velocities",
                   "get_dof_actuation_forces", "get_dof_projected_joint_forces"):
        try:
            result["physx"][method] = _snapshot(
                getattr(articulation.root_physx_view, method)(), env_idx, indices)
        except Exception as error:
            result["errors"]["physx." + method] = f"{type(error).__name__}: {error}"
    result["physx_semantics"] = {
        "get_dof_actuation_forces": "User feedforward actuation, not solved implicit drive torque.",
        "get_dof_projected_joint_forces": "Incoming joint reaction projected on joint axes, not an isolated drive torque or identified contact pair.",
    }
    return result
