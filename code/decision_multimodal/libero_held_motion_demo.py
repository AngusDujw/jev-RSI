"""Record offline held-object motion examples; never a model-policy evaluation.

Replay an explicitly selected archived command prefix, then execute one isolated
own-hand rotation. Only RGB/depth and own robot geometry are recorded. No native
object state, contacts, reward or task-success checker is read.
"""
import argparse
import io
import json
import os
from pathlib import Path
import sys


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--libero-root',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--prefix-execution',type=Path,required=True)
    p.add_argument('--prefix-actions',type=int,required=True)
    p.add_argument('--task',type=int,required=True)
    p.add_argument('--init',type=int,required=True)
    p.add_argument('--axis',choices=('rx','ry','rz'),required=True)
    p.add_argument('--sign',type=int,choices=(-1,1),required=True)
    p.add_argument('--angle-deg',type=float,default=30.)
    args=p.parse_args()
    if not 0<args.angle_deg<=45:raise ValueError('Isolated demonstration angle must be in (0,45].')
    rows=[json.loads(x) for x in args.prefix_execution.read_text().splitlines()]
    if not 1<=args.prefix_actions<=len(rows):raise ValueError('Invalid archive prefix length')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    cache=out/'cache';cache.mkdir()
    os.environ.update(LIBERO_CONFIG_PATH=args.libero_root+'/.libero-config',MUJOCO_GL='egl',
        MUJOCO_EGL_DEVICE_ID='0',TMPDIR=str(cache),XDG_CACHE_HOME=str(cache))
    sys.path.insert(0,args.libero_root)
    import numpy as np
    from scipy.spatial.transform import Rotation
    from PIL import Image,ImageDraw
    from libero.libero import benchmark
    from libero.libero.envs.env_wrapper import ControlEnv
    from robosuite.utils.camera_utils import get_camera_intrinsic_matrix,get_camera_extrinsic_matrix
    from libero_inframe_axes import overlay_gripper_axes

    cameras=['agentview','sideview']
    suite=benchmark.get_benchmark_dict()['libero_goal'](0)
    env=None;tick=0;grip=-1.;records=[]
    result=dict(kind='offline_held_motion_example',model_calls=0,native_evaluated=False,
        task=args.task,init=args.init,axis=args.axis,sign=args.sign,
        requested_rotation_deg=args.sign*args.angle_deg,
        prefix_execution=str(args.prefix_execution.resolve()),prefix_actions=args.prefix_actions,
        source_note='Only archived commands, current RGB and own measured robot state. This is not a policy trial or a current action candidate.')
    try:
        env=ControlEnv(bddl_file_name=suite.get_task_bddl_file_path(args.task),camera_names=cameras,
            camera_heights=512,camera_widths=512,camera_depths=False,control_freq=20,horizon=1200,
            controller='OSC_POSE',initialization_noise=None)
        env.seed(0);env.reset()
        obs=env.set_init_state(np.asarray(suite.get_task_init_states(args.task)[args.init],float))
        native=env.env;site=native.robots[0].eef_site_id

        def pose():
            return native.sim.data.site_xpos[site].copy(),native.sim.data.site_xmat[site].reshape(3,3).copy()

        def execute(dp,dr,steps=12):
            nonlocal obs,tick
            before_p,before_R=pose();target_p=before_p+dp
            target_R=Rotation.from_rotvec(dr).as_matrix()@before_R
            for _ in range(steps):
                now_p,now_R=pose()
                u_p=.7*(target_p-now_p);u_r=.7*Rotation.from_matrix(target_R@now_R.T).as_rotvec()
                obs,_,_,_=env.step(np.r_[np.clip(u_p/.05,-1,1),np.clip(u_r/.5,-1,1),grip]);tick+=1
            after_p,after_R=pose()
            records.append(dict(tick=tick,commanded_translation_mm=(dp*1000).tolist(),
                commanded_rotation_world_deg=np.rad2deg(dr).tolist(),gripper_command='close' if grip>0 else 'open',
                measured_translation_mm=((after_p-before_p)*1000).tolist(),
                measured_rotation_world_deg=np.rad2deg(Rotation.from_matrix(after_R@before_R.T).as_rotvec()).tolist()))

        for _ in range(10):obs,_,_,_=env.step(np.r_[np.zeros(6),grip]);tick+=1
        for row in rows[:args.prefix_actions]:
            command=row['choices']['gripper']
            if command!='hold':grip=1. if command=='close' else -1.
            execute(np.asarray(row['commanded_translation_mm'])/1000,
                np.deg2rad(row['commanded_rotation_world_deg']))
        before_p,before_R=pose();result['before_tick']=tick
        result['prefix_final_own_position_mm']=(before_p*1000).tolist()

        def capture(label):
            images=[];own_p,_=pose()
            for camera in cameras:
                im=Image.fromarray(np.ascontiguousarray(obs[camera+'_image'][::-1]))
                im.save(out/(label+'-'+camera+'-raw.png'))
                K=get_camera_intrinsic_matrix(native.sim,camera,512,512)
                T=get_camera_extrinsic_matrix(native.sim,camera)
                raw=io.BytesIO();im.save(raw,format='PNG')
                marked,_,_=overlay_gripper_axes(raw.getvalue(),T,K,own_p,camera)
                im=Image.open(io.BytesIO(marked)).convert('RGB')
                point=np.linalg.inv(T)@np.r_[own_p,1.]
                uv=K@point[:3];u,v=uv[:2]/uv[2]
                # Own-hand-centred detail only; no scene-object pose or target is used.
                box=(int(u)-140,int(v)-140,int(u)+140,int(v)+140)
                im=im.crop(box).resize((512,512));im.save(out/(label+'-'+camera+'-detail.png'))
                images.append(im)
            return images

        before=capture('before')
        remaining=args.angle_deg
        while remaining>1e-6:
            angle=min(10.,remaining);dr=np.zeros(3)
            dr[('rx','ry','rz').index(args.axis)]=np.deg2rad(args.sign*angle)
            execute(np.zeros(3),dr);remaining-=angle
        after=capture('after');after_p,after_R=pose()
        result.update(after_tick=tick,measured_translation_mm=((after_p-before_p)*1000).tolist(),
            measured_rotation_world_deg=np.rad2deg(Rotation.from_matrix(after_R@before_R.T).as_rotvec()).tolist(),
            object_following='Not certified. Inspect the actual BEFORE/AFTER RGB; no contact or hidden object state is queried.')
        card=Image.new('RGB',(2048,550),'#10222a');draw=ImageDraw.Draw(card)
        draw.text((12,10),f'ARCHIVED HELD-OBJECT EXAMPLE: {args.sign*args.angle_deg:+g} degrees about world {args.axis[-1].upper()} | BEFORE left pair, AFTER right pair',fill='white')
        draw.text((12,28),'Each pair: fixed agentview then fixed sideview. Own-hand-centred crops. Actual recorded motion, not the CURRENT scene or a next-action candidate.',fill='white')
        for index,im in enumerate([*before,*after]):card.paste(im,(index*512,38))
        card.save(out/'example.png')
        result['example_image']='example.png'
    finally:
        (out/'execution.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        if env is not None:env.close()
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
