"""Visible cap travel from RGB rim arcs with public robot occlusion masking."""
import cv2
import numpy as np
from scipy.optimize import minimize_scalar
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
    mask=color_component(rgb,'red',uv[0])
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
