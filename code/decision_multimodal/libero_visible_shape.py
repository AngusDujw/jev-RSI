"""Shape descriptions of current colour-filtered RGB-D points only.

No desired axis, orientation residual, robot command or scene-state lookup.
"""
import numpy as np


def principal_shape(points):
    points=np.asarray(points,float)
    centre=np.median(points,axis=0)
    distance=np.linalg.norm(points-centre,axis=1)
    points=points[distance<=np.quantile(distance,.98)]
    centre=points.mean(axis=0)
    _,values,axes=np.linalg.svd(points-centre,full_matrices=False)
    projection=(points-centre)@axes.T
    spans=np.quantile(projection,.95,axis=0)-np.quantile(projection,.05,axis=0)
    return centre,values,axes,spans


def describe_visible_shape(points_mm,kind):
    points=np.asarray(points_mm,float)
    points=points[np.isfinite(points).all(axis=1)]
    if len(points)<40:return dict(status='unknown',reason='Too few current depth samples.')
    points=points[::max(1,len(points)//2500)]
    centre,values,axes,spans=principal_shape(points)
    result=dict(status='observed_partial_shape',sample_count=len(points),
        meaning='Current visible colour-filtered surfaces only. All axes are UNORIENTED: v and -v describe the same line. Not a full object pose, desired axis, rotation error, grasp or support certificate.',
        uncertainty='Occlusion and colour/depth mixing can bias shape. Use current RGB to check which physical part these points describe.')
    if kind=='bottle':
        axis=axes[0]
        if axis[np.argmax(np.abs(axis))]<0:axis=-axis
        result.update(visible_long_axis_world_unit=np.round(axis,3).tolist(),
            visible_principal_spans_mm=np.round(spans,1).tolist(),
            elongation_ratio=round(float(values[0]/max(values[1],1e-9)),2))
        return result
    if kind!='rack':return result
    rng=np.random.default_rng(0);remaining=points.copy();planes=[]
    for _ in range(2):
        if len(remaining)<100:break
        best=None;best_count=0
        for _ in range(100):
            a,b,c=remaining[rng.choice(len(remaining),3,replace=False)]
            normal=np.cross(b-a,c-a);length=np.linalg.norm(normal)
            if length<1e-6:continue
            normal/=length
            inliers=np.abs((remaining-a)@normal)<=2.0
            count=int(inliers.sum())
            if count>best_count:best,best_count=inliers,count
        if best is None or best_count<100:break
        cloud=remaining[best];centre,values,axes,spans=principal_shape(cloud)
        normal=axes[2]
        if normal[2]<0:normal=-normal
        planes.append(dict(label='P'+str(len(planes)),visible_centroid_world_mm=np.round(centre,1).tolist(),
            surface_normal_world_unit=np.round(normal,3).tolist(),
            in_plane_axes_world_unit=np.round(axes[:2],3).tolist(),
            visible_in_plane_spans_mm=np.round(spans[:2],1).tolist(),
            current_inliers=best_count,
            plane_fit_rms_mm=round(float(np.sqrt(np.mean(((cloud-centre)@normal)**2))),2)))
        remaining=remaining[~best]
    result['observed_wood_planes']=planes
    result['plane_meaning']='P labels describe fitted visible wood surfaces, not the correct receiver. Select the actual cradle from CURRENT RGB; a plane can be a leg, edge or partial slat.'
    return result
