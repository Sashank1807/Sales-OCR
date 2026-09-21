"""Tables inside Word (`.docx`) and web-page (`.htm`) exports.

Some billing software exports a stock statement as a Word document or an HTML
page instead of a PDF. Both hold the table as addressed cells - rows of cells
in document order - so, like a spreadsheet, there is nothing to read from
pixels and no geometry to reconstruct: the cells become a matrix and go
through the same grid builder as a sheet. Lines of text outside the tables
(the distributor's name, the period) become single-cell rows above them, so
report details are still found.

Standard library only: a `.docx` is a zip of XML, and HTML is parsed with
`html.parser`.
"""

from __future__ import annotations

import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

__all__ = ["docx_matrix", "html_matrix"]

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _text(element) -> str:
    return "".join(t.text or "" for t in element.iter(f"{_W}t")).strip()


def docx_matrix(path: Path) -> list[list[str]]:
    """Every paragraph and table row of a Word document, in order."""
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    body = root.find(f"{_W}body")
    matrix: list[list[str]] = []
    for block in (body if body is not None else []):
        if block.tag == f"{_W}p":
            line = _text(block)
            if line:
                matrix.append([line])
        elif block.tag == f"{_W}tbl":
            for tr in block.iter(f"{_W}tr"):
                row: list[str] = []
                for tc in tr.findall(f"{_W}tc"):
                    span = tc.find(f"{_W}tcPr/{_W}gridSpan")
                    width = int(span.get(f"{_W}val", "1")) if span is not None else 1
                    row.append(" ".join(_text(p) for p in tc.findall(f"{_W}p")).strip())
                    row.extend([""] * (width - 1))
                matrix.append(row)
    return matrix


class _TableParser(HTMLParser):
    """Rows of `<td>`/`<th>` cells, with `colspan` and `rowspan` laid out, and
    loose text between tables kept as single-cell rows."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.matrix: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.span = 1
        self.rowspan = 1
        self.pending: dict[int, tuple[int, str]] = {}   # column -> rows still covered
        self.loose: list[str] = []
        self.depth = 0

    def _flush_loose(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.loose)).strip()
        if text:
            self.matrix.append([text])
        self.loose = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self._flush_loose()
            self.depth += 1
        elif tag == "tr" and self.depth:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self._fill_rowspans()
            self.cell = []
            self.span = _int(attrs.get("colspan"))
            self.rowspan = _int(attrs.get("rowspan"))
        elif tag in ("br", "p", "div") and not self.depth:
            self._flush_loose()

    def _fill_rowspans(self) -> None:
        while self.row is not None and len(self.row) in self.pending:
            column = len(self.row)
            left, _ = self.pending[column]
            self.row.append("")
            if left <= 1:
                del self.pending[column]
            else:
                self.pending[column] = (left - 1, "")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            text = re.sub(r"\s+", " ", "".join(self.cell)).strip()
            start = len(self.row)
            self.row.append(text)
            self.row.extend([""] * (self.span - 1))
            if self.rowspan > 1:
                for column in range(start, start + self.span):
                    self.pending[column] = (self.rowspan - 1, "")
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self._fill_rowspans()
            if any(c for c in self.row):
                self.matrix.append(self.row)
            self.row = None
        elif tag == "table" and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        elif not self.depth:
            self.loose.append(data)

    def close(self):
        super().close()
        self._flush_loose()


def _int(value) -> int:
    try:
        return max(1, int(str(value).strip()))
    except (TypeError, ValueError):
        return 1


def html_matrix(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1")
    parser = _TableParser()
    parser.feed(text.replace(" ", " "))
    parser.close()
    return parser.matrix
