import argparse
import json
import os
from pathlib import Path
from datetime import datetime


def main():
    cache=Path(".cache/tmp").resolve(); cache.mkdir(parents=True,exist_ok=True)
    os.environ["TMPDIR"]=str(cache)
    import tempfile
    tempfile.tempdir=str(cache)
    p=argparse.ArgumentParser(description="GPT semantic stages + Jev actions + measured execution")
    p.add_argument("command",choices=["run","inspect","check-api","calibrate-points","calibrate-handeye","sample-marker"])
    p.add_argument("--config",default="config/sim.json")
    p.add_argument("--api",default="config/api.local.json")
    p.add_argument("--backend",choices=["sim","realman"],default="sim")
    p.add_argument("--execute",action="store_true")
    p.add_argument("--goal",default="Pick up the red block and place it in the blue tray, open fingers and retreat.")
    p.add_argument("--seed",type=int,default=0)
    p.add_argument("--max-steps",type=int,default=160)
    p.add_argument("--output")
    p.add_argument("--input")
    p.add_argument("--save-frames",action="store_true")
    p.add_argument("--plan-file",help="Explicit operator-authored plan for Jev-only diagnostics; NOT a GPT-6 result")
    p.add_argument("--camera",default="top")
    p.add_argument("--marker-id",type=int,default=0)
    p.add_argument("--marker-size",type=float,default=.04)
    p.add_argument("--base-point",type=float,nargs=3)
    args=p.parse_args()
    os.environ.setdefault("MUJOCO_GL","egl")
    cfg=json.loads(Path(args.config).read_text())
    if args.command=="sample-marker":
        from .hardware import RealMan
        from .calibration import sample_marker
        if not args.output: p.error("sample-marker requires --output")
        robot=RealMan(cfg["realman"],False)
        try: print(json.dumps(sample_marker(robot,args.camera,args.marker_id,args.marker_size,args.output,args.base_point)))
        finally: robot.close()
        return
    if args.command.startswith("calibrate-"):
        from .calibration import solve_file
        if not args.input or not args.output: p.error("calibration requires --input and --output")
        print(json.dumps(solve_file(args.input,args.output,args.command.split("-")[1]),indent=2)); return
    if args.command=="check-api":
        from .api import API
        apis=json.loads(Path(args.api).read_text())
        for role in ("gpt","jev"):
            a=API(apis[role],lambda e:print(json.dumps(e)),role)
            try:
                if role=="gpt": print(a.chat('Return JSON {"ok":true}',{"test":True}))
                else: print(a.jev({"test":True},{"check":{"type":"choice","instructions":"Select ok","criteria":{"ok":"API diagnostic","no":"Wrong"}}}))
            finally: a.close()
        return
    if args.command=="inspect":
        from .perception import Perception
        vision=None
        if cfg["perception"]["mode"]=="vlm":
            from .api import API
            apis=json.loads(Path(args.api).read_text())
            vision=API(apis["vision"],lambda e:print(json.dumps(e)),"vision")
        if args.backend=="sim":
            from .simulation import Simulation
            robot=Simulation(cfg["sim"],args.seed)
        else:
            from .hardware import RealMan
            robot=RealMan(cfg["realman"],False)
        try:
            obs=robot.observe(); perception=Perception(cfg["perception"],vision)
            e=perception.observe(obs)
            print(json.dumps(e,indent=2))
            if args.output:
                import numpy as np
                from PIL import Image
                out=Path(args.output); out.mkdir(parents=True,exist_ok=False)
                (out/"evidence.json").write_text(json.dumps(e,indent=2))
                for name,f in obs.cameras.items():
                    Image.fromarray(f.rgb).save(out/f"{name}.png")
                    np.savez_compressed(out/f"{name}.npz",rgb=f.rgb,depth=f.depth,K=f.K,T_base_camera=f.T_base_camera,
                                        tcp=obs.tcp,rotation=obs.rotation,joints=obs.joints)
        finally:
            robot.close()
            if vision: vision.close()
        return
    from .runtime import run
    apis=json.loads(Path(args.api).read_text())
    out=args.output or "runs/"+datetime.now().strftime("%Y%m%d-%H%M%S")+f"-{args.backend}-s{args.seed}"
    print(json.dumps(run(cfg,apis,out,args.goal,args.backend,args.execute,args.seed,args.max_steps,args.save_frames,args.plan_file),ensure_ascii=False,indent=2))


if __name__=="__main__": main()
