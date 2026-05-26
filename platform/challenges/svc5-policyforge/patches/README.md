# PolicyForge patches

Each `.patch` file mitigates exactly one vulnerability. Patches are organized
by the flagstore they protect; applying all five returns the service to a
fully patched baseline while preserving the SLA. CI applies each patch in
isolation and re-runs the checker to assert the SLA still holds.

## Flagstore 0 — incident object

- `flagstore-0/vuln-a-cache-key-object-id.patch` — primary path
  Extend the policy-decision cache key to include the object id. The cache
  can no longer carry an allow decision from a public object to a private
  one of the same class.

- `flagstore-0/vuln-b-policy-eval-data-leak.patch` — exercise
  Refuse private objects from `PolicyDSL.load/1` and strip the `data` field
  from successful `allow public::` responses.

- `flagstore-0/vuln-c-snapshot-tenant-bypass.patch` — exercise
  Stop honoring `?tenant=public` on `/api/snapshot/<s>/object/<id>`. The
  legacy snapshot endpoint now relies solely on the object's own public bit.

## Flagstore 1 — snapshot share token

- `flagstore-1/vuln-d-share-token-object-binding.patch`
  Require the requested object id to appear in the snapshot the share
  token was minted for. A token issued for `public-snap` only unlocks
  the objects sealed inside it.

## Flagstore 2 — audit record (policy DSL `unless`)

- `flagstore-2/vuln-e-policy-unless-bypass.patch`
  Drop the `unless` fast-path and its `raw_eval/1` helper from the policy
  DSL. Every expression now flows through the cond chain in `eval/1`, so
  the `private::` substring denylist always applies.
