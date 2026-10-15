"""Conditional partial RGB cuboid fit with explicit within-episode geometry prior.

This local sensitivity estimator is not interval branch-and-bound or a certified
worst-case set. Missing silhouette portions never count as measured edges.
"""
import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull
from rgb_cuboid import vertices,project
from cap_motion import tool_mask


def fit_partial(public,name,views,camera_names,prior,models,support_z=None):
    center=np.asarray(prior['center_m']);size=np.asarray(prior['size_m'])
    records=[];families=[]
    for (camera,material),camera_name in zip(views,camera_names):
        occlusion=tool_mask(public,camera_name)
        _,own_depth=project(camera,center.reshape(1,3))
        for other,model in models.items():
            if other==name or not model.get('usable') or model.get('step')!=public['step']:
                continue
            uv,depth=project(camera,vertices(np.r_[model['center_m'],model['size_m'],model['yaw_rad']]))
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
        angles=[] if lines is None else [np.arctan2(y2-y1,x2-x1)%np.pi for x1,y1,x2,y2 in lines[:,0]]
        independent=any(abs(np.sin(a-b))>.25 for a in angles for b in angles)
        families.append(dict(camera=camera_name,pixels=len(pixels),two_edge_directions=independent))
        pixels=pixels[np.linspace(0,len(pixels)-1,min(100,len(pixels))).astype(int)].astype(float)
        records.append((camera,pixels))
    if not records or (len(records)<2 and not any(f['two_edge_directions'] for f in families)):
        return dict(usable=False,reason='Partial fit lacks two independent visible edge families',edge_families=families)
    initial=np.r_[center,prior['yaw_rad']]
    extent=np.r_[np.full(3,.012 if support_z is not None else .030),.20]
    lower=initial-extent;upper=initial+extent

    def residual(p,perturb=0.):
        shape=size+perturb
        world=vertices(np.r_[p[:3],shape,p[3]])
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
            rows.append((p[2]-shape[2]/2-support_z)*1000)
        return np.asarray(rows)

    solutions=[]
    for yaw in (-.10,0.,.10):
        start=initial.copy();start[3]+=yaw
        solution=least_squares(residual,start,bounds=(lower,upper),loss='soft_l1',f_scale=2.,max_nfev=60)
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
    usable=bool(rank==4 and rms<3.5 and max(width)<.012 and restart_spread<.003 and interior)
    p=result.x
    return dict(status='fitted_visual_hypothesis',usable=usable,center_m=p[:3].tolist(),size_m=size.tolist(),
        yaw_rad=float(p[3]),bottom_z_m=float(p[2]-size[2]/2),top_z_m=float(p[2]+size[2]/2),
        conditional_center_halfwidth_m=width.tolist(),conditional_size_halfwidth_m=prior.get('conditional_size_halfwidth_m'),
        silhouette_rmse_px=rms,jacobian_rank=rank,interior_solution=interior,restart_center_spread_m=restart_spread,
        edge_families=families,camera_names=[f['camera'] for f in families],step=public['step'],
        provenance='CURRENT_PARTIAL_WITH_STATIONARY_PRIOR' if support_z is not None else 'CURRENT_PARTIAL_DYNAMIC',
        prior_step=prior.get('step'),support_z_hypothesis_m=support_z,
        source='Current unoccluded material edges plus earlier same-episode RGB dimensions; public robot/held-object projections',
        limits='Local conditional fit,2mm size/shape sensitivity and optional stationary-flat-support hypothesis; not a full current silhouette, calibrated confidence, exact interval set or contact evidence')
