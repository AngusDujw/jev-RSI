"""Opt-in HTTPS transport through a campaign-owned Unix HTTP proxy socket."""
import http.client
from pathlib import Path
import shlex
import socket
import ssl
import subprocess
import time
from urllib.parse import urlsplit


def post(config, wire, socket_path, timeout):
    root = Path(__file__).resolve().parents[1] / 'runs/company2-20261018/private-api-proxy-20261018'
    resolved = Path(socket_path).resolve(strict=True)
    if resolved.parent != root.resolve() or resolved.name != 'api.sock':
        raise ValueError('Proxy socket is outside the owned campaign directory')
    url, headers = None, {}
    for line in config.splitlines():
        key, value = line.split('=', 1)
        value = shlex.split(value.strip())[0]
        if key.strip() == 'url':
            url = urlsplit(value)
        elif key.strip() == 'header':
            name, content = value.split(':', 1)
            headers[name] = content.strip()
        else:
            raise ValueError('Unsupported transport configuration')
    if url is None or url.scheme != 'https' or url.hostname not in {
        'api.openai.com', 'ai2robcowork.site', 'api.typesafe.ai'
    } or url.port not in (None, 443):
        raise ValueError('Unexpected model endpoint')
    raw, connection, chunks = None, None, []
    http_status = None
    deadline = time.monotonic() + timeout
    try:
        raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        raw.settimeout(min(timeout, 25))
        raw.connect(socket_path)
        raw.sendall(f'CONNECT {url.hostname}:443 HTTP/1.1\r\nHost: {url.hostname}:443\r\n\r\n'.encode())
        response = bytearray()
        while not response.endswith(b'\r\n\r\n'):
            byte = raw.recv(1)
            if not byte or len(response) > 16384:
                raise ConnectionError('Invalid proxy response')
            response.extend(byte)
        if response.split(b'\r\n', 1)[0].split()[1] != b'200':
            raise ConnectionError('Proxy CONNECT rejected')
        tls = ssl.create_default_context().wrap_socket(raw, server_hostname=url.hostname)
        raw = tls
        tls.settimeout(timeout)
        connection = http.client.HTTPSConnection(url.hostname, timeout=timeout)
        connection.sock = tls
        target = url.path + ('?' + url.query if url.query else '')
        connection.request('POST', target, body=Path(wire).read_bytes(), headers=headers)
        result = connection.getresponse()
        http_status = result.status
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            tls.settimeout(remaining)
            block = result.read1(65536)
            if not block:
                break
            chunks.append(block)
        code = 22 if result.status >= 400 else 0
        error = f'HTTP {result.status}' if code else ''
    except (OSError, http.client.HTTPException) as exc:
        if isinstance(exc, http.client.IncompleteRead) and exc.partial:
            chunks.append(exc.partial)
        code = 22 if http_status is not None and http_status >= 400 else 28 if isinstance(exc, TimeoutError) else 35 if isinstance(exc, ssl.SSLError) else 7
        # Do not log headers, credentials or exception payloads.
        error = (f'HTTP {http_status}; body transport failed: ' if code == 22 else 'Owned proxy transport failed: ') + type(exc).__name__
    finally:
        if connection is not None:
            connection.close()
        if raw is not None:
            raw.close()
    return subprocess.CompletedProcess(['owned-unix-proxy'], code, b''.join(chunks).decode('utf-8', errors='replace'), error)
