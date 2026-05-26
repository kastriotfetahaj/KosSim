# NanoFleet patches

Each `.patch` file mitigates exactly one vulnerability. Patches are organized
by the flagstore they protect; applying all five returns the service to a
fully patched baseline while preserving the SLA. CI applies each patch in
isolation and re-runs the checker to assert the SLA still holds.

## Flagstore 0 — drone telemetry node

- `flagstore-0/vuln-a-route-shadow.patch` — primary path
  Replace the prefix check on `/api/route/<chain>` with strict equality and
  drop the semicolon-chain executor. The authorized command is executed
  exactly once.

- `flagstore-0/vuln-b-tlv-magic-length.patch` — exercise
  Remove the `length=260` magic-value branch from `/api/tlv/decode`.

- `flagstore-0/vuln-c-firmware-manifest-public.patch` — exercise
  Drop the `?manifest=public` override on `/api/firmware/blob/<b>`.

## Flagstore 1 — firmware manifest

- `flagstore-1/vuln-d-firmware-reveal-binding.patch`
  Require the `?blob=` parameter on `/api/v2/firmware/read` to match the
  blob bound by the signed manifest, and stop honoring the unsigned
  `?reveal=1` query flag. Public manifest tokens can no longer unlock
  foreign blobs.

## Flagstore 2 — diagnostic JWT

- `flagstore-2/vuln-e-jwt-kid-confusion.patch`
  Remove the `alg=KID` path from the diagnostic-token verifier so only
  HS256 (the operator's shared secret) is accepted.
