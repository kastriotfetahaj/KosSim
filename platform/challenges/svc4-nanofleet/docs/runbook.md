# NanoFleet — runbook

## Local development

Build the image from `platform/challenges`:

```sh
docker build -t nanofleet-service -f svc4-nanofleet/service/Dockerfile .
docker run --rm -p 8080:8080 \
  -e SERVICE_PUSH_SECRET=rotate-secret \
  -e TEAM_NAME=dev \
  -e SERVICE_NAME=svc4 \
  nanofleet-service
```

Pure-Go build for fast iteration:

```sh
cd svc4-nanofleet/service
go build ./...
./nanofleet
```

## Smoke test

```sh
# health + checker
python svc4-nanofleet/checker/checker.py http://127.0.0.1:8080

# one flag round end-to-end (flagstore 0)
INFO=$(curl -fsS \
  -H "X-Checker-Secret: rotate-secret" \
  -H "Content-Type: application/json" \
  -d '{"method":"PUTFLAG","current_round_id":1,"variant_id":0,"flag":"FLAG{SMOKE}"}' \
  http://127.0.0.1:8080/ | python -c "import sys,json;print(json.load(sys.stdin)['attack_info'])")
python svc4-nanofleet/exploits/exp1.py 127.0.0.1:8080 "$INFO"
# expect: FLAG{SMOKE}
```

## Patch validation

Apply all five patches and re-run the SLA checker. The CI workflow
(`.github/workflows/ci.yml`) does this for every patch in isolation via a
matrix job; reproduce locally with:

```sh
cd svc4-nanofleet
for p in patches/flagstore-*/*.patch; do
  patch -p1 < "$p"
done
go -C service build ./...
# ...rebuild image, run checker, expect OK...
for p in $(ls -r patches/flagstore-*/*.patch); do
  patch -R -p1 < "$p"
done
```

## Operating

- `NANOFLEET_DATA_DIR` — state directory (default `/var/lib/nanofleet`).
  Persist the volume across container restarts to keep flags between
  rounds; the round driver will reset round state on PUTFLAG anyway.
- `SERVICE_PUSH_SECRET` — must match the platform's checker secret.
- `TEAM_NAME`, `SERVICE_NAME` — used for HMAC salting in attack_info and
  in display strings on `/health` and `/whoami`.
- `BOOT_FLAG` — seed flag for the bootstrap state. Defaults to
  `FLAG{BOOT_NANOFLEET}`. Used internally only; production deployments
  override it.

## Failure modes

- **Checker `MUMBLE`**: state file in `$NANOFLEET_DATA_DIR` is corrupted.
  Delete `state.json` and reboot; flags will be re-seeded.
- **Checker `DOWN`**: container crashed or port 8080 not listening. Check
  the container logs and ensure the appuser has write permission to
  `$NANOFLEET_DATA_DIR`.
- **All exploits succeed against a patched build**: a patch was reverted
  somewhere. Re-run `patch -p1 < ...` for the relevant flagstore.
