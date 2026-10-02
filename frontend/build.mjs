import {build} from 'esbuild';
import {mkdir,copyFile,writeFile,readFile} from 'node:fs/promises';
await build({entryPoints:['frontend/motion.js'],bundle:true,minify:true,outfile:'rescue/static/motion.js',legalComments:'eof'});
await build({entryPoints:['frontend/showcase.js'],bundle:true,minify:true,outfile:'rescue/static/showcase.js',legalComments:'eof'});
await mkdir('dist/static',{recursive:true});
for(const name of ['style.css','app.js','motion.js','showcase.css','showcase.js']) await copyFile(`rescue/static/${name}`,`dist/static/${name}`);
let html=await readFile('rescue/static/showcase.html','utf8');
// A static deployment has no worker/API until the operator configures a backend.
html=html.replace('<body>','<body data-hosted="standalone">');
await writeFile('dist/index.html',html);
await copyFile('rescue/static/technical.html','dist/technical.html');
await writeFile('dist/vercel.json',JSON.stringify({headers:[{source:'/(.*)',headers:[{key:'Content-Security-Policy',value:"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"},{key:'X-Content-Type-Options',value:'nosniff'},{key:'Referrer-Policy',value:'no-referrer'},{key:'Permissions-Policy',value:'camera=(), microphone=(), geolocation=()'}]}]},null,2));
