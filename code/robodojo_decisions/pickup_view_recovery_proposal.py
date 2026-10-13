"""Legal view programs ranked by public hand overlap with a recent view proxy."""
from pathlib import Path
import numpy as np
from pickup_visual_hull import _green_mask
from pickup_rgb_axes import _targets
from pickup_source_visibility import effect
from robot_path_preview import preview


def propose(obs, reference):
    if obs['episode_id'] != reference['episode_id']:
        raise ValueError('View proxy must come from this exact native episode')
    age=obs['step_id']-reference['step_id']
    if not 0 < age <= 20:
        return [], {'unavailable':'Same-episode reference must be 1..20 physical steps old'}
    path=next(row['path'] for row in reference['images'] if row['camera']=='cam_high')
    try:
        mask=_green_mask(Path(path),'cam_high')
    except ValueError as error:
        return [], {'unavailable':str(error)}
    yy,xx=np.nonzero(mask)
    proxy=np.zeros_like(mask);proxy[yy.min():yy.max()+1,xx.min():xx.max()+1]=True
    rows=[]
    for axis,sign in [('x',1),('x',-1),('y',1),('y',-1),('z',1)]:
        target=_targets(obs,axis,sign,.020)
        check=preview(obs,target['right'],None,steps=5)
        if not(check['public_path_gate'] and check['native_eef_single_action_legal']):
            continue
        predicted=effect(obs,target,source_mask_override=proxy,source_step_id=reference['step_id'])
        gain=(predicted['current_public_hand_footprint_overlap_fraction']-
              predicted['after_full_target_public_hand_footprint_overlap_fraction'])
        delta=[0,0,0];delta['xyz'.index(axis)]=sign*20
        rows.append({'id':f'view_world_{axis}_{sign}_20mm','target':target,
                     'delta_xyz_mm':delta,'public_path':check,'view_prediction':predicted,
                     'predicted_view_proxy_overlap_reduction':round(gain,4)})
    diagnostics={'reference_step_id':reference['step_id'],'reference_image_path':path,
        'reference_age_physical_steps':age,'view_proxy_bbox_xyxy':[int(xx.min()),int(yy.min()),int(xx.max()),int(yy.max())],
        'programs':rows,'scope':'Historical bbox ONLY a static-source view hypothesis. No current material/geometry/contact is inferred. The full short sweep still needs current RGB Luna review.'}
    ranked=sorted((row for row in rows if row['predicted_view_proxy_overlap_reduction']>0),
                  key=lambda row:row['predicted_view_proxy_overlap_reduction'],reverse=True)
    return ranked[:2], diagnostics
