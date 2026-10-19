"""Verify local ChatGPT login, writable SQLite and original app-server startup.

No inference turn, OpenAI API key, native simulator or old episode is used.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3

from hybrid_rollout.robodojo.skill.run import CodexPolicy


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    auth=json.loads((Path(os.environ['CODEX_HOME'])/'auth.json').read_text())
    if auth.get('auth_mode')!='chatgpt' or auth.get('OPENAI_API_KEY') or not auth.get('tokens'):
        raise RuntimeError('Local ChatGPT login required; no API fallback')
    state=Path(os.environ['ROLLOUT_CODEX_STATE_DIR'])
    state.mkdir(parents=True,exist_ok=False)
    if shutil.disk_usage(state).free<4*1024**3:raise RuntimeError('Need 4GiB free local state storage')
    probe=state/'storage-probe.sqlite'
    with sqlite3.connect(probe) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE probe(value INTEGER)')
        db.execute('INSERT INTO probe VALUES(1)')
        db.commit()
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('SQLite probe failed')
    for suffix in ('','-wal','-shm'):(state/('storage-probe.sqlite'+suffix)).unlink(missing_ok=True)
    worker=CodexPolicy(args.output/'workspace',shutil.which('codex'),method='gpt_only')
    try:
        result=dict(auth_mode='chatgpt',api_key_used=False,model='gpt-6-luna',effort='high',
            sqlite_probe='passed',app_server_initialize='passed',thread_start='passed',
            inference_turns=0,model_access_entitlement_checked=False)
        (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result),flush=True)
    finally:worker.close()


if __name__=='__main__':main()
