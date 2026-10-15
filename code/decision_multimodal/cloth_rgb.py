"""Supported garment landmarks and visible deformation, from RGB only."""
import cv2
import numpy as np
from rgb_cuboid import ray, project
from cap_motion import tool_mask


def garment(rgb):
    r,g,b=np.asarray(rgb,float).transpose(2,0,1)
    # Coral has nearly equal G/B; the brown tabletop is also red-dominant
    # but has a much larger green-minus-blue difference.
    mask=((r>35)&(g<.62*r)&(b>.90*g)&(g-b<9)&(r>1.4*b)).astype(np.uint8)
    mask[:120]=0;mask[390:]=0;mask[:,:110]=0;mask[:,515:]=0
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    out=np.zeros_like(mask)
    for i in range(1,count):
        if stats[i,cv2.CC_STAT_AREA]>=50:
            out[labels==i]=1
    return out


def supported(camera,uv,z):
    origin,direction=ray(camera,uv)
    distance=(z-origin[2])/direction[2]
    if distance<=0:
        raise ValueError('Supported garment point is behind camera')
    return origin+direction*distance


def landmark(public,seed,z,kind='cuff'):
    """Refine the declared semantic edge, not an arbitrary mask centroid."""
    rgb=public['rgb']['cam_high'];mask=garment(rgb)
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    if not contours:
        return dict(usable=False,reason='No current garment contour')
    points=np.concatenate(contours).reshape(-1,2).astype(float)
    x0,y0,x1,y1=seed['roi'];roi=points[(points[:,0]>=x0)&(points[:,0]<=x1)&(points[:,1]>=y0)&(points[:,1]<=y1)]
    if len(roi)<6:
        return dict(usable=False,reason='Semantic garment edge unavailable in its ROI')
    uv=np.asarray(seed['seed'],float);results=[]
    if kind=='cuff':
        endpoints=np.asarray(seed['edge_endpoints'],float)
        axis=endpoints[1]-endpoints[0];axis/=np.linalg.norm(axis)
        normal=np.array([-axis[1],axis[0]])
        delta=roi-endpoints.mean(0)
        region=roi[(abs(delta@normal)<5)&(abs(delta@axis)<np.linalg.norm(endpoints[1]-endpoints[0])*.6)]
        if len(region)<6:
            return dict(usable=False,reason='Declared cuff cut-edge not resolved')
        for shift in ([0,0],[2,0],[-2,0],[0,2],[0,-2]):
            center=uv+shift
            selected=region[abs((region-center)@axis)<18]
            if len(selected)<6:
                return dict(usable=False,reason='Insufficient declared cuff edge support at a refinement start')
            # Median signed line offset is robust to a few side-edge pixels.
            value=np.median((selected-endpoints.mean(0))@normal)
            results.append(endpoints.mean(0)+value*normal)
    else:
        # A hem corner is a locally convex contour landmark near its seed.
        candidates=[]
        for contour in contours:
            polygon=cv2.approxPolyDP(contour,2.,True).reshape(-1,2)
            candidates.extend([p for p in polygon if x0<=p[0]<=x1 and y0<=p[1]<=y1])
        if not candidates:
            return dict(usable=False,reason='Declared hem corner not resolved')
        candidates=np.asarray(candidates,float)
        for shift in ([0,0],[2,0],[-2,0],[0,2],[0,-2]):
            results.append(candidates[np.linalg.norm(candidates-uv-shift,axis=1).argmin()])
        yy,xx=np.nonzero(mask);normal=np.array([xx.mean(),yy.mean()])-results[0]
        normal/=np.linalg.norm(normal);axis=np.array([-normal[1],normal[0]])
    results=np.asarray(results);uv=np.median(results,axis=0)
    spread=float(np.linalg.norm(results[:,None]-results[None,:],axis=2).max())
    camera=public['calibration']['cam_high'];edge=supported(camera,uv,z)
    direction=supported(camera,uv+normal*3,z)-edge;direction[2]=0;direction/=np.linalg.norm(direction)
    yy,xx=np.nonzero(mask);centroid=supported(camera,[xx.mean(),yy.mean()],z)
    if np.dot(direction,centroid-edge)<0:
        direction=-direction;normal=-normal
    source=edge+direction*.008
    sensitivity=[]
    for du in (-3,0,3):
        for dv in (-3,0,3):
            for dz in (-.002,0,.002):
                sensitivity.append(np.linalg.norm((supported(camera,uv+[du,dv],z+dz)-edge)[:2]))
    uncertainty=float(max(sensitivity))
    inside_uv,_=project(camera,source.reshape(1,3));u,v=inside_uv[0].round().astype(int)
    inside=bool(0<=v<mask.shape[0] and 0<=u<mask.shape[1] and mask[v,u])
    return dict(usable=bool(spread<=3 and uncertainty<=.015 and inside),edge_pixel=uv.tolist(),
        refinement_points=results.tolist(),refinement_spread_px=spread,source_m=source.tolist(),
        inward_normal_world=direction.tolist(),source_uncertainty_m=uncertainty,inside_garment=inside,
        supported_hypothesis=True,source='Current high RGB semantic boundary and public ray/table intersection',
        limits='Visible flat support is a hypothesis; not a measured cloth 3D pose. Sensitivity is conditional, not a calibrated confidence interval.')


def deformation(public,baseline_rgb,source_uv):
    current=public['rgb']['cam_high'];initial=garment(baseline_rgb);mask=garment(current)
    robot=tool_mask(public,'cam_high')>0
    # Public palm/fingers plus conservatively excluded achromatic robot regions.
    x=current.astype(float);robot|=((x.max(2)>100)&(np.ptp(x,axis=2)<35))|(x.max(2)<65)
    robot=cv2.dilate(robot.astype(np.uint8),np.ones((5,5),np.uint8))>0
    u,v=np.asarray(source_uv).round().astype(int);region=np.zeros_like(mask,bool)
    region[max(0,v-22):min(mask.shape[0],v+23),max(0,u-22):min(mask.shape[1],u+23)]=True
    valid=region&~robot;old=initial.astype(bool);now=mask.astype(bool)
    boundary=old&~cv2.erode(initial,np.ones((3,3),np.uint8)).astype(bool)
    current_boundary=now&~cv2.erode(mask,np.ones((3,3),np.uint8)).astype(bool)
    distance=cv2.distanceTransform((~current_boundary).astype(np.uint8),cv2.DIST_L2,5)
    edge_points=boundary&valid
    changed=int(np.sum(valid&(old!=now)))
    displacement=float(np.median(distance[edge_points])) if edge_points.sum()>=8 else None
    visible_fraction=float(np.sum(old&valid)/max(1,np.sum(old&region)))
    adequate=bool(edge_points.sum()>=8 and visible_fraction>.40)
    deformed=bool(adequate and changed>=80 and displacement>=3)
    return dict(local_deformation_visible=deformed,evidence_unknown=not adequate,
        changed_source_pixels=changed,boundary_displacement_px=displacement,visible_baseline_fraction=visible_fraction,
        visible_escape=False,source='Current unoccluded coral garment mask against same-episode preapproach RGB',
        limits='Shape deformation supports an active lift candidate, not attachment or task success.')
