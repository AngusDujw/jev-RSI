"""Current two-RGB planar silhouette fit; no simulator scene state."""
from pathlib import Path
import cv2
import numpy as np
from pickup_visual_hull import _green_mask, _project_many
from pickup_temporal_stereo import _high_static_check


def build(obs, reference=None, max_pixel_p95_mm=5.0, max_halfwidth_m=.020, allow_coarse_occlusion=False, wrist_fit_region=None):
    if not 5 <= max_pixel_p95_mm <= 10 or not .020 <= max_halfwidth_m <= .035:
        raise ValueError("Invalid declared approach-only sensitivity allowance")
    cal = obs['camera_calibration']
    if obs['task'] != 'general_pickup' or cal['step_id'] != obs['step_id']:
        raise ValueError('Current pickup RGB/calibration required')
    paths = {r['camera']: Path(r['path']) for r in obs['images']}
    high = _green_mask(paths['cam_high'], 'cam_high').astype(np.uint8)
    wrist = _green_mask(paths['cam_right_wrist'], 'cam_right_wrist')
    if high.sum() < 80 or wrist.sum() < 100:
        raise ValueError('Insufficient green pixels for plane fit')
    fit_region = np.ones(wrist.shape, dtype=bool)
    if wrist_fit_region is not None:
        x0,y0,x1,y1 = wrist_fit_region
        yy,xx = np.indices(wrist.shape)
        fit_region = (xx>=x0)&(xx<=x1)&(yy>=y0)&(yy<=y1)
        if (wrist & fit_region).sum()<500:
            raise ValueError('Insufficient CURRENT green material in public-finger fit region')
    source_label = 'high'
    static_check = None
    coarse_occlusion = False
    if reference is not None:
        if reference['task'] != obs['task'] or reference['step_id'] >= obs['step_id']:
            raise ValueError('Reference must be earlier same-task RGB')
        if reference.get('episode_id') != obs.get('episode_id'):
            raise ValueError('Reference must be from the same native episode')
        static_check = _high_static_check(reference, obs)
        if not static_check['stable_enough_for_temporal_ray_check']:
            # Shadow changes raw brightness; keep this alternative directional
            # only, never elevate it to strict contact geometry.
            ref_high = _green_mask(Path(next(r['path'] for r in reference['images']
                                      if r['camera']=='cam_high')), 'cam_high')
            shared = ref_high.astype(bool) & high.astype(bool)
            old_rgb = cv2.imread(next(r['path'] for r in reference['images'] if r['camera']=='cam_high')).astype(float)
            new_rgb = cv2.imread(str(paths['cam_high'])).astype(float)
            chroma_old = old_rgb / np.maximum(old_rgb.sum(axis=2, keepdims=True), 1)
            chroma_new = new_rgb / np.maximum(new_rgb.sum(axis=2, keepdims=True), 1)
            chroma_p95 = (float(np.quantile(np.linalg.norm(chroma_old[shared]-chroma_new[shared],axis=1),.95))
                          if shared.sum() >= 80 else 1.0)
            coarse_occlusion = bool(allow_coarse_occlusion and
                obs['step_id']-reference['step_id'] <= 60 and
                static_check['area_ratio'] >= .5 and
                static_check['current_green_pixels_present_in_reference_fraction'] >= .98 and
                static_check['centroid_change_px'] <= 4 and
                static_check['shared_green_rgb_abs_change_p95'] <= 40 and
                chroma_p95 <= .08)
            if not coarse_occlusion:
                raise ValueError('Current high RGB does not support static source')
            static_check = dict(static_check, directional_subset_shadow_hypothesis=True,
                shared_green_chromaticity_change_p95=round(chroma_p95,4),
                limitation='Current visible fixed-high green subset and chromaticity support only a coarse stationary-source hypothesis under occlusion/shadow; not strict stationarity/contact evidence.')
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
    valid_heights = []
    for z in heights:
        xyz = t[:3, 3] + rays*((z-t[2, 3])/rays[:, 2])[:, None]
        uv, depth = _project_many(cb, xyz)
        if np.any(depth <= 0):
            continue
        valid_heights.append(float(z))
        transforms.append(cv2.getPerspectiveTransform(corners, uv.astype(np.float32)))
    if len(valid_heights) < 40:
        raise ValueError('Insufficient positive-depth plane search range')
    heights = valid_heights

    def shifted(mask, dx, dy):
        return cv2.warpAffine(mask.astype(np.uint8), np.float32([[1, 0, dx], [0, 1, dy]]),
                              (640, 480), flags=cv2.INTER_NEAREST).astype(bool)

    def curve(a, b):
        rows = []
        for z, transform in zip(heights, transforms):
            warped = cv2.warpPerspective(a.astype(np.uint8), transform, (640, 480),
                                         flags=cv2.INTER_NEAREST).astype(bool)
            observed = b & fit_region
            warped &= fit_region
            overlap = int((warped & observed).sum())
            rows.append((float(z), overlap/max(1, int((warped | observed).sum())),
                         overlap/max(1, int(observed.sum())), overlap/max(1, int(warped.sum()))))
        return rows

    nominal = curve(high, wrist)
    best = max(nominal, key=lambda r: r[1])
    if (best[1] < .55 or min(best[2:]) < .65 or
            not heights[0]+.003 < best[0] < heights[-1]-.003):
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
    if round(p95, 9) > max_pixel_p95_mm/1000 or min(r['iou'] for r in jitter) < .45:
        raise ValueError(f'Green plane pixel sensitivity too large: {p95*1000:.2f}mm')
    compatible = [r[0] for r in nominal if r[1] >= best[1]-.03]
    # Declared systematic allowance is deliberately separate from pixel jitter.
    halfwidth = max(.005, max(abs(best[0]-z) for z in compatible)+p95+.005)
    if halfwidth > max_halfwidth_m:
        raise ValueError('Fit cannot narrow original 20mm height hypothesis')
    contact_precision = bool(not coarse_occlusion and round(p95, 9) <= .005 and halfwidth <= .020)
    return {'current_public_finger_wrist_fit_region_xyxy': wrist_fit_region,
            'coarse_occlusion_hypothesis': coarse_occlusion,
            'contact_precision_eligible': contact_precision,
            'geometry_scope': 'strict_5mm_pixel_gate_hypothesis' if contact_precision else 'COARSE_DIRECTIONAL_APPROACH_ONLY: no CLOSE or contact-approach candidate',
            'declared_pixel_sensitivity_limit_mm': max_pixel_p95_mm,
            'source': ('Same-episode earlier/current right-wrist green silhouettes, CURRENT fixed-high static-source check, public K/T; horizontal plane homography' if reference is not None else 'CURRENT fixed-high/right green silhouettes, public K/T; horizontal plane homography'),
            'reference_step_id': reference['step_id'] if reference is not None else obs['step_id'],
            'current_fixed_high_static_check': static_check,
            'current_step_id': obs['step_id'], 'estimated_green_plane_height_m': round(best[0], 6),
            'declared_green_height_halfwidth_m': round(halfwidth, 6),
            'best_iou': round(best[1], 4), 'right_green_coverage': round(best[2], 4),
            'projected_high_green_coverage': round(best[3], 4),
            'near_optimal_height_range_m': [round(min(compatible), 6), round(max(compatible), 6)],
            'positive_depth_height_search_range_m': [round(heights[0], 6), round(heights[-1], 6)],
            'pixel_shift_height_p95_mm': round(p95*1000, 3),
            'declared_systematic_allowance_mm': 5, 'jitter_trials': jitter,
            'limitations': 'Horizontal planar green surface and RGB identity are hypotheses. Occlusion, different visible surfaces, segmentation and unknown calibration bias remain. Pixel sensitivity is not a calibrated confidence bound. Added5mm is a declared allowance, not certified clearance. Not true object pose, same-point stereo, contact or a grasp target.'}
