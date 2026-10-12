"""GPT-declared, sensor-only visual method for the staged RoboDojo policy."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Camera = Literal['cam_high', 'cam_left_wrist', 'cam_right_wrist']


class VisualEntityMethod(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^v_[a-z][a-z0-9_]*$', max_length=42)
    role: Literal['source', 'receiver', 'support', 'obstacle', 'landmark']
    query: str = Field(min_length=2, max_length=120)
    redetection_operator: Literal['gpt_rgb_boxes', 'grounding_dino_sam2_rgb'] = 'gpt_rgb_boxes'
    local_detector_query_en: str | None = Field(default=None, max_length=100)
    distinguishing_cues: list[str] = Field(min_length=1, max_length=5)
    preferred_views: list[Camera] = Field(min_length=1, max_length=3)
    silhouette: Literal['rgb_box', 'grabcut_rgb']
    metric_point: Literal['box_center', 'silhouette_centroid']
    max_ray_gap_m: float = Field(default=.015, ge=.005, le=.04)
    max_stale_ticks: int = Field(default=12, ge=0, le=80)
    verification: list[Literal['fresh_stereo', 'visible_motion', 'relative_position',
                               'robot_motion', 'gripper_aperture']] = Field(min_length=1, max_length=5)

    @model_validator(mode='after')
    def compatible_geometry(self):
        if self.metric_point == 'silhouette_centroid' and self.silhouette != 'grabcut_rgb':
            raise ValueError('silhouette_centroid requires grabcut_rgb')
        if len(set(self.preferred_views)) != len(self.preferred_views):
            raise ValueError('preferred_views must be unique')
        if self.redetection_operator == 'grounding_dino_sam2_rgb' and not self.local_detector_query_en:
            raise ValueError('Local DINO+SAM2 redetection requires an English query')
        return self


class VisualCycleMethod(BaseModel):
    model_config = ConfigDict(extra='forbid')
    moving_id: str = Field(pattern=r'^v_[a-z][a-z0-9_]*$')
    reference_id: str = Field(pattern=r'^v_[a-z][a-z0-9_]*$')
    axis: Literal['x', 'y', 'z'] = 'z'
    press_direction: Literal['increase', 'decrease'] = 'decrease'
    press_delta_m: float = Field(ge=.001, le=.04)
    release_delta_m: float = Field(ge=0., le=.02)
    confirmations: int = Field(default=2, ge=1, le=3)

    @model_validator(mode='after')
    def ordered_thresholds(self):
        if self.moving_id == self.reference_id or self.release_delta_m >= self.press_delta_m:
            raise ValueError('A visual cycle needs distinct landmarks and separated thresholds')
        return self


class VisionMethodPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reasoning: str = Field(min_length=20)
    entities: list[VisualEntityMethod] = Field(min_length=1, max_length=12)
    visible_success_evidence: str = Field(min_length=10)
    unobservable_requirements: list[str] = Field(default_factory=list, max_length=12)
    reobserve_triggers: list[str] = Field(min_length=1, max_length=8)
    event_monitors: list[VisualCycleMethod] = Field(default_factory=list, max_length=12)

    @model_validator(mode='after')
    def unique_ids(self):
        ids = [entity.id for entity in self.entities]
        if len(ids) != len(set(ids)):
            raise ValueError('Visual entity ids must be unique')
        monitors = [monitor.moving_id for monitor in self.event_monitors]
        if len(monitors) != len(set(monitors)) or any(
                monitor.moving_id not in ids or monitor.reference_id not in ids
                for monitor in self.event_monitors):
            raise ValueError('Visual cycle landmarks must be declared and moving IDs unique')
        return self


METHOD_PROMPT = '''You are GPT-6 designing the VISUAL ALGORITHM for a RoboDojo
manipulation task before any motor action. This is a live per-episode plan, not
an offline task lookup. Use only the public instruction, the three supplied RGB
images, camera calibration and robot proprioception. Never request or infer a
simulator object id, object truth pose, asset geometry, reward or success flag.
Return the VisionMethodPlan JSON. Give each task-relevant physical entity a
stable semantic id beginning v_; distinguish duplicates with visible color,
shape, position or context, not a scene name. Choose among the IMPLEMENTED
operators only: GPT RGB boxes; optional local RGB GrabCut foreground mask;
calibrated cross-view center-ray triangulation; RGB tracking; robot proprioception.
If grounding_dino_sam2_rgb is listed among available_operators, you may use
it to propose fresh RGB boxes after the FIRST GPT identity grounding. Supply
an English noun phrase in local_detector_query_en, e.g. "pale conch shell"
or "purple block". Local detections are only candidates: the runtime matches
them against the established visual instance by image overlap and appearance,
and falls back to GPT if association is uncertain. Prefer this operator for
compact visible objects with meaningful noun phrases; use GPT for broad
surfaces or subtle relations the detector cannot identify reliably.
GrabCut can refine an RGB silhouette, but it is not SAM, and a silhouette
centroid from different cameras is only an approximate correspondence. There
is NO object depth image, measured object orientation, full mesh, or hidden
support plane in this interface. A one-camera projection using a prior height
has UNVERIFIED Z. If an essential target surface, opening, orientation or
physical relation is not observable, say so in unobservable_requirements and
name the reobservation trigger. Never invent its 3D coordinates. Say what
fresh visual evidence and own-robot feedback could verify progress or reveal
failure. For a stationary, ungrasped tabletop entity with confirmed stereo,
choose a bounded max_stale_ticks that covers several short approach actions
(roughly 8-16 native ticks at 25 Hz); this permits a brief hand occlusion.
For moving/ambiguous entities use a much shorter age. The runtime refuses
stale guidance once visual motion or possible grasp is detected. Stale geometry
never proves capture or success. The later stage planner, not this method call,
chooses motor goals.
When a whole-object box centre is not a useful physical correspondence across
views or a contact target, declare an additional small visual landmark tied by
its query and distinguishing cues to that same object. Examples include a
visible handle loop, a rigid graspable segment, a block top face, a button
surface, or an opening rim. Use a distinct v_ id and role=landmark; retain the
whole-object entity for identity and motion checks. Ask the localizer for a
tight box around the SAME visible part in each camera, not different silhouette
centres. If the part is hidden in a view, omit that view and keep its depth
unverified. A landmark gives an approximate camera-derived point for a bounded
action, not a precise contact surface or proof of grasp/placement. Select only
parts visible and useful for the next action; avoid whole-scene searches.
For a public task that requires repeated full presses and releases, declare
both the visible moving button top and a stationary base/rim as separate
landmarks, and add one event_monitors entry for that pair. The implemented
monitor compares their CURRENT accepted stereo RGB points along the selected
world axis, initializes its baseline from a visible released state, and counts
only a down-then-return cycle beyond your declared conservative metre
thresholds for the specified number of consecutive observations. Choose
thresholds above expected pixel/stereo jitter, with release_delta_m smaller
than press_delta_m; these are visual hypotheses, not simulator button travel.
If the two parts cannot both be triangulated, the monitor will report invalid
instead of inventing a count. Keep an independent viewing camera clear during
contact. The cycle count is visual evidence only, not a native success flag.
Do not choose a task-specific fixed pixel ROI or absolute world point.'''
