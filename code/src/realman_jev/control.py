"""Task-independent action guards: no hidden task policy or alternate direction."""
import time
from pathlib import Path
import numpy as np


class Guard:
    def __init__(self,cfg,real=False):
        self.cfg,self.real=cfg,real
        self.distance=0.

    def validate(self,action,obs):
        d=np.asarray(action["delta"],float)
        if d.shape!=(3,) or not np.isfinite(d).all() or np.linalg.norm(d)>self.cfg["coarse_m"]+1e-9:
            raise ValueError("Action exceeds fixed atomic step")
        if action["gripper"] not in {"open","close","hold"}:
            raise ValueError("Invalid gripper command")
        if self.real:
            if time.monotonic()-obs.captured>self.cfg["max_sensor_age_s"]:
                raise ValueError("Stale proprioception")
            if any(time.monotonic()-f.captured>self.cfg["max_sensor_age_s"] for f in obs.cameras.values()):
                raise ValueError("Stale camera")
            stop=self.cfg.get("stop_file")
            if stop and Path(stop).exists():
                raise ValueError("STOP file exists")
        target=obs.tcp+d
        lo,hi=np.asarray(self.cfg["workspace_m"])
        if not np.isfinite(target).all() or np.any(target<lo) or np.any(target>hi):
            raise ValueError("Motion outside configured tool workspace")
        grasp=obs.grasp_point+d
        if grasp[2] < self.cfg["minimum_grasp_z_m"]:
            raise ValueError("Grasp point below calibrated table clearance")
        for box in self.cfg.get("forbidden_tcp_boxes_m", []):
            blo,bhi=np.asarray(box)
            # Conservative swept AABB; diagonal moves may be rejected early.
            if np.all(np.maximum(obs.tcp,target)>=blo) and np.all(np.minimum(obs.tcp,target)<=bhi):
                raise ValueError("Motion crosses configured keep-out volume")
        if self.distance+np.linalg.norm(d)>self.cfg.get("max_total_distance_m",3):
            raise ValueError("Total travel budget exhausted")

    def charge(self,action):
        self.distance+=float(np.linalg.norm(action["delta"]))

    def candidates(self,catalog,obs):
        out={}
        for name,action in catalog.items():
            try:
                self.validate(action,obs)
                out[name]=action
            except ValueError:
                pass
        if "hold" not in out:
            raise ValueError("Current pose or sensors invalid; no actions admitted")
        return out
