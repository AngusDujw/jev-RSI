"""Text-only paired Jev condition, sharing the fixed categorical questions."""
import math
import json
from pathlib import Path
import subprocess
import time
from models import dump,english,post_json


def decide(state,questions,folder):
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=False)
    body=dict(model='jev-latest',state=state,questions=questions)
    english(body)
    dump(folder/'request.json',dict(**body,input_modality='text_only_no_images'))
    wire=folder/'.wire.json'
    dump(wire,body)
    key=(Path(__file__).resolve().parents[2]/'.private/jev.key').read_text().strip()
    config='url = "https://api.typesafe.ai/v1/systemone"\nheader = "Authorization: Bearer '+key+'"\nheader = "Content-Type: application/json"\n'
    started=time.time()
    try:
        result=post_json(config,wire,folder,timeout=180)
        (folder/'response.json').write_text(result.stdout)
        if result.returncode:
            raise RuntimeError('Jev transport failed: '+result.stdout[:400]+result.stderr[-200:])
        raw=json.loads(result.stdout)
        if not str(raw.get('model','')).startswith('jev'):
            raise ValueError('Unexpected Jev model identity')
        answers=raw['answers']
        if set(answers)!=set(questions):
            raise ValueError('Unexpected Jev answer keys')
        choices={}
        for name,answer in answers.items():
            probabilities=answer['probabilities']
            if set(probabilities)!=set(questions[name]['criteria']) or any(not math.isfinite(p) or not 0<=p<=1 for p in probabilities.values()) or abs(sum(probabilities.values())-1)>.02:
                raise ValueError('Invalid Jev choice distribution')
            choices[name]=answer['choice']
        english(choices)
        dump(folder/'output.json',choices)
        (folder/'output.txt').write_text(json.dumps(choices))
        return choices
    finally:
        wire.unlink(missing_ok=True)
        dump(folder/'timing.json',dict(seconds=time.time()-started,input_modality='text_only_no_images'))
