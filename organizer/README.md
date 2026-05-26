# organizer/

This directory contains **organizer-only** artifacts that must never
be mounted into player containers:

- `DESIGN.md` — Phase 2 spec for the ECSC-grade upgrade.
- `exploits/svcN/exploit_fsK.py` — one working exploit per flagstore.
  - Each script accepts `--target host:port` and prints the captured
    flag to stdout.
  - Must be deterministic enough for CI.
- `patches/svcN/{vulnK.patch,all.patch}` — per-vuln reference patches and
  one rollup. Applied with `patch -p1` from inside `service/`.
- `docs/svcN/PATCH_MATRIX.md` — ECSC-style matrix per vulnerability
  (root cause, exploit idea, difficulty/discoverability/patchability,
  expected solve path, rabbit holes, checker coverage, …).
- `ci/` — helper scripts used by `.github/workflows/ci.yml` and the root
  `Makefile`.

## Conventions

- Filenames use `svcN` (not the long codename) so paths stay short.
- Exploit scripts must exit non-zero if the flag is not captured.
- Patches must apply cleanly to the service tree as shipped.
- Tests in `tests/integration/test_svcN.py` run each exploit against:
  1. the unpatched service → exploit must succeed,
  2. the patched service (after applying `all.patch`) → exploit must fail,
  3. the patched service via the noise workflow → must still succeed
     (ensures the patch does not regress legitimate functionality).

## Status

See `DESIGN.md` for the master per-service checklist.
