# LIBERO motion definitions and six independent demonstrations

Date: 2026-10-17. This is a deterministic control audit, not a model evaluation.
The motion prompt is a draft for user review; it has not been injected into a
Decision request. No task-success claim is made.

## Verified interface

The installed robosuite version is 1.4.0 with MuJoCo 2.3.7. Its
`controllers/osc.py:set_goal` scales a normalized action into position and
axis-angle increments. `utils/control_utils.py:set_goal_orientation` computes
`R_goal = Exp(delta_world) @ R_current`: rotation increments use world axes.
The native six pose channels are `[dx, dy, dz, rx, ry, rz]`. The output scales
are 0.05 metres and 0.5 radians per normalized unit. The controller runs at20Hz.
The general axis-angle description is also documented in the official
[robosuite controller documentation](https://robosuite.ai/docs/modules/controllers.html);
the installed 1.4 source, rather than newer controller defaults, defines this run.

There are no native YPR fields. This draft explicitly names `rz` yaw, `ry`
pitch, and `rx` roll. The user's example names pitch X and roll Y; these aliases
are intentionally different and must not be silently interchanged. Multiple
native rotation channels form one rotation vector, not a sequential Euler order.
No benchmark action convention or frozen policy has been changed.

The measured robot base is at `[-0.66, 0, 0.912]` with identity rotation.
Facing the table along+X from behind this base gives forward+X, left+Y, up+Z.
This is a viewing convention, not an assertion about pixel directions.

`robots/single_arm.py` controls and reports position at `gripper0_grip_site`.
The native gripper is PandaGripper. At the demonstrated open pose, the midpoint
of the two own-robot pad-geometry centres is 3.600mm from this site. Therefore
the prompt does not call the site the exact physical pad midpoint.
The observable `robot0_eef_quat` reads the robot end-effector **body** rotation;
the OSC controller reads the **site** rotation. They differ by approximately
90 degrees in this setup. Demonstration rotations are measured at the controlled
site, not by pretending this body quaternion is the site's absolute orientation.
A fixed body/site offset cancels in a relative world rotation `R_end @ R_start.T`.

## Demonstrations

Same LIBERO-Plus Goal1144/init7, seed0, ordinary reset and ten neutral warmup
steps before each of six independent trials. All six starting positions and
orientations match exactly. No cumulative motion between trials.

Start grip_site: `[-0.216729645, -0.009499641, 1.159407823]` metres.
Each trial follows a smooth two-second target ramp and two-second convergence
period. Robot-only feedback holds the other pose channels. It limits each native
update to10mm and0.10rad; a30-degree demonstration is not one clipped action.
The gripper stays open. No model, depth image, object pose, contact, reward or
success value is used by the demonstration controller.

| Video time | Independent target | Measured primary component | Endpoint position error | Endpoint orientation error |
|---|---|---:|---:|---:|
| 00-06s | +X50mm | +50.105mm | 0.285mm | 0.083deg |
| 06-12s | +Y50mm | +49.650mm | 0.738mm | 0.132deg |
| 12-18s | +Z50mm | +49.720mm | 0.301mm | 0.073deg |
| 18-24s | +yaw30deg = +Rz | +29.921deg | 0.594mm | 0.134deg |
| 24-30s | +pitch30deg = +Ry | +30.063deg | 0.327mm | 0.086deg |
| 30-36s | +roll30deg = +Rx | +29.970deg | 0.409mm | 0.058deg |

Maximum position drift anywhere during yaw/pitch/roll is0.913/5.118/1.785mm.
The pitch transient remains visible and recorded; endpoint accuracy does not
mean a perfectly fixed physical pivot throughout the trajectory.

The36-second H264 video has both camera views at1024x700/20fps, including one
second of repeated start/end frames for readability per trial. All80 native
steps per trial are shown; there is no frame interpolation. Red/green/blue
overlays mark positive worldX/Y/Z at the controlled site. The ring marks the
site. They are diagnostic overlays, not images already sent to a model.

## Files and checks

Server: company-server-2, physicalGPU4 only. Existing environment unchanged.
Assets: `code/runs/2026-10-17-libero-six-axis-motion-v2/` in the project worktree.
Six subdirectories contain raw RGB for81 consecutive states, robot/action
traces, metrics, start/end previews and individual MP4s. Top-level files include
the combined video, `setup.json`, `metrics.json`, and `audit.json`. Local copies
contain the combined video, setup/metrics/audit and selected previews only.
Total server assets203MiB; combined video2.05MB. SHA256 source/video checks and
full FFmpeg video decoding passed. Every endpoint is within1mm and0.2degrees.

The initial v1 launch failed before environment creation because the EGL index
was not the physical GPU index expected by this installed robosuite binding.
v1 remains preserved. v2 uses physicalGPU4, without changing any driver.

Prompt: [libero_robot_actions_v1.txt](libero_robot_actions_v1.txt).
Runner: [libero_motion_demo.py](libero_motion_demo.py).
After user review, the intended follow-up preserves the previous stages,
processing, seeds and budgets while testing the clarified motion explanation:
full structured text plus RGB, followed by the previously defined processed
input reductions. No dependent multimodal trial has started in this audit.
