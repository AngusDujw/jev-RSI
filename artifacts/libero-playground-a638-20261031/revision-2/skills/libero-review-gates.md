---
name: libero-review-gates
description: Use typed, scoped evidence gates without converting missing temporal comparison into observed change or obstruction.
---

# Typed and scoped review gates

**Status:** verified for the repeated failure pattern: two gates blocked despite affirmative scoped route/pad findings because unavailable temporal evidence or field interpretation was mishandled. The schema recommendations are safeguards, not an isolated success experiment.

**Applicability:** Programs consuming visual review fields, especially initial entry, same-frame recovery and partial approvals.

**Inputs and frames/units:** Exact review schema and returned fields; review status; frame/camera IDs; scoped action description; current robot state and acknowledgement history; identity and temporal-comparison provenance. Boolean and enum types are not interchangeable. Any metric fields retain explicit world-meter/radian units.

**Jev versus program:** Review supplies visible identities and relations. Program validates schema, separates evidence predicates and authorizes only the supported scope. Jev receives the resulting bounded request, not ambiguous review text to reinterpret.

## Design rules
1. Separate current identity/support, temporal change, route clearance, contact feasibility and effect completion.
2. Prefer explicit enums: yes/no/unknown for a relation; clear/blocked/unknown for a route; unchanged/changed/unknown for temporal comparison.
3. Test exact values. Do not use truthiness of strings, compare a boolean with a string, or read a similarly named field. Missing fields are unavailable evidence, not implicit approval.
4. A single initial view cannot independently establish temporal stationarity. If no prior comparison exists, create a current baseline instead of repeating the same impossible temporal question.
5. Unknown temporal change is neither observed change nor proof of stationarity. It need not negate separately affirmative current identity/support and a scoped noncontact observation route.
6. Same-frame reuse requires reconciled actual state and applicable dependencies. Unchanged robot counters alone do not prove that external objects could not move.
7. After relevant motion, obtain fresh comparisons and contact checks. Initial route clearance never licenses unreviewed contact.
8. If a returned blocking reason conflicts with the actual fields, inspect the gate and provenance before requesting another review. Preserve the rejected physical candidate while repairing the software interpretation.

Useful decision separation:
- Affirmative physical contradiction: needs_replan.
- Missing evidence necessary for this segment: blocked.
- Positive evidence for this segment only: eligible for its numerical checks.
- Review stop: abort.

**Failure/stopping conditions:** Stop on malformed schema, ambiguous field meaning, stale dependencies or unresolved required evidence. Do not repair a gate by treating unknown as yes. A genuine contradiction cannot be bypassed using a more favorable summary.

**Evidence IDs:** N-J1, N-J3, N-G acquire.supplement, N-M02, N-M04, N-PLAN. Both erroneous gates stopped without the disputed next movement. Subsequent continuation supports the usefulness of reconciliation, but does not isolate the effect of any one gate implementation.
