"""A horizontal circular cap/rim hypothesis fitted to calibrated RGB contours."""
import cv2
import numpy as np
from scipy.optimize import least_squares
from rgb_cuboid import project, ray


def color_component(rgb, color, uv):
    r,g,b=rgb.astype(float).transpose(2,0,1)
    # Brown table texture also has R>G and R>B. The bright cap top is
    # substantially brighter; including the table joins the entire image.
    binary=((r>205)&(r>g*1.5)&(r>b*1.5)) if color=='red' else ((b>130)&(b>r*1.5)&(b>g*1.3))
    n,labels,stats,centers=cv2.connectedComponentsWithStats(binary.astype(np.uint8))
    items=[]
    for i in range(1,n):
        if stats[i,4]<12:
            continue
        distance=np.linalg.norm(centers[i]-uv)
        if distance<80:
            items.append((stats[i,4]/(1+distance),i))
    return (labels==max(items)[1]).astype(np.uint8) if items else None


def fit_cap(public,high_pixel,color,table_z,prior=None):
    high=public['calibration']['cam_high']
    origin,direction=ray(high,high_pixel)
    point=origin+direction*((table_z+.010-origin[2])/direction[2]) if prior is None else np.asarray(prior['center_m'])
    views=[]
    for name,rgb in public['rgb'].items():
        camera=public['calibration'][name]
        uv,depth=project(camera,point.reshape(1,3))
        if depth[0]<=0:
            continue
        mask=color_component(rgb,color,np.asarray(high_pixel) if name=='cam_high' and prior is None else uv[0])
        if mask is None or mask[:5].any() or mask[-5:].any() or mask[:,:5].any() or mask[:,-5:].any():
            continue
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
        contour=max(contours,key=cv2.contourArea).reshape(-1,2).astype(float)
        contour=contour[np.linspace(0,len(contour)-1,min(160,len(contour))).astype(int)]
        views.append((name,camera,contour))
    if len(views)<2:
        return dict(usable=False,reason='Circular RGB fit needs two uncropped current views',camera_names=[n for n,_,_ in views])
    angle=np.linspace(0,2*np.pi,160,endpoint=False)
    def residual(p):
        circle=p[:3]+p[3]*np.column_stack([np.cos(angle),np.sin(angle),np.zeros(len(angle))])
        rows=[]
        for _,camera,contour in views:
            uv,_=project(camera,circle)
            distances=np.linalg.norm(uv[:,None,:]-contour[None,:,:],axis=2)
            rows.extend(distances.min(0));rows.extend(distances.min(1))
        return np.asarray(rows)
    initial=np.r_[point,.018 if prior is None else prior['radius_m']]
    lower=np.r_[point[:2]-.06,table_z+.001,.005]
    upper=np.r_[point[:2]+.06,table_z+.070,.045]
    result=least_squares(residual,np.clip(initial,lower+1e-6,upper-1e-6),bounds=(lower,upper),loss='soft_l1',f_scale=2.)
    rms=float(np.sqrt(np.mean(residual(result.x)**2)))
    cov=np.linalg.pinv(result.jac.T@result.jac)*max(1.,rms)**2
    halfwidth=np.maximum(.002,2*np.sqrt(np.maximum(0,np.diag(cov)[:3])))
    return dict(usable=bool(rms<3. and max(halfwidth)<.008),center_m=result.x[:3].tolist(),radius_m=float(result.x[3]),
        contour_rms_px=rms,conditional_halfwidth_m=halfwidth.tolist(),camera_names=[n for n,_,_ in views],
        source='Current color cap boundary and public K/T under horizontal circular top hypothesis',
        limits='Full color silhouette includes cap sidewall; height may be biased. Not contact, depression, electrical actuation or object truth.')
