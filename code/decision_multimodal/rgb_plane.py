"""Calibrated RGB feature triangulation and a robust visible tabletop model."""
import cv2
import numpy as np
from scipy.optimize import minimize_scalar
from rgb_cuboid import project, ray


def triangulate(a, b, uv_a, uv_b):
    oa, da = ray(a, uv_a)
    ob, db = ray(b, uv_b)
    ranges = np.linalg.lstsq(np.column_stack([da, -db]), ob-oa, rcond=None)[0]
    pa, pb = oa+da*ranges[0], ob+db*ranges[1]
    point = (pa+pb)/2
    angle = np.arccos(np.clip(abs(np.dot(da, db)), -1, 1))
    return dict(point=point, gap_m=float(np.linalg.norm(pa-pb)), ranges=ranges,
                angle_rad=float(angle))


def wood_mask(rgb):
    x = np.asarray(rgb, float)
    r, g, b = x[:, :, 0], x[:, :, 1], x[:, :, 2]
    keep = (r > g*1.3) & (g > b*1.2) & (r > 70) & (g > 35) & (b < 160)
    keep[:30] = False
    keep[-35:] = False
    keep[:, :20] = False
    keep[:, -20:] = False
    return keep.astype(np.uint8)*255


def fit_table(public):
    sift = cv2.SIFT_create(nfeatures=5000, contrastThreshold=.015)
    features = {}
    for name, rgb in public['rgb'].items():
        kp, descriptors = sift.detectAndCompute(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), wood_mask(rgb))
        features[name] = (kp, descriptors)
    high, desc_high = features['cam_high']
    points, sources = [], []
    matcher = cv2.BFMatcher()
    if desc_high is None:
        return dict(status='unavailable', reason='No current high-view table texture')
    for name in ('cam_left_wrist', 'cam_right_wrist'):
        wrist, desc = features[name]
        if desc is None:
            continue
        def match(a, b):
            return {m.queryIdx:m.trainIdx for rows in matcher.knnMatch(a, b, k=2)
                    if len(rows) == 2 for m, n in [rows] if m.distance < .72*n.distance}
        forward, reverse = match(desc_high, desc), match(desc, desc_high)
        for i, j in forward.items():
            if reverse.get(j) != i:
                continue
            ua, ub = np.asarray(high[i].pt), np.asarray(wrist[j].pt)
            a, b = public['calibration']['cam_high'], public['calibration'][name]
            estimate = triangulate(a, b, ua, ub)
            point = estimate['point']
            if (min(estimate['ranges']) <= 0 or estimate['gap_m'] > .005 or
                estimate['angle_rad'] < .10 or not .4 < point[2] < 1.3 or
                max(abs(point[:2])) > 1.2):
                continue
            va, _ = project(a, point.reshape(1, 3))
            vb, _ = project(b, point.reshape(1, 3))
            if max(np.linalg.norm(va[0]-ua), np.linalg.norm(vb[0]-ub)) > 2.:
                continue
            points.append(point)
            sources.append(dict(cameras=['cam_high', name], pixels=[ua.tolist(), ub.tolist()],
                                ray_gap_m=estimate['gap_m']))
    if len(points) < 8:
        return dict(status='unavailable', reason='Insufficient reciprocal geometrically consistent table features',
                    candidate_count=len(points), keypoint_counts={n:len(v[0]) for n,v in features.items()})
    points = np.asarray(points)
    bins = np.arange(.4, 1.302, .002)
    counts, edges = np.histogram(points[:, 2], bins=bins)
    index = int(np.argmax(counts))
    z = (edges[index]+edges[index+1])/2
    keep = abs(points[:, 2]-z) < .008
    for _ in range(6):
        if keep.sum() < 6:
            break
        data = np.column_stack([points[keep, :2], np.ones(keep.sum())])
        coefficients = np.linalg.lstsq(data, points[keep, 2], rcond=None)[0]
        residual = points[:, 2]-np.column_stack([points[:, :2], np.ones(len(points))]) @ coefficients
        scale = max(.001, 1.4826*np.median(abs(residual[keep]-np.median(residual[keep]))))
        keep = abs(residual) < min(.008, max(.002, 3*scale))
    if keep.sum() < 6:
        return dict(status='unavailable', reason='No robust spatial table plane', candidate_count=len(points))
    rms = float(np.sqrt(np.mean(residual[keep]**2)))
    span = np.ptp(points[keep, :2], axis=0)
    normal = np.r_[-coefficients[:2], 1.]
    normal /= np.linalg.norm(normal)
    usable = bool(keep.sum() >= 12 and max(span) > .08 and rms < .004 and normal[2] > .98)
    return dict(status='current_RGB_table_hypothesis', usable=usable,
        plane_z_equals_ax_plus_by_plus_c=coefficients.tolist(), normal_world=normal.tolist(),
        inlier_count=int(keep.sum()), candidate_count=len(points), spatial_span_xy_m=span.tolist(),
        rms_m=rms, conditional_height_sensitivity_m=max(.0015, 2*rms/np.sqrt(keep.sum())),
        inlier_points_m=points[keep].tolist(),
        inlier_matches=[s for s, valid in zip(sources, keep) if valid],
        source='Current RGB wood texture, reciprocal SIFT and public camera K/T',
        limits='Horizontal-table selection and material identity are hypotheses; sensitivity excludes unmeasured calibration/systematic errors. Not depth or scene state.')


def fit_horizontal_texture(public):
    """Estimate one horizontal plane by calibrated multi-view texture alignment.

    This uses an explicit horizontal-table hypothesis, not simulator depth.
    Independently optimize each wrist and require agreement before use.
    """
    def texture(rgb):
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
        detail = gray-cv2.GaussianBlur(gray, (0, 0), 3.)
        scale = np.sqrt(cv2.GaussianBlur(detail**2, (0, 0), 5.)+4.)
        return np.clip(detail/scale, -3., 3.)
    high = public['rgb']['cam_high']
    k = np.asarray(public['calibration']['cam_high']['intrinsic'])
    t = np.asarray(public['calibration']['cam_high']['camera_to_environment'])
    yy, xx = np.mgrid[0:high.shape[0]:3, 0:high.shape[1]:3]
    valid = wood_mask(high)[yy, xx] > 0
    source_texture = texture(high)
    valid &= abs(source_texture[yy, xx]) > .18
    xx, yy = xx[valid], yy[valid]
    directions = np.column_stack([(xx-k[0, 2])/k[0, 0], -(yy-k[1, 2])/k[1, 1], -np.ones(len(xx))]) @ t[:3, :3].T
    source = source_texture[yy, xx]
    estimates = {}
    for name in ('cam_left_wrist', 'cam_right_wrist'):
        rgb = public['rgb'][name]
        target = texture(rgb)
        target_mask = wood_mask(rgb).astype(np.float32)/255
        camera = public['calibration'][name]
        def score(z, detail=False):
            points = t[:3, 3]+directions*((z-t[2, 3])/directions[:, 2])[:, None]
            uv, depth = project(camera, points)
            u, v = uv[:, 0].astype(np.float32).reshape(-1, 1), uv[:, 1].astype(np.float32).reshape(-1, 1)
            inside = (depth > .05) & (uv[:, 0] > 25) & (uv[:, 0] < rgb.shape[1]-25) & (uv[:, 1] > 35) & (uv[:, 1] < rgb.shape[0]-40)
            inside &= cv2.remap(target_mask, u, v, cv2.INTER_NEAREST).ravel() > .5
            other = cv2.remap(target, u, v, cv2.INTER_LINEAR).ravel()
            n = int(inside.sum())
            if n < 100:
                return (-1., n) if detail else -1.
            a, b = source[inside], other[inside]
            a, b = a-a.mean(), b-b.mean()
            correlation = float(np.dot(a, b)/max(1e-9, np.linalg.norm(a)*np.linalg.norm(b)))
            return (correlation, n) if detail else correlation
        grid = np.arange(.45, 1.151, .002)
        values = np.asarray([score(z) for z in grid])
        best = int(np.argmax(values))
        z0 = grid[best]
        result = minimize_scalar(lambda z:-score(z), bounds=(z0-.003, z0+.003), method='bounded', options={'xatol':.00005})
        z = float(result.x)
        value, count = score(z, True)
        peak_drop = value-max(score(z-.005), score(z+.005))
        estimates[name] = dict(z_m=z, correlation=value, sample_count=count, correlation_drop_at_5mm=peak_drop,
                               usable=bool(value > .45 and peak_drop > .02))
    good = [v for v in estimates.values() if v['usable']]
    disagreement = float(np.ptp([v['z_m'] for v in good])) if len(good) == 2 else None
    usable = len(good) == 2 and disagreement < .004
    return dict(status='current_RGB_horizontal_texture_hypothesis', usable=bool(usable), wrist_estimates=estimates,
        plane_z_m=float(np.mean([v['z_m'] for v in good])) if good else None,
        cross_wrist_height_disagreement_m=disagreement,
        conditional_height_sensitivity_m=max(.002, disagreement or 0.) if usable else None,
        source='Current table RGB texture registered across public calibrated cameras; horizontal-plane hypothesis',
        limits='Conditional on horizontal tabletop and camera calibration. No scene pose or depth; reported sensitivity is not a calibrated probability interval.')
