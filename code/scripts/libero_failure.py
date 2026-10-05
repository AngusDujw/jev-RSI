"""Post-episode failure classification; never supplies information to a policy."""
TRANSPORT_TYPES = {
    'ConnectError', 'ReadError', 'WriteError', 'CloseError', 'ProxyError',
    'ConnectTimeout', 'ReadTimeout', 'WriteTimeout', 'PoolTimeout',
    'RemoteProtocolError', 'LocalProtocolError', 'TransportError', 'NetworkError',
}
TRANSPORT_MESSAGES = (
    'name or service not known', 'temporary failure in name resolution',
    'connection refused', 'network is unreachable', 'connection reset',
    'server disconnected without sending a response', 'unexpected_eof',
    'unexpected eof', 'eof occurred in violation of protocol',
    'connecterror', 'readtimeout', 'connecttimeout', 'ssl:',
    'http 401', 'http 402', 'http 403', 'http 429', 'http 500',
    'http 502', 'http 503', 'http 504',
)


def classify(result, batch_row=None, events=()):
    row = batch_row or {}
    if row.get('runner_termination') or (row.get('returncode') is not None
        and row['returncode'] < 0):
        return 'interrupted'
    if not result.get('error'):
        return 'physical_or_policy'
    message = str(result['error']).casefold()
    if any(s in message for s in TRANSPORT_MESSAGES):
        return 'infrastructure'
    if any(e.get('kind') == 'api' and e.get('error_type') in TRANSPORT_TYPES
        for e in events):
        return 'infrastructure'
    return 'physical_or_policy'
