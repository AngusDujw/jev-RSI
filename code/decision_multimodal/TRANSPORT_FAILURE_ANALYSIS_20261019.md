# Transport failure analysis: EXP-2026W43-010

## Confirmed sequence (Asia/Shanghai, 2026-10-19)

- At 15:06, all 23 native loops were alive and actual commands were being executed.
- Seven API calls exhausted three unanswered transport attempts around 15:20:20–25.
  These calls ran on the LOCAL host through its authorized proxy, not on v4090.
  There were 56 failed API transport attempts in total: 33 TLS EOF, 15 connection
  resets (including two wrapped URLErrors), three RemoteDisconnected, three
  broken pipes and two read timeouts. Earlier attempts often recovered.
- SSH transport events began at 15:24:39.668 and continued through 15:55:28.352:
  306 events, including 35-second read and reply-delivery command timeouts.
- Around 15:25:46–47, two native readers failed parsing their reply.json.
  Both remote files are exactly zero bytes, SHA256
  e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.
- The corresponding locally persisted replies are valid answers:
  knob-all_examples-init10 / request0064: 1995 bytes,
  SHA256 04a7e91abd3eeeb4b05e947bcf1148b91182fed3eb32633d0da89add7a46e8c9.
  knob-motion_only-init8 / request0064: 2003 bytes,
  SHA256 f1ee24ebea8e9ba7a1882b67869d0611270fc80c254fbf0379ccb38f3fe653cc.
- Fourteen other loops eventually exhausted their 1800-second spool wait.
  The last campaign state is 15:55:56, with no active loops.

## Root causes and limits of attribution

1. Local proxy-to-API TLS transport failed. Logs do not identify whether the
   proxy, intervening network or upstream service closed those connections.
   A successful short connectivity check would not explain this historical fault.
2. The SSH data/control path failed separately. The bridge kept retrying through
   one multiplexed connection without an independent fresh-connection fallback.
   The logs establish SSH timeouts, not a proven GPU or simulator crash, and do
   not prove that multiplexing alone caused the link fault.
3. There is a proven application integrity defect: reply delivery read stdin
   and published it without validating length, JSON or an expected content hash.
   Interrupted SSH stdin can produce EOF with empty/truncated bytes. Atomic
   rename protects against partial disk writes, not against publishing empty
   input. The native client immediately parsed that bad file and aborted.
4. Recovery was bounded to three API attempts and 30 minutes of spool waiting.
   The scheduler records a child exit but does not resume that simulator state.
   Thus independent tmux processes do not guarantee continuous experiment work.

These 23 interrupted runs are not 23 completed robot-task failures. Their
native_evaluated fields are all false. No new task success is established.

## Implemented repair, narrowly tested

- Verify SHA256 and JSON-object parsing before publishing a remote reply.
- Require the same hash as an SSH delivery acknowledgement.
- Quarantine invalid local copies and wait for retransmission of the already
  persisted response. Do not resample a model to replace a bad delivered copy.
- Allow pending requests to reappear after a quarantined reply, even after a
  prior delivery acknowledgement.
- Retry failed file operations once using an independent SSH connection,
  bypassing the possibly stuck multiplex master.
- Do not rewrite historical failed reply files or replace experiment outcomes.

Checks passed with zero API calls / zero physics steps: empty/truncated input
cannot replace an existing valid reply; complete input returns its hash ACK;
native reader recovers from a zero-byte copy; a mocked stalled multiplex
connection falls back to a fresh connection. A real v4090 SSH fixture passed
the hash roundtrip and empty-input rejection. Temporary fixtures were removed.

This verifies file-integrity repairs, not full multi-hour network resilience.
API outage pause/resume and continuation of the same native state remain open.
No new native batch was launched during this investigation.

## Evidence locations

Local: code/runs/2026-10-19-v4090-retry1/bridge, including dispatch.json,
reply.json, network-attempts.jsonl and transport-events.jsonl.
Remote: DataStorage/gpt6-dec/libero-decision-20261019/campaign-retry1/runs,
including native traceback logs, result.json and bridge-jobs/0064/reply.json.
Checks: code/runs/2026-10-19-transport-diagnosis/checks.json.
