# PolicyForge — architecture

PolicyForge is a single-container Elixir / Plug / Cowboy service that
simulates an ABAC policy engine for incident objects. It exposes port
8080 and persists state to an Erlang term file under
`$POLICYFORGE_DATA_DIR` (default `/var/lib/policyforge`).

## Process layout

```
+--------------------------------------------------------------+
|  policy_forge (Elixir/OTP, port 8080)                        |
|                                                              |
|  PolicyForge.Router (Plug.Router) ─────► PolicyForge.State   |
|     ├──► /api/object/:id  ─────────► allowed?/2 (cache)      |
|     ├──► /api/policy/eval ─────────► PolicyDSL.eval/1        |
|     ├──► /api/snapshot/:s/object/:id ─► Snapshot.read/3      |
|     ├──► /api/snapshot/share/issue                            |
|     ├──► /api/snapshot/share/:t/object/:id ─► Share.verify/2 |
|     └──► /rpc, /health, /whoami, /service                    |
+--------------------------------------------------------------+
                          │
                          ▼
        /var/lib/policyforge/state.term  (Erlang :term)
```

There is no database. All state — flags per (tick, variant), incident
objects, decision cache, snapshots — lives inside a single OTP
`Agent` named `PolicyForge.State`. Mutations are serialized through the
agent and snapshotted to disk via `:erlang.term_to_binary/1`. The
process is rebuilt deterministically from disk on boot.

## Flagstore layout

Each flagstore stores its flag inside a synthetic object whose `data`
field holds the round's plaintext flag. The `class` discriminator
records which flagstore minted the object, which is also what the
policy-decision cache used to key by (see flagstore-0/vuln-a).

| Flagstore | Variant | Object class    | Surface                                          |
|-----------|---------|-----------------|--------------------------------------------------|
| 0         | 0       | `incident`      | `GET /api/object/:id?session=...`                |
| 1         | 1       | `ledger-share`  | `GET /api/snapshot/share/:token/object/:id`      |
| 2         | 2       | `audit-record`  | `GET /api/policy/eval?expr=unless ... allow private::...` |

The `attack_info` payload is consistent across flagstores: `{"a", "b", "c", "p"}`
where `a` is the flag object id, `b` is the public-incident id (warmup
target for FS0), `c` is the flag object's own snapshot id, and `p` is
the variant.

A fixed public object/snapshot pair (`public-incident` inside
`public-snap`) is seeded at boot so share-token issuance has a sealed
public snapshot to mint against.

## Token formats

PolicyForge mints two unrelated token types. Both use
`base64.url_encode64/1` (no padding) for components and HMAC-SHA-256 as
the underlying primitive.

- **Guest session tokens** (`Token.sign/3`) —
  `body64 . sig` with body `{"user","groups","exp"}`. Used to gate
  `/api/object/:id` and `/api/policy/eval`.

- **Share tokens** (`Share.issue/2`) — `body64 . sig` with body equal
  to the (raw) snapshot id. The signature binds the snapshot but not
  the object id (intended bug surface).

## Persistence

`PolicyForge.State.persist/1` writes the full agent map as an Erlang
term on every mutation. A separate `evaluations.log` records the
current object count for operator dashboards. Both files live under
`$POLICYFORGE_DATA_DIR` and are chowned to `appuser` by the Dockerfile.
