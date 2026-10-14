"""Conditional source belief under occlusion; original current RGB is untouched."""
from pickup_visual_hull import build as build_hull
from pickup_fixed_blade_anchor import check


def build(obs,references):
    try:return build_hull(obs)
    except ValueError as original:
        errors=[]
        for step,reference in sorted(references.items()):
            if not 0<obs['step_id']-step<=200:continue
            try:
                anchor=check(reference,obs)
                if anchor['passed']:
                    return build_hull(obs,high_reference=reference,current_anchor=anchor)
            except ValueError as error:errors.append(str(error))
        raise ValueError(f'Current source geometry unavailable ({original}); no current-anchored prior silhouette passed: {errors}')
