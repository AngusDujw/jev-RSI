"""Visible shirt-outline landmarks, with conservative shape rejection.

Labels describe inferred visible silhouette roles, not simulator cloth vertices.
No model calls or scene constants. Points must remain inside current RGB mask.
"""
import cv2
import numpy as np


def outline_landmarks(polygon, shape):
    h,w = shape
    poly = np.asarray(polygon,float)*[w-1,h-1]
    mask = np.zeros((h,w), np.uint8)
    cv2.fillPoly(mask,[np.rint(poly).astype(np.int32)],1)
    y,x = np.where(mask)
    if len(x)<150 or np.ptp(x)<40 or np.ptp(y)<40:
        return {}
    # Overview image: find body column by maximum vertical occupied span.
    columns = [(int(xx),int(y[x==xx].min()),int(y[x==xx].max())) for xx in np.unique(x)]
    spans = np.asarray([b-a for _,a,b in columns])
    body = [r for r,s in zip(columns,spans) if s>=.83*spans.max()]
    if not body:
        return {}
    center_x = float(np.median([r[0] for r in body]))
    neck_y = float(np.quantile(y,.03)); hem_y = float(np.quantile(y,.92))
    height = hem_y-neck_y
    if height<40:
        return {}
    # Two cuff extremities and torso hem/shoulders are visible-role hypotheses.
    def interior(point):
        distance = (x-point[0])**2+(y-point[1])**2
        nearest = np.argmin(distance)
        px,py = float(x[nearest]),float(y[nearest])
        # Inset at most three pixels into the current connected foreground.
        dt = cv2.distanceTransform(mask,cv2.DIST_L2,3)
        near = (np.abs(x-px)<7)&(np.abs(y-py)<7)&(dt[y,x]>=2)
        if near.any():
            ii = np.where(near)[0][np.argmin(distance[near])]
            px,py = float(x[ii]),float(y[ii])
        return np.asarray([px/(w-1),py/(h-1)])
    left = np.where(x<=np.quantile(x,.025))[0];right=np.where(x>=np.quantile(x,.975))[0]
    points = {'left_cuff':interior([np.median(x[left]),np.median(y[left])]),
              'right_cuff':interior([np.median(x[right]),np.median(y[right])])}
    shoulder_y = neck_y+.19*height
    body_width = max(24,float(np.ptp([r[0] for r in body])))
    for side,sign in [('left',-1),('right',1)]:
        points[side+'_shoulder'] = interior([center_x+sign*.40*body_width,shoulder_y])
        points[side+'_hem'] = interior([center_x+sign*.42*body_width,hem_y])
    cuff_span = abs(points['left_cuff'][0]-points['right_cuff'][0])
    hem_span = abs(points['left_hem'][0]-points['right_hem'][0])
    if cuff_span<1.4*hem_span or hem_span<.04:
        return {}  # No reliable unfolded-shirt silhouette; do not invent roles.
    return {k:v.tolist() for k,v in points.items()}


def add_landmarks(observation, measured):
    view = measured.get('views',{}).get('cam_high')
    if view is None:
        return
    shape = np.asarray(observation['cameras']['cam_high']['rgb']).shape[:2]
    for row in view['objects']:
        if row['category'] != 'cloth':
            continue
        keys = outline_landmarks(row['polygon_uv01'],shape)
        if keys:
            row.setdefault('keypoints',{}).update(keys)
            row['source'] = 'current segmented visible shirt silhouette; heuristic landmarks, not cloth vertices'
