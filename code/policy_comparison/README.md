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
quality result. A pre-existing fresh-name directory is never overwritten.

`supervise_comparison.py` owns the finite batch and storage guard under the local
user service `robodojo-comparison-20261019.service`, without automatic restart.
Its logs, owner PIDs and minute resource snapshots are in
`code/runs/server02-policy-comparison-20261018/supervision-20261019b/`.
Transport services are `robodojo-comparison-ssh-20261019.service` and
`robodojo-comparison-mount-20261019.service`; both use SSH keepalives. The
authorized AgentsDock five-minute monitoring job independently checks live
processes, native progress, errors and resource pressure and handles faults.
Do not infer health solely from `status.json` or automatically resample policy
answers. Stop only campaign-owned processes when the user pauses/cancels.

Artifacts remain on server02 under
`/home/user/ykj/project/gpt6/jev-RSI/code/runs/server02-policy-comparison-20261018`,
mounted locally outside the research tree to avoid inherited agent instructions.
Original-policy images are temporary same-episode inputs and are deleted only
after both controller and simulator exit; text results remain. No API fallback
is permitted for ordinary Pro Luna. Native source, scores, physics and drivers
are unchanged.
