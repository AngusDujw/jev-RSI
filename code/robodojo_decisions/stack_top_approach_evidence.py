"""Current RGB top-plane/pad residuals for FAR approach, never grasp truth."""
from pathlib import Path
import itertools
import copy
import cv2
import numpy as np
from scipy.ndimage import binary_dilation
from camera_geometry import ray, eef_transform, gripper_height_above_landmark
from gripper_pad_projection import inspect
from planar_patch_geometry import fit, _rgb_mask


def _region(path, minimum):
    rgb=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB).astype(int)
    mask=(np.all(rgb >= [220,210,150],axis=2) &
          (rgb[:,:,0]-rgb[:,:,2]>25) & (rgb[:,:,1]-rgb[:,:,2]>15))
    _,_,stats,_=cv2.connectedComponentsWithStats(mask.astype('uint8'))
    candidates=[s for s in stats[1:] if int(s[4])>=minimum]
    if len(candidates)!=1:
        raise ValueError('Current pale-material component identity ambiguous or absent')
    x,y,w,h,area=map(int,candidates[0])
    return (x,y,x+w-1,y+h-1),area


def build(obs, programs, paths=None, high_reference=None):
    if obs['task']!='stack_blocks' or 'measured_gripper_joint_state' not in obs:
        raise ValueError('Current stack RGB and actual finger encoders required')
    if float(obs['current_eef']['right']['gripper_opening_command'])<.5:
        raise ValueError('Top-plane operator is only for open-hand approach')
    image_paths={x['camera']:Path(x['path']) for x in obs['images']}
    hi,hn=_region(image_paths['cam_high'],20);wr,wn=_region(image_paths['cam_right_wrist'],50)
    cal=obs['camera_calibration']
    fit_obs=obs;fit_hi=hi;reference_check=None
    if high_reference is not None:
        age=obs['step_id']-high_reference['step_id']
        if (high_reference['episode_id']!=obs['episode_id'] or not 0<age<=50):
            raise ValueError('Prior high source requires same episode and age1..50 physical steps')
        a=cal['cameras']['cam_high'];b=high_reference['camera_calibration']['cameras']['cam_high']
        if not all(np.allclose(a[key],b[key],atol=1e-7,rtol=0)
                   for key in ['camera_to_environment','intrinsic']):
            raise ValueError('Prior high source requires an unchanged fixed camera')
        reference_path=Path(next(x['path'] for x in high_reference['images'] if x['camera']=='cam_high'))
        fit_hi,reference_pixels=_region(reference_path,20)
        current=_rgb_mask(image_paths['cam_high'],hi,(220,210,150))
        prior=_rgb_mask(reference_path,fit_hi,(220,210,150))
        covered=float((current&binary_dilation(prior,iterations=2)).sum()/current.sum())
        visible=float((current&prior).sum()/prior.sum())
        if covered<.95 or visible<.30:
            raise ValueError('Current fixed-high material does not support the prior source footprint')
        reference_check={'reference_step_id':high_reference['step_id'],'age_physical_steps':age,
            'current_high_pixels_in_prior_2px_dilation_fraction':covered,
            'prior_high_pixels_currently_visible_fraction':visible,
            'reference_high_pixels':reference_pixels,
            'scope':'CURRENT partial high material and CURRENT wrist revalidate a bounded static-source possibility; prior full high pixels are historical, not current contact evidence.'}
        fit_obs=copy.deepcopy(obs)
        for image in fit_obs['images']:
            if image['camera']=='cam_high':image['path']=str(reference_path)
    fitted=fit(fit_obs,cal,fit_hi,wr,(220,210,150),.74,.85,.001)
    if fitted['best_mask_iou']<.65:
        raise ValueError('Current two-view top-plane support insufficient')
    lo,up=fitted['near_best_z_m_at_iou_within_0p05']
    if up-lo>.025:
        raise ValueError('Current top-plane height hypothesis too broad')
    pads=inspect(obs,cal)
    center=np.mean([np.mean(v['inner_facet_world_xyz_m'],axis=0)
                    for v in pads['rows'].values()],axis=0)
    point=np.asarray(fitted['top_interior_material_candidate']['camera_derived_world_hypothesis_m'])
    uv=fitted['top_interior_material_candidate']['high_pixel_uv'];poss=[]
    for du,dv,z in itertools.product([-2,0,2],[-2,0,2],[lo-.002,up+.002]):
        eye,direction=ray(cal['cameras']['cam_high'],[uv[0]+du,uv[1]+dv])
        distance=(z-eye[2])/direction[2]
        if distance<=0:raise ValueError('Top-plane ray is behind the camera')
        poss.append(eye+distance*direction)
    poss=np.asarray(poss);old=eef_transform(obs['current_eef']['right'])
    local=np.linalg.inv(old)@np.r_[center,1];predicted={}
    for name,program in programs.items():
        target=program['target']['right']
        if target['gripper_closed']:continue
        newcenter=(eef_transform(target)@local)[:3]
        predicted[name]={'top_minus_pad_midpoint_world_xyz_mm':((point-newcenter)*1000).round(2).tolist(),
                         'hypothesis_distance_mm':round(float(np.linalg.norm(point-newcenter)*1000),2)}
        if paths is not None:
            gaps=[]
            for row in paths[name]['public_five_step_path']['predicted_joint_path']:
                pose={'position':row['predicted_link6_position_m'],
                      'quaternion_wxyz':row['predicted_link6_quaternion_wxyz']}
                gaps.append(gripper_height_above_landmark(pose,[0,0,up+.002],0)['hand_above_landmark_plane_after_m']*1000)
            predicted[name]['minimum_whole_hand_above_source_top_upper_hypothesis_mm']=round(min(gaps),2)
            predicted[name]['height_scope']='Public hand mesh over all openings and predicted five-step robot path vs this SOURCE top-height hypothesis only. Other objects and entire visible short corridor still require RGB; not scene collision certification.'
    fitted.pop('score_grid')
    if reference_check is not None:
        fitted['source']='PRIOR same-episode fixed-high mask + CURRENT right-wrist material, under CURRENT partial-high static-footprint check; not current two-view contact geometry'
    return {'status':'current_conditional_top_hypothesis',
            'entity':'Unique CURRENT pale yellow wood-textured region candidate; Luna must verify identity and role from raw RGB.',
            'step_id':obs['step_id'],'current_component_pixels':{'high':hn,'right':wn},
            'high_source_basis':'CURRENT high mask' if reference_check is None else 'PRIOR fixed-high source mask, conditionally revalidated by CURRENT partial-high and wrist RGB',
            'current_full_two_view_top_supported':reference_check is None,
            'prior_high_source_check':reference_check,
            'fit':fitted,'public_actual_finger_facets':pads,
            'measured_robot_pad_midpoint_world_m':center.tolist(),
            'top_minus_pad_midpoint_world_xyz_mm':((point-center)*1000).round(2).tolist(),
            'top_minus_pad_midpoint_xyz_interval_mm':np.stack([(poss.min(axis=0)-center)*1000,(poss.max(axis=0)-center)*1000],axis=1).round(2).tolist(),
            'current_hypothesis_distance_mm':round(float(np.linalg.norm(point-center)*1000),2),
            'candidate_endpoint_relations':predicted,
            'interpretation':'Residual = source-top hypothesis minus actual public pad midpoint, in WORLD XYZ. Positive component means material hypothesis is on that positive side. Translation of the pad in that sign reduces that component; rotations also move the pad about LINK6. Endpoint relations use target robot pose; actual tracking must be measured.',
            'limits':'FAR OPEN approach only. Masks/flat-plane search and +-2px/2mm sensitivity form conditional possibilities, not calibrated confidence, object pose, grasp target or scene clearance. A PRIOR high mask is historical and requires the explicit CURRENT material check and fresh wrist refit above; it never certifies CURRENT contact. Top interior is not opposed side contact. Midpoint can be in free space. Do not descend into material or CLOSE based on this residual. Raw RGB must independently support identity, phase and entire short corridor. Multiple/absent masks or failed current reference checks return UNKNOWN; never reuse old geometry without current revalidation.'}
