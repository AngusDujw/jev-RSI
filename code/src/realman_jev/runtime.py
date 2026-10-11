import hashlib
import json
import time
from pathlib import Path
import numpy as np
from PIL import Image
from .api import API
from .contracts import actions
from .control import Guard
from .perception import Perception,Facts
from .planning import plan_task,choose


class Log:
    def __init__(self,folder):
        self.folder=Path(folder)
        self.folder.mkdir(parents=True,exist_ok=False)
        self.file=(self.folder/"events.jsonl").open("w",buffering=1)
    def __call__(self,event):
        self.file.write(json.dumps({"time":time.time(),**event},ensure_ascii=False,allow_nan=False)+"\n")
    def close(self): self.file.close()


def run(cfg,apis,folder,goal,backend="sim",execute=False,seed=0,max_steps=160,save_frames=False,plan_file=None):
    log=Log(folder); robot=None; clients=[]
    (log.folder/"config.json").write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
    summary={"status":"starting","backend":backend,"seed":seed,"goal":goal,"hardware_execute":execute,
             "policy_success":False,"gpt_calls":0,"jev_calls":0,"vision_calls":0,"steps":0}
    started=time.monotonic(); history=[]; plans=0; stage_steps=0; blocked=0
    try:
        if backend=="sim":
            from .simulation import Simulation
            robot=Simulation(cfg["sim"],seed)
        else:
            from .hardware import RealMan
            robot=RealMan(cfg["realman"],execute)
        gpt=None
        if not plan_file:
            gpt=API(apis["gpt"],log,"planner"); clients.append(gpt)
        jev=API(apis["jev"],log,"jev"); clients.append(jev)
        vision=None
        if cfg["perception"]["mode"]=="vlm":
            vision=API(apis["vision"],log,"vision"); clients.append(vision)
        perception=Perception(cfg["perception"],vision)
        facts=Facts(cfg["facts"])
        guard=Guard(cfg["control"],backend=="realman")
        catalog=actions(cfg["control"]["coarse_m"],cfg["control"]["fine_m"])
        plan=None; index=0; reason=None
        if plan_file:
            from .contracts import Plan
            plan=Plan.model_validate_json(Path(plan_file).read_text())
            summary["plan_source"]="operator_file_NOT_GPT6"
            log({"kind":"plan","source":"operator_file_NOT_GPT6","plan":plan.model_dump()})
        for step in range(max_steps):
            summary["steps"]=step+1
            if time.monotonic()-started>cfg["runtime"]["timeout_s"]:
                summary["status"]="time_budget"; break
            obs=robot.observe()
            evidence=perception.observe(obs)
            if save_frames:
                for name,frame in obs.cameras.items():
                    Image.fromarray(frame.rgb).save(log.folder/f"{step:04d}-{name}.jpg")
            log({"kind":"sensor","sequence":obs.sequence,"camera_rgb_sha256":{n:hashlib.sha256(f.rgb.tobytes()).hexdigest() for n,f in obs.cameras.items()}})
            if plan is None:
                if plan_file:
                    summary["status"]="operator_plan_needs_replanning"; break
                if plans>=cfg["runtime"]["max_plans"]:
                    summary["status"]="planning_budget"; break
                plan=plan_task(gpt,goal,cfg["robot_description"],evidence,obs.cameras,reason)
                plans+=1; index=0; stage_steps=0
                log({"kind":"plan","number":plans,"plan":plan.model_dump()})
                # Camera information may be stale after a slow high-level response.
                continue
            evidence=facts.update(evidence,plan.object_label,plan.destination_label)
            stage=plan.stages[index]
            if any(evidence["facts"].get(k) is not True for k in stage.maintain):
                reason={"problem":"stage invariant not observed","stage":stage.model_dump(),"evidence":evidence}
                log({"kind":"invariant_replan",**reason}); plan=None; continue
            candidates=guard.candidates(catalog,obs)
            decision,raw=choose(jev,plan,index,evidence,candidates,history,cfg["runtime"]["motion_confidence"])
            if time.monotonic()-started>cfg["runtime"]["timeout_s"]:
                summary["status"]="time_budget_after_model"; break
            log({"kind":"decision","step":step,"stage":stage.id,"evidence":evidence,"candidates":candidates,"decision":decision.model_dump(),"answers":raw})
            print(f"{step:03d} {stage.id}: {decision.transition}/{decision.action} p={decision.confidence:.3f}",flush=True)
            if decision.transition=="stop":
                summary["status"]="model_stop"; break
            if decision.transition=="replan" or stage_steps>=stage.max_decisions:
                reason={"previous_plan":plan.model_dump(),"stage":stage.id,"evidence":evidence,"history":history[-6:]}
                plan=None; continue
            if decision.transition=="advance":
                if decision.transition_confidence>=cfg["runtime"]["transition_confidence"] and all(evidence["facts"].get(k) is True for k in stage.completion):
                    index+=1; stage_steps=0; blocked=0
                    log({"kind":"stage_complete","stage":stage.id})
                    if index==len(plan.stages):
                        # A short plan cannot declare task success without release+placement.
                        summary["policy_success"]=all(evidence["facts"].get(k) is True for k in ("object_in_destination","retreated","released"))
                        summary["status"]="completed" if summary["policy_success"] else "unverified_completion"
                        break
                    continue
                blocked+=1
                log({"kind":"transition_rejected","stage":stage.id})
                if blocked>=5:
                    reason={"problem":"unproved stage transition","stage":stage.model_dump(),"evidence":evidence}; plan=None; blocked=0
                continue
            stage_steps+=1
            if decision.confidence<cfg["runtime"]["motion_confidence"]:
                blocked+=1
                log({"kind":"hold","reason":"low_confidence"})
                if blocked>=5:
                    reason={"problem":"repeated low confidence","evidence":evidence}; plan=None; blocked=0
                continue
            action=candidates[decision.action]
            if backend=="realman":
                fresh=robot.observe()
                fresh_evidence=perception.observe(fresh)
                moved=False
                for label in (plan.object_label,plan.destination_label):
                    old=evidence["objects"].get(label,{}).get("position_m")
                    new=fresh_evidence["objects"].get(label,{}).get("position_m")
                    if old is None or new is None or np.linalg.norm(np.subtract(old,new))>.005:
                        moved=True
                if moved:
                    log({"kind":"hold","reason":"scene_changed_while_waiting"}); continue
                obs=fresh
            guard.validate(action,obs)
            outcome=robot.execute(action,obs)
            if outcome["executed"]: guard.charge(action)
            blocked=0
            history.append({"stage":stage.id,"action":decision.action,"before_grasp_m":evidence["robot"]["grasp_point_m"],"outcome":outcome})
            log({"kind":"execution",**history[-1]})
            if backend=="realman" and not execute:
                summary["status"]="observe_only_proposal"; break
            # No alternate policy on failure; log actual progress and request System 2.
            if len(history)>=12 and len({h["action"] for h in history[-12:]})==1 and np.linalg.norm(np.subtract(history[-1]["before_grasp_m"],history[-12]["before_grasp_m"]))<.003:
                reason={"problem":"repeated identical actions","history":history[-12:],"evidence":evidence}; plan=None
        else:
            summary["status"]="step_budget"
    except BaseException as e:
        summary.update(status="error",error_type=type(e).__name__,error=str(e))
        log({"kind":"error","error_type":type(e).__name__,"message":str(e)})
        raise
    finally:
        summary["wall_seconds"]=round(time.monotonic()-started,3)
        for client in clients:
            summary[{"planner":"gpt_calls","jev":"jev_calls","vision":"vision_calls"}[client.role]]=client.calls
            client.close()
        if robot:
            try: summary["evaluation"]=robot.evaluation()
            finally: robot.close()
        (log.folder/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2))
        log.close()
    return summary
