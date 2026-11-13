"""Reads a holder's own file of dormant balances: a CSV or an Excel export from a payroll or banking system.

Nothing here knows what the columns mean. It returns the header row, the rows under it as text, and where the
header was found, and leaves the meaning of the columns to holder_list.py. Only the standard library is used:
an Excel workbook is a zip of XML files, and the first sheet is read straight from it.

The file's bytes stay on the server. No part of this module calls a language model or the network.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from xml.etree import ElementTree

MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 200_000
MAX_COLUMNS = 80

# The mark the generator writes on the first line of an invented file. A file that carries it is treated as a
# demonstration file everywhere: its records are demonstration records and no real person is in it.
INVENTED_MARK = "INVENTED DEMONSTRATION DATA"


class FileProblem(ValueError):
    """The file cannot be read as a table. The message is a sentence for the screen."""


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]                 # every row has exactly len(header) cells
    row_numbers: list[int]                # the line or sheet row each row came from, counted from 1
    header_row: int                       # the same for the header
    kind: str                             # "csv" or "excel"
    invented: bool = False
    notes: list[str] = field(default_factory=list)


def _clean(cell) -> str:
    return " ".join(str(cell if cell is not None else "").replace(" ", " ").split())


# ---- CSV ---------------------------------------------------------------------------------------------------------

def _decode(data: bytes) -> tuple[str, str]:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16"), "utf-16"
        except UnicodeError:
            pass
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding), encoding
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("latin-1"), "latin-1"


def _delimiter(text: str) -> str:
    """The separator that gives the most lines the same number of cells, among comma, semicolon, tab and bar."""
    lines = [line for line in text.splitlines()[:60] if line.strip()]
    best, best_score = ",", -1.0
    for candidate in (",", ";", "\t", "|"):
        counts = [len(next(csv.reader([line], delimiter=candidate))) for line in lines]
        if not counts:
            continue
        common = max(set(counts), key=counts.count)
        score = counts.count(common) * (common - 1)
        if common > 1 and score > best_score:
            best, best_score = candidate, score
    return best


def _csv_rows(data: bytes) -> tuple[list[list[str]], list[str]]:
    text, encoding = _decode(data)
    delimiter = _delimiter(text)
    rows = [[_clean(c) for c in row] for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)]
    names = {",": "commas", ";": "semicolons", "\t": "tabs", "|": "vertical bars"}
    return rows, [f"Read as text separated by {names[delimiter]}, in the {encoding.replace('-sig', '')} encoding."]


# ---- Excel -------------------------------------------------------------------------------------------------------

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
_BUILT_IN_DATES = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))
_DATE_LETTERS = re.compile(r"[dmyDMY]")
_QUOTED = re.compile(r'"[^"]*"|\[[^\]]*\]|\\.')


def _is_date_format(code: str) -> bool:
    return bool(_DATE_LETTERS.search(_QUOTED.sub("", code or "")))


def excel_date(serial: float) -> str:
    """An Excel day count as an ISO date. Day 1 is 1 January 1900 in Excel's own (leap-year-bug) calendar."""
    day = datetime(1899, 12, 30) + timedelta(days=float(serial))
    return day.date().isoformat()


def _column_index(ref: str) -> int:
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _excel_rows(data: bytes) -> tuple[list[list[str]], list[str]]:
    try:
        book = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise FileProblem("The file is named like an Excel workbook but cannot be opened as one. Save it again "
                          "as .xlsx or as .csv and upload that.") from None
    names = set(book.namelist())
    if "xl/workbook.xml" not in names:
        raise FileProblem("The file is not an Excel workbook of the .xlsx kind. Save it as .xlsx or .csv.")

    def xml(name: str):
        if book.getinfo(name).file_size > 100 * 1024 * 1024:
            raise FileProblem("The workbook is too large to read. Export the list as .csv.")
        data = book.read(name)
        if b"<!DOCTYPE" in data or b"<!ENTITY" in data:      # a spreadsheet has neither; a crafted file might
            raise FileProblem("The workbook holds something a spreadsheet does not. Export the list as .csv.")
        return ElementTree.fromstring(data)

    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in xml("xl/sharedStrings.xml").findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
    date_styles: set[int] = set()
    if "xl/styles.xml" in names:
        styles = xml("xl/styles.xml")
        custom = {int(f.get("numFmtId")): f.get("formatCode") or "" for f in styles.findall("m:numFmts/m:numFmt", _NS)}
        for i, xf in enumerate(styles.findall("m:cellXfs/m:xf", _NS)):
            fmt = int(xf.get("numFmtId") or 0)
            if fmt in _BUILT_IN_DATES or _is_date_format(custom.get(fmt, "")):
                date_styles.add(i)
    # The first sheet in the workbook's own order.
    workbook = xml("xl/workbook.xml")
    first = workbook.find("m:sheets/m:sheet", _NS)
    target = "xl/worksheets/sheet1.xml"
    if first is not None and "xl/_rels/workbook.xml.rels" in names:
        rid = first.get(f"{{{_NS['r']}}}id")
        for rel in xml("xl/_rels/workbook.xml.rels").findall("p:Relationship", _NS):
            if rel.get("Id") == rid:
                target = "xl/" + rel.get("Target").lstrip("/").removeprefix("xl/")
    if target not in names:
        raise FileProblem("The workbook has no sheet that can be read.")
    sheets = len(workbook.findall("m:sheets/m:sheet", _NS))
    rows: list[list[str]] = []
    for row in xml(target).iter(f"{{{_NS['m']}}}row"):
        number = int(row.get("r") or len(rows) + 1)
        while len(rows) < number - 1:
            rows.append([])
        cells: list[str] = []
        for c in row.findall("m:c", _NS):
            at = _column_index(c.get("r") or "") if c.get("r") else len(cells)
            if at >= MAX_COLUMNS:
                continue
            while len(cells) < at:
                cells.append("")
            kind, value = c.get("t"), c.find("m:v", _NS)
            if kind == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
            elif value is None or value.text is None:
                text = ""
            elif kind == "s":
                text = shared[int(value.text)] if int(value.text) < len(shared) else ""
            elif kind == "b":
                text = "TRUE" if value.text == "1" else "FALSE"
            elif kind in (None, "n") and int(c.get("s") or 0) in date_styles:
                try:
                    text = excel_date(float(value.text))
                except (ValueError, OverflowError):
                    text = value.text
            else:
                text = value.text
                if kind in (None, "n") and re.fullmatch(r"-?\d+\.0+", text):
                    text = text.split(".")[0]
            cells.append(_clean(text))
        rows.append(cells)
        if len(rows) > MAX_ROWS + 50:
            break
    note = "Read from the first sheet of the workbook." + (f" The other {sheets - 1} were not read." if sheets > 1 else "")
    return rows, [note]


# ---- the header ----------------------------------------------------------------------------------------------------

_NUMBERISH = re.compile(r"[\d$€£¥().,/\-\s:]+")


def _looks_like_header(cells: list[str]) -> bool:
    filled = [c for c in cells if c]
    if len(filled) < 3:
        return False
    wordy = [c for c in filled if not _NUMBERISH.fullmatch(c) and len(c) <= 60]
    return len(wordy) >= max(3, int(len(filled) * 0.8)) and len({c.lower() for c in filled}) >= len(filled) - 1


def find_header(rows: list[list[str]]) -> int:
    """The index of the header row: among the first 25 rows, the widest one that reads like column titles
    (several short pieces of text, none of them a number) and is followed by a row with about as many filled
    cells. A line of report details above the titles ("Run date ... Prepared by ...") is narrower and loses."""
    best, best_width, alone = -1, 0, -1
    for i, cells in enumerate(rows[:25]):
        if not _looks_like_header(cells):
            continue
        below = next((r for r in rows[i + 1:i + 6] if any(r)), None)
        width = len([c for c in cells if c])
        if below is None:
            alone = i                       # titles with nothing under them: `read` says so
        elif len([c for c in below if c]) >= max(2, width // 2) and width > best_width:
            best, best_width = i, width
    if best >= 0 or alone >= 0:
        return best if best >= 0 else alone
    raise FileProblem("No row of column titles was found in the first 25 rows. The list needs one row that names "
                      "its columns, with the balances under it.")


def read(data: bytes, filename: str = "") -> Table:
    """The file as a table of text. Raises FileProblem, in words for the screen, when it cannot be read."""
    if not data:
        raise FileProblem("The file is empty.")
    if len(data) > MAX_BYTES:
        raise FileProblem("The file is larger than 20 MB. Export only the dormant balances and upload that.")
    excel = data[:4] == b"PK\x03\x04"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise FileProblem("This is an Excel workbook of the old .xls kind. Save it as .xlsx or .csv and upload that.")
    if b"\x00" in data[:2000] and not excel and data[:2] not in (b"\xff\xfe", b"\xfe\xff"):
        raise FileProblem("The file is not a CSV or an Excel workbook.")
    rows, notes = _excel_rows(data) if excel else _csv_rows(data)
    invented = any(INVENTED_MARK in cell.upper() for row in rows[:5] for cell in row) or INVENTED_MARK in filename.upper()
    at = find_header(rows)
    header = list(rows[at])
    while header and not header[-1]:
        header.pop()
    if len(header) > MAX_COLUMNS:
        raise FileProblem(f"The list has more than {MAX_COLUMNS} columns. Export only the columns that describe "
                          "the owner and the balance.")
    seen: dict[str, int] = {}
    for i, title in enumerate(header):          # an untitled or repeated column still needs a name of its own
        title = title or f"Column {i + 1}"
        seen[title.lower()] = seen.get(title.lower(), 0) + 1
        header[i] = title if seen[title.lower()] == 1 else f"{title} ({seen[title.lower()]})"
    body, numbers = [], []
    for offset, cells in enumerate(rows[at + 1:], start=at + 2):
        if not any(cells):
            continue
        cells = (cells + [""] * len(header))[:len(header)]
        body.append(cells)
        numbers.append(offset)
        if len(body) > MAX_ROWS:
            raise FileProblem(f"The list has more than {MAX_ROWS:,} rows. Upload it in parts.")
    if not body:
        raise FileProblem("The list has column titles and no rows under them.")
    if at:
        notes.append(f"The column titles are on row {at + 1}; the {at} {'row' if at == 1 else 'rows'} above "
                     "were skipped.")
    return Table(header=header, rows=body, row_numbers=numbers, header_row=at + 1,
                 kind="excel" if excel else "csv", invented=invented, notes=notes)


# ---- writing a small workbook, for the invented file and the tests ---------------------------------------------------

def write_excel(rows: list[list], date_columns: set[int] | None = None) -> bytes:
    """A minimal .xlsx with one sheet. `date_columns` are written as Excel day counts with a date style, the
    way a real export stores dates; every other cell is text or a number."""
    from xml.sax.saxutils import escape

    date_columns = date_columns or set()

    def ref(col: int, row: int) -> str:
        letters = ""
        col += 1
        while col:
            col, rem = divmod(col - 1, 26)
            letters = chr(65 + rem) + letters
        return f"{letters}{row}"

    out = []
    for r, cells in enumerate(rows, start=1):
        line = []
        for c, value in enumerate(cells):
            if value is None or value == "":
                continue
            if isinstance(value, (date, datetime)) and c in date_columns:
                day = value if isinstance(value, date) and not isinstance(value, datetime) else value.date()
                line.append(f'<c r="{ref(c, r)}" s="1"><v>{(day - date(1899, 12, 30)).days}</v></c>')
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                line.append(f'<c r="{ref(c, r)}"><v>{value}</v></c>')
            else:
                line.append(f'<c r="{ref(c, r)}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>')
        out.append(f'<row r="{r}">{"".join(line)}</row>')
    main = _NS["m"]
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                               '<Default Extension="xml" ContentType="application/xml"/>'
                               '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                               '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                               '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{main}" xmlns:r="{_NS["r"]}">'
                           '<sheets><sheet name="Dormant balances" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                                      '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        "xl/styles.xml": f'<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="{main}"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
                         '<fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="1"><border/></borders>'
                         '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                         '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                         '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{main}"><sheetData>{"".join(out)}</sheetData></worksheet>',
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as book:
        for name, text in files.items():
            book.writestr(name, text)
    return buffer.getvalue()
