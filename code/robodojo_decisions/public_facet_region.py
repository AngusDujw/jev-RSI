"""Interior regions of PUBLIC planar finger facets, not contact observations."""
import os
import numpy as np
from scipy.spatial import ConvexHull


def inset_faces(vertices, margin_m):
    """Trim a convex coplanar triangle union by a declared metric edge margin.

    Internal triangulation edges are not physical boundaries. Reject a
    nonconvex, nonplanar or empty region rather than silently relaxing it.
    """
    faces=np.asarray(vertices,float).reshape(-1,3,3)
    if not np.isfinite(faces).all() or not np.isfinite(margin_m) or margin_m<0:
        raise ValueError('Invalid public facet coordinates or inset margin')
    if margin_m==0:return faces.reshape(-1,3).copy()
    points=np.unique(faces.reshape(-1,3),axis=0)
    origin=points.mean(axis=0)
    _,_,basis=np.linalg.svd(points-origin,full_matrices=False)
    if basis.shape!=(3,3) or np.max(np.abs((points-origin)@basis[2]))>1e-5:
        raise ValueError('Public contact-region facet is not planar within10um')
    uv=(points-origin)@basis[:2].T
    hull=ConvexHull(uv)
    polygon=uv[hull.vertices]
    original_area=np.linalg.norm(np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0]),axis=1).sum()/2
    if not np.isclose(original_area,hull.volume,rtol=1e-4,atol=1e-10):
        raise ValueError('Public facet triangles do not form one convex union')
    signed_area=np.sum(polygon[:,0]*np.roll(polygon[:,1],-1)-polygon[:,1]*np.roll(polygon[:,0],-1))/2
    if signed_area<0:polygon=polygon[::-1]
    edges=np.roll(polygon,-1,axis=0)-polygon
    lengths=np.linalg.norm(edges,axis=1)
    if np.any(lengths<1e-8):raise ValueError('Degenerate public facet edge')
    normals=np.column_stack((-edges[:,1],edges[:,0]))/lengths[:,None]
    offsets=np.sum(normals*polygon,axis=1)+margin_m
    intersections=[]
    for i in range(len(polygon)):
        matrix=normals[[i-1,i]]
        if abs(np.linalg.det(matrix))<1e-9:raise ValueError('Parallel public facet boundaries')
        intersections.append(np.linalg.solve(matrix,offsets[[i-1,i]]))
    inset=np.asarray(intersections)
    if np.any(inset@normals.T<offsets[None,:]-1e-9):
        raise ValueError('Requested public facet inset has no valid interior')
    area=abs(np.sum(inset[:,0]*np.roll(inset[:,1],-1)-inset[:,1]*np.roll(inset[:,0],-1)))/2
    if area<1e-10:raise ValueError('Requested public facet inset is empty')
    world=inset@basis[:2]+origin
    return np.asarray([[world[0],world[i],world[i+1]] for i in range(1,len(world)-1)]).reshape(-1,3)


def selected_facets(pads):
    margin_mm=float(os.environ.get('ROBODOJO_PICKUP_PUBLIC_FACET_INSET_MM','0'))
    if not np.isfinite(margin_mm) or not 0<=margin_mm<=4:
        raise ValueError('Public facet inset must be within0..4mm')
    full=[np.asarray(pads['rows'][name]['inner_facet_world_xyz_m'],float) for name in ('link7','link8')]
    selected=[inset_faces(face,margin_mm/1000) for face in full]
    return full,selected,margin_mm
