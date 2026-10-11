"""GPT semantic stages -> Jev RGB decisions -> bounded robot-only EEF IK.

Uses the existing RoboDojo RPC bridge; no pi05, reward queries, depth or object poses.
Run with python -m realman_jev.robodojo --help from this project's uv environment.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation
from pydantic import BaseModel, ConfigDict, Field
from .api import API
from .runtime import Log
from .robodojo_rgb import RGBEvidence, CAMERAS


class RGBStage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    objective: str
    completion_evidence: str
    maintain: list[str]
    recovery: str
    max_decisions: int = Field(ge=1, le=80)


class RGBPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str
    stages: list[RGBStage] = Field(min_length=1,max_length=32)


PLANNER = """You are GPT System 2. Plan the entire instructed RoboDojo task into semantic
stages, with visually observable completion evidence, invariants and recovery.
Never output XYZ, pixels, angles, waypoints, axis commands, numeric robot targets or
executable code. Jev System 1 chooses all individual small motions and gripper actions.
Robot: dual ARX X5, six joints per arm, parallel fingers. Robot FK link6 is NOT the
fingertip center. RGB-only: three camera images, no depth or object true pose.
Jev receives local GroundingDINO/SAM2 masks, contours, colors, image locations and
changes, robot proprio/FK, full plan and recent actions. It cannot see RGB itself.
Plan grasp approach, closure, lift/verify actual object movement, transport, release
and return. Never treat closed fingers as proof of holding. For multiple objects
cover every visible target. Prefer simple separately verifiable milestones. Do not
invent success or use hidden task geometry. Describe object appearance in language.
Give useful semantic constraints, not numerical motion instructions. Return JSON.
"""

LOCAL = """You are Jev System 1, controlling one tiny motion at a time under a fixed GPT plan.
Input is RGB-derived 2D masks/contours/centers from THREE DISTINCT cameras, plus real
robot proprio/FK. There is NO object XYZ or depth. Never subtract a pixel coordinate
from a metric robot position; never compare coordinates across cameras as if aligned.
Use visible shapes, occlusion, relative image layout, previous image changes and
recent executed motions to reason about the next small increment. Missing detections
are unknown, not disappearance evidence. IoU IDs may change under occlusion.
EEF frame is environment_origin, Z up. No assumed mapping of image x/y to world X/Y.
Use measured recent motion/evidence to establish direction; hold/replan if ambiguous.
EEF is link6, not finger contact center. Never move the wrong arm based on unlabeled
gripper detections. Arms ordered left/right in all proprio arrays. Opening 0 closed,
1 open. A fixed controller converts your selected primitive to bounded IK, it does
not compute grasp waypoints. Do not claim holding from closure alone. Before carry,
require observed target follows gripper during lift. Keep held objects closed.
Question completion: satisfied only with actual current evidence for the stage;
unknown if RGB summaries cannot prove it. No task reward is available to you.
Use hold for a stage transition. Stop/replan instead of oscillating or guessing.
"""


def primitives(step, angle):
    result={"hold":dict(arm=None,delta=[0.,0.,0.],rotation=[0.,0.,0.],gripper="hold")}
    for arm in ("left","right"):
        for kind in ("open","close"):
            result[f"{arm}_{kind}"]=dict(arm=arm,delta=[0.,0.,0.],rotation=[0.,0.,0.],gripper=kind)
        for i,axis in enumerate("xyz"):
            for sign,value in (("positive",1),("negative",-1)):
                for kind,amount in (("move",step),("rotate",angle)):
                    vector=[0.,0.,0.]; vector[i]=value*amount
                    result[f"{arm}_{kind}_{axis}_{sign}"]=dict(arm=arm,
                        delta=vector if kind=="move" else [0.,0.,0.],
                        rotation=vector if kind=="rotate" else [0.,0.,0.],gripper="hold")
    return result


def targets_for(obs, primitive, step, angle):
    delta=np.asarray(primitive["delta"],float); rot=np.asarray(primitive["rotation"],float)
    if not np.isfinite(np.r_[delta,rot]).all() or np.linalg.norm(delta)>step+1e-8 or np.linalg.norm(rot)>angle+1e-8:
        raise ValueError("Primitive exceeds configured bounds")
    targets={}
    for i,arm in enumerate(("left","right")):
        p=np.array(obs["eef_positions"][i],float)
        q=np.array(obs["eef_quaternions_wxyz"][i],float)
        opening=float(obs["states"][i*7+6])
        if primitive["arm"]==arm:
            p+=delta
            orientation=Rotation.from_rotvec(rot)*Rotation.from_quat(q[[1,2,3,0]])
            q=orientation.as_quat()[[3,0,1,2]]
            if primitive["gripper"]!="hold": opening=float(primitive["gripper"]=="open")
        targets[arm]=dict(position=p.tolist(),quaternion_wxyz=(q/np.linalg.norm(q)).tolist(),
                          gripper_closed=bool(opening<.5),gripper_opening=opening)
    return targets


def choice(prompt, criteria):
    return dict(type="choice",instructions=prompt,criteria={k:v for k,v in criteria.items()})


def controller_check(args):
    """Simulation-only physical ACK check, explicitly not a model task rollout."""
    cfg=json.loads(Path(args.config).read_text())
    sys.path.insert(0,str(Path(cfg["bridge_source"]).resolve()))
    from hybrid_rollout.robodojo.robodojo_server.protocol import RPCClient
    folder=Path(args.output);folder.mkdir(parents=True,exist_ok=False)
    rpc=RPCClient("127.0.0.1",args.port,timeout=180); episode=None; tick=0
    result=dict(status="starting",plan_source="DETERMINISTIC_ACTUATOR_CHECK_NOT_POLICY",gpt_calls=0,jev_calls=0,
                complete=False,physical_success=False,checks=[])
    def call(op,**kwargs): return rpc.request(op,episode_id=episode,step_id=tick,**kwargs)
    try:
        meta=rpc.request("metadata")
        if meta.get("simulator")!="RoboDojo": raise ValueError("Check is simulation-only")
        reset=rpc.request("reset",seed=cfg["layout_id"],source="gpt_eef",policy_version="actuator_check_NOT_POLICY")
        episode=reset["episode_id"]
        catalog=primitives(cfg["step_m"],cfg["angle_rad"])
        for name in ("right_move_z_positive","right_move_z_negative","right_rotate_z_positive","right_rotate_z_negative","right_close","right_open"):
            obs=call("teacher_observation"); primitive=catalog[name]
            targets=targets_for(obs,primitive,cfg["step_m"],cfg["angle_rad"])
            for _ in range(10):
                proposal=call("eef_joint_target",targets=targets)
                command=np.asarray(proposal["action"],np.float32);command[:7]=obs["states"][:7]
                ack=call("chunk_step",actions=command.reshape(1,14),controller="actuator_check_NOT_POLICY")
                tick=ack["step_id"]
                if any(r["terminated"] or r["truncated"] for r in ack["steps"]): raise RuntimeError("Unexpected task termination in actuator check")
            after=call("teacher_observation")
            delta=(after["eef_positions"]-obs["eef_positions"]).tolist()
            q0=np.asarray(obs["eef_quaternions_wxyz"])[1,[1,2,3,0]]
            q1=np.asarray(after["eef_quaternions_wxyz"])[1,[1,2,3,0]]
            rotation=(Rotation.from_quat(q1)*Rotation.from_quat(q0).inv()).as_rotvec().tolist()
            target_error=float(np.linalg.norm(after["eef_positions"][1]-targets["right"]["position"]))
            opening=float(after["states"][13])
            passed=target_error<.004 and np.linalg.norm(delta[0])<.002
            if "rotate" in name: passed=passed and abs(rotation[2]-primitive["rotation"][2])<.04
            if name.endswith("close"): passed=passed and opening<.2
            if name.endswith("open"): passed=passed and opening>.8
            result["checks"].append(dict(action=name,delta_m=delta,rotation_delta_rad=rotation,
                target_error_m=target_error,opening=opening,passed=bool(passed)))
            print(json.dumps(result["checks"][-1]),flush=True)
        result["status"]="actuator_checks_passed" if all(c["passed"] for c in result["checks"]) else "actuator_check_failed"
    finally:
        if episode:
            try: result["native_result"]=call("finish_pilot",reason=result["status"])
            finally: rpc.close()
        else: rpc.close()
        result["native_steps"]=tick
        (folder/"summary.json").write_text(json.dumps(result,indent=2))
    return result


def run(args):
    cfg=json.loads(Path(args.config).read_text())
    sys.path.insert(0,str(Path(cfg["bridge_source"]).resolve()))
    from hybrid_rollout.robodojo.robodojo_server.protocol import RPCClient
    log=Log(args.output); rpc=None; gpt=None; jev=None; episode=None; tick=0
    summary=dict(status="starting",task=cfg["task"],gpt_calls=0,jev_calls=0,vision_api_calls=0,
                 native_steps=0,physical_success=False,complete=False,observation_protocol="RGB+proprio only")
    started=time.monotonic(); history=[]; plan=None; index=0; stages_used=0; stable=0; plans=0
    (log.folder/"config.json").write_text(json.dumps(cfg,indent=2))
    def call(op,**kwargs):
        return rpc.request(op,episode_id=episode,step_id=tick,**kwargs)
    try:
        vision=RGBEvidence(cfg["vision"])
        rpc=RPCClient("127.0.0.1",args.port,timeout=180)
        meta=rpc.request("metadata")
        if meta["task"]!=cfg["task"]: raise ValueError("Wrong simulator task")
        reset=rpc.request("reset",seed=cfg["layout_id"],source="gpt_eef",policy_version="gpt6_jev_rgb_v1")
        episode,tick=reset["episode_id"],reset["step_id"]
        log(dict(kind="reset",result=reset))
        call("begin_combination",evaluation_method="gpt6_jev_rgb",pi05_enabled=False,
             visual_frontend="GroundingDINO+SAM2",privileged_object_input=False)
        apis=json.loads(Path(args.api_config).read_text())
        if args.plan_file:
            plan=RGBPlan.model_validate_json(Path(args.plan_file).read_text())
            summary["plan_source"]="operator_file_NOT_GPT6"
            log(dict(kind="plan",source=summary["plan_source"],plan=plan.model_dump()))
            (log.folder/"plan-operator.json").write_text(plan.model_dump_json(indent=2))
        else:
            gpt=API(apis["gpt"],log,"planner")
            summary["plan_source"]="GPT6"
        jev=API(apis["jev"],log,"jev")
        catalog=primitives(cfg["step_m"],cfg["angle_rad"])
        previous=None; cached_tick=None; evidence=None; initial_robot=None
        for decision in range(args.max_decisions):
            if time.monotonic()-started>cfg["timeout_s"]:
                summary["status"]="time_budget"; break
            if Path(cfg["stop_file"]).exists(): summary["status"]="operator_stop"; break
            obs=call("teacher_observation")
            # Strict allowlist: even if upstream adds fields, none reach a model.
            obs={k:obs[k] for k in (*CAMERAS,"states","eef_positions","eef_quaternions_wxyz","instruction")}
            if cached_tick!=tick:
                evidence=vision.observe(obs); cached_tick=tick
                if initial_robot is None: initial_robot=evidence["robot"]
                for camera in CAMERAS:
                    Image.fromarray(obs[camera]).save(log.folder/f"{tick:05d}-{camera}.jpg")
                log(dict(kind="evidence",tick=tick,evidence=evidence,
                         rgb_sha256={k:hashlib.sha256(obs[k].tobytes()).hexdigest() for k in CAMERAS}))
            if plan is None:
                if args.plan_file: summary["status"]="operator_plan_needs_replanning"; break
                if plans>=cfg["max_plans"]: summary["status"]="planning_budget"; break
                planner_state=dict(instruction=obs["instruction"],robot=meta["robot_adapter"],
                    evidence=evidence,previous_failure=previous)
                (log.folder/f"planner-input-{plans+1}.json").write_text(json.dumps(dict(
                    instructions=PLANNER,state=planner_state,schema=RGBPlan.model_json_schema(),
                    images=[f"{tick:05d}-{k}.jpg" for k in CAMERAS]),indent=2))
                raw=gpt.chat(PLANNER,planner_state,
                    {k:SimpleNamespace(rgb=obs[k]) for k in CAMERAS},RGBPlan.model_json_schema())
                plan=RGBPlan.model_validate(raw); plans+=1; index=0; stages_used=0; stable=0
                log(dict(kind="plan",plan=plan.model_dump(),number=plans))
                (log.folder/f"plan-{plans}.json").write_text(json.dumps(raw,indent=2))
            stage=plan.stages[index]
            state=dict(instruction=LOCAL,plan=plan.model_dump(),stage_index=index,current_stage=stage.model_dump(),
                evidence=evidence,initial_robot=initial_robot,recent=history[-6:],allowed_primitives=catalog)
            questions=dict(action=choice("Choose one small primitive for current stage; hold if uncertain.",
                {k:json.dumps(v) for k,v in catalog.items()}),
                completion=choice("Is the current stage completion actually evidenced?",
                    dict(satisfied="Direct current evidence supports all requirements",not_yet="Observed incomplete",unknown="Insufficient evidence")),
                invariant=choice("Are ALL current_stage.maintain conditions supported now? Empty list means satisfied.",
                    dict(satisfied="All maintained requirements observed, or empty list",violated="Observed violation",unknown="Required evidence unavailable")),
                transition=choice("Continue current stage, advance, replan, or stop?",
                    dict(continue_="Execute selected primitive",advance="Advance only if completion satisfied; no motion",replan="Request high-level recovery; no motion",stop="Stop without claiming success")))
            # Save the EXACT state/questions sent to Jev (no credentials).
            (log.folder/f"jev-input-{decision:03d}.json").write_text(json.dumps(dict(model=jev.cfg["model"],state=state,questions=questions),indent=2))
            answer=jev.jev(state,questions)
            log(dict(kind="decision",decision=decision,tick=tick,stage=stage.id,answers=answer))
            selected=answer["action"]["choice"]; transition=answer["transition"]["choice"]
            print(f"{decision:03d} tick={tick} {stage.id}: {transition}/{selected}",flush=True)
            if time.monotonic()-started>cfg["timeout_s"]:
                summary["status"]="time_budget_after_model"; break
            if Path(cfg["stop_file"]).exists(): summary["status"]="operator_stop"; break
            stages_used+=1
            satisfied=answer["completion"]["choice"]=="satisfied" and answer["completion"]["confidence"]>=cfg["confidence"]
            stable=stable+1 if satisfied else 0
            if transition=="stop" and answer["transition"]["confidence"]>=cfg["confidence"]:
                summary["status"]="model_stop"; break
            if stage.maintain and (answer["invariant"]["choice"]!="satisfied" or answer["invariant"]["confidence"]<cfg["confidence"]):
                previous=dict(stage=stage.model_dump(),reason="Stage invariant not reliably observed",recent=history[-6:])
                log(dict(kind="invariant_replan",reason=previous));plan=None;continue
            if transition=="replan" or stages_used>=stage.max_decisions:
                previous=dict(stage=stage.model_dump(),reason="Jev recovery or stage budget",recent=history[-6:])
                plan=None; continue
            if transition=="advance" and stable>=2 and answer["transition"]["confidence"]>=cfg["confidence"]:
                log(dict(kind="stage_complete",stage=stage.id,tick=tick)); index+=1; stages_used=0; stable=0
                if index==len(plan.stages): summary["status"]="policy_completion_unverified"; break
                continue
            # Two observations require a physical hold ACK between transition votes.
            if transition!="continue_" or answer["action"]["confidence"]<cfg["confidence"]: selected="hold"
            primitive=catalog[selected]
            targets=targets_for(obs,primitive,cfg["step_m"],cfg["angle_rad"])
            ticks=0; diagnostics=None
            for _ in range(cfg["ticks_per_action"]):
                proposal=call("eef_joint_target",targets=targets)
                diagnostics=proposal["diagnostics"]
                command=np.asarray(proposal["action"],np.float32)
                # Exactly preserve the inactive arm joint targets, bypass its IK drift.
                for i,arm in enumerate(("left","right")):
                    if primitive["arm"]!=arm: command[i*7:i*7+7]=obs["states"][i*7:i*7+7]
                result=call("chunk_step",actions=command.reshape(1,14),controller="jev_rgb")
                tick=result["step_id"]; ticks+=1
                row=result["steps"][-1]
                if row["terminated"] or row["truncated"]:
                    summary.update(status="native_terminal",complete=True,physical_success=bool(row["success"])); break
            event=dict(stage=stage.id,action=selected,start_eef=evidence["robot"]["eef_positions_m"],
                       target=targets,tick=tick,executed_ticks=ticks,ik=diagnostics)
            history.append(event); log(dict(kind="execution",**event))
            if summary["complete"]: break
            if len(history)>=8:
                names=[h["action"] for h in history[-8:]]
                a=np.asarray(history[-8]["start_eef"]); b=np.asarray(history[-1]["start_eef"])
                if len(set(names))<=2 and np.linalg.norm(a-b)<.005:
                    summary["status"]="no_progress"; break
        else: summary["status"]="decision_budget"
    except BaseException as exc:
        summary.update(status="error",error_type=type(exc).__name__)
        # API failures already redact credentials; do not log arbitrary HTTP bodies.
        log(dict(kind="error",error_type=type(exc).__name__,message=str(exc)[:500]))
        raise
    finally:
        if rpc and episode:
            try:
                final=call("finish_pilot",reason=summary["status"])
                summary.update(native_result=final,physical_success=bool(final["success"]),
                               complete=bool(final["terminated"] or final["truncated"]))
            except Exception as exc: summary["finish_error"]=type(exc).__name__
        if rpc: rpc.close()
        for api,name in ((gpt,"gpt_calls"),(jev,"jev_calls")):
            if api: summary[name]=api.calls; api.close()
        summary.update(native_steps=tick,wall_seconds=round(time.monotonic()-started,3))
        (log.folder/"summary.json").write_text(json.dumps(summary,indent=2)); log.close()
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",default="config/robodojo.json")
    p.add_argument("--api-config",default="config/api.local.json")
    p.add_argument("--port",type=int,default=19117)
    p.add_argument("--output",required=True)
    p.add_argument("--max-decisions",type=int,default=80)
    p.add_argument("--plan-file",help="Explicit operator-plan diagnostic; never labeled as GPT output")
    p.add_argument("--controller-check",action="store_true",help="Simulation-only deterministic actuator test, no models")
    args=p.parse_args()
    if args.max_decisions<1: p.error("max-decisions must be positive")
    print(json.dumps(controller_check(args) if args.controller_check else run(args),indent=2))


if __name__=="__main__": main()
