# Final MVP Caddy release verification

## Candidate and scope

PR [#67](https://github.com/KirillBelianskiy/mai-stolovka/pull/67) preserves main
`c80993a5b681679900caa87e43e0d9e4017a622b` and the working baseline
`f0202c1a1924415018236a7641df7a9623adf0f8`. Exact Caddy commit
`b8a67b66999bbc441aac7093ff142b849fe1a87b` was fetched from the owner-specified separate
clone; its direct parent is the baseline. Subsequent changes are ordinary descendants.
No source checkout or primary-checkout edits were changed. Publication uses fast-forward pushes.

The release changes ingress and verification, with a Next.js patch from 16.4.3 to 16.4.5 after
the local build reported an advisory. Both frontends remain static exports; no Next.js runtime,
business policy, role, service boundary, data model, Redis, or real payment provider is added.

## Local checks — 2026-11-25

- Root Ruff, 28 contract tests and two acceptance harness tests passed, including Mac artifact
  selection and failure recovery. All four Compose models validated with synthetic values.
- All service Ruff, formatting and Mypy checks passed. Unit/snapshot results: User 53,
  Menu 21, Order 62, Notification 31, WebSocket 32 passed. Respectively 14, 14, 51, 30 and 1
  integration cases skipped locally without isolated database/broker endpoints.
- Both frontend typechecks and static builds passed with Next.js 16.4.5. The build includes
  30 client unit tests and 23 DOM component tests; all passed. The patched npm audit reports
  zero vulnerabilities. Existing Starlette/httpx deprecation warnings remain.
- Local Docker has no daemon socket. No container or production-route pass is claimed locally.
  Container builds, integration and production-path checks run on GitHub-hosted disposable runners.

## Automated production-path gate

Run from the candidate checkout with Python 3.12, OpenSSL, Git and a local Docker daemon:

```sh
git fetch --no-tags --depth=1 origin f0202c1a1924415018236a7641df7a9623adf0f8
python3 tests/e2e/production_release.py --output /tmp/mai-production-new-run.json
```

The runner reads production Compose and Caddy configuration directly. Only the issuer changes
to local TLS. The HTTP client connects exclusively to IPv4 loopback and verifies the generated
CA and expected hostname. Compose guards reject external volumes/networks, non-loopback ports,
or a real dispatcher token. Both PostgreSQL and Kafka remain unexposed. Synthetic Telegram HMAC
and Notification signing keys are generated per run; no user account or live Telegram API is used.
All four migrations precede services/workers; the Kafka topic is explicitly provisioned.

The report records the checked-out Git SHA, migration heads, pinned Caddy/module identity,
stage outcomes, synthetic API status observations, wallet/ledger/slot/Outbox invariants, and
one committed fake delivery. It never includes passwords, cookies, JWTs, initData or webhook
secrets. Cleanup removes only the UUID-named test project and its disposable volumes.

| Gate | Evidence required |
| --- | --- |
| Proxy compatibility | Replay immutable baseline Nginx config and migrated Caddy against identical upstreams/exports; compare methods, prefixes, slash redirects/query, API JSON/status, assets, unknown route 404 |
| Mac rollback | Validate actual staging Caddyfile and serve explicit immutable old → new → old artifact selections; existing unit test also covers failed selection restoration |
| Customer | Menu, signed Telegram login, Secure/HttpOnly/SameSite=Strict cookie, session restore/logout/replay rejection, profile read/update, authenticated slots, wallet, history, details, no-store |
| Booking | Concurrent same-key checkout causes one debit/order; cancellation causes one refund; original replay remains stable; repricing needs explicit confirmation |
| Kitchen | Staff login/profile/queue, role denials, admin menu/slots/credit, source-network denial despite spoofed forwarding headers |
| Staff limiter | Ten login attempts reach auth; eleventh is 429 even with spoofed X-Forwarded-For; other APIs remain available; next login is accepted after the rolling minute |
| Webhook | Exact production POST only when flag enabled; missing/invalid secret denied; valid update/replay accepted; query/trailing slash/wrong method/Kitchen host denied |
| Internal routes | Recipient endpoints remain 404 on both hosts despite forwarding/public-marker spoofing; staff token cannot use customer-only routes |
| WSS | Local TLS, staff first-frame auth and reconnect, invalid/client token denial, actual Kafka order hint during preparation/issuance |
| READY | One fake Telegram send and one committed sent dispatch/attempt before cashier completion; same result after restart |
| Upgrade | Reapply four migration heads and restart over the same disposable volumes; completed order, wallet and delivery remain intact |
| Logging | Compression, HTTP→HTTPS redirect/query, and no credential/launch-data marker in edge request logs |

The initial production run built Caddy/modules, migrated all four databases and authenticated
synthetic users, then failed on the harness expecting SameSite=Lax. The contract is Strict;
the harness was corrected without changing product cookies or authorization. This is a test
expectation correction, not a fixed application vulnerability.

Revision `183796d9aba1d24d6a97faf7dbaccef552efddc4` then passed all nine jobs in its
[push workflow](https://github.com/KirillBelianskiy/mai-stolovka/actions/runs/45585737509).
Its [18-stage report](https://github.com/KirillBelianskiy/mai-stolovka/actions/runs/45585737509/artifacts/15008114807)
records Caddy 2.11.9 with rate-limit 0.1.0, all four schema heads, 19 baseline proxy comparisons,
54 authenticated/booking observations, two database snapshots, one fake send, and clean teardown.
The integration job passed 109 service cases and 10 running-stack smoke checks. Nginx and Caddy
returned the same application JSON and static asset bytes in the paired cases. The redirects
matched status and destination path/query. Caddy uses its own proxy-generated redirect and 404
bodies. The final revision has its own push workflow and report. Its links and review decision
belong in the release handoff.

## Operational boundary and references

Public DNS, VM provisioning/deployment, public ACME, real Telegram rollout, real-device/browser
acceptance, off-VM backup recovery, resource/load qualification and pilot authorization remain
separate operational work. The legacy Cloudflare Pages check is tracked separately from this
Caddy release and is not evidence for backend or edge health. GitHub main initially reported
no active branch rules; owner-required CI and independent review still gate the merge.

Official sources checked 2026-11-25:
[Caddy reverse proxy and forwarding](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy),
[Caddy static file behavior](https://caddyserver.com/docs/caddyfile/directives/file_server),
[Caddy 2.11.9](https://github.com/caddyserver/caddy/releases/tag/v2.11.9),
[rate-limit module 0.1.0](https://github.com/mholt/caddy-ratelimit/tree/v0.1.0),
[Next.js patched version](https://github.com/vercel/next.js/security/advisories/GHSA-f3mh-rxg3-f5g2).
The pinned tags were independently resolved through GitHub's API before the build.
