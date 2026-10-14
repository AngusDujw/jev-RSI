"""Current RGB source pixels vs public hand footprints; no scene truth."""
from pathlib import Path
import os
import pwd
import cv2
import numpy as np
from camera_geometry import eef_transform, gripper_mesh_vertices
from pickup_visual_hull import _green_mask, _project_many


def effect(obs, target, material=None, source_mask_override=None, source_step_id=None):
    image = next(row['path'] for row in obs['images'] if row['camera']=='cam_high')
    try:
        source = (_green_mask(Path(image), 'cam_high') if source_mask_override is None
                  else np.asarray(source_mask_override,dtype=bool))
        count = int(source.sum())
    except ValueError:
        source,count=None,None
    high_available=bool(count is not None and count>=80)
    if not high_available and material is None:return None
    mesh_root = Path(pwd.getpwuid(os.getuid()).pw_dir) / 'DataStorage/jev-router/sources/RoboDojo/Assets/Robots/x5/meshes'
    vertices = gripper_mesh_vertices(str(mesh_root)) if high_available else []
    calibration = obs['camera_calibration']['cameras']['cam_high']
    def fraction(pose):
        transform = eef_transform(pose)
        footprint = np.zeros(source.shape, np.uint8)
        for verts, origin, axis in zip(vertices,
                ([0,0,0],[.08657,.024896,-.0002436],[.08657,-.0249,-.00024366]), (0,1,-1)):
            offset = np.asarray(origin) + [0,axis*.044,0]
            world = (verts+offset) @ transform[:3,:3].T + transform[:3,3]
            uv, depth = _project_many(calibration, world)
            valid = (depth > 0) & np.isfinite(uv).all(axis=1) & (np.abs(uv).max(axis=1)<1e6)
            if valid.sum() >= 3:
                hull = cv2.convexHull(np.round(uv[valid]).astype(np.int32))
                cv2.fillConvexPoly(footprint, hull, 1)
        return float(footprint[source].mean())
    current = fraction(obs['current_eef']['right']) if high_available else None
    predicted = fraction(target['right']) if high_available else None
    wrist = None
    if material is not None:
        point = np.asarray(material['representative_material_point']['estimated_world_xyz_m']).reshape(1,3)
        camera = dict(obs['camera_calibration']['cameras']['cam_right_wrist'])
        mount = np.linalg.inv(eef_transform(obs['current_eef']['right'])) @ np.asarray(camera['camera_to_environment'])
        uv0, depth0 = _project_many(camera, point)
        camera['camera_to_environment'] = (eef_transform(target['right']) @ mount).tolist()
        uv1, depth1 = _project_many(camera, point)
        def margin(uv, depth):
            return float(min(uv[0,0],639-uv[0,0],uv[0,1],479-uv[0,1])) if depth[0]>0 else -1000.0
        wrist = {'current_named_green_pixel_projection_uv':uv0[0].round(2).tolist(),
                 'after_target_named_green_pixel_projection_uv':uv1[0].round(2).tolist(),
                 'current_edge_margin_px':round(margin(uv0,depth0),2),
                 'after_target_edge_margin_px':round(margin(uv1,depth1),2),
                 'scope':'One CURRENT RGB ray/height point hypothesis, propagated PUBLIC rigid wrist mount; not source ground truth, full-object visibility or predicted contact.'}
    return {'named_source_wrist_field_of_view':wrist,
            'current_actual_high_green_pixels':count if source_mask_override is None else None,
            'historical_view_proxy_pixel_count':count if source_mask_override is not None else None,
            'historical_view_proxy_step_id':source_step_id,
            'current_high_footprint_evidence_available':high_available,
            'current_public_hand_footprint_overlap_fraction':round(current,4) if current is not None else None,
            'after_full_target_public_hand_footprint_overlap_fraction':round(predicted,4) if predicted is not None else None,
            ('additional_current_source_pixel_overlap_fraction' if source_mask_override is None else
             'additional_reference_view_proxy_overlap_fraction'):round(max(0,predicted-current),4) if current is not None else None,
            'scope':('Conservative per-link convex PUBLIC mesh projections against CURRENT visible green pixels; assumes those pixels remain fixed. ' if source_mask_override is None else
                     'Conservative PUBLIC hand-mesh projections against an explicitly HISTORICAL fixed-high source-BBOX view proxy, under a declared static-source hypothesis. The bbox includes unknown/negative space and is NEVER current material, depth or contact evidence. ')+
                    'High-footprint values may be null when current high evidence is insufficient; null is UNKNOWN, not zero overlap. Wrist named-point FOV is independently available from current wrist-supported uncertain geometry. Not a rendered future image, guaranteed visibility, collision or contact certificate. Hidden source pixels are unknown.'}
