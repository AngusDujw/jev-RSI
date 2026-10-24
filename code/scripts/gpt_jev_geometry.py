"""Pure numerical geometry for generated programs; no sensors or task policy.

All inputs are caller-selected measurements. Fits report residuals and reject
degenerate data; they cannot establish semantic identity or physical success.
"""
import numpy as np


def _array(value, shape=None):
    result = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(result)) or (shape is not None and result.shape != shape):
        raise ValueError("Invalid geometry shape or nonfinite value")
    return result


def rotation(quaternion_xyzw):
    """Active tool-to-world matrix for a unit xyzw quaternion."""
    q = _array(quaternion_xyzw, (4,))
    norm = float(np.linalg.norm(q))
    if abs(norm - 1.) > .01:
        raise ValueError("Expected a unit quaternion")
    x, y, z, w = q / norm
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def transform(points, matrix):
    """Apply a proper rigid homogeneous transform to N x 3 points."""
    p, t = _array(points), _array(matrix, (4, 4))
    r = t[:3, :3]
    if p.ndim != 2 or p.shape[1] != 3:
        raise ValueError("Expected N x 3 points")
    if (not np.allclose(t[3], [0, 0, 0, 1], atol=1e-6) or
            not np.allclose(r.T @ r, np.eye(3), atol=1e-5) or np.linalg.det(r) < .999):
        raise ValueError("Expected a proper rigid transform")
    return p @ r.T + t[:3, 3]


def pad_position(state):
    """World pad center from public proprioception and own tool offset."""
    return (_array(state['tcp_position_world_m'], (3,)) +
            rotation(state['tcp_quaternion_xyzw']) @
            _array(state['own_geometry']['pad_center_in_tool_m'], (3,)))


def plane(points):
    """SVD plane, normal oriented toward world +z; no automatic acceptance."""
    p = _array(points)
    if p.ndim != 2 or p.shape[1] != 3 or len(p) < 3:
        raise ValueError("Plane requires at least three 3D samples")
    center = p.mean(axis=0)
    _, singular, vt = np.linalg.svd(p-center, full_matrices=False)
    if singular[1] <= 1e-8:
        raise ValueError("Plane samples are collinear")
    normal = vt[-1]
    if normal[2] < 0:
        normal = -normal
    d = -float(normal @ center)
    return dict(coefficients=[*normal.tolist(), d], center_world_m=center.tolist(),
                rms_m=float(np.sqrt(np.mean((p @ normal+d)**2))),
                in_plane_spread_m=(singular[:2]/np.sqrt(len(p))).tolist())


def circle_xy(points):
    """Least-squares XY circle; callers must validate plane and boundary identity."""
    p = _array(points)
    if p.ndim != 2 or p.shape[1] not in (2, 3) or len(p) < 3:
        raise ValueError("Circle requires at least three XY or XYZ samples")
    xy = p[:, :2]
    origin = xy.mean(axis=0)
    x = xy-origin
    design = np.column_stack((2*x, np.ones(len(x))))
    sol, _, rank, _ = np.linalg.lstsq(design, np.sum(x*x, axis=1), rcond=None)
    if rank != 3:
        raise ValueError("Circle samples are collinear")
    center = origin+sol[:2]
    radii = np.linalg.norm(xy-center, axis=1)
    angles = np.sort(np.arctan2(xy[:, 1]-center[1], xy[:, 0]-center[0]))
    return dict(center_xy_m=center.tolist(), radius_m=float(radii.mean()),
                rms_m=float(radii.std()), max_radial_error_m=float(np.max(np.abs(radii-radii.mean()))),
                largest_angular_gap_rad=float(np.max(np.diff(np.r_[angles, angles[0]+2*np.pi]))))


def attachment_error(points_before, points_after, state_before, state_after):
    """Maximum discrepancy from measured hand rigid motion, not a grasp label."""
    p, q = _array(points_before), _array(points_after)
    if p.shape != q.shape or p.ndim != 2 or p.shape[1] != 3 or len(p) == 0:
        raise ValueError("Expected corresponding nonempty N x 3 points")
    local = (p-_array(state_before['tcp_position_world_m'], (3,))) @ rotation(state_before['tcp_quaternion_xyzw'])
    expected = local @ rotation(state_after['tcp_quaternion_xyzw']).T + _array(state_after['tcp_position_world_m'], (3,))
    return float(np.max(np.linalg.norm(q-expected, axis=1)))
