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
import hashlib
import shutil

import numpy as np
import cv2  # Pin the environment's compatible binary before Kit adjusts sys.path.
import rtree  # Pin the project wheel, including its libspatialindex, before Kit.
from models import call, dump, english, legacy_input_contract
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
    parser.add_argument('--layout-manifest',type=Path)
    parser.add_argument('--enable-processing',action='store_true')
    parser.add_argument('--prepared-from',type=Path)
    parser.add_argument('--resume-processing-from',type=Path)
    parser.add_argument('--decision-backend',choices=['luna','jev'],default='luna')
    parser.add_argument('--omit-images',action='store_true')
    parser.add_argument('--camera-intrinsics',choices=['native','sdk'],default='native')
    parser.add_argument('--tool-geometry-details',action='store_true')
    parser.add_argument('--execution-budget-details',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--decision-budget',type=int,default=240)
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    if (args.prepared_from or args.resume_processing_from or args.decision_backend=='jev' or args.omit_images) and not args.enable_processing:
        raise ValueError('Prepared-plan and text-only comparisons require additional processing')
    args.output.mkdir(parents=True,exist_ok=False)
    protocol=dict(camera_intrinsics=args.camera_intrinsics,tool_geometry_details=args.tool_geometry_details,
                  execution_budget_details=args.execution_budget_details)
    if args.prepared_from:
        source=args.prepared_from.resolve()
        campaign_root=Path(__file__).resolve().parents[1]/'runs/company2-20261018'
        if not source.is_relative_to(campaign_root.resolve()):
            raise ValueError('Paired plan source must belong to this campaign')
        prior=source/'input_contract.json'
        protocol=json.loads(prior.read_text()) if prior.exists() else legacy_input_contract(json.loads((source/'observations/initial/observation.json').read_text()))
        if set(protocol)!={'camera_intrinsics','tool_geometry_details','execution_budget_details'} or protocol['camera_intrinsics'] not in ('sdk','native') or any(type(protocol[k]) is not bool for k in ('tool_geometry_details','execution_budget_details')):
            raise ValueError('Invalid source input contract')
        for key,value in protocol.items():
            setattr(args,key,value)
    dump(args.output/'input_contract.json',protocol)
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
        identity=None
        if args.layout_manifest:
            panel=json.loads(args.layout_manifest.read_text())
            case=next(c for c in panel['entries'] if c['task']==args.task and c['layout_id']==args.layout)
            path=Path(case['path'])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=case['sha256']:
                raise ValueError('Frozen layout hash mismatch')
            env.seed_manager.seed_info[args.layout]={'scene_layout':str(path)}
            identity=dict(layout_id=args.layout,layout_sha256=case['sha256'],runtime_task=args.task,
                          eval_seed=case['eval_seed'],source_url=case['url'])
            dump(args.output/'evaluation_case.json',identity)
        session=RoboDojoSession(env,args.output/'native',args.task,evaluation_identity=identity)
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

        def observe(label,stage=None):
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
                if args.tool_geometry_details:
                    state[arm]['public_tool_geometry']=dict(
                        description='The reported tool frame is parallel to X5 LINK6. Fingers extend from the palm along tool-local +X. The two prismatic jaws slide along tool-local +Y and -Y. Tool-local Z is the third transverse axis. These axes are carried into world coordinates by the reported rotation matrix.',
                        finger_extension_axis_world_unit=t[:3,0].tolist(),
                        jaw_sliding_axis_world_unit=t[:3,1].tolist(),
                        transverse_axis_world_unit=t[:3,2].tolist(),
                        finger_extension_dot_world_down=float(-t[2,0]),
                        evidence='Public X5A.urdf joint7/joint8 origins and sliding axes; public link7/link8 STL geometry. No object geometry is used.')
            state['definitions']='Rotation matrix columns are tool-local X/Y/Z axes expressed in world coordinates. Gripper target 0 is closed and 1 is open. Measured gripper native state is reported separately; closure alone does not prove holding.'
            dump(folder/'robot_state.json',state)
            if args.enable_processing:
                manager=env.camera_manager
                names=list(manager.camera_names[0])
                aliases=dict(cam_high=('cam_high','cam_head','head_camera','top_camera'),
                             cam_left_wrist=('cam_left_wrist','left_camera'),cam_right_wrist=('cam_right_wrist','right_camera'))
                cameras={}
                native_base=kin.manager.get_link_pose(kin.robots['right'],kin.robots['right'].base_link,is_relative=False)[0]
                origin=np.asarray(native_base[:3])-kin.root('right')[:3,3]
                for label,options in aliases.items():
                    cam_id=next(i for i,name in enumerate(names) if name in options)
                    camera=manager.cameras[0][cam_id]
                    position,quaternion=camera.get_world_pose(camera_axes='ros')
                    position,quaternion=np.asarray(position),np.asarray(quaternion)
                    matrix=np.eye(4)
                    matrix[:3,:3]=R.from_quat(quaternion[[1,2,3,0]]).as_matrix()
                    matrix[:3,3]=position-origin
                    sdk_intrinsic=np.asarray(camera.get_intrinsics_matrix())
                    intrinsic=np.asarray(manager.get_camera_intrinsics(cam_id,0)) if args.camera_intrinsics=='native' else sdk_intrinsic
                    if intrinsic.shape!=(3,3) or min(intrinsic[0,0],intrinsic[1,1])<10:
                        raise RuntimeError('Camera intrinsics are not usable pixel calibration')
                    projections={}
                    for arm in ('left','right'):
                        point=np.linalg.inv(matrix)@np.r_[pose(arm)[:3,3],1.]
                        pixel=intrinsic@point[:3]
                        projections[arm]=dict(depth_m=float(point[2]),pixel=(pixel[:2]/pixel[2]).tolist() if abs(pixel[2])>1e-9 else None)
                    cameras[label]=dict(K=intrinsic.tolist(),robot_tcp_projection_check=projections,
                        calibration_source=('Native CameraManager pinhole intrinsics from configured focal length, horizontal aperture and resolution; square pixels. Validate image consistency before precise use.' if args.camera_intrinsics=='native' else 'Camera SDK intrinsics; paired legacy observation protocol. Validate rendered-image consistency before precise use.'),
                        sdk_intrinsics_diagnostic=sdk_intrinsic.tolist(),
                        camera_to_world=matrix.tolist(),image_size=list(Image.open(images[label]).size),
                        convention='Camera X right, Y down, Z forward; world frame matches TCP positions; meters. Extrinsics updated from current measured camera mounting pose.')
                observation=dict(task=str(session.obs['instruction']),robot_state=state,
                    current_stage=stage or dict(id='planning_placeholder',goal='Design the stages for the supplied task.'),
                    cameras=cameras,images={k:'/input/'+p.name for k,p in images.items()})
                if args.execution_budget_details:
                    observation['execution_budget']=dict(native_control_step_limit=int(env.step_lim),
                        native_steps_used=int(session.step_id),native_steps_remaining=max(0,int(env.step_lim)-int(session.step_id)),
                        native_steps_per_continue_decision=5,native_steps_per_advance_decision=0)
                dump(folder/'observation.json',observation)
            return state,images

        state,images=observe('initial')
        task=session.obs['instruction']
        english(task)
        output_spec='''Return only a JSON object with schema_version="1", task, initial_stage, and stages. Each stage has id, goal, target_description, controlled_arm (left or right), completion_condition, next_stage (id or null), and additional_inputs. Do not include processing code or tests. Conditions must be judged from current observations; no historical images are supplied. Final-stage advance ends the plan, not native benchmark evaluation.'''
        mode='Only current three RGB images and current robot state are enabled. No extra perception processing is enabled for this baseline. Set additional_inputs to empty arrays.'
        if args.enable_processing:
            mode='Additional observation processing is enabled. Implement and verify task-appropriate extra inputs through the supplied tools. Preserve the fixed advancer questions and choices.'
        plan_prompt=planner_role+'\n\nROBOT ACTIONS\n'+shared+'\n\nADVANCER QUESTIONS\n'+json.dumps(QUESTIONS)+\
            '\n\nTASK\n'+str(task)+'\n\nCURRENT ROBOT STATE\n'+json.dumps(state)+\
            '\n\nCURRENT INPUT MODE\n'+mode+' No history or experience is supplied. Fixed increments are 0.02 meters per non-hold translation channel and 0.10 radians per non-hold rotation channel. Translation and one rotation may execute together. Advance dispatches no action.\n\nOUTPUT\n'+output_spec+\
            '\n\nREFERENCE IMPLEMENTATIONS\n'+(code/'contracts/planner_processing_references.md').read_text()
        if args.execution_budget_details:
            plan_prompt+='\n\nEXECUTION BUDGET\n'+json.dumps(dict(native_control_step_limit=int(env.step_lim),
                native_steps_per_continue_decision=5,native_steps_per_advance_decision=0,
                maximum_full_continue_decisions=int(env.step_lim)//5,total_decision_call_limit=args.decision_budget,
                meaning='The native episode ends at this fixed control-step limit. Each continue decision, including hold or gripper-only decisions, uses up to five native steps. Stage advance uses no native steps. This is an execution budget, not a task-success signal.'))
        implementation=None
        if args.prepared_from:
            source=args.prepared_from.resolve()
            campaign_root=Path(__file__).resolve().parents[1]/'runs/company2-20261018'
            if not source.is_relative_to(campaign_root.resolve()):
                raise ValueError('Prepared plan must belong to this campaign')
            original=json.loads((source/'evaluation_case.json').read_text())
            if not identity or any(original[k]!=identity[k] for k in ('runtime_task','layout_id','layout_sha256')):
                raise ValueError('Paired condition differs from prepared plan native case')
            plan=json.loads((source/'plan.json').read_text())
            implementation=args.output/'planner/implementation'
            shutil.copytree(source/'planner/implementation',implementation,symlinks=True)
            dump(args.output/'paired_plan_source.json',dict(source=str(source),plan_sha256=hashlib.sha256((source/'plan.json').read_bytes()).hexdigest(),
                 backend=args.decision_backend,images_omitted=args.omit_images or args.decision_backend=='jev'))
        elif args.enable_processing:
            from planning import prepare
            partial=None
            if args.resume_processing_from:
                source=args.resume_processing_from.resolve()
                campaign_root=Path(__file__).resolve().parents[1]/'runs/company2-20261018'
                if not source.is_relative_to(campaign_root.resolve()):
                    raise ValueError('Partial preparation must belong to this campaign')
                original=json.loads((source/'evaluation_case.json').read_text())
                if not identity or any(original[k]!=identity[k] for k in ('runtime_task','layout_id','layout_sha256')):
                    raise ValueError('Partial processing reference belongs to a different case')
                partial=source/'planner/implementation'
                dump(args.output/'partial_preparation_source.json',dict(source=str(source),no_final_plan_reused=True))
            plan,implementation=prepare(plan_prompt,images,args.output/'observations/initial',args.output/'planner',partial)
        else:
            plan=call('planner',plan_prompt,images,args.output/'planner')
        stages={s['id']:s for s in plan['stages']}
        assert len(stages)==len(plan['stages']) and plan['initial_stage'] in stages
        for s in stages.values():
            assert s['controlled_arm'] in ('left','right')
            assert args.enable_processing or not s['additional_inputs']
            assert s['next_stage'] is None or s['next_stage'] in stages
        dump(args.output/'plan.json',plan)
        current=plan['initial_stage']
        for index in range(args.decision_budget):
            if session.terminated or session.truncated:
                break
            stage=stages[current]
            if index:
                state,images=observe(f'decision-{index:03d}',stage)
            additional={}
            if implementation:
                from sandbox import execute
                input_folder=args.output/'observations'/('initial' if not index else f'decision-{index:03d}')
                value=json.loads((input_folder/'observation.json').read_text())
                value['current_stage']=stage
                dump(input_folder/'observation.json',value)
                processed=args.output/'processing'/f'{index:03d}'
                result=execute(implementation,input_folder,processed,'./processor /input/observation.json /output/additional.json',readonly=True)
                dump(processed/'execution.json',result)
                if result['returncode']:
                    raise RuntimeError('Prepared processor failed on fresh observations')
                if (processed/'additional.json').is_symlink():
                    raise RuntimeError('Processor output must be a regular file')
                values=json.loads((processed/'additional.json').read_text())
                additional={entry['name']:values[entry['name']] for entry in stage['additional_inputs']}
                for name,value in list(additional.items()):
                    if isinstance(value,dict) and 'image_path' in value:
                        guest=str(value['image_path'])
                        if not guest.startswith('/output/'):
                            raise ValueError('Additional image must be under /output')
                        image_file=(processed/guest[len('/output/'):]).resolve()
                        if not image_file.is_relative_to(processed.resolve()) or not image_file.is_file() or image_file.suffix.lower()!='.png':
                            raise ValueError('Additional image is not a verified PNG output')
                        label='additional_'+name
                        if args.decision_backend!='jev' and not args.omit_images:
                            images[label]=image_file
                            additional[name]=dict(image_label=label,description=value.get('description',''))
                        else:
                            additional[name]=dict(image_omitted=True,description=value.get('description',''))
                english(additional)
            context=dict(task=task,current_stage=stage,controlled_arm=stage['controlled_arm'],
                current_robot_state=state,additional_information=additional,
                execution_parameters=dict(translation_step_m=.02,rotation_step_rad=.10))
            if args.execution_budget_details:
                context['execution_parameters'].update(native_control_step_limit=int(env.step_lim),
                    native_steps_used=int(session.step_id),native_steps_remaining=max(0,int(env.step_lim)-int(session.step_id)),
                    native_steps_per_continue_decision=5,native_steps_per_advance_decision=0,
                    decision_calls_remaining=args.decision_budget-index)
            if args.decision_backend=='jev':
                from jev_client import decide
                context.update(advancer_instructions=role,action_definitions=shared,input_modality='Text only. No RGB images are supplied. Use the current robot state and additional information.')
                decision=decide(context,QUESTIONS,args.output/'decisions'/f'{index:03d}')
            else:
                prompt=role+'\n\n'+shared+'\n\n'+json.dumps(dict(**context,questions=QUESTIONS))
                if args.omit_images:
                    prompt+='\nThis is a text-only condition. No images are supplied; use the additional information and robot state.'
                decision=call('decision',prompt,{} if args.omit_images else images,args.output/'decisions'/f'{index:03d}',SCHEMA)
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
            measured_joints=np.asarray(session.obs['states'][j:j+6],float)
            target_joints=np.asarray(path[-1][j:j+6],float)
            joint_error=measured_joints-target_joints
            try:
                fk_check=kin.check()
            except ValueError as error:
                fk_check=dict(passed=False,error=str(error))
            dump(args.output/'decisions'/f'{index:03d}'/'tracking.json',dict(position_error_m=float(np.linalg.norm(measured[:3,3]-target[:3,3])),rotation_error_rad=float(R.from_matrix(target[:3,:3]@measured[:3,:3].T).magnitude()),native_steps=session.step_id,
                joint_names=robot.arm_joints_name,target_joints_rad=target_joints.tolist(),measured_joints_rad=measured_joints.tolist(),
                joint_tracking_error_rad=joint_error.tolist(),max_joint_tracking_error_rad=float(np.max(np.abs(joint_error))),
                max_planned_joint_waypoint_delta_rad=float(np.max(np.abs(np.diff(np.vstack([np.asarray(state[arm]['arm_joints_rad']),np.asarray(path)[:,j:j+6]]),axis=0)))),
                public_robot_fk_check=fk_check))
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
