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
    object_area=tabletop if held_tcp is None else ((z>held_tcp[2]-.13)&(z<held_tcp[2]+.020)&(np.linalg.norm(xyz[:,:,:2]-held_tcp[:2],axis=2)<.11))
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


def select_transfer_target(evidence, rgb, depth, K, T, relation):
    """Declared task-specific selector, no hidden object metadata.
    Ramekin: small achromatic circular vessel; center: image-center heuristic.
    """
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    rim=(hsv[:,:,0]>15)&(hsv[:,:,0]<45)&(hsv[:,:,1]>85)&(hsv[:,:,2]>65)
    bowls=[]
    for b in evidence['candidates']:
        x,y,w,h=b['bbox']
        if w/h>1.2 and int(rim[max(0,y-15):y+h+5,max(0,x-5):x+w+5].sum())>=2:
            bowls.append(b)
    if not bowls: raise RuntimeError('No bowl candidate with visible coloured rim')
    reference=None
    if relation=='near_ramekin':
        circles=cv2.HoughCircles(cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY),cv2.HOUGH_GRADIENT,1,24,
                                param1=80,param2=22,minRadius=10,maxRadius=23)
        refs=[]
        for u,v,r in ([] if circles is None else circles[0]):
            u,v=int(u),int(v);d=float(depth[v,u])
            pt=T[:3,:3]@np.array([(u-K[0,2])*d/K[0,0],(v-K[1,2])*d/K[1,1],d])+T[:3,3]
            if not evidence['table_z']-.005<pt[2]<evidence['table_z']+.085: continue
            if any(np.linalg.norm(np.array(b['pixel'])-[u,v])<r+15 for b in bowls):continue
            if np.linalg.norm(np.array(evidence['plate']['pixel'])-[u,v])<60:continue
            y0,y1=max(0,v-8),min(rgb.shape[0],v+8);x0,x1=max(0,u-8),min(rgb.shape[1],u+8)
            saturation=float(np.median(hsv[y0:y1,x0:x1,1]));value=float(np.median(hsv[y0:y1,x0:x1,2]))
            if saturation<45 and value>85:refs.append(dict(pixel=[u,v],position=pt,saturation=saturation))
        if len(refs)!=1:raise RuntimeError('Ramekin circular detection missing or ambiguous')
        reference=refs[0];bowl=min(bowls,key=lambda b:np.linalg.norm(b['position'][:2]-reference['position'][:2]))
    elif relation=='table_center':
        reference=dict(pixel=[rgb.shape[1]/2,rgb.shape[0]/2],note='image-center heuristic, not metric table-center guarantee')
        bowl=min(bowls,key=lambda b:np.linalg.norm(np.array(b['pixel'])-reference['pixel']))
    elif relation=='near_plate':
        reference=evidence['plate'];bowl=min(bowls,key=lambda b:np.linalg.norm(b['position'][:2]-reference['position'][:2]))
    else: raise ValueError('Unknown transfer relation')
    return dict(evidence,bowl=bowl,candidates=bowls,relation=relation,reference=reference,
                selection_source='external RGB-D colour/shape and relation scaffold')


def held_rim(rgb, depth, K, T, tcp, minimum_points=80):
    """Fit visible yellow/olive bowl rim in world XY. Task-specific appearance.
    Fresh camera pose, trimmed-depth points, radius/residual/arc checks; no truth.
    """
    vv,uu=np.indices(depth.shape)
    points=np.stack([(uu-K[0,2])*depth/K[0,0],(vv-K[1,2])*depth/K[1,1],depth],-1)@T[:3,:3].T+T[:3,3]
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    mask=((hsv[:,:,0]>15)&(hsv[:,:,0]<45)&(hsv[:,:,1]>85)&(hsv[:,:,2]>65)
          &(points[:,:,2]>tcp[2]-.08)&(points[:,:,2]<tcp[2]+.08)
          &(np.linalg.norm(points[:,:,:2]-tcp[:2],axis=2)<.18))
    pts=points[mask]
    if len(pts)<minimum_points: raise RuntimeError('Insufficient visible held rim points')
    bounds=np.quantile(pts[:,2],[.2,.8]); pts=pts[(pts[:,2]>=bounds[0])&(pts[:,2]<=bounds[1])]
    xy=pts[:,:2]; fit=np.linalg.lstsq(np.c_[2*xy,np.ones(len(xy))],(xy*xy).sum(axis=1),rcond=None)[0]
    radius=float(np.sqrt(max(0,fit[2]+sum(fit[:2]**2))))
    residual=float(np.std(np.linalg.norm(xy-fit[:2],axis=1)))
    angles=np.sort(np.arctan2(xy[:,1]-fit[1],xy[:,0]-fit[0])); arc=float(2*np.pi-np.max(np.diff(np.r_[angles,angles[0]+2*np.pi])))
    if not (.025<radius<.09 and residual<.005 and arc>.7 and np.linalg.norm(fit[:2]-tcp[:2])<.10):
        raise RuntimeError('Held rim fit failed geometric quality bounds')
    return dict(center_xy=fit[:2],radius_m=radius,residual_m=residual,arc_radians=arc,
                points=len(pts),offset_xy=fit[:2]-tcp[:2],source='RGB-D visible rim circle; task-specific colour prior')


def run_policy(env, obs, rec, task, depth_fn, k_fn, t_fn):
    model=Jev(rec)
    ticks=0
    def snapshot(label):
        for camera,suffix in [('agentview',''),('robot0_eye_in_hand','-wrist')]:
            rgb=np.ascontiguousarray(obs[camera+'_image'][::-1])
            cv2.imwrite(str(rec.folder/(label+suffix+'.png')),cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
            if not label.startswith('step-'):
                np.save(rec.folder/(label+suffix+'-depth.npy'),depth_fn(env.sim,obs[camera+'_depth'])[::-1].squeeze())
                dump(rec.folder/(label+suffix+'-calibration.json'),dict(K=k_fn(env.sim,camera,384,384),T=t_fn(env.sim,camera),tcp=obs['robot0_eef_pos']))
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
        if rec.cfg.get('relation'):
            evidence=select_transfer_target(evidence,rgb,depth,k_fn(env.sim,cam,384,384),t_fn(env.sim,cam),rec.cfg['relation'])
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
            for iteration in range(40):
                position=obs['robot0_eef_pos'].copy(); error=target-position
                if np.max(np.abs(error))<.006: break
                state=dict(task=task.language,stage=stage,position_m=position.tolist(),target_position_m=target.tolist(),
                      hold_tolerance_m=.004, observation_source='external initial RGB-D; wrist rim offset after lift/carry; live robot feedback',
                      stage_source='external fixed pick-place scaffold',target_source='RGB-D plate and wrist held-rim compensation with declared grasp offsets',
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
            else:
                if np.max(np.abs(target-obs['robot0_eef_pos'])) >= .006:
                    raise RuntimeError('Stage motion budget exhausted: '+stage)
            snapshot(stage)
            if stage in ('lift','carry'):
                estimates={}
                for view,minimum in [('robot0_eye_in_hand',80),('agentview',8)]:
                    try:
                        estimates[view]=held_rim(np.ascontiguousarray(obs[view+'_image'][::-1]),
                            depth_fn(env.sim,obs[view+'_depth'])[::-1].squeeze(),
                            k_fn(env.sim,view,384,384),t_fn(env.sim,view),obs['robot0_eef_pos'],minimum)
                    except RuntimeError as exc: estimates[view]=dict(error=str(exc))
                wrist=estimates['robot0_eye_in_hand']; external=estimates['agentview']
                dump(rec.folder/(stage+'-rim.json'),estimates)
                if 'error' in wrist: raise RuntimeError('Wrist held rim unavailable: '+wrist['error'])
                if 'error' not in external and np.linalg.norm(wrist['center_xy']-external['center_xy'])>.020:
                    raise RuntimeError('Cross-view bowl center disagreement exceeds 20mm')
                offset=wrist['offset_xy']
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
    p.add_argument('--drawer-supervisor', action='store_true',
                   help='Jev-controlled visible-handle Goal 1098 init0 drawer trial')
    p.add_argument('--drawer-contact-mode', choices=['pinch', 'hook'], default='pinch',
                   help='Fixed public-vision handle contact method; Jev still selects gripper and stages')
    p.add_argument('--offline-goal-vision', action='store_true',
                   help='Use predeclared init0 Goal image boxes and runtime RGB-D/SAM; no GPT-6 calls')
    p.add_argument('--local-goal-vision', action='store_true',
                   help='Use local RGB GroundingDINO/SAM for public Goal nouns and fixed visible fixture regions; no GPT-6 calls')
    p.add_argument('--recovery-supervisor', action='store_true')
    p.add_argument('--push-supervisor', action='store_true',
                   help='Visible RGB-D contact pushing with model-owned gripper and phase edges')
    p.add_argument('--goal-plate-push', action='store_true',
                   help='Task 1296 visible plate/stove/table geometry with runtime Jev push decisions')
    p.add_argument('--input-organization', choices=['contract','evidence','local','focused'], default='contract')
    p.add_argument('--grasp-algorithm', choices=['legacy_clearance','pad_fit'], default='pad_fit')
    p.add_argument('--contact-angle-deg',type=float,default=0.)
    p.add_argument('--pad-overlap-mm',type=float,default=6.)
    p.add_argument('--table-margin-mm',type=float,default=1.)
    p.add_argument('--preserve-source',action='store_true')
    p.add_argument('--allow-retry',action='store_true')
    p.add_argument('--execution-profile',choices=['baseline','adaptive'],default='baseline')
    p.add_argument('--jev-supervisor', dest='jev_supervisor',action='store_true',default=True)
    p.add_argument('--scripted-supervisor',dest='jev_supervisor',action='store_false',help='Historical automatic gripper/phase policy; reproduction only')
    p.add_argument('--max-jev-decisions',type=int,default=120)
    p.add_argument('--wall-limit-seconds',type=int,default=900)
    p.add_argument('--schema', choices=['numeric','feedback'], default='feedback')
    p.add_argument('--grasp-fraction', type=float, default=.4)
    p.add_argument('--geometry-profile',choices=['base','observed_surfaces'],default='base')
    p.add_argument('--generic-vision', dest='generic_vision', action='store_true', default=True)
    p.add_argument('--legacy-vision', dest='generic_vision', action='store_false', help='Reproduce archived task-specific colour/rim policy only')
    p.add_argument('--task-id', type=int, default=988)
    p.add_argument('--lift-check',action='store_true')
    p.add_argument('--approach-mode',choices=['top','side','angled'],default='top')
    p.add_argument('--camera-size',type=int,choices=[384,768],default=384)
    p.add_argument('--suite', choices=['libero_spatial','libero_object','libero_goal','libero_10'], default='libero_spatial')
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--init-index', type=int, default=0)
    p.add_argument('--relation', choices=['near_ramekin','table_center','near_plate'])
    a = p.parse_args()
    if a.offline_goal_vision and (a.suite != 'libero_goal' or a.init_index != 0 or a.camera_size != 768):
        p.error('--offline-goal-vision requires libero_goal init0 at 768x768')
    if a.local_goal_vision and (a.offline_goal_vision or a.suite != 'libero_goal' or
                                a.task_id not in (1144, 1163, 1252, 1335, 1423, 1458) or
                                a.camera_size != 768 or
                                os.environ.get('JEV_RSI_MODEL_BACKEND') != 'jev'):
        p.error('--local-goal-vision requires a supported Goal task, 768px and Jev backend')
    if a.drawer_supervisor and (a.suite != 'libero_goal' or a.task_id != 1098 or
                                a.init_index != 0 or a.camera_size != 768 or
                                os.environ.get('JEV_RSI_MODEL_BACKEND') == 'codex_pro'):
        p.error('--drawer-supervisor requires Goal 1098 init0, 768px, and Jev backend')
    if a.goal_plate_push and (not a.push_supervisor or a.suite != 'libero_goal' or
                              a.task_id != 1296 or a.camera_size != 768 or
                              os.environ.get('JEV_RSI_MODEL_BACKEND') != 'jev'):
        p.error('--goal-plate-push requires --push-supervisor Goal 1296, 768px, Jev backend')
    out = Path(a.output).resolve()
    cfg = dict(existing_root='/root/yekangjie/project/robodojo-jev',
               api_config='/root/yekangjie/project/robodojo-jev/controller/config/api.company.local.json',
               wall_limit_seconds=a.wall_limit_seconds, output_limit_mb=600 if a.recovery_supervisor or a.push_supervisor else 400, max_jev_decisions=a.max_jev_decisions,
               suite=a.suite, task_id=a.task_id, seed=a.seed, init_index=a.init_index, relation=a.relation,
               permissions='RGB-D/calibration/robot feedback; NO object truth', deepseek_calls=0, generic_vision=a.generic_vision, supervisor=a.jev_supervisor, schema=a.schema, grasp_fraction=a.grasp_fraction, geometry_profile=a.geometry_profile, camera_size=a.camera_size,approach_mode=a.approach_mode,lift_check=a.lift_check, recovery_supervisor=a.recovery_supervisor,push_supervisor=a.push_supervisor,drawer_contact_mode=a.drawer_contact_mode,goal_plate_push=a.goal_plate_push,input_organization=a.input_organization,grasp_algorithm=a.grasp_algorithm,contact_angle_deg=a.contact_angle_deg,pad_overlap_mm=a.pad_overlap_mm,table_margin_mm=a.table_margin_mm,preserve_source=a.preserve_source,allow_retry=a.allow_retry,execution_profile=a.execution_profile,offline_goal_vision=a.offline_goal_vision,local_goal_vision=a.local_goal_vision)
    rec = Recorder(out, cfg)
    cache = out / 'cache'; cache.mkdir()
    os.environ.update(LIBERO_CONFIG_PATH=ROOT+'/.libero-config', MUJOCO_GL='egl',
                      TMPDIR=str(cache), XDG_CACHE_HOME=str(cache))
    os.environ.setdefault('MUJOCO_EGL_DEVICE_ID', '0')
    sys.path.insert(0, ROOT)
    from libero.libero import benchmark
    from libero.libero.envs.env_wrapper import ControlEnv
    from robosuite.utils.camera_utils import get_real_depth_map, get_camera_intrinsic_matrix, get_camera_extrinsic_matrix
    with contextlib.redirect_stdout(io.StringIO()):
        suite = benchmark.get_benchmark_dict()[a.suite](0)
    task = suite.get_task(a.task_id)
    dump(out/'task.json', dict(name=task.name, language=task.language, bddl=suite.get_task_bddl_file_path(a.task_id)))
    env = None
    try:
        env = ControlEnv(bddl_file_name=suite.get_task_bddl_file_path(a.task_id),
             camera_names=['agentview','robot0_eye_in_hand'], camera_heights=a.camera_size, camera_widths=a.camera_size,
             camera_depths=True, control_freq=20, horizon=600, controller='OSC_POSE', initialization_noise=None)
        env.seed(a.seed); env.reset()
        obs = env.set_init_state(np.asarray(suite.get_task_init_states(a.task_id)[a.init_index],float))
        for _ in range(10): obs, _, _, _ = env.step(np.array([0.,0.,0.,0.,0.,0.,-1.]))
        for cam in ['agentview','robot0_eye_in_hand']:
            rgb = np.ascontiguousarray(obs[cam+'_image'][::-1])
            depth = get_real_depth_map(env.sim,obs[cam+'_depth'])[::-1].squeeze()
            cv2.imwrite(str(out/(cam+'.png')),cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
            np.save(out/(cam+'-depth.npy'),depth)
            dump(out/(cam+'-calibration.json'),dict(K=get_camera_intrinsic_matrix(env.sim,cam,a.camera_size,a.camera_size),T=get_camera_extrinsic_matrix(env.sim,cam)))
        dump(out/'robot.json',dict(position=obs['robot0_eef_pos'],quaternion=obs['robot0_eef_quat']))
        if a.capture_only:
            rec.finish('capture_only'); return
        if a.drawer_supervisor:
            from libero_goal_drawer_control import run_drawer
            run_drawer(env,obs,rec,task,get_real_depth_map,get_camera_intrinsic_matrix,get_camera_extrinsic_matrix)
        elif a.push_supervisor:
            from libero_push_control import run_push
            run_push(env,obs,rec,task,get_real_depth_map,get_camera_intrinsic_matrix,get_camera_extrinsic_matrix)
        elif a.recovery_supervisor:
            from libero_jev_recovery import run_recovery
            run_recovery(env,obs,rec,task,get_real_depth_map,get_camera_intrinsic_matrix,get_camera_extrinsic_matrix)
        elif a.jev_supervisor and a.generic_vision:
            from libero_jev_supervisor import run_supervisor
            run_supervisor(env,obs,rec,task,get_real_depth_map,get_camera_intrinsic_matrix,get_camera_extrinsic_matrix)
        elif a.generic_vision:
            from libero_generic_vision import run_generic
            run_generic(env,obs,rec,task,get_real_depth_map,get_camera_intrinsic_matrix,get_camera_extrinsic_matrix)
        else:
            run_policy(env, obs, rec, task, get_real_depth_map, get_camera_intrinsic_matrix, get_camera_extrinsic_matrix)

    finally:
        if env is not None: env.close()

if __name__ == '__main__': main()
