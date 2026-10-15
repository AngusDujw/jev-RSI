"""Public X5 finger reference from URDF/STL and measured prismatic encoders."""
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
import trimesh

ROOT = Path('/root/yekangjie/project/robodojo-jev/robodojo/Assets/Robots/x5')


class Tool:
    def __init__(self):
        urdf = ET.parse(ROOT/'X5A.urdf').getroot()
        joints = {entry.get('name'): entry for entry in urdf.findall('joint')}
        self.fingers = []
        self.palm_triangles=np.asarray(trimesh.load_mesh(ROOT/'meshes/link6.STL',process=False).triangles,float)
        for link, joint_name, sign in (('link7', 'joint7', -1), ('link8', 'joint8', 1)):
            joint = joints[joint_name]
            origin = np.fromstring(joint.find('origin').get('xyz'), sep=' ')
            rpy = np.fromstring(joint.find('origin').get('rpy', '0 0 0'), sep=' ')
            rotation = Rotation.from_euler('xyz', rpy).as_matrix()
            axis = np.fromstring(joint.find('axis').get('xyz'), sep=' ')
            upper = float(joint.find('limit').get('upper'))
            mesh = trimesh.load_mesh(ROOT/f'meshes/{link}.STL', process=False)
            vertices = np.asarray(mesh.vertices, float)
            centers = np.asarray(mesh.triangles_center, float)
            normals = np.asarray(mesh.face_normals, float)
            inward_y = float(vertices[:, 1].min() if sign == -1 else vertices[:, 1].max())
            faces = ((centers[:, 0] > .04) & (np.abs(centers[:, 1]-inward_y) < .001)
                     & (normals[:, 1]*sign > .99))
            if not np.any(faces):
                raise ValueError('Public inward finger facet selection failed')
            points = np.asarray(mesh.triangles[faces]).reshape(-1, 3)
            self.fingers.append(dict(joint=joint_name, origin=origin, rotation=rotation,
                                     axis=axis, upper=upper, points=points, vertices=vertices,
                                     triangles=np.asarray(mesh.triangles,float)))

    def local_triangles(self,public,arm):
        values=public['measured_gripper'][arm]
        encoders=dict(zip(values['joint_names'],values['joint_positions_m']))
        result=[self.palm_triangles]
        for finger in self.fingers:
            offset=finger['origin']+finger['rotation']@(finger['axis']*encoders[finger['joint']])
            result.append(finger['triangles']@finger['rotation'].T+offset)
        return np.concatenate(result)

    def geometry(self, public, arm='right'):
        values = public['measured_gripper'][arm]
        encoders = dict(zip(values['joint_names'], values['joint_positions_m']))
        centers, vertices = [], []
        for finger in self.fingers:
            position = float(encoders[finger['joint']])
            if not np.isfinite(position) or not -.001 <= position <= finger['upper']+.001:
                raise ValueError('Measured finger joint outside public range')
            offset = finger['origin'] + finger['rotation'] @ (finger['axis']*position)
            centers.append((finger['points'] @ finger['rotation'].T+offset).mean(0))
            vertices.append(finger['vertices'] @ finger['rotation'].T+offset)
        local = np.mean(centers, axis=0)
        index = ('left', 'right').index(arm)
        robot = public['robot']
        quaternion = np.asarray(robot['eef_quaternions_wxyz'][index])
        rotation = Rotation.from_quat(quaternion[[1, 2, 3, 0]])
        point = np.asarray(robot['eef_positions'][index])+rotation.apply(local)
        tips=[v[v[:,0]>v[:,0].max()-.001].mean(0) for v in vertices]
        radii=[float(np.max(np.linalg.norm(v[v[:,0]>v[:,0].max()-.001,1:]-tip[1:],axis=1))) for v,tip in zip(vertices,tips)]
        return dict(local_center_m=local, world_center_m=point,
            finger_tips_local_m=np.asarray(tips),finger_tip_footprint_radius_m=radii,
            aperture_m=float(np.linalg.norm(centers[0]-centers[1])),
            distal_tip_from_center_m=float(max(v[:, 0].max() for v in vertices)-local[0]),
            downward_extent_m=float(max(np.max(-rotation.apply(v-local)[:,2]) for v in vertices)),
            rotation=rotation,
            source='Public URDF/STL inward finger facets plus current robot prismatic encoders; not contact')
