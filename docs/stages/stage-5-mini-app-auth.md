# Stage 5 — Mini App authentication and profile

This follow-up to the menu/cart slice uses User Service session contract PR #42. It does not
change the User API, checkout, payments, or the existing menu/cart implementation.

## Client flow

- Read the original Telegram `initData` with `retrieveRawInitData`; do not use parsed Telegram
  identity as proof of authentication.
- On startup, call `POST /api/v1/users/auth/session`. If it returns 401, submit the raw init data
  to `POST /api/v1/users/auth/telegram`. Other failures remain visible and do not silently start a
  second login flow.
- Keep the access JWT and returned profile in React memory. The browser manages the HttpOnly
  `mai_session` cookie with same-origin requests; do not persist tokens in web storage.
- Use `GET` and `PATCH /api/v1/users/me` for the profile, limiting edits to `full_name`. A protected
  request that gets 401 attempts one session restore and one request retry.
- Logout posts to `/api/v1/users/auth/logout` before clearing in-memory auth state. Account switch
  explicitly submits raw init data; a failed switch leaves the existing in-memory session intact.

## Verification record

| Check | Result |
| --- | --- |
| Mini App Node tests | 18 passed, including restore-first, login fallback, malformed responses, token refresh, explicit account switching, profile update, logout and network errors |
| Mini App TypeScript check | Passed on final source |
| Next.js static export build | Passed before the final refresh fallback and account-switch test changes; not rerun after those source changes |
| `git diff --check` | Passed |
| Chromium against live User Service over HTTPS | Not run: local disposable User DB setup could not authenticate with the checked-out local PostgreSQL credentials; the temporary DB was removed. |
| Live Telegram client | Not run: no real BotFather token or Telegram session was supplied. |

Browser and live-service behavior remain to be verified by the owner in a correctly configured
local environment. PR #41 and User session PR #42 remain independent and unmerged. This branch is
a follow-up based on PR #41; its integration handoff uses the User API contract in PR #42.
