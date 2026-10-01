import os
import subprocess
import httpx
from .config import cases
from .providers import settings


def check():
    result={'cases_ready':sum(c.public()['ready'] for c in cases().values()),'model_ready':False,'executor_ready':False}
    try:
        with httpx.Client(timeout=3,trust_env=False) as c:
            provider,model_url,model,key=settings();model_url=model_url.rstrip('/')
            if provider=='ollama':
                r=c.get(model_url+'/api/tags');r.raise_for_status()
                result['model_ready']=model in {m['name'] for m in r.json().get('models',[])}
            elif provider=='gemini':
                r=c.get(model_url+'/models/'+model,headers={'x-goog-api-key':key or ''});r.raise_for_status()
                result['model_ready']='generateContent' in r.json().get('supportedGenerationMethods',[])
            elif provider=='anthropic':
                r=c.get(model_url+'/models/'+model,headers={'x-api-key':key or '', 'anthropic-version':'2023-06-01'});r.raise_for_status()
                result['model_ready']=r.json().get('id')==model
            else:
                # Configuration alone is not a live provider check.
                r=c.get(model_url+'/models',headers={'Authorization':'Bearer '+os.getenv('RESCUE_MODEL_API_KEY','')});r.raise_for_status()
                result['model_ready']=os.getenv('RESCUE_MODEL') in {m['id'] for m in r.json().get('data',[])}
            if os.getenv('RESCUE_RUNNER')=='remote':
                r=c.get(os.environ['RESCUE_EXECUTOR_URL'].rstrip('/')+'/healthz');result['executor_ready']=r.status_code==200
            elif os.getenv('RESCUE_RUNNER')=='docker':
                from .execution import docker_prefix
                result['executor_ready']=subprocess.run([*docker_prefix(),'info','--format','{{.ServerVersion}}'],capture_output=True,timeout=3).returncode==0
            else:
                import platform
                result['executor_ready']=platform.system()=='Darwin'
    except (httpx.HTTPError,KeyError,ValueError,OSError,subprocess.TimeoutExpired):
        pass
    result['ready']=result['cases_ready']>0 and result['model_ready'] and result['executor_ready']
    return result
