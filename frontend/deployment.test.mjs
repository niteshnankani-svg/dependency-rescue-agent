import {test} from 'node:test';
import assert from 'node:assert/strict';
import {backendOrigin,backendRewrites} from './deployment.mjs';
test('public backend requires HTTPS and rejects credentials and URL components',()=>{
 for(const value of ['http://api.example.com','https://user:secret@api.example.com','https://api.example.com/path','https://api.example.com?key=secret','https://api.example.com#fragment','https://localhost'])assert.throws(()=>backendOrigin(value));
 assert.equal(backendOrigin('https://api.example.com/'),'https://api.example.com');
 assert.equal(backendOrigin(), '');
});
test('workspace and authenticated API use same-origin rewrites only when configured',()=>{
 assert.deepEqual(backendRewrites(''),[]);
 const routes=backendRewrites('https://api.example.com');
 assert.deepEqual(routes.find(r=>r.source==='/workspace'),{source:'/workspace',destination:'https://api.example.com/'});
 assert.equal(routes.find(r=>r.source==='/auth/:path*').destination,'https://api.example.com/auth/:path*');
 assert.ok(!routes.some(r=>r.source==='/'));
});
