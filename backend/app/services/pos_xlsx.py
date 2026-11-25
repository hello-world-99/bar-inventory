"""Parser of the POS "sales by item" report (상품별 매출현황) exported as .xlsx.

The file is untrusted input, read with the standard library only (reply 32; reply 39, P1):
  * limits on the upload size, the number of zip members, the UNPACKED bytes of every part (read in chunks,
    never trusting the declared size), and - while parsing - on rows, cells per row and text per cell;
  * every XML part is parsed as a STREAM with expat (no DOM): memory stays at the size of the result, not of
    the XML. A DTD or entity declaration in any encoding is refused; external links are never followed - only
    the workbook, its relationships, the first worksheet, shared strings and core properties are read;
  * formulas in the columns we use are refused: values must be what the POS exported.

Columns are found by their header text, not by letter. The Korean strings below are the literal headers of the
POS export (code, item name, quantity, revenue, total row) and must stay as they are. The total row (합계) is skipped and used as a check.
Every problem is a ParseError with a machine-readable code; the API turns it into a 422.
"""

import hashlib
import io
import posixpath
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.parsers import expat

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_MEMBERS = 50
MAX_MEMBER_BYTES = 4 * 1024 * 1024  # a real day is a few KB; 5000 rows x 5 cells is ~1.5 MB
MAX_ROWS = 5000
MAX_CELLS_PER_ROW = 64
MAX_CELL_TEXT = 1024
MAX_SHARED_STRINGS = 50000
HEADER_SEARCH_ROWS = 10
QTY_LIMIT = Decimal("1000000")
CHUNK = 64 * 1024

H_CODE, H_NAME, H_QTY, H_REVENUE = "상품코드", "상품명", "수량", "실매출"
TOTAL_MARK = "합계"

_CELL_REF = re.compile(r"^([A-Z]{1,3})(\d+)$")


class ParseError(Exception):
    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


@dataclass
class PosLine:
    code: str
    name: str
    qty: Decimal  # net: rows with the same code are summed, returns (negative rows) included
    revenue: Decimal | None


@dataclass
class PosReport:
    lines: list[PosLine]
    total_qty: Decimal  # sum of the item rows
    total_revenue: Decimal | None
    file_total_qty: Decimal | None  # from the 합계 row, if present
    created: datetime | None  # docProps/core.xml dcterms:created
    warnings: list[dict[str, Any]] = field(default_factory=list)


# ------------------------------------------------------------------ streaming
def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _no_dtd(*_: Any) -> None:
    raise ParseError("bad_file", "The file contains a DTD or entity declaration, which a sales report never has")


def _ignore(*_: Any) -> None:
    pass


def _stream(z: zipfile.ZipFile, name: str, start: Callable[[str, dict[str, str]], None],
            end: Callable[[str], None], text: Callable[[str], None]) -> None:
    """Feed one zip part to expat in chunks. Callbacks get local element names (namespaces stripped)."""
    p = expat.ParserCreate(namespace_separator="}")
    p.StartDoctypeDeclHandler = _no_dtd
    p.EntityDeclHandler = _no_dtd
    p.ExternalEntityRefHandler = lambda *_: 0  # never resolve
    p.StartElementHandler = lambda n, a: start(_local(n), {_local(k): v for k, v in a.items()})
    p.EndElementHandler = lambda n: end(_local(n))
    p.CharacterDataHandler = text
    p.buffer_text = True
    try:
        with z.open(name) as f:
            total = 0
            while chunk := f.read(CHUNK):
                total += len(chunk)
                if total > MAX_MEMBER_BYTES:
                    raise ParseError("file_too_large", "The file unpacks to more data than a sales report can have")
                p.Parse(chunk, False)
            p.Parse(b"", True)
    except KeyError:
        raise ParseError("bad_file", f"The file has no part '{name}'; is it an .xlsx sales report?") from None
    except expat.ExpatError:
        raise ParseError("bad_file", "The file is damaged (invalid XML)") from None
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, RuntimeError, NotImplementedError) as e:
        raise ParseError("bad_file", f"The file is damaged ({type(e).__name__})") from None


def _first_sheet_path(z: zipfile.ZipFile) -> str:
    rid: list[str] = []
    rels: dict[str, dict[str, str]] = {}

    def on_sheet(n: str, a: dict[str, str]) -> None:
        if n == "sheet" and not rid:
            rid.append(a.get("id", ""))

    def on_rel(n: str, a: dict[str, str]) -> None:
        if n == "Relationship" and len(rels) < 1000:
            rels.setdefault(a.get("Id", ""), a)

    _stream(z, "xl/workbook.xml", on_sheet, _ignore, _ignore)
    if not rid:
        raise ParseError("bad_file", "The workbook has no sheets")
    _stream(z, "xl/_rels/workbook.xml.rels", on_rel, _ignore, _ignore)
    rel = rels.get(rid[0])
    if rel is None:
        raise ParseError("bad_file", "The first sheet of the workbook is missing")
    if rel.get("TargetMode") == "External":
        raise ParseError("bad_file", "The sheet points outside the file")
    target = rel.get("Target") or ""
    path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
    if path.startswith("..") or not path.startswith("xl/"):
        raise ParseError("bad_file", "The sheet points outside the workbook")
    return path


class _Text:
    """Collects character data of the current element, capped (a single huge string is refused, not stored)."""

    def __init__(self) -> None:
        self.on = False
        self.parts: list[str] = []
        self.size = 0

    def start(self) -> None:
        self.on, self.parts, self.size = True, [], 0

    def __call__(self, s: str) -> None:
        if self.on:
            self.size += len(s)
            if self.size > MAX_CELL_TEXT:
                raise ParseError("bad_file", "A cell of the report holds too much text")
            self.parts.append(s)

    def take(self) -> str:
        self.on = False
        return "".join(self.parts)


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    out: list[str] = []
    cur: list[str] = []
    txt = _Text()

    def start(n: str, _a: dict[str, str]) -> None:
        if n == "si":
            cur.clear()
        elif n == "t":
            txt.start()

    def end(n: str) -> None:
        if n == "t":
            cur.append(txt.take())
        elif n == "si":
            if len(out) >= MAX_SHARED_STRINGS:
                raise ParseError("file_too_large", "The file has too many texts for a sales report")
            out.append("".join(cur))

    _stream(z, "xl/sharedStrings.xml", start, end, txt)
    return out


def _created(z: zipfile.ZipFile) -> datetime | None:
    if "docProps/core.xml" not in z.namelist():
        return None
    found: list[str] = []
    txt = _Text()

    def start(n: str, _a: dict[str, str]) -> None:
        if n == "created":
            txt.start()

    def end(n: str) -> None:
        if n == "created":
            found.append(txt.take())

    try:
        _stream(z, "docProps/core.xml", start, end, txt)
        return datetime.fromisoformat(found[0].strip().replace("Z", "+00:00")) if found else None
    except (ParseError, ValueError):
        return None  # informational only


# ---------------------------------------------------------------- the sheet
@dataclass
class _Cell:
    value: str
    formula: bool
    numeric: bool


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _rows(z: zipfile.ZipFile, path: str, shared: list[str]) -> list[tuple[int, dict[int, _Cell]]]:
    """Rows of the sheet as {column: cell}; limits are enforced while streaming, before memory grows."""
    rows: list[tuple[int, dict[int, _Cell]]] = []
    st: dict[str, Any] = {"row": None, "rnum": 0, "cell": None, "seen_data": False}
    txt = _Text()

    def start(n: str, a: dict[str, str]) -> None:
        if n == "sheetData":
            st["seen_data"] = True
        elif n == "row":
            if len(rows) >= MAX_ROWS:
                raise ParseError("file_too_large", f"The report has more than {MAX_ROWS} rows")
            r = a.get("r", "")
            st["rnum"] = int(r) if r.isdigit() else len(rows) + 1
            st["row"] = {}
        elif n == "c" and st["row"] is not None:
            if len(st["row"]) >= MAX_CELLS_PER_ROW:
                raise ParseError("file_too_large", f"Row {st['rnum']} has more than {MAX_CELLS_PER_ROW} cells")
            m = _CELL_REF.match(a.get("r", ""))
            col = _col_index(m.group(1)) if m else len(st["row"]) + 1
            st["cell"] = {"col": col, "t": a.get("t") or "n", "f": False, "v": "", "is": []}
        elif st["cell"] is not None:
            if n == "f":
                st["cell"]["f"] = True
            elif n in ("v", "t"):
                txt.start()

    def end(n: str) -> None:
        cell = st["cell"]
        if n == "v" and cell is not None:
            cell["v"] = txt.take()
        elif n == "t" and cell is not None:
            cell["is"].append(txt.take())
        elif n == "c" and cell is not None:
            t, rnum = cell["t"], st["rnum"]
            if t == "inlineStr":
                value = "".join(cell["is"])
            elif t == "s":
                try:
                    value = shared[int(cell["v"].strip())]
                except (ValueError, IndexError):
                    raise ParseError("bad_file", f"Row {rnum} refers to a missing text") from None
            else:
                value = cell["v"]
            st["row"][cell["col"]] = _Cell(value.strip(), cell["f"], t == "n")
            st["cell"] = None
        elif n == "row" and st["row"] is not None:
            rows.append((st["rnum"], st["row"]))
            st["row"] = None

    _stream(z, path, start, end, txt)
    if not st["seen_data"]:
        raise ParseError("bad_file", "The sheet has no data")
    return rows


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _find_header(rows: list[tuple[int, dict[int, _Cell]]]) -> tuple[int, dict[str, int]]:
    for idx, (_, cells) in enumerate(rows[:HEADER_SEARCH_ROWS]):
        found = {_norm(c.value): col for col, c in cells.items() if c.value}
        if all(h in found for h in (H_CODE, H_NAME, H_QTY)):
            return idx, {"code": found[H_CODE], "name": found[H_NAME], "qty": found[H_QTY], "revenue": found.get(H_REVENUE, 0)}
    raise ParseError(
        "missing_columns",
        f"Columns '{H_CODE}', '{H_NAME}' and '{H_QTY}' were not found; is this the POS 'sales by item' report?",
    )


def _number(cell: _Cell | None, rnum: int, what: str) -> Decimal | None:
    if cell is None or cell.value == "":
        return None
    if cell.formula:
        raise ParseError("formula_not_allowed", f"Row {rnum}: the {what} is a formula; upload the report exactly as the POS exported it", row=rnum)
    try:
        d = Decimal(cell.value.replace(",", ""))
    except InvalidOperation:
        raise ParseError("bad_qty", f"Row {rnum}: the {what} '{cell.value[:30]}' is not a number", row=rnum) from None
    if not d.is_finite() or abs(d) >= QTY_LIMIT * 1000:
        raise ParseError("bad_qty", f"Row {rnum}: the {what} is out of range", row=rnum)
    return d


def _code(cell: _Cell) -> str:
    v = cell.value
    if cell.numeric:  # a code stored as a number loses its leading zeros; keep the integer text
        try:
            d = Decimal(v)
            if d == d.to_integral_value():
                v = str(int(d))
        except InvalidOperation:
            pass
    return v


def parse(data: bytes) -> PosReport:
    if len(data) > MAX_FILE_BYTES:
        raise ParseError("file_too_large", f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, OSError):
        raise ParseError("bad_file", "This is not an .xlsx file") from None
    with z:
        if len(z.infolist()) > MAX_MEMBERS:
            raise ParseError("bad_file", "The file has too many parts for a sales report")
        shared = _shared_strings(z)
        rows = _rows(z, _first_sheet_path(z), shared)
        created = _created(z)

    header_idx, col = _find_header(rows)
    by_code: dict[str, PosLine] = {}
    file_total: Decimal | None = None
    warnings: list[dict[str, Any]] = []
    for rnum, cells in rows[header_idx + 1:]:
        if any(c.value == TOTAL_MARK for c in cells.values()):
            file_total = _number(cells.get(col["qty"]), rnum, "total quantity")
            continue
        code_cell, name_cell = cells.get(col["code"]), cells.get(col["name"])
        qty = _number(cells.get(col["qty"]), rnum, "quantity")
        code = _code(code_cell) if code_cell else ""
        name = name_cell.value if name_cell else ""
        if not code and not name and qty is None:
            continue  # empty row
        for c in (code_cell, name_cell):
            if c is not None and c.formula:
                raise ParseError("formula_not_allowed", f"Row {rnum}: a formula in the item columns", row=rnum)
        if not code:
            raise ParseError("bad_row", f"Row {rnum}: the item code ({H_CODE}) is empty", row=rnum)
        if len(code) > 32 or len(name) > 128:
            raise ParseError("bad_row", f"Row {rnum}: the item code or name is too long", row=rnum)
        if qty is None:
            raise ParseError("bad_qty", f"Row {rnum}: the quantity is empty", row=rnum)
        if abs(qty) >= QTY_LIMIT:
            raise ParseError("bad_qty", f"Row {rnum}: the quantity is out of range", row=rnum)
        revenue = _number(cells.get(col["revenue"]), rnum, "revenue") if col["revenue"] else None
        line = by_code.get(code)
        if line is None:
            by_code[code] = PosLine(code, name or code, qty, revenue)
        else:  # same item on several rows (e.g. a refund): sum before anything is clamped (reply 32, N5)
            line.qty += qty
            line.revenue = None if line.revenue is None or revenue is None else line.revenue + revenue
            if name:
                line.name = name

    if not by_code:
        raise ParseError("empty_report", "The report has no items")
    lines = list(by_code.values())
    total_qty = sum((line.qty for line in lines), Decimal(0))
    revenues = [line.revenue for line in lines]
    total_revenue = None if any(r is None for r in revenues) else sum(revenues, Decimal(0))
    for line in lines:
        if line.qty < 0:
            warnings.append({"code": "negative_qty", "pos_code": line.code, "pos_name": line.name, "qty": str(line.qty)})
    if file_total is not None and file_total != total_qty:
        warnings.append({"code": "total_mismatch", "file_total": str(file_total), "sum": str(total_qty)})
    return PosReport(lines, total_qty, total_revenue, file_total, created, warnings)


def content_hash(report: PosReport) -> str:
    """Hash of the sales themselves, independent of the xlsx bytes (re-exports of a day differ only in metadata)."""
    canon = "\n".join(
        f"{line.code}\t{line.qty.normalize():f}\t{'' if line.revenue is None else f'{line.revenue.normalize():f}'}"
        for line in sorted(report.lines, key=lambda x: x.code)
    )
    return hashlib.sha256(canon.encode()).hexdigest()


def file_date_warning(report: PosReport, sales_date: date) -> dict[str, Any] | None:
    """The file was created far from the chosen sales day: probably the wrong day (reply 32, P1)."""
    if report.created is None:
        return None
    created = report.created.date()
    if abs((created - sales_date).days) > 2:
        return {"code": "file_date_far", "created": created.isoformat(), "sales_date": sales_date.isoformat()}
    return None
