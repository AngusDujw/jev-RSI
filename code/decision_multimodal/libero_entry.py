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
    profile = os.environ.get('DECISION_MM_LIBERO_PROFILE', 'frozen')
    if profile == 'frozen':
        api.API = LegacyAPI
    elif profile == 'libero-clarity-v1':
        from libero_prompt_revision import RevisedAPI
        api.API = RevisedAPI
    elif profile == 'libero-clarity-v2':
        from libero_prompt_revision_v2 import LocalAPI
        api.API = LocalAPI
    elif profile == 'libero-clarity-v3':
        from libero_prompt_revision_v2 import RecoveryAPI
        api.API = RecoveryAPI
    elif profile == 'libero-rgb-full':
        from libero_multimodal import MultimodalAPI, install_stream
        install_stream(args.arguments)
        api.API = MultimodalAPI
    else:
        raise ValueError('Unknown declared LIBERO request profile')
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
