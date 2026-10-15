"""One foreground native episode with public RGB/calibration/robot interfaces.

Task-specific processing and phase logic live in a separately frozen controller.
The actor initially receives text only. No experience or evaluator fields are
included in the public observation supplied to that controller.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation
from legacy_decisions import LegacyAPI
from run_libero_campaign import GPU_UUIDS

ROOT = Path('/root/yekangjie/project/robodojo-jev')
PYTHON = ROOT/'envs/robodojo-isaac51/bin/python'
ARMS = ('left', 'right')
CAMERAS = ('cam_high', 'cam_left_wrist', 'cam_right_wrist')


def save(path, value):
    def arrays(item):
        if isinstance(item, np.ndarray):
            return item.tolist()
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError(type(item).__name__)
    path.write_text(json.dumps(value, default=arrays, indent=2, allow_nan=False)+'\n')


def transform(position, quaternion):
    result = np.eye(4)
    result[:3, :3] = Rotation.from_quat(np.asarray(quaternion)[[1, 2, 3, 0]]).as_matrix()
    result[:3, 3] = position
    return result


class Episode:
    def __init__(self, args):
        self.args = args
        self.folder = args.output.resolve()
        self.folder.mkdir(parents=True, exist_ok=False)
        self.tick, self.episode_id = 0, None
        self.client = self.actor = self.process = None
        self.mounts = {}
        self.last_decision_tick = None
        self.action_used = True
        self.ended = False
        self.program_finished = False

    def event(self, value):
        with (self.folder/'events.jsonl').open('a') as handle:
            handle.write(json.dumps(dict(wall_time=time.time(), **value))+'\n')

    def open(self):
        paths = [Path(__file__).resolve().parent, ROOT/'GPT-as-Policy',
                 ROOT/'robodojo', ROOT/'robodojo/XPolicyLab', ROOT/'controller/src']
        for path in paths:
            sys.path.insert(0, str(path))
        from hybrid_rollout.robodojo.robodojo_server.protocol import RPCClient
        with socket.socket() as socket_:
            socket_.bind(('127.0.0.1', 0))
            port = socket_.getsockname()[1]
        cache = self.folder/'cache'
        cache.mkdir()
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(map(str, paths)),
            TMPDIR=str(cache), XDG_CACHE_HOME=str(cache),
            TORCH_EXTENSIONS_DIR=str(cache/'torch_extensions'),
            ROBODOJO_DECISION_CACHE=str(cache), ROBODOJO_TASK=self.args.task,
            ROBODOJO_MEASURED_GRIPPER_STATE='1', ROBODOJO_SYNC_PUBLIC_WRIST_MOUNTS='1',
            ROBODOJO_FOLD_CPU_USD_SYNC_AUDIT='1' if self.args.task == 'fold_clothes' else '0',
            ROBODOJO_PRESS_GPU_FABRIC_AUDIT='1' if self.args.task == 'press_by_number' else '0',
            OMNI_KIT_ACCEPT_EULA='YES', ACCEPT_EULA='Y',
            CUDA_VISIBLE_DEVICES=GPU_UUIDS[self.args.gpu],
            OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
            HTTP_PROXY='http://127.0.0.1:7897', HTTPS_PROXY='http://127.0.0.1:7897',
            NO_PROXY='127.0.0.1,localhost', PYTHONDONTWRITEBYTECODE='1',
            OMNICLIENT_HTTP_TIMEOUT='10', OMNICLIENT_HTTP_RETRIES='1')
        command = [str(PYTHON), '-B', '-u', str(Path(__file__).with_name('robodojo_sensor_server.py')),
            '--task', self.args.task, '--eval-seed', '0', '--output', str(self.folder/'native'),
            '--port', str(port), '--headless', '--enable_cameras', '--device', 'cuda:0',
            '--kit_args=--/renderer/activeGpu='+str(self.args.gpu)+
            ' --/renderer/multiGpu/enabled=false --/app/renderer/waitIdle=true --/app/hydraEngine/waitIdle=true']
        save(self.folder/'launch.json', dict(command=command, gpu=self.args.gpu,
            gpu_uuid=GPU_UUIDS[self.args.gpu], task=self.args.task, layout=self.args.layout,
            actor='gpt-6-luna', actor_images=0, planner='local ChatGPT Pro gpt-6.1-sol/high',
            inputs='three RGB, public camera calibration and measured robot state only',
            experience_injection=False))
        self.log = (self.folder/'simulator.log').open('w')
        self.process = subprocess.Popen(command, cwd=ROOT/'robodojo', env=env,
            stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic()+900
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError('Simulator exited before readiness; inspect simulator.log')
            text = (self.folder/'simulator.log').read_text(errors='replace')[-16000:]
            if '"event": "ready"' in text:
                break
            time.sleep(2)
        else:
            raise TimeoutError('Native RPC readiness timeout')
        self.client = RPCClient('127.0.0.1', port, timeout=300)
        self.metadata = self.client.request('metadata')
        reset = self.client.request('reset', seed=self.args.layout, source='gpt_eef',
                                    policy_version='fixed_task_decision_text')
        self.episode_id = reset['episode_id']
        self.tick = reset['step_id']
        save(self.folder/'reset.json', reset)
        return self.observe()

    def rpc(self, op, **kwargs):
        return self.client.request(op, episode_id=self.episode_id, step_id=self.tick, **kwargs)

    def observe(self):
        raw = self.rpc('teacher_observation')
        calibration = self.rpc('public_camera_calibration')['cameras']
        for index, arm in enumerate(ARMS):
            name = 'cam_'+arm+'_wrist'
            link = transform(raw['eef_positions'][index], raw['eef_quaternions_wxyz'][index])
            if arm not in self.mounts:
                self.mounts[arm] = np.linalg.inv(link) @ np.asarray(calibration[name]['camera_to_environment'])
            calibration[name]['camera_to_environment'] = (link @ self.mounts[arm]).tolist()
        gripper = self.rpc('public_robot_gripper_state')
        # Strict whitelist; never copy ACK, native result, reward or scene metadata.
        public = dict(step=self.tick, instruction=raw['instruction'],
            robot={k: np.asarray(raw[k]).tolist() for k in
                   ('states', 'eef_positions', 'eef_quaternions_wxyz')},
            measured_gripper=gripper['arms'], calibration=calibration,
            rgb={name: np.asarray(raw[name]) for name in CAMERAS})
        self.public = public
        directory = self.folder/f'frame-{self.tick:06d}'
        if not directory.exists():
            directory.mkdir()
            for name in CAMERAS:
                Image.fromarray(public['rgb'][name]).save(directory/(name+'.png'))
            save(directory/'public.json', {k: v for k, v in public.items() if k != 'rgb'})
        return public

    def decide(self, state, questions):
        if self.ended or self.last_decision_tick == self.tick:
            raise ValueError('One actor decision per fresh physical step; no repeated sampling')
        if self.actor is None:
            os.environ['DECISION_MM_KEY_FILE'] = str(self.args.key_file.resolve())
            os.environ['DECISION_MM_PROXY'] = 'http://127.0.0.1:7897'
            self.actor = LegacyAPI({}, self.event, 'jev')
        answer = self.actor.post('/systemone', dict(model='gpt-6-luna', state=state, questions=questions))
        self.last_decision_tick, self.action_used = self.tick, False
        return answer['answers']

    def execute(self, targets, steps=5):
        if self.ended or self.action_used or self.last_decision_tick != self.tick:
            raise ValueError('Current actual actor answer required before execution')
        if set(targets) != set(ARMS) or not 1 <= steps <= 5:
            raise ValueError('Explicit dual arm targets and 1..5 native steps required')
        robot = self.public['robot']
        for index, arm in enumerate(ARMS):
            target = targets[arm]
            position = np.asarray(target['position'], dtype=float)
            if position.shape != (3,) or not np.isfinite(position).all():
                raise ValueError('Invalid EEF target position')
            if np.linalg.norm(position-robot['eef_positions'][index]) > .050001:
                raise ValueError('EEF translation exceeds 0.05m')
            q = np.asarray(target['quaternion_wxyz'])
            old = np.asarray(robot['eef_quaternions_wxyz'][index])
            if q.shape != (4,) or not np.isfinite(q).all() or abs(np.linalg.norm(q)-1) > .001:
                raise ValueError('Invalid target orientation')
            angle = (Rotation.from_quat(q[[1, 2, 3, 0]]) *
                     Rotation.from_quat(old[[1, 2, 3, 0]]).inv()).magnitude()
            if angle > .350001:
                raise ValueError('EEF rotation exceeds 0.35rad')
            opening = target['gripper_opening']
            if not np.isfinite(opening) or not 0 <= opening <= 1:
                raise ValueError('Invalid gripper opening')
        self.action_used = True
        before = self.tick
        for _ in range(steps):
            proposal = self.rpc('eef_joint_target', targets=targets)
            ack = self.rpc('chunk_step', actions=np.asarray(proposal['action'], np.float32).reshape(1, 14),
                           controller='fixed_task_decision_text')
            self.tick = ack['step_id']
            self.ended = any(row['terminated'] or row['truncated'] for row in ack['steps'])
            save(self.folder/f'execution-{self.tick:06d}.json', dict(proposal=proposal, native_ack=ack))
            if self.ended:
                break
        self.event(dict(kind='action', start_step=before, end_step=self.tick, targets=targets))
        return self.observe()

    def close(self):
        error = None
        if self.client is not None:
            try:
                result = self.rpc('finish_pilot', reason='terminal' if self.ended else 'controller_finished_incomplete')
                save(self.folder/'native_finish.json', result)
                save(self.folder/'result.json', dict(program_finished=self.program_finished,
                    native=result, joint_success=self.program_finished and result.get('success') is True))
            except Exception as failure:
                error = failure
            finally:
                self.client.close()
        if self.actor is not None:
            self.actor.close()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        if hasattr(self, 'log'):
            self.log.close()
        if error is not None:
            self.event(dict(kind='finish_transport_error', error_type=type(error).__name__, error=str(error)[:300]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', choices=['stack_blocks', 'general_pickup', 'fold_clothes', 'press_by_number', 'stack_bowls'], required=True)
    parser.add_argument('--gpu', type=int, choices=[4, 5, 6, 7], required=True)
    parser.add_argument('--layout', type=int, default=0)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--controller', type=Path)
    args = parser.parse_args()
    episode = Episode(args)
    def terminate(signum, frame):
        raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        episode.open()
        print(json.dumps(dict(event='public_observation_ready', output=str(episode.folder), step=episode.tick)), flush=True)
        controller = args.controller
        if controller is None:
            # Keep this native episode paused while its current images are reviewed.
            for line in sys.stdin:
                request = json.loads(line)
                if request.get('op') == 'run_controller':
                    controller = Path(request['controller'])
                    break
                if request.get('op') == 'finish':
                    return
                raise ValueError('Expected a fixed controller path or explicit finish')
        if controller is not None:
            source = controller.resolve()
            import hashlib
            save(episode.folder/'controller_source.json', dict(path=str(source), sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
            spec = importlib.util.spec_from_file_location('fixed_task_controller', source)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.run(episode)
    finally:
        episode.close()


if __name__ == '__main__':
    main()
