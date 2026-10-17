"""Explicit own-robot initial pose perturbation for the rectangular-box test."""
import json
import os
from pathlib import Path


def install(arguments):
    task=int(arguments[arguments.index('--task-id')+1])
    if task!=1335:return
    init=int(arguments[arguments.index('--init-index')+1])
    from libero.libero.envs.env_wrapper import ControlEnv
    from scipy.spatial.transform import Rotation
    import numpy as np
    import libero_multimodal as stream
    original=ControlEnv.set_init_state
    original_step=ControlEnv.step

    def budgeted_step(env,*args,**kwargs):
        if stream.CURRENT.tick>=600:
            raise RuntimeError('Combined native600-step budget exhausted, including own-robot setup')
        return original_step(env,*args,**kwargs)
    ControlEnv.step=budgeted_step

    def perturbed(env,*args,**kwargs):
        obs=original(env,*args,**kwargs)
        position=obs['robot0_eef_pos'].copy()
        initial=Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
        sign=1 if init%2 else -1
        offset=np.deg2rad([sign*12,-sign*12,sign*25])
        target=Rotation.from_rotvec(offset).as_matrix()@initial
        count=0
        for count in range(45):
            current=Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
            error=Rotation.from_matrix(target@current.T).as_rotvec()
            if np.linalg.norm(error)<.02:break
            delta=np.clip(position-obs['robot0_eef_pos'],-.005,.005)
            turn=np.clip(error*.5,-.06,.06)
            obs,_,_,_=env.step(np.r_[delta/.05,turn/.5,-1])
        final=Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
        residual=float(np.linalg.norm(Rotation.from_matrix(target@final.T).as_rotvec()))
        record=dict(task=task,init=init,purpose='Own-robot setup, not model performance',
            requested_rotation_vector_rad=offset.tolist(),setup_steps=count,
            residual_rad=residual,translation_drift_m=float(np.linalg.norm(obs['robot0_eef_pos']-position)),
            object_state_used=False)
        root=Path(os.environ['DECISION_MM_ASSET_ROOT']);root.mkdir(exist_ok=True)
        (root/'rotation-setup.json').write_text(json.dumps(record,indent=2)+'\n')
        if residual>.04:raise RuntimeError('Initial own-robot rotation setup did not track')
        return obs
    ControlEnv.set_init_state=perturbed
