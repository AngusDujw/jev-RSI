"""Opt-in manipulation-stage pilot; does not change the frozen v1 experiment."""
from dataclasses import dataclass
import re
from typing import Literal
import numpy as np

from pydantic import BaseModel, ConfigDict, Field


class MotorStage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    operation: Literal['approach', 'descend', 'close', 'lift', 'carry', 'lower', 'release', 'retreat']
    arm: Literal['left', 'right']
    target_id: str
    destination_id: str | None
    objective: str
    expected_change: str
    evidence_fields: list[Literal['object_pose', 'robot_pose', 'gripper_opening', 'rgb_geometry', 'temporal_change']] = Field(min_length=1)
    completion_evidence: str
    maintain: list[str]
    recovery: str
    max_decisions: int = Field(ge=1, le=24)


class MotorPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task: str
    stages: list[MotorStage] = Field(min_length=1, max_length=32)


PROMPT = """You are the high-level GPT planner for dual ARX X5 manipulation.
Plan the entire remaining pickup/stack task as SHORT PHYSICAL OPERATIONS that
Jev can advance with fixed translation/rotation increments or open/close commands.
Jev cannot see RGB. It receives ONLY the supplied structured evidence, robot
proprioception, stage-entry evidence, action history and your complete plan.
You choose semantic objects/relations; Jev chooses every motion direction and
increment. Do not output XYZ, angles, pixels, waypoints, axis commands or code.

Each stage MUST specify operation, arm, an observed target_id, optional observed
destination_id, a physical objective, expected observable change, evidence_fields,
an operational completion criterion, invariants, recovery and max_decisions.
Object identification, choosing a base, task interpretation and resolving conflicting
descriptions are YOUR planning work: NEVER create identify/confirm/verify/assess/
observe/choose/understand as standalone stages. A stage must change physical state.
Approach/descend change hand-object relation; close changes gripper opening;
lift changes object height with correlated hand-object motion; carry changes held
object-destination relation; lower/release/retreat change support/gripper separation.
Closing completes ONLY the close operation, not a grasp. Lift is an active test:
require object motion with the hand; hand-only lift is failure requiring recovery.
Close completion is the observed closing response to the command (decreased opening
while retaining the closure pose), not reaching the empty-gripper zero endpoint:
an object may oppose the fingers. Then actively test acquisition by lifting.
Every lift AND release stage MUST name temporal_change in evidence_fields.
Split approach, closure and test-lift when separate evidence makes them checkable.
If a preparatory operation is already satisfied by present evidence, omit it.

Completion must be decidable from named evidence_fields, comparing stage entry
with current observations. Do not require proving safety, free space, stable support,
contact force, texture identity or dimensions when those signals are not supplied.
Never substitute a narrative intention or gripper closure for observed object effect.
Oracle: object poses and nominal robot grasp points are available, but no measured
contact or support graph. If object geometry is supplied, world_bbox_min_m and
world_bbox_max_m describe the observed bounding surfaces, not measured contact.
For upright blocks use the held block's bottom and destination's top, not center
height ordering, to specify lift clearance, carry clearance and lowering endpoint.
Never lower until motion stalls: a plateau could be IK tracking error or a jam.
Describe closure positioning relative to the observed block center and the named
nominal grasp reference, not an undefined grasp neighborhood. Account for approach
orientation when needed. Use the existing finest action resolution to express
alignment; do not invent numerical tolerances, contact forces or pose waypoints.
Keep a positive bottom-to-top clearance during carry. Lower to the first nonnegative
surface gap within the existing finest translation increment, then release and test
retention by retreat. Do not wait for nonpenetrating surfaces to overlap. If observed
geometry or orientation cannot establish these relations, explicitly report missing
evidence in recovery; do not replace geometry by force, plateau or center height.
Pose proximity is not contact proof. Release can settle; retreat must show the object
stays at the destination and does not follow the hand. Carry stages must not require
movement in every component when that component was already aligned at entry.
After release, use bottom-to-top adjacency within existing motion resolution;
do not require an exactly nonnegative settled gap because simulator contact can
have small penetration. This does not authorize intentional penetrating lowering.
Vision: only per-camera 2D geometry/color/masks, calibrated robot projections and
temporal changes are available. No object depth or XYZ. Pixel alignment alone is
not metric grasp alignment; co-motion needs fixed-camera evidence. If depth/contact
is essential but unobservable, recovery must explicitly request missing evidence
or an informative physical reposition, not repeat passive confirmation indefinitely.

Use existing object IDs, including observed destination IDs; never invent one.
Same object has separate IDs in different cameras; do not assume correspondence.
The controller enforces max_decisions, requests a revision on 6 consecutive holds
or a blocked transition, and caps total planning rounds. Budgets count actual Jev
decisions. A timeout does NOT complete a stage. Given failure_feedback, replace
the failed approach with an evidence-supported physical alternative, not the same
non-operational condition. Native task success remains the simulator's decision.
Return the requested JSON schema. This pilot supports pickup and stacking only.
"""


def stage_signals(evidence, entry, stage, mode):
    """Observation arithmetic only; no waypoint generator, audit or task reward."""
    arm = ('left', 'right').index(stage.arm)
    robot, initial_robot = evidence['robot'], entry['robot']
    out = dict(gripper_opening=robot['states'][arm*7+6],
               gripper_opening_at_entry=initial_robot['states'][arm*7+6],
               caution='Relative observations, not contact or success proof; Jev still chooses actions and completion')
    if mode == 'oracle':
        current = {o['id']: o for o in evidence['objects']}
        initial = {o['id']: o for o in entry['objects']}
        if stage.target_id not in current or stage.target_id not in initial:
            return dict(out, target_available=False)
        p = np.asarray(current[stage.target_id]['position_m'])
        p0 = np.asarray(initial[stage.target_id]['position_m'])
        hand = np.asarray(robot['nominal_grasp_points_m'][arm])
        hand0 = np.asarray(initial_robot['nominal_grasp_points_m'][arm])
        out.update(target_available=True, frame='environment_origin', units='metres',
            target_minus_nominal_grasp_m=(p-hand).round(5).tolist(),
            horizontal_separation_m=float(np.linalg.norm((p-hand)[:2])),
            object_delta_since_entry_m=(p-p0).round(5).tolist(),
            hand_delta_since_entry_m=(hand-hand0).round(5).tolist(),
            object_hand_displacement_residual_m=float(np.linalg.norm((p-p0)-(hand-hand0))))
        if stage.destination_id in current:
            out['destination_minus_object_m'] = (np.asarray(current[stage.destination_id]['position_m'])-p).round(5).tolist()
            if stage.destination_id in initial:
                out['destination_minus_object_at_entry_m'] = (np.asarray(initial[stage.destination_id]['position_m'])-p0).round(5).tolist()
                out['destination_horizontal_separation_at_entry_m'] = float(np.linalg.norm(np.asarray(out['destination_minus_object_at_entry_m'])[:2]))
            target_geometry = current[stage.target_id].get('geometry')
            destination_geometry = current[stage.destination_id].get('geometry')
            if target_geometry and destination_geometry:
                out['object_bottom_minus_destination_top_m'] = float(target_geometry['world_bbox_min_m'][2]-destination_geometry['world_bbox_max_m'][2])
        return out
    def table(ev):
        return {obj['id']: (camera, obj) for camera, view in ev['views'].items()
                for obj in view.get('objects', [dict(zip(view.get('object_columns', []), row)) for row in view.get('object_rows', [])])}
    current, initial = table(evidence), table(entry)
    if stage.target_id not in current:
        return dict(out, target_available=False)
    camera, target = current[stage.target_id]
    geom = evidence.get('robot_image_geometry', {}).get('views', {}).get(camera, {}).get('robot', {}).get(stage.arm, {})
    out.update(target_available=True, camera=camera, units='normalized pixels, not metres',
               correspondence='Detector ID may be unreliable under occlusion; do not assume physical identity')
    if geom.get('inside_image'):
        out['target_minus_projected_grasp_uv01'] = (np.asarray(target['center_uv01'])-geom['nominal_grasp_uv01']).round(5).tolist()
    if stage.target_id in initial:
        out['target_center_delta_uv01'] = (np.asarray(target['center_uv01'])-initial[stage.target_id][1]['center_uv01']).round(5).tolist()
    out['object_height_contact_and_depth'] = 'unavailable; pixel overlap cannot establish these'
    return out


def validate_plan(raw, evidence, mode):
    plan = MotorPlan.model_validate(raw)
    if mode == 'oracle':
        ids = {obj['id'] for obj in evidence['objects']}
    else:
        ids = {obj['id'] for view in evidence['views'].values() for obj in view['objects']}
    for stage in plan.stages:
        if stage.target_id not in ids or (stage.destination_id is not None and stage.destination_id not in ids):
            raise ValueError('Stage refers to an unobserved object ID')
        if re.match(r'\s*(identify|confirm|verify|assess|observe|choose|understand|decide)\b', stage.objective, re.I):
            raise ValueError('Non-operational stage objective')
        if mode == 'vision' and 'object_pose' in stage.evidence_fields:
            raise ValueError('Vision stage requires unavailable object poses')
        if mode == 'oracle' and 'rgb_geometry' in stage.evidence_fields:
            raise ValueError('Oracle Jev input contains no RGB geometry')
        if stage.operation == 'carry' and stage.destination_id is None:
            raise ValueError('Carry requires an observed destination')
        if stage.operation in {'lift', 'release'} and 'temporal_change' not in stage.evidence_fields:
            raise ValueError('Lift/release requires temporal evidence')
    return plan


@dataclass
class StageClock:
    decisions: int = 0
    holds: int = 0
    blocked: bool = False

    def record(self, executed, blocked=False):
        self.decisions += 1
        self.holds = self.holds+1 if executed == 'hold' else 0
        self.blocked = blocked

    def failure(self, stage):
        if self.blocked:
            return 'Jev reported stage blocked or evidence unavailable'
        if self.decisions >= stage.max_decisions:
            return 'Stage decision budget exhausted without completion'
        if self.holds >= 6:
            return 'Six consecutive holds without stage completion'
        return None
