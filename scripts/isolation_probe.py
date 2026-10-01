"""Fixed harmless probes verify worker controls independently of model output."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rescue.config import get_case,ROOT
from rescue.execution import docker_execute

case=get_case()
probe=r'''
const fs=require('fs'),net=require('net');let failures=[];
function check(name,fn){try{fn()}catch(e){failures.push({fullTitle:name,err:{message:String(e)}})}}
check('non-root',()=>{if(process.getuid()===0)throw Error('root')});
check('source read-only',()=>{try{fs.writeFileSync('/app/forbidden-write','x');throw Error('write succeeded')}catch(e){if(!['EROFS','EACCES','EPERM'].includes(e.code))throw e}});
check('host credentials absent',()=>{if(fs.existsSync('/root/.ssh')||fs.existsSync('/var/run/docker.sock'))throw Error('host access')});
check('no capabilities',()=>{if(!/CapEff:\s+0+\n/.test(fs.readFileSync('/proc/self/status','utf8')))throw Error('capabilities present')});
const s=net.connect({host:'1.1.1.1',port:443});s.setTimeout(2000);
function done(blocked){s.destroy();if(!blocked)failures.push({fullTitle:'network denied',err:{message:'egress connected'}});console.log(JSON.stringify({stats:{tests:5,passes:5-failures.length},failures}));process.exit(failures.length?1:0)}
s.once('connect',()=>done(false));s.once('error',()=>done(true));s.once('timeout',()=>done(true));
'''
result=docker_execute(case.templates/'baseline',case,args=['-e',probe])
(ROOT/'reports/isolation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
raise SystemExit(0 if result['ok'] else 1)
