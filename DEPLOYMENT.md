# Deployment qualification

Current release is a loopback-only macOS pilot. **Do not deploy it as a public customer-code execution service.** No tested Docker image or AWS/Azure/Railway deployment exists yet.

The cloud design needs a control plane (API, durable queue, identity, evidence store) and separate disposable execution workers. The API must never hold a Docker socket and run model-generated customer code in the same security boundary.

| Gate | Required evidence | Current status |
| --- | --- | --- |
| Core repair | Real upgrade regression and model-generated repair pass tests | Passed one development case |
| Generalization | Untouched held-out tasks across repositories/ecosystems; failure taxonomy | Not run |
| Isolation | Independent Linux VM/container workers; no credentials, no egress; escape/probe tests; resource quotas | Local macOS harness only |
| Identity | OIDC, tenant scoping, reviewer roles, key rotation and TLS | Loopback cookie/bearer only |
| Integrity | Pinned image/dependency/source/test digests and approval freshness | Source/protected-file checks; environment binding incomplete |
| Operations | Leases, cancellation, restart/kill tests, bounded logs, retention, monitoring, backups | Single worker, SQLite checkpoints and basic queue |
| Delivery | Least-privilege GitHub App; draft PR against exact base SHA; idempotent publish | Local patch export only |
| Supply chain | License and vulnerability review of service and worker dependencies | Dataset license reviewed; complete audit pending |
| Customer value | Pilot measuring manual repair effort, accepted changes and regression rate | Not established |

A containerization milestone must validate worker isolation and the same repair case in Linux, not merely make `/healthz` respond. Only after these gates can the original “dockerize and put it in the cloud” expectation be honestly met.
