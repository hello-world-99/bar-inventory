# Bar Inventory

Web application for stock control and inventory counts in a small bar: products, storage locations, receipts, write-offs, transfers, inventory counts, daily POS sales import with kitchen norms, a stock chart per product and a full movement journal. Quantities only: no prices are shown.

- Requirements: [`docs/requirements.md`](docs/requirements.md) (English translation; the owner's original is [`docs/requirements.ru.md`](docs/requirements.ru.md))
- Architecture and agreed design decisions: [`docs/architecture.md`](docs/architecture.md)

## Quick start

**You need:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) on Windows or macOS, or Docker Engine with the Compose plugin on Linux (`docker compose version` must work). Nothing else: no Python, no Node.

```bash
git clone <this repository> bar-inventory
cd bar-inventory
```

| | Windows | Linux / macOS |
|---|---|---|
| Start (first run: creates `.env`, builds for a few minutes) | double-click **`start.bat`** | `./start.sh` |
| Load example data (optional, fresh install only) | double-click **`examples.bat`** | `./examples.sh` |
| Stop (data is kept) | **`stop.bat`** | `./stop.sh` |

1. **Start.** The first run creates `.env` with random secrets, builds and starts the app, and prints the first password for the user **`admin`**. On Windows it starts Docker Desktop if needed and opens the browser.
2. **Open** http://localhost:8080 and sign in as `admin` with that password.
3. **Change the password**: *Change password* at the bottom of the left menu. Then delete the value after `INITIAL_ADMIN_PASSWORD=` in `.env` (the start script keeps reminding you until you do).
4. **Set up:** staff accounts on the *Users* page; products and storage places in the catalog. The kitchen products and POS norms of the owner's bar come with the database.

Port 8080 is taken? Set `HTTP_PORT=` in `.env` before the first start (or later, then start again).

On Windows, turn on **"Start Docker Desktop when you sign in"** in Docker Desktop → Settings → General: the app then comes back by itself after a reboot. On Linux, enable the Docker service (`sudo systemctl enable --now docker`); the containers restart with it.

By default only this computer can open the app (`BIND_ADDR=127.0.0.1`). To use tablets on the bar's Wi-Fi, see the comments at `BIND_ADDR` in `.env.example`: they need `BIND_ADDR=0.0.0.0` **and** `COOKIE_SECURE=false`. Otherwise they are signed out every 15 minutes, because without HTTPS browsers keep the sign-in cookie only on `localhost`.

**Backups:** the app makes a backup every day into the `backups` folder next to this file (see "Backups"). That folder is on the same disk as the data. Copy it regularly to a USB stick or to a OneDrive / Google Drive folder — once a day if you can, at least once a week.

### Example data

`examples.bat` / `./examples.sh` fill a **fresh** install with a realistic picture, through the same API as the UI:

1. a week of POS days with receipts (`examples/pos/`), moved to the seven days before yesterday;
2. the owner's own POS day (`backend/app/examples/pos_day.xlsx`) for yesterday;
3. operations over the last nine hours that run some products low: a delivery to a *Freezer*, transfers, spoilage, a staff meal, breakage, a refill and a count with shortages. Some products end red (at or below the minimum), one at exactly zero.

It uses the `admin` password from `.env`, or asks for it. It refuses to run when the database already has POS reports.

### Start over with an empty database

**This deletes all data** (make a dump first if any of it matters, see "Backups"):

```bash
docker compose down -v      # stops the app and deletes its database volume
```

Then start again; to get a new first password too, delete `.env` before starting (a new one with new secrets is created). Do not delete `.env` while the old database volume still exists: the database keeps the password it was created with.

### Update to a new version

```bash
git pull
docker compose up -d --build     # or start.bat / ./start.sh
```

Database migrations run by themselves when the backend starts. A dump is made every day anyway; before a big update you can make one by hand (`docker compose exec backup pgtool dump`).

### Without the start scripts

```bash
cp .env.example .env          # then put random values into POSTGRES_PASSWORD, JWT_SECRET and INITIAL_ADMIN_PASSWORD
docker compose up -d --build
```

On first start the backend creates the administrator from `INITIAL_ADMIN_USERNAME` / `INITIAL_ADMIN_PASSWORD` if no users exist. Alternatively: `docker compose exec backend python -m app.cli create-admin <username>`.

## Daily POS sales (kitchen usage)

**Sales (POS)** in the menu: upload the POS "sales by item" report (`.xlsx`, exactly as exported) and choose its business day. The app computes the kitchen usage (fries, wings, fish, meat packs, buns) by the norms on the **POS norms** page and writes it off with **Write off from stock**. The write-off is dated at the start of that business day.

- **Upload each day's report before you complete a night count.** A count completed after the sales already contains them. The app then refuses to write those sales off, because they would be counted twice. Mark such a report as covered by that inventory instead. The count's completion dialog lists the days not written off yet.
- `business_day_starts_at` in Settings must lie between closing and the next opening (e.g. 06:00). A count made after midnight then still belongs to the same day.
- Before writing off, the used quantity (in g, ml or pcs) of each product can be corrected right in the report; the stock "after" is recalculated at once, and a correction shows up in the breakdown as "Manual correction". A written-off day can be corrected later too, also after an inventory.
- **Stock never goes below zero.** A day that sells more than the shelf has is refused with the product and the missing quantity: record the missing receipt or count the stock first.
- Products at or below their minimum stock (total over all places) are shown in red: in the report, on Stock and Products, and on the dashboard. Set the minimum in the product card.
- Items without a norm are listed on top of the report. An administrator sets a norm (there is a one-click burger preset) or marks drinks as "not kitchen". Changing a norm does not change reports already written off.
- A day can be written off only once, and the same sales cannot be uploaded under two dates. To redo a day, an administrator uses **Void & re-import**: the write-off is reversed.

Meat is counted in **packs** of 200 g, converted to grams: a count can be entered as "2 packs + 50 g". The pack size of a product is fixed after its first receipt or count; a pack of another size is a new product.

Click a product on **Stock** or **Products** for its card: stock by place and a chart of the stock at the end of each business day (7 / 30 / 90 days, with the minimum, and what came in and went out each day).

## Currency

The app shows quantities only (owner's decision). Prices and costs are still stored in **won** in the background, and the USD→KRW rate support is kept but hidden: the daily rate fetch is off (`RATE_AUTO_UPDATE=false`).

## Stack

FastAPI + SQLAlchemy 2 + PostgreSQL 16 (backend, `backend/`), React + TypeScript + Vite + Tailwind (frontend, `frontend/`), Docker Compose. The REST API (`/api/v1`, OpenAPI at `/api/docs`) is the contract for the web client and for a future mobile app or POS integration.

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
