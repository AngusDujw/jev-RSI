"""Bounded RGB-D LIBERO-Plus development rollouts using existing Jev recorder.
No object poses, segmentation IDs, reward or predicates enter the policy.
"""
import argparse
import contextlib
import io
import os
from pathlib import Path
import sys
import time

import cv2
import numpy as np
from run_position_pilot import Recorder, Jev, dump

ROOT = '/root/yekangjie/project/embodied-jev/.sim/LIBERO-plus'

def perceive(rgb, depth, K, T, held_tcp=None):
    """Task-specific colour/shape frontend, no simulator object data.
    Black bowl silhouette and red plate rim; nearest bowl to plate disambiguates
    the 'between plate and ramekin' task. This is a declared task scaffold.
    """
    vv, uu = np.indices(depth.shape)
    xyz = np.stack([(uu-K[0,2])*depth/K[0,0], (vv-K[1,2])*depth/K[1,1], depth],-1)
    xyz = xyz @ T[:3,:3].T + T[:3,3]
    hsv = cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    # Table level is measured from the broad visible horizontal surface.
    z = xyz[:,:,2]
    area = (z > .6) & (z < 1.1)
    hist, edges = np.histogram(z[area], bins=200, range=(.6,1.1))
    table_z = float((edges[np.argmax(hist)]+edges[np.argmax(hist)+1])/2)
    tabletop = (z > table_z-.004) & (z < table_z+.085)
    red = (((hsv[:,:,0]<12)|(hsv[:,:,0]>170)) & (hsv[:,:,1]>65) & (hsv[:,:,2]>70) & tabletop).astype('uint8')*255
    red = cv2.morphologyEx(red,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_ = cv2.findContours(red,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    plates=[]
    for c in contours:
        x,y,w,h=cv2.boundingRect(c)
        if w>30 and h>20 and .5<h/w<1.3 and cv2.contourArea(c)>300:
            mask=np.zeros(depth.shape,np.uint8); cv2.drawContours(mask,[cv2.convexHull(c)],-1,255,-1)
            pts=xyz[(mask>0)&tabletop]
            plates.append(dict(pixel=[x+w/2,y+h/2],position=np.median(pts,axis=0),area=float(cv2.contourArea(c))))
    if not plates: raise RuntimeError('No unambiguous visible red plate')
    plate=max(plates,key=lambda o:o['area'])
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    object_area=tabletop if held_tcp is None else ((z>held_tcp[2]-.13)&(z<held_tcp[2]-.012)&(np.linalg.norm(xyz[:,:,:2]-held_tcp[:2],axis=2)<.11))
    dark=((gray<85)&object_area).astype('uint8')*255
    dark=cv2.morphologyEx(dark,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(dark,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    bowls=[]
    for c in contours:
        x,y,w,h=cv2.boundingRect(c)
        if 30<w<85 and 12<h<60 and cv2.contourArea(c)>150:
            # Silhouette's top corresponds to bowl rim; include upper ellipse.
            mask=np.zeros(depth.shape,np.uint8)
            cv2.ellipse(mask,(int(x+w/2),int(y+h*.35)),(int(w*.44),int(h*.45)),0,0,360,255,-1)
            pts=xyz[(mask>0)&object_area]
            if len(pts)<60: continue
            center=np.median(pts,axis=0)
            bowls.append(dict(pixel=[x+w/2,y+h*.35],position=center,top=float(np.quantile(pts[:,2],.90)),bbox=[x,y,w,h]))
    if not bowls: raise RuntimeError('No visible bowl')
    anchor=plate['position'] if held_tcp is None else held_tcp
    bowl=min(bowls,key=lambda o:np.linalg.norm(o['position'][:2]-anchor[:2]))
    return dict(bowl=bowl,plate=plate,table_z=table_z,candidates=bowls)


def run_policy(env, obs, rec, task, depth_fn, k_fn, t_fn):
    model=Jev(rec)
    ticks=0
    def snapshot(label):
        rgb=np.ascontiguousarray(obs['agentview_image'][::-1])
        cv2.imwrite(str(rec.folder/(label+'.png')),cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
        if not label.startswith('step-'):
            np.save(rec.folder/(label+'-depth.npy'),depth_fn(env.sim,obs['agentview_depth'])[::-1].squeeze())
    def step(action,n):
        nonlocal obs,ticks
        for _ in range(n):
            rec.check_budget()
            if ticks>=550: raise RuntimeError('native step budget')
            obs,_,_,_=env.step(np.asarray(action,float)); ticks+=1
    try:
        cam='agentview'
        rgb=np.ascontiguousarray(obs[cam+'_image'][::-1])
        depth=depth_fn(env.sim,obs[cam+'_depth'])[::-1].squeeze()
        evidence=perceive(rgb,depth,k_fn(env.sim,cam,384,384),t_fn(env.sim,cam))
        dump(rec.folder/'perception.json',evidence)
        bowl=evidence['bowl']; plate=evidence['plate']; z=evidence['table_z']
        hover=max(bowl['top']+.14,z+.18)
        # TCP offsets are explicit grasp heuristics, not hidden mesh dimensions.
        grasp=np.r_[bowl['position'][:2], bowl['top']-.015]
        carry=np.r_[plate['position'][:2],hover]
        targets=[('approach',np.r_[grasp[:2],hover],-1),('descend',grasp,-1),
                 ('close',None,1),('lift',np.r_[grasp[:2],hover],1),
                 ('carry',carry,1),('lower',np.r_[plate['position'][:2],z+.055],1),
                 ('release',None,-1),('retreat',carry,-1)]
        for stage,target,grip in targets:
            rec.event(dict(kind='stage',stage=stage,target=target.tolist() if target is not None else None))
            if target is None:
                step([0,0,0,0,0,0,grip],16); snapshot(stage); continue
            for iteration in range(30):
                position=obs['robot0_eef_pos'].copy(); error=target-position
                if np.max(np.abs(error))<.006: break
                state=dict(task=task.language,stage=stage,position_m=position.tolist(),target_position_m=target.tolist(),
                      hold_tolerance_m=.004, observation_source='RGB-D initial scene estimate plus live robot feedback',
                      stage_source='external fixed pick-place scaffold',target_source='initial measured RGB-D with declared grasp offsets',
                      error_m=error.tolist(),frame='world XYZ metres',gripper=grip)
                decision=model.choose(state,dict(stage=stage,iteration=iteration,environment='libero_plus'))
                if decision is None: raise RuntimeError('Jev budget exhausted')
                signs=np.asarray(decision['signs'])
                delta=signs*np.minimum(.025,np.abs(error)*.65)
                # OSC_POSE scales normalized translation by .05 m per native step.
                before=position.copy(); step(np.r_[delta/.05,0,0,0,grip],3)
                rec.branch(dict(stage=stage,decision_id=decision['decision_id'],delta=delta,
                                before=before,after=obs['robot0_eef_pos'].copy(),native_steps=ticks))
                snapshot('step-%04d'%ticks)
            else: raise RuntimeError('Stage motion budget exhausted: '+stage)
            snapshot(stage)
            if stage=='lift':
                held=perceive(np.ascontiguousarray(obs[cam+'_image'][::-1]),
                      depth_fn(env.sim,obs[cam+'_depth'])[::-1].squeeze(),
                      k_fn(env.sim,cam,384,384),t_fn(env.sim,cam),obs['robot0_eef_pos'])
                offset=held['bowl']['position'][:2]-obs['robot0_eef_pos'][:2]
                dump(rec.folder/'held-offset.json',dict(evidence=held,offset_xy=offset))
                # Targets retain references in this stage list.
                carry[:2]=plate['position'][:2]-offset
                targets[5][1][:2]=carry[:2]
        # Evaluator-only predicate: never passed into Jev or the action policy.
        success=bool(env.check_success())
        dump(rec.folder/'result.json',dict(success=success,native_steps=ticks,jev_calls=len(rec.decisions),deepseek_calls=0))
        rec.finish('success' if success else 'task_failed')
    except Exception as exc:
        dump(rec.folder/'result.json',dict(success=False,native_steps=ticks,jev_calls=len(rec.decisions),error_type=type(exc).__name__,error=str(exc)))
        rec.finish('failed'); raise
    finally: model.close()

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--capture-only', action='store_true')
    p.add_argument('--task-id', type=int, default=988)
    p.add_argument('--seed', type=int, default=0)
    a = p.parse_args()
    out = Path(a.output).resolve()
    cfg = dict(existing_root='/root/yekangjie/project/robodojo-jev',
               api_config='/root/yekangjie/project/robodojo-jev/controller/config/api.company.local.json',
               wall_limit_seconds=900, output_limit_mb=400, max_jev_decisions=120,
               suite='libero_spatial', task_id=a.task_id, seed=a.seed,
               permissions='RGB-D/calibration/robot feedback; NO object truth', deepseek_calls=0)
    rec = Recorder(out, cfg)
    cache = out / 'cache'; cache.mkdir()
    os.environ.update(LIBERO_CONFIG_PATH=ROOT+'/.libero-config', MUJOCO_GL='egl',
                      MUJOCO_EGL_DEVICE_ID='0', TMPDIR=str(cache), XDG_CACHE_HOME=str(cache))
    sys.path.insert(0, ROOT)
    from libero.libero import benchmark
    from libero.libero.envs.env_wrapper import ControlEnv
    from robosuite.utils.camera_utils import get_real_depth_map, get_camera_intrinsic_matrix, get_camera_extrinsic_matrix
    with contextlib.redirect_stdout(io.StringIO()):
        suite = benchmark.get_benchmark_dict()['libero_spatial'](0)
    task = suite.get_task(a.task_id)
    dump(out/'task.json', dict(name=task.name, language=task.language, bddl=suite.get_task_bddl_file_path(a.task_id)))
    env = None
    try:
        env = ControlEnv(bddl_file_name=suite.get_task_bddl_file_path(a.task_id),
             camera_names=['agentview','robot0_eye_in_hand'], camera_heights=384, camera_widths=384,
             camera_depths=True, control_freq=20, horizon=600, controller='OSC_POSE', initialization_noise=None)
        env.seed(a.seed); env.reset()
        obs = env.set_init_state(np.asarray(suite.get_task_init_states(a.task_id)[0],float))
        for _ in range(10): obs, _, _, _ = env.step(np.array([0.,0.,0.,0.,0.,0.,-1.]))
        for cam in ['agentview','robot0_eye_in_hand']:
            rgb = np.ascontiguousarray(obs[cam+'_image'][::-1])
            depth = get_real_depth_map(env.sim,obs[cam+'_depth'])[::-1].squeeze()
            cv2.imwrite(str(out/(cam+'.png')),cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
            np.save(out/(cam+'-depth.npy'),depth)
            dump(out/(cam+'-calibration.json'),dict(K=get_camera_intrinsic_matrix(env.sim,cam,384,384),T=get_camera_extrinsic_matrix(env.sim,cam)))
        dump(out/'robot.json',dict(position=obs['robot0_eef_pos'],quaternion=obs['robot0_eef_quat']))
        if a.capture_only:
            rec.finish('capture_only'); return
        run_policy(env, obs, rec, task, get_real_depth_map, get_camera_intrinsic_matrix, get_camera_extrinsic_matrix)

    finally:
        if env is not None: env.close()

if __name__ == '__main__': main()
