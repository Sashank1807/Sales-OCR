"""Read a spreadsheet into the grid contract. No recognition step.

Excel already knows its own cell addresses, so this reader does not go through
the clustering geometry - there is nothing to reconstruct. It does synthesise
coordinates from row and column indices, because Stage A uses bounding boxes to
match a spanning two-tier header onto the columns beneath it, and a merged
Excel range is exactly that situation.

Values come from the cached results of formulas (``data_only=True``); a
workbook never opened by Excel will have no cache, and that is reported rather
than silently yielding blanks.
"""

from __future__ import annotations

import csv
import re
import io
import datetime as _dt
from pathlib import Path
from typing import Any, Sequence

from .contract import Grid, GridCell, GridRow, Token

__all__ = ["read_excel", "CELL_WIDTH", "ROW_HEIGHT"]

#: Synthetic geometry. The absolute numbers are arbitrary; only their ratios
#: matter, and they must leave a gutter between adjacent columns.
CELL_WIDTH = 100.0
ROW_HEIGHT = 20.0
_GUTTER = 8.0


def _format(value: Any) -> str:
    """Render a cell as text without inventing precision.

    Excel stores 50 as 50.0; printing "50.0" would put a decimal place into the
    raw layer that the source never had.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.strftime("%d/%m/%Y")
    return str(value).strip()


def _bbox(row: int, col: int, span: int = 1) -> tuple[float, float, float, float]:
    x0 = col * CELL_WIDTH
    return (x0, row * ROW_HEIGHT, x0 + span * CELL_WIDTH - _GUTTER,
            row * ROW_HEIGHT + ROW_HEIGHT - 4.0)


def _grid_from_matrix(matrix: Sequence[Sequence[str]], page: int, origin: str,
                      label: str, spans: dict[tuple[int, int], int] | None = None,
                      notes: Sequence[str] = ()) -> Grid:
    """Build a Grid from an already-addressed matrix of strings."""
    from .text_reader import grid_from_lines, looks_like_printout
    filled = [[str(t) for t in record if str(t).strip()] for record in matrix]
    single = [cells[0] for cells in filled if len(cells) == 1]
    if single and len(single) * 2 > sum(1 for cells in filled if cells)             and looks_like_printout(single):
        # A printout pasted into column A: its columns live inside the text.
        lines = [" ".join(cells) for cells in filled]
        grid = grid_from_lines(lines, page, origin, label)
        grid.notes.extend(notes)
        return grid
    spans = spans or {}
    rows: list[GridRow] = []
    tokens: list[Token] = []

    for r, record in enumerate(matrix):
        cells: list[GridCell] = []
        for c, text in enumerate(record):
            if not str(text).strip():
                continue
            span = spans.get((r, c), 1)
            box = _bbox(r, c, span)
            token = Token(text=str(text), x0=box[0], y0=box[1], x1=box[2], y1=box[3],
                          confidence=1.0, index=len(tokens))
            tokens.append(token)
            cells.append(GridCell(text=str(text), column=c, bbox=box,
                                  confidence=1.0, token_ids=[token.index]))
        if cells:
            rows.append(GridRow(index=len(rows), cells=cells,
                                bbox=(min(c.bbox[0] for c in cells),
                                      min(c.bbox[1] for c in cells),
                                      max(c.bbox[2] for c in cells),
                                      max(c.bbox[3] for c in cells))))

    return Grid(page=page, source="excel", rows=rows, tokens=tokens, origin=origin,
                page_label=label, notes=list(notes))


def sniff_format(path: Path) -> str:
    """"xlsx", "xls" or "text", from the file's first bytes, not its name.

    Three `.xls` files in the JUNE corpus are zip-packaged `.xlsx` workbooks
    and a `.csv` is one too; each was refused by the reader its extension
    picked (`Excel xlsx file; not supported`, `can't decode byte 0xe3`).
    """
    with open(path, "rb") as handle:
        head = handle.read(1024)
    if head.startswith(bytes([0x50, 0x4B, 0x03, 0x04])):          # zip: xlsx or docx
        import zipfile
        try:
            with zipfile.ZipFile(path) as archive:
                if "word/document.xml" in archive.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            pass
        return "xlsx"
    if head.startswith(bytes([0xD0, 0xCF, 0x11, 0xE0])):          # OLE2: xls
        return "xls"
    if re.search(rb"<\s*(html|table)\b", head, re.IGNORECASE):
        return "html"
    return "text"


def _csv_encoding(path: Path) -> str:
    """UTF-8 when the file is UTF-8, else the Windows code page exports use."""
    raw = path.read_bytes()
    try:
        raw.decode("utf-8-sig")
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "cp1252"


def _read_csv(path: Path, page: int) -> Grid:
    with open(path, "r", encoding=_csv_encoding(path), errors="replace", newline="") as handle:
        sample = handle.read(8192)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        matrix = [[_format(v) for v in record] for record in csv.reader(handle, dialect)]
    return _grid_from_matrix(matrix, page, str(path), path.stem,
                             notes=[f"csv, delimiter {dialect.delimiter!r}"])


def _read_xls(path: Path, sheet_index: int, page: int) -> Grid:
    import xlrd

    book = xlrd.open_workbook(str(path), formatting_info=False)
    try:
        sheet = book.sheet_by_index(sheet_index)
        matrix = [[_format(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
                  for r in range(sheet.nrows)]
        spans: dict[tuple[int, int], int] = {}
        for r0, r1, c0, c1 in getattr(sheet, "merged_cells", []) or []:
            spans[(r0, c0)] = c1 - c0
        return _grid_from_matrix(matrix, page, str(path), sheet.name, spans,
                                 notes=[f"xls sheet {sheet.name!r}"])
    finally:
        book.release_resources()


def _read_xlsx(path: Path, sheet_index: int, page: int) -> Grid:
    import openpyxl

    # A file object, not a name: openpyxl refuses by extension, and `.xls`
    # files that are really `.xlsx` are read by their contents.
    book = openpyxl.load_workbook(io.BytesIO(path.read_bytes()), read_only=False, data_only=True)
    try:
        visible = [ws for ws in book.worksheets if ws.sheet_state == "visible"]
        if not visible:
            raise ValueError("workbook has no visible sheets")
        sheet = visible[min(sheet_index, len(visible) - 1)]

        # A merged range holds its value in the top-left cell; the rest read as
        # None. Record the span so the header can be matched to the columns it
        # covers, and blank the followers so the value is not duplicated.
        spans: dict[tuple[int, int], int] = {}
        covered: set[tuple[int, int]] = set()
        for rng in sheet.merged_cells.ranges:
            r0, c0 = rng.min_row - 1, rng.min_col - 1
            spans[(r0, c0)] = rng.max_col - rng.min_col + 1
            for r in range(rng.min_row - 1, rng.max_row):
                for c in range(rng.min_col - 1, rng.max_col):
                    if (r, c) != (r0, c0):
                        covered.add((r, c))

        matrix: list[list[str]] = []
        formula_cells = 0
        for r, record in enumerate(sheet.iter_rows(values_only=False)):
            line: list[str] = []
            for c, cell in enumerate(record):
                if (r, c) in covered:
                    line.append("")
                    continue
                value = cell.value
                if isinstance(value, str) and value.startswith("="):
                    formula_cells += 1      # no cached result available
                    value = ""
                line.append(_format(value))
            matrix.append(line)

        notes = [f"xlsx sheet {sheet.title!r}"]
        if spans:
            notes.append(f"{len(spans)} merged range(s) preserved as column spans")
        if formula_cells:
            notes.append(f"{formula_cells} formula cell(s) had no cached value; "
                         "the workbook has not been recalculated")
        return _grid_from_matrix(matrix, page, str(path), sheet.title, spans, notes)
    finally:
        book.close()


def read_excel(path: str | Path, sheet_index: int = 0, page: int = 1) -> Grid:
    """Read one sheet (or a CSV) into the grid contract."""
    path = Path(path)
    kind = sniff_format(path)
    if kind in ("docx", "html"):
        from .document_reader import docx_matrix, html_matrix
        matrix = docx_matrix(path) if kind == "docx" else html_matrix(path)
        return _grid_from_matrix(matrix, page, str(path), path.stem,
                                 notes=[f"{kind} export: table cells read as addressed"])
    if kind == "xlsx":
        return _read_xlsx(path, sheet_index, page)
    if kind == "xls":
        return _read_xls(path, sheet_index, page)
    return _read_csv(path, page)
