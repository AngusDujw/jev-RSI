---
name: libero-bounded-checkpoints
description: Persist bounded intent, evidence and predicate outcomes with verified writes and separate field provenance.
---

# Bounded persistence

For every finding, **inputs/frames** are documented byte/key limits and serializer capabilities, checkpoint manifest, finite world-meter/radian measurements with camera/frame/source metadata, bounded errors, actual states and acknowledgements. Bytes, characters, keys and calls differ. **Responsibilities:** program owns serialization/storage and reconciliation; reviewer supplies scoped evidence; Jev has no storage-repair role.

## A. Raw review payloads can exceed limits

**Status:** verified for two N oversized writes; compact persistence supported one continuation, not final containment repair.
**Applicability:** Payload/key-limited checkpoints.

Whitelist necessary points, physical descriptions/IDs, numerical references, errors and quality statistics. Bound every nested list/string; exclude clouds/full tracker arrays while retaining a support-checked correspondence subset. Preserve intent, whole-action endpoints, command, acknowledgement and pending effect without reducing precision merely to fit.

Budget keys as well as bytes. Reuse slots only with explicit schema/stage ownership and preserved references. Size using supported serialization, inspect acknowledgements/readback provenance, and do not assume a failed write replaced its predecessor. Bound handoffs/progress too. A new write can contain old geometry/results.

N twice exceeded a historical 16384-byte limit; the first compact repair reached descent, the later write left old review provenance. Limits are not defaults for a fresh runtime.
**Stop:** no dependent motion without durable required intent. After failure reconcile actual state and old/new records; do not replay work or label storage failure a failed grasp.
**Evidence IDs:** N-J4, N-J5, N-J9, N-C, N-P, N-M05, N-M06, N-RT.

## B. Validate the preflight mechanism

**Status:** scene-specific codec failure; replacement serialization policy is a hypothesis.
**Applicability:** Restricted runtimes.

N's final recursive size bound failed on unicode_escape before baseline resampling or proposed rise/rotation. Use documented serializer/byte-count primitives. If unavailable, test a conservative bounded ASCII schema against the actual serialization contract. Include escaping/numeric representation, reject non-finite/unsupported values, and maintain a smaller failure-record path without the failing dependency.
**Stop:** unsupported encoding, uncertain bound, failed write/readback or stale provenance blocks continuation. Prose intent and empty motion records do not establish a prefix.
**Evidence IDs:** N-M10 full source, N-J10, N-RT gpt-38, N-C. No successful post-codec repair supplied.

## C. Preserve exact predicates before short-circuit return

**Status:** scene-specific diagnostic/persistence gaps; factored durable outcome records are a proposed safeguard.
**Applicability:** Compound gates and exceptions after acknowledged motion.
**Additional inputs:** each predicate's availability/value, quantity, threshold, uncertainty, scope and source frame.

Record passed, failed and unavailable predicates independently. T's first closing failure archived pre-close geometry but lacked post-close subpredicates. Passing pose drift could not clear that failure; later geometry cannot reconstruct its exact historical cause.

T saved lift endpoints, then received disturbance/invalid-depth findings and returned without saving that second review. Final-frame checkpoints still held baseline-only evidence and one review count. Returned/journal evidence is newer than those fields; a fresh write frame does not imply a fresh effect. Full source stopped before numerical attachment and fit processing.

Persist bounded independent facts before throwing, while withholding dependent motion. Preserve material descriptions, not just labels. These are recommended repairs, not observed repaired executions.
**Stop:** missing subpredicates blocks causal diagnosis; missing critical persistence blocks dependent continuation. Do not infer absent comparisons/fits from key names or overwrite contrary evidence with a favorable summary.
**Evidence IDs:** T-J3, T-J4, T-C, T-M08, T-J8, T-A, T-CP, T-RBASE, T-RLIFT.
