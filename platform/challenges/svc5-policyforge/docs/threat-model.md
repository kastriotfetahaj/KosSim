# PolicyForge — threat model

## Roles

| Role             | Capabilities                                                          |
|------------------|------------------------------------------------------------------------|
| Unauthenticated  | Read `/health`, `/whoami`, `/api/objects` (no `data`), warm a guest    |
|                  | session via `/api/session/guest`, eval `allow public::<id>` against    |
|                  | public objects, mint a share token for any all-public snapshot.       |
| Guest session    | Same as above plus `/api/object/:id?session=<t>` with cached ABAC      |
|                  | enforcement.                                                           |
| Checker / ops    | Holds `X-Checker-Secret`. Drives PUTFLAG / GETFLAG / PUTNOISE /        |
|                  | GETNOISE / HAVOC against POST `/`. May read `/service`.                |

## Assets

- **Flag plaintext** for each round, stored in the `data` field of
  three independent objects (one per flagstore) with classes
  `incident`, `ledger-share`, `audit-record`.
- The **service secret** (`SERVICE_PUSH_SECRET`) which keys guest
  sessions and share tokens.
- The **decision cache** entries, which are sensitive when keyed coarsely.

## Trust boundaries

1. Plug pipeline → `PolicyForge.State` agent: same-process; trust is
   total but state mutations go through the agent's queue so two
   concurrent writers cannot tear an intermediate state.
2. Unauthenticated caller → router: untrusted; every privileged route
   must check either a signed session token, a signed share token, or
   the `X-Checker-Secret` header.
3. The service → disk: `state.term` is `chown appuser` and restored by
   `:erlang.binary_to_term/1` on boot. State restoration trusts the
   file; an attacker who can write under the data dir wins.

## Vulnerability classes covered by the challenge

- **Cache-key under-specification** — the policy decision cache used
  only `user:tenant:class`, so a positive decision on one object warmed
  all other same-class objects in the same tenant.
- **Substring denylist bypass** — a custom DSL keyword (`unless`) used
  an alternate evaluation pathway that did not run the `private::`
  substring check.
- **Signature binding gaps** — share tokens HMAC the snapshot id but
  the read handler dereferenced an unsigned `:id` URL parameter.
- **Magic-value query parameters** — `?tenant=public` on the legacy
  snapshot endpoint and `allow public::` returning a full object body.

## Out of scope

- Tenant boundaries beyond what `tenant=` covers. PolicyForge is
  effectively single-tenant per container.
- Erlang term forgery against `state.term`. We trust the file system
  inside the container.
- Replay protection on share tokens. The challenge does not require
  per-request nonces; defenders may add one if they like.
