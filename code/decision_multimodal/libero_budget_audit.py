"""Outer-only native budget checkpoints; never enter a model request."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys


def install(remaining):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--libero-root', type=Path, required=True)
    parser.add_argument('--gpu', default='0')
    args, _ = parser.parse_known_args(remaining)
    sys.path.insert(0, str(args.libero_root))
    os.environ.update(MUJOCO_GL='egl', MUJOCO_EGL_DEVICE_ID=str(args.gpu),
                      LIBERO_CONFIG_PATH=str(args.libero_root / '.libero-config'))
    from libero.libero.envs.env_wrapper import ControlEnv
    original = ControlEnv.step
    counts = {}

    def step(self, action):
        result = original(self, action)
        count = counts.get(id(self), 0) + 1
        counts[id(self)] = count
        if count in (600, 1200, 3000):
            # Read evaluator state exclusively for outer reporting. Return the
            # original observation/feedback unmodified; do not stop or branch.
            row = dict(physical_steps=count, native_success=bool(self.env._check_success()),
                       model_input=False, control_flow_changed=False)
            with (args.output / 'outer-budget-checkpoints.jsonl').open('a') as stream:
                stream.write(json.dumps(row) + '\n')
        return result

    ControlEnv.step = step


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--frozen-source', type=Path, required=True)
    args, remaining = parser.parse_known_args()
    source = args.frozen_source.resolve()
    sys.path.insert(0, str(source.parent))
    namespace = runpy.run_path(str(source), run_name='pinned_actor_budget_probe')
    install(remaining)
    sys.argv = [str(source), *remaining]
    namespace['main']()


if __name__ == '__main__':
    main()
