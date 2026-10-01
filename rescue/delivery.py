"""Optional GitHub App delivery, allowlisted repositories and deterministic branch names."""
import os
import hashlib
from pathlib import Path
import time
import httpx
import jwt


def installation_token():
    now=int(time.time())
    signed=jwt.encode({'iat':now-30,'exp':now+300,'iss':os.environ['RESCUE_GITHUB_APP_ID']},Path(os.environ['RESCUE_GITHUB_PRIVATE_KEY_FILE']).read_text(),algorithm='RS256')
    with httpx.Client(timeout=20,trust_env=False) as client:
        r=client.post('https://api.github.com/app/installations/'+os.environ['RESCUE_GITHUB_INSTALLATION_ID']+'/access_tokens',headers={'Authorization':'Bearer '+signed,'Accept':'application/vnd.github+json'})
        r.raise_for_status();return r.json()['token']


def publish(case,state,root,client=None):
    allowed=set(filter(None,os.getenv('RESCUE_GITHUB_ALLOWED_REPOS','').split(',')))
    if case.repository not in allowed:
        raise ValueError('Repository is not allowlisted for delivery')
    if state['status']!='completed':
        raise ValueError('Approved artifact required')
    own=client is None
    if own:
        client=httpx.Client(base_url='https://api.github.com',headers={'Authorization':'Bearer '+installation_token(),'Accept':'application/vnd.github+json'},timeout=30,trust_env=False)
    prefix='/repos/'+case.repository;branch='rescue/'+state['run_id']
    def request(method,path,**kwargs):
        response=client.request(method,prefix+path,**kwargs);response.raise_for_status();return response.json()
    try:
        metadata=request('GET','');base=metadata['default_branch']
        ref=request('GET','/git/ref/heads/'+base)
        if ref['object']['sha']!=case.base_commit:
            raise ValueError('Base branch changed; rebase and rerun verification before delivery')
        commit=request('GET','/git/commits/'+case.base_commit)
        existing=request('GET','/pulls',params={'state':'all','head':case.repository.split('/')[0]+':'+branch})
        if existing:
            head=existing[0].get('head',{}).get('sha')
            if not head:raise ValueError('Existing delivery has no verifiable head')
            previous=request('GET','/git/commits/'+head)
            if [p['sha'] for p in previous['parents']]!=[case.base_commit]:
                raise ValueError('Existing delivery branch changed')
            def tree_map(sha):
                value=request('GET','/git/trees/'+sha,params={'recursive':'1'})
                if value.get('truncated'):raise ValueError('Repository tree exceeds delivery review limit')
                return {p['path']:(p['mode'],p['type'],p['sha']) for p in value['tree'] if p['type']!='tree'}
            expected=tree_map(commit['tree']['sha'])
            for name in [*state['sources'],'package.json','package-lock.json',*case.test_migration_files]:
                data=(root/name).read_bytes();sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
                expected[name]=('100755' if (root/name).stat().st_mode&0o111 else '100644','blob',sha)
            if tree_map(previous['tree']['sha'])!=expected:
                raise ValueError('Existing delivery content differs from approved evidence')
            return {'url':existing[0]['html_url'],'number':existing[0]['number'],'reused':True}
        entries=[]
        for name in [*state['sources'],'package.json','package-lock.json',*case.test_migration_files]:
            content=(root/name).read_text()
            if name in state['sources'] and content==state['sources'][name]:
                continue
            blob=request('POST','/git/blobs',json={'content':content,'encoding':'utf-8'})
            entries.append({'path':name,'mode':'100755' if (root/name).stat().st_mode&0o111 else '100644','type':'blob','sha':blob['sha']})
        tree=request('POST','/git/trees',json={'base_tree':commit['tree']['sha'],'tree':entries})
        new_commit=request('POST','/git/commits',json={'message':f'Repair compatibility with {case.dependency} {case.target_version}','tree':tree['sha'],'parents':[case.base_commit]})
        branch_response=client.get(prefix+'/git/ref/heads/'+branch)
        if branch_response.status_code==404:
            request('POST','/git/refs',json={'ref':'refs/heads/'+branch,'sha':new_commit['sha']})
        else:
            branch_response.raise_for_status()
            # A partial retry can reuse only an identical tree rooted at the same base.
            previous=request('GET','/git/commits/'+branch_response.json()['object']['sha'])
            if previous['tree']['sha']!=tree['sha'] or [p['sha'] for p in previous['parents']]!=[case.base_commit]:
                raise ValueError('Delivery branch has changed; refusing to overwrite')
        verified=state['verification']
        body=f"Repairs source compatibility after upgrading {case.dependency} to {case.target_version}.\n\nValidation: {verified['passes']}/{verified['tests']} tests passed in isolated execution. Test and dependency integrity were checked.\n\nEvidence digest: `{state['evidence_digest']}`\nRun: `{state['run_id']}`\n\nReview required. This change has not been merged or deployed."
        pr=request('POST','/pulls',json={'title':f'Repair {case.dependency} {case.target_version} upgrade','head':branch,'base':base,'body':body,'draft':True})
        return {'url':pr['html_url'],'number':pr['number'],'reused':False}
    finally:
        if own:client.close()
