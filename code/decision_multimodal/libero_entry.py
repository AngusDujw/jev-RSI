"""Run an unchanged frozen LIBERO policy with only its Jev API replaced."""
import argparse
import json
import os
from pathlib import Path
import runpy
import signal
import sys
from legacy_decisions import LegacyAPI


def main():
    # Let original finally blocks close their own vision worker on termination.
    def terminate(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser()
    parser.add_argument('--policy', required=True, type=Path)
    parser.add_argument('--controller-root', required=True, type=Path)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    policy = args.policy.resolve()
    if not policy.is_file() or policy.name != 'libero_jev_rollout.py':
        raise ValueError('Explicit frozen rollout source required')
    sys.path.insert(0, str(args.controller_root / 'controller/src'))
    import realman_jev.api as api
    api.API = LegacyAPI
    sys.path.insert(0, str(policy.parent))
    config = policy.parent / 'decision-api-config.json'
    if json.loads(config.read_text()) != {'jev': {'model': 'gpt-6-luna'}}:
        raise ValueError('Sanitized Decisions-only configuration required')
    os.environ['JEV_RSI_API_CONFIG'] = str(config)
    os.environ['JEV_RSI_MODEL_BACKEND'] = 'jev'
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    sys.argv = [str(policy), *arguments]
    runpy.run_path(str(policy), run_name='__main__')


if __name__ == '__main__':
    main()
