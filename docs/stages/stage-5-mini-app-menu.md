# SCRUM-25 — public Mini App menu and cart

Status: bounded implementation for review, 2026-11-04. Part of
[#20](https://github.com/KirillBelianskiy/mai-stolovka/issues/20), based on main `4fb6886`.
This slice replaces the placeholder with public browsing and a saved food selection.
It does not complete Telegram authentication/profile, checkout/history or demo-payment UI.

## Owner decision and task boundary

The owner rejected mandatory re-login after every close and explicitly requested persistent
Mini App login on 2026-11-04: “Нужен вход с сохранением сессии”. The previous memory-only
login recommendation D8 is not approved. User-owned session contract/runtime is now
[#40](https://github.com/KirillBelianskiy/mai-stolovka/issues/40), assigned to Bobr2610.
Frontend auth completion in #20, then #21/#33, depends on that reviewed interface.

The server-owned session, protected cookie, restore/logout, expiry/CSRF/rotation and account-switch
details remain User-owned design work. This public slice adds no auth endpoint, token persistence,
remembered identity, fake Telegram login, private Query data or checkout intent journal.
Public menu/cart needs no new authentication policy or shared infrastructure. Mac edits only
`apps/telegram-mini-app` and this verification record; Bobr's User/Kitchen/WebSocket paths remain
separate. No shared API/Compose/proxy/CI configuration changes are needed.

## Design and behavior

Direction: a readable cafeteria menu in the existing ivory/navy/blue palette, with system Arial
type, strong dish/price hierarchy and a navy receipt-shaped cart as the signature element.
Desktop uses two menu columns beside a sticky receipt; mobile uses a single menu column,
horizontal category controls and a fixed cart anchor. Motion communicates loading/refresh,
with a reduced-motion override. No external visual reference, downloaded font or generated
photo is required. Optional images come from validated HTTP(S) menu URLs and fail safely.

- GET categories and paginated items from existing same-origin public Menu APIs. Validate successful
  response shapes, UUIDs, pagination and integer kopecks before rendering. Public fetches omit
  credentials, bypass browser cache, reject redirects and forward cancellation signals.
- Category selection resets pagination. Explicit “Ещё блюда” loads the next page; changing category
  does not replace the cart. Loading, empty, network-error/retry and refresh states are visible.
- Cart entries hold only dish UUID and positive integer quantity. At most 100 distinct lines and
  existing signed-32-bit amount/quantity bounds apply. Browser totals are estimates, not quotes.
- Persist a versioned public selection in localStorage; never persist prices, tokens, user/profile
  data, statuses or order/payment claims. Validate size, schema, UUIDs, uniqueness and quantities
  on restore. Corrupt input is discarded with a visible warning; storage failures explicitly
  limit persistence to the current page. No cross-tab synchronization is promised.
- Each saved line resolves its current public item endpoint, independent of selected category
  and loaded pages. Missing/unavailable/failed item data makes the estimate incomplete, disables
  its increment control and leaves remove/recheck available. No stale balance/order is inferred.
- Render safe money arithmetic and explicit price-confirmation wording. Free prices remain valid;
  incomplete/overflowing totals show a check-needed state. No order/payment request is sent.

Future auth integration must decide how this anonymous food selection is adopted/cleared across
accounts; it is not an account identity or an uncertain checkout journal. #21 still owns exact
key/body persistence, price reconfirmation, slots and cancellation. #33 owns demo balance/payment.

## Verification defined and performed

Before implementation, `tests/menu.test.mjs` specified corrupted/duplicate/credential-containing
cart rejection, quantity/line caps, current-price arithmetic/overflow and validated/cancellable
public requests. The first run failed with `ERR_MODULE_NOT_FOUND` for the absent `src/lib/menu.ts`.
After implementation, all six domain/API test groups pass. No fabricated browser red is claimed.
Tests run automatically as part of the Mini App build without adding a dependency or editing CI.

Installed Next.js is `16.4.3`, beyond the ui-design skill's specified patched minimum. Existing
static export and client components remain; there is no server route, server action or runtime
Next.js requirement. Node 22 runs the TypeScript-only domain module through built-in stripping.

| Check | Result |
| --- | --- |
| `npm run test --workspace @mai/telegram-mini-app` | Six test groups pass: money/image safety; strict cart persistence; bounds/removal; current-price totals; response validation; public-fetch options/error sanitization |
| `npm run typecheck --workspace @mai/telegram-mini-app` | Passed |
| `npm run build --workspace @mai/telegram-mini-app` | Passed; static `/` and not-found output; tests run first |
| Formatting / whitespace | Prettier 3.6.2 applied to changed frontend/test files; `git diff --check` passed |
| Desktop browser, 1440×1000 | Synthetic exported-app preview inspected; menu/receipt render without horizontal overflow; quantity controls 44×44 px |
| Mobile browser, 390×844 | No horizontal document overflow; stacked cards and fixed cart anchor inspected; keyboard focus has visible solid outline |
| Browser interaction | Add/remove/increment and clear controls; reload restores selected lines/quantities; category filtering and 24→28 item pagination observed |
| Browser state failures | Loading skeleton observed with delayed API; explicit empty state; 503 error with enabled retry; unavailable saved items show unknown estimate and disabled increment |

Browser tests used only `tests/preview-server.mjs`, a loopback-only static-export server with
synthetic Menu responses. It is test infrastructure and is never imported into production code.
No live menu/customer data, Telegram identity, credentials, payment or staff state was used.
The test preview's displayed dishes are examples, not the live cafeteria menu. Browser screenshots
are local review artifacts, not evidence of production deployment or user-tested usability.
Cookie/session behavior, blocked localStorage, real Telegram entry, profile, checkout, provider
payment, production routing and load capacity were not tested by this slice.

## Handoff

Keep #20 open: persistent session/auth/profile depend on #40. #21/#33 remain separate units.
No merge or deployment is authorized. Final PR-head GitHub Actions results belong in the PR
handoff; local builds alone do not establish remote CI or maistolovka.me backend connectivity.

Sources checked 2026-11-04: [Next.js static exports](https://nextjs.org/docs/app/guides/static-exports),
[browser Set-Cookie behavior](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie).
Actual data shapes were checked against committed Menu OpenAPI and service routes. Cookie
documentation supports the future User-owned session discussion; it does not establish an
implemented or approved session contract in this change.
