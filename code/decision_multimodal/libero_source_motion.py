"""Uncertain RGB-D displacement of an actor-selected feature, never object pose.

This measures a matched feature only. It neither certifies holding nor chooses
an action or phase. Phase classification remains an actual Decisions request.
"""
import math


def vector(value):
    return isinstance(value,(tuple,list)) and len(value)==3 and all(type(v) in (int,float) and math.isfinite(v) for v in value)


def entry_feature(sample,camera,tick):
    point=sample.get('visible_surface_world_mm') if sample else None
    if not vector(point):return None
    change=sample.get('matched_feature_change_since_selection_mm')
    if sample.get('label')=='S':
        if not vector(change):return None
        origin=[p-d for p,d in zip(point,change)]
    else:origin=list(point)
    return dict(entry_tick=tick,camera=camera,entry_visible_feature_world_mm=list(point),
        estimated_selection_origin_world_mm=origin)


def motion_observation(entry,samples,camera,tick,own_motion):
    missing=dict(available=False,meaning='No usable same-feature phase-entry/current RGB-D displacement. Unknown is not zero.')
    if entry is None:return dict(missing,reason='No phase-entry feature was established by the actor.')
    if entry['camera']!=camera:return dict(missing,reason='Source observation camera changed.')
    sample=next((s for s in samples if s.get('label')=='S'),None)
    if sample is None:return dict(missing,reason='Current forward/backward-checked feature S is missing.')
    point=sample.get('visible_surface_world_mm');change=sample.get('matched_feature_change_since_selection_mm')
    own=own_motion.get('translation_world_mm');rotation=own_motion.get('relative_world_rotvec_deg')
    if not all(vector(x) for x in (point,change,own,rotation)):
        return dict(missing,reason='A current feature or measured own-motion vector is unavailable.')
    origin=[p-d for p,d in zip(point,change)]
    gap=math.sqrt(sum((a-b)**2 for a,b in zip(origin,entry['estimated_selection_origin_world_mm'])))
    if gap>.5:return dict(missing,reason='The estimated feature-selection origin changed.',origin_discrepancy_mm=round(gap,3))
    if sum(v*v for v in rotation)>9:
        return dict(missing,reason='Own rotation exceeds the three-degree scope of this short translation test.')
    delta=[round(a-b,1) for a,b in zip(point,entry['entry_visible_feature_world_mm'])]
    return dict(available=True,entry_tick=entry['entry_tick'],current_tick=tick,camera=camera,
        origin_discrepancy_mm=round(gap,3),observed_feature_change_world_mm=delta,
        measured_own_hand_change_world_mm=own,
        feature_minus_hand_motion_mm=[round(a-b,1) for a,b in zip(delta,own)],
        meaning='An actor-selected visible feature tracked by forward/backward RGB correspondence and remeasured with current registered depth/public calibration. Only a camera-derived feature estimate, not simulator object pose, contact or a holding certificate.',
        uncertainty='Pixel/depth mixing, occlusion and appearance mistakes may invalidate the match. The 0.5mm origin check only checks continuity of the stored estimate, not sensor accuracy. Confirm identity in current RGB. No motor direction or phase result is computed here.')
