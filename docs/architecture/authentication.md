# Authentication and authorization — Stage 2

Status: User/Menu backend implementation. The owner selected separate staff password accounts.

## Identity paths

`POST /api/v1/users/auth/telegram` accepts the original `init_data` string, not a client-parsed
user object. The server validates the Telegram HMAC using the configured bot token, compares
digests in constant time, rejects duplicate/malformed fields, and checks `auth_date`. Default
freshness is 300 seconds with 30 seconds of permitted future clock skew. Every signed field
except `hash`, including `signature` when present, participates in the HMAC data-check string.

The Telegram ID is a positive signed-64-bit integer. A database unique constraint and PostgreSQL
upsert preserve one user under concurrent login. New Telegram identities always receive CLIENT.
An existing staff identity cannot use Telegram login. Username refreshes from Telegram on login;
full name is initially populated from Telegram and later profile edits are preserved.

`POST /api/v1/users/auth/staff` accepts a separate staff login and password. Staff logins are
case-insensitive ASCII identifiers of 3–64 characters. `staff_credentials` has its own unique
login and a foreign key to users; it never shares Telegram usernames as credential identifiers.
Staff users have no Telegram ID. Password hashes use pwdlib's recommended Argon2id settings and
independent salts. Hashing/verification runs in the thread pool rather than blocking the async
event loop. Unknown users receive the same response and a dummy hash verification. Passwords and
hashes never appear in profile or login responses.

There is no public signup, default administrator, password in source, or Telegram-based employee
login. Operator-only commands provision COOK, CASHIER, or ADMIN accounts and reset passwords.
They require an interactive terminal and hidden password confirmation. Provisioning validates
12–128 characters, writes user and credential atomically, and rejects duplicate logins.

NGINX limits the exact staff-login route to 10 requests/minute per client IP with a burst of 10;
excess requests return 429. This is a local edge guard, not per-account lockout or a complete
production abuse-control system. Backend ports are not published. Review client-IP forwarding,
TLS, account recovery, MFA, and audit requirements before exposing real staff credentials.

## Access tokens and service boundaries

User Service signs RS256 JWTs; Menu Service receives only the RSA public key. A symmetric shared
secret would let a verifier mint tokens, so asymmetric signing preserves this responsibility.
The libraries are PyJWT with cryptography and pwdlib with Argon2; no identity infrastructure is
added. OIDC remains a possible future migration, but is not the selected Stage 2 staff mechanism.

The contract requires `sub` (user UUID), `role`, `jti` (UUID), `iat`, `nbf`, `exp`, `iss`, `aud`,
and `token_use=access`, with configured `kid`. Verification pins RS256, issuer, audience, key ID,
claim formats, and expiry. Default issuer/audience are `mai-food-users` / `mai-food-api`;
default lifetime is 900 seconds, configurable between 60 and 900 seconds. Keys below 2048 bits
or mismatched signing/verification pairs are rejected at startup. The local helper generates
3072-bit keys. Unknown keys/algorithms and malformed or expired tokens fail closed.

There are no refresh tokens or server-side revocation lists in Stage 2. Password reset does not
invalidate already issued JWTs immediately; they expire within the configured lifetime. User
Service checks current user existence and role for `/me`. Menu Service verifies signed claims
offline and cannot observe a deleted user or changed role until token expiry. Immediate revocation,
multi-key/JWKS rotation, device sessions, and staff lifecycle controls require a follow-up design.
Do not describe this implementation as complete production identity management.

## Mini App browser sessions

Telegram client login still validates the original fresh `initData`. On success, User Service also
creates a 32-byte random browser-session credential and stores only its SHA-256 digest in
`user_sessions`. The response retains the existing access-token/profile body and sets `mai_session`
as Secure, HttpOnly, host-only, SameSite=Strict, with path `/api/v1/users/auth`. There is no
cross-origin credential sharing. Set `APP_SESSION_COOKIE_ALLOWED_ORIGINS` to a comma-separated
list of exact Mini App origins; login, restore, and logout reject missing or unlisted Origin values.

`POST /api/v1/users/auth/session` verifies the cookie and current CLIENT profile, extends the idle
deadline by 30 days (capped by the 90-day absolute expiry), and returns a fresh access JWT. The
cookie value remains stable. `POST /api/v1/users/auth/logout` revokes only the presented browser
session and clears the cookie; repeating logout is safe. Logging into Telegram from the same browser
revokes its previously presented session before issuing a new one. Other browsers/devices are not
affected. An already-issued service JWT remains valid until expiry; the configured access-token TTL
is limited to 15 minutes.
The Mini App must verify the cookie-backed session before showing a remembered identity; missing,
blocked, revoked, or expired cookies require fresh Telegram authentication.

For browser regression, verify reopen/restore, cleared-cookie fallback, blocked-cookie fallback,
logout/replay rejection, and cookie flags in each supported browser engine. Run Secure-cookie checks
over local HTTPS: browser treatment of Secure cookies on localhost varies, and Safari/WebKit has a
documented exception. Browser-engine coverage must be recorded by the Mini App integration owner;
service integration tests alone do not establish browser compatibility.

Local private/public key values are base64 PEM in the ignored mode-0600 `.env`. Only User Service
receives the private key and bot token. Menu receives only the public key. Base64 is transport
encoding, not encryption. Production secret storage and rotation remain deployment decisions.
The helper refuses to overwrite an existing key pair; replacing keys is an explicit operation.

No Telegram bot token is generated or faked. With no real token, Telegram login returns 503.
Missing JWT keys disable authentication with 503; invalid credentials/tokens return 401. Database
health remains a bounded `SELECT 1`, so healthy HTTP/DB processes do not prove that auth secrets
are configured. Real Telegram use requires HTTPS and actual BotFather configuration. Bot write
permission and notification consent are separate and remain deferred.

## Current role matrix

| Operation | Anonymous | CLIENT | COOK | CASHIER | ADMIN |
| --- | --- | --- | --- | --- | --- |
| Public categories / available dishes | Yes | Yes | Yes | Yes | Yes |
| Own profile read / full-name update | No | Yes | Yes | Yes | Yes |
| Read unavailable dishes via admin listing | No | No | No | No | Yes |
| Create/update/delete categories and dishes | No | No | No | No | Yes |
| Set another user's role or create staff via HTTP | No | No | No | No | No |

Order, kitchen, cashier, and slot permissions remain future decisions. Do not infer them from
this menu/profile matrix. Credentials and tokens must not be stored in logs or committed files.

## References

- [Telegram initData verification](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)
- [FastAPI password hashing and JWT](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
- [PyJWT claim and RSA validation](https://pyjwt.readthedocs.io/en/stable/usage.html)
- [SQLAlchemy PostgreSQL upsert](https://docs.sqlalchemy.org/en/20/orm/queryguide/dml.html#orm-upsert-statements)
