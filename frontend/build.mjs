import {backendOrigin,backendRewrites} from './deployment.mjs';
import {build} from 'esbuild';
import {mkdir,copyFile,writeFile,readFile} from 'node:fs/promises';
await build({entryPoints:['frontend/motion.js'],bundle:true,minify:true,outfile:'rescue/static/motion.js',legalComments:'eof'});
await build({entryPoints:['frontend/showcase.js'],bundle:true,minify:true,outfile:'rescue/static/showcase.js',legalComments:'eof'});
await mkdir('dist/static',{recursive:true});
for(const name of ['style.css','app.js','motion.js','showcase.css','showcase.js']) await copyFile(`rescue/static/${name}`,`dist/static/${name}`);
const backend=backendOrigin(process.env.RESCUE_BACKEND_URL);
let html=await readFile('rescue/static/showcase.html','utf8');
// A static deployment has no worker/API until the operator configures a backend.
if(backend || process.env.RESCUE_FRONTEND_MODE==='azure'){
  html=html.replace('Watch a real repair ↗</a>','Open repair workspace ↗</a>').replace('class="button primary" href="#demo"','class="button primary" href="/workspace"');
  html=html.replace('Explore the agent ↗</a>','Open workspace ↗</a>').replace('class="nav-cta" href="#demo"','class="nav-cta" href="/workspace"');
  html=html.replace('No live backend is connected here.','Open the workspace to sign in and check backend readiness.');
  html=html.replace('requires the separately hosted API and isolated worker.','uses a separately hosted API and isolated worker.');
} else html=html.replace('<body>','<body data-hosted="standalone">');
if(process.env.RESCUE_FRONTEND_MODE==='azure')html=html.replace('This Vercel site','This Azure site');
await writeFile('dist/index.html',html);
let brief=await readFile('rescue/static/technical.html','utf8');
if(backend || process.env.RESCUE_FRONTEND_MODE==='azure'){
  brief=brief.replace('The authenticated API, persistent job state, and isolated repair worker require separate hosting. Live repository connection, sign-in, and repair execution are not offered by this static deployment.','The workspace connects to a separately hosted authenticated API and isolated repair worker. Readiness depends on the deployed worker, model, and prepared repository snapshots. Automatic preparation of new repositories is currently limited to the local Docker workflow.');
}
if(process.env.RESCUE_FRONTEND_MODE==='azure')brief=brief.replace('This Vercel deployment','This Azure deployment');
await writeFile('dist/technical.html',brief);
await writeFile('dist/vercel.json',JSON.stringify({rewrites:backendRewrites(backend),headers:[{source:'/(.*)',headers:[{key:'Content-Security-Policy',value:"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"},{key:'X-Content-Type-Options',value:'nosniff'},{key:'Referrer-Policy',value:'no-referrer'},{key:'Permissions-Policy',value:'camera=(), microphone=(), geolocation=()'}]}]},null,2));
