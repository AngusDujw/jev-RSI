# SSH path comparison: v4090 and 5880-jump, 2026-10-19

## Measured isolation

Both aliases connect through 8.162.4.36:22 as ykj. v4090 forwards to the
jump host's localhost:10060; 5880-jump forwards to localhost:10022.
The v4090 alias spells its ProxyJump destination directly; 5880 uses ali-jump.
The latter has a keepalive setting, which does not explain the initial
handshake comparison below. No global SSH configuration was changed.

Parallel fresh-login probes:
- Shared jump-host public-key authentication: approximately 1.07 / 1.16 seconds.
- 5880-jump completed printf SSH_OK in 3.065 seconds.
- v4090 had not completed authentication at the 22-second probe deadline.
  Its target banner appeared at 4.609 seconds; later authentication progress
  did not appear until 18.728 seconds. The owned probe group was terminated.

From inside ali-jump, TCP connect to both listening ports was immediate:
- 10022 SSH banner: 0.063 / 0.095 / 0.128 seconds.
- 10060: three successive six-second banner timeouts.
Thus the common local-to-jump leg does not explain the observed difference.
The slow segment is the v4090 reverse-forward path or its target SSH endpoint.

## Intervention confined to this experiment

The experiment's dedicated local bridge process group was temporarily paused.
Only 22 SSH processes in that exact owned process group were closed. No other
chat's processes, SSH services, reverse-tunnel services or drivers were changed.
The group was resumed in a finally block.

While its connections were cleared:
- 10022 banner: 0.061 / 0.105 / 0.126 seconds.
- 10060 banner: 2.563 / 0.111 / 0.114 seconds.

This supports an interaction with our connection pressure / accumulated
connection state. It does not isolate session count, stale connection state,
bulk-data load and incidental underlying link variation from one another.

## Host and network checks

A subsequent v4090 login completed in 24.866 seconds. The target had load
0.69 / 0.40 / 0.37, about 69 GB available RAM and 97-98% CPU idle, with no
observed swap-in/out or I/O wait in the two vmstat samples.
This does not support host CPU/RAM saturation as the observed slow-login cause.

v4090's existing outbound SSH tunnel to the jump host was visible as pid1836591.
Its TCP state showed RTT about 37-42ms, cumulative bytes_retrans106055160 and
retrans0/75857. Those retransmission totals did not increase across the two
samples. Its NIC reported cumulative RX drops4862006 after75 days uptime.
These are historical counters, not proof of current packet loss. No tunnel
restart was attempted.

## Application repair and checks

The broker previously allowed12 API workers plus polling to independently
perform SSH operations, each with fresh-connection fallback on failure.
API inference concurrency and file-transfer concurrency are now separated:
- API workers remain12.
- At most3 SSH file/control operations can execute simultaneously.
- Each outer SSH operation starts its own process group.
- A timeout or interrupt kills and drains that owned group, including its
  ProxyJump child, instead of only terminating the outer process.
- One-second pacing precedes the independent-connection fallback.

The old broker child received SIGINT and drained its work; the existing managed
parent restarted it with --resume and the repaired module. Persisted replies
remain reused; native loops were not reset or replaced.

Checks:12 concurrent callers reached peak3 SSH operations; a real injected
timeout killed both the owned parent and its child process. Temporary fixture
files were deleted. Checks used no model calls or simulator steps.

After limiting/draining, the next paired host checks completed in4.34 seconds
(v4090) and4.39 seconds (5880), both including a fixed2-second sampling sleep.
Persisted valid answers progressed from94 to101 during the live continuation.
The last native status read found9 active /14 finished, evaluated0/success0.

## Conclusion boundary

The shared jump host was fast in this comparison. The v4090 forwarding path
became unresponsive under this experiment's connection workload and improved
after its connections were cleared and concurrency limited. This is stronger
evidence than labeling every failure an API-network problem.
The short improvement is not a long-duration reliability guarantee.
System SSH/reverse-tunnel limits were not inspected with elevated privileges;
a read-only sudo -n request required authentication and was not pursued.
