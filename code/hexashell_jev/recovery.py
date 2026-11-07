"""Bounded, sandbox-local method dispatch. No model credentials or motion policy."""
import re
import uuid


def recover(robot, methods, *, observe, resolved, context=None, max_attempts=3,
            rule_selector=None):
    """Select and execute registered methods without a planner turn between them.

    Each method has description, eligible(obs), run(obs), and optional max_uses.
    observe() refreshes public measurements and returns policy-local observations.
    resolved(obs) means this recovery goal is met, NEVER native task success.
    Predicates must be pure booleans. Exceptions, including EpisodeOver, propagate;
    a partly executed physical method is never automatically replayed.
    rule_selector(evidence, options, context) is an explicit offline-rule control.
    """
    if type(max_attempts) is not int or not 1 <= max_attempts <= 6:
        raise ValueError("max_attempts must be 1..6")
    if not isinstance(methods, dict) or not 2 <= len(methods) <= 10:
        raise ValueError("Register 2..10 alternative recovery methods")
    if not callable(observe) or not callable(resolved):
        raise ValueError("observe and resolved must be callable")
    if rule_selector is not None and not callable(rule_selector):
        raise ValueError("rule_selector must be callable")
    registry = {}
    for name, method in methods.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", name) or name == "unknown":
            raise ValueError("Invalid method name")
        desc = method.get("description")
        uses = method.get("max_uses", 1)
        if not isinstance(desc, str) or not desc.isascii() or not 1 <= len(desc) <= 800:
            raise ValueError("Methods require English descriptions of 1..800 characters")
        if type(uses) is not int or not 1 <= uses <= 3:
            raise ValueError("max_uses must be 1..3")
        if not callable(method.get("eligible")) or not callable(method.get("run")):
            raise ValueError("Each method requires eligible and run callables")
        registry[name] = dict(method, max_uses=uses)

    ident, history = uuid.uuid4().hex, []
    counts = dict.fromkeys(registry, 0)

    def emit(event, **data):
        robot._call("recovery_event", (dict(recovery_id=ident, event=event, **data),), {})

    def boolean(value):
        if type(value) is not bool:
            raise ValueError("Recovery predicates must return Python bool")
        return value

    def finish(reason):
        emit("finish", reason=reason, attempts=len(history))
        return dict(reason=reason, resolved=reason == "resolved", history=history)

    emit("start", methods={k: dict(description=v["description"], max_uses=v["max_uses"])
                           for k, v in registry.items()}, max_attempts=max_attempts,
         selector="rules" if rule_selector else "configured_model")
    obs = observe()
    for attempt in range(max_attempts):
        if boolean(resolved(obs)):
            return finish("resolved")
        options = {k: v["description"] for k, v in registry.items()
                   if counts[k] < v["max_uses"] and boolean(v["eligible"](obs))}
        if not options:
            return finish("no_eligible_method")
        options["unknown"] = "No available method is supported; return to GPT without motion."
        packet = dict(policy_context=context, recovery_id=ident, attempt=attempt,
                      method_history=history, uses=counts.copy(),
                      scope="Choose a useful available recovery or observation method; no diagnosis is assumed.")
        if rule_selector is None:
            receipt = robot.decide(
                "Which available method best addresses the current execution difficulty, "
                "given measured history and previous attempts? Choose unknown if none is supported.",
                options, context=packet)
            choice = receipt["choice"]
        else:
            choice = rule_selector(robot.evidence(), dict(options), packet)
            receipt = dict(choice=choice, backend="rules")
        if choice not in options:
            raise ValueError("Selector returned an unavailable method")
        emit("selected", attempt=attempt, options=options, receipt=receipt)
        if choice == "unknown":
            return finish("unknown")
        # Recheck immediately before invoking a method. Guards remain authoritative.
        if not boolean(registry[choice]["eligible"](obs)):
            return finish("guard_changed")
        counts[choice] += 1
        emit("dispatch", attempt=attempt, method=choice)
        registry[choice]["run"](obs)
        # If run raises, no retry, completion event, or further robot call occurs.
        obs = observe()
        row = dict(attempt=attempt, method=choice, uses=counts[choice])
        history.append(row)
        emit("observed", **row)
    return finish("resolved" if boolean(resolved(obs)) else "attempt_budget")
