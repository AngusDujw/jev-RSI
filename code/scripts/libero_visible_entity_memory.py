"""Preserve an observed entity through occlusion using public RGB-D only.

The reference is a previously rendered RGB-D/SAM observation, not an asset or
simulator object identity. A current view must provide matching visible points.
"""
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial import cKDTree


def world_cloud(view):
    depth = np.asarray(view['depth'], float)
    k, t = np.asarray(view['K'], float), np.asarray(view['T'], float)
    vv, uu = np.indices(depth.shape)
    camera = np.stack(((uu-k[0, 2])*depth/k[0, 0],
                       (vv-k[1, 2])*depth/k[1, 1], depth), axis=-1)
    return camera @ t[:3, :3].T+t[:3, 3]


class ObservedEntityMemory:
    def __init__(self, reference_folder):
        folder = Path(reference_folder)
        self.geometry = json.loads((folder/'source-geometry.json').read_text())
        mask_path = Path(self.geometry['visible_mask_path'])
        if not mask_path.exists():
            mask_path = folder/'mask-1/segmentation'/mask_path.name
        capture = mask_path.parent.parent
        calibration = json.loads((capture/'calibration.json').read_text())
        self.reference_view = dict(rgb=cv2.cvtColor(cv2.imread(str(capture/'rgb.png')),
            cv2.COLOR_BGR2RGB), depth=np.load(capture/'depth.npy'), **calibration)
        mask = np.load(mask_path).astype(bool)
        good = mask & np.isfinite(self.reference_view['depth']) & (self.reference_view['depth'] > .02)
        self.reference_points = world_cloud(self.reference_view)[good]
        self.reference_chroma = cv2.cvtColor(self.reference_view['rgb'], cv2.COLOR_RGB2LAB)[good, 1:].astype(float)
        if len(self.reference_points) < 80:
            raise RuntimeError('Observed entity reference has insufficient public depth')
        self.tree = cKDTree(self.reference_points)
        self.low, self.high = (np.asarray(self.geometry[k], float) for k in ('low', 'high'))
        self.current_reference_points = self.reference_points.copy()

    def _match(self, view):
        points = world_cloud(view)
        valid = np.isfinite(view['depth']) & (view['depth'] > .02) & (view['depth'] < 3.)
        region = valid & np.all(points >= self.low-.025, axis=-1) & np.all(points <= self.high+.025, axis=-1)
        p = points[region]
        chroma = cv2.cvtColor(view['rgb'], cv2.COLOR_RGB2LAB)[region, 1:].astype(float)
        if len(p) < 80:
            raise RuntimeError('Prior entity region has insufficient current visible depth')
        translation = np.zeros(3)
        for _ in range(5):
            distance, nearest = self.tree.query(p-translation)
            colour = np.linalg.norm(chroma-self.reference_chroma[nearest], axis=1)
            inliers = (distance < .012) & (colour < 30.)
            if int(inliers.sum()) < 80:
                raise RuntimeError('Current depth/appearance does not match observed entity')
            translation = np.median(p[inliers]-self.reference_points[nearest[inliers]], axis=0)
            if np.max(np.abs(translation)) > .025:
                raise RuntimeError('Observed entity displacement exceeds bounded reference tracking')
        distance, nearest = self.tree.query(p-translation)
        colour = np.linalg.norm(chroma-self.reference_chroma[nearest], axis=1)
        inliers = (distance < .004) & (colour < 30.)
        count = int(inliers.sum())
        unique = int(len(np.unique(nearest[inliers])))
        if count < 80 or unique < max(50, int(.01*len(self.reference_points))):
            raise RuntimeError('Insufficient distinct visible reference matches')
        mask = np.zeros(region.shape, bool)
        pixels = np.flatnonzero(region)
        mask.flat[pixels[inliers]] = True
        yy, xx = np.where(mask)
        bbox = [max(0, int(xx.min())-3), max(0, int(yy.min())-3),
                min(mask.shape[1]-1, int(xx.max())+3), min(mask.shape[0]-1, int(yy.max())+3)]
        evidence = dict(visible_matching_pixels=count, matched_reference_points=unique,
            reference_points=int(len(self.reference_points)),
            p90_residual_mm=round(float(np.quantile(distance[inliers], .9))*1000, 3),
            estimated_translation_mm=np.round(translation*1000, 3).tolist(),
            geometry_from='prior observed RGB-D bounds + bounded visible-point translation',
            identity_from='current depth and reference LAB chroma, no simulator identity')
        return mask, bbox, translation, evidence

    def track(self, views, output):
        matches, errors = [], {}
        for camera, view in views.items():
            try:
                mask, bbox, translation, evidence = self._match(view)
                matches.append((evidence['matched_reference_points'], camera, mask, bbox, translation, evidence))
            except RuntimeError as exc:
                errors[camera] = str(exc)
        if not matches:
            raise RuntimeError('Previously observed entity not verified in current RGB-D: '+json.dumps(errors))
        _, camera, mask, bbox, translation, evidence = max(matches, key=lambda row: row[0])
        folder = Path(output)
        folder.mkdir(parents=True, exist_ok=False)
        np.save(folder/'mask.npy', mask)
        view = views[camera]
        cv2.imwrite(str(folder/'rgb.png'), cv2.cvtColor(view['rgb'], cv2.COLOR_RGB2BGR))
        np.save(folder/'depth.npy', view['depth'])
        (folder/'calibration.json').write_text(json.dumps(dict(
            K=np.asarray(view['K']).tolist(), T=np.asarray(view['T']).tolist())))
        geometry = dict(self.geometry, center=np.asarray(self.geometry['center'])+translation,
            low=self.low+translation, high=self.high+translation,
            points=evidence['visible_matching_pixels'], visible_mask_path=str(folder/'mask.npy'),
            source='previously observed entity geometry verified by current RGB-D reference matching')
        self.current_reference_points = self.reference_points+translation
        evidence.update(camera=camera, bbox=bbox, other_view_errors=errors)
        (folder/'evidence.json').write_text(json.dumps(evidence, indent=2))
        return geometry, dict(label=self.geometry['label'], camera=camera, bbox=bbox,
            visible=True, evidence='matched prior public RGB-D entity'), evidence
