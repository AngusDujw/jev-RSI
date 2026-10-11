from .contracts import Plan, Decision

PLANNER = """You are the high-level System 2 of a robot. Plan the ENTIRE requested task
as semantic stages with observable completion goals. You never output XYZ, pixels,
Euler angles, waypoints, joint values, per-axis directions, or executable code.
The independent Jev System 1 sees freshly measured visual geometry and selects
individual fixed Cartesian increments or open/close. A controller executes them.
Describe object identity, stage objectives, invariants and recovery in plain language.
Use only observable predicates in the schema. Keep stages simple, preferably one
physical milestone each, ordered to make picking and placing physically possible.
For tabletop pick-place: identify/align above object with fingers open, descend to
grasp height, close, lift and verify object movement, carry above destination while
raised, lower without losing grip, release, retract and verify placement.
Do not put released in an alignment stage, as released means the object was released
AFTER grasping. lifted means visual lift since first sighting with closed gripper.
at_grasp_height uses visual object surface with the configured grasp offset.
lowered is low above the destination after transport. retreated is raised with open
gripper after release. object_in_destination requires visible object inside destination
and no longer moving. A closed gripper alone is NOT evidence of grasp success.
Plans must be feasible for a fixed-orientation, single active arm.
For carry and lower stages set maintain=["holding"]: the object must remain
visually close to the grasp point with closed fingers. Loss requests replanning.
For all other stages use maintain=[] in this implementation. Maintain is checked
BEFORE taking any action, not a future target: never require aligned in the stage
that establishes alignment, or holding in the stage that establishes the grasp.
Use gripper_closed as completion of closing; the subsequent lift verifies success.
If a visible obstacle separates source and destination, lift until lifted is true
before carrying. The local observable lifted predicate includes configured visual
obstacle clearance; never invent a height or ask the low-level model to ignore it.
Never assume hidden objects, simulator rewards or known object positions.
Unknown -> observe/replan.
The completion fields are ANDed. Do not ask for a future-stage predicate early.
Return only the specified JSON. Budget 100 local decisions for a travel stage.
"""

LOCAL = """You are System 1: choose local XYZ directions and a finger command for the CURRENT stage.
You receive only camera-derived objects, relations, robot proprioception and history.
Do not skip stages. Geometry is in metres in the active robot base/work frame:
positive axis increases that coordinate. Deltas in candidates are executed literally.
Compute useful signs from observed relative vectors; axes can change concurrently.
The local executor uses a configured constant-length increment, normalizing diagonal
motion. Choose hold for axes already aligned. It never computes a task waypoint.
Never lower before horizontal alignment.
During lift/carry keep fingers closed. Keep object elevated over destination walls.
Aperture is measured opening: 0 closed, 1 fully open. If grasp fails request replanning.
Unknown geometry is not zero. If necessary object lost, hold/observe or replan.
No motion accompanies advance/replan/stop. Advance only when ALL current completion
facts are true (including consecutive evidence). Do not advance merely because an
action was commanded. Missing/unproved conditions mean continue. The final stage
advances only on observed placement verification. Prioritize object movement, not
just hand movement. Confidence is uncertainty, not a guarantee of safety.
"""


def plan_task(api, goal, robot_description, evidence, cameras, previous=None):
    raw = api.chat(PLANNER, {"goal": goal, "robot": robot_description,
                           "observation": evidence, "previous_failure": previous}, cameras, Plan.model_json_schema())
    plan = Plan.model_validate(raw)
    # Strict schema prevents numeric motion payloads; prose cannot override executor.
    return plan


def choose(api, plan, index, evidence, candidates, history, min_confidence=.55):
    stage = plan.stages[index]
    # Full masks remain in local evidence logs; decisions use their measured summary.
    compact = {k:v for k,v in evidence.items() if k != "views"}
    compact["objects"] = {label:{k:v for k,v in obj.items() if k not in {"mask_grid_8x8", "contour_uv"}} for label,obj in evidence["objects"].items()}
    state = {"instruction": LOCAL, "plan": plan.model_dump(), "stage_index": index,
             "current_stage": stage.model_dump(), "evidence": compact, "recent": history[-4:]}
    questions = {
        "gripper": {"type":"choice","instructions":"Choose finger command for current stage objective: keep current state during translation. Explicit grasp means close; explicit release means open. Once measured aperture meets the goal hold it. Never release during lift or carry.","criteria":{"hold":"Keep present finger command","open":"Open fingers","close":"Close fingers"}},
        "transition": {"type": "choice", "instructions": {"current_stage":stage.id,"required_measured_facts":{k:evidence["facts"].get(k) for k in stage.completion},"question":"Judge ONLY this stage, not the entire task. If every required_measured_fact is true, select advance. False or null means continue unless progress is impossible. Gripper_closed stage only requires measured closure; next lift stage verifies grasp. These facts already require consecutive observations."},
                       "criteria": {"continue": "Current stage incomplete, local actions can progress it", "advance": "All current stage completion facts are proven", "replan": "Plan invalid, repeated no progress or required information unavailable", "stop": "Unsafe or user intervention required"}}}
    if not all(evidence["facts"].get(k) is True for k in stage.completion):
        # Completion is an admission condition, like workspace limits for motors.
        # The model may not advance on guessed or missing sensor evidence.
        questions["transition"]["criteria"].pop("advance")
    for axis in "xyz":
        allowed={sign: f"Translate {axis} in {sign} direction in robot frame" for sign in ("negative","positive") if any(f"{axis}_{sign}_{scale}" in candidates for scale in ("coarse","fine"))}
        allowed["hold"]="Do not change this coordinate"
        component="xyz".index(axis)
        geometry={"current_grasp_coordinate_m":evidence["robot"]["grasp_point_m"][component],
                  "object_coordinate_m":evidence["objects"].get(plan.object_label,{}).get("position_m"),
                  "destination_coordinate_m":evidence["objects"].get(plan.destination_label,{}).get("position_m"),
                  "object_grasp_height_m":evidence.get("object_grasp_height_m"),
                  "grasp_tolerance_m":evidence.get("grasp_tolerance_m",.006),
                  "axis_index":component}
        questions[axis]={"type":"choice","instructions":{"axis":axis,"geometry":geometry,
             "question":f"Choose the {axis.upper()} direction for current_stage.objective. All axes are decided concurrently. XY alignment: object/destination coordinate minus current grasp coordinate; hold if absolute error < 0.007m. Pure descend/lift/retreat stages: ALWAYS hold X and Y; do not chase the partially occluded visible surface centroid. Grasp/release: hold all XYZ. For descend compare Z with object_grasp_height_m, hold only within grasp_tolerance_m. Lift/retreat increase Z until completion; lower stage decrease Z until lowered. Carry keeps Z unchanged. Once ALL current completion predicates are true, hold all axes. Unknown target -> hold. No automatic stage switching."},"criteria":allowed}
    state["fixed_steps_m"]={k:v["delta"] for k,v in candidates.items()}
    a = api.jev(state, questions)
    import numpy as np
    gripper=a["gripper"]["choice"]
    aperture=evidence["robot"]["aperture"]
    if gripper=="open" and aperture>.95:
        gripper="hold"  # Idempotent request already satisfied by measured feedback.
    if gripper!="hold":
        selected=gripper; confidence=a["gripper"]["confidence"]
    else:
        selected="hold"; confidence=1.; delta=np.zeros(3); names=[]
        for i,axis in enumerate("xyz"):
            sign=a[axis]["choice"]
            if sign!="hold":
                if a[axis]["confidence"] < min_confidence:
                    # Abstain on just this uncertain axis; never flip its sign.
                    continue
                name=f"{axis}_{sign}_coarse"
                if name not in candidates:
                    confidence=0.; continue
                delta+=np.array(candidates[name]["delta"])
                confidence=min(confidence,a[axis]["confidence"])
                names.append(name)
        if names:
            # Constant Euclidean step, chosen signs preserved; no computed waypoint.
            delta/=len(names)**.5
            selected="+".join(names)
            candidates[selected]={"delta":delta.tolist(),"gripper":"hold"}
        else:
            confidence=min(a[axis]["confidence"] for axis in "xyz")
    return Decision(action=selected, transition=a["transition"]["choice"],
                    confidence=float(confidence), transition_confidence=float(a["transition"]["confidence"])), a
