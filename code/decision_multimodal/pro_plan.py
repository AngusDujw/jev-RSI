"""Foreground local ChatGPT Pro planning with isolated, English task context."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from legacy_decisions import english


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prompt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--image', type=Path, action='append', default=[])
    args = parser.parse_args()
    prompt = args.prompt.read_text()
    english(prompt)
    for image in args.image:
        english(str(image))
        if not image.is_file():
            raise ValueError('Planner image missing')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output/'prompt.txt').write_text(prompt)
    command = ['codex', 'exec', '--ephemeral', '--ignore-user-config',
        '--skip-git-repo-check', '--model', 'gpt-6.1-sol',
        '-c', 'model_reasoning_effort="high"',
        # The outer research agent follows AGENTS.md. It is not task context
        # for the internal planner, and can contain non-English instructions.
        '-c', 'project_doc_max_bytes=0',
        '-c', 'features.skip_host_skill_discovery=true',
        '-c', 'features.plugins=false', '-c', 'features.remote_plugin=false',
        '-c', 'features.skill_search=false',
        '-c', 'suppress_unstable_features_warning=true',
        '--sandbox', 'read-only', '--json',
        '-o', str(output/'response.txt')]
    for image in args.image:
        command += ['-i', str(image.resolve())]
    command += ['-']
    audit = dict(model='gpt-6.1-sol', reasoning_effort='high',
        authentication='existing local ChatGPT Pro login; no API key',
        project_doc_max_bytes=0, host_skill_discovery=False, plugins=False,
        image_paths=[str(p.resolve()) for p in args.image], experience_injection=False,
        command=command)
    (output/'dispatch.json').write_text(json.dumps(audit, indent=2)+'\n')
    env = os.environ.copy()
    for key in ('OPENAI_API_KEY', 'OPENAI_BASE_URL', 'CODEX_API_KEY'):
        env.pop(key, None)
    print(json.dumps(dict(event='planner_started', output=str(output), model='gpt-6.1-sol', effort='high')), flush=True)
    with (output/'events.jsonl').open('w') as events, (output/'stderr.log').open('w') as errors:
        done = subprocess.run(command, input=prompt, text=True, env=env,
                              stdout=events, stderr=errors)
    if done.returncode:
        raise RuntimeError('Local Pro planner failed; original stderr preserved')
    records = [json.loads(line) for line in (output/'events.jsonl').read_text().splitlines()]
    for record in records:
        if record.get('type') != 'item.completed':
            continue
        item = record.get('item', {})
        if item.get('type') in ('agent_message', 'reasoning'):
            continue
        if item.get('type') == 'error' and item.get('message', '').startswith(
                'Under-development features enabled: skip_host_skill_discovery.'):
            continue  # CLI startup advisory, not a model tool call.
        raise ValueError('Unexpected tool activity or error in internal planning call')
    text = (output/'response.txt').read_text()
    english(text)
    result = json.loads(text)
    english(result)
    (output/'plan.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps(dict(event='planner_accepted', output=str(output/'plan.json'))), flush=True)


if __name__ == '__main__':
    main()
