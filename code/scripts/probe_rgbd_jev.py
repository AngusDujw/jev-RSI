"""Offline sensor-to-Jev smoke test; audit truth is loaded AFTER vision requests.

GroundingDINO+SAM2 yields approximate mask contours. Depth lifts their eroded
interiors into metric visible surfaces, not hidden object centers or full poses.
"""
import argparse
import json
from pathlib import Path
import sys
import cv2
import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation
from run_position_pilot import Recorder, Jev, dump, state_for, direction_metrics


def lift(depth, intrinsic, camera_to_world, origin, mask):
    valid = mask & np.isfinite(depth) & (depth > .05) & (depth < 3.)
    y, x = np.where(valid)
    if len(x) < 12:
        raise ValueError('Too few valid depth pixels')
    rays = np.stack([x, y, np.ones_like(x)], axis=1) @ np.linalg.inv(intrinsic).T
    optical = rays * depth[y, x, None]
    camera = optical * [1., -1., -1.]
    world = camera @ camera_to_world[:3, :3].T + camera_to_world[:3, 3] - origin
    return world


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture', type=Path, required=True)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cfg = json.loads(a.config.read_text())
    cfg['max_jev_decisions'] = 30
    rec = Recorder(a.output, cfg)
    root = Path(cfg['existing_root'])
    sys.path.insert(0, str(root/'controller/src'))
    from realman_jev.robodojo_rgb import RGBEvidence
    observation = json.loads((a.capture/'rgbd_capture.json').read_text())
    vcfg = json.loads((root/'controller/config/company-stack-study.json').read_text())['vision']
    vcfg.update(device='cuda:0', phrases=['block'], include_instruction=False, max_instances=8)
    dump(rec.folder/'perception_config.json', vcfg)
    obs = dict(observation['robot'], instruction=observation['instruction'])
    for k, v in observation['cameras'].items():
        obs[k] = np.asarray(Image.open(a.capture/v['rgb_file']).convert('RGB'))
    detector = RGBEvidence(vcfg)
    evidence = detector.observe(obs)
    dump(rec.folder/'rgb_evidence.json', evidence)
    view = observation['cameras']['cam_high']
    depth = np.load(a.capture/view['depth_file'])
    image = obs['cam_high'].copy()
    h, w = depth.shape
    objects = []
    for detection in evidence['views']['cam_high']['objects']:
        polygon = np.rint(np.asarray(detection['contour_uv01'])*[w,h]).astype(np.int32)
        mask = np.zeros((h,w), dtype=np.uint8)
        cv2.fillPoly(mask, [polygon], 1)
        mask = cv2.erode(mask, np.ones((3,3), dtype=np.uint8)).astype(bool)
        points = lift(depth, np.asarray(view['intrinsic']), np.asarray(view['camera_to_world_opengl']),
                      np.asarray(observation['env_origin']), mask)
        top_z = float(np.quantile(points[:,2], .9))
        top_points = points[np.abs(points[:,2]-top_z)<.005]
        if len(top_points)<8:
            top_points = points
        top_xy = (np.quantile(top_points[:,:2], .1, axis=0)+np.quantile(top_points[:,:2], .9, axis=0))/2
        target = np.r_[top_xy, top_z+.05]
        obj = dict(id=detection['id'], score=detection['confidence'],
            visible_surface_top_m=np.r_[top_xy,top_z].tolist(), approach_target_m=target.tolist(),
            valid_depth_pixels=len(points), visible_spread_m=np.ptp(points,axis=0).tolist(),
            source='RGB contour plus depth; top-surface estimate, not hidden center',
            contour_uv01=detection['contour_uv01'])
        objects.append(obj)
        cv2.polylines(image, [polygon], True, (0,255,0), 2)
        cv2.putText(image, obj['id'], tuple(polygon[0]), cv2.FONT_HERSHEY_SIMPLEX, .4, (0,255,0), 1)
    Image.fromarray(image).save(rec.folder/'detections.png')
    dump(rec.folder/'visual_objects.json', objects)
    model = Jev(rec)
    status = 'completed'
    try:
        decisions = []
        for obj in objects:
            i = int(obj['approach_target_m'][0]>=0)
            q = np.asarray(obs['eef_quaternions_wxyz'][i])
            position = np.asarray(obs['eef_positions'][i])+Rotation.from_quat(q[[1,2,3,0]]).apply([observation['gripper_bias_m'][i],0,0])
            state = state_for(position, obj['approach_target_m'], 'approach', cfg,
                visual_estimate=obj, gripper_opening=float(obs['states'][i*7+6]))
            state.update(observation_source='RGB_D_estimated_object_plus_robot_feedback',
                         coordinate_frame='environment_origin_nominal_grasp_m')
            decision = model.choose(state, dict(stage='approach', environment='robodojo',
                trajectory_id=a.capture.name, object_id=obj['id'], observation_mode='rgbd'))
            decisions.append((obj, position, decision))
        # Independent evaluator: no audit field is inserted into visual requests.
        from realman_jev.company_geometry import add_block_geometry
        audit = json.loads((a.capture/'simulator/audit_only/initial.json').read_text())
        case = json.loads((a.capture/'case.json').read_text())
        layout = root/'robodojo'/case['layout']
        add_block_geometry(audit, layout.parents[4]/'Object/RoboDojo', layout)
        truth = []
        for obj in audit['objects']:
            if obj.get('category') == 'block':
                lo, hi = np.asarray(obj['geometry']['world_bbox_min_m']), np.asarray(obj['geometry']['world_bbox_max_m'])
                truth.append((obj['id'], np.r_[(lo[:2]+hi[:2])/2, hi[2]+.05]))
        from scipy.optimize import linear_sum_assignment
        report = dict(detections=len(objects), truth_objects=len(truth), comparisons=[],
                      scope='Initial-frame approach only; no physical actions, no whole-task visual success',
                      matching='Evaluator-only one-to-one nearest 3D approach targets, 80mm gate')
        if decisions and truth:
            cost = np.array([[np.linalg.norm(np.asarray(o['approach_target_m'])-t) for _,t in truth] for o,_,_ in decisions])
            ri, ci = linear_sum_assignment(cost)
            for r,c in zip(ri,ci):
                if cost[r,c]>.08:
                    continue
                obj, position, decision = decisions[r]
                tid, target = truth[c]
                reference = direction_metrics(position, target, decision['signs'], cfg['axis_tolerance_m'])
                report['comparisons'].append(dict(visual_id=obj['id'], audit_id=tid,
                    target_error_mm=float(cost[r,c]*1000), decision_id=decision['decision_id'],
                    true_target_metrics=reference, visual_input_metrics=decision['metrics']))
        report['unmatched_truth'] = len(truth)-len(report['comparisons'])
        report['unmatched_detections'] = len(objects)-len(report['comparisons'])
        dump(rec.folder/'audit_metrics.json', report)
        print(json.dumps(report, default=lambda x:x.tolist()), flush=True)
    except Exception as exc:
        status='failed'
        rec.errors.append(dict(type=type(exc).__name__, error=str(exc)))
        raise
    finally:
        model.close()
        rec.finish(status)


if __name__ == '__main__':
    main()
