"""Horizontal bowl-rim hypotheses from upper silhouette arcs in calibrated RGB."""
import cv2
import numpy as np
from scipy.optimize import least_squares
from rgb_cuboid import project,ray


def white_region(rgb,box,seed):
    x=np.asarray(rgb,float);white=(x.min(2)>135)&(np.ptp(x,axis=2)<40)
    x0,y0,x1,y1=np.asarray(box).round().astype(int);region=np.zeros(white.shape,bool)
    region[max(0,y0-4):min(len(region),y1+5),max(0,x0-4):min(region.shape[1],x1+5)]=True
    count,labels,stats,centers=cv2.connectedComponentsWithStats((white&region).astype(np.uint8))
    choices=[(np.linalg.norm(centers[i]-seed),i) for i in range(1,count) if stats[i,4]>50]
    if not choices:
        return None
    return (labels==min(choices)[1]).astype(np.uint8)


def fit(public,seeds,table_z,prior=None):
    views=[];masks={}
    high=seeds['cam_high'];camera=public['calibration']['cam_high']
    origin,direction=ray(camera,high['center'])
    nominal=origin+direction*((table_z+.04-origin[2])/direction[2])
    if prior is not None:
        nominal=np.asarray(prior['center_m'])
    radius_guess=None
    for name,seed in seeds.items():
        rgb=public['rgb'][name];camera=public['calibration'][name]
        mask=white_region(rgb,seed['box'],seed.get('aperture_center',seed.get('center')))
        if mask is None:
            continue
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
        pixels=max(contours,key=cv2.contourArea).reshape(-1,2).astype(float)
        uv,depth=project(camera,np.stack([nominal,nominal+[0,0,.01]]))
        up=uv[1]-uv[0];up/=np.linalg.norm(up)
        coordinate=pixels@up
        selected=pixels[coordinate>=np.quantile(coordinate,.55)]
        if len(selected)<12:
            continue
        views.append((name,selected));masks[name]=mask
        if name=='cam_high':
            radius_guess=float(np.ptp(pixels[:,0])*.5*depth[0]/camera['intrinsic'][0][0])
    if len(views)<2 or radius_guess is None:
        return dict(usable=False,reason='Bowl rim requires two associated current upper arcs'),masks
    theta=np.linspace(0,2*np.pi,360,endpoint=False);unit=np.column_stack([np.cos(theta),np.sin(theta),np.zeros(len(theta))])
    lower=np.r_[nominal[:2]-.10,table_z+.002,.45*radius_guess]
    upper=np.r_[nominal[:2]+.10,table_z+.20,1.6*radius_guess]
    def residual(p,offset=0.):
        points=p[:3]+p[3]*unit;values=[]
        for name,pixels in views:
            predicted,_=project(public['calibration'][name],points)
            observed=pixels+offset
            distance=np.linalg.norm(observed[:,None]-predicted[None,:],axis=2)
            values.extend((observed-predicted[distance.argmin(1)]).ravel())
        return np.asarray(values)
    candidates=[]
    for dz in (.020,.055,.100):
        for radius_scale in (.8,1.,1.2):
            initial=np.r_[nominal[:2],table_z+dz,radius_guess*radius_scale]
            result=least_squares(residual,np.clip(initial,lower+1e-5,upper-1e-5),bounds=(lower,upper),loss='soft_l1',f_scale=1.5,max_nfev=100)
            candidates.append((float(np.mean(residual(result.x)**2)),result))
    _,result=min(candidates,key=lambda row:row[0]);rms=float(np.sqrt(np.mean(residual(result.x)**2)))
    covariance=np.linalg.pinv(result.jac.T@result.jac)*max(1.,rms)**2
    sensitivity=np.maximum(.002,3*np.sqrt(np.maximum(0,np.diag(covariance))))
    perturbations=[]
    for shift in (-3.,3.):
        changed=least_squares(lambda p:residual(p,shift),result.x,bounds=(lower,upper),loss='soft_l1',f_scale=1.5,max_nfev=100)
        perturbations.append(changed.x-result.x)
    sensitivity=np.maximum(sensitivity,np.max(abs(np.asarray(perturbations)),axis=0))
    interior=bool(min(np.min(result.x-lower),np.min(upper-result.x))>.0005)
    rank=int(np.linalg.matrix_rank(result.jac))
    return dict(usable=bool(rms<2.5 and max(sensitivity[:3])<.015 and sensitivity[3]<.012 and interior and rank==4),
        center_m=result.x[:3].tolist(),radius_m=float(result.x[3]),rim_rms_px=rms,
        sensitivity_xyz_radius_m=sensitivity.tolist(),camera_names=[name for name,_ in views],
        rim_pixels={name:len(pixels) for name,pixels in views},upper_arc_pixels={name:pixels.tolist() for name,pixels in views},
        interior_solution=interior,jacobian_rank=rank,
        source='Upper45percent of associated RGB white silhouette contours and public calibrated circle projection',
        limits='Horizontal circular rim and upper-silhouette arc identity are hypotheses. Not cavity depth, wall thickness, contact or object truth. Sensitivity is conditional, not a calibrated confidence interval.'),masks
