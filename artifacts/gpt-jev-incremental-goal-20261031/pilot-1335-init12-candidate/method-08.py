def main(api):
    state = api.state()
    questions = {}
    for axis in ("x", "y", "z", "rx", "ry", "rz"):
        questions[axis] = {
            "type": "choice",
            "instructions": "For world axis " + axis + ", read state.processed_features.axes." + axis + ".goal_relation. Hold unless state.processed_features.program.action_authorized is true. Otherwise follow decrease, within_tolerance, or increase respectively. Do not infer contact or clearance.",
            "criteria": {"negative": "Authorized decrease of this world coordinate or rotation-vector component.",
                         "hold": "Action not authorized, or this axis is within tolerance.",
                         "positive": "Authorized increase of this world coordinate or rotation-vector component."}}
    questions["gripper"] = {
        "type": "choice",
        "instructions": "Read state.processed_features.objective.gripper and state.processed_features.program.action_authorized. Keep when unauthorized. Otherwise deliver only the explicitly authorized open, close, or keep objective. Closure does not establish retention.",
        "criteria": {"open": "Authorized objective is open.",
                     "close": "Authorized objective is close.",
                     "keep": "Objective is keep, or physical action is unauthorized."}}
    records = {}
    read_errors = []
    for key in ("alt.model", "secure.failure", "alt.progress"):
        try:
            records[key] = api.recall(key)
        except Exception as exc:
            read_errors.append({"key": key, "error": str(exc)})
    model = records.get("alt.model", {}).get("value", {})
    observation = model.get("observation", {})
    params = observation.get("parameters", {})
    points = observation.get("points", {})
    errors = observation.get("measurement_errors", [])
    error_names = [item.get("name", "") for item in errors]
    missing = [name for name in ("b0", "b1") if name not in points or name in error_names]
    same_frame = observation.get("frame_id") == state["frame_id"]
    current_identity = same_frame and params.get("identity") == "same_package_on_counter"
    empty_observed = same_frame and params.get("empty_open_hand") is True
    trials = [
        {"position_tolerance_m": 0.002, "lower_pad_z_m": 0.919552, "upper_pad_z_m": 0.916658,
         "required_nominal_overlap_m": 0.00874137, "interval_width_m": -0.00289441,
         "residual_margin_m": -0.00309441},
        {"position_tolerance_m": 0.001, "lower_pad_z_m": 0.918552, "upper_pad_z_m": 0.917658,
         "required_nominal_overlap_m": 0.00774137, "interval_width_m": -0.000894407,
         "residual_margin_m": -0.00109441},
        {"position_tolerance_m": 0.0005, "lower_pad_z_m": 0.918052, "upper_pad_z_m": 0.918158,
         "required_nominal_overlap_m": 0.00724137, "interval_width_m": 0.000105593,
         "residual_margin_m": -0.000094407}]
    height_gate = {
        "gate": "previous_candidate_guarded_height_interval",
        "prevented_action": "Repeat descent and closure using the rejected flat-package configuration.",
        "observation_frame": 216, "reference_frame": 0, "minimum_interval_width_m": 0.0002,
        "top_floor_world_z_m": 0.917398, "counter_ceiling_world_z_m": 0.899961,
        "finger_bottom_offset_m": -0.01285, "half_pad_z_m": 0.00800089,
        "guard_m": 0.00174137, "guarded_counter_clearance_m": 0.003,
        "guarded_overlap_m": 0.005, "nominal_overlap_floor_m": 0.007, "trials": trials,
        "uncertainty_accounting": "Historical guard plus each trial's pose tolerance, on both clearance and overlap bounds.",
        "provenance": "Acknowledged frame-216 diagnostics supplied with this request; secure.failure retained separately.",
        "scope": "Rejected candidate only. Not a new fit, current collision certificate, or rejection of every possible grasp."}
    gates = [
        height_gate,
        {"gate": "opposed_short_end_contact_evidence", "prevented_action": "Short-end pinch acquisition.",
         "observation_frame": observation.get("frame_id"), "missing": missing, "measurement_errors": errors,
         "interpretation": params.get("local_walls", "unknown"), "same_physical_frame": same_frame},
        {"gate": "replacement_configuration_and_sensing_route", "prevented_action": "New contact or complementary camera motion.",
         "status": "Not established by the supplied observations.",
         "scope": "The previous 30 mm retreat was already executed. Its clearance does not authorize a new lateral or rotational route. Hidden-wall visibility alone would not repair the rejected height interval."}]
    reason = "Acquisition remains blocked: no replacement configuration has established opposed contacts, aperture, full-hand clearance, and guarded overlap. The rejected candidate's best interval is 0.105593 mm, below 0.200 mm. No additional motion was commanded."
    status = "blocked"
    if not same_frame or read_errors:
        reason = "Current-stage admission references are unavailable or no longer contemporaneous. No motion or reopening was attempted; reacquisition and action-specific clearance are required."
    elif params.get("identity") == "changed" or not empty_observed:
        status = "needs_replan"
        reason = "The recorded entry condition does not establish the expected empty hand and unchanged package. Preserve the actual gripper state and reassess before any action."
    evidence = {
        "state": state, "action_authorized": False, "control_calls": 0,
        "control_questions_defined": list(questions), "gates": gates, "checkpoint_read_errors": read_errors,
        "package_on_counter_at_current_frame": current_identity, "empty_hand_at_current_frame": empty_observed,
        "acquisition_or_containment_effect_established": False,
        "source_observation": {"frame_id": observation.get("frame_id"), "parameters": params},
        "preserved_failure": records.get("secure.failure", {}).get("value", {}),
        "already_acknowledged_progress": records.get("alt.progress", {}).get("value", {}),
        "excluded_route": "Near-horizontal +/-88 and +/-90 degree long-side descents: observed palm-counter interference at frame 216.",
        "budget_interpretation": "Do not spend the remaining review repeating unchanged questions. This is an unresolved local admission gate, not proof of global impossibility."}
    receipt = api.checkpoint("place_verify.audit", evidence)
    handoff = {
        "stage": "place_verify", "checkpoint_keys": ["place_verify.audit", "alt.model", "secure.failure", "alt.progress"],
        "audit_checkpoint_frame": receipt["frame_id"], "frames": "World meters; rotations radians and xyzw; image pixels top-left.",
        "provenance": "alt.model contains frame-234 labeled depth receipts. secure.failure and the copied numerical trials are historical rejected-candidate diagnostics. alt.progress records the executed retreat. place_verify.audit records this zero-action admission check.",
        "necessary_gap": "A different evidence-supported contact configuration and its clearance/overlap margins; merely exposing b0/b1 does not clear the historical height gate.",
        "assumptions": "No reset, pickup, release, or containment inferred. Preserve the current gripper state. Revalidate any moved-object or moved-camera dependencies. Later retention and bowl-fit gates remain unresolved but were not used to reject a separately supported action."}
    return {"stage_status": status, "reason": reason, "evidence": evidence,
            "handoff": handoff, "completion_proposed": False}
