"""Explicit oracle-only asset geometry. No task labels, contacts or rewards."""
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation


def add_block_geometry(evidence, assets, layout):
    robot = evidence['robot']
    rotations = Rotation.from_quat(np.asarray(robot['eef_quaternions_wxyz'])[:, [1, 2, 3, 0]])
    robot['gripper_axes'] = dict(source='X5A URDF joint7 prismatic axis and published gripper_bias',
        frame='environment_origin', arms=['left', 'right'],
        approach_local=[1., 0., 0.], closing_local=[0., 1., 0.],
        approach_world=rotations.apply([1., 0., 0.]).tolist(),
        closing_world=rotations.apply([0., 1., 0.]).tolist(),
        limitation='Axes and nominal center define a candidate grasp, not collision or contact evidence.')
    records = json.loads(Path(layout).read_text())['Rigid'].get('block', [])
    for obj in evidence['objects']:
        if obj.get('category') != 'block':
            continue
        index = int(obj['id'].split('_')[-2])
        record = next(r for r in records if r['category_idx'] == index)
        path = Path(assets)/'Rigid/block'/f'{index:05d}'/'metadata.json'
        metadata = json.loads(path.read_text())
        vertices = np.asarray(metadata['geometry']['oriented_bbox']['vertices'], float)
        vertices *= np.asarray(record.get('scale', [1., 1., 1.]))
        quaternion = np.asarray(obj['quaternion_wxyz'])
        world = Rotation.from_quat(quaternion[[1, 2, 3, 0]]).apply(vertices) + obj['position_m']
        obj['geometry'] = dict(source='privileged_asset_bbox_plus_observed_pose', frame='environment_origin',
            local_bbox_min_m=vertices.min(0).tolist(), local_bbox_max_m=vertices.max(0).tolist(),
            world_bbox_min_m=world.min(0).tolist(), world_bbox_max_m=world.max(0).tolist(),
            limitation='Bounding surfaces are geometry, not measured contact or support. Tilted AABB is not a flat support plane.')
    return evidence
