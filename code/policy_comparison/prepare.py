"""Prepare an isolated official GPT-as-Policy Luna/high execution copy."""
import hashlib
import json
import os
from pathlib import Path
import shutil

PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT / 'code/runs/server02-policy-comparison-20261018'
SOURCE = Path('/home/ykj/project/gpt6/benchmark/gpt_as_policy_robodojo/src/GPT-as-Policy')
PYTHON = Path('/home/ykj/project/gpt6/benchmark/gpt_as_policy_robodojo/.venv/bin/python')


def prepare():
    ROOT.mkdir(parents=True, exist_ok=True)
    runtime = ROOT / 'official_runtime'
    if not runtime.exists():
        shutil.copytree(SOURCE / 'hybrid_rollout', runtime / 'hybrid_rollout',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        settings = runtime / 'hybrid_rollout/robodojo/settings.py'
        text = settings.read_text().replace("MODEL = 'gpt-6-astra'", "MODEL = 'gpt-6-luna'")
        text = text.replace("EFFORT = 'xhigh'", "EFFORT = 'high'")
        settings.write_text(text)
        context = runtime / 'hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/teacher_context.md'
        context.write_text(context.read_text().replace('GPT-6/xhigh', 'GPT-6 Luna/high'))
    changes = []
    manifest = []
    for dest in sorted(runtime.rglob('*')):
        if not dest.is_file() or '__pycache__' in dest.parts:
            continue
        rel = dest.relative_to(runtime)
        original = SOURCE / rel
        sha = hashlib.sha256(dest.read_bytes()).hexdigest()
        old = hashlib.sha256(original.read_bytes()).hexdigest()
        manifest.append(dict(path=str(rel), source_sha256=old, runtime_sha256=sha))
        if sha != old:
            changes.append(str(rel))
    allowed = ['hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/teacher_context.md',
               'hybrid_rollout/robodojo/settings.py']
    if sorted(changes) != allowed:
        raise RuntimeError('Unexpected official source changes: ' + repr(changes))
    (ROOT / 'source_manifest.json').write_text(json.dumps(dict(source=str(SOURCE),
        provenance_commit='8f3d362b077d8efb77e2a7274d5b2c20e2243846',
        changes=changes, files=manifest), indent=2) + '\n')
    auth = json.loads((Path.home() / '.codex/auth.json').read_text())
    if auth.get('auth_mode') != 'chatgpt' or auth.get('OPENAI_API_KEY') or not auth.get('tokens'):
        raise RuntimeError('A genuine local ChatGPT login is required; no API fallback')
    private = PROJECT / '.private/server02-policy-pro-20261018'
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    for task in ('stack_blocks', 'classify_objects'):
        for layout in range(3):
            home = private / f'{task}-{layout}'
            home.mkdir(exist_ok=True, mode=0o700)
            credential = home / 'auth.json'
            if not credential.exists():
                fd = os.open(credential, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    json.dump(auth, stream)
            (home / 'config.toml').write_text('model_provider = "openai"\nmodel = "gpt-6-luna"\n'
                'model_reasoning_effort = "high"\ncli_auth_credentials_store = "file"\n'
                'forced_login_method = "chatgpt"\n[analytics]\nenabled = false\n')
    print(json.dumps(dict(runtime=str(runtime), changes=changes, auth='ChatGPT_Pro_only',
                          homes=6, python=str(PYTHON))))


if __name__ == '__main__':
    prepare()
