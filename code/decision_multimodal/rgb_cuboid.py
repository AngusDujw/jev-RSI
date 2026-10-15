"""Conditional upright-block geometry from RGB silhouettes and public K/T.

This is a fitted visual hypothesis, not scene state. The flat common support
plane option is explicit; no simulator depth, object dimensions or poses enter.
"""
import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull


def project(camera, points):
    k = np.asarray(camera['intrinsic'], float)
    t = np.asarray(camera['camera_to_environment'], float)
    local = (np.asarray(points)-t[:3, 3]) @ t[:3, :3]
    depth = -local[:, 2]
    uv = np.column_stack([k[0, 2]+k[0, 0]*local[:, 0]/np.maximum(depth, 1e-6),
                          k[1, 2]-k[1, 1]*local[:, 1]/np.maximum(depth, 1e-6)])
    return uv, depth


def ray(camera, uv):
    k = np.asarray(camera['intrinsic'], float)
    t = np.asarray(camera['camera_to_environment'], float)
    d = t[:3, :3] @ [(uv[0]-k[0, 2])/k[0, 0], -(uv[1]-k[1, 2])/k[1, 1], -1.]
    return t[:3, 3], d/np.linalg.norm(d)


def material(rgb, name):
    x = np.asarray(rgb, float)
    r, g, b = x[:, :, 0], x[:, :, 1], x[:, :, 2]
    if name == 'wood':
        return (r > 175) & (g > 150) & (b > 85) & (r-b > 25) & (g-b > 18)
    if name == 'white':
        return (np.min(x, axis=2) > 175) & (np.ptp(x, axis=2) < 35)
    if name == 'purple':
        return (r > 35) & (b > 30) & (g < r*.75) & (g < b*.85) & (r+b > 90)
    raise ValueError('Unknown declared block material')


def segment(rgb, name, seed_roi=None, predicted_uv=None):
    mask = material(rgb, name).astype(np.uint8)
    count, labels, stats, centers = cv2.connectedComponentsWithStats(mask)
    candidates = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if area < 12 or w > rgb.shape[1]*.6 or h > rgb.shape[0]*.6:
            continue
        if seed_roi is not None:
            x0, y0, x1, y1 = seed_roi
            overlap = (labels[y0:y1, x0:x1] == i).sum()
            if overlap < max(8, .3*area):
                continue
            score = float(overlap)
        elif predicted_uv is not None:
            distance = np.linalg.norm(centers[i]-predicted_uv)
            if distance > max(70, 2*max(w, h)):
                continue
            score = float(area)/(1+distance)
        else:
            score = float(area)
        candidates.append((score, i))
    if not candidates:
        return None
    _, i = max(candidates)
    return (labels == i).astype(np.uint8)


def contour(mask):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError('Empty block contour')
    c = max(contours, key=cv2.contourArea).reshape(-1, 2).astype(float)
    return c[ConvexHull(c).vertices]


def boundary(polygon, n=48):
    closed = np.vstack([polygon, polygon[0]])
    lengths = np.r_[0, np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))]
    if lengths[-1] <= 0:
        raise ValueError('Degenerate silhouette')
    positions = np.arange(n)*lengths[-1]/n
    return np.column_stack([np.interp(positions, lengths, closed[:, k]) for k in (0, 1)])


def distances(points, polygon):
    a = polygon
    d = np.roll(a, -1, axis=0)-a
    v = points[:, None, :]-a[None, :, :]
    f = np.clip(np.sum(v*d, axis=2)/np.maximum(np.sum(d*d, axis=1), 1e-12), 0, 1)
    return np.min(np.linalg.norm(v-f[:, :, None]*d, axis=2), axis=1)


def vertices(parameters):
    center, size, angle = parameters[:3], parameters[3:6], parameters[6]
    signs = np.array([[x, y, z] for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)])
    c, s = np.cos(angle), np.sin(angle)
    rotation = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    return (signs*size) @ rotation.T + center


def fit(views, prior=None, support_z=None):
    """views = [(public camera, current binary material mask), ...]."""
    shape_prior = prior is not None and prior.get('status') == 'fitted_visual_hypothesis'
    if not views or (len(views) < 2 and support_z is None and not shape_prior):
        return dict(status='unavailable', reason='Need two views or a declared measured support-plane hypothesis')
    records = [(camera, boundary(contour(mask)), contour(mask)) for camera, mask in views]
    if prior is not None and prior.get('status') == 'fitted_visual_hypothesis':
        initial = np.r_[prior['center_m'], prior['size_m'], prior['yaw_rad']]
    else:
        rays = [ray(camera, points.mean(0)) for camera, points, polygon in records]
        if len(rays) >= 2:
            lhs = sum(np.eye(3)-np.outer(d, d) for o, d in rays)
            rhs = sum((np.eye(3)-np.outer(d, d)) @ o for o, d in rays)
            center = np.linalg.lstsq(lhs, rhs, rcond=None)[0]
        else:
            o, d = rays[0]
            center = o+d*((support_z+.02-o[2])/d[2])
        initial = np.r_[center, [.04, .04, .04], 0.]
    lower = np.array([-1., -1., .1, .008, .008, .008, -10.])
    upper = np.array([1., 1., 1.8, .15, .15, .15, 10.])
    if shape_prior:
        lower[3:6] = np.maximum(lower[3:6], np.asarray(prior['size_m'])-.004)
        upper[3:6] = np.minimum(upper[3:6], np.asarray(prior['size_m'])+.004)
    initial = np.clip(initial, lower+1e-5, upper-1e-5)

    def residual(parameters):
        result = []
        world = vertices(parameters)
        for camera, measured, polygon in records:
            uv, depth = project(camera, world)
            if np.min(depth) <= .01:
                result.extend([1000.] * 96)
                continue
            try:
                projected = uv[ConvexHull(uv).vertices]
                rendered = boundary(projected)
                result.extend(distances(measured, projected))
                result.extend(distances(rendered, polygon))
            except Exception:
                result.extend([1000.] * 96)
        if support_z is not None:
            # Explicit common-flat-table model, not a measured object support.
            result.append((parameters[2]-parameters[5]/2-support_z)*1000)
        if shape_prior:
            # Rigid dimensions learned from earlier RGB, not an asset lookup.
            # This also permits current monocular fitting after partial occlusion.
            result.extend((parameters[3:6]-np.asarray(prior['size_m']))/.003)
        return np.asarray(result)

    solutions = []
    for yaw in (initial[6], initial[6]+.4, initial[6]-.4):
        guess = initial.copy()
        guess[6] = np.clip(yaw, lower[6]+1e-4, upper[6]-1e-4)
        solved = least_squares(residual, guess, bounds=(lower, upper),
            loss='soft_l1', f_scale=1.5, max_nfev=90, x_scale='jac')
        solutions.append(solved)
    solution = min(solutions, key=lambda s: np.mean(residual(s.x)**2))
    error = residual(solution.x)
    covariance = np.linalg.pinv(solution.jac.T @ solution.jac) * max(1., np.mean(error**2))
    uncertainty = np.sqrt(np.maximum(np.diag(covariance)[:3], 0))*2+.002
    _, singular, vh = np.linalg.svd(solution.jac, full_matrices=False)
    rank = int(np.sum(singular > 1e-4))
    if rank < 7:
        null = vh[rank:]
        uncertainty[np.linalg.norm(null[:, :3], axis=0) > .01] = .1
    center, size, yaw = solution.x[:3], solution.x[3:6], solution.x[6]
    fit_error = float(np.sqrt(np.mean(error**2)))
    return dict(status='fitted_visual_hypothesis', center_m=center.tolist(), size_m=size.tolist(),
        yaw_rad=float(yaw), bottom_z_m=float(center[2]-size[2]/2),
        top_z_m=float(center[2]+size[2]/2), silhouette_rmse_px=fit_error,
        conditional_center_halfwidth_m=uncertainty.tolist(), cameras=len(records),
        conditional_size_halfwidth_m=(np.sqrt(np.maximum(np.diag(covariance)[3:6], 0))*2+.001).tolist(),
        prior_image_derived_rigid_dimensions=shape_prior,
        support_z_hypothesis_m=support_z,
        usable=bool(fit_error < 4 and max(uncertainty) < .025),
        assumptions='Upright cuboid; visible segmentation silhouette; public camera calibration; optional common flat support plane',
        limits='Conditional visual fit and local sensitivity, not object truth, calibrated confidence, hidden contact or holding')
