"""Pure Decisions action contract. No network, credentials, or environment access.

Native EE poses refer to link6; all translations/rotations below refer to the
fingertip TCP. Gripper commands use native 0=closed, 1=open. A measured opening
is never substituted for the previous command.
"""
from collections.abc import Mapping, Sequence
import math

ARMS = ("left", "right")
TCP_OFFSET = (.15007, 0., 0.)
TRANSLATION_M = .02
ROTATION_RAD = .10
ROTATIONS = ("hold", "yaw_negative", "yaw_positive", "pitch_negative",
             "pitch_positive", "roll_negative", "roll_positive")


def questions():
    """Return ten independent categorical questions, in arm/XYZ/rotation/grip order."""
    result = []
    for arm in ARMS:
        for axis in "xyz":
            result.append(dict(type="choice", name=f"{arm}_{axis}",
                instructions=f"Select the {arm} fingertip TCP world {axis.upper()} translation: negative, hold, or positive 0.020 m. Use the current images, measured robot state, and supplied applicable evidence.",
                choices=[dict(value=v, description=d) for v, d in (
                    ("negative", "Move -0.020 m along this world axis."),
                    ("hold", "No translation along this axis."),
                    ("positive", "Move +0.020 m along this world axis."))]))
        choices = [dict(value="hold", description="Hold orientation.")]
        for axis, world in (("yaw", "Z"), ("pitch", "X"), ("roll", "Y")):
            for direction in ("negative", "positive"):
                choices.append(dict(value=f"{axis}_{direction}", description=
                    f"Rotate {direction} 0.10 rad about world {world} at the TCP; hold other rotation channels."))
        result.append(dict(type="choice", name=f"{arm}_rotation",
            instructions=f"Select exactly one rotation option for the {arm} arm. Translation may accompany rotation.", choices=choices))
        result.append(dict(type="choice", name=f"{arm}_gripper",
            instructions=f"Select the {arm} gripper command.", choices=[dict(value=v, description=d)
                for v, d in (("keep", "Retain the previous commanded gripper state."),
                             ("open", "Command fully open."), ("close", "Command fully closed."))]))
    return result


def validate_answers(answers):
    """Validate a name->choice mapping or raw API answer list, preserving duplicates.

    Raw list records must contain name and choice. The documented transport
    metadata type/confidence/probabilities is preserved in the raw response and
    does not affect action selection. Validate the raw list before building
    any dictionary: dictionary construction would silently erase duplicate names.
    Reject invalid output without repairing, replacing, or resampling it.
    """
    if isinstance(answers, Mapping):
        pairs = list(answers.items())
    elif isinstance(answers, Sequence) and not isinstance(answers, (str, bytes)):
        pairs = []
        for item in answers:
            if (not isinstance(item, Mapping) or not {"name", "choice"} <= set(item)
                    or set(item)-{"name", "choice", "type", "confidence", "probabilities"}):
                raise ValueError("Unexpected Decisions answer fields")
            pairs.append((item["name"], item["choice"]))
    else:
        raise ValueError("Answers must be a mapping or raw answer list")
    allowed = {q["name"]: {c["value"] for c in q["choices"]} for q in questions()}
    names = [name for name, _ in pairs]
    if any(not isinstance(n, str) for n in names) or len(names) != 10 or len(set(names)) != 10 or set(names) != set(allowed):
        raise ValueError("Expected exactly ten unique contract answer names")
    for name, choice in pairs:
        if not isinstance(choice, str) or choice not in allowed[name]:
            raise ValueError(f"Invalid choice for {name}")
    return dict(pairs)


def _vector(value, size=None):
    if isinstance(value, (str, bytes, Mapping)):
        raise ValueError("Expected a finite numeric vector")
    try:
        values = [float(x) for x in value]
    except (TypeError, ValueError) as error:
        raise ValueError("Expected a finite numeric vector") from error
    if (size is not None and len(values) != size) or not values or not all(math.isfinite(x) for x in values):
        raise ValueError("Invalid vector length or non-finite value")
    return values


def _quaternion(value):
    q = _vector(value, 4)
    norm = math.sqrt(sum(x*x for x in q))
    if norm < 1e-12:
        raise ValueError("Zero quaternion")
    return [x/norm for x in q]


def _multiply(a, b):
    w, x, y, z = a
    v, i, j, k = b
    return [w*v-x*i-y*j-z*k, w*i+x*v+y*k-z*j,
            w*j-x*k+y*v+z*i, w*k+x*j-y*i+z*v]


def _matrix(q):
    w, x, y, z = q
    return [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
            [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
            [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]


def _apply(matrix, vector):
    return [sum(row[i]*vector[i] for i in range(3)) for row in matrix]


def _command(state, arm, command_state=None):
    explicit = command_state if command_state is not None else state.get("command_state", {})
    if not isinstance(explicit, Mapping):
        raise ValueError("command_state must be a mapping")
    value = explicit.get(arm, explicit.get(f"{arm}_ee_joint_state"))
    # Native adapter audit: ee_joint_state is prev_control normalized command,
    # not a measured aperture. Explicit runner command state takes precedence.
    if value is None:
        value = state.get(f"{arm}_ee_joint_state")
    if isinstance(value, Mapping):
        value = value.get("gripper_command")
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        value = _vector(value, 1)[0]
    value = float(value)
    if not math.isfinite(value) or not 0. <= value <= 1.:
        raise ValueError("Explicit gripper command must be in the native [0,1] range")
    return value


def permitted_state(raw_state, command_state=None):
    """Allowlist robot measurements and explicit commands; discard all other keys.

    Input: native {left/right_ee_pose: [x,y,z,qw,qx,qy,qz],
    left/right_ee_joint_state: [...], left/right_arm_joint_state: [...]}.
    Native ee_joint_state is an adapter-audited prev_control command, not a
    measured aperture. Optional command_state={left:0,right:1} takes precedence
    over its nested counterpart and native prev_control. No camera parameters
    or native outcome flags pass.
    """
    result = {}
    for arm in ARMS:
        pose = _vector(raw_state[f"{arm}_ee_pose"], 7)
        q = _quaternion(pose[3:])
        matrix = _matrix(q)
        offset = _apply(matrix, TCP_OFFSET)
        entry = dict(link6_pose_world_wxyz=pose[:3]+q,
            tcp_position_world_m=[pose[i]+offset[i] for i in range(3)],
            tool_rotation_world_from_local=matrix,
            finger_extension_axis_world=[row[0] for row in matrix],
            jaw_sliding_axis_world=[row[1] for row in matrix])
        for field in ("arm_joint_state",):
            key = f"{arm}_{field}"
            if key in raw_state:
                entry[f"measured_{field}"] = _vector(raw_state[key])
        command = _command(raw_state, arm, command_state)
        if command is not None:
            entry["gripper_command_native"] = command
        entry["gripper_opening_measured"] = None
        result[arm] = entry
    return dict(frame="environment_origin_world", robot=result)


def decode(answers, robot_state, command_state=None):
    """Return (native_action, audit) without mutating inputs or clipping actions.

    Pass explicit native gripper commands via command_state or its robot_state
    key; audited native prev_control ee_joint_state is the fallback. keep
    without either command raises ValueError. Action poses are raw LINK6 flange
    targets, not TCP targets; quaternions are wxyz. The RPC adapter, not this
    function, converts raw targets to the native IK delta frame.
    """
    selected = validate_answers(answers)
    action, audit = {}, {}
    sign = {"negative": -1., "hold": 0., "positive": 1.}
    for arm in ARMS:
        pose = _vector(robot_state[f"{arm}_ee_pose"], 7)
        old_q = _quaternion(pose[3:])
        old_r = _matrix(old_q)
        offset = _apply(old_r, TCP_OFFSET)
        old_tcp = [pose[i]+offset[i] for i in range(3)]
        new_tcp = [old_tcp[i]+TRANSLATION_M*sign[selected[f"{arm}_{axis}"]] for i, axis in enumerate("xyz")]
        new_q = old_q
        rotation = selected[f"{arm}_rotation"]
        if rotation != "hold":
            axis, direction = rotation.split("_")
            angle = ROTATION_RAD*sign[direction]
            increment = [math.cos(angle/2), 0., 0., 0.]
            increment[{"yaw": 3, "pitch": 1, "roll": 2}[axis]] = math.sin(angle/2)
            new_q = _quaternion(_multiply(increment, old_q))
        new_r = _matrix(new_q)
        new_offset = _apply(new_r, TCP_OFFSET)
        command = selected[f"{arm}_gripper"]
        gripper = {"open": 1., "close": 0.}.get(command)
        if gripper is None:
            gripper = _command(robot_state, arm, command_state)
        if gripper is None:
            raise ValueError(f"{arm}: keep requires an explicit previous gripper command")
        action[f"{arm}_ee_pose"] = [new_tcp[i]-new_offset[i] for i in range(3)]+new_q
        action[f"{arm}_ee_joint_state"] = [gripper]
        audit[arm] = dict(pose_frame="raw_link_frame", native_delta_applied=False,
            tcp_before_world_m=old_tcp, tcp_target_world_m=new_tcp,
            rotation_before_world_from_local=old_r, rotation_target_world_from_local=new_r,
            rotation_choice=rotation, gripper_command_native=gripper)
    return action, audit


def motion_feedback(audit, after_raw_state):
    """Compare decoded TCP targets with measured post-execution robot poses.

    These are geometric motion discrepancies, not diagnoses of collision,
    contact, object retention, or native task success. Translation vectors and
    position errors refer to the same fingertip TCP used by decode().
    """
    measured = permitted_state(after_raw_state)["robot"]
    feedback = {}
    for arm in ARMS:
        before = _vector(audit[arm]["tcp_before_world_m"], 3)
        target = _vector(audit[arm]["tcp_target_world_m"], 3)
        after = measured[arm]["tcp_position_world_m"]
        target_rotation = [_vector(row, 3) for row in audit[arm]["rotation_target_world_from_local"]]
        if len(target_rotation) != 3:
            raise ValueError("Expected a 3 by 3 target rotation matrix")
        after_rotation = measured[arm]["tool_rotation_world_from_local"]
        # trace(R_target.T @ R_after) is the Frobenius inner product.
        cosine = (sum(target_rotation[i][j]*after_rotation[i][j]
                      for i in range(3) for j in range(3))-1.)/2.
        feedback[arm] = dict(
            requested_translation_world_m=[target[i]-before[i] for i in range(3)],
            achieved_translation_world_m=[after[i]-before[i] for i in range(3)],
            target_position_error_m=math.sqrt(sum((after[i]-target[i])**2 for i in range(3))),
            target_orientation_error_rad=math.acos(max(-1., min(1., cosine))))
    return feedback
