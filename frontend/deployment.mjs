// Public routing configuration only. Never embed service keys in the frontend.
export function backendOrigin(value='') {
  if (!value) return '';
  const url=new URL(value);
  if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash||url.pathname!=='/'||['localhost','127.0.0.1','[::1]'].includes(url.hostname))throw new Error('RESCUE_BACKEND_URL must be a hosted HTTPS origin');
  return url.origin;
}
export function backendRewrites(origin) {
  if(!origin)return [];
  return [
    {source:'/workspace',destination:origin+'/'},
    ...['api','auth'].map(path=>({source:`/${path}/:path*`,destination:`${origin}/${path}/:path*`})),
    ...['healthz','readyz','docs','openapi.json'].map(path=>({source:`/${path}`,destination:`${origin}/${path}`}))
  ];
}
