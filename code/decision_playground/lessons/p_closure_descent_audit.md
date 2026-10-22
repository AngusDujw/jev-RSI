# p closure/descent audit (outer agent only)

Status: execution diagnosis and command-semantics repair, not a promoted Skill.
Do not load this audit into the model. Zero new API or native calls were made.
All source p requests, images, and outcomes remain unchanged.

## First renewed tracking mismatch

The raw head and right-wrist images at steps20,25,29 were reviewed. Fingers close
near the shovel blade; occlusion and image overlap do not establish enclosure,
attachment, or retention. There is no verified lift or stable transport.

| Native step | Right joint2 measured (rad) | IK/runtime joint2 target (rad) | Dispatched TCP position error (mm) |
| --- | --- | --- | --- |
| 20, open hold | -0.217127 | -0.217127 | 0.0677 |
| 25, close hold | -0.217127 | -0.217127 | 0.0670 |
| 26, first descent substep | -0.230684 | -0.242945 | 1.3897 |
| 27 | -0.230608 | -0.270536 | 7.1854 |
| 28 | -0.230583 | -0.300144 | 13.3279 |
| 29 | -0.230593 | -0.332052 | 11.3440 |

The closure phase itself was position-stable. Renewed descent mismatched from
its first substep, then joint2 plateaued while other joints moved. Accepted
current-to-target increments were at most0.101469rad in this segment, below
the original0.15rad guard. Runtime targets equal the accepted IK targets; this
is not evidence of clipping a target to the measured plateau. The fifth solve
failed before dispatch; its repeated step29 snapshot is excluded from actual
step counts. No contact-report stream exists in p. A recurring plateau is not
proof of the same contact pair, a unique physical cause, or a successful grasp.

## Independently verified keep-command mismatch

The source native gripper mapping is q_target=-0.010+0.054*c, in metres. Its
low-level control limits each frame's movement relative to the measured finger
joint to0.2*0.054=0.0108m. prev_control therefore stores the rate-limited target,
not necessarily the selected final goal. Observations invert that mapping.

In p, answer4 selected close, sending c=0. After five dispatched steps the
observation reported c=0.04503823007560438. Answer5 selected keep; the old worker
then sent that low-level value instead of retaining the selected goal0. This
is a command-semantics discrepancy, not a measurement of aperture. It does not
establish that this discrepancy caused the arm's descent overshoot.

Repair condition selected-gripper-command-v1 retains an explicit per-arm goal
ledger. Bootstrap/reset uses the audited initial control target. After a native
response, positive actual dispatch count commits the selected final gripper
goal; zero dispatch preserves the old goal. A mismatched counter or unknown
RPC result stops without guessing or replay. decode and model robot state use
this ledger explicitly. Raw low-level targets never overwrite it. Actual
opening remains null; no physical aperture or capture claim is fabricated.

## Public robot geometry

URDF joint7 origin[0.08657,0.024896,-0.0002436]m and axis+Y; joint8 origin
[0.08657,-0.0249,-0.00024366]m and effective axis-Y. Both prismatic limits are
[0,0.044]m. USD local rotations agree. Public finger meshes extend to
Link6 localX=0.157570m. The configured TCP at0.150070m is7.500mm behind that
extreme. LocalX extension and localY opening axes are supported, but this
reference point is not a validated object contact centre. The separate0.145m
robot bias is not substituted for this offset. No asset or physics changed.

## Validation and limits

Pure prefix0..5, varying low-level feedback, invalid counts, immutability,
zero-dispatch refusal and reset checks passed. An actual worker.main loop with
in-memory native/request substitutes verified close/keep/refusal/reset over six
fake requests. Independent review also passed. No network/model/native calls;
test fixture removed. Real repaired command semantics have not yet been tested.
The next minimal test is one new zero-API initial-pose close/keep probe, holding
arm poses fixed and comparing the selected-goal ledger, actual sent commands,
and normalized low-level observations. Do not resume p or infer a grasp benefit.

## Sources

- Remote p/closure-descent-trajectory-audit.json, native/ik.jsonl, native/steps.jsonl.
- Remote p worker interactions and retained original images20/25/29.
- Baseline third_party/RoboDojo/env/robot_manager/control_manager.py:22,81,127.
- Baseline third_party/RoboDojo/env/observation_manager/obs_manager.py:185.
- Baseline third_party/RoboDojo/env/robot_manager/robot_manager.py:204.
- Baseline third_party/RoboDojo/src/eval_client/eval_env.py:453.
- Public data/Assets/Robots/x5/X5A.urdf:252,281 and robot_config.yml:10.
- Local selected-gripper-goal-offline-validation.json.

## q probe validation status

The single real probe stopped at step0 before dispatch because its checker
compared a raw measurement quaternion with decode's normalized quaternion by
exact component equality. No motion or API call occurred. This is a checker
error, not a negative grasp result or evidence against the command repair.
A canonical first-decoded-hold reference passed1212 offline phase cases and
still rejects an intentional1mm target change. A new real probe remains
unauthorized pending the user's explicit exception to the one-probe limit.
