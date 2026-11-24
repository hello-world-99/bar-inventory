# Bar Inventory

Web application for stock control and inventory counts in a small bar: products, storage locations, receipts, write-offs, transfers, inventory counts with discrepancy costing, and a full movement journal.

- Requirements: [`docs/requirements.md`](docs/requirements.md)
- Architecture and agreed design decisions: [`docs/architecture.md`](docs/architecture.md)

**Status:** stage 2 of 6 — catalog and storage locations (stage 1: authentication, users, settings).

## Stack

FastAPI + SQLAlchemy 2 + PostgreSQL 16 (backend, `backend/`), React + TypeScript + Vite + Tailwind (frontend, `frontend/`), Docker Compose. The REST API (`/api/v1`, OpenAPI at `/api/docs`) is the contract for the web client and for a future mobile app or POS integration.

## Running

Requires Docker (Docker Desktop on Windows/macOS).

```bash
cp .env.example .env          # then edit every secret in .env
docker compose up -d --build
```

Open http://localhost:8080. On first start the backend creates the administrator from `INITIAL_ADMIN_USERNAME` / `INITIAL_ADMIN_PASSWORD` if no users exist; remove the password from `.env` afterwards. Alternatively:

```bash
docker compose exec backend python -m app.cli create-admin <username>
```

### HTTPS vs. local network

Sign-in uses a refresh cookie. With `COOKIE_SECURE=true` (default) browsers only keep it over HTTPS or on `http://localhost`.

- **Server with a domain and HTTPS:** keep `COOKIE_SECURE=true`.
- **Mini-PC in the bar, tablets open `http://192.168.x.x:8080`:** set `COOKIE_SECURE=false`, otherwise tablets are signed out every 15 minutes. Only do this on a trusted network.

## Tests

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm tests
```

Tests use a separate database `<POSTGRES_DB>_test` on the same Postgres server and refuse to run against any database whose name does not end in `_test`.
Each run truncates that database, so two runs at the same time (for example a developer and CI) must not share it: give the second one its own, e.g. `-e TEST_DATABASE_URL=postgresql+psycopg://…/bar_ci_test`.

Frontend type check, unit tests and build (no local Node needed):

```bash
docker run --rm -v "$PWD/frontend:/app" -v bar-web-nm:/app/node_modules -w /app node:22-alpine   sh -c "npm ci && npm run typecheck && npm test && npx vite build"
```

When testing login limits against a running instance, use non-existent usernames: behind Docker Desktop all clients share one source address, so failed attempts for a real user lock that user out on every device for 5 minutes.

## Backups

The `backup` service dumps the database every day at `BACKUP_AT` (time zone `TZ`, default 04:00 UTC) into `./backups` on the host, and once on start if the newest dump is older than a day. Each dump is checked to be a readable archive before it counts. Dumps older than `BACKUP_KEEP_DAYS` (14) are deleted, but the newest 7 are always kept.

**A copy on the same disk is not a backup.** Copy `./backups` somewhere else regularly (a USB drive, a cloud folder).

```sh
docker compose exec backup pgtool dump                 # make a dump now
docker compose exec backup pgtool list
docker compose exec backup pgtool verify bar-20261125-040000.dump   # restore into a scratch database, show row counts, drop it
```

Restore (replaces the live data; the current database is kept under a `bar_before_<time>` name until you drop it):

```sh
docker compose stop backend
docker compose exec backup pgtool restore bar-20261125-040000.dump --yes
docker compose start backend
```

`verify` and `restore` print row counts and `balance_mismatches`, which must be 0.
