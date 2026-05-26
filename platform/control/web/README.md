# KosSim Web

React + Vite + TypeScript frontend for the KosSim control plane. Talks to the
FastAPI backend (`platform/control/app`) over `/api/v1/*` (public) and
`/admin/api/*` (operator) JSON endpoints.

## Setup

```bash
cd platform/control/web
npm ci
```

`npm ci` installs exactly what is in `package-lock.json`. Until you run it,
your editor will show "could not find declaration file" errors — that's expected.

## Develop

Start the FastAPI backend on `:8000` (from `platform/control`):

```bash
uvicorn app.main:app --reload --port 8000
```

Then start Vite:

```bash
cd platform/control/web
npm run dev
```

Vite serves on http://localhost:5173 and proxies `/api`, `/admin`,
`/static`, and `/health` to the backend (override with
`KOSSIM_BACKEND=http://...`).

### Routes

- `/public/scoreboard` — public scoreboard (frozen when the game is frozen)
- `/scoreboard` — internal scoreboard (includes NOP team)
- `/admin/login` — operator sign in
- `/admin` — dashboard (live stats + charts)
- `/admin/checkers` — service health, debounced search + per-column filters
- `/admin/flags` — flag inspector (HMAC decode) + recent stored flags
- `/admin/submissions` — every submit attempt, by-tick chart
- `/admin/game` — start / pause / stop / schedule (live tick countdown)
- `/admin/services` — enable/disable checker targets, segmented filter
- `/admin/logs` — event timeline with level + component filters

Search inputs are debounced (~200ms) and synced to the URL, so filtered
views are linkable and survive refresh.

## Auth

Auth uses the same `kossim_admin` session cookie that the legacy HTML admin
used. Logging in via `/admin/login` calls `POST /admin/api/login` and the
cookie is set automatically; the SPA includes it via `credentials:
"same-origin"` on every request.

## Build

```bash
npm run build
```

Outputs to `web/dist/`. The FastAPI runtime serves that directory through
the SPA catch-all, and the control Dockerfile builds it with `npm ci`.
