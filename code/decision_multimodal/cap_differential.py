"""Same-episode RGB rim-template travel under a vertical-cap hypothesis."""
import cv2
import numpy as np
from scipy.optimize import least_squares
from rgb_cuboid import project,ray
from cap_motion import tool_mask


def upper_arc(public,mask,cap,camera):
    rgb=public['rgb'][camera].astype(float);r,g,b=rgb.transpose(2,0,1)
    chroma=((r>80)&(r>1.25*g)&(r>1.25*b)) if cap.get('color','red')=='red' else ((b>80)&(b>1.25*r)&(b>1.25*g))
    contours,_=cv2.findContours((mask&chroma).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    if not contours:
        return np.empty((0,2))
    pixels=max(contours,key=cv2.contourArea).reshape(-1,2).astype(float)
    center=np.asarray(cap['center_m']);vertical,_=project(public['calibration'][camera],np.stack([center,center+[0,0,.01]]))
    up=vertical[1]-vertical[0];up/=np.linalg.norm(up)
    pixels=pixels[pixels@up>=np.quantile(pixels@up,.55)]
    hand=tool_mask(public,camera);index=pixels.astype(int)
    return pixels[hand[index[:,1],index[:,0]]==0]


def measure(public,baseline,mask,baseline_mask,cap,camera,baseline_z):
    before=upper_arc(baseline,baseline_mask,cap,camera);now=upper_arc(public,mask,cap,camera)
    if len(before)<12 or len(now)<12:
        return dict(usable=False,reason='Insufficient independent baseline/current rim-template arc')
    points=[]
    for pixel in before:
        origin,direction=ray(baseline['calibration'][camera],pixel)
        points.append(origin+direction*((baseline_z-origin[2])/direction[2]))
    points=np.asarray(points)
    def residual(value,shift=np.zeros(2)):
        moved=points+[0,0,float(value[0])]
        predicted,depth=project(public['calibration'][camera],moved)
        distance=np.linalg.norm((now+shift)[:,None]-predicted[None,:],axis=2)
        return ((now+shift)-predicted[distance.argmin(1)]).ravel()
    results=[]
    for start in (-.018,-.010,-.002):
        fit=least_squares(residual,[start],bounds=([-.025],[.005]),loss='soft_l1',f_scale=1.,max_nfev=80)
        results.append(fit)
    best=min(results,key=lambda fit:np.mean(residual(fit.x)**2))
    rms=float(np.sqrt(np.mean(residual(best.x)**2)));sensitivity=.002
    for shift in ([1,0],[-1,0],[0,1],[0,-1]):
        fit=least_squares(lambda h:residual(h,np.asarray(shift)),best.x,bounds=([-.025],[.005]),loss='soft_l1',f_scale=1.,max_nfev=80)
        sensitivity=max(sensitivity,float(abs(fit.x[0]-best.x[0])))
    interior=bool(-.0245<best.x[0]<.0045)
    return dict(usable=bool(rms<2. and sensitivity<.008 and interior),downward_displacement_m=float(-best.x[0]),
        conditional_travel_halfwidth_m=sensitivity,rim_template_rms_px=rms,baseline_arc_pixels=len(before),current_arc_pixels=len(now),
        camera_names=[camera],baseline_step=baseline['step'],step=public['step'],
        source='Current independent RGB rim matched to a same-episode unpressed RGB upper-arc template; public K/T',
        limits='Vertical rigid-cap and baseline rim-plane hypotheses; no radius, object state or contact truth.1px differential perturbation is conditional sensitivity, not calibrated confidence.')
