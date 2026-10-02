"""Bounded request handling for the documented single-process API topology."""
import time
import asyncio
from starlette.responses import JSONResponse


class RequestGuard:
    def __init__(self,app,body_limit=65536,write_limit=120,read_limit=300):
        self.app=app;self.body_limit=body_limit;self.write_limit=write_limit;self.read_limit=read_limit
        self.buckets={}

    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or not scope['path'].startswith('/api/'):
            return await self.app(scope,receive,send)
        headers={k.lower():v for k,v in scope.get('headers',[])}
        write=scope['method'] not in ['GET','HEAD','OPTIONS']
        now=time.monotonic()
        self.buckets={key:value for key,value in self.buckets.items() if value[0]>now}
        host=(scope.get('client') or ('unknown',0))[0]
        bucket='login' if scope['path']=='/api/session' else 'write' if write else 'read'
        key=(host,bucket)
        expiry,count=self.buckets.get(key,(now+60,0))
        limit=20 if bucket=='login' else self.write_limit if write else self.read_limit
        if count>=limit or (key not in self.buckets and len(self.buckets)>=4096):
            return await JSONResponse({'detail':'Request limit reached; retry later'},429,headers={'Retry-After':'60'})(scope,receive,send)
        self.buckets[key]=(expiry,count+1)
        if not write:return await self.app(scope,receive,send)
        if headers.get(b'sec-fetch-site')==b'cross-site':
            return await JSONResponse({'detail':'Cross-site write refused'},403)(scope,receive,send)
        try:length=int(headers.get(b'content-length',b'0'))
        except ValueError:length=-1
        if length<0 or length>self.body_limit:
            return await JSONResponse({'detail':'Request body too large or invalid'},413)(scope,receive,send)
        body=bytearray();deadline=time.monotonic()+10
        while True:
            try:message=await asyncio.wait_for(receive(),timeout=max(.001,deadline-time.monotonic()))
            except TimeoutError:
                return await JSONResponse({'detail':'Request body deadline exceeded'},408)(scope,receive,send)
            if message['type']=='http.disconnect':return
            body.extend(message.get('body',b''))
            if len(body)>self.body_limit:
                return await JSONResponse({'detail':'Request body too large'},413)(scope,receive,send)
            if not message.get('more_body',False):break
        if body and headers.get(b'content-type',b'').split(b';')[0].strip()!=b'application/json':
            return await JSONResponse({'detail':'JSON content type required'},415)(scope,receive,send)
        sent=False
        async def replay():
            nonlocal sent
            if not sent:
                sent=True
                return {'type':'http.request','body':bytes(body),'more_body':False}
            return await receive()
        await self.app(scope,replay,send)
