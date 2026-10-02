'use strict';
const status=document.getElementById('setup-status');
async function load(){
 try{const r=await fetch('/api/oauth/setup');if(!r.ok)throw Error('Open the local workspace first, then return to Administrator setup.');const v=await r.json();for(const p of ['github','google']){document.getElementById(p+'-callback').textContent=v.origin+'/auth/'+p+'/callback';document.getElementById(p+'-test').hidden=!v[p];}status.textContent='Ready. Paste your settings into the forms below.';}
 catch(e){status.textContent=e.message;document.querySelectorAll('form button').forEach(b=>b.disabled=true);}
}
for(const form of document.querySelectorAll('.setup-form'))form.addEventListener('submit',async event=>{
 event.preventDefault();const button=form.querySelector('button');button.disabled=true;status.textContent='Saving privately…';
 const body={provider:form.dataset.provider,client_id:form.elements.client_id.value.trim(),client_secret:form.elements.client_secret.value.trim(),account:form.elements.account.value.trim()};
 try{const r=await fetch('/api/oauth/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await r.json();if(!r.ok)throw Error(typeof result.detail==='string'?result.detail:'Check the form fields and try again.');form.elements.client_secret.value='';status.textContent=`${body.provider==='github'?'GitHub':'Google'} saved. Make sure its callback URL matches ${result.callback_url}. You can now sign in.`;document.getElementById(body.provider+'-test').hidden=false;}
 catch(e){status.textContent=e.message;}finally{button.disabled=false;body.client_secret='';}
});
load();
