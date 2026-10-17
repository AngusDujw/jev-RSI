"""Single-plan, raw-three-RGB RoboDojo baseline. No scene truth reaches models."""
import argparse
import importlib
import json
import os
from pathlib import Path
import sys
import traceback
import time
import types

import numpy as np
import cv2  # Pin the environment's compatible binary before Kit adjusts sys.path.
import rtree  # Pin the project wheel, including its libspatialindex, before Kit.
from models import call, dump, english
from kinematics import solve_tcp

AXES = ('x','y','z','yaw','pitch','roll')
CHOICES = {a:['negative','hold','positive'] for a in AXES}
CHOICES.update(gripper=['open','close','keep'], stage_progress=['continue','advance'])
SCHEMA = dict(type='object', properties={k:dict(type='string',enum=v) for k,v in CHOICES.items()},
              required=list(CHOICES), additionalProperties=False)
QUESTIONS = {a:dict(type='choice', instructions=f'Which world-{w} {a} '+('translation' if a in AXES[:3] else 'rotation')+
                ' direction should the controlled TCP take to advance the current stage?',
                criteria=dict(negative='Decrease coordinate or negative rotation.',hold='No displacement or rotation.',positive='Increase coordinate or positive rotation.'))
             for a,w in zip(AXES,('X','Y','Z','Z','X','Y'))}
QUESTIONS['gripper'] = dict(type='choice',instructions='Should the controlled gripper open, close, or keep its current command to advance the current stage?',
                criteria=dict(open='Command open.',close='Command close.',keep='Preserve the current commanded target.'))
QUESTIONS['stage_progress'] = dict(type='choice',instructions="Is the current stage's completion condition satisfied by the current observations, so that the plan should advance?",
                criteria=dict(continue_='The stage is not complete.',advance='The condition is satisfied. Set all motion channels to hold and gripper to keep.'))
QUESTIONS['stage_progress']['criteria']['continue'] = QUESTIONS['stage_progress']['criteria'].pop('continue_')


def block(path, start, end):
    return path.read_text().split(start,1)[1].split(end,1)[0].strip()


def main():
    from isaaclab.app import AppLauncher
    parser = argparse.ArgumentParser()
    parser.add_argument('--task',required=True)
    parser.add_argument('--layout',type=int,default=0)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--decision-budget',type=int,default=240)
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    args.headless,args.enable_cameras = True,True
    app = AppLauncher(args).app
    session = env = None
    try:
        from isaacsim.core.utils.extensions import enable_extension
        enable_extension('isaacsim.sensors.camera')
        enable_extension('isaacsim.replicator.behavior')
        import carb
        settings = carb.settings.get_settings()
        for k,v in [('/physics/updateToUsd',True),('/app/renderer/waitIdle',True),('/app/hydraEngine/waitIdle',True)]:
            settings.set_bool(k,v)
        settings.set_int('/app/updateOrder/checkForHydraRenderComplete',1000)
        from omegaconf import OmegaConf
        from scipy.spatial.transform import Rotation as R, Slerp
        from PIL import Image
        from env.global_configs import ENV_CONFIG_PATH, ROOT_DIR, BENCHMARK
        sys.path.insert(0,str(Path(ROOT_DIR)/'XPolicyLab'))
        import utils
        utils.__path__=[str(Path(ROOT_DIR)/'utils')]
        from utils.load_file import load_yaml
        from utils.pipeline_utils import process_config, process_randomization
        # Native RobotManager eagerly imports cuRobo even with need_planner=False.
        # Fail closed if this disabled optional component is ever constructed.
        disabled=types.ModuleType('env.planner_manager.curobo_planner')
        class DisabledCuroboPlanner:
            def __init__(self,*unused_args,**unused_kwargs):
                raise RuntimeError('cuRobo is disabled; only measured-robot IK is allowed in this adapter')
        disabled.CuroboPlanner=DisabledCuroboPlanner
        sys.modules[disabled.__name__]=disabled
        from src.eval_client import eval_env
        from hybrid_rollout.robodojo.robodojo_server.server import NoPolicyConnection
        from hybrid_rollout.robodojo.robodojo_server.session import RoboDojoSession,CAMERAS
        registry=importlib.import_module(f'task.{BENCHMARK}.task_registry')
        root=Path(ENV_CONFIG_PATH)
        ev=load_yaml(str(root/'arx_x5.yml'))
        ev.update(task_name=args.task,num_envs=1,device_id=0,eval_batch=False,policy_name='Pi_05',
                  additional_info='planner_advancer_raw_v1',seed=0,physx_monitor_enabled=False)
        values={k:load_yaml(str(root/k/(ev['config'][k]+'.yml'))) for k in ('sim','scene','camera','robot')}
        values.update(eval_cfg=ev,deploy_cfg=dict(port=1,policy_name='Pi_05'),
                      task_env=load_yaml(registry.task_config_path(str(Path(ROOT_DIR)/'task'/BENCHMARK/'config'),args.task)))
        cfg=process_randomization(OmegaConf.create(values))
        cfg,_=process_config(cfg,task_name=args.task)
        cfg.eval_cfg.eval_num=1
        cfg.sim.scene.num_envs=1
        cfg.camera.default_frequency=cfg.eval_cfg.observation.collect_freq
        cfg.sim.seed=[0]
        cfg.sim.device='cpu'
        cfg.sim.use_fabric=False
        for robot in cfg.robot.robots:
            robot.need_planner=False
        old=eval_env.WsModelClient
        try:
            eval_env.WsModelClient=NoPolicyConnection
            env=eval_env.create_eval_env(cfg,app)
        finally:
            eval_env.WsModelClient=old
        session=RoboDojoSession(env,args.output/'native',args.task)
        session.reset(args.layout,'planner_advancer','raw-three-rgb-v1')
        kin=session.kinematics
        offset=np.array([.15007,0.,0.])
        dump(args.output/'robot_public_geometry.json',{arm:dict(root=kin.root(arm).tolist(),
            joint_names=kin.robots[arm].arm_joints_name,urdf=str(kin.robots[arm].urdf_path),
            limits=kin.manager.robot_key[kin.manager.robot_list.index(kin.robots[arm])].data.soft_joint_pos_limits[0,kin.robots[arm].arm_joint_indices].cpu().numpy().tolist())
            for arm in ('left','right')})
        grip={a:float(session.obs['states'][i]) for a,i in [('left',6),('right',13)]}
        code=Path(__file__).resolve().parents[1]
        shared=block(code/'contracts/tcp_action_interface.draft.md','<!-- SHARED_ACTION_DESCRIPTION_START -->','<!-- SHARED_ACTION_DESCRIPTION_END -->')
        role=block(code/'contracts/advancer_baseline.draft.md','```text','```')
        planner_role=block(code/'contracts/planner_prompt.draft.md','```text','```')

        def pose(arm,q=None):
            i=0 if arm=='left' else 7
            q=np.array(session.obs['states'][i:i+6],float) if q is None else q
            t=kin.root(arm)@kin.fk[arm].matrix(q)
            t[:3,3]+=t[:3,:3]@offset
            return t

        def observe(label):
            folder=args.output/'observations'/label
            folder.mkdir(parents=True,exist_ok=False)
            images={}
            for name in CAMERAS:
                p=folder/(name+'.png')
                Image.fromarray(session.obs[name]).save(p)
                images[name]=p
            state={}
            for arm,i in [('left',0),('right',7)]:
                t=pose(arm)
                state[arm]=dict(tcp_position_world_m=t[:3,3].tolist(),tcp_rotation_world_from_tool=t[:3,:3].tolist(),
                    arm_joints_rad=session.obs['states'][i:i+6].tolist(),
                    measured_gripper_native_state=float(session.obs['states'][i+6]),
                    commanded_gripper_target=grip[arm])
            state['definitions']='Rotation matrix columns are tool-local X/Y/Z axes expressed in world coordinates. Gripper target 0 is closed and 1 is open. Measured gripper native state is reported separately; closure alone does not prove holding.'
            dump(folder/'robot_state.json',state)
            return state,images

        state,images=observe('initial')
        task=session.obs['instruction']
        english(task)
        output_spec='''Return only a JSON object with schema_version="1", task, initial_stage, and stages. Each stage has id, goal, target_description, controlled_arm (left or right), completion_condition, next_stage (id or null), and additional_inputs (empty array in this baseline). Do not include processing code or tests. Conditions must be judged from current observations; no historical images are supplied. Final-stage advance ends the plan, not native benchmark evaluation.'''
        plan_prompt=planner_role+'\n\nROBOT ACTIONS\n'+shared+'\n\nADVANCER QUESTIONS\n'+json.dumps(QUESTIONS)+\
            '\n\nTASK\n'+str(task)+'\n\nCURRENT ROBOT STATE\n'+json.dumps(state)+\
            '\n\nCURRENT BASELINE\nOnly current three RGB images and current robot state are enabled. No extra perception processing is enabled for this baseline. No history or experience is supplied. Fixed increments are 0.02 meters per non-hold translation channel and 0.10 radians per non-hold rotation channel. Translation and one rotation may execute together. Advance dispatches no action.\n\nOUTPUT\n'+output_spec+\
            '\n\nREFERENCE IMPLEMENTATIONS\n'+(code/'contracts/planner_processing_references.md').read_text()
        plan=call('planner',plan_prompt,images,args.output/'planner')
        stages={s['id']:s for s in plan['stages']}
        assert len(stages)==len(plan['stages']) and plan['initial_stage'] in stages
        for s in stages.values():
            assert s['controlled_arm'] in ('left','right') and not s['additional_inputs']
            assert s['next_stage'] is None or s['next_stage'] in stages
        dump(args.output/'plan.json',plan)
        current=plan['initial_stage']
        for index in range(args.decision_budget):
            if session.terminated or session.truncated:
                break
            if index:
                state,images=observe(f'decision-{index:03d}')
            stage=stages[current]
            prompt=role+'\n\n'+shared+'\n\n'+json.dumps(dict(task=task,current_stage=stage,controlled_arm=stage['controlled_arm'],
                current_robot_state=state,execution_parameters=dict(translation_step_m=.02,rotation_step_rad=.10),questions=QUESTIONS))
            decision=call('decision',prompt,images,args.output/'decisions'/f'{index:03d}',SCHEMA)
            if set(decision)!=set(CHOICES) or any(decision[k] not in v for k,v in CHOICES.items()):
                raise ValueError('Invalid categorical decision')
            if sum(decision[a]!='hold' for a in AXES[3:])>1:
                raise ValueError('Multiple rotation channels selected')
            if decision['stage_progress']=='advance':
                if any(decision[a]!='hold' for a in AXES) or decision['gripper']!='keep':
                    raise ValueError('Advance must contain no robot action')
                current=stage['next_stage']
                if current is None:
                    session._write_summary('plan_ended')
                    break
                continue
            arm=stage['controlled_arm']
            sign={'negative':-1,'hold':0,'positive':1}
            start=pose(arm)
            target=start.copy()
            target[:3,3]+=np.array([sign[decision[a]] for a in AXES[:3]])*.02
            rv=np.array([sign[decision['pitch']],sign[decision['roll']],sign[decision['yaw']]])*.10
            target[:3,:3]=R.from_rotvec(rv).as_matrix()@start[:3,:3]
            if decision['gripper']!='keep':
                grip[arm]=float(decision['gripper']=='open')
            robot=kin.robots[arm]
            robot_key=kin.manager.robot_key[kin.manager.robot_list.index(robot)]
            limits=robot_key.data.soft_joint_pos_limits[0,robot.arm_joint_indices].cpu().numpy()
            j=0 if arm=='left' else 7
            seed=np.array(session.obs['states'][j:j+6],float)
            path=[]
            rotations=Slerp([0.,1.],R.from_matrix(np.array([start[:3,:3],target[:3,:3]])))
            for f in np.linspace(.2,1.,5):
                p=start[:3,3]+f*(target[:3,3]-start[:3,3])
                rot=rotations(f).as_matrix()
                joints,diagnostic=solve_tcp(lambda q:pose(arm,q),p,rot,seed,limits)
                dump(args.output/'decisions'/f'{index:03d}'/f'ik-{f:.1f}.json',diagnostic)
                if not diagnostic['passed']:
                    raise RuntimeError('Robot-only five-step IK path cannot track requested TCP action')
                row=np.array(session.obs['states'],float)
                row[j:j+6]=joints
                row[6],row[13]=grip['left'],grip['right']
                path.append(row)
                seed=joints
            dump(args.output/'decisions'/f'{index:03d}'/'execution.json',dict(controlled_arm=arm,target_tcp=target.tolist(),planned_joint_path=np.array(path).tolist(),stage=current))
            session.chunk_step(np.array(path))
            measured=pose(arm)
            dump(args.output/'decisions'/f'{index:03d}'/'tracking.json',dict(position_error_m=float(np.linalg.norm(measured[:3,3]-target[:3,3])),rotation_error_rad=float(R.from_matrix(target[:3,:3]@measured[:3,:3].T).magnitude()),native_steps=session.step_id))
            print('DECISION',index,'STAGE',current,'NATIVE_STEPS',session.step_id,flush=True)
        if not session.terminated and not session.truncated:
            session._write_summary('decision_budget' if current is not None else 'plan_ended')
    except Exception:
        (args.output/'error.txt').write_text(traceback.format_exc())
        print(traceback.format_exc(),flush=True)
        if session:
            session.finish_reason='runtime_error'
            session._write_summary('runtime_error')
    finally:
        if session and session.video_writer:
            session.video_writer.close()
        if env:
            env.close()
        app.close()


if __name__=='__main__':
    main()
