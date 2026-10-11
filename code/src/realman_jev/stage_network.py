"""Process-scoped name resolution with unchanged HTTP host and TLS verification."""
import argparse
from contextlib import contextmanager
import ipaddress
import json
from pathlib import Path
import socket
from urllib.parse import urlsplit


@contextmanager
def api_dns_overrides(settings):
    mapping={}
    for setting in settings:
        address=setting.get('resolved_host_ip')
        if not address:continue
        if setting.get('proxy'):
            raise ValueError('Use either a proxy or direct host resolution')
        host=urlsplit(setting['base_url']).hostname
        if not host:raise ValueError('API base URL requires a hostname')
        ipaddress.ip_address(address)
        if host in mapping and mapping[host]!=address:
            raise ValueError('Conflicting API host resolutions')
        mapping[host]=address
    original=socket.getaddrinfo
    def resolved(host,port,*args,**kwargs):
        name=host.decode('ascii') if isinstance(host,bytes) else host
        return original(mapping.get(name,host),port,*args,**kwargs)
    if mapping:socket.getaddrinfo=resolved
    try:
        yield
    finally:
        if mapping:socket.getaddrinfo=original


def preflight(settings):
    import httpx
    results={}
    with api_dns_overrides(settings.values()):
        for role in ('gpt','decision'):
            setting=settings[role]
            with httpx.Client(proxy=setting.get('proxy'),trust_env=False,timeout=15) as client:
                response=client.get(setting['base_url'])
            if response.status_code in (407,500,502,503,504,520,522,524):
                raise RuntimeError('API connectivity preflight failed for '+role)
            results[role]=dict(http_status=response.status_code,
                interpretation='Unauthenticated GET verifies connectivity only')
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    print(json.dumps(preflight(json.loads(Path(parser.parse_args().config).read_text()))))
