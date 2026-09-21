"""Read a plain-text report: a printout saved as `.TXT` instead of sent to paper.

Distributor billing software often "prints to file". The result is a
fixed-width page - headings, dashed rules, columns aligned with spaces - and
its characters are the file's own, so like a PDF text layer there is no
reading step and nothing can be misread. Each run of non-space characters
becomes a token placed by its character column and line number, and the shared
geometry finds rows and column gutters exactly as it does for a text layer.

Pages are separated by form feeds, as a printer driver writes them.
"""

from __future__ import annotations

import re
from pathlib import Path

from .contract import Grid, Token
from .geometry import GeometryConfig, build_grid

__all__ = ["read_text_page", "text_page_count", "grid_from_lines", "looks_like_printout",
           "TEXT_SUFFIXES"]

TEXT_SUFFIXES = {".txt", ".prn"}

#: A character cell of a fixed-width page, in the same units the geometry uses
#: for a text layer. The height must exceed the width divided by the gutter
#: ratio, so one space between words is never taken for a column gutter while
#: two or more are.
CHAR_WIDTH = 6.0
LINE_HEIGHT = 12.0

_WORD_RE = re.compile(r"\S+")


#: Printer commands that take one parameter byte after their letter
#: (page length, margins, line spacing).
_ESC_WITH_PARAMETER = frozenset("CQlNJ3A$!W-")


def _strip_printer_codes(text: str) -> str:
    """Remove the printer's control codes, keep what it would have printed.

    A report "printed" to a `.dat` file carries the commands for the printer
    inline: `ESC C H` (page length), `ESC M`, `ESC E` / `ESC F` (bold on and
    off), SO for double width. Left in, they glue control bytes to the first
    word of a line. Form feeds, tabs and line ends are kept.
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\x1b":
            skip = 2 if i + 1 < len(text) and text[i + 1] in _ESC_WITH_PARAMETER else 1
            i += 1 + skip
            continue
        if ord(ch) < 32 and ch not in "\t\n\r\f":
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _decode(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return _strip_printer_codes(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    return _strip_printer_codes(raw.decode("latin-1"))   # never fails


def _pages(path: Path) -> list[str]:
    pages = _decode(path).split("\f")
    kept = [p for p in pages if p.strip()]
    return kept or [""]


def text_page_count(path: str | Path) -> int:
    return len(_pages(Path(path)))


#: Two or more spaces - how a fixed-width printout separates its columns.
_COLUMN_GAP_RE = re.compile(r"\S {2,}\S")


def looks_like_printout(lines: list[str]) -> bool:
    """Is this a fixed-width printout, one line per string?

    Most substantial lines must carry at least two column gaps. Used for a
    spreadsheet whose every row is a single cell holding a whole printed line
    (`HETRO.XLS`, `HETERO 010726.XLS`): read as cells, the page had one column
    and no table.
    """
    lines = [_normalise(l) for l in lines if l and len(l.strip()) >= 20]
    if len(lines) < 5:
        return False
    gapped = sum(1 for l in lines if len(_COLUMN_GAP_RE.findall(l)) >= 2)
    return gapped * 2 > len(lines)


def _normalise(line: str) -> str:
    # A non-breaking space is a space on a printed page.
    return line.replace("\u00a0", " ").expandtabs(8)


def grid_from_lines(lines: list[str], page: int, origin: str, label: str,
                    config: GeometryConfig | None = None) -> Grid:
    tokens: list[Token] = []
    for line_number, line in enumerate(lines):
        top = line_number * LINE_HEIGHT
        for match in _WORD_RE.finditer(_normalise(line)):
            tokens.append(Token(text=match.group(0), x0=match.start() * CHAR_WIDTH,
                                x1=match.end() * CHAR_WIDTH, y0=top, y1=top + LINE_HEIGHT,
                                confidence=1.0, index=len(tokens)))
    grid = build_grid(tokens, page=page, source="pdf_text", origin=origin,
                      page_label=label, config=config)
    grid.notes.append("fixed-width printout: characters placed by column and line")
    return grid


def read_text_page(path: str | Path, page_index: int = 0,
                   config: GeometryConfig | None = None) -> Grid:
    path = Path(path)
    pages = _pages(path)
    if not 0 <= page_index < len(pages):
        raise IndexError(f"page {page_index} out of range for {path.name} ({len(pages)} pages)")
    return grid_from_lines(pages[page_index].splitlines(), page_index + 1, str(path),
                           f"p{page_index + 1}", config)
