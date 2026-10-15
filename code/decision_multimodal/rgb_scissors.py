"""Mint-material planar contour fitting from current RGB and public cameras."""
import cv2
import numpy as np
from scipy.optimize import least_squares, minimize_scalar
from rgb_cuboid import project, ray


def mint(rgb, roi=None, prediction=None):
    x = rgb.astype(float)
    r, g, b = x[:, :, 0], x[:, :, 1], x[:, :, 2]
    mask = ((g-r > 5) & (g-b > 0) & (r > 80)).astype(np.uint8)
    count, labels, stats, centers = cv2.connectedComponentsWithStats(mask)
    candidates = []
    for i in range(1, count):
        if stats[i, 4] < 30:
            continue
        if roi is not None:
            a,b,c,d = roi
            overlap = int((labels[b:d, a:c] == i).sum())
            if overlap < .3*stats[i, 4]:
                continue
            score = overlap
        elif prediction is not None:
            distance = np.linalg.norm(centers[i]-prediction)
            if distance > 100:
                continue
            score = stats[i, 4]/(1+distance)
        else:
            score = stats[i, 4]
        candidates.append((score, i))
    return (labels == max(candidates)[1]).astype(np.uint8) if candidates else None


def boundary(mask):
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    return np.concatenate([c.reshape(-1, 2) for c in contours if cv2.arcLength(c, True) > 15]).astype(float)


def intersect(camera, uv, height):
    return np.asarray([o+d*((height-o[2])/d[2]) for o,d in (ray(camera, p) for p in uv)])


class Scissors:
    def __init__(self, public, seeds, table):
        self.table = table
        self.cameras = public['calibration']
        self.height0 = table['plane_z_m']
        masks = {n:mint(public['rgb'][n], roi=s['scissors_roi'])
                 for n,s in seeds.items() if isinstance(s, dict) and s.get('scissors_roi')}
        if any(m is None for m in masks.values()) or len(masks) < 2:
            raise ValueError('Initial named mint material is not visible in two views')
        high = boundary(masks['cam_high'])
        right = boundary(masks['cam_right_wrist'])
        high = high[np.linspace(0, len(high)-1, min(240,len(high))).astype(int)]
        right = right[np.linspace(0, len(right)-1, min(300,len(right))).astype(int)]
        def residual(height):
            points = intersect(self.cameras['cam_high'], high, float(height))
            uv,_ = project(self.cameras['cam_right_wrist'], points)
            distances = np.linalg.norm(uv[:,None,:]-right[None,:,:], axis=2)
            return np.r_[distances.min(1), distances.min(0)]
        fit = least_squares(lambda h:residual(h[0]), [self.height0+.008],
            bounds=([self.height0+.001],[self.height0+.030]), loss='soft_l1', f_scale=2.)
        self.top_height = float(fit.x[0])
        self.initial_rms = float(np.sqrt(np.mean(residual(self.top_height)**2)))
        self.points0 = intersect(self.cameras['cam_high'], high, self.top_height)
        a,b,c,d = seeds['cam_high']['neck_roi']
        neck = masks['cam_high'][b:d,a:c]
        yy,xx = np.nonzero(neck)
        if len(xx) < 8:
            raise ValueError('Selected neck does not contain mint solid material')
        self.neck_uv = [float(a+xx.mean()), float(b+yy.mean())]
        self.center0 = intersect(self.cameras['cam_high'], [self.neck_uv], self.top_height)[0]
        holes = [seeds['cam_high']['left_hole_center'], seeds['cam_high']['right_hole_center']]
        hp = intersect(self.cameras['cam_high'], holes, self.top_height)
        self.closing_axis = hp[1]-hp[0]
        self.closing_axis[2] = 0
        self.closing_axis /= np.linalg.norm(self.closing_axis)
        self.local_points = self.points0-self.center0
        neck_points = intersect(self.cameras['cam_high'], np.column_stack([a+xx,b+yy]), self.top_height)
        self.width = float(np.ptp(neck_points @ self.closing_axis))
        self.estimate = np.r_[self.center0, 0.]
        self.last_tick = None
        self.last_result = None

    def update(self, public, predicted=None):
        if public['step'] == self.last_tick:
            return self.last_result
        self.last_tick = public['step']
        initial = self.estimate.copy()
        if predicted is not None:
            initial[:3] = predicted
        observed = []
        for name,rgb in public['rgb'].items():
            uv,depth = project(public['calibration'][name], initial[:3].reshape(1,3))
            if depth[0] <= 0:
                continue
            mask = mint(rgb, prediction=uv[0])
            if mask is None:
                continue
            points = boundary(mask)
            if len(points) < 20 or mask[:5].any() or mask[-5:].any() or mask[:,:5].any() or mask[:,-5:].any():
                continue
            points = points[np.linspace(0,len(points)-1,min(220,len(points))).astype(int)]
            observed.append((name, points))
        def transform(p):
            c,s = np.cos(p[3]),np.sin(p[3])
            rotation = np.array([[c,-s,0],[s,c,0],[0,0,1]])
            return self.local_points @ rotation.T+p[:3]
        def residual(p):
            values = []
            for name,points in observed:
                uv,_ = project(public['calibration'][name], transform(p))
                distances = np.linalg.norm(points[:,None,:]-uv[None,:,:],axis=2)
                # Current mint boundary -> reference material contour; missing
                # occluded model portions do not pull the model toward the hand.
                values.extend(distances.min(1))
            return values
        if len(observed) >= 2:
            result = least_squares(residual, initial, bounds=(initial-np.r_[.08,.08,.08,.35], initial+np.r_[.08,.08,.08,.35]),
                loss='soft_l1', f_scale=2., max_nfev=40)
            estimate = result.x
            rms = float(np.sqrt(np.mean(np.asarray(residual(estimate))**2)))
            covariance = np.linalg.pinv(result.jac.T @ result.jac)*max(1.,rms)**2
            halfwidth = np.maximum(.003, 2*np.sqrt(np.maximum(0,np.diag(covariance)[:3])))
            usable = bool(rms < 3.5 and max(halfwidth) <= .012)
            if usable:
                self.estimate = estimate
            answer = dict(usable=usable, center_m=estimate[:3].tolist(), yaw_delta_rad=float(estimate[3]),
                silhouette_rms_px=rms, conditional_halfwidth_m=halfwidth.tolist(), camera_names=[n for n,_ in observed],
                height_gain_m=float(estimate[2]-self.center0[2]))
        else:
            answer = dict(usable=False, reason='Mint planar tracking requires two current views', camera_names=[n for n,_ in observed])
        answer.update(step=public['step'], source='Current mint material contours, camera K/T, initially RGB-derived planar material shape',
            limits='Flat material and fixed shape/orientation hypotheses; partial occlusion and unmeasured calibration errors are not certified contact evidence.')
        self.last_result = answer
        return answer
