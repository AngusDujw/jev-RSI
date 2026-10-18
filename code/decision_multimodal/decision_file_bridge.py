"""SSH file transport for Decisions when a remote proxy path is unavailable.

Only /v1/decisions is callable. Credentials stay local and never enter a job.
The remote native loop still owns observations, decisions and physical actions.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import time
import urllib.request

ENDPOINT='https://api.openai.com/v1/decisions'


class FileClient:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir();self.counter=0
    def open(self,request,timeout=120):
        assert request.full_url==ENDPOINT
        folder=self.root/f'{self.counter:04d}';self.counter+=1;folder.mkdir()
        payload=json.loads(request.data)
        (folder/'pending.json').write_text(json.dumps(dict(endpoint=ENDPOINT,payload=payload)))
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if (folder/'reply.json').exists():
                result=json.loads((folder/'reply.json').read_text())
                if 'bridge_error' in result:raise RuntimeError(result['bridge_error'])
                return io.BytesIO(json.dumps(result).encode())
            time.sleep(.2)
        raise TimeoutError('Local Decisions bridge did not return before the physical loop timeout')


def ssh(host,code,input=None):
    command='python3 -c '+shlex.quote(code)
    done=subprocess.run(['ssh','--',host,command],input=input,text=True,capture_output=True)
    if done.returncode:raise RuntimeError(done.stderr[-600:])
    return done.stdout


def main():
    p=argparse.ArgumentParser();p.add_argument('--host',required=True)
    p.add_argument('--remote-roots',nargs='+',required=True)
    p.add_argument('--key-file',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seconds',type=int,default=1800)
    a=p.parse_args();assert a.key_file.name=='du-openai-direct.key'
    key=a.key_file.read_text().strip();assert key.startswith('sk-')
    a.output.mkdir(parents=True,exist_ok=False)
    client=urllib.request.build_opener(urllib.request.ProxyHandler({'https':'http://127.0.0.1:7897'}))
    started=time.monotonic();calls=0;seen=set()
    while time.monotonic()-started<a.seconds:
        code=('import pathlib,json; roots='+repr(a.remote_roots)+'; print(json.dumps([str(p) for r in roots '
            'for p in pathlib.Path(r).glob("bridge-jobs/*/pending.json") if not (p.parent/"reply.json").exists()]))')
        pending=json.loads(ssh(a.host,code))
        for remote in pending:
            if remote in seen:continue
            seen.add(remote);folder=a.output/f'{calls:04d}';calls+=1;folder.mkdir()
            job=json.loads(ssh(a.host,'import pathlib; print(pathlib.Path('+repr(remote)+').read_text())'))
            assert job['endpoint']==ENDPOINT and job['payload']['model']=='gpt-6-luna'
            (folder/'request.json').write_text(json.dumps(job['payload']))
            (folder/'dispatch.json').write_text(json.dumps(dict(endpoint=ENDPOINT,key_origin='du',
                key_file=str(a.key_file),remote_job=remote,transport='local authorized proxy via SSH file spool',
                request_sha256=hashlib.sha256(json.dumps(job['payload']).encode()).hexdigest())))
            request=urllib.request.Request(ENDPOINT,data=json.dumps(job['payload']).encode(),
                headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
            try:
                with client.open(request,timeout=100) as response:reply=json.load(response)
            except Exception as error:
                reply=dict(bridge_error=type(error).__name__+': '+str(error).replace(key,'[redacted]')[:500])
            (folder/'reply.json').write_text(json.dumps(reply))
            target=str(Path(remote).parent/'reply.json')
            code=('import pathlib,sys,os; p=pathlib.Path('+repr(target)+'); '
                't=p.with_suffix(".part"); t.write_text(sys.stdin.read()); os.replace(t,p)')
            ssh(a.host,code,input=json.dumps(reply))
            print(json.dumps(dict(call=calls,remote_job=remote,answered='answers' in reply)),flush=True)
        # Exit after all requested native loops have written their final result.
        if calls:
            code='import pathlib; print(int(all((pathlib.Path(p)/"result.json").exists() for p in '+repr(a.remote_roots)+')))'
            if ssh(a.host,code).strip()=='1':break
        time.sleep(.5)


if __name__=='__main__':main()
