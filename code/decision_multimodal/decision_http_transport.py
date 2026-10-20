"""Optional pooled HTTP/2 transport for the authorized Decisions endpoint only."""
import io
import json
import threading
import urllib.error

ENDPOINT='https://api.openai.com/v1/decisions'


class PooledDecisionsHTTP:
    """Keep urllib's response/error contract; preserve the exact request bytes."""
    def __init__(self,client=None):
        import httpx
        self.httpx=httpx
        self.local=threading.local()
        self.client=client or httpx.Client(http2=True,trust_env=False,
            proxy='http://127.0.0.1:7897',follow_redirects=False,
            limits=httpx.Limits(max_connections=24,max_keepalive_connections=12,
                keepalive_expiry=60.))

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
            response=self.client.post(ENDPOINT,content=request.data,
                headers=dict(request.header_items()),
                timeout=self.httpx.Timeout(timeout,connect=min(timeout,20.)))
        except self.httpx.RequestError as error:
            # infer_unanswered handles only unanswered transport failures.
            raise OSError(type(error).__name__+': '+str(error)) from error
        self.local.http_version=response.http_version
        body=io.BytesIO(response.content)
        if not 200<=response.status_code<300:
            raise urllib.error.HTTPError(ENDPOINT,response.status_code,
                response.reason_phrase,dict(response.headers),body)
        return body

    def close(self):
        self.client.close()
