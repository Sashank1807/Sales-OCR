"""Read a native PDF page through its text layer. No recognition step.

PyMuPDF's ``get_text("words")`` hands back the exact characters the file
contains together with their coordinates. Those coordinates go through the same
clustering and gutter detection as OCR output, so a native page and a scanned
one produce grids of identical shape and the stages downstream cannot tell them
apart.

Because reconstruction is driven by coordinates, the order PyMuPDF happens to
return words in never matters - which is what makes a scrambled reading order a
non-issue here rather than a special case to repair.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .contract import Grid, Token
from .geometry import GeometryConfig, build_grid

__all__ = ["read_pdf_text", "tokens_for_page"]


def tokens_for_page(page) -> list[Token]:
    """Every positioned word on the page, as tokens.

    PyMuPDF returns ``(x0, y0, x1, y1, word, block_no, line_no, word_no)``.
    Confidence is 1.0: the characters are not being guessed at, they are
    recorded in the file.
    """
    tokens: list[Token] = []
    for entry in page.get_text("words"):
        if len(entry) < 5:
            continue
        x0, y0, x1, y1, text = entry[0], entry[1], entry[2], entry[3], str(entry[4])
        if not text.strip():
            continue
        tokens.append(Token(text=text.strip(), x0=float(x0), y0=float(y0),
                            x1=float(x1), y1=float(y1), confidence=1.0,
                            index=len(tokens)))
    return tokens


def read_pdf_text(path: str | Path, page_index: int = 0,
                  config: GeometryConfig | None = None) -> Grid:
    """Read one native PDF page into the grid contract."""
    import pymupdf

    path = Path(path)
    with pymupdf.open(str(path)) as doc:
        if not 0 <= page_index < doc.page_count:
            raise IndexError(f"page {page_index} out of range for {path.name} "
                             f"({doc.page_count} pages)")
        page = doc[page_index]
        tokens = tokens_for_page(page)
        rotation = page.rotation

    grid = build_grid(tokens, page=page_index + 1, source="pdf_text",
                      origin=str(path), page_label=f"p{page_index + 1}",
                      config=config)
    if rotation:
        grid.notes.append(f"page rotation {rotation} degrees reported by the file")
    if not tokens:
        grid.notes.append("text layer yielded no words")
    return grid
