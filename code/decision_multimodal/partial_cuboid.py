"""Conditional partial RGB cuboid fit with explicit within-episode geometry prior.

This local sensitivity estimator is not interval branch-and-bound or a certified
worst-case set. Missing silhouette portions never count as measured edges.
"""
import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation
from rgb_cuboid import vertices,project,model_vertices
from cap_motion import tool_mask


def fit_partial(public,name,views,camera_names,prior,models,support_z=None,extra_occlusion=None,straight_only=False):
    center=np.asarray(prior['center_m']);size=np.asarray(prior['size_m'])
    records=[];families=[]
    for (camera,material),camera_name in zip(views,camera_names):
        occlusion=tool_mask(public,camera_name)
        if extra_occlusion and camera_name in extra_occlusion:
            # Current foreground-object SAM silhouettes, not their fitted
            # world poses, can explain a T-junction occlusion boundary.
            observed=np.asarray(extra_occlusion[camera_name],np.uint8)*255
            occlusion=np.maximum(occlusion,cv2.dilate(observed,np.ones((7,7),np.uint8)))
        _,own_depth=project(camera,center.reshape(1,3))
        for other,model in models.items():
            if other==name or not model.get('usable') or model.get('step')!=public['step']:
                continue
            uv,depth=project(camera,model_vertices(model))
            if min(depth)>.01 and depth.mean()<own_depth[0] and np.max(abs(uv))<10000:
                cv2.fillConvexPoly(occlusion,uv[ConvexHull(uv).vertices].round().astype(np.int32),255)
        occlusion=cv2.dilate(occlusion,np.ones((5,5),np.uint8))
        contours,_=cv2.findContours(material.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue
        pixels=max(contours,key=cv2.contourArea).reshape(-1,2)
        pixels=pixels[occlusion[pixels[:,1],pixels[:,0]]==0]
        if len(pixels)<12:
            continue
        edge=np.zeros(material.shape,np.uint8);edge[pixels[:,1],pixels[:,0]]=255
        lines=cv2.HoughLinesP(edge,1,np.pi/180,threshold=8,minLineLength=12,maxLineGap=2)
        if straight_only:
            if lines is None:
                continue
            keep=np.zeros(len(pixels),bool)
            for x1,y1,x2,y2 in lines[:,0]:
                a=np.array([x1,y1]);b=np.array([x2,y2]);segment=b-a
                t=np.clip((pixels-a)@segment/(segment@segment+1e-12),0,1)
                keep|=np.linalg.norm(pixels-a-t[:,None]*segment,axis=1)<=1.5
            pixels=pixels[keep]
            if len(pixels)<12:
                continue
        angles=[] if lines is None else [np.arctan2(y2-y1,x2-x1)%np.pi for x1,y1,x2,y2 in lines[:,0]]
        independent=any(abs(np.sin(a-b))>.25 for a in angles for b in angles)
        families.append(dict(camera=camera_name,pixels=len(pixels),two_edge_directions=independent))
        pixels=pixels[np.linspace(0,len(pixels)-1,min(100,len(pixels))).astype(int)].astype(float)
        records.append((camera,pixels))
    if not records or (len(records)<2 and not any(f['two_edge_directions'] for f in families)):
        return dict(usable=False,reason='Partial fit lacks two independent visible edge families',edge_families=families)
    base_rotation=(Rotation.from_rotvec(prior['rotation_vector_world_rad']) if prior.get('rotation_vector_world_rad') is not None
        else Rotation.from_euler('z',prior['yaw_rad']))
    signs=np.array([[x,y,z] for x in (-.5,.5) for y in (-.5,.5) for z in (-.5,.5)])
    initial=np.r_[center,np.zeros(3)]
    extent=np.r_[np.full(3,.012 if support_z is not None else .030),np.full(3,.35)]
    lower=initial-extent;upper=initial+extent

    def residual(p,perturb=0.):
        shape=size+perturb
        rotation=Rotation.from_rotvec(p[3:])*base_rotation
        world=rotation.apply(signs*shape)+p[:3]
        rows=[]
        for camera,pixels in records:
            uv,_=project(camera,world)
            polygon=uv[ConvexHull(uv).vertices]
            nearest=np.empty_like(pixels);best=np.full(len(pixels),np.inf)
            for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
                segment=b-a
                t=np.clip(((pixels-a)@segment)/(segment@segment+1e-12),0,1)
                projected=a+t[:,None]*segment
                distance=np.linalg.norm(pixels-projected,axis=1)
                chosen=distance<best;nearest[chosen]=projected[chosen];best[chosen]=distance[chosen]
            rows.extend((pixels-nearest).ravel())
        if support_z is not None:
            rows.append((world[:,2].min()-support_z)*1000)
        return np.asarray(rows)

    solutions=[]
    starts=[initial.copy()]
    for axis in range(3):
        for sign in (-1,1):
            start=initial.copy();start[3+axis]=sign*.15;starts.append(start)
    for start in starts:
        solution=least_squares(residual,start,bounds=(lower,upper),loss='soft_l1',f_scale=1.5,max_nfev=60)
        solutions.append(solution)
    result=min(solutions,key=lambda r:np.mean(residual(r.x)**2))
    rms=float(np.sqrt(np.mean(residual(result.x)**2)))
    covariance=np.linalg.pinv(result.jac.T@result.jac)*max(1.,rms)**2
    rank=int(np.linalg.matrix_rank(result.jac))
    alternatives=[]
    for perturb in (-.002,.002):
        solved=least_squares(lambda p:residual(p,perturb),result.x,bounds=(lower,upper),loss='soft_l1',f_scale=2.,max_nfev=40)
        alternatives.append(solved.x[:3])
    width=2*np.sqrt(np.maximum(0,np.diag(covariance)[:3]))+.002
    width+=np.max(abs(np.asarray(alternatives)-result.x[:3]),axis=0)
    restart_spread=float(np.max(np.ptp([r.x[:3] for r in solutions],axis=0)))
    interior=bool(np.min(result.x-lower)>.0001 and np.min(upper-result.x)>.0001)
    rotation_width=2*np.sqrt(np.maximum(0,np.diag(covariance)[3:]))+.02
    usable=bool(rank==6 and rms<3.5 and max(width)<.012 and max(rotation_width)<.25 and restart_spread<.003 and interior)
    p=result.x
    rotation=Rotation.from_rotvec(p[3:])*base_rotation
    world=rotation.apply(signs*size)+p[:3]
    height_width=float(width[2]+np.linalg.norm(size/2)*min(1.,np.linalg.norm(rotation_width)))
    return dict(status='fitted_visual_hypothesis',usable=usable,center_m=p[:3].tolist(),size_m=size.tolist(),
        yaw_rad=float(rotation.as_euler('xyz')[2]),rotation_vector_world_rad=rotation.as_rotvec().tolist(),
        bottom_z_m=float(world[:,2].min()),top_z_m=float(world[:,2].max()),
        conditional_rotation_halfwidth_rad=rotation_width.tolist(),conditional_bottom_top_halfwidth_m=height_width,
        conditional_center_halfwidth_m=width.tolist(),conditional_size_halfwidth_m=prior.get('conditional_size_halfwidth_m'),
        silhouette_rmse_px=rms,jacobian_rank=rank,interior_solution=interior,restart_center_spread_m=restart_spread,
        edge_families=families,camera_names=[f['camera'] for f in families],step=public['step'],
        provenance='CURRENT_PARTIAL_WITH_STATIONARY_PRIOR' if support_z is not None else 'CURRENT_PARTIAL_DYNAMIC',
        prior_step=prior.get('step'),support_z_hypothesis_m=support_z,
        extra_RGB_foreground_occlusion=bool(extra_occlusion),straight_silhouette_segments_only=bool(straight_only),
        source='Current unoccluded material edges plus earlier same-episode RGB dimensions; public robot/held-object projections',
        limits='Local conditional fit,2mm size/shape sensitivity and optional stationary-flat-support hypothesis; not a full current silhouette, calibrated confidence, exact interval set or contact evidence')
