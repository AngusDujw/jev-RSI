"""Sandbox-side extension. Credentials and model calls remain in the host."""
from hexashell.benches.libero.proxy import Robot as LiberoRobot


class Robot(LiberoRobot):
    def recover(self, methods, *, observe, resolved, context=None, max_attempts=3,
                rule_selector=None):
        """Run bounded method selection locally; see recovery.py for the contract."""
        from hexashell.recovery import recover
        return recover(self, methods, observe=observe, resolved=resolved,
                       context=context, max_attempts=max_attempts, rule_selector=rule_selector)

    def decide(self, question, options, *, context=None):
        """Choose a local branch from host-recorded measurements and action feedback.

        options maps branch names to English descriptions. Include 'unknown' for
        insufficient evidence. context names the goal, target and proposed plans;
        it is program-authored context, not a sensor. The host adds timestamped
        measurements, proprioception and temporal deltas independently. Returns
        a dict with choice, backend, decision_id and evidence_step. This call
        never moves the robot. Execute the selected branch explicitly in code.
        """
        return self._call("decide", (question, options), dict(context=context))

    def evidence(self):
        """Return the same bounded observation evidence used by decide (no images)."""
        return self._call("evidence", (), {})
