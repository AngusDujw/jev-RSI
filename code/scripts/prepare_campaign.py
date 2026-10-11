"""Write nonsecret configs for the first five sensor-only RoboDojo tasks."""
from __future__ import annotations

import json
from pathlib import Path


CODE = Path('/home/user/ykj/project/gpt6/jev-RSI/code')
ROOT = Path('/data/ykj_robodojo/RoboLaya')
CAMPAIGN = ROOT / 'runs/jev-rsi-gpt-decision-20261011'
TEMPLATE = ROOT / 'runs/vision-method-20261011/config-v3-gpu0.json'


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def main() -> None:
    api = {
        'gpt': {
            'base_url': 'http://127.0.0.1:18883/v1',
            'auth_mode': 'none',
            'model': 'gpt-6.1-sol',
            'expected_model_prefix': 'gpt-6.1-sol',
            'reasoning_effort': 'high',
            'wire': 'chat',
            'max_tokens': 12000,
            'timeout_s': 1300,
            'transport_recovery_s': 300,
        },
        'decision': {
            'base_url': 'https://api.openai.com/v1',
            'key_file': '/home/user/.config/jev-rsi/du-openai-direct.key',
            'model': 'gpt-6-luna',
            'expected_model_prefix': 'gpt-6-luna',
            'reasoning_effort': 'medium',
            'wire': 'responses',
            'max_tokens': 3000,
            'timeout_s': 150,
            'transport_recovery_s': 300,
            'proxy': 'http://127.0.0.1:10408',
        },
    }
    write(CODE / 'config/api.du.json', api)
    template = json.loads(TEMPLATE.read_text())
    template.update(
        controller_root=str(CODE),
        sim_python=str(CODE / 'scripts/server02_isaac_python_private_ipc.sh'),
        api_config=str(CODE / 'config/api.du.json'),
        manifest=str(CODE / 'config/manifest-top5.json'),
        task_specs=str(CODE / 'config/staged-task-specs.json'),
        campaign=str(CAMPAIGN),
        variant='gpt61-high-plan-gpt6-luna-vision-v1',
        experience_bank_path=str(CAMPAIGN / 'experience.jsonl'),
        stop_file=str(CAMPAIGN / 'STOP'),
        timeout_s=6500,
        startup_timeout_s=500,
        minimum_free_gb=20,
        archive_completed_logs=False,
        preflight_api_connections=True,
        preflight_gpu_health=True,
        planner_prompt_mode='vision_method_v1',
        observation_mode='vision',
        track_material_points=False,
        decision_hold_stall_actions=4,
        max_planning_rounds=10,
    )
    template.pop('controller_commit', None)
    for gpu in (0, 1):
        cfg = dict(template, gpu_ids=[gpu], renderer_gpu_id=gpu,
                   base_port=19980 + gpu)
        write(CODE / f'config/campaign-top5-gpu{gpu}.json', cfg)


if __name__ == '__main__':
    main()
