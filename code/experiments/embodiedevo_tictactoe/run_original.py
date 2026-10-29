"""Deployment-only compatibility around the pinned upstream Playground runner."""
import argparse
from dataclasses import replace
import os
from pathlib import Path
import sys


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--repo",type=Path,required=True)
    p.add_argument("--run-dir",type=Path,required=True)
    p.add_argument("--task",default="RoboDojo")
    a=p.parse_args()
    sys.path.insert(0,str(a.repo))
    from orchestrator import resources, launch_agent
    original_env=resources.sim_env
    resources.sim_env=lambda *args,**kw: dict(original_env(*args,**kw),XDG_RUNTIME_DIR=os.environ["XDG_RUNTIME_DIR"])
    original_agent=launch_agent.agent_argv
    def agent_argv(*args, **kw):
        argv=original_agent(*args, **kw)
        run_id=str(a.run_dir.resolve())
        import json
        argv[-1:-1]=["-c", "model_providers.paired-local-pro.http_headers={\"X-Experiment-Run\"="+json.dumps(run_id)+"}"]
        return argv
    launch_agent.agent_argv=agent_argv
    original_docker=launch_agent.docker_argv
    def docker_argv(*args,**kw):
        argv=original_docker(*args,**kw)
        argv=["/runtime-tmp:mode=1777" if x=="/tmp:mode=1777" else x for x in argv]
        argv[2:2]=["--env","TMPDIR=/runtime-tmp","--env","TMP=/runtime-tmp","--env","TEMP=/runtime-tmp"]
        if os.environ.get("JEV_ROUTER_URL"):
            argv[2:2]=["--env","JEV_ROUTER_URL="+os.environ["JEV_ROUTER_URL"]]
        if os.environ.get("EMBODIEDEVO_RUN_ID"):
            argv[2:2]=["--env","EMBODIEDEVO_RUN_ID="+os.environ["EMBODIEDEVO_RUN_ID"]]
        return argv
    launch_agent.docker_argv=docker_argv
    from orchestrator.config import load_task
    from orchestrator.session_runner import explore
    cfg=load_task(a.task,env_task="play_tic_tac_toe")
    cfg=replace(cfg,agent=replace(cfg.agent,model="gpt-6-astra",reasoning_effort="high"),
        simulator=replace(cfg.simulator,interpreter="/data/ykj_robodojo/RoboLaya/.conda"))
    return explore(cfg,a.run_dir,gpu="0")


if __name__ == "__main__":
    sys.exit(main())
