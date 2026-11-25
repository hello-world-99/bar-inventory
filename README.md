# Bar Inventory

Web application for stock control and inventory counts in a small bar: products, storage locations, receipts, write-offs, transfers, inventory counts with discrepancy costing, and a full movement journal.

- Requirements: [`docs/requirements.md`](docs/requirements.md)
- Architecture and agreed design decisions: [`docs/architecture.md`](docs/architecture.md)

**Status:** MVP complete (stages 1–6). First delivery: one computer, local use. A VPS with HTTPS is described below for later.

## Install on one computer (Windows)

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it once. In its Settings → General, turn on **"Start Docker Desktop when you sign in"** so the app comes back by itself after a reboot.
2. Double-click **`start.bat`** in this folder.
   - The first run creates `.env` with random secrets, builds the app (a few minutes) and prints the first password for the user **`admin`**.
   - Then it opens http://localhost:8080 in the browser. Later runs only start it and open the browser.
3. Sign in as `admin` with that password, then **Change password** (bottom of the left menu).
4. Open `.env` in Notepad and delete the value after `INITIAL_ADMIN_PASSWORD=`.
5. Add staff accounts on the **Users** page, and products and locations in the catalog.

`stop.bat` stops the app; data is kept. Everything restarts by itself with Docker Desktop.

By default only this computer can open the app (`BIND_ADDR=127.0.0.1`). To use tablets on the bar's Wi-Fi, see the comments at `BIND_ADDR` in `.env.example`: they need `BIND_ADDR=0.0.0.0` **and** `COOKIE_SECURE=false`. Otherwise they are signed out every 15 minutes, because without HTTPS browsers keep the sign-in cookie only on `localhost`.

**Backups:** the app makes a backup every day into the `backups` folder next to this file (see "Backups"). That folder is on the same disk as the data. Copy it regularly to a USB stick or to a OneDrive / Google Drive folder — once a day if you can, at least once a week.

## Daily POS sales (kitchen usage)

**Sales (POS)** in the menu: upload the POS "sales by item" report (`.xlsx`, exactly as exported) and choose its business day. The app computes the kitchen usage (fries, wings, fish, meat packs, buns) by the norms on the **POS norms** page and writes it off with **Write off from stock**. The write-off is dated at the start of that business day.

- **Upload each day's report before you complete a night count.** A count completed after the sales already contains them. The app then refuses to write those sales off, because they would be counted twice. Mark such a report as covered by that inventory instead. The count's completion dialog lists the days not written off yet.
- `business_day_starts_at` in Settings must lie between closing and the next opening (e.g. 06:00). A count made after midnight then still belongs to the same day.
- Before writing off, the used quantity (in g, ml or pcs) and the price of each product can be corrected right in the report. The cost and the stock "after" are recalculated at once, and a correction shows up in the breakdown as "Manual correction".
- Products at or below their minimum stock are shown in red: in the report, on Stock and Products, and on the dashboard. Set the minimum in the product card.
- Items without a norm are listed on top of the report. An administrator sets a norm (there is a one-click burger preset) or marks drinks as "not kitchen". Changing a norm does not change reports already written off.
- A day can be written off only once, and the same sales cannot be uploaded under two dates. To redo a day, an administrator uses **Void & re-import**: the write-off is reversed.

Meat is counted in **packs** of 200 g, converted to grams: a count can be entered as "2 packs + 50 g". The pack size of a product is fixed after its first receipt or count; a pack of another size is a new product.

**Example data:** `docker compose exec backend python -m app.cli seed-example` loads one day of the owner's POS report on a fresh install:
- a receipt marked "Example data" to the kitchen;
- the day's report, with drinks marked "not kitchen";
- the write-off.

It refuses to run twice.

## Currency

Money is stored in **won**. **Settings → Currency** chooses how it is shown and typed in:
- **KRW** (default, no decimals);
- **USD**, at the won-per-dollar rate.

The rate is fetched once a day from the European Central Bank reference rates. The address is `RATE_URL` in `.env`; the request carries no data about the bar. You can also type the rate in (manual mode). If an update fails, the last rate is kept and the menu says so.

Changing the currency or the rate never changes stored numbers. A receipt priced in dollars is converted to won at the current rate, and the document keeps that rate. Past documents shown in dollars use today's rate. Rates by document date are not kept.

## Stack

FastAPI + SQLAlchemy 2 + PostgreSQL 16 (backend, `backend/`), React + TypeScript + Vite + Tailwind (frontend, `frontend/`), Docker Compose. The REST API (`/api/v1`, OpenAPI at `/api/docs`) is the contract for the web client and for a future mobile app or POS integration.

## Running without start.bat

Requires Docker (Docker Desktop on Windows/macOS).

```bash
cp .env.example .env          # then edit every secret in .env
docker compose up -d --build
```

Open http://localhost:8080. On first start the backend creates the administrator from `INITIAL_ADMIN_USERNAME` / `INITIAL_ADMIN_PASSWORD` if no users exist; remove the password from `.env` afterwards. Alternatively:

```bash
docker compose exec backend python -m app.cli create-admin <username>
```

## Production (VPS with HTTPS)

1. Point a DNS A record (e.g. `stock.mybar.com`) at the VPS. Open only ports 80 and 443 in its firewall.
2. In `.env`: `DOMAIN=stock.mybar.com`, `HTTP_PORT=80`, `COOKIE_SECURE=true`, fresh random secrets.
3. Start:
   ```sh
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
   ```
   Caddy (`deploy/Caddyfile`) gets and renews the Let's Encrypt certificate, redirects http:// to https:// and sends HSTS. Only Caddy publishes ports; `web`, `backend` and `db` are reachable only inside Docker.
4. Sign in as `admin`, change the password, then delete `INITIAL_ADMIN_PASSWORD` from `.env`.

Rate limiting keys on the client address: Caddy passes it in `X-Forwarded-For`, and `web` trusts that header only from Caddy's fixed address `172.31.250.10` (network `edge`, subnet `172.31.250.0/24`). If that subnet clashes with a network on the server, change it in both `docker-compose.prod.yml` and `frontend/nginx.conf`.

IPv6: do not create an AAAA record for the domain unless Docker is set up to keep IPv6 client addresses (`"ip6tables": true, "userland-proxy": false` in `/etc/docker/daemon.json`). Otherwise all IPv6 visitors share one address and one login rate-limit bucket.

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

**A copy on the same disk is not a backup.** Copy `./backups` off the server every day, for example with [rclone](https://rclone.org) to any cloud storage, from the host's crontab half an hour after `BACKUP_AT`:

```
30 4 * * * rclone copy /opt/bar-inventory/backups remote:bar-backups --max-age 48h
```

Restore a copy from elsewhere by putting the file into `./backups` and running `restore` below.

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

Once a week, run `docker compose ps`: the `backup` service turns **unhealthy** when no dump has succeeded for more than 26 hours (see `docker compose logs backup` for the reason).

`verify` and `restore` print row counts and `balance_mismatches`, which must be 0.
