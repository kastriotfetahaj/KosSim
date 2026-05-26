# NanoFleet — threat model

## Roles

| Role             | Capabilities                                                          |
|------------------|------------------------------------------------------------------------|
| Unauthenticated  | Read `/health`, `/whoami`, `/api/nodes`. Mint a fresh agent via       |
|                  | `/api/v2/agent/register` and receive that agent's node id + blob.     |
|                  | Mint a route token for `diag` via `/api/routes/diag-token`. Mint a    |
|                  | manifest token for a public blob via `/api/v2/firmware/issue`.        |
| Authenticated    | None modeled. NanoFleet has no user accounts.                          |
| Checker / ops    | Holds `X-Checker-Secret`. Drives PUTFLAG / GETFLAG / PUTNOISE /        |
|                  | GETNOISE / HAVOC against POST `/`. May read `/service`.                |

## Assets

- **Flag plaintext** for each round, stored on three independent nodes
  (one per flagstore) with `Kind` ∈ {`secret`, `manifest`, `diagnostic`}.
- The **service secret** (`SERVICE_PUSH_SECRET`) which keys the route,
  firmware-manifest, and HS256 diagnostic tokens.
- The **agent blob** values, returned to whomever registered the agent.

## Trust boundaries

1. The router → `state.Store`: same-process; trust is total.
2. Unauthenticated caller → router: untrusted; every request must be
   gated by either path-encoded permission, a signed token, or the
   `X-Checker-Secret` header.
3. The service → disk: the state file is `chown appuser`, so any process
   that escapes the container cannot rewrite state via that path. State
   restoration on boot trusts the on-disk JSON.

## Vulnerability classes covered by the challenge

- **Route shadowing via ad-hoc parsing** — the authorization check and the
  execution-step parser disagree about what a "command" is.
- **Magic-value side channels in legacy endpoints** — exercise paths kept
  for backwards compatibility expose flag bytes when a sentinel query
  parameter is sent.
- **Signature-binding bugs** — the manifest token binds {blob, ttl} but
  the read handler additionally consults unsigned `?blob=` and `?reveal=1`
  query parameters.
- **JWT alg/kid confusion** — the diagnostic token verifier accepts
  `alg=KID` and resolves the kid against a publicly-accessible key
  table (the agent registry).

## Out of scope

- Multi-tenant isolation (NanoFleet is single-tenant per container).
- Replay protection on manifest / diagnostic tokens. The challenge does
  not require nonce uniqueness; defenders may add it if they like.
- Side-channel timing attacks against the HMAC comparators
  (`hmac.Equal` is constant-time so this category is closed by Go itself).
