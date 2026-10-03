# Azure deployment

Status: two dedicated VMs provisioned in Central India; application images built. Model credentials and service-token upload await explicit authorization, so public app startup and end-to-end repair verification are pending.

Use two dedicated Linux VMs in one Azure virtual network:

- Web/API VM: Compose `api` plus Caddy serving the built frontend; persistent runtime volume.
- Worker VM: executor controller and Docker test containers; no model keys, repository OAuth keys, managed identity, or unrelated workloads.

Use a private worker IP. Its network security group should allow port 8094 only from the API host. Restrict SSH to the operator's current address. The deployed network uses 10.42.1.4 for the web/API host and 10.42.2.4 for the worker. Public access belongs only on the web host's ports 80/443. Set RESCUE_EXECUTOR_BIND=10.42.2.4 to publish the executor only on its private address (the default is loopback-only). Set `RESCUE_PRIVATE_EXECUTOR=1` for this isolated private transport. Block metadata access from execution workloads. Do not share the Docker socket with the API.

## Before creating resources

1. Sign in with `az login` and select the intended subscription.
2. Confirm available credit, region, VM quota, and estimated costs for two VMs, OS disks, public IP, and outbound transfer. Credits and budgets are not hard spending caps.
3. Review the specific resource plan before provisioning. Do not change existing AWS or Railway resources.

## Prepare frontend and API

```sh
RESCUE_FRONTEND_MODE=azure npm run build
# Populate private .env.production using DEPLOYMENT.md. Never commit it.
docker compose --env-file .env.production -f compose.yaml -f compose.azure.yaml config --quiet
docker compose --env-file .env.production -f compose.yaml -f compose.azure.yaml up -d --build
```

Set RESCUE_DOMAIN to the web VM's DNS hostname. Set RESCUE_ALLOWED_HOSTS to that hostname plus localhost and 127.0.0.1. The overlay sets RESCUE_PUBLIC_URL to its HTTPS origin and sends OAuth logins back to /workspace. The legacy setting RESCUE_VERCEL_WORKSPACE enables this path on either hosting provider.

The web VM serves the showcase at `/`, the working UI at `/workspace`, and proxies `/api/*` and `/auth/*` to the API. No cross-origin cookies or browser-held backend service key are needed. Both OAuth provider registrations must include their new `https://<hostname>/auth/<provider>/callback` URLs.

## Worker and data

Follow DEPLOYMENT.md for the separate executor. Prepare immutable snapshots and synchronize identical snapshots and case registry to both hosts. Pull registered digest-pinned test images before invoking repairs. Do not upload local credentials, runtime databases, or customer source archives indiscriminately.

Automatic preparation of new GitHub repositories currently supports only the local Docker workflow. Cloud deployment does not remove this restriction. Initially only explicitly prepared and synchronized cases can run; remote preparation needs additional implementation and validation.

## Acceptance checks

- HTTPS landing page, `/workspace`, and provider configuration work.
- `/healthz` reports production with a remote runner; `/readyz` reports all dependencies ready.
- Unauthenticated API access fails, and operator/reviewer roles remain distinct.
- A prepared real fixture reproduces the break and reaches verified evidence awaiting approval.
- API restart preserves run history; executor is unreachable from public ingress.
- No automatic merge, no credentials passed into test containers, no public setup endpoint.

## Provisioned deployment (2026-10-03)

Resource group: `dependency-rescue`; location: `centralindia`; VM size: `Standard_B2ls_v2` (two hosts). Web hostname: `dependency-rescue-7943-web.centralindia.cloudapp.azure.com`.

Azure reported the subscription's free-trial spending limit as enabled. Retail compute price retrieved for this region/size: $0.0448 per VM-hour, about $65.41 for two VMs across 730 hours. Disks, two public IPs, outbound transfer, taxes, and model-provider usage are additional. Credit balance/expiry must be checked in Azure billing.

Only the public, pinned `hexo-uglify-terser` development fixture has been prepared on the worker for initial validation: baseline 6/6; upgraded 3/6. No new model repair has been executed on Azure yet.

Deployment SSH keys and private environment files are in ignored `runtime/azure/` with restrictive permissions. They are excluded from application archives and Git. The API host needs the existing Gemini key; the worker receives only its executor token. OAuth remains disabled until hosted callback URLs are registered.
