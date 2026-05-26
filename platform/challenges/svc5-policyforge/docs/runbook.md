# PolicyForge — runbook

## Local development

Build the image from `platform/challenges`:

```sh
docker build -t policyforge-service -f svc5-policyforge/service/Dockerfile .
docker run --rm -p 8080:8080 \
  -e SERVICE_PUSH_SECRET=rotate-secret \
  -e TEAM_NAME=dev \
  -e SERVICE_NAME=svc5 \
  policyforge-service
```

There is no host-Elixir workflow shipped with this challenge; the
`elixir:1.17-slim` image and `mix deps.get` line in the Dockerfile are
the canonical build. If you have Elixir installed locally you can run
`mix compile && mix run --no-halt` from `svc5-policyforge/service`, but
CI never does this.

## Smoke test

```sh
python svc5-policyforge/checker/checker.py http://127.0.0.1:8080

INFO=$(curl -fsS \
  -H "X-Checker-Secret: rotate-secret" \
  -H "Content-Type: application/json" \
  -d '{"method":"PUTFLAG","current_round_id":1,"variant_id":0,"flag":"FLAG{SMOKE}"}' \
  http://127.0.0.1:8080/ | python -c "import sys,json;print(json.load(sys.stdin)['attack_info'])")
python svc5-policyforge/exploits/exp1.py 127.0.0.1:8080 "$INFO"
# expect: FLAG{SMOKE}
```

## Patch validation

Apply all five patches and re-run the SLA checker. The CI workflow
(`.github/workflows/ci.yml`) does this for every patch in isolation via
a matrix job; reproduce locally with:

```sh
cd svc5-policyforge
for p in patches/flagstore-*/*.patch; do
  patch -p1 < "$p"
done
# rebuild image, run checker, expect OK
for p in $(ls -r patches/flagstore-*/*.patch); do
  patch -R -p1 < "$p"
done
```

## Operating

- `POLICYFORGE_DATA_DIR` — state directory (default
  `/var/lib/policyforge`). The agent restores from
  `state.term` on boot.
- `SERVICE_PUSH_SECRET` — must match the platform's checker secret. The
  same secret keys guest sessions and share tokens.
- `TEAM_NAME`, `SERVICE_NAME` — used for hash salting on flag-object ids
  and in display strings on `/health` / `/whoami`.
- `BOOT_FLAG` — seed flag for the bootstrap state. Defaults to
  `FLAG{BOOT_POLICYFORGE}`. Production deployments override it.

## Failure modes

- **Checker `MUMBLE`**: state file in `$POLICYFORGE_DATA_DIR` is
  corrupted. Delete `state.term` and reboot; the agent will seed a fresh
  public snapshot.
- **Checker `DOWN`**: container crashed or port 8080 not listening. Check
  `docker logs` and ensure `appuser` can write to the data dir.
- **`exp3.py` returns empty under unpatched build**: the policy DSL
  rewriter probably evaluated the `unless` guard. Confirm by sending
  `expr=unless never allow private::<flag-id>` directly to
  `/api/policy/eval` and check for a 200 with `"decision":"allow"`.
