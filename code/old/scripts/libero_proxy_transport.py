"""Explicit API transport for unchanged, SHA-verified LIBERO policy snapshots.

Only API construction receives a proxy setting. Requests, answers, observations,
and policy source are untouched. Preflight requests do not execute the robot.
"""
import argparse
import json
import math
import runpy
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

EXISTING_ROOT = Path('/root/yekangjie/project/robodojo-jev')
API_CONFIG = EXISTING_ROOT/'controller/config/api.company.local.json'
VISION_CONFIG = dict(base_url='https://sub2api.qinjiu8.com/v1',
    model='gpt-6-astra', expected_model_prefix='gpt-6', timeout_s=30,
    key_file='/root/yekangjie/project/jev_rsi/.private/openai.key')


def validate_proxy(url):
    if url is None:
        return None
    parsed = urlsplit(url)
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
        or parsed.port not in (7901, 7902, 7903) or parsed.username
        or parsed.password or parsed.path not in ('', '/') or parsed.query
        or parsed.fragment):
        raise ValueError('Use an explicitly authorized HTTP proxy on 127.0.0.1:7901/7902/7903')
    return url


def api_class():
    sys.path.insert(0, str(EXISTING_ROOT/'controller/src'))
    from realman_jev.api import API
    return API


def install_transport(jev_proxy, vision_proxy):
    proxies = dict(jev=validate_proxy(jev_proxy),
        semantic_vision=validate_proxy(vision_proxy))
    API = api_class()
    original = getattr(API, '_libero_transport_original_init', API.__init__)
    API._libero_transport_original_init = original

    def initialize(self, cfg, log, role):
        settings = dict(cfg)
        if proxies.get(role):
            settings['proxy'] = proxies[role]
        original(self, settings, log, role)
        if proxies.get(role):
            log(dict(kind='explicit_proxy_transport', role=role,
                proxy=proxies[role], policy_payload_changed=False))

    API.__init__ = initialize


def probe(jev_proxy, vision_proxy):
    """One small authenticated Jev request; vision /models is non-generative."""
    install_transport(jev_proxy, vision_proxy)
    API = api_class()
    events = []
    jev_cfg = dict(json.loads(API_CONFIG.read_text())['jev'], timeout_s=30)
    vision_cfg = dict(VISION_CONFIG)
    clients = []
    result = dict(jev_proxy=jev_proxy, vision_proxy=vision_proxy,
        physical_episodes=0, vision_generation_requests=0, events=events)
    started = time.monotonic()
    try:
        jev = API(jev_cfg, events.append, 'jev'); clients.append(jev)
        vision = API(vision_cfg, events.append, 'semantic_vision'); clients.append(vision)
        result['effective_api_proxies'] = dict(jev=jev.cfg.get('proxy'),
            semantic_vision=vision.cfg.get('proxy'))
        response = jev.client.get('https://example.com/')
        result['external_http_status'] = response.status_code
        response.raise_for_status()
        # Authenticate the exact vision endpoint without generating an image analysis.
        models = vision.client.get(vision.cfg['base_url'].rstrip('/')+'/models',
            headers={'Authorization': 'Bearer '+vision.credential})
        result['vision_models_http_status'] = models.status_code
        models.raise_for_status()
        ids = [r.get('id') for r in models.json().get('data', [])]
        result['vision_model_available'] = vision.cfg['model'] in ids
        if not result['vision_model_available']:
            raise RuntimeError('Configured vision model missing from authenticated /models')
        payload = dict(model=jev.cfg['model'],
            state=dict(current_x_m=0.0, goal_x_m=0.01, tolerance_m=0.001,
                purpose='Network-only test; no robot action is executed.'),
            questions=dict(x=dict(type='choice',
                instructions='Choose the X direction toward the goal.',
                criteria=dict(negative='Decrease X', hold='Keep X', positive='Increase X'))))
        result['jev_request'] = payload
        result['jev_response'] = jev.post('/systemone', payload)
        # Validate this existing response without making a second model call.
        answer = result['jev_response']['answers']['x']
        probabilities = answer.get('probabilities', {})
        if (answer.get('type') != 'choice'
            or answer.get('choice') not in payload['questions']['x']['criteria']
            or set(probabilities) != set(payload['questions']['x']['criteria'])
            or any(type(v) not in (int, float) or not math.isfinite(v)
                or not 0 <= v <= 1 for v in [answer.get('confidence'), *probabilities.values()])
            or abs(sum(probabilities.values())-1) > 0.02):
            raise RuntimeError('Malformed Jev answer')
        result['ok'] = True
    except Exception as exc:
        detail = str(exc)
        for client in clients:
            detail = detail.replace(client.credential, '[redacted]')
        result.update(ok=False, error_type=type(exc).__name__, error=detail[:500])
    finally:
        for client in clients:
            client.close()
        result['seconds'] = round(time.monotonic()-started, 3)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    pre = sub.add_parser('preflight')
    pre.add_argument('--ports', type=int, nargs='+', default=[7901, 7902, 7903])
    pre.add_argument('--output', type=Path, required=True)
    run = sub.add_parser('run')
    run.add_argument('--jev-proxy', required=True)
    run.add_argument('--vision-proxy', required=True)
    run.add_argument('--policy', type=Path, required=True)
    run.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.operation == 'preflight':
        args.output.mkdir(parents=True, exist_ok=False)
        rows = []
        for port in args.ports:
            proxy = validate_proxy('http://127.0.0.1:'+str(port))
            row = probe(proxy, proxy)
            rows.append(row)
            (args.output/'network.json').write_text(json.dumps(rows, indent=2)+'\n')
            print(json.dumps({k: v for k, v in row.items()
                if k not in ('jev_request', 'jev_response', 'events')}), flush=True)
        sys.exit(0 if all(r['ok'] for r in rows) else 2)
    install_transport(args.jev_proxy, args.vision_proxy)
    policy = args.policy.resolve()
    sys.path.insert(0, str(policy.parent))
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    sys.argv = [str(policy), *arguments]
    runpy.run_path(str(policy), run_name='__main__')


if __name__ == '__main__':
    main()
