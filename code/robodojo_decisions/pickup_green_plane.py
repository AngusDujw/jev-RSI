"""Current two-RGB planar silhouette fit; no simulator scene state."""
from pathlib import Path
import cv2
import numpy as np
from pickup_visual_hull import _green_mask, _project_many
from pickup_temporal_stereo import _high_static_check


def build(obs, reference=None):
    cal = obs['camera_calibration']
    if obs['task'] != 'general_pickup' or cal['step_id'] != obs['step_id']:
        raise ValueError('Current pickup RGB/calibration required')
    paths = {r['camera']: Path(r['path']) for r in obs['images']}
    high = _green_mask(paths['cam_high'], 'cam_high').astype(np.uint8)
    wrist = _green_mask(paths['cam_right_wrist'], 'cam_right_wrist')
    if high.sum() < 80 or wrist.sum() < 100:
        raise ValueError('Insufficient green pixels for plane fit')
    source_label = 'high'
    static_check = None
    if reference is not None:
        if reference['task'] != obs['task'] or reference['step_id'] >= obs['step_id']:
            raise ValueError('Reference must be earlier same-task RGB')
        if reference.get('episode_id') != obs.get('episode_id'):
            raise ValueError('Reference must be from the same native episode')
        static_check = _high_static_check(reference, obs)
        if not static_check['stable_enough_for_temporal_ray_check']:
            raise ValueError('Current high RGB does not support static source')
        ref_paths = {r['camera']: Path(r['path']) for r in reference['images']}
        high = _green_mask(ref_paths['cam_right_wrist'], 'cam_right_wrist').astype(np.uint8)
        source_label = 'reference_right'
        ca = reference['camera_calibration']['cameras']['cam_right_wrist']
    else:
        ca = cal['cameras']['cam_high']
    cb = cal['cameras']['cam_right_wrist']
    k = np.asarray(ca['intrinsic'], float)
    t = np.asarray(ca['camera_to_environment'], float)
    yy, xx = np.nonzero(high)
    corners = np.array([[xx.min()-3, yy.min()-3], [xx.max()+3, yy.min()-3],
                        [xx.max()+3, yy.max()+3], [xx.min()-3, yy.max()+3]], np.float32)
    rays = np.column_stack(((corners[:, 0]-k[0, 2])/k[0, 0],
                            -(corners[:, 1]-k[1, 2])/k[1, 1], -np.ones(4))) @ t[:3, :3].T
    if np.any(np.abs(rays[:, 2]) < .02):
        raise ValueError('Near-horizontal source rays')
    heights = np.arange(.700, .851, .001)
    transforms = []
    for z in heights:
        xyz = t[:3, 3] + rays*((z-t[2, 3])/rays[:, 2])[:, None]
        uv, depth = _project_many(cb, xyz)
        if np.any(depth <= 0):
            raise ValueError('Source ROI projects behind current wrist')
        transforms.append(cv2.getPerspectiveTransform(corners, uv.astype(np.float32)))

    def shifted(mask, dx, dy):
        return cv2.warpAffine(mask.astype(np.uint8), np.float32([[1, 0, dx], [0, 1, dy]]),
                              (640, 480), flags=cv2.INTER_NEAREST).astype(bool)

    def curve(a, b):
        rows = []
        for z, transform in zip(heights, transforms):
            warped = cv2.warpPerspective(a.astype(np.uint8), transform, (640, 480),
                                         flags=cv2.INTER_NEAREST).astype(bool)
            overlap = int((warped & b).sum())
            rows.append((float(z), overlap/max(1, int((warped | b).sum())),
                         overlap/max(1, int(b.sum())), overlap/max(1, int(warped.sum()))))
        return rows

    nominal = curve(high, wrist)
    best = max(nominal, key=lambda r: r[1])
    if best[1] < .55 or min(best[2:]) < .65 or not .703 < best[0] < .847:
        raise ValueError(f'Green plane fit insufficient: best IoU={best[1]:.3f}')
    jitter = []
    for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
        trial = max(curve(shifted(high, dx, dy), wrist), key=lambda r: r[1])
        jitter.append({'camera': source_label, 'shift_px': [dx, dy], 'best_height_m': trial[0], 'iou': trial[1]})
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        trial = max(curve(high, shifted(wrist, dx, dy)), key=lambda r: r[1])
        jitter.append({'camera': 'right', 'shift_px': [dx, dy], 'best_height_m': trial[0], 'iou': trial[1]})
    changes = np.abs(np.array([r['best_height_m'] for r in jitter])-best[0])
    p95 = float(np.quantile(changes, .95))
    if round(p95, 9) > .005 or min(r['iou'] for r in jitter) < .45:
        raise ValueError(f'Green plane pixel sensitivity too large: {p95*1000:.2f}mm')
    compatible = [r[0] for r in nominal if r[1] >= best[1]-.03]
    # Declared systematic allowance is deliberately separate from pixel jitter.
    halfwidth = max(.005, max(abs(best[0]-z) for z in compatible)+p95+.005)
    if halfwidth > .020:
        raise ValueError('Fit cannot narrow original 20mm height hypothesis')
    return {'source': ('Same-episode earlier/current right-wrist green silhouettes, CURRENT fixed-high static-source check, public K/T; horizontal plane homography' if reference is not None else 'CURRENT fixed-high/right green silhouettes, public K/T; horizontal plane homography'),
            'reference_step_id': reference['step_id'] if reference is not None else obs['step_id'],
            'current_fixed_high_static_check': static_check,
            'current_step_id': obs['step_id'], 'estimated_green_plane_height_m': round(best[0], 6),
            'declared_green_height_halfwidth_m': round(halfwidth, 6),
            'best_iou': round(best[1], 4), 'right_green_coverage': round(best[2], 4),
            'projected_high_green_coverage': round(best[3], 4),
            'near_optimal_height_range_m': [round(min(compatible), 6), round(max(compatible), 6)],
            'pixel_shift_height_p95_mm': round(p95*1000, 3),
            'declared_systematic_allowance_mm': 5, 'jitter_trials': jitter,
            'limitations': 'Horizontal planar green surface and RGB identity are hypotheses. Occlusion, different visible surfaces, segmentation and unknown calibration bias remain. Pixel sensitivity is not a calibrated confidence bound. Added5mm is a declared allowance, not certified clearance. Not true object pose, same-point stereo, contact or a grasp target.'}
