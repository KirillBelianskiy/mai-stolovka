# Stage 5 — Mini App authentication and profile

This follow-up to the menu/cart slice uses User Service session contract PR #42. It does not
change the User API, checkout, payments, or the existing menu/cart implementation.

## Client flow

- Read the original Telegram `tgWebAppData` from the current/navigation launch URL; do not use
  parsed Telegram identity as proof of authentication. Avoid the SDK reader's sessionStorage
  cache and remove only its known legacy `tapps/launchParams` entry. Cookie restore remains the
  persistent-login mechanism when the launch URL no longer contains fresh Telegram data.
- On startup, call `POST /api/v1/users/auth/session`. If it returns 401, submit the raw init data
  to `POST /api/v1/users/auth/telegram`. Other failures remain visible and do not silently start a
  second login flow.
- Keep the access JWT and returned profile in React memory. The browser manages the HttpOnly
  `mai_session` cookie with same-origin requests; do not persist tokens in web storage.
- Use `GET` and `PATCH /api/v1/users/me` for the profile, limiting edits to `full_name`. A protected
  request that gets 401 attempts one session restore. Retry once only when the restored account
  matches the original operation's account. If it changed in another tab, show the restored
  profile and an explicit cancellation notice; never replay the previous account's operation.
  Discard results that complete after the authentication generation has changed.
- Logout posts to `/api/v1/users/auth/logout` before clearing in-memory auth state. Account switch
  explicitly submits raw init data; a failed switch leaves the existing in-memory session intact.

## Verification record

| Check | Result |
| --- | --- |
| Mini App Node tests | 20 passed, including restore-first, login fallback, malformed responses, token refresh, explicit account switching, profile update, logout, network errors, cross-account retry rejection and raw URL extraction without a credential cache |
| Mini App TypeScript check | Passed on final source |
| Next.js static export build | Passed; all 20 tests passed in the build command, TypeScript completed, and both static routes prerendered |
| `git diff --check` | Passed |
| Browser against live disposable User Service | Passed in the Codex in-app Chromium browser on HTTP localhost: verified synthetic initData login, HttpOnly-cookie restore in a new tab with no launch data, name update, cross-tab account change with an expired 60s test JWT, cancelled old mutation, visible notice, logout and refusal to restore the revoked cookie. User runtime is exact #46 head 36a6897, including #42 sessions. PostgreSQL DB was generated and dropped. This is not HTTPS/domain/Telegram-webview acceptance. |
| Live Telegram client | Not run: no real BotFather token or Telegram session was supplied. |

Original PR #44 at a4d080c reported 18 Node tests and no live browser/User verification. The
review follow-up is stacked on that head and preserves its work. The two new tests had observed
red results before implementation: wrong-account replay succeeded, and the uncached reader was
absent. During browser verification the cancellation notice initially disappeared after automatic
profile refresh; preserving the notice through that refresh fixed the observed UX regression.

The static preview accepts optional `MAI_USER_TEST_URL` for an explicitly launched disposable
localhost User Service. It forwards only the User API prefix and selected request headers;
without this variable it serves the existing synthetic menu. It is test tooling, not a deployment
proxy or app route. No real bot token, Telegram send, application DB migration or production
configuration was used. Test services were stopped, test tabs closed and temporary DBs removed.

HTTPS/domain routing, other browser engines and the real Telegram client remain unverified.
PR #41/#44 and User session PR #42 remain independent and unmerged. No API or backend schema was
changed by the review follow-up. #46 recipient defects are a separate review finding, not a
failure of the exercised session flow; see [the delivery review](../reviews/2026-11-04-bobr.md).

Source checked 2026-11-04: [SDK launch-parameter caching](https://docs.telegram-mini-apps.com/packages/tma-js-bridge/launch-parameters),
[Telegram raw initData validation](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).
