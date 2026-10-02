import json,time
import httpx,jwt,pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from rescue import auth


def test_signing_keys_use_verified_https_and_cache(monkeypatch):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()));jwk.update(kid='google-key',use='sig',alg='RS256')
    calls=[]
    class Client:
        def __init__(self,**kwargs):
            assert kwargs['trust_env'] is False and 'verify' not in kwargs
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url):
            calls.append(url);return httpx.Response(200,json={'keys':[jwk]},request=httpx.Request('GET',url))
    monkeypatch.setattr(auth.httpx,'Client',Client)
    auth.jwks_client.cache_clear()
    client=auth.jwks_client('https://www.googleapis.com/oauth2/v3/certs')
    token=jwt.encode({'sub':'123','exp':int(time.time())+60},key,algorithm='RS256',headers={'kid':'google-key'})
    for _ in range(2):
        public=client.get_signing_key_from_jwt(token).key
        assert jwt.decode(token,public,algorithms=['RS256'])['sub']=='123'
    assert len(calls)==1
    auth.jwks_client.cache_clear()


def test_tls_failure_is_not_bypassed_or_exposed(monkeypatch):
    class Client:
        def __init__(self,**kwargs):assert 'verify' not in kwargs
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url):raise httpx.ConnectError('private transport information')
    monkeypatch.setattr(auth.httpx,'Client',Client)
    with pytest.raises(jwt.PyJWKClientConnectionError) as error:
        auth.VerifiedJWKClient('https://www.googleapis.com/oauth2/v3/certs').fetch_data()
    assert 'private transport information' not in str(error.value)
