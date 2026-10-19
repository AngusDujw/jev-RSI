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
