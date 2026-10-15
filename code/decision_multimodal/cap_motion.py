"""Visible cap travel from RGB rim arcs with public robot occlusion masking."""
import cv2
import numpy as np
from scipy.optimize import minimize_scalar,least_squares
from rgb_cuboid import project
from rgb_circle import color_component
from robot_tool import Tool
from robodojo_episode import transform


def tool_mask(public,camera):
    tools=Tool();shape=public['rgb'][camera].shape[:2]
    mask=np.zeros(shape,np.uint8)
    for i,arm in enumerate(('left','right')):
        pose=transform(public['robot']['eef_positions'][i],public['robot']['eef_quaternions_wxyz'][i])
        triangles=tools.local_triangles(public,arm)
        world=triangles@pose[:3,:3].T+pose[:3,3]
        pixels,depth=project(public['calibration'][camera],world.reshape(-1,3))
        pixels=pixels.reshape(-1,3,2);depth=depth.reshape(-1,3)
        for triangle,z in zip(pixels,depth):
            if min(z)<=.01 or not np.isfinite(triangle).all() or np.max(abs(triangle))>10000:
                continue
            cv2.fillConvexPoly(mask,triangle.round().astype(np.int32),255)
    return cv2.dilate(mask,np.ones((7,7),np.uint8))


def cap_height(public,cap,camera='cam_high'):
    calibration=public['calibration'][camera];rgb=public['rgb'][camera]
    center=np.asarray(cap['center_m']);uv,_=project(calibration,center.reshape(1,3))
    k=np.asarray(calibration['intrinsic']);_,depth=project(calibration,center.reshape(1,3))
    distance=max(12.,1.8*k[0,0]*cap['radius_m']/depth[0])
    mask=color_component(rgb,'red',uv[0],max_distance=distance)
    if mask is None:
        return dict(usable=False,reason='No current red cap region')
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    pixels=max(contours,key=cv2.contourArea).reshape(-1,2).astype(float)
    hand=tool_mask(public,camera)
    indices=pixels.astype(int)
    pixels=pixels[hand[indices[:,1],indices[:,0]]==0]
    if len(pixels)<12:
        return dict(usable=False,reason='Insufficient unoccluded cap rim arc',rim_pixels=len(pixels))
    angles=np.linspace(0,2*np.pi,360,endpoint=False)
    circle=np.column_stack([cap['radius_m']*np.cos(angles),cap['radius_m']*np.sin(angles),np.zeros(len(angles))])+center
    def error(z):
        current=circle.copy();current[:,2]=z
        model,_=project(calibration,current)
        distances=np.linalg.norm(pixels[:,None,:]-model[None,:,:],axis=2).min(1)
        return distances
    fitted=minimize_scalar(lambda z:float(np.mean(np.minimum(error(z)**2,25.))),
        bounds=(center[2]-.022,center[2]+.008),method='bounded',options={'xatol':.00002})
    rms=float(np.sqrt(np.mean(error(fitted.x)**2)))
    return dict(usable=bool(rms<3.),height_m=float(fitted.x),rim_rms_px=rms,rim_pixels=len(pixels),
        source='Current fixed-camera cap rim arcs, public finger/palm occlusion mask, initial RGB circle radius/XY',
        limits='Vertical-spring and rigid-circle hypotheses; incomplete arcs can bias travel. No joint/contact/electrical state.')


def cap_pose(public,cap,material_masks=None,upper_arc=False):
    """Refit cap translation using a previously RGB-measured radius."""
    center=np.asarray(cap['center_m']);views=[];color=cap.get('color','red')
    for camera,rgb in public['rgb'].items():
        calibration=public['calibration'][camera]
        uv,depth=project(calibration,center.reshape(1,3))
        if depth[0]<=0:
            continue
        k=np.asarray(calibration['intrinsic'])
        radius_px=k[0,0]*cap['radius_m']/depth[0]
        if material_masks is not None:
            if camera not in material_masks:
                continue
            r,g,b=rgb.astype(float).transpose(2,0,1)
            chroma=((r>80)&(r>1.25*g)&(r>1.25*b)) if color=='red' else ((b>80)&(b>1.25*r)&(b>1.25*g))
            mask=(np.asarray(material_masks[camera],bool)&chroma).astype(np.uint8)
        else:
            mask=color_component(rgb,color,uv[0],max_distance=max(12.,1.8*radius_px))
        if mask is None:
            continue
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
        pixels=max(contours,key=cv2.contourArea).reshape(-1,2).astype(float)
        if upper_arc:
            # Select a top/back arc before removing projected finger pixels.
            # The front colored sidewall is not part of a horizontal top rim.
            vertical,_=project(calibration,np.stack([center,center+[0,0,.01]]))
            up=vertical[1]-vertical[0];up/=np.linalg.norm(up)
            coordinate=pixels@up
            pixels=pixels[coordinate>=np.quantile(coordinate,.55)]
        hand=tool_mask(public,camera);index=pixels.astype(int)
        pixels=pixels[hand[index[:,1],index[:,0]]==0]
        if len(pixels)>=12:
            if upper_arc:
                # A close pressing wrist must not dominate an independent
                # observer merely by providing more contour pixels.
                pixels=pixels[np.linspace(0,len(pixels)-1,min(80,len(pixels))).astype(int)]
            views.append((camera,pixels))
    if not views:
        return dict(usable=False,reason='No unoccluded associated cap rim')
    angles=np.linspace(0,2*np.pi,360,endpoint=False)
    offsets=cap['radius_m']*np.column_stack([np.cos(angles),np.sin(angles),np.zeros(len(angles))])
    def residual(p):
        values=[]
        for name,pixels in views:
            model,_=project(public['calibration'][name],offsets+p)
            distance=np.linalg.norm(pixels[:,None,:]-model[None,:,:],axis=2)
            values.extend((pixels-model[distance.argmin(1)]).ravel())
        return np.asarray(values)
    lower=center+[-.008,-.008,-.022];upper=center+[.008,.008,.008]
    result=least_squares(residual,center,bounds=(lower,upper),loss='soft_l1',f_scale=2.,max_nfev=80)
    rms=float(np.sqrt(np.mean(residual(result.x)**2)))
    cov=np.linalg.pinv(result.jac.T@result.jac)*max(1.,rms)**2
    width=np.maximum(.002,2*np.sqrt(np.maximum(0,np.diag(cov))))
    rank=int(np.linalg.matrix_rank(result.jac))
    interior=bool(min(np.min(result.x-lower),np.min(upper-result.x))>.0002)
    return dict(usable=bool(rms<3. and max(width)<.008 and rank==3 and interior),center_m=result.x.tolist(),
        downward_displacement_m=float(center[2]-result.x[2]),rim_rms_px=rms,
        jacobian_rank=rank,interior_solution=interior,
        conditional_halfwidth_m=width.tolist(),camera_names=[n for n,_ in views],
        rim_pixel_counts={n:len(p) for n,p in views},
        rim_method='upper45percent_balanced_views' if upper_arc else 'full_associated_contours',
        source='Current associated rim arcs minus public robot occlusion; horizontal cap and previously RGB-measured radius',
        limits='Radius/base/vertical-spring hypotheses; local sensitivity excludes unknown radius and calibration biases. No contact, joint or electrical state.')
