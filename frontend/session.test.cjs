const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('rescue/static/app.js','utf8');
const fn=source.slice(source.indexOf('async function api('),source.indexOf('function metric('));
function setup(responses){
  const calls=[],login={hidden:true};
  const context=vm.createContext({AbortController,setTimeout,clearTimeout,fetch:async(path,options)=>{calls.push({path,options});if(!responses.length)throw Error('Unexpected retry');return responses.shift();},$:()=>login,notice:()=>{}});
  vm.runInContext(fn,context);return {api:context.api,calls,login};
}
function response(status,body={},renew=false){return {status,ok:status<400,json:async()=>body,headers:new Map(renew?[['X-Rescue-Local-Session','renewed']]:[])};}
test('expired local session retries rejected POST once with same idempotency body',async()=>{
 const s=setup([response(401),response(200,{},true),response(202,{run_id:'new-run'})]);
 const options={method:'POST',body:'{"idempotency_key":"same-key"}'};
 assert.equal((await s.api('/api/runs',options)).run_id,'new-run');
 assert.deepEqual(s.calls.map(c=>c.path),['/api/runs','/','/api/runs']);
 assert.equal(s.calls[0].options.body,s.calls[2].options.body);
});
test('production does not silently retry a write without a local bootstrap',async()=>{
 const s=setup([response(401,{detail:'API token required'}),response(200)]);
 await assert.rejects(s.api('/api/runs',{method:'POST'}),/API token required/);assert.equal(s.calls.length,2);assert.equal(s.login.hidden,false);
});
test('a failed renewal cannot loop and successful writes are never replayed',async()=>{
 const s=setup([response(401),response(200,{},true),response(401)]);
 await assert.rejects(s.api('/api/runs'));assert.equal(s.calls.length,3);
 const ok=setup([response(202,{run_id:'one'})]);await ok.api('/api/runs',{method:'POST'});assert.equal(ok.calls.length,1);
});
