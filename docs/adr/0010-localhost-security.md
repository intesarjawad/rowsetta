# 0010: Localhost security model

Status: accepted.

## Threat

The local server holds the user's table. Any web page the user visits can send
requests to `127.0.0.1`, and DNS rebinding can make a foreign host name resolve
there. Other local users and processes can reach a port bound to every
interface.

## Decision

- **Loopback bind by default.** `--host` defaults to `127.0.0.1`.
- **Host allowlist.** `TrustedHostMiddleware` accepts only `127.0.0.1` and
  `localhost` in the `Host` header, which defeats DNS rebinding. A foreign host
  is rejected before authentication.
- **Per-launch token.** Each launch draws a fresh `secrets.token_urlsafe(32)`
  and prints the URL `/?token=...`. The first request exchanges it for an
  HTTP-only, `SameSite=Strict` cookie and redirects to `/` with
  `Referrer-Policy: no-referrer`, so the token leaves the address bar. Every
  route except `/health` requires the cookie; tokens are compared in constant
  time.
- **Test token on loopback only.** `ROWSETTA_SESSION_TOKEN` fixes the token
  for end-to-end tests and is refused unless the bind address is `127.0.0.1`.
- **No egress.** The app sets `HF_HUB_DISABLE_TELEMETRY=1` and
  `HF_HUB_OFFLINE=1` before the Hugging Face client is imported; the model is
  fetched only by `rowsetta doctor --fix` or the first run of `demo` and
  `open`. An integration test runs the whole flow with name resolution and
  outgoing connections blocked.
- **Errors without internals.** Unexpected failures return the error contract
  body with a recovery step and log the details locally; the token never
  appears in workspace state or exports.

## Consequences

`/health` stays public so scripts and the install smoke test can poll it; it
carries no workspace state. Binding to another interface is an explicit user
choice and still requires the token.
