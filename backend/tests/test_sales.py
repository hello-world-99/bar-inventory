"""POS sales import (agent-room replies 30-32): parser, norms, report, write-off, idempotency, inventory interplay."""

import io
import os
import uuid
import zipfile
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services import kitchen_seed
from app.services.pos_xlsx import ParseError, content_hash, parse
from tests.test_concurrency import _parallel
from tests.test_inventory import complete, count, start
from tests.test_posting import assert_journal_consistent, balance

P = "/api/v1"
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "pos_day.xlsx")
DAY_FILE = open(FIXTURE, "rb").read()  # noqa: SIM115  (read once, a few KB)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Reference from replies 30 and 37, for this file: fries 2025 g, wings 600 g, fish 4, philly meat 400 g (2 packs), philly buns 2.
REFERENCE = {"KIT-FRIES": Decimal(2025), "KIT-WINGS": Decimal(600), "KIT-FISH": Decimal(4), "KIT-PHILLY-MEAT": Decimal(400), "KIT-PHILLY-BUN": Decimal(2)}


# ------------------------------------------------------------------ helpers
def make_xlsx(rows, created="2026-11-24T23:30:00Z", sheet_xml=None, extra=None) -> bytes:
    """Minimal .xlsx: rows are lists of str / number / {"f": formula, "v": value} cells."""
    def cell(ref, v):
        if isinstance(v, dict):
            return f'<c r="{ref}"><f>{v["f"]}</f><v>{v["v"]}</v></c>'
        if isinstance(v, int | float | Decimal):
            return f'<c r="{ref}" t="n"><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'

    body = "".join(
        f'<row r="{r}">' + "".join(cell(f"{chr(65 + i)}{r}", v) for i, v in enumerate(row) if v is not None) + "</row>"
        for r, row in enumerate(rows, 1)
    )
    sheet = sheet_xml or f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{body}</sheetData></worksheet>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet" r:id="rId3" sheetId="1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId3" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        if created:
            z.writestr("docProps/core.xml", '<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                       f'xmlns:dcterms="http://purl.org/dc/terms/"><dcterms:created>{created}</dcterms:created></cp:coreProperties>')
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


HEADER = [["상품별 매출현황"], ["No.", "상품코드", "상품명", "수량", "실매출"]]


def rexport(data: bytes, created: str) -> bytes:
    """The same report exported again: identical rows, different metadata -> different bytes (reply 32, P1)."""
    src = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for info in src.infolist():
            content = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                content = content.replace(b"2026-11-08T13:17:30Z", created.encode())
            z.writestr(info.filename, content)
    return buf.getvalue()


@pytest.fixture
def kitchen(engine, client, admin_h):
    with engine.begin() as conn:
        kitchen_seed.seed(conn)
    loc = client.post(f"{P}/locations", json={"name": "Kitchen"}, headers=admin_h).json()["id"]
    with engine.connect() as conn:
        skus = dict(conn.execute(text("SELECT sku, id FROM products WHERE sku LIKE 'KIT-%'")).all())
    return {"loc": loc, **skus}


def upload(client, h, data=DAY_FILE, day=None, import_id=None, name="day.xlsx"):
    params = {"id": str(import_id or uuid.uuid4()), "sales_date": (day or yesterday(client, h)).isoformat(), "file_name": name}
    return client.post(f"{P}/sales-imports", params=params, content=data, headers=h | {"Content-Type": XLSX})


def yesterday(client, h) -> date:
    return date.fromisoformat(client.get(f"{P}/sales-imports", headers=h).json()["default_sales_date"])


def post(client, h, imp, loc, **kw):
    body = {"document_id": str(uuid.uuid4()), "location_id": loc} | kw
    return client.post(f"{P}/sales-imports/{imp['id']}/post", json=body, headers=h)


def by_sku(report):
    return {i["product_sku"]: Decimal(i["qty_base"]) for i in report["items"]}


def stock_up(client, h, k, qty_by_sku):
    lines = [{"product_id": k[s], "location_id": k["loc"], "qty": str(q), "qty_unit": "g" if s in GRAMS else None,
              "unit_price": "0"} for s, q in qty_by_sku.items()]
    r = client.post(f"{P}/receipts", json={"id": str(uuid.uuid4()), "lines": [{k2: v for k2, v in ln.items() if v is not None} for ln in lines]}, headers=h)
    assert r.status_code == 201, r.text


GRAMS = ("KIT-FRIES", "KIT-WINGS", "KIT-PHILLY-MEAT", "KIT-BURGER-MEAT")
FULL_STOCK = {"KIT-FRIES": 10000, "KIT-WINGS": 5000, "KIT-FISH": 20, "KIT-PHILLY-MEAT": 2000, "KIT-PHILLY-BUN": 10}  # base units


# -------------------------------------------------------------------- parser
def test_parser_on_the_owner_file():
    r = parse(DAY_FILE)
    assert len(r.lines) == 54 and r.total_qty == 369 and r.file_total_qty == 369 and r.total_revenue == 2971000
    q = {line.code: line.qty for line in r.lines}
    assert (q["001783"], q["001542"], q["001779"], q["001782"], q["001781"], q["001981"]) == (3, 1, 4, 1, 1, 2)
    assert r.warnings == []


def test_parser_sums_same_code_before_clamping_and_checks_total():
    rows = HEADER + [[1, "001783", "Fries", 3, 24000], [2, "001783", "Fries", -1, -8000], [3, "009", "Refund", -2, 0], ["합계", None, None, 5, 0]]
    r = parse(make_xlsx(rows))
    q = {line.code: line.qty for line in r.lines}
    assert q == {"001783": 2, "009": -2}
    codes = {w["code"] for w in r.warnings}
    assert codes == {"negative_qty", "total_mismatch"}


def test_content_hash_ignores_file_metadata():
    again = rexport(DAY_FILE, "2026-11-25T01:00:00Z")
    assert again != DAY_FILE and content_hash(parse(again)) == content_hash(parse(DAY_FILE))


@pytest.mark.parametrize(
    "data,code",
    [
        (b"not a zip at all", "bad_file"),
        (make_xlsx([["a", "b"], [1, 2]]), "missing_columns"),
        (make_xlsx(HEADER + [[1, "001", "X", {"f": "1+1", "v": 2}, 0]]), "formula_not_allowed"),
        (make_xlsx(HEADER + [[1, "001", "X", "three", 0]]), "bad_qty"),
        (make_xlsx(HEADER + [[1, None, "X", 1, 0]]), "bad_row"),
        (make_xlsx(HEADER), "empty_report"),
        (make_xlsx([], sheet_xml='<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>'), "bad_file"),
        # zip bomb: 30 MB of spaces compress to a few KB; refused by the unpacked-size limit, not the declared size
        (make_xlsx([], sheet_xml="<worksheet>" + " " * (30 * 1024 * 1024) + "</worksheet>"), "file_too_large"),
        (make_xlsx(HEADER, extra={f"junk/{i}.xml": "x" for i in range(60)}), "bad_file"),
    ],
)
def test_broken_files_are_parse_errors(data, code):
    with pytest.raises(ParseError) as e:
        parse(data)
    assert e.value.code == code


def test_bloated_sheet_is_refused_fast_and_without_memory_blowup():
    """Reply 39, P1: one row of 950 000 cells (20 MB of XML, ~50 KB zipped) used to take 600 MB and 4 s."""
    import time
    import tracemalloc

    row = '<row r="1">' + '<c t="n"><v>1</v></c>' * 950_000 + "</row>"
    data = make_xlsx([], sheet_xml=f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{row}</sheetData></worksheet>')
    assert len(data) < 200_000
    tracemalloc.start()
    t0 = time.monotonic()
    with pytest.raises(ParseError) as e:
        parse(data)
    elapsed = time.monotonic() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert e.value.code == "file_too_large"
    assert elapsed < 1.0 and peak < 20 * 1024 * 1024


def test_dtd_in_utf16_is_refused():
    xml = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x [<!ENTITY a "aaaa">]><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>'
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(make_xlsx(HEADER))) as src, zipfile.ZipFile(buf, "w") as z:
        for info in src.infolist():
            z.writestr(info.filename, xml.encode("utf-16") if info.filename.endswith("sheet1.xml") else src.read(info.filename))
    with pytest.raises(ParseError) as e:
        parse(buf.getvalue())
    assert e.value.code == "bad_file"


# ------------------------------------------------------------------- report
def test_upload_report_matches_reference(client, admin_h, kitchen):
    r = upload(client, admin_h)
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["status"] == "draft" and rep["line_count"] == 54
    assert by_sku(rep) == REFERENCE
    fries = next(i for i in rep["items"] if i["product_sku"] == "KIT-FRIES")
    assert {(p["pos_code"], Decimal(p["sold_qty"]), Decimal(p["qty_base"])) for p in fries["parts"]} == {
        ("001783", 3, 1050), ("001542", 1, 175), ("001779", 4, 800)}
    # every drink has no norm yet: listed, nothing hidden
    assert len(rep["unmapped"]) == 48 and rep["not_kitchen"] == []
    assert any(w["code"] == "file_date_far" for w in rep["warnings"])  # file made 2026-11-08


def test_upload_by_staff_and_raw_body_limits(client, staff_h, kitchen):
    assert upload(client, staff_h).status_code == 201
    r = client.post(f"{P}/sales-imports", params={"id": str(uuid.uuid4()), "sales_date": "2026-01-01"}, content=b"x" * (2 * 1024 * 1024 + 1),
                    headers=staff_h | {"Content-Type": XLSX})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "file_too_large"
    r = upload(client, staff_h, data=b"garbage")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_file"
    r = upload(client, staff_h, day=date.today() + timedelta(days=3))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "future_date"


def test_not_kitchen_and_norm_editing(client, admin_h, staff_h, kitchen):
    rep = upload(client, admin_h).json()
    drinks = [x["pos_item_id"] for x in rep["unmapped"] if x["code"] != "001877"]
    assert client.post(f"{P}/pos-items/not-kitchen", json={"ids": drinks}, headers=staff_h).status_code == 403
    assert client.post(f"{P}/pos-items/not-kitchen", json={"ids": drinks}, headers=admin_h).status_code == 200
    rep = client.get(f"{P}/sales-imports/{rep['id']}", headers=admin_h).json()
    assert [x["code"] for x in rep["unmapped"]] == ["001877"] and len(rep["not_kitchen"]) == 47

    jager = next(x["pos_item_id"] for x in rep["unmapped"])
    burger = {"components": [{"product_id": kitchen["KIT-FRIES"], "qty": "175", "qty_unit": "g"},
                             {"product_id": kitchen["KIT-BURGER-MEAT"], "qty": "1", "qty_unit": "pack"}, {"product_id": kitchen["KIT-BURGER-BUN"], "qty": "1"}]}
    assert client.put(f"{P}/pos-items/{jager}", json=burger, headers=staff_h).status_code == 403
    r = client.put(f"{P}/pos-items/{jager}", json=burger, headers=admin_h)
    assert r.status_code == 200, r.text
    assert {c["product_sku"]: Decimal(c["qty_base"]) for c in r.json()["components"]} == {"KIT-FRIES": 175, "KIT-BURGER-MEAT": 200, "KIT-BURGER-BUN": 1}
    # 23 Jagerbombs "as burgers": the draft follows the current norms
    rep = client.get(f"{P}/sales-imports/{rep['id']}", headers=admin_h).json()
    assert by_sku(rep)["KIT-FRIES"] == 2025 + 23 * 175 and by_sku(rep)["KIT-BURGER-BUN"] == 23
    # validation
    bad = client.put(f"{P}/pos-items/{jager}", json={"not_kitchen": True, **burger}, headers=admin_h)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "not_kitchen_with_norm"
    bad = client.put(f"{P}/pos-items/{jager}", json={"components": [{"product_id": kitchen["KIT-FISH"], "qty": "1", "qty_unit": "g"}]}, headers=admin_h)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "bad_unit"


# --------------------------------------------------------------- write-off
def test_post_writes_off_the_usage_at_the_start_of_the_sales_day(client, db, admin_h, staff_h, kitchen):
    stock_up(client, admin_h, kitchen, FULL_STOCK)
    rep = upload(client, staff_h).json()
    r = post(client, staff_h, rep, kitchen["loc"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unmapped_items" and len(r.json()["detail"]["items"]) == 48
    r = post(client, staff_h, rep, kitchen["loc"], acknowledge_unmapped=True)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "posted" and by_sku(done) == REFERENCE
    doc = client.get(f"{P}/documents/{done['write_off_id']}", headers=staff_h).json()
    assert doc["type"] == "write_off" and doc["reason"] == "sales"
    assert doc["doc_date"].startswith(rep["sales_date"] + "T06:00:00")  # business day starts at 06:00 UTC by default
    for sku, qty in REFERENCE.items():
        assert balance(db, kitchen[sku], kitchen["loc"]) == FULL_STOCK[sku] - qty
    assert_journal_consistent(db)

    # the frozen report does not follow later norm changes
    fries_item = next(x["id"] for x in client.get(f"{P}/pos-items", headers=admin_h).json() if x["code"] == "001783")
    client.put(f"{P}/pos-items/{fries_item}", json={"components": [{"product_id": kitchen["KIT-FRIES"], "qty": "999", "qty_unit": "g"}]}, headers=admin_h)
    assert by_sku(client.get(f"{P}/sales-imports/{rep['id']}", headers=admin_h).json()) == REFERENCE


def test_negative_stock_follows_the_usual_rules(client, db, admin_h, staff_h, kitchen):
    rep = upload(client, staff_h).json()
    r = post(client, staff_h, rep, kitchen["loc"], acknowledge_unmapped=True)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "insufficient_stock" and r.json()["detail"]["can_override"] is False
    r = post(client, admin_h, rep, kitchen["loc"], acknowledge_unmapped=True, allow_negative=True)
    assert r.status_code == 200, r.text
    assert balance(db, kitchen["KIT-FRIES"], kitchen["loc"]) == -2025


def test_sales_reason_is_reserved_for_imports(client, admin_h, kitchen):
    body = {"id": str(uuid.uuid4()), "reason": "sales", "lines": [{"product_id": kitchen["KIT-FISH"], "location_id": kitchen["loc"], "qty": "1"}]}
    r = client.post(f"{P}/write-offs", json=body, headers=admin_h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reserved_reason"


# ------------------------------------------------------------ idempotency
def test_same_day_twice_and_same_sales_under_another_date(client, admin_h, staff_h, kitchen):
    stock_up(client, admin_h, kitchen, FULL_STOCK)
    day = yesterday(client, staff_h)
    first = upload(client, staff_h, day=day).json()
    # an unposted draft of the day is simply replaced
    second = upload(client, staff_h, day=day, data=rexport(DAY_FILE, "2026-11-25T01:00:00Z")).json()
    assert client.get(f"{P}/sales-imports/{first['id']}", headers=staff_h).status_code == 404
    assert post(client, staff_h, second, kitchen["loc"], acknowledge_unmapped=True).status_code == 200

    r = upload(client, staff_h, day=day)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_posted" and r.json()["detail"]["import_id"] == second["id"]
    # the same day exported again and uploaded under another date by mistake (reply 32, P1)
    r = upload(client, staff_h, day=day - timedelta(days=1), data=rexport(DAY_FILE, "2026-11-26T09:00:00Z"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "same_file" and r.json()["detail"]["sales_date"] == day.isoformat()
    # a retried upload with the same id is idempotent
    imp_id = uuid.uuid4()
    other = make_xlsx(HEADER + [[1, "001783", "Fries", 1, 8000]])
    a, b = upload(client, staff_h, data=other, day=day - timedelta(days=2), import_id=imp_id), upload(client, staff_h, data=other, day=day - timedelta(days=2), import_id=imp_id)
    assert (a.status_code, b.status_code) == (201, 200) and a.json()["id"] == b.json()["id"]


def test_double_click_posts_once(client, db, admin_h, staff_h, kitchen):
    stock_up(client, admin_h, kitchen, FULL_STOCK)
    rep = upload(client, staff_h).json()
    results = _parallel(2, lambda c, i: post(c, staff_h, rep, kitchen["loc"], acknowledge_unmapped=True))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert db.execute(text("SELECT count(*) FROM stock_documents WHERE reason = 'sales'")).scalar() == 1
    assert balance(db, kitchen["KIT-FRIES"], kitchen["loc"]) == 10000 - 2025
    # a retry of the request that succeeded returns the same report
    winner = next(r for r in results if r.status_code == 200).json()
    again = client.post(f"{P}/sales-imports/{rep['id']}/post", json={"document_id": winner["write_off_id"], "location_id": kitchen["loc"]}, headers=staff_h)
    assert again.status_code == 200 and again.json()["write_off_id"] == winner["write_off_id"]


def test_void_reverses_and_frees_the_day(client, db, admin_h, staff_h, kitchen):
    stock_up(client, admin_h, kitchen, FULL_STOCK)
    rep = upload(client, staff_h).json()
    post(client, staff_h, rep, kitchen["loc"], acknowledge_unmapped=True)
    assert client.post(f"{P}/sales-imports/{rep['id']}/void", json={"reversal_id": str(uuid.uuid4())}, headers=staff_h).status_code == 403
    r = client.post(f"{P}/sales-imports/{rep['id']}/void", json={"reversal_id": str(uuid.uuid4())}, headers=admin_h)
    assert r.status_code == 200 and r.json()["status"] == "voided"
    assert balance(db, kitchen["KIT-FRIES"], kitchen["loc"]) == 10000
    assert upload(client, staff_h).status_code == 201  # the day can be imported again
    assert_journal_consistent(db)


# ---------------------------------------------------- inventory interplay
def test_products_counted_after_the_sales_are_skipped_the_rest_written_off(client, db, admin, admin_h, staff_h, kitchen):
    """Night count of the fries only, completed at night; POS report uploaded in the morning (reply 39, P2)."""
    stock_up(client, admin_h, kitchen, FULL_STOCK)
    inv = start(client, admin_h, {"main": kitchen["loc"]}, "main")
    assert count(client, admin_h, inv, kitchen["KIT-FRIES"], [(7975, "g")]).status_code == 200
    assert complete(client, admin_h, inv).status_code == 200
    assert balance(db, kitchen["KIT-FRIES"], kitchen["loc"]) == 7975  # the count already took the fries sales out

    rep = upload(client, staff_h).json()
    preview = client.get(f"{P}/sales-imports/{rep['id']}", params={"location_id": kitchen["loc"]}, headers=staff_h).json()
    assert {i["product_sku"]: i["covered_inventory_id"] for i in preview["items"]}["KIT-FRIES"] == inv["id"]

    r = post(client, staff_h, rep, kitchen["loc"], acknowledge_unmapped=True)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "posted" and by_sku(done) == REFERENCE  # the report keeps the full usage
    status = {i["product_sku"]: i["covered_inventory_id"] for i in done["items"]}
    assert status == {"KIT-FRIES": inv["id"], "KIT-WINGS": None, "KIT-FISH": None, "KIT-PHILLY-MEAT": None, "KIT-PHILLY-BUN": None}
    doc = client.get(f"{P}/documents/{done['write_off_id']}", headers=staff_h).json()
    assert {ln["product_sku"] for ln in doc["lines"]} == {"KIT-WINGS", "KIT-FISH", "KIT-PHILLY-MEAT", "KIT-PHILLY-BUN"}
    assert balance(db, kitchen["KIT-FRIES"], kitchen["loc"]) == 7975  # not twice
    for sku in ("KIT-WINGS", "KIT-FISH", "KIT-PHILLY-MEAT", "KIT-PHILLY-BUN"):
        assert balance(db, kitchen[sku], kitchen["loc"]) == FULL_STOCK[sku] - REFERENCE[sku]
    assert_journal_consistent(db)
    assert upload(client, staff_h).json()["detail"]["code"] == "already_posted"


def test_all_products_counted_after_the_sales_means_covered_without_a_document(client, db, admin_h, staff_h, kitchen):
    stock_up(client, admin_h, kitchen, FULL_STOCK)
    inv = start(client, admin_h, {"main": kitchen["loc"]}, "main")
    for sku in REFERENCE:
        assert count(client, admin_h, inv, kitchen[sku], [(FULL_STOCK[sku] - REFERENCE[sku], "g" if sku in GRAMS else "pcs")]).status_code == 200
    assert complete(client, admin_h, inv).status_code == 200
    rep = upload(client, staff_h).json()
    doc_id = str(uuid.uuid4())
    r = client.post(f"{P}/sales-imports/{rep['id']}/post", json={"document_id": doc_id, "location_id": kitchen["loc"], "acknowledge_unmapped": True}, headers=staff_h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "covered" and r.json()["write_off_id"] is None and r.json()["covered_inventory_id"] == inv["id"]
    assert db.execute(text("SELECT count(*) FROM stock_documents WHERE reason = 'sales'")).scalar() == 0
    # a retry of the same request returns the same result
    again = client.post(f"{P}/sales-imports/{rep['id']}/post", json={"document_id": doc_id, "location_id": kitchen["loc"], "acknowledge_unmapped": True}, headers=staff_h)
    assert again.status_code == 200 and again.json()["status"] == "covered"
    assert_journal_consistent(db)


def test_upload_before_completing_the_count_gives_a_zero_difference(client, db, admin_h, staff_h, kitchen):
    stock_up(client, admin_h, kitchen, FULL_STOCK)
    inv = start(client, admin_h, {"main": kitchen["loc"]}, "main")
    assert count(client, admin_h, inv, kitchen["KIT-FRIES"], [(7975, "g")]).status_code == 200
    rep = upload(client, staff_h).json()  # the right order: POS report first, then completion
    assert post(client, staff_h, rep, kitchen["loc"], acknowledge_unmapped=True).status_code == 200
    done = complete(client, admin_h, inv).json()
    assert done["adjustment_document_id"] is None  # counted 7975 = 10000 - 2025: no shortage
    assert balance(db, kitchen["KIT-FRIES"], kitchen["loc"]) == 7975


def test_void_after_the_day_was_counted_is_refused_with_a_clear_error(client, db, admin, admin_h, staff_h, kitchen):
    stock_up(client, admin_h, kitchen, FULL_STOCK)
    rep = upload(client, staff_h).json()
    post(client, staff_h, rep, kitchen["loc"], acknowledge_unmapped=True)
    inv = start(client, admin_h, {"main": kitchen["loc"]}, "main")
    count(client, admin_h, inv, kitchen["KIT-FRIES"], [(7975, "g")])
    complete(client, admin_h, inv)
    r = client.post(f"{P}/sales-imports/{rep['id']}/void", json={"reversal_id": str(uuid.uuid4())}, headers=admin_h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "counted_after"
    assert "cannot be voided" in r.json()["detail"]["message"]


def test_pending_days_before_completing_an_inventory(client, db, admin_h, staff_h, kitchen):
    stock_up(client, admin_h, kitchen, FULL_STOCK)
    r = client.get(f"{P}/sales-imports/pending-days", params={"location_id": kitchen["loc"]}, headers=staff_h).json()
    assert r["days"] == [] and r["last_imported"] is None  # never imported here: no warning
    day = yesterday(client, staff_h)
    rep = upload(client, staff_h, day=day - timedelta(days=2), data=make_xlsx(HEADER + [[1, "001783", "Fries", 1, 8000]])).json()
    assert post(client, staff_h, rep, kitchen["loc"], acknowledge_unmapped=True).status_code == 200
    r = client.get(f"{P}/sales-imports/pending-days", params={"location_id": kitchen["loc"]}, headers=staff_h).json()
    assert r["days"] == [(day - timedelta(days=1)).isoformat(), day.isoformat(), (day + timedelta(days=1)).isoformat()]


def test_seed_skips_norms_for_products_in_other_units(engine, admin):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO products (name, sku, category_id, unit, base_unit, unit_size) "
                          "VALUES ('Fries', 'KIT-FRIES', (SELECT id FROM categories LIMIT 1), 'pcs', 'pcs', 1)"))
        kitchen_seed.seed(conn)
        norms = dict(conn.execute(text("SELECT i.code, count(c.product_id) FROM pos_items i LEFT JOIN pos_item_components c ON c.pos_item_id = i.id GROUP BY i.code")).all())
    assert norms["001783"] == 0 and norms["001779"] == 0  # fries kept in pieces: no norm rather than 350 pieces
    assert norms["001782"] == 1 and norms["001981"] == 2


def test_meat_is_counted_in_packs_and_converted_to_grams(client, db, admin_h, kitchen):
    """Reply 37: unit 'pack' (base g, 200 g) like bottle/ml."""
    meat = kitchen["KIT-PHILLY-MEAT"]
    p = client.get(f"{P}/products/{meat}", headers=admin_h).json()
    assert (p["unit"], p["base_unit"], Decimal(p["unit_size"])) == ("pack", "g", 200)
    body = {"id": str(uuid.uuid4()), "lines": [{"product_id": meat, "location_id": kitchen["loc"], "qty": "3", "unit_price": "9000"}]}
    assert client.post(f"{P}/receipts", json=body, headers=admin_h).status_code == 201
    assert balance(db, meat, kitchen["loc"]) == 600  # 3 packs
    inv = start(client, admin_h, {"main": kitchen["loc"]}, "main")
    r = count(client, admin_h, inv, meat, [(2, "pack"), (50, "g")])  # two packs and an open one with 50 g left
    assert r.status_code == 200 and Decimal(r.json()["counted_base"]) == 450
    assert count(client, admin_h, inv, meat, [("0.45", "kg")]).status_code == 200  # grams/kg only also work
    r = count(client, admin_h, inv, kitchen["KIT-FISH"], [(1, "pack")])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_unit"  # a pack of a piece product: no
    # the pack size is frozen once there are movements
    r = client.patch(f"{P}/products/{meat}", json={"unit_size": "250"}, headers=admin_h)
    assert r.status_code in (409, 422)


def test_pack_products_need_a_size(client, admin_h, kitchen):
    cat = next(c["id"] for c in client.get(f"{P}/categories", headers=admin_h).json() if c["code"] == "kitchen")
    r = client.post(f"{P}/products", json={"name": "Ribs", "sku": "RIBS", "category_id": cat, "unit": "pack"}, headers=admin_h)
    assert r.status_code == 422
    r = client.post(f"{P}/products", json={"name": "Ribs", "sku": "RIBS", "category_id": cat, "unit": "pack", "unit_size": "250"}, headers=admin_h)
    assert r.status_code == 201 and r.json()["base_unit"] == "g"


def test_codes_exported_as_numbers_match_the_known_codes(client, admin_h, kitchen):
    """Reply 39, N2: a POS that writes codes as numbers drops the leading zeros (1783 instead of 001783)."""
    data = make_xlsx(HEADER + [[1, 1783, "Fries", 2, 16000], [2, 1981, "Philly", 1, 20000], [3, 777, "New dish", 1, 9000]])
    rep = upload(client, admin_h, data=data).json()
    assert by_sku(rep)["KIT-FRIES"] == 700 and by_sku(rep)["KIT-PHILLY-MEAT"] == 200
    assert [x["code"] for x in rep["unmapped"]] == ["777"]  # unknown codes stay as they are


def test_example_data_runs_the_real_flow_once(engine, db, admin, client, admin_h):
    """Reply 33, p. 3: `python -m app.cli seed-example` on a fresh install."""
    from app.services.example import seed_example

    with engine.begin() as conn:
        kitchen_seed.seed(conn)
    msg = seed_example(db)
    assert "written off (posted)" in msg
    imports = client.get(f"{P}/sales-imports", headers=admin_h).json()["items"]
    assert len(imports) == 1 and imports[0]["status"] == "posted"
    rep = client.get(f"{P}/sales-imports/{imports[0]['id']}", headers=admin_h).json()
    assert by_sku(rep) == REFERENCE and rep["unmapped"] == [] and len(rep["not_kitchen"]) == 48
    low = {r["product_sku"] for r in client.get(f"{P}/stock", headers=admin_h).json() if r["is_low_stock"]}
    assert low == {"KIT-WINGS", "KIT-FISH", "KIT-PHILLY-BUN"}  # stocked short on purpose: shown red
    assert "already there" in seed_example(db)
    assert_journal_consistent(db)


def test_quantities_and_prices_corrected_in_the_report_are_written_off(client, db, admin_h, staff_h, kitchen):
    """Owner, 2026-11-25: quantity and cost are editable in the report before writing off."""
    stock_up(client, admin_h, kitchen, FULL_STOCK)
    rep = upload(client, staff_h).json()
    lines = [
        {"product_id": kitchen["KIT-FRIES"], "qty_base": "2100", "unit_price": "5000"},  # 2.1 kg at 5000 per kg
        {"product_id": kitchen["KIT-FISH"], "qty_base": "0"},  # not written off at all
    ]
    r = post(client, staff_h, rep, kitchen["loc"], acknowledge_unmapped=True, lines=lines)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "price_not_allowed"  # prices: admin only (reply 41)
    r = post(client, admin_h, rep, kitchen["loc"], acknowledge_unmapped=True, lines=lines)
    assert r.status_code == 200, r.text
    done = r.json()
    used = by_sku(done)
    assert used["KIT-FRIES"] == 2100 and "KIT-FISH" not in used and used["KIT-WINGS"] == 600
    fries = next(i for i in done["items"] if i["product_sku"] == "KIT-FRIES")
    assert Decimal(fries["amount"]) == Decimal("10500")  # 2100 g x 5 per g
    assert any(p["pos_name"] == "Manual correction" and Decimal(p["qty_base"]) == 75 for p in fries["parts"])
    assert balance(db, kitchen["KIT-FRIES"], kitchen["loc"]) == 10000 - 2100
    assert balance(db, kitchen["KIT-FISH"], kitchen["loc"]) == FULL_STOCK["KIT-FISH"]
    doc = client.get(f"{P}/documents/{done['write_off_id']}", headers=staff_h).json()
    assert Decimal(next(ln for ln in doc["lines"] if ln["product_sku"] == "KIT-FRIES")["amount"]) == Decimal("10500")
    assert_journal_consistent(db)


def test_a_correction_must_belong_to_the_report(client, admin_h, staff_h, kitchen):
    rep = upload(client, staff_h).json()
    r = post(client, staff_h, rep, kitchen["loc"], acknowledge_unmapped=True, lines=[{"product_id": kitchen["KIT-BURGER-BUN"], "qty_base": "1"}])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_product"


def test_stock_rows_flag_products_running_out(client, db, admin_h, kitchen):
    stock_up(client, admin_h, kitchen, {"KIT-FISH": 2, "KIT-FRIES": 10000})
    client.patch(f"{P}/products/{kitchen['KIT-FISH']}", json={"min_stock_base": "3"}, headers=admin_h)
    client.patch(f"{P}/products/{kitchen['KIT-FRIES']}", json={"min_stock_base": "3000"}, headers=admin_h)
    rows = {r["product_sku"]: r for r in client.get(f"{P}/stock", headers=admin_h).json()}
    assert rows["KIT-FISH"]["is_low_stock"] is True and rows["KIT-FRIES"]["is_low_stock"] is False


def test_staff_may_correct_quantities_without_prices(client, db, admin_h, staff_h, kitchen):
    stock_up(client, admin_h, kitchen, FULL_STOCK)
    rep = upload(client, staff_h).json()
    r = post(client, staff_h, rep, kitchen["loc"], acknowledge_unmapped=True, lines=[{"product_id": kitchen["KIT-FRIES"], "qty_base": "2000"}])
    assert r.status_code == 200, r.text
    assert balance(db, kitchen["KIT-FRIES"], kitchen["loc"]) == 8000
