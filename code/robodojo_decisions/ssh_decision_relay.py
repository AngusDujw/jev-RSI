"""Foreground local relay: remote simulator stays on v4090; no local asset files.

Only the two user-authorized model endpoints/keys are accepted. Keys enter
memory through SSH, never argv, stdout, API frames or local files.
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from decision_stdio import REQUEST_PREFIX,RESPONSE_PREFIX
from model_input_language import require_english_model_input


def call(payload,key,timeout,url):
    require_english_model_input(payload, "model relay request")
    read_fd,write_fd=os.pipe()
    try:os.write(write_fd,f'header = "Authorization: Bearer {key}"\n'.encode())
    finally:os.close(write_fd)
    try:
        env={k:v for k,v in os.environ.items() if k.lower() not in ('http_proxy','https_proxy','all_proxy')}
        command=['curl','--silent','--show-error','--http1.1','--socks5-hostname','127.0.0.1:7897',
                 '--connect-timeout','15','--max-time',str(timeout),'--header','Content-Type: application/json',
                 '--config',f'/proc/self/fd/{read_fd}','--data-binary','@-','--write-out','\n%{http_code}',url]
        p=subprocess.run(command,input=json.dumps(payload).encode(),capture_output=True,
                         pass_fds=(read_fd,),env=env,timeout=timeout+5)
        body,_,status=p.stdout.rpartition(b'\n')
        code=int(status) if status.isdigit() else 0
        if code>=400:return {'http_error':code,'body':body.decode(errors='replace').replace(key,'[redacted]')}
        if p.returncode or not 200<=code<300:
            return {'transport_error':f'curl code={p.returncode},status={code}'}
        return {'response':json.loads(body)}
    finally:os.close(read_fd)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',choices=['v4090'],required=True)
    parser.add_argument('--decision-key-file',required=True)
    parser.add_argument('--planner-auth-file',required=True)
    parser.add_argument('--remote-command',required=True)
    args=parser.parse_args()
    prefix='/home/v4090-1/DataStorage/gpt6-dec/secrets/'
    if not all(p.startswith(prefix) for p in [args.decision_key_file,args.planner_auth_file]):
        raise ValueError('Only this task authorized remote secret paths are accepted')
    keys={}
    def key(service):
        if service not in keys:
            path=args.decision_key_file if service=='luna' else args.planner_auth_file
            value=subprocess.run(['ssh','--',args.host,'cat '+shlex.quote(path)],
                                 capture_output=True,timeout=30,check=True).stdout.decode().strip()
            keys[service]=value if service=='luna' else json.loads(value)['OPENAI_API_KEY']
        return keys[service]
    child=subprocess.Popen(['ssh','--',args.host,args.remote_command],stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    try:
        for line in child.stdout:
            if line.startswith(REQUEST_PREFIX):
                frame=json.loads(line[len(REQUEST_PREFIX):]);service=frame['service'];payload=frame['payload']
                if service not in ('luna','planner'):
                    raise ValueError('Unknown model service')
                model='gpt-6-luna' if service=='luna' else 'gpt-6.1-sol'
                if payload.get('model')!=model or (service=='planner' and payload.get('reasoning',{}).get('effort')!='high'):
                    raise ValueError('Relay cannot substitute authorized model/reasoning')
                url='https://api.openai.com/v1/decisions' if service=='luna' else 'https://ai2robcowork.site/openai/v1/responses'
                timeout=int(frame['timeout'])
                limit=1800 if service=='planner' else 600
                if not 1<=timeout<=limit:raise ValueError('Relay timeout outside bounded range')
                start=time.monotonic()
                try:answer=call(payload,key(service),timeout,url)
                except Exception as error:answer={'transport_error':type(error).__name__}
                answer['id']=frame['id']
                child.stdin.write(RESPONSE_PREFIX+json.dumps(answer)+'\n');child.stdin.flush()
                print(json.dumps({'relay_service':service,'wall_seconds':round(time.monotonic()-start,3),
                    'status':'response' if 'response' in answer else 'error','origin':'du' if service=='luna' else 'user-authorized-ai2robcowork'}),flush=True)
            else:
                try:row=json.loads(line)
                except (json.JSONDecodeError,ValueError):
                    if line.startswith(('Traceback','RuntimeError','ValueError','urllib.error')):print(line[:500],end='',flush=True)
                    continue
                print(json.dumps({k:v for k,v in row.items() if k in (
                    'event','step_id','status','task','native_result','relay_diagnostic','plan','stage_count','image_count')}),flush=True)
        return child.wait()
    finally:
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=15)
            except subprocess.TimeoutExpired:child.kill();child.wait()


if __name__=='__main__':raise SystemExit(main())
