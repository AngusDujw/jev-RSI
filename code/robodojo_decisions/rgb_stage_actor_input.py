"""Stage-focused actor evidence; full solver diagnostics remain in run assets."""
import copy


def compact(data, action=False):
    result = copy.deepcopy(data)
    geometry = result.get('algorithmic_far_approach_evidence')
    if isinstance(geometry, dict) and geometry.get('status') == 'current_conditional_top_hypothesis':
        fit = geometry.get('fit', {})
        geometry['fit'] = {k: fit[k] for k in (
            'best_plane_z_m', 'best_mask_iou',
            'near_best_z_m_at_iou_within_0p05',
            'top_interior_material_candidate') if k in fit}
        offered = result.get('complete_programs', {})
        geometry['candidate_endpoint_relations'] = {
            k: v for k, v in geometry.get('candidate_endpoint_relations', {}).items()
            if k in offered}
    if action:
        # The current stage and its exact provider rule are already supplied.
        # Later-stage EXIT recipes belong to the separate perception query.
        result.pop('planner_stages', None)
    result['actor_evidence_scope'] = (
        'Current RGB/robot state, current semantic roles, declared uncertainty '
        'and only the OFFERED complete programs. Removed unused solver '
        'alternatives remain in the saved full evidence. Exact current error '
        'values, target poses, original experience and all original RGB are '
        'preserved. This input formatting grants no action permission.')
    return result
