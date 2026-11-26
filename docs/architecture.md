# Architecture — Bar Inventory

Status: agreed in `agent-room/discussion.md`, replies 1–53. Original specification: [`requirements.md`](requirements.md) (English translation) / [`requirements.ru.md`](requirements.ru.md) (owner's original).

## 1. Stack and deployment

| Layer | Choice |
|---|---|
| Backend | Python 3.13, FastAPI, **synchronous** SQLAlchemy 2.0 + psycopg 3, Alembic, Pydantic v2 |
| Database | PostgreSQL 16 |
| Frontend | React 18 + TypeScript + Vite, TanStack Query/Table, React Router, i18next, Tailwind CSS, `big.js` for quantity and money arithmetic |
| Auth | argon2; JWT access token (15 min, kept in client memory) + refresh token in an `HttpOnly; SameSite=Strict; Path=/api/v1/auth` cookie; the `Secure` flag comes from env `COOKIE_SECURE` (default `true`; `false` only for plain HTTP on a LAN) |
| Infrastructure | Docker Compose: `db`; `backend` (uvicorn, **1 worker**: the login rate limit is in memory); `web` (multi-stage node → nginx; nginx proxies `/api`, so there is one origin); `backup` (`pgtool`, section 9) |
| Tests | pytest against a real Postgres: database `<POSTGRES_DB>_test` in the same `db` service, run through `docker-compose.test.yml` (profile `test`). `conftest` refuses any database whose name does not end in `_test`. Vitest for the frontend |

**Deployment** (owner's decisions):
- **First delivery: one computer, local** (reply 25). `start.bat` / `scripts/start.ps1`:
  - creates `.env` with random secrets;
  - starts Docker Desktop;
  - runs `docker compose up -d --build`;
  - prints the first `admin` password while it is still in `.env`.

  The web port is bound to `${BIND_ADDR:-127.0.0.1}:${HTTP_PORT:-8080}`.
- **Later: a VPS with HTTPS.** `docker-compose.prod.yml` adds Caddy (automatic Let's Encrypt, HSTS) on ports 80/443. `web` then has no public port. nginx trusts `X-Forwarded-For` only from Caddy's fixed address on the `edge` network.

Nothing in the code assumes localhost. Client UUIDs come from `crypto.getRandomValues`, which works outside a secure context too, not from `crypto.randomUUID`.

The API is REST under `/api/v1/...`. FastAPI generates OpenAPI, which is the contract for a future mobile app or POS integration. `Decimal` values travel in JSON **as strings**.

## 2. Units of measure

A product has three fields:

- `base_unit` ∈ `ml | g | pcs` — the unit every quantity is stored in (`qty_base`, `NUMERIC(14,3)`).
- `unit` ∈ `pcs | bottle | pack | l | ml | kg | g` — the product's own unit: purchases, the price and the default display use it.
- `unit_size` — how many `base_unit` one `unit` holds.

| unit | base_unit | unit_size |
|---|---|---|
| ml | ml | 1 (fixed) |
| l | ml | 1000 (fixed) |
| bottle | ml | set per product (e.g. 700) |
| pack | g | set per product (e.g. 200; reply 37: meat is counted in packs and converted to grams) |
| g | g | 1 (fixed) |
| kg | g | 1000 (fixed) |
| pcs | pcs | 1 (fixed) |

Invariants:

- `bottle` and `pack` are **containers**:
  - their size is required;
  - a container unit is accepted only for products counted in it (`CONTAINERS` in `core/units.py` and `lib/units.ts`).
- `purchase_price` is the price of one `unit` (bottle, pack, kg, piece), **in won** (section 10).
- `min_stock_base` is stored in base units and applies to the **total over all locations**.
  - "Low stock" = `min_stock_base > 0 AND Σ qty_base ≤ min_stock_base`. The minimum is a reorder point; `0` means not tracked.
  - The same rule is used everywhere: products list, stock rows, dashboard and POS report. Such products are shown in red (owner, 2026-11-25).
- `base_unit`, `unit` and `unit_size` become **read-only once the product appears in movements, document lines (drafts included) or count lines** (409). Otherwise changing bottle → kg would turn stored ml into g. To fix a unit, create a new product and deactivate the old one: SKU and barcode are unique among active products only.
- Quantities are entered in `unit` or in the base or metric unit of the same base; the server converts `qty` + `qty_unit` into `qty_base`.
- **Partly used containers:**
  - a count is entered as "N full + X in the open one"; `N·unit_size + X` is stored;
  - display: "2 btl + 350 ml (2.5 btl)" or "2 pcs + 50 g (450 g)". The short label of a pack is "pcs" (owner).
- Reserved for weighing: nullable `full_weight_g` and `empty_weight_g`.

## 3. Data model

```
categories(id, code NULL UNIQUE, name, is_active)     -- seed: the 5 categories of the spec + 'kitchen' (code = i18n key)
products(id, name, sku, category_id, unit, base_unit, unit_size,
         purchase_price NUMERIC(14,2) -- won, price_updated_at, min_stock_base, barcode NULL,
         full_weight_g NULL, empty_weight_g NULL, is_active, created_at, updated_at)
   -- UNIQUE(lower(sku)) WHERE is_active; UNIQUE(barcode) WHERE is_active AND barcode IS NOT NULL
locations(id, name, description, is_active)          -- UNIQUE(lower(name)) WHERE is_active
users(id, username, full_name, password_hash, role admin|staff, is_active, token_version)
settings(id=1, venue_name, currency KRW|USD, currency_decimals, timezone, business_day_starts_at, blind_count,
         usd_krw_rate NULL, rate_mode auto|manual, rate_source, rate_date, rate_updated_at, rate_checked_at, rate_error)

stock_balances(product_id, location_id, qty_base)  PK(product_id, location_id)
   -- cache of the journal; invariant: qty_base = SUM(stock_movements.delta_base) of the pair

stock_documents(id UUID generated by the client, type receipt|write_off|transfer|inventory_adjustment|reversal,
         status draft|posted, doc_date timestamptz, reason NULL, supplier NULL, invoice_no NULL, comment,
         reversal_of NULL UNIQUE, request_hash NULL, allow_negative, backdate_confirmed,
         price_rate NULL       -- receipts priced in dollars: the won-per-dollar rate used
         sales_import_id NULL  -- compensation of a POS report corrected after a count (section 11)
         created_by, created_at, posted_by, posted_at)
   -- CHECK: reason required ⇔ type='write_off' (reasons incl. 'sales', set only by the POS import);
   --        reversal_of required ⇔ type='reversal'
stock_document_lines(id, document_id, line_no, product_id, location_from_id NULL, location_to_id NULL,
         qty_base NUMERIC(14,3),                 -- > 0, except inventory_adjustment (signed, ≠ 0)
         unit_price NUMERIC(14,2) NULL,          -- receipt: price per unit in won
         unit_cost_base NUMERIC(18,6))
stock_movements(id, document_id, product_id, location_id, delta_base, unit_cost_base NOT NULL,
         balance_after, doc_date, created_at, user_id)   -- append-only (trigger)
   -- doc_date: the business date (journal filters, counts); created_at: posting order
   -- INDEX(product_id, location_id, doc_date)

inventories(id, location_id, status in_progress|completed|cancelled, started_by, started_at,
         completed_by, completed_at, comment, adjustment_document_id NULL UNIQUE)
   -- partial UNIQUE(location_id) WHERE status='in_progress'
inventory_lines(id, inventory_id, product_id, UNIQUE(inventory_id, product_id),
         expected_at_start_base, counted_base NULL, expected_at_count_base NULL, counted_at NULL, counted_by NULL,
         unit_cost_base NULL, version)

-- POS sales import (section 11)
pos_items(id, code UNIQUE, name, not_kitchen, updated_at)
pos_item_components(pos_item_id, product_id, qty_base > 0)        -- the norm: one sold unit uses qty_base
sales_imports(id UUID, sales_date, file_name, file_sha256, content_sha256, status draft|posted|covered|voided,
         total_qty, total_revenue, warnings jsonb, location_id, write_off_id UNIQUE, covered_inventory_id,
         post_request_id, prepared_by, uploaded_by, uploaded_at, closed_by, closed_at)
   -- UNIQUE(sales_date) and UNIQUE(content_sha256) WHERE status <> 'voided'
sales_import_lines(id, import_id, line_no, pos_code, pos_name, qty, revenue)   -- UNIQUE(import_id, pos_code)
sales_import_usage(id, import_id, pos_code, pos_name, sold_qty, product_id, per_unit_base, qty_base,
         covered_inventory_id, covered_at, unit_cost_base)   -- snapshot taken when the report is closed
```

## 4. Posting documents

One transaction:

1. **Locks.**
   - The document's products: `SELECT … FROM products WHERE id IN (…) ORDER BY id FOR SHARE` (`FOR UPDATE` for receipts, which update the price). Postings do not block each other but serialize with product updates, so `unit_size` cannot change between reading it and writing the first movement.
   - Then, for every affected `(product_id, location_id)` pair: `INSERT … ON CONFLICT DO NOTHING` and `SELECT … FOR UPDATE` **ordered by (product_id, location_id)**.
   - **The lock order is the same everywhere:** POS report row / count row (if involved) → products → count lines / balances. So there are no deadlocks.
2. **Checks that depend on other transactions** (backdate, absorption A1 of reversals, POS coverage) run **after the balance locks** (`pre_check` in `_post`). Completing a count locks the same rows before writing `status='completed'`, so under READ COMMITTED the check sees a committed completion (no TOCTOU).
3. **Negative stock check** (write-off, transfer, reversal):
   - everyone → 422;
   - nobody can override it (owner, reply 96: a bar cannot have less than nothing): the error names each product, place, what is in stock and what is needed, and says to post the missing receipt or count first. `allow_negative` in requests is ignored; documents posted earlier with it keep the flag. A POS day that sells more than the shelf has stays a draft until then;
   - count adjustments and POS compensations are exempt.
4. **The document is flipped to posted.** Lines are written to a draft, then `UPDATE … SET status='posted' WHERE status='draft'`; 0 rows → 409. Triggers make posted documents and their lines immutable.
5. **Balances are updated** and movements written, with the `unit_cost_base` snapshot, the document's `doc_date` and `created_at = now()`.

`posted_at` and `completed_at` use `clock_timestamp()` taken after the locks, not `now()` (the transaction start): A1 depends on their order (reply 17).

**Document date:**
- in the future (more than `now()` + 5 min of clock skew) → 422 `future_date`;
- older than a year → 422 `date_too_old`.

**Backdating is checked per (product, location) pair.** A document conflicts only if a completed count **counted** the pair with `counted_at ≥ doc_date`:
- staff → 422 `backdate_forbidden`;
- admin → 422 `backdate_confirmation_required` without `confirm_backdate=true`; with the flag the document posts and is marked `backdate_confirmed`.

**Limits:** a line ≤ 10⁹ base units, a balance ≤ 99 999 999 999.999 → otherwise 422 `qty_too_large`. Any `DataError` → 422, never 500.

**Idempotency:** the client generates the document UUID.
- The same id with the same body (sha256 of the canonical request) → the existing document, 200.
- The same id with a different body → 409.

**`unit_cost_base` of a movement:**
- receipt — `unit_price / unit_size`;
- others — the current `purchase_price / unit_size`;
- reversal — the original's costs;
- POS write-off — the price typed in the report by an admin, if any (section 11).

A receipt updates `purchase_price` only if `doc_date ≥ price_updated_at`.

**Valuation:**

| What | How |
|---|---|
| Stock value (dashboard, stock) | Σ `qty_base × purchase_price / unit_size` at the **current** price |
| Journal, documents, completed counts | from `unit_cost_base` of movements and lines (historical snapshot) |
| Discrepancies of a count in progress | current price; the price is frozen into the line on completion |

Money is rounded only for display (section 10).

**Corrections — reversal (admin) of a posted receipt, write-off or transfer.** It creates a `reversal` document with mirrored movements and `reversal_of` (unique: a second reversal → 409).
- **A1:** 409 `counted_after` if a completed count absorbed the document, i.e. `completed_at > posted_at` and the pair was counted with `counted_at ≥` the original's `doc_date`.
- **The reversal carries the original's `doc_date`:** it fixes a record rather than describing a new event.
- A POS report's write-off can **not** be reversed from the journal (409 `use_sales_report`). It is corrected or voided on its report (section 11).
- Count adjustments are not reversible; they are corrected by a new count.

## 5. Inventory counts

- **Start** — one count in progress per location. Lines: every active product with a balance row at the location (zero and negative included) + `expected_at_start_base`. Products found on the shelf can be added.
- **Counting a line:** the client sends `parts` (e.g. full bottles + open ml), `counted_at` (when the person tapped "counted", possibly offline) and `sent_at`.
  - The server removes the device clock skew: `counted_at += server_now − sent_at`.
  - Then it clamps the result to `[started_at, now()]`.
  - Line `version` → 409 on concurrent overwrite.
  - The offline queue of the device keeps every entry until the server answers definitively.
- **Expected quantity at the moment of counting** is computed from event dates, not entry dates: `expected_at_count_base = Σ delta_base of the pair with doc_date ≤ counted_at`.
  - It is shown when the line is entered.
  - It is computed again on completion under the balance locks.
- **Blind count:** `settings.blind_count` hides expected values from staff. It is a hint for honesty, not security.
- **Completion** (admin), one transaction:
  1. count row `FOR UPDATE`;
  2. products `FOR SHARE`;
  3. counted balances `FOR UPDATE`;
  4. `completed_at = clock_timestamp()`;
  5. optional "uncounted = zero";
  6. expected values;
  7. an `inventory_adjustment` document with `delta = counted − expected` at `doc_date = completed_at` (no negative check);
  8. status `completed`.
- **Cancel** (admin): stock unchanged.
- **Why this formula:**
  - counter-examples A and B (reply 2);
  - offline entry (reply 4);
  - a reversal during a count and a backdated receipt during a count (reply 15).
- **Before completing,** the dialog lists the business days without a written-off POS report at this location (section 11). Their sales would otherwise read as a shortage.

## 6. Permissions (`backend/app/core/permissions.py`, single place)

| Action | admin | staff |
|---|---|---|
| Dashboard, stock, catalog (view), journal, POS reports (view) | ✔ | ✔ |
| Catalog, categories, locations, **POS norms**: create / edit / deactivate | ✔ | — |
| Receipt: create and post | ✔ | ✔ |
| Write-off: create and post (reason required) | ✔ | ✔ posted immediately (owner, reply 21), no negative stock |
| Transfer | ✔ | ✔ (no negative stock) |
| Reverse a document | ✔ | — |
| **POS report: upload, write off, correct quantities before writing off, sign a draft** | ✔ | ✔ |
| **POS report: change prices, correct or void a written-off day, sign a closed report** | ✔ | — |
| Count: start, enter quantities | ✔ | ✔ (expected hidden if `blind_count`) |
| Posting backdated before a count | ✔ (`confirm_backdate`) | — |
| Count: see discrepancies, complete, cancel | ✔ | — |
| Users, settings (currency, rate) | ✔ | — |

Administrators are protected: you cannot deactivate or demote yourself or the last active admin (409).

## 7. Time

`timestamptz` (UTC) everywhere; displayed in `settings.timezone`. The installation uses **Asia/Seoul** (owner).

The business day starts at `settings.business_day_starts_at` (06:00). It is used in filters, the dashboard and POS reports. A count after midnight still belongs to the same day.

## 8. Security

- **First admin:** created from env on first start (`INITIAL_ADMIN_PASSWORD`, printed by `start.bat` until removed from `.env`) or by `python -m app.cli create-admin`. No hard-coded passwords.
- **Login rate limit** (in memory, one backend instance): 10 failures per 5 min per (IP, username) and 30 per 15 min per username.
  - The IP comes from `X-Forwarded-For`, which nginx overwrites with `$remote_addr`. Behind Caddy, nginx trusts only Caddy's address.
  - `/auth/change-password` is limited the same way per user.
- **Own password** changes only through `/auth/change-password`, which re-issues the session tokens. `token_version++` revokes refresh tokens on deactivation or password change.
- **POS files are untrusted** (section 11): size limits, streaming XML parse, no DTD, no formulas.
- **Exchange rate request** (section 10): HTTPS only, at most 2 HTTPS redirects, a capped response, strict parsing. It carries no data about the bar.
- No CORS (one origin).

## 9. Backups

Service `backup` (`backup/pgtool.sh`, image `postgres:16-alpine`):
- `daemon` — a daily `pg_dump -Fc` at `BACKUP_AT` (`HH:MM`, time zone `TZ`) into `./backups`:
  - written to `.partial` and checked with `pg_restore --list` before it counts;
  - rotation keeps 14 days, but never fewer than the 7 newest dumps;
  - healthcheck: unhealthy without a successful dump in the last 26 hours.
- Commands:
  - `dump`, `list`;
  - `verify FILE` — restore into a scratch database, print row counts and journal mismatches;
  - `restore FILE --yes` — restore into a new database and swap it in by rename; the previous database is kept as `<db>_before_<timestamp>`.

The README warns that a copy on the same disk is not a backup. Copy `backups/` elsewhere.

## 10. Currency (replies 33–35)

> **Hidden for now (owner, 2026-11-26, replies 68–69):** the app tracks quantities only. Prices, money totals, the currency choice and the exchange rate are not shown anywhere, and the rate fetch is off (`RATE_AUTO_UPDATE=false` by default). The code and the stored data stay, so this can come back; the section below describes it as built.

**Storage.** All money is stored in **won**: prices, costs, movements and sums. Changing the currency or the rate never changes a stored number.

**Display.**
- `settings.currency` is the **display** currency:
  - `KRW` — the default, 0 decimals;
  - `USD` — amounts shown as won / `usd_krw_rate`, 2 decimals.
- Decimals follow the currency; the server sets them.
- The conversion happens in one place: `moneyFormat` / `useCurrency` / `useMoney` in `frontend/src/lib/format.ts`.
- The menu shows the rate in use and its date, and "update failed" when the last fetch failed.

**Exchange rate.**
- `rate_mode=auto`: a background thread in the FastAPI lifespan checks hourly and fetches when the rate is a day old (an hour after a failure). It also fetches on "Update now".
  - **Source:** `RATE_URL`, default Frankfurter, ECB reference rates: free, no key, HTTPS.
  - **Validation:** timeout 8 s, response ≤ 64 KB, exactly `rates.KRW` as a number within 500…5000.
  - **On failure** the last rate is kept and `rate_error` recorded.
  - **The write** is one `UPDATE … WHERE rate_mode='auto'`, safe with several workers.
- `rate_mode=manual`: the admin types the rate (100…100000); the automatic update never overwrites it.
- `USD` without a rate → 422 `rate_required`.

**Prices typed in dollars.**
- Receipts and the product card send `price_currency`.
- The server multiplies by the current rate and rounds to whole won.
- A receipt keeps the rate in `price_rate`.
- The product card sends a price only when it changed, so there is no rounding drift.

Past documents shown in USD use today's rate; rates by date are not kept.

## 11. POS sales import (replies 30–52)

The owner uploads the POS daily "sales by item" report (`.xlsx`). The app computes the kitchen usage by norms and writes it off from stock.

**Parser** (`services/pos_xlsx.py`, standard library only):
- **Limits on the file:**
  - file ≤ 2 MB, ≤ 50 zip parts;
  - every part read in chunks, ≤ 4 MB unpacked — zip bombs are cut by actual size, not the declared one.
- **Streaming parse** of every XML part with expat, with limits enforced while parsing:
  - ≤ 5000 rows, ≤ 64 cells per row, ≤ 1024 characters per cell;
  - DTD and entity declarations refused in any encoding, external entities never resolved.
- **Columns** are found by the report's literal Korean headers: `상품코드` (code), `상품명` (name), `수량` (quantity), optional `실매출` (revenue). The total row `합계` is skipped and checked against the sum.
- **Rows:**
  - formulas in used cells are refused;
  - rows with the same code are summed before negative totals are clamped;
  - codes written as numbers are matched to known codes by digits.
- **Errors** are 422 with a code: `bad_file`, `file_too_large`, `missing_columns`, `formula_not_allowed`, `bad_qty`, `bad_row`, `empty_report`.
- The upload is the raw body (no multipart).

**Norms.**
- `pos_items` + `pos_item_components` are data, edited by an admin (page "POS norms").
- An item can be marked "not kitchen" (drinks).
- Seeded by migration 0006 with the owner's norms:
  - Fries 350 g, Half Fries 175 g;
  - Fish & Chips 200 g fries + 1 fish;
  - Full wings 400 g, Half wings 200 g;
  - Philly 200 g meat + 1 bun.
- The burger (175 g fries + 200 g meat + 1 bun) is a one-click preset; its POS code is unknown yet.

**Report** (`sales_imports`):
- one active report per business day and per content hash — both are unique indexes;
- a draft follows the current norms; closing it freezes the usage snapshot;
- items without a norm are listed on top; writing off needs `acknowledge_unmapped`;
- `prepared_by` is free text (default: the user's name), editable without touching stock.

**Write-off (`post`)** — an ordinary `write_off` with reason `sales`, dated at the **start** of the sales business day.
- Under the balance locks, every product that a completed count at that location counted at or after that moment is **covered**: it is skipped and marked, because the count already contains the sales.
- Nothing left to write off → status `covered`, no document.
- Before writing off, quantities can be corrected in the report (difference kept as a "Manual correction" part), prices by an admin only.

**Correct and void a written-off day** — one procedure, `_rewrite(old, target)`; void is `target = {}`.
1. Lock the report, the products, then the balances.
2. Find the covered products.
3. Reverse the old write-off. The absorption check is skipped because the counted pairs are compensated.
4. For every covered product, post a compensation `target − old`: an `inventory_adjustment` with `sales_import_id`, dated at the earliest affected `counted_at`. That date is ≥ the start of the day and ≤ every affected count.
5. Post the new write-off at the start of the day (none for a void).

Every completed count therefore still sees exactly what it saw (`Σ movements ≤ counted_at = expected_at_count_base`), and the stock after it stays as counted. Only the split between "sales" and "count shortage" changes.

**Pending days.** `GET /sales-imports/pending-days?location_id=` lists the business days after the last closed report at a location. It is shown before completing a count.

**Example data:**
- `python -m app.cli seed-example` — one POS day from the owner's file with a receipt.
- `examples/pos/` — a generated week (17–23.11), followed on the live install by the owner's own day 24.11 (`seed-example`, unchanged): kitchen items with made-up burger codes `9000xx`, weekend peaks, a few drinks.
- `examples/load_week.py` — loads that week through the API: receipts without prices (17.11, then 19.11 and 21.11 refills), burger norms, drinks as "not kitchen", write-offs. A few products end the week in red. By default the week is moved to the seven business days before yesterday (`--original-dates` keeps 17–23.11), so a new install gets recent dates.
- `examples/load_low_stock.py` — operations over the last nine hours: a delivery to a *Freezer*, transfers, spoilage, a staff meal, breakage, a refill and a count with shortages; quantities relative to the stock, never below zero.
- `examples/load_examples.py` — all three in order (week, `seed-example` for yesterday, low stock); run by `examples.bat` / `examples.sh` in a one-off backend container (`docker compose run --rm --no-deps -v ./examples:/examples:ro backend …`), so the computer needs only Docker. Refuses when POS reports exist.

## 12. Frontend

- **Sidebar:**
  - Dashboard, Stock;
  - Operations — Receipts, Write-offs, Transfers, Inventory, **Sales (POS)**, Journal;
  - Catalog — Products, Locations, **POS norms**;
  - Administration — Users, Settings (admin).
- **i18n:** every string is a key (English), enums through keys, numbers and dates through `Intl`. Product names are not translated. Russian and Korean can be added as locale files later.
- **Count lines** are queued in `localStorage` per user and entry (`entryId`) and resent after a lost connection; sign-out warns about unsent counts.
- **Low stock** is red on Stock, Products, the dashboard and in the POS report ("running out").

## 13. Invariant tests

- Two parallel write-offs of the last bottle: one passes, the other gets 422.
- Counts: cases A and B, offline entry, a reversal and a backdated receipt during a count.
- Double posting and a retried POST with the same UUID; double completion of a count.
- A reversal waiting for the balance locks while a count completes → 409 (A1 TOCTOU).
- Posting against a concurrent `unit_size` change.
- Backdating before a count: staff 422; admin without `confirm_backdate` → 422.
- The last admin and yourself cannot be deactivated or demoted.
- **POS:**
  - parser on the owner's file and on broken, bloated and hostile files;
  - reference usage;
  - same day twice and the same sales under another date;
  - double click;
  - per-product coverage;
  - correct and void before and after a count with `counts_hold`;
  - no journal reversal of POS write-offs;
  - prices by admin only.
- **Currency:** won by default, `rate_required`, rate failures keep the last rate, dollar prices stored in won, no stored number changes with the currency or the rate.
- After every scenario: `SUM(movements) = balances`; admin endpoint `/stock/reconcile`.
