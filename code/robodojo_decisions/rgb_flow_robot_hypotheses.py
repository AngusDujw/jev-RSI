"""Past RGB correspondence residuals under static / rigid-tool hypotheses.

Depth is a declared hypothesis domain, never a measured object pose. This
compares explanations of already-observed motion; it proposes no action.
"""
import numpy as np
from scipy.spatial.transform import Rotation
from camera_geometry import eef_transform


def compare(previous,current,old_uv,new_uv,camera='cam_high'):
    if previous['episode_id']!=current['episode_id'] or previous['step_id']>=current['step_id']:
        raise ValueError('Ordered same-episode actual features required')
    for o in [previous,current]:
        if o['camera_calibration']['step_id']!=o['step_id']:
            raise ValueError('Public calibration must match its actual RGB step')
    old_uv,new_uv=np.asarray(old_uv,float),np.asarray(new_uv,float)
    if old_uv.shape!=new_uv.shape or old_uv.ndim!=2 or old_uv.shape[1]!=2 or len(old_uv)<6:
        raise ValueError('At least6 actual two-frame matched pixels required')
    if not np.isfinite(old_uv).all() or not np.isfinite(new_uv).all():
        raise ValueError('Finite actual feature coordinates required')
    a,b=[o['camera_calibration']['cameras'][camera] for o in [previous,current]]
    ka,kb=np.asarray(a['intrinsic'],float),np.asarray(b['intrinsic'],float)
    ta,tb=np.asarray(a['camera_to_environment'],float),np.asarray(b['camera_to_environment'],float)
    ray=np.column_stack(((old_uv[:,0]-ka[0,2])/ka[0,0],-(old_uv[:,1]-ka[1,2])/ka[1,1],-np.ones(len(old_uv))))
    ray=ray@ta[:3,:3].T;ray/=np.linalg.norm(ray,axis=1,keepdims=True)
    depths=np.linspace(.2,2.,37)
    points=ta[:3,3]+ray[:,None,:]*depths[None,:,None]
    e0,e1=[eef_transform(o['current_eef']['right']) for o in [previous,current]]
    change=e1@np.linalg.inv(e0)
    moved=points@change[:3,:3].T+change[:3,3]
    def project(p):
        local=(p-tb[:3,3])@tb[:3,:3]
        depth=-local[:,:,2]
        uv=np.stack((kb[0,2]+kb[0,0]*local[:,:,0]/depth,
                     kb[1,2]-kb[1,1]*local[:,:,1]/depth),axis=-1)
        uv[depth<=0]=np.nan
        return uv
    static,following=project(points),project(moved)
    static_error=np.linalg.norm(static-new_uv[:,None,:],axis=2)
    following_error=np.linalg.norm(following-new_uv[:,None,:],axis=2)
    if np.any(~np.isfinite(static_error).any(1)) or np.any(~np.isfinite(following_error).any(1)):
        raise ValueError('No positive-depth hypothesis for an actual feature')
    flow=following-old_uv[:,None,:]
    separating=np.linalg.norm(following-static,axis=2)
    translation=float(np.linalg.norm(e1[:3,3]-e0[:3,3]))
    angle=float(Rotation.from_matrix(change[:3,:3]).magnitude())
    return {'actual_matched_features':len(old_uv),'previous_step_id':previous['step_id'],'current_step_id':current['step_id'],
        'hypothesis_ray_distance_domain_m':[.2,2.],'sample_step_m':.05,
        'camera_axis_convention':'render ray [u/fx,-v/fy,-1], positive optical depth=-render_z',
        'observed_robot_translation_mm':round(translation*1000,3),'observed_robot_rotation_rad':round(angle,6),
        'robot_motion_informative_for_test':bool(translation>=.001 or angle>=.005),
        'median_static_world_reprojection_residual_px':round(float(np.median(np.nanmin(static_error,1))),4),
        'median_min_rigid_tool_following_reprojection_residual_px':round(float(np.median(np.nanmin(following_error,1))),4),
        'median_min_hypothesis_pixel_separation_px':round(float(np.median(np.nanmin(separating,1))),4),
        'rigid_following_pixel_flow_component_min_max':np.stack((np.nanmin(flow,axis=(0,1)),np.nanmax(flow,axis=(0,1)))).round(3).tolist(),
        'meaning':'Compare observed SAME-feature pixels against explanations of the PAST measured robot motion: static source versus source rigidly following the measured tool. Smaller residual favours that image hypothesis only within the declared sampled depth domain. Depth is NOT estimated or true object XYZ. Uninformative robot motion or overlapping projected hypotheses cannot establish following. Source rotation/slip relative to fingers, reflections, incorrect material feature identity and unknown calibration systematics can invalidate rigid following without proving an empty hand. No holding/contact/height truth, success probability or new action recommendation. Inspect actual current RGB and fingers.'}
