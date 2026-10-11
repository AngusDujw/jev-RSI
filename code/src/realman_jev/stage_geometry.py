"""Observed gripper collision geometry, without object-specific grasp selection."""
from functools import lru_cache
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation


def material_reference(vertices, fingertip, vertex_id=None):
    """Observe a mesh vertex; retaining an ID follows material, not nearest space."""
    vertices=np.asarray(vertices,float)
    fingertip=np.asarray(fingertip,float)
    if vertices.ndim!=2 or vertices.shape[1]!=3 or not len(vertices) or fingertip.shape!=(3,) or not np.isfinite(vertices).all() or not np.isfinite(fingertip).all():
        raise ValueError('Material reference requires finite mesh XYZ and fingertip XYZ')
    if vertex_id is None:
        vertex_id=int(np.argmin(np.linalg.norm(vertices-fingertip,axis=1)))
    if type(vertex_id) is not int or not 0<=vertex_id<len(vertices):
        raise ValueError('Pinned material vertex is unavailable')
    point=vertices[vertex_id]
    return dict(vertex_id=vertex_id,position_m=point.tolist(),distance_to_fingertip_m=float(np.linalg.norm(point-fingertip)))


@lru_cache(maxsize=8)
def finger_meshes(urdf_path, joint_names):
    import trimesh
    path = Path(urdf_path)
    root = ET.parse(path).getroot()
    links = {link.attrib['name']: link for link in root.findall('link')}
    result = []
    for joint in root.findall('joint'):
        if joint.attrib['name'] not in joint_names:
            continue
        link_name = joint.find('child').attrib['link']
        pieces = []
        for collision in links[link_name].findall('collision'):
            mesh = collision.find('geometry/mesh')
            if mesh is None:
                continue
            filename = mesh.attrib['filename']
            mesh_path = path.parent / filename
            vertices = np.asarray(trimesh.load(mesh_path, force='mesh', process=False).vertices, float)
            vertices = vertices * np.fromstring(mesh.attrib.get('scale', '1 1 1'), sep=' ')
            origin = collision.find('origin')
            xyz = np.fromstring(origin.attrib.get('xyz', '0 0 0'), sep=' ') if origin is not None else np.zeros(3)
            rpy = np.fromstring(origin.attrib.get('rpy', '0 0 0'), sep=' ') if origin is not None else np.zeros(3)
            pieces.append(Rotation.from_euler('xyz', rpy).apply(vertices)+xyz)
        if pieces:
            vertices = np.concatenate(pieces)
            result.append((link_name, vertices))
    return tuple(result)


def observed_fingers(manager, robot, wrist_position, wrist_quaternion):
    fingers = []
    all_points, tips = [], []
    wrist_rotation = Rotation.from_quat(np.asarray(wrist_quaternion)[[1, 2, 3, 0]])
    for link, vertices in finger_meshes(str(robot.urdf_path), tuple(robot.gripper_joints_name)):
        pose = manager.get_link_pose(robot, link, is_relative=True)[0]
        rotation = Rotation.from_quat(np.asarray(pose)[[4, 5, 6, 3]])
        points = rotation.apply(vertices)+np.asarray(pose[:3])
        # Distal +X boundary is a geometric point, not a measured contact.
        distal = points[vertices[:, 0] >= vertices[:, 0].max()-.001].mean(0)
        fingers.append(dict(link=link, local_collision_min_m=vertices.min(0).tolist(),
            local_collision_max_m=vertices.max(0).tolist(), world_bbox_min_m=points.min(0).tolist(),
            world_bbox_max_m=points.max(0).tolist(), distal_boundary_point_m=distal.tolist()))
        all_points.append(points); tips.append(distal)
    if not all_points:
        return None
    points = np.concatenate(all_points)
    in_wrist = wrist_rotation.inv().apply(points-np.asarray(wrist_position))
    return dict(fingers=fingers, world_bbox_min_m=points.min(0).tolist(), world_bbox_max_m=points.max(0).tolist(),
        distal_midpoint_m=np.mean(tips, axis=0).tolist(),
        maximum_reach_along_wrist_x_m=float(in_wrist[:, 0].max()),
        reach_beyond_nominal_tcp_m=float(in_wrist[:, 0].max()-robot.gripper_bias),
        provenance='URDF collision mesh transformed by measured finger link poses; distal +X mesh boundary; NOT contact force, capture evidence, or validated grasp')
