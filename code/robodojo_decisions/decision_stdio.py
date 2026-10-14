"""Framed API transport over the existing foreground SSH stream, no new port."""
import io
import json
import os
import select
import sys
import urllib.error
import uuid
from model_input_language import require_english_model_input

REQUEST_PREFIX='ROBODOJO_API_REQUEST '
RESPONSE_PREFIX='ROBODOJO_API_RESPONSE '


def request(payload, timeout, service='luna'):
    require_english_model_input(payload, service + " SSH request")
    identifier=uuid.uuid4().hex
    frame={'id':identifier,'service':service,'timeout':timeout,'payload':payload}
    parent=int(os.environ.get('ROBODOJO_STDIO_RELAY_PARENT_PID',os.getpid()))
    # Planner subprocess stdout is deliberately a log file. Its parent's SSH
    # stdout still reaches the relay; stdin is inherited while parent waits.
    with open(f'/proc/{parent}/fd/1','w',buffering=1) as output:
        output.write(REQUEST_PREFIX+json.dumps(frame,ensure_ascii=False)+'\n')
    if not select.select([sys.stdin],[],[],timeout+15)[0]:
        raise urllib.error.URLError('SSH stdio relay response timeout')
    line=sys.stdin.readline()
    if not line.startswith(RESPONSE_PREFIX):
        raise urllib.error.URLError('SSH stdio relay closed or invalid response frame')
    answer=json.loads(line[len(RESPONSE_PREFIX):])
    if answer.get('id')!=identifier:
        raise ValueError('SSH stdio response request id mismatch')
    if 'http_error' in answer:
        raise urllib.error.HTTPError('authorized-model-endpoint',answer['http_error'],
                                     'SSH relay upstream HTTP error',None,
                                     io.BytesIO(answer.get('body','').encode()))
    if 'transport_error' in answer:
        raise urllib.error.URLError('SSH relay '+answer['transport_error'])
    return answer['response']
