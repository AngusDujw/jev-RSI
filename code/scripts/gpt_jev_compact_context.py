"""Bound planner context by role; raw records remain outside model requests."""
import ast
import hashlib
import json


def size(value):
    return len(json.dumps(value, ensure_ascii=True, separators=(",", ":")))


def bounded(value, limit):
    """Explicitly label omitted data; never silently present excerpts as complete."""
    if size(value) <= limit:
        return value
    def shrink(item, width, depth=0):
        if isinstance(item, str):
            return item if len(item) <= width else item[:width]+" [excerpt; remainder omitted]"
        if isinstance(item, dict):
            if depth >= 7:
                return {"omitted": "nested diagnostic", "original_chars": size(item)}
            return {k: shrink(v, width, depth+1) for k, v in item.items()}
        if isinstance(item, list):
            selected = item if len(item) <= 6 else item[:3]+item[-3:]
            result = [shrink(v, width, depth+1) for v in selected]
            return result if len(item) <= 6 else {"excerpt_items": result, "original_count": len(item)}
        return item
    for width in (400, 160, 60):
        candidate = {"excerpt": shrink(value, width), "original_chars": size(value),
                     "scope": "Incomplete diagnostic; omitted data is unavailable, not negative evidence."}
        if size(candidate) <= limit:
            return candidate
    return {"excerpt_json": json.dumps(value, ensure_ascii=True)[:max(0, limit//2-200)],
            "original_chars": size(value), "scope": "Truncated diagnostic JSON text, not a complete record."}


def source_excerpt(source, failure, limit=3000):
    """Diagnostic lines only; repair returns a complete new current-stage source."""
    lines = source.splitlines(keepends=True)
    hint = json.dumps(failure, ensure_ascii=True).lower()
    chosen = set(range(min(10, len(lines))))
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name != "main" and node.name.lower() in hint:
                chosen.update(range(node.lineno-1, min(node.end_lineno, node.lineno+12)))
    except SyntaxError:
        pass
    for i, line in enumerate(lines):
        if any(word in line.lower() and word in hint for word in ("gate", "blocked", "failure", "error")):
            chosen.update(range(max(0, i-1), min(len(lines), i+2)))
    chunks, used = [], 0
    for i in sorted(chosen):
        line = lines[i]
        if used+len(line) > limit:
            continue
        chunks.append(dict(line=i+1, text=line))
        used += len(line)
    return dict(source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                total_lines=len(lines), diagnostic_lines=chunks,
                scope="Partial previous source for diagnosis only; not runnable or an exact-patch base.")


def compact_state(state, kind):
    result = {k: state[k] for k in ("instruction", "question", "robot", "cameras") if k in state}
    result["context_scope"] = "Current-stage context only. Raw history is archived; omitted evidence is not established. Checkpoints can be recalled by executable code."
    result["recent_acknowledged_execution"] = [bounded(v, 650) for v in state.get("recent_acknowledged_execution", [])[-2:]]
    result["recent_program_feedback"] = [bounded(v, 650) for v in state.get("recent_program_feedback", [])[-2:]]
    if state.get("active_program_rpc"):
        result["active_program_rpc"] = bounded(state["active_program_rpc"], 2400)
    manifest = state.get("program_checkpoint_manifest", [])
    result["program_checkpoint_manifest"] = bounded(manifest, 1400)
    context = state.get("hierarchical_context", {})
    if context:
        slim = {k: context[k] for k in ("current_stage", "stage_index", "final_stage", "plan_revision",
                    "remaining_stage_updates", "method_revision", "slice_limits", "model_call_budget",
                    "trigger", "live_continuation_available", "no_new_evidence_count", "watchdog_event") if k in context}
        plan = context.get("overall_plan", {})
        slim["overall_plan"] = dict(goal_evidence=bounded(plan.get("goal_evidence"), 600),
            stages=[{k: v[k] for k in ("id", "objective") if k in v} for v in plan.get("stages", [])])
        for key in ("latest_outcome", "stage_outcome", "stage_result", "handoff"):
            if key in context:
                slim[key] = bounded(context[key], 2600)
        decisions = context.get("latest_decision", [])
        slim["latest_decision"] = [bounded(v.get("decision", v), 1800) for v in decisions[-1:]]
        slim["completed_stage_history"] = [bounded(v, 500) for v in context.get("completed_stage_history", [])[-2:]]
        result["hierarchical_context"] = slim
    if "program_supplied_review_context" in state:
        result["program_supplied_review_context"] = bounded(state["program_supplied_review_context"], 5000)
    previous = state.get("previous_method")
    if previous:
        failure = previous.get("incomplete_result", {})
        result["previous_method"] = dict(incomplete_result=bounded(failure, 2200),
            interface=bounded(previous.get("interface"), 700),
            source_excerpt=source_excerpt(previous.get("source", ""), failure))
    # A second envelope bound protects unusual deeply nested stage outcomes.
    if size(result) > 19000:
        for key in ("recent_program_feedback", "recent_acknowledged_execution", "program_supplied_review_context", "hierarchical_context"):
            if key in result:
                result[key] = bounded(result[key], 2500)
    return result
