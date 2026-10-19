"""Durable concurrent SSH transport restricted to authorized du /v1/decisions."""
import argparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import shlex
import subprocess
import threading
import time
import urllib.request
import urllib.error

ENDPOINT='https://api.openai.com/v1/decisions'
CONTROL=None
SSH_SLOTS=threading.BoundedSemaphore(3)


class ImageMemory:
    """Bounded transient image URLs; no rollout image files on the local disk."""
    def __init__(self,limit=64*1024**2):
        self.limit=limit;self.bytes=0;self.values=OrderedDict();self.lock=threading.Lock()
    def get(self,key):
        with self.lock:
            value=self.values.get(key)
            if value is not None:self.values.move_to_end(key)
            return value
    def put(self,key,value):
        assert hashlib.sha256(value.encode()).hexdigest()==key,'Image transport hash mismatch'
        with self.lock:
            if key in self.values:return
            self.values[key]=value;self.bytes+=len(value)
            while self.bytes>self.limit and self.values:
                _,old=self.values.popitem(last=False);self.bytes-=len(old)


def fetch_job(host,remote,memory):
    """Transfer changed images only, then verify the full original payload hash."""
    prelude='import pathlib,json,hashlib; job=json.loads(pathlib.Path('+repr(remote)+').read_text()); '
    slim=ssh(host,prelude+
        'digest=hashlib.sha256(json.dumps(job["payload"],sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest(); '
        '\nfor message in job["payload"]["input"]:\n for part in message["content"]:\n'
        '  if part["type"]=="input_image":part["bridge_image_sha256"]=hashlib.sha256(part.pop("image_url").encode()).hexdigest()\n'
        'print(json.dumps(dict(job=job,payload_digest=digest)))')
    envelope=json.loads(slim);job=envelope['job']
    parts=[part for m in job['payload']['input'] for part in m['content'] if part['type']=='input_image']
    required={p['bridge_image_sha256'] for p in parts};pinned={k:memory.get(k) for k in required}
    missing={k for k,v in pinned.items() if v is None};image_reply=''
    if missing:
        image_reply=ssh(host,prelude+'wanted=set('+repr(sorted(missing))+'); images={}; '
            '\nfor message in job["payload"]["input"]:\n for part in message["content"]:\n'
            '  if part["type"]=="input_image":\n'
            '   value=part["image_url"]; key=hashlib.sha256(value.encode()).hexdigest()\n'
            '   if key in wanted:images[key]=value\n'
            'assert set(images)==wanted; print(json.dumps(images))')
        images=json.loads(image_reply)
        assert set(images)==missing,'Missing original request image'
        for key,value in images.items():memory.put(key,value);pinned[key]=value
    for part in parts:part['image_url']=pinned[part.pop('bridge_image_sha256')]
    digest=hashlib.sha256(json.dumps(job['payload'],sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
    assert digest==envelope['payload_digest'],'Reconstructed request differs from native payload'
    return job,dict(image_count=len(parts),unique_images=len(required),cached_images=len(required)-len(missing),
        ssh_download_bytes=len(slim.encode())+len(image_reply.encode()),exact_payload_verified=True)


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
    # Model inference does not hold an SSH slot. Cap file/control sessions
    # independently to avoid flooding the reverse tunnel with reconnects.
    with SSH_SLOTS:return _ssh(host,code,input)


def _ssh(host,code,input=None):
    command='python3 -c '+shlex.quote(code)
    for attempt in range(2):
        opts=(['-o','ControlMaster=auto','-o','ControlPersist=60','-o','ControlPath='+CONTROL]
            if CONTROL and attempt==0 else ['-o','ControlMaster=no','-o','ControlPath=none'])
        try:
            proc=subprocess.Popen(['ssh','-o','ConnectTimeout=10','-o','ServerAliveInterval=10',
                '-o','ServerAliveCountMax=2',*opts,'--',host,command],text=True,
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
            try:out,err=proc.communicate(input=input,timeout=35)
            except BaseException:
                # Killing only the outer ssh can leave a ProxyJump child alive.
                # This process group was created solely for this bridge operation.
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.communicate()
                raise
            if proc.returncode:raise RuntimeError(err[-600:])
            return out
        except (subprocess.TimeoutExpired,OSError,RuntimeError):
            if attempt:raise
            # All bridge commands are read/verified-file-write operations. Retry
            # over a fresh connection rather than reusing a possibly stuck master.
            time.sleep(1)


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
    lock=threading.Lock();calls=0;seen=set();active={};started=time.monotonic();last_served={};memory=ImageMemory()
    def process(remote):
        nonlocal calls
        began=time.monotonic();timing=dict(started=time.time())
        folder=a.output/hashlib.sha256(remote.encode()).hexdigest()[:20];folder.mkdir(exist_ok=True)
        if (folder/'reply.json').exists():reply=json.loads((folder/'reply.json').read_text());called=False
        else:
            job,transfer=fetch_job(a.host,remote,memory)
            timing.update(transfer,download_seconds=time.monotonic()-began)
            assert job['endpoint']==ENDPOINT and job['payload']['model']=='gpt-6-luna'
            raw=json.dumps(job['payload']).encode()
            if not a.compact:(folder/'request.json').write_bytes(raw)
            (folder/'dispatch.json').write_text(json.dumps(dict(endpoint=ENDPOINT,key_origin='du',
                remote_job=remote,compact=a.compact,request_sha256=hashlib.sha256(raw).hexdigest())))
            request=urllib.request.Request(ENDPOINT,data=raw,
                headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
            client=urllib.request.build_opener(urllib.request.ProxyHandler({'https':'http://127.0.0.1:7897'}))
            called=True
            api_started=time.monotonic()
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
            timing['api_seconds']=time.monotonic()-api_started
        target=str(Path(remote).parent/'reply.json')
        body=json.dumps(reply);digest=hashlib.sha256(body.encode()).hexdigest()
        delivery_started=time.monotonic();ack=ssh(a.host,delivery_command(target,digest),input=body)
        if ack.strip()!=digest:raise RuntimeError('Missing verified reply-delivery acknowledgement')
        timing.update(delivery_seconds=time.monotonic()-delivery_started,total_seconds=time.monotonic()-began,model_called=called)
        (folder/'timing.json').write_text(json.dumps(timing,indent=2))
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
