---
name: libero-bounded-checkpoints
description: Persist bounded evidence records with explicit provenance and verified writes in constrained runtimes.
---

# Bounded evidence persistence

## A. Raw reviews can exceed the storage contract

**Status:** verified for the repeated hazard: two review-checkpoint writes exceeded the runtime payload limit. Bounded persistence supported one subsequent continuation, not the final containment repair.

**Applicability:** Runtime checkpoint/RPC APIs with per-value byte limits and a finite key count.

**Inputs and frames/units:** Documented byte/key limits, checkpoint manifest, returned review fields, finite world-meter samples, camera/frame metadata, errors, actual motion states and acknowledgement receipts. Bytes, characters, keys and calls are distinct quantities.

**Jev versus program:** Program owns schema, storage and acknowledgement checks. Reviewer supplies bounded requested evidence. Jev controls physical actions only; storage failure is not a negative geometric observation.

## Design
- Request only evidence needed by the next gate. A point request can still accompany large region/cloud outputs; do not persist the complete response by default.
- Whitelist named points, physical IDs, frame/camera/pixel/source metadata, bounded schema parameters, short errors and compact outcome summaries.
- Bound every nested list and string. Exclude raw clouds and full tracker receipts; retain quality statistics and a bounded, support-checked correspondence subset where needed.
- Keep essential intent, actual before/after poses, command, acknowledgement, pending effect and original measurement provenance. Do not reduce numerical precision merely to save space.
- Budget key count as well as payload size. Reuse slots only with explicit stage/schema ownership and preserved critical references; a key's old name is not its current meaning.
- Size records using supported serialization behavior, then inspect write acknowledgement and returned provenance. Do not assume a failed write replaced its predecessor.
- Track write provenance separately from field provenance: a newly written record can still contain an older outcome or copied geometry.
- Validate compact progress/handoff size too; duplicated full states and review prose can recreate the problem.

Episode 1 hit a 16384-byte value limit after the offset and again during containment planning. The first compact-record revision reached descent; the later failed write left older review provenance in place. These limits are historical observations, not defaults for a new runtime.

**Failure/stopping conditions:** Stop before motion if intent cannot be durably recorded. After failure, reconcile actual state and old/new checkpoint provenance; do not replay physical work or label the error as grasp/placement failure.

**Evidence IDs:** N-J4, N-J5, N-J9, N-C, N-P, N-M05, N-M06, N-RT.

## B. Validate the size-checking mechanism itself

**Status:** scene-specific failure; the replacement serialization/preflight procedure remains a hypothesis.

**Applicability:** Restricted Python or other sandbox runtimes where familiar codecs, imports or language features may be unavailable.

**Inputs and frames/units:** Documented runtime capabilities, bounded ASCII schema, finite numeric representations, payload limits and acknowledged read/write results. Preserve measurement units inside the schema.

**Jev versus program:** Program tests persistence compatibility before physical work. Jev has no role until a valid execution record and approved segment exist.

The final recovery used an encoding-dependent recursive size bound. The runtime rejected unicode_escape before baseline resampling or the proposed rise/rotation. The recovery's prose described intended work, not completed work.

For fresh synthesis:
1. Use only documented supported primitives; do not copy the failed codec dependency.
2. Prefer a documented serializer/byte-count facility. If unavailable, design a conservatively bounded ASCII-only schema and test its bound against the actual supported serialization contract.
3. Reject non-finite values and unsupported types. Bound escaping and numeric representation, not just raw string character count.
4. Preflight compact persistence and verify acknowledgement before committing to physical work. Do not sacrifice identity, errors or provenance to make a record fit.
5. Keep a smaller failure record whose own persistence path does not repeat the failing dependency.

**Failure/stopping conditions:** Unsupported encoding, uncertain byte bound, failed write/readback or stale provenance blocks continuation. Empty motion records and unchanged actual state do not support a claimed prefix effect.

**Evidence IDs:** N-M10 full source, N-J10, N-RT gpt-38, N-C. No successful post-codec repair is supplied.
