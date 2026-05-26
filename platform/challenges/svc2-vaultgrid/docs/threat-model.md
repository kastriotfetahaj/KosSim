# VaultGrid threat model

## Trust boundaries

| Principal | Trust |
|---|---|
| The checker | Holds `SERVICE_PUSH_SECRET`. Drives PUTFLAG / GETFLAG / HAVOC via `POST /` and may register accounts or store noise via authenticated endpoints. |
| The team (defender) | Owns the source tree and may patch the service. Patches must keep the checker passing. |
| Other teams (attackers) | Have unauthenticated network access to port 8080 and the values published via attack-info. |
| Sidecars to each other | Trust the shared secret on internal write paths. Read paths are tenant-scoped. |

## Attack-info schemas

```
flagstore 0 (wire-transfer):
    {"a": object_id, "b": lease_id, "c": meta_id, "p": 0, "t": tick}

flagstore 1 (manifest):
    {"a": manifest_id, "b": "checker", "iv": hex, "ciphertext": hex,
     "p": 1, "t": tick}

flagstore 2 (feed record):
    {"a": record_id, "b": "checker", "offset": int, "length": int,
     "p": 2, "t": tick}
```

## SLA contract (what patches must preserve)

- `POST /` PUTFLAG/GETFLAG/PUTNOISE/GETNOISE/HAVOC for variants 0, 1, 2 keep returning `result: OK`.
- `/health`, `/whoami`, `/service` (with checker secret), `/api/objects` keep their JSON shapes.
- The proxy paths `/api/crypt/manifests`, `/api/crypt/manifests/:id`, `/api/feed/records`, `/api/feed/show` keep their shapes on the public-tenant happy paths.
- Per-tick PUT+GET roundtrip completes under 15 seconds against a healthy stack.
