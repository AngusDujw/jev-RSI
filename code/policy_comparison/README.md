# Original policy comparison and oversight

The fixed comparison runs `stack_blocks` and `classify_objects`: three ordinary
`gpt-6-luna`/high trials per task through local ChatGPT Pro, then five actual
`/v1/decisions` trials per task. The Decisions comparison retains fourteen axis
questions; the separately authorized seven-choice rotation grasp pilot is a
different experiment. Original image/tool/history differences are recorded in
EXP-2026W42-300. Never replay a completed or interrupted episode.

`recover_comparison.py` selects preserved terminal trials and runs only missing
slots under fresh names. Three workers share one queue; native startup is
serialized, with at most three own simulators, at least 20 GiB available host
RAM before startup and 8 GiB free target-GPU VRAM. A model-policy rejection is a
trial result; an explicitly audited infrastructure interruption is not a model
quality result and blocks the next model phase. An unclassified incomplete
terminal requires review. A pre-existing fresh-name directory is never overwritten.

`supervise_comparison.py` owns the finite batch and storage guard under the local
user service `robodojo-comparison-20261019d.service`, without automatic restart.
Its logs, owner PIDs and minute resource snapshots are in
`code/runs/server02-policy-comparison-20261018/supervision-20261019d/`.
The transport service is `robodojo-comparison-ssh-20261019d.service`, using SSH
keepalives. SSHFS is no longer used by the batch or original-policy tools. The
service explicitly carries over the parent's HTTP(S) proxy variables. Pro
startup preflights use local disk (no inference), with small result receipts
copied to the remote campaign, avoiding duplicate workspace copies over SFTP.
The authorized AgentsDock five-minute monitoring job independently checks live
processes, native progress, errors and resource pressure and handles faults.
Do not infer health solely from `status.json` or automatically resample policy
answers. Stop only campaign-owned processes when the user pauses/cancels.

The local execution directory is
`/home/ykj/project/gpt6/benchmark/gpt_as_policy_robodojo/runs/server02-policy-execution-20261019`.
It is outside the research tree to avoid inherited agent instructions. It must
have at least 8 GiB free before admission. Images and tool scratch files stay
on local disk while needed by the current episode. The supervisor copies text
to server02 once per telemetry cycle, without deletion or binary images. A text
sync failure is logged without terminating the controller. Native terminal JSON
is fetched separately after simulator exit. Remote native artifacts stay under
`/home/user/ykj/project/gpt6/jev-RSI/code/runs/server02-policy-comparison-20261018`,
and remote primary remains untouched. This removes the SSHFS failure dependency;
a prolonged loss of the simulation RPC can still interrupt an episode and must
be audited, never replayed silently.
Original-policy images are temporary same-episode inputs and are deleted only
after both controller and simulator exit; text results remain. No API fallback
is permitted for ordinary Pro Luna. Native source, scores, physics and drivers
are unchanged. The 14:05 network loss ended generation c at native steps
160/162/170 (all incomplete). Premature Decisions setup had zero API calls and
zero policy steps; its orphan was stopped. All those attempts are preserved and
excluded as infrastructure interruptions before fresh generation d.
The host also rebooted at 14:17:38 (previous boot journal ends at 14:06:44).
Transient services and local controllers from c did not survive; do not mistake
their recorded PIDs for live processes or resume their ended native episodes.

Generation d's stack trial 3 received a Pro `serverOverloaded` error before any
model response, tool call or native action. `retry_empty_slot.py` permits exactly
one fresh generation-e replacement after that empty attempt's cleanup, under
`robodojo-comparison-empty-slot-20261019e.service`. It refuses any prior model
answer or started episode. The two generation-d classification slots continue;
never launch another all-slot batch while those controllers are alive. The d
parent retains its infrastructure failure and will stop at its phase barrier.
Once d and e have drained, inspect the six selected Luna slots; if all are valid,
start a new coordinator generation for the ten Decisions slots, reusing the six
finished results. Do not replay any Luna slot or bypass this audit.

Generation d has drained: classification trial 3 reached 1100 native steps,
complete=true, success=false, score=0. Generation e stack stopped at 215 steps
and d classification trial 2 at 566 steps with Pro serverOverloaded; those
incomplete attempts remain preserved. After cleanup and about forty minutes,
`robodojo-comparison-20261019f.service` runs the existing finite supervisor with
`--generation 20261019f`. It reuses four complete Luna results and allocates only
the two infrastructure-interrupted missing slots under fresh names. It does not
resume episodes, change the original policy, or restart automatically on failure.
Logs and owner PIDs are in `supervision-20261019f/`; the same six-slot phase
barrier applies before Decisions. Original runtime manifest hashes were verified.

All six selected Pro Luna/high trials reached native limits (three per task):
stack 0/3 and classification 0/3 successes. The last f classification ended at
1100 steps with controller exit 0. The same f coordinator passed its phase
barrier and began the fixed ten Decisions slots. Early setup is not evidence of
an API response; verify run identity, actual responses and native controls.
The six-slot terminal audit is `luna-six-slot-terminal-audit.json`.

HTTP 413 follow-up: the original 126-image bound does not bound wire size.
Observed successful requests with 96/99/102 images were reconstructed by exact
SHA-matched official PNG data URLs at 28,323,001 / 29,265,489 / 30,205,207 bytes.
Two stack slots stopped at 190/200 native steps and classification trial 1 at
185 with HTTP 413, without a decision answer for the failed request. The exact
service byte limit is unverified. Preserve these incomplete episodes.

`decisions_wire_budget.py` and `decisions_comparison_wire_completion.py` are
offline-validated future-slot candidates, NOT wired into generation f. They
cap the exact original JSON serialization at 24 MiB and 126 images, removing
only oldest complete camera triplets while keeping all text, latest three
images and original image pixels. This changes the available historical image
window and must be disclosed in the comparison. Oversized text/latest images
raise without sending a request. Size receipts survive HTTP failure. Do not
hot-swap running sources or retry failed requests. After f has drained, select
valid slots, adapt only future dispatch and use independent fresh names for
audited infrastructure-interrupted missing slots; never rerun policy failures.
