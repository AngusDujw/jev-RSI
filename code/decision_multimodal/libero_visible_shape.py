"""Shape descriptions of current colour-filtered RGB-D points only.

No desired axis, orientation residual, robot command or scene-state lookup.
"""
import numpy as np


def upward_line(axis):
    """A consistent representative, independent of any desired relationship."""
    axis=np.asarray(axis,float).copy()
    component=axis[2] if abs(axis[2])>.1 else axis[np.argmax(abs(axis))]
    return -axis if component<0 else axis


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
    points=points[::max(1,int(np.ceil(len(points)/2500)))]
    centre,values,axes,spans=principal_shape(points)
    result=dict(status='observed_partial_shape',sample_count=len(points),
        meaning='Current visible colour-filtered surfaces only. All axes are UNORIENTED: v and -v describe the same line. Not a full object pose, desired axis, rotation error, grasp or support certificate.',
        uncertainty='Occlusion and colour/depth mixing can bias shape. Use current RGB to check which physical part these points describe.')
    if kind=='bottle':
        axis=upward_line(axes[0])
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
            in_plane_axes_world_unit=np.round([upward_line(a) for a in axes[:2]],3).tolist(),
            visible_in_plane_spans_mm=np.round(spans[:2],1).tolist(),
            current_inliers=best_count,
            plane_fit_rms_mm=round(float(np.sqrt(np.mean(((cloud-centre)@normal)**2))),2)))
        # Remove the full refined plane, not just the original three-point fit.
        # Otherwise leftover pixels from one slat plane masquerade as a second plane.
        remaining=remaining[np.abs((remaining-centre)@normal)>4.0]
    result['observed_wood_planes']=planes
    result['plane_meaning']='P labels describe fitted visible wood surfaces, not the correct receiver. Select the actual cradle from CURRENT RGB; a plane can be a leg, edge or partial slat.'
    return result


def overlay_observed_wood_lines(image,shape,K,T):
    """Project all fitted visible spans; no target, ranking or angle residual."""
    from PIL import ImageDraw,ImageFont
    draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14)
    world_to_camera=np.linalg.inv(T)
    for plane in (shape or {}).get('observed_wood_planes',[]):
        centre=np.array(plane['visible_centroid_world_mm'])/1000
        for i,axis in enumerate(plane['in_plane_axes_world_unit']):
            half=np.array(axis)*plane['visible_in_plane_spans_mm'][i]/2000
            points=[]
            for point in (centre-half,centre+half):
                camera=(world_to_camera@np.r_[point,1])[:3]
                if camera[2]<=0:break
                uv=K@camera;points.append(tuple(uv[:2]/uv[2]))
            if len(points)!=2:continue
            colour=('#ff8cff','#ffaf48')[i]
            draw.line(points,fill=colour,width=2)
            u,v=points[1]
            draw.text((max(0,min(image.width-42,u)),max(0,min(image.height-20,v))),
                plane['label']+('A','B')[i],font=font,fill=colour,stroke_width=1,stroke_fill='black')
