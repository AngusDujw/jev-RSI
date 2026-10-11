"""Fit a sloped receiving surface from a visible rack RGB-D mask only."""
import numpy as np


def fit_visible_rack(points_world, source_bounds):
    """Return an observable support line and a bottle-axis target.

    ``points_world`` must be reconstructed from rendered depth inside the
    visible rack mask. ``source_bounds`` are visible RGB-D quantile bounds.
    No simulator body pose, fixture mesh, or task predicate is used.
    """
    points = np.asarray(points_world, float)
    low, high = (np.asarray(source_bounds[key], float) for key in ('low', 'high'))
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 1000:
        raise RuntimeError('Insufficient visible rack points')
    points = points[np.isfinite(points).all(axis=1)]
    x_center = float(np.median(points[:, 0]))
    middle = points[np.abs(points[:, 0]-x_center) < .04]
    if len(middle) < 1000:
        raise RuntimeError('Insufficient central visible rack surface')
    y_low, y_high = np.quantile(middle[:, 1], [.02, .98])
    if y_high-y_low < .10:
        raise RuntimeError('Visible rack slope is too short for source')
    centres, heights, counts = [], [], []
    for y in np.linspace(y_low+.01, y_high-.01, 7):
        strip = middle[np.abs(middle[:, 1]-y) < .008]
        if len(strip) >= 60:
            centres.append(float(y))
            heights.append(float(np.median(strip[:, 2])))
            counts.append(len(strip))
    if len(centres) < 5:
        raise RuntimeError('No continuous visible rack slope')
    slope, intercept = np.polyfit(centres, heights, 1)
    residual = float(np.quantile(np.abs(np.asarray(heights)-
                         (slope*np.asarray(centres)+intercept)), .9))
    if not -.95 < slope < -.25 or residual > .015:
        raise RuntimeError('Visible rack line not consistent with a sloped support')
    # A world-X rotation tilts the held vertical bottle toward rearward -Y.
    angle = float(np.arctan2(1., -slope))
    source_length = float(high[2]-low[2])
    source_radius = float(max(high[0]-low[0], high[1]-low[1])/2)
    y_center = float((y_low+y_high)/2)
    z_surface = float(slope*y_center+intercept)
    return dict(center_world_m=[x_center, y_center,
                                z_surface+source_radius+.006],
                visible_surface_z_m=z_surface,
                source_visible_radius_m=source_radius,
                source_visible_length_m=source_length,
                source_projected_length_y_m=float(source_length*np.sin(angle)),
                x_rotation_world_rad=angle,
                support_slope_dz_dy=float(slope),
                line_residual_p90_m=residual,
                y_visible_quantile_range_m=[float(y_low), float(y_high)],
                line_samples_m=list(zip(centres, heights, counts)),
                points_used=len(middle),
                source='Visible SAM rack mask + calibrated RGB-D and visible source bounds')
