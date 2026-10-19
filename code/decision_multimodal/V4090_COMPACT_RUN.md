# v4090 compact visual-control campaign, 2026-10-19

## Scope and immutable evaluation records

Native LIBERO-plus task 1383 (stove knob) and 1458 (wine bottle onto rack).
The actor chooses each world translation / rotation-vector component from
positive, negative, hold, plus gripper and stage transition. No target pose,
axis residual, selected grasp pose or evaluator label enters the actor.
Current RGB, current visible surface samples, own measured hand geometry,
axis arrows and fixed actual motion examples remain available. This is not
a pure RGB experiment. Plans are previously saved local Pro outputs.
Experience is collected by the experiment agent, not injected in this batch.

24 distinct cases: two tasks, three fixed initial states per task, four input
variants (`all_examples`, `task_only`, `motion_only`, `task_native_frame`).
The last variant uses task examples and native coordinates instead of the
constant translated coordinate display. Do not pool variants as repetitions
of one policy or call startup / stage completion a native task success.
Normal failures remain in place; infrastructure errors are reported separately.

## Deployment

Host: `v4090`. Code worktree:
`/home/v4090-1/ykj/project/jev-RSI-libero-decision-20261019`.
All environment copies, assets, plans, campaign outputs and bundles:
`/home/v4090-1/DataStorage/gpt6-dec/libero-decision-20261019`.
The existing RoboDojo worktree is not modified.

Runtime copies the already installed `.venv-libero-plus` and LIBERO-plus source
from the authorized previous server, excluding unrelated new_objects assets
and Python caches. Python is 3.10.12 on both hosts. ImageMagick dependencies
are official Ubuntu Jammy `.deb` packages extracted under `runtime-libs`, not
installed into system Python / base. These packages are libmagickwand-6.q16-6,
libmagickcore-6.q16-6, liblqr-1-0 and libfftw3-double3. Own relative library
symlinks expose MagickWand / MagickCore under `runtime-libs/usr/lib` for Wand;
per-process MAGICK_HOME and LD_LIBRARY_PATH select this copy. No driver changes.

## Runtime and review

Both native scheduler and local broker run in independent tmux sessions named
`dm-v4090-20261019`; these are separate machines' sessions. Do not restart the
same campaign over existing outputs. Scheduler reads `campaign/concurrency.json`
every cycle; it also checks free GPU memory, available RAM and disk space.
Initial cap is two, then increased only after real observations and responses.
Local broker has 12 independent API workers and persists answers before delivery.
The remote needs no API key. Only the locally authorized du `/v1/decisions`
endpoint is callable. A persisted answer is reused after SSH delivery errors.
A valid refusal / normal failed trial is not resampled.

No rollout PNG, video, base64 request archive or duplicated demonstration image
is retained. Fixed functional examples share 18 PNG files (about 4.5 MB) once.
Transient SSH spool `pending.json` holds the live request and is removed after
reply or timeout. Small request hashes / image hashes, model answers, chosen
and measured commands, native terminal status and process status are retained.
Native `success`, `native_evaluated`, and `program_finished` are distinct fields.

Inspect remote `campaign/status.json`, `campaign/runs/*/result.json`,
`campaign/runs/*/execution.jsonl`, and local
`code/runs/2026-10-19-v4090-preparation/bridge/heartbeat.json`.
Pending files correspond to current outstanding calls, not retained image logs.
The old company-server-2 native and matching local bridge sessions were stopped
at the user's migration request; no GPU experiments continue there for this chat.

First resource gate: both native cases returned four real answers and executed
22/26 steps, with zero saved rollout PNG. RSS was about 1.2 GiB per process.
Cap increased to 24 after this check. All 24 processes were then alive, queue
empty; total GPU memory was 22160 MiB including pre-existing other-user usage,
with 26349 MiB free and about 54 GiB available RAM. No completed new terminal
evaluation was available at this checkpoint.


## Infrastructure continuation, EXP-2026W43-010

The original batch ended at 14:05 with 23 infrastructure interruptions and
one evaluated normal failure. Continue only the 23 interrupted cases in a new
campaign-retry1 folder; each case records retry_of. Keep the normal failure.
Scheduling now rotates by the episode's last service time instead of fixed
root order. Network errors with no received response and HTTP 429/502/503/504
allow at most three attempts, each audited. A received answer or refusal is
never resampled; no exactly-once server computation guarantee is claimed for
a connection lost after sending. Persisted replies remain authoritative for
delivery recovery. Native spool waiting is 1800 seconds. Startup still checks
two actual native/Decisions streams before raising concurrency. New tmux
control sockets are explicit project/DataStorage files, not default /tmp paths.
