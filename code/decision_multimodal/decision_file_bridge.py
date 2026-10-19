"""Durable concurrent SSH transport restricted to authorized du /v1/decisions."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import threading
import time
import urllib.request
import urllib.error

ENDPOINT='https://api.openai.com/v1/decisions'
CONTROL=None


class FileClient:
    def __init__(self,root,compact=False):
        self.root=Path(root);self.root.mkdir();self.counter=0;self.compact=compact
    def open(self,request,timeout=120):
        assert request.full_url==ENDPOINT
        folder=self.root/f'{self.counter:04d}';self.counter+=1;folder.mkdir()
        temporary=folder/'pending.part'
        temporary.write_text(json.dumps(dict(endpoint=ENDPOINT,payload=json.loads(request.data))))
        temporary.replace(folder/'pending.json')
        deadline=time.monotonic()+max(timeout,1800)
        try:
            while time.monotonic()<deadline:
                if (folder/'reply.json').exists():
                    raw=(folder/'reply.json').read_bytes()
                    try:result=json.loads(raw)
                    except (ValueError,UnicodeError):
                        # Keep the same observation pending; let the broker resend its
                        # persisted answer, never call the model to replace a bad copy.
                        (folder/'reply.json').replace(folder/'reply.invalid')
                        with (folder/'delivery-errors.jsonl').open('a') as f:
                            f.write(json.dumps(dict(time=time.time(),bytes=len(raw),
                                sha256=hashlib.sha256(raw).hexdigest(),reason='Invalid delivered JSON'))+'\n')
                        continue
                    if 'bridge_error' in result:raise RuntimeError(result['bridge_error'])
                    return io.BytesIO(json.dumps(result).encode())
                time.sleep(.2)
            raise TimeoutError('Local Decisions bridge exceeded the physical loop timeout')
        finally:
            if self.compact:(folder/'pending.json').unlink(missing_ok=True)


def ssh(host,code,input=None):
    command='python3 -c '+shlex.quote(code)
    for attempt in range(2):
        opts=(['-o','ControlMaster=auto','-o','ControlPersist=60','-o','ControlPath='+CONTROL]
            if CONTROL and attempt==0 else ['-o','ControlMaster=no','-o','ControlPath=none'])
        try:
            done=subprocess.run(['ssh','-o','ConnectTimeout=10','-o','ServerAliveInterval=10',
                '-o','ServerAliveCountMax=2',*opts,'--',host,command],input=input,text=True,capture_output=True,timeout=35)
            if done.returncode:raise RuntimeError(done.stderr[-600:])
            return done.stdout
        except (subprocess.TimeoutExpired,OSError,RuntimeError):
            if attempt:raise
            # All bridge commands are read/verified-file-write operations. Retry
            # over a fresh connection rather than reusing a possibly stuck master.


def delivery_command(target,expected_sha256):
    """Validate complete bytes before publication; return a content-hash ACK."""
    return ('import pathlib,sys,os,json,hashlib; p=pathlib.Path('+repr(target)+'); '
        'raw=sys.stdin.buffer.read(); '
        'assert hashlib.sha256(raw).hexdigest()=='+repr(expected_sha256)+',"Reply transfer hash mismatch"; '
        'assert isinstance(json.loads(raw),dict),"Reply must be a JSON object"; '
        't=p.with_suffix(".part"); t.write_bytes(raw); os.replace(t,p); '
        'print(hashlib.sha256(raw).hexdigest())')


def main():
    global CONTROL
    p=argparse.ArgumentParser();p.add_argument('--host',required=True)
    p.add_argument('--remote-roots',nargs='+',required=True)
    p.add_argument('--key-file',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seconds',type=int,default=14400);p.add_argument('--workers',type=int,default=1)
    p.add_argument('--compact',action='store_true');p.add_argument('--control-path')
    p.add_argument('--resume',action='store_true')
    a=p.parse_args();assert a.key_file.name=='du-openai-direct.key';assert 1<=a.workers<=24
    CONTROL=a.control_path;key=a.key_file.read_text().strip();assert key.startswith('sk-')
    a.output.mkdir(parents=True,exist_ok=a.resume)
    lock=threading.Lock();calls=0;seen=set();active={};started=time.monotonic();last_served={}
    def process(remote):
        nonlocal calls
        folder=a.output/hashlib.sha256(remote.encode()).hexdigest()[:20];folder.mkdir(exist_ok=True)
        if (folder/'reply.json').exists():reply=json.loads((folder/'reply.json').read_text());called=False
        else:
            job=json.loads(ssh(a.host,'import pathlib; print(pathlib.Path('+repr(remote)+').read_text())'))
            assert job['endpoint']==ENDPOINT and job['payload']['model']=='gpt-6-luna'
            raw=json.dumps(job['payload']).encode()
            if not a.compact:(folder/'request.json').write_bytes(raw)
            (folder/'dispatch.json').write_text(json.dumps(dict(endpoint=ENDPOINT,key_origin='du',
                remote_job=remote,compact=a.compact,request_sha256=hashlib.sha256(raw).hexdigest())))
            request=urllib.request.Request(ENDPOINT,data=raw,
                headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
            client=urllib.request.build_opener(urllib.request.ProxyHandler({'https':'http://127.0.0.1:7897'}))
            called=True
            for attempt in range(3):
                with lock:calls+=1
                try:
                    with client.open(request,timeout=100) as response:reply=json.load(response)
                    break  # A received answer/refusal is never resampled.
                except (OSError,urllib.error.URLError) as error:
                    retryable=not isinstance(error,urllib.error.HTTPError) or error.code in (429,502,503,504)
                    with (folder/'network-attempts.jsonl').open('a') as f:
                        f.write(json.dumps(dict(attempt=attempt+1,time=time.time(),retryable=retryable,
                            error=str(error).replace(key,'[redacted]')[:500],received_answer=False))+'\n')
                    if not retryable or attempt==2:
                        reply=dict(bridge_error=type(error).__name__+': '+str(error).replace(key,'[redacted]')[:500]);break
                    time.sleep(2**(attempt+1))
                except Exception as error:
                    reply=dict(bridge_error=type(error).__name__+': '+str(error).replace(key,'[redacted]')[:500]);break
            temporary=folder/'reply.part';temporary.write_text(json.dumps(reply));temporary.replace(folder/'reply.json')
        target=str(Path(remote).parent/'reply.json')
        body=json.dumps(reply);digest=hashlib.sha256(body.encode()).hexdigest()
        ack=ssh(a.host,delivery_command(target,digest),input=body)
        if ack.strip()!=digest:raise RuntimeError('Missing verified reply-delivery acknowledgement')
        print(json.dumps(dict(remote_job=remote,answered='answers' in reply,model_called=called)),flush=True)
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        while time.monotonic()-started<a.seconds:
            for path,future in list(active.items()):
                if not future.done():continue
                try:future.result();seen.add(path)
                except Exception as error:
                    with (a.output/'transport-events.jsonl').open('a') as f:
                        f.write(json.dumps(dict(time=time.time(),operation='transfer',error=str(error).replace(key,'[redacted]')[-500:]))+'\n')
                del active[path]
            (a.output/'heartbeat.json').write_text(json.dumps(dict(time=time.time(),calls=calls,inflight=len(active),workers=a.workers)))
            code=('import pathlib,json; roots='+repr(a.remote_roots)+'; print(json.dumps([str(p) for r in roots '
                'for p in pathlib.Path(r).glob("bridge-jobs/*/pending.json") if not (p.parent/"reply.json").exists()]))')
            try:pending=json.loads(ssh(a.host,code))
            except (RuntimeError,subprocess.TimeoutExpired,OSError):time.sleep(2);continue
            # Old fixed-root order let fast early roots repeatedly occupy all workers.
            # Round-robin by episode, including its previous request, prevents starvation.
            pending.sort(key=lambda path:last_served.get(str(Path(path).parents[2]),0))
            for path in pending:
                # A quarantined corrupt delivery can reappear here even after ACK.
                # process() reuses the saved answer; it does not resample the model.
                if path not in active and len(active)<a.workers:
                    last_served[str(Path(path).parents[2])]=time.monotonic()
                    active[path]=pool.submit(process,path)
            if not active and (calls or a.resume):
                code='import pathlib; print(int(all((pathlib.Path(p)/"result.json").exists() for p in '+repr(a.remote_roots)+')))'
                try:
                    if ssh(a.host,code).strip()=='1':break
                except (RuntimeError,subprocess.TimeoutExpired,OSError):pass
            time.sleep(.5)


if __name__=='__main__':main()
