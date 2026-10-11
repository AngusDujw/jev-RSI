"""RoboDojo RPC extension: isolated physical audit and explicit oracle ablation.

The upstream MIT bridge owns stepping and native task evaluation. This extension
never returns audit records to the policy, and refuses oracle RPC in vision mode.
"""
import json
import hashlib
import os
from pathlib import Path

import numpy as np
from PIL import Image


def array(value):
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value).tolist()


def install():
    from hybrid_rollout.robodojo.robodojo_server import session as upstream
    from hybrid_rollout.robodojo.robodojo_server.session import CAMERAS

    class CampaignSession(upstream.RoboDojoSession):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.input_mode = os.environ["COMPANY_OBSERVATION"]
            if self.input_mode not in ("oracle", "vision"):
                raise ValueError("Explicit observation mode required")
            self.metadata["company_observation"] = self.input_mode
            self.pending_audit = None
            self.audit_dir = self.output / "audit_only"
            self.audit_dir.mkdir(exist_ok=False)

        def _observe(self, record=False):
            # Keep the native RGB video at 25 Hz without duplicating every image
            # into compressed NPZ. Decision-boundary images are saved by policy.
            obs = super()._observe(record=False)
            if record:
                if self.video_writer is None:
                    import imageio.v2 as imageio
                    self.video_writer = imageio.get_writer(str(self.output / "sensors.mp4"),
                        fps=1 / self.metadata["control_dt"], codec="libx264",
                        pixelformat="yuv420p", macro_block_size=2,
                        output_params=["-movflags", "+faststart"])
                frames = [np.asarray(Image.fromarray(obs[k]).resize((640, 360))) for k in CAMERAS]
                self.video_writer.append_data(np.concatenate(frames, axis=1))
                self.video_frames += 1
            return obs

        def physical_snapshot(self):
            from scipy.spatial.transform import Rotation
            manager = self.env.scene_manager.layout_manager
            objects = []
            errors = []
            for kind, records in manager.object_records_by_type.items():
                for record in records.layout_records_by_env[0]:
                    name = record["inst_name"]
                    try:
                        pose = manager.get_instance_pose(env_idx=0, inst_name=name, relative=True)
                        if pose is None or pose[0] is None:
                            raise ValueError("No physical pose available")
                        metadata = manager.get_instance_metadata(env_idx=0, inst_name=name) or {}
                        descriptions = metadata.get("description", [])
                        if isinstance(descriptions, (list, tuple)):
                            descriptions = descriptions[:3]
                        objects.append(dict(id=name, kind=kind, category=record.get("category") or metadata.get("model_name"),
                            descriptions=descriptions,
                            position_m=array(pose[0]), quaternion_wxyz=array(pose[1]),
                            audit_label=record.get("label")))
                    except Exception as exc:
                        errors.append(dict(id=name, error=type(exc).__name__))
            grasp_points = []
            for arm in ("left", "right"):
                robot = self.kinematics.robots[arm]
                i = ("left", "right").index(arm)
                q = self.obs["eef_quaternions_wxyz"][i]
                offset = [float(robot.gripper_bias), 0., 0.]
                point = self.obs["eef_positions"][i] + Rotation.from_quat(q[[1, 2, 3, 0]]).apply(offset)
                grasp_points.append(array(point))
            cameras = {}
            cm = self.env.camera_manager
            for camera_id, name in enumerate(cm.camera_names[0]):
                alias = "cam_high" if name in ("cam_head", "head_camera", "top_camera") else name
                cameras[alias] = dict(intrinsic=array(cm.get_camera_intrinsics(camera_id, 0)),
                    camera_to_world=array(cm.get_camera_extrinsics(camera_id, 0)))
            return dict(tick=self.step_id, frame="environment_origin", objects=objects,
                cameras=cameras, env_origin=array(self.env.scene_manager.env_origins[0]),
                robot=dict(eef_positions_m=array(self.obs["eef_positions"]),
                    eef_quaternions_wxyz=array(self.obs["eef_quaternions_wxyz"]),
                    nominal_grasp_points_m=grasp_points,
                    grasp_reference="robot_config gripper_bias along link6 X; nominal, not measured contact",
                    states=array(self.obs["states"]), reference="link6, not fingertip center"),
                unavailable_objects=errors)

        def dispatch(self, op, args):
            if op == "reset":
                resolved = Path(self.env.seed_manager.seed_info[args["seed"]]["scene_layout"]).resolve()
                if resolved != Path(os.environ["COMPANY_LAYOUT_PATH"]) or hashlib.sha256(resolved.read_bytes()).hexdigest() != os.environ["COMPANY_LAYOUT_SHA256"]:
                    raise ValueError("Native SeedManager differs from frozen scene")
            if op == "robot_image_geometry":
                self._check_identity(args["episode_id"], args["step_id"])
                from .company_camera import robot_image_geometry
                cm = self.env.camera_manager
                calibration = {}
                for camera_id, name in enumerate(cm.camera_names[0]):
                    alias = "cam_high" if name in ("cam_head", "head_camera", "top_camera") else name
                    if alias not in CAMERAS:
                        continue
                    h, w = self.obs[alias].shape[:2]
                    calibration[alias] = dict(intrinsic=array(cm.get_camera_intrinsics(camera_id, 0)),
                        camera_to_world=array(cm.get_camera_extrinsics(camera_id, 0)), size=[w, h])
                # Deliberately independent of physical_snapshot / LayoutManager.
                return robot_image_geometry(self.obs["eef_positions"], self.obs["eef_quaternions_wxyz"],
                    calibration, array(self.env.scene_manager.env_origins[0]),
                    [float(self.kinematics.robots[arm].gripper_bias) for arm in ("left", "right")])
            if op in ("oracle_observation", "audit_before", "audit_after"):
                self._check_identity(args["episode_id"], args["step_id"])
                if op == "oracle_observation":
                    if self.input_mode != "oracle":
                        raise PermissionError("Ground truth is forbidden in vision mode")
                    snapshot = self.physical_snapshot()
                    if os.environ.get('COMPANY_ORACLE_GEOMETRY') == '1':
                        from .company_geometry import add_block_geometry
                        add_block_geometry(snapshot, Path(os.environ['COMPANY_LAYOUT_PATH']).parents[4]/'Object/RoboDojo', os.environ['COMPANY_LAYOUT_PATH'])
                    # Task-internal labels and unavailable-object identifiers are
                    # audit-only. Oracle gives physical state, never reward data.
                    return dict(source="privileged_simulator_physical_state", frame=snapshot["frame"],
                        objects=[{k: v for k, v in obj.items() if k != "audit_label"} for obj in snapshot["objects"]],
                        robot=snapshot["robot"])
                if op == "audit_before":
                    if self.pending_audit is not None:
                        raise RuntimeError("Previous decision audit not finalized")
                    self.pending_audit = dict(decision=args["decision"], declaration=args["declaration"],
                        before=self.physical_snapshot())
                    (self.audit_dir / f'decision-{args["decision"]:04d}-before.json').write_text(
                        json.dumps(self.pending_audit, allow_nan=False))
                    return dict(recorded=True)  # Absolutely no truth/score in ACK.
                if self.pending_audit is None:
                    raise RuntimeError("No pre-action declaration")
                row = dict(**self.pending_audit, after=self.physical_snapshot(), execution=args["execution"])
                with (self.audit_dir / "decisions.jsonl").open("a") as stream:
                    stream.write(json.dumps(row, allow_nan=False) + "\n")
                self.pending_audit = None
                return dict(recorded=True)
            result = super().dispatch(op, args)
            if op == "reset":
                (self.audit_dir / "initial.json").write_text(json.dumps(self.physical_snapshot(), indent=2))
            return result

    upstream.RoboDojoSession = CampaignSession


def main():
    # Kit adds extension search paths. Freeze RoboDojo's namespace package before
    # another extension's generic `utils` package can shadow it.
    from env.global_configs import ROOT_DIR
    import utils
    utils.__path__ = [str(Path(ROOT_DIR).resolve() / "utils")]
    import utils.load_file
    install()
    from hybrid_rollout.robodojo.robodojo_server.server import main as launch
    launch()


if __name__ == "__main__":
    main()
