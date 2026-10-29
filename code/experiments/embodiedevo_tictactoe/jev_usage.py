"""Summarize real Jev HTTP attempts, preserving partial/unknown usage."""
import argparse
import json
from pathlib import Path

def summarize(root):
    groups={}
    for folder in sorted(root.iterdir() if root.exists() else []):
        if not folder.is_dir():continue
        def read(name):
            p=folder/name
            return json.loads(p.read_text()) if p.is_file() else {}
        ledger=read('ledger.json'); state=read('input-state.json')
        request=read('request.json'); response=read('response.json')
        run=ledger.get('run_id',state.get('run_id','unlabeled'))
        g=groups.setdefault(run,dict(http_attempts=0,logical_questions=0,completed=0,
            input_tokens=0,output_tokens=0,unknown_usage=0,elapsed_seconds=0.0,choices={}))
        g['http_attempts']+=1;g['logical_questions']+=len(request.get('questions',{}))
        g['completed']+=bool(response)
        usage=response.get('usage')
        if not isinstance(usage,dict) or any(k not in usage for k in ('input_tokens','output_tokens')):
            g['unknown_usage']+=1
        else:
            g['input_tokens']+=usage['input_tokens'];g['output_tokens']+=usage['output_tokens']
        g['elapsed_seconds']+=ledger.get('elapsed_seconds',0)
        for answer in response.get('answers',{}).values():
            choice=answer.get('choice','invalid');g['choices'][choice]=g['choices'].get(choice,0)+1
    return groups

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('ledger',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args();result={'ledger':str(a.ledger),'runs':summarize(a.ledger)}
    text=json.dumps(result,indent=2)
    if a.output:a.output.write_text(text+'\n')
    print(text)
