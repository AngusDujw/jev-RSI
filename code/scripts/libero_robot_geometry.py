"""Own-robot gripper envelope only; never query scene-object geometry."""
import itertools
import numpy as np


def gripper_geometry(env, obs):
    sim = env.sim
    gripper = env.robots[0].gripper
    tcp = np.asarray(obs['robot0_eef_pos'])
    from scipy.spatial.transform import Rotation
    R = Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
    pads, fingers = [], []
    names = gripper.important_geoms
    for name in dict.fromkeys(names['left_finger'] + names['right_finger']):
        gid = sim.model.geom_name2id(name)
        G = sim.data.geom_xmat[gid].reshape(3, 3)
        pos = sim.data.geom_xpos[gid]
        mesh = int(sim.model.geom_dataid[gid])
        if int(sim.model.geom_type[gid]) == 7 and mesh >= 0:
            start, count = int(sim.model.mesh_vertadr[mesh]), int(sim.model.mesh_vertnum[mesh])
            vertices = sim.model.mesh_vert[start:start+count]
        elif int(sim.model.geom_type[gid]) == 6:
            vertices = np.asarray(list(itertools.product([-1, 1], repeat=3))) * sim.model.geom_size[gid]
        else:
            raise ValueError('Unsupported own finger geometry: ' + name)
        local = (vertices @ G.T + pos - tcp) @ R
        fingers.append(local)
        if name in names['left_fingerpad'] + names['right_fingerpad']:
            pads.append(local)
    return dict(pad_vertices_tool=np.concatenate(pads), finger_vertices_tool=np.concatenate(fingers),
                source='Own robot finger/pad collision mesh and proprioceptive TCP; no scene geometry')


def envelope(geometry, orientation):
    p = geometry['pad_vertices_tool'] @ orientation.T
    f = geometry['finger_vertices_tool'] @ orientation.T
    return dict(pad_low_offset=p.min(axis=0), pad_high_offset=p.max(axis=0),
                pad_center_offset=(p.min(axis=0)+p.max(axis=0))/2,
                finger_low_z_offset=float(f[:, 2].min()))
