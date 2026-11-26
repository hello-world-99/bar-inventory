"""Example operations that show stock running low (owner, reply 96): spoilage, staff meals, breakage, transfers from a
freezer, refills that bring a product back to normal and a count with shortages. Ends with some products LOW (at or
below the minimum), one at exactly zero and NONE below zero.

    python examples/load_low_stock.py [http://localhost:8080]     # admin password as for examples/load_week.py

Run after examples/load_week.py and the owner's day (seed-example). The operations are dated today (business day of
the installation) between 07:00 and 16:00 KST, so the current time must be past 16:00; the closing count is done now.
Some quantities are relative to the stock at the moment of the run (buns down to 4, Philly meat down to its minimum).
Document ids are fixed per day (uuid5): a second run on the same day stops at once and changes nothing.
"""

import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from load_week import call, ok, password

KST = timezone(timedelta(hours=9))
NS = uuid.UUID("6f0c3a52-2c61-4c55-9a3b-1a7a0b4e9d01")
COMMENT = "Example data (low stock)"


def doc_id(name: str, day: str) -> str:
    return str(uuid.uuid5(NS, f"{day}/{name}"))


def main() -> None:
    tok = ok(call("POST", "/auth/login", {"username": "admin", "password": password()}), "login")["access_token"]
    now = datetime.now(KST)
    if now.hour < 16:
        sys.exit("Run after 16:00 KST: the example operations are dated today 07:00-16:00")
    day = now.date().isoformat()

    def at(hh: int) -> str:
        return f"{day}T{hh:02d}:00:00+09:00"

    if call("GET", f"/documents/{doc_id('receipt to the freezer', day)}", token=tok)[0] == 200:
        sys.exit(f"The low-stock example is already loaded for {day}")

    locs = {x["name"]: x["id"] for x in ok(call("GET", "/locations?active=active", token=tok), "locations")}
    kitchen = locs["Kitchen"]
    freezer = locs.get("Freezer") or ok(call("POST", "/locations", {"name": "Freezer"}, token=tok), "location")["id"]
    prods = {p["sku"]: p for p in ok(call("GET", "/products?active=active&limit=1000", token=tok), "products")["items"]}
    pid = {s: p["id"] for s, p in prods.items()}

    def stock(sku: str, loc: int) -> Decimal:
        rows = ok(call("GET", f"/stock?location_id={loc}&include_zero=true", token=tok), "stock")
        return next((Decimal(r["qty_base"]) for r in rows if r["product_id"] == pid[sku]), Decimal(0))

    def post(path: str, name: str, body: dict) -> None:
        r = ok(call("POST", path, {"id": doc_id(name, day), "comment": COMMENT, **body}, token=tok), name)
        print(f"{datetime.fromisoformat(r['doc_date']).astimezone(KST):%H:%M}  {name}")

    def line(sku, qty, unit, loc=None):
        x = {"product_id": pid[sku], "qty": str(qty), "qty_unit": unit}
        return x | ({"location_id": loc} if loc else {})

    # 07:00 a delivery goes to the freezer, 08:00 part of it moves to the kitchen
    post("/receipts", "receipt to the freezer", {"doc_date": at(7), "supplier": "Example supplier", "lines": [
        line("KIT-FRIES", 20, "kg", freezer), line("KIT-BURGER-MEAT", 20, "pack", freezer), line("KIT-WINGS", 5, "kg", freezer)]})
    post("/transfers", "freezer to kitchen", {"doc_date": at(8), "from_location_id": freezer, "to_location_id": kitchen,
                                               "lines": [line("KIT-FRIES", 5, "kg"), line("KIT-BURGER-MEAT", 5, "pack")]})
    # 09:00-11:00 losses in the kitchen
    post("/write-offs", "spoilage: fish", {"doc_date": at(9), "reason": "spoilage", "lines": [line("KIT-FISH", 4, "pcs", kitchen)]})
    post("/write-offs", "staff meal", {"doc_date": at(10), "reason": "staff_use", "lines": [
        line("KIT-PHILLY-MEAT", 3, "pack", kitchen), line("KIT-BURGER-MEAT", 2, "pack", kitchen)]})
    # burger buns down to 4 (minimum 5): LOW
    bun = stock("KIT-BURGER-BUN", kitchen)
    if bun > 4:
        post("/write-offs", "breakage: burger buns", {"doc_date": at(11), "reason": "breakage",
                                                      "lines": [line("KIT-BURGER-BUN", bun - 4, "pcs", kitchen)]})
    # 13:00 Philly meat down to exactly its minimum (LOW), 15:00 the refill brings it back to normal
    meat = stock("KIT-PHILLY-MEAT", kitchen)
    minimum = Decimal(prods["KIT-PHILLY-MEAT"]["min_stock_base"])
    if meat > minimum:
        post("/write-offs", "spoilage: Philly meat", {"doc_date": at(13), "reason": "spoilage",
                                                      "lines": [line("KIT-PHILLY-MEAT", meat - minimum, "g", kitchen)]})
    post("/receipts", "refill: Philly meat", {"doc_date": at(15), "supplier": "Example supplier",
                                              "lines": [line("KIT-PHILLY-MEAT", 10, "pack", kitchen)]})
    post("/transfers", "freezer to kitchen: wings", {"doc_date": at(16), "from_location_id": freezer, "to_location_id": kitchen,
                                                      "lines": [line("KIT-WINGS", 2, "kg")]})

    # now: a count in the kitchen with shortages: Philly buns 3 (minimum 4), no fish left, 500 g of wings missing
    # the count is done now, after every document above (a backdated document after it would need confirming)
    inv = ok(call("POST", "/inventories", {"location_id": kitchen, "comment": COMMENT}, token=tok), "start count")
    wings = stock("KIT-WINGS", kitchen) - 500
    for sku, qty, unit in (("KIT-PHILLY-BUN", 3, "pcs"), ("KIT-FISH", 0, "pcs"), ("KIT-WINGS", wings, "g")):
        ok(call("PUT", f"/inventories/{inv['id']}/lines/{pid[sku]}", {"parts": [{"qty": str(qty), "qty_unit": unit}]}, token=tok),
           f"count {sku}")
    ok(call("POST", f"/inventories/{inv['id']}/complete", {}, token=tok), "complete count")
    print("now    count in the kitchen: Philly buns 3, fish 0, wings -500 g")

    print("\nStock at the end:")
    for r in ok(call("GET", "/stock?include_zero=true", token=tok), "stock"):
        if r["product_sku"].startswith("KIT-"):
            print(f"  {r['location_name']:<8} {r['product_name']:<22} {r['qty_base']:>12} {'LOW' if r['is_low_stock'] else ''}")


if __name__ == "__main__":
    main()
