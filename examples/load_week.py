"""Load the example week (examples/pos/pos_2026-11-17 ... 23) into a running app through its API, as an admin.
The owner's own example day (24.11, his original file) is loaded separately by `python -m app.cli seed-example`.

    python examples/load_week.py [http://localhost:8080]       # admin password from .env INITIAL_ADMIN_PASSWORD
                                                                # or the BAR_ADMIN_PASSWORD environment variable

Meant for a fresh install with the kitchen products of migration 0006 and no POS reports for these days. It:
  * creates the location "Kitchen" if missing and sets example minimum stocks of the kitchen products;
  * posts three receipts WITHOUT prices (quantities only, owner's decision): 17.11 start, 19.11 and 21.11 refills;
  * uploads every day, sets the burger norms on first sight (175 g fries + 200 g meat, 400 g for the double,
    + 1 bun; the burger codes 9000xx are made-up examples), marks drinks "not kitchen" and writes the day off.
Receipts are sized so the stock never goes negative and a few products end the week below their minimum (red).
"""

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080").rstrip("/") + "/api/v1"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PREPARED = ["Minji", "Jun", "Sora", "Minji", "Hyun", "Jun", "Sora"]

# sku -> minimum stock in base units (g / pcs)
MINIMUMS = {"KIT-FRIES": 3000, "KIT-WINGS": 1000, "KIT-FISH": 3, "KIT-PHILLY-MEAT": 1000, "KIT-BURGER-MEAT": 1000,
            "KIT-PHILLY-BUN": 4, "KIT-BURGER-BUN": 5}
# date (05:00 KST, before the business day), [(sku, qty, unit)]
RECEIPTS = [
    ("2026-11-17", [("KIT-FRIES", "25", "kg"), ("KIT-WINGS", "5", "kg"), ("KIT-FISH", "16", "pcs"), ("KIT-PHILLY-MEAT", "15", "pack"),
                    ("KIT-BURGER-MEAT", "50", "pack"), ("KIT-PHILLY-BUN", "12", "pcs"), ("KIT-BURGER-BUN", "40", "pcs")]),
    ("2026-11-19", [("KIT-FRIES", "25", "kg"), ("KIT-WINGS", "8", "kg"), ("KIT-FISH", "30", "pcs"), ("KIT-PHILLY-MEAT", "20", "pack"),
                    ("KIT-BURGER-MEAT", "50", "pack"), ("KIT-PHILLY-BUN", "15", "pcs"), ("KIT-BURGER-BUN", "40", "pcs")]),
    ("2026-11-21", [("KIT-FRIES", "32", "kg"), ("KIT-WINGS", "6.4", "kg"), ("KIT-FISH", "31", "pcs"),
                    ("KIT-BURGER-MEAT", "60", "pack"), ("KIT-PHILLY-BUN", "10", "pcs"), ("KIT-BURGER-BUN", "40", "pcs")]),
]
BURGERS = {"900001": 200, "900002": 200, "900003": 400}  # grams of burger meat per portion


def password() -> str:
    if os.environ.get("BAR_ADMIN_PASSWORD"):
        return os.environ["BAR_ADMIN_PASSWORD"]
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("INITIAL_ADMIN_PASSWORD=") and line.split("=", 1)[1].strip():
            return line.split("=", 1)[1].strip()
    sys.exit("Set BAR_ADMIN_PASSWORD (the admin password)")


def call(method, path, body=None, token=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", ctype)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def ok(res, what):
    st, body = res
    if st >= 300:
        sys.exit(f"{what}: HTTP {st} {body}")
    return body


def main() -> None:
    tok = ok(call("POST", "/auth/login", {"username": "admin", "password": password()}), "login")["access_token"]
    locs = ok(call("GET", "/locations?active=active", token=tok), "locations")
    loc = next((x["id"] for x in locs if x["name"].lower() == "kitchen"), None)
    if loc is None:
        loc = ok(call("POST", "/locations", {"name": "Kitchen"}, token=tok), "location")["id"]
    prods = {p["sku"]: p["id"] for p in ok(call("GET", "/products?active=active&limit=1000", token=tok), "products")["items"]}
    for sku, minimum in MINIMUMS.items():
        ok(call("PATCH", f"/products/{prods[sku]}", {"min_stock_base": str(minimum)}, token=tok), f"minimum {sku}")

    receipts = dict(RECEIPTS)
    days = sorted((ROOT / "examples" / "pos").glob("pos_*.xlsx"))
    for n, f in enumerate(days):
        day = f.stem.split("_")[1]
        if day in receipts:
            lines = [{"product_id": prods[s], "location_id": loc, "qty": q, "qty_unit": u} for s, q, u in receipts[day]]
            ok(call("POST", "/receipts", {"id": str(uuid.uuid4()), "doc_date": f"{day}T05:00:00+09:00", "supplier": "Example supplier",
                                          "comment": "Example data (week)", "lines": lines}, token=tok), f"receipt {day}")
            print(f"{day}  receipt ({len(lines)} products)")
        q = f"?id={uuid.uuid4()}&sales_date={day}&file_name={f.name}&prepared_by={PREPARED[n % len(PREPARED)]}"
        imp = ok(call("POST", "/sales-imports" + q, raw=f.read_bytes(), token=tok, ctype=XLSX), f"upload {day}")
        items = {i["code"]: i for i in ok(call("GET", "/pos-items", token=tok), "pos items")}
        for line in imp["unmapped"]:
            meat = BURGERS.get(line["code"])
            if meat:
                comps = [{"product_id": prods["KIT-FRIES"], "qty": "175", "qty_unit": "g"},
                         {"product_id": prods["KIT-BURGER-MEAT"], "qty": str(meat), "qty_unit": "g"},
                         {"product_id": prods["KIT-BURGER-BUN"], "qty": "1", "qty_unit": "pcs"}]
                ok(call("PUT", f"/pos-items/{items[line['code']]['id']}", {"components": comps}, token=tok), f"norm {line['code']}")
        drinks = [items[x["code"]]["id"] for x in imp["unmapped"] if x["code"] not in BURGERS]
        if drinks:
            ok(call("POST", "/pos-items/not-kitchen", {"ids": drinks}, token=tok), "not kitchen")
        done = ok(call("POST", f"/sales-imports/{imp['id']}/post", {"document_id": str(uuid.uuid4()), "location_id": loc}, token=tok),
                  f"write-off {day}")
        print(f"{day}  POS day written off ({done['status']}), {len(done['items'])} products, prepared by {done['prepared_by']}")

    print("\nStock at the end:")
    for r in ok(call("GET", f"/stock?location_id={loc}", token=tok), "stock"):
        print(f"  {r['product_name']:<22} {r['qty_base']:>12} {'LOW' if r['is_low_stock'] else ''}")


if __name__ == "__main__":
    main()
