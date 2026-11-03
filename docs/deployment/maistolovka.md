# Existing maistolovka.me deployment assessment — issue #25

Status: read-only assessment, 2026-11-03. No provider settings, DNS, secrets, runtime, proxy, or
production resources were changed. Target remains the existing `maistolovka.me` deployment.

## Observed public state

| Probe | Observation | What it establishes |
| --- | --- | --- |
| `https://maistolovka.me/` browser | HTTP page renders the Russian Stage 1 placeholder “Обед в МАИ”; text says auth and orders are forthcoming | Static homepage is reachable; product journeys are not deployed there |
| HTTPS response headers | `200 OK`, `Server: cloudflare`, Cloudflare Ray ID returned | Request passes through Cloudflare; does not identify origin/provider or backend runtime |
| DNS A/AAAA | Resolves to Cloudflare anycast addresses | Cloudflare is in the DNS/edge path; origin addresses and hosting remain unknown |
| `/health/user/live` | `404 text/html` | No public route to the repository's User health endpoint was observed |
| `/health/order/ready` | `404 text/html` | No public route to Order readiness was observed |
| `/health/websocket/ready` | `404 text/html` | No public route to WebSocket readiness was observed |
| `/api/v1/users/health/live` | `404 text/html` | The local NGINX API route is not present on the observed public deployment |
| `/api/v1/ws/kitchen` HTTP request | `404 text/html` | The reserved local WebSocket route is not present on the observed public deployment; no WS handshake was attempted |
| `/kitchen/` | `404 text/html` | No Kitchen app route was observed at this path |

Checks were read-only and performed from Windows on 2026-11-03. Public HTTP reachability does not
prove what branch/artifact is deployed, whether a backend exists privately, or whether a WebSocket
upgrade works. Do not infer those facts from DNS or the homepage.

## Repository baseline and gap

At product main `4fb68861409fde88e6f0ea98d9cb7d7a61a79c4c`, the repository contains two static Next.js
exports served on local Compose ports 8080/8081; User, Menu and Order FastAPI services; process-only
Notification and WebSocket shells; PostgreSQL and Kafka. Compose binds public-facing development
ports to `127.0.0.1`, and no deploy workflow or provider runtime manifest is present in `.github` or
`infra`. The local NGINX file routes both app origins, service APIs and `/api/v1/ws/kitchen`; that is
local configuration, not evidence it is active in the Cloudflare deployment.

The public root content matches the placeholder stage, while the inspected product source contains
Stages 1–3. Current source therefore cannot be assumed to match the live artifact. The public
health/API probes return HTML 404 and must not be described as backend health checks.

## Cloudflare Pages build failure

Cloudflare Pages check comments on product PRs #11, #12, and #26 show a failed build, but their
GitHub status links expose only the deployment summary and a Cloudflare dashboard link. No build log
or root cause was available through the repository status/comment. The known failed build is evidence
of a failed Pages check only; attributing it to a Node version, framework setting, or source error
would be speculation.

Read-only dashboard log review and Pages project settings are still required from an authorized
Cloudflare account session to record the actual project ID/name, production branch, build command,
output directory, Node/package-manager versions, environment-variable names (never values), deployed
commit, and exact failure. Do not change settings or retry production deployment during assessment.

## Routing and runtime decisions needed

The current two static origins (customer and staff) can be mapped behind the domain, but no public
backend routes work. A complete route plan requires a verified long-running backend host for five
Python services, PostgreSQL, and Kafka. Cloudflare Pages static hosting alone does not establish
those runtimes. Do not place databases/brokers in a Pages function or expose local Compose ports as a
production design without explicit architecture review.

Before an isolated routing change, record:

- Which existing host runs the service containers, PostgreSQL and Kafka, its private network path,
  process supervision and backup responsibility.
- Customer and Kitchen path prefixes, API routing, WebSocket upgrade pass-through, trusted proxy
  headers, exact allowed origins/CORS, TLS termination, timeouts and request-size/rate limits.
- Telegram Mini App's registered HTTPS URL, bot/update intake mode, webhook route if selected, and
  secure owner-controlled token injection. Do not publish tokens or use browser-supplied credentials
  for service-to-service access.
- Whether Pages is the existing static frontend host and how it reaches the verified backend host;
  require a tested end-to-end TLS/API/WebSocket path before any production settings change.

## Next steps and gates

1. Owner/operator reviews the assessment and supplies or opens an authorized read-only Cloudflare
   dashboard session. Capture actual failure logs and deployment settings without secret values.
2. Identify the existing backend host and confirm it can run the Python services plus PostgreSQL and
   Kafka under the already selected architecture. If none exists, prepare options and request an
   explicit infrastructure decision; do not provision a replacement as part of this task.
3. Draft a route/TLS/WebSocket plan against verified provider capabilities. Validate it in an
   isolated preview/staging environment with both apps, API health, authenticated API calls and a
   real WebSocket upgrade before proposing any production change.
4. Production changes require a reviewed plan and explicit rollout approval. No migration, secret
   upload, domain/DNS edit, Pages settings change, or deployment was performed in this assessment.

## Evidence limits

No Cloudflare dashboard credentials/logs, origin configuration, service host, private network,
production secrets, or authenticated customer/staff flows were available in this pass. The existing
domain is reachable but the repository's full application is not demonstrated on it. This assessment
does not claim deployment readiness or recommend a replacement host.
