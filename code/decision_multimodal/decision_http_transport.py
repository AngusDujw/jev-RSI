"""Optional pooled HTTP/2 transport for the authorized Decisions endpoint only."""
import io
import json
import threading
import urllib.error

ENDPOINT='https://api.openai.com/v1/decisions'


class PooledDecisionsHTTP:
    """Keep urllib's response/error contract; preserve the exact request bytes."""
    def __init__(self,client=None,http2=True,client_factory=None):
        import httpx
        self.httpx=httpx
        self.local=threading.local()
        self.injected=client
        self.factory=client_factory
        self.http2=http2
        self.clients=[client] if client is not None else []
        self.lock=threading.Lock()

    @property
    def strategy(self):
        return 'per_worker_http2_keepalive' if self.http2 else 'per_worker_http1_keepalive'

    def worker_client(self):
        if self.injected is not None:return self.injected
        if not hasattr(self.local,'client'):
            client=self.factory() if self.factory else self.httpx.Client(
                http2=self.http2,trust_env=False,proxy='http://127.0.0.1:7897',
                follow_redirects=False,limits=self.httpx.Limits(max_connections=1,
                    max_keepalive_connections=1,keepalive_expiry=60.))
            self.local.client=client
            with self.lock:self.clients.append(client)
        return self.local.client

    @property
    def http_version(self):
        return getattr(self.local,'http_version',None)

    def open(self,request,timeout=100):
        if request.full_url!=ENDPOINT or request.get_method()!='POST':
            raise ValueError('Pooled transport is restricted to POST /v1/decisions')
        payload=json.loads(request.data)
        if payload.get('model')!='gpt-6-luna':
            raise ValueError('Pooled transport cannot change the actor model')
        self.local.http_version=None
        try:
            response=self.worker_client().post(ENDPOINT,content=request.data,
                headers=dict(request.header_items()),
                timeout=self.httpx.Timeout(timeout,connect=min(timeout,20.)))
        except self.httpx.RequestError as error:
            # Only the failing worker's connection is retired. Other in-flight
            # workers must finish and preserve their own provider answers.
            if self.injected is None and hasattr(self.local,'client'):
                client=self.local.client
                try:client.close()
                except Exception:pass  # Preserve the original transport error.
                finally:
                    del self.local.client
                    with self.lock:self.clients.remove(client)
            # infer_unanswered handles only unanswered transport failures.
            raise OSError(type(error).__name__+': '+str(error)) from error
        self.local.http_version=response.http_version
        body=io.BytesIO(response.content)
        if not 200<=response.status_code<300:
            raise urllib.error.HTTPError(ENDPOINT,response.status_code,
                response.reason_phrase,dict(response.headers),body)
        return body

    def close(self):
        for client in self.clients:client.close()
        self.clients=[]
