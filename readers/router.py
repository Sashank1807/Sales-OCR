"""Decide how each page should be read.

The decision is made **per page**, not per file. A PDF routinely mixes native
pages with scanned ones - in the sample corpus 6 of 79 PDFs do - so a
file-level verdict would send half a document down the wrong path.

The extension chooses the family; it never decides whether a PDF page has a
usable text layer. That is measured: how many words the page yields, how much
of it is alphanumeric, and whether the words carry sane geometry. A scanned
page sometimes carries a scrap of a text layer (a stamp, a footer, a previous
OCR pass), and character count alone would be fooled by it.
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

__all__ = ["PageKind", "PageRef", "RouterConfig", "classify_file", "classify_paths"]

SPREADSHEET_SUFFIXES = {".xlsx", ".xlsm", ".xltx", ".xls", ".csv"}
#: `.jfif` is JPEG under another name, and `.heic` is what an iPhone camera
#: saves by default - both arrive in the corpus as ordinary phone photos.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".jfif", ".bmp", ".webp", ".tif", ".tiff",
                  ".heic", ".heif"}
PDF_SUFFIXES = {".pdf"}


class PageKind(str, Enum):
    EXCEL = "excel"
    PDF_TEXT = "pdf_text"
    IMAGE = "image"
    TEXT = "text"


@dataclass
class RouterConfig:
    #: Below this many extracted words a PDF page is treated as scanned.
    min_words: int = 15
    #: A usable text layer is mostly letters and digits, not stray glyphs.
    min_alnum_ratio: float = 0.50
    #: Words must carry non-degenerate boxes for the geometry to work.
    min_boxed_ratio: float = 0.80
    #: A text layer whose words carry symbols no report prints (`£`, `•`, `°`
    #: inside words) at this share or more is a garbled overlay, and the page is
    #: read with OCR instead. Measured over 1,212 text-layer pages of JUNE and
    #: MAY: 1,189 have none; the garbled overlays sit at 2.5-7.4%.
    #: A text layer more invisible than this is an OCR layer laid over a scan,
    #: not a document's own text. Measured across 990 MAY text-layer pages the
    #: signal is binary: 382 of the first 400 are wholly visible, 18 are wholly
    #: invisible, and nothing sits between.
    max_invisible_ratio: float = 0.9
    max_garbled_ratio: float = 0.02
    #: Below this many words a few symbols (a `©` footer) are not evidence.
    garbled_min_words: int = 30


@dataclass
class PageRef:
    """One unit of work: a file, a page or sheet within it, and how to read it."""

    path: Path
    kind: PageKind
    page_index: int = 0
    page_count: int = 1
    label: str = ""
    reason: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def page_number(self) -> int:
        return self.page_index + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "kind": self.kind.value,
            "page_index": self.page_index,
            "page_count": self.page_count,
            "label": self.label,
            "reason": self.reason,
            "metrics": self.metrics,
        }


#: Characters above ASCII that genuine reports do print.
_TYPOGRAPHIC = frozenset(chr(c) for c in (0x20B9, 0x2013, 0x2014, 0x2018, 0x2019, 0x201C,
                                          0x201D, 0x2026, 0x00A9, 0x00AE, 0x00A0))


def _probe_pdf_page(page, config: RouterConfig) -> tuple[PageKind, str, dict[str, Any]]:
    """Measure a PDF page's text layer and decide whether it is usable."""
    try:
        words = page.get_text("words")
    except Exception as exc:
        return (PageKind.IMAGE, f"text extraction failed ({type(exc).__name__}); "
                                "falling back to OCR", {})

    texts = [w[4] for w in words if len(w) > 4 and str(w[4]).strip()]
    joined = "".join(texts)
    alnum = sum(1 for ch in joined if ch.isalnum())
    boxed = sum(1 for w in words
                if len(w) > 4 and (w[2] - w[0]) > 0 and (w[3] - w[1]) > 0)

    metrics = {
        "words": len(texts),
        "chars": len(joined),
        "alnum_ratio": round(alnum / len(joined), 3) if joined else 0.0,
        "boxed_ratio": round(boxed / len(words), 3) if words else 0.0,
    }

    if len(texts) < config.min_words:
        return (PageKind.IMAGE,
                f"only {len(texts)} words in the text layer "
                f"(need {config.min_words})", metrics)
    if metrics["alnum_ratio"] < config.min_alnum_ratio:
        return (PageKind.IMAGE,
                f"text layer is {metrics['alnum_ratio']:.0%} alphanumeric "
                f"(need {config.min_alnum_ratio:.0%}); likely artefacts", metrics)
    if metrics["boxed_ratio"] < config.min_boxed_ratio:
        return (PageKind.IMAGE,
                f"only {metrics['boxed_ratio']:.0%} of words carry usable boxes",
                metrics)

    # Invisible text (PDF render mode 3) is not drawn on the page. Scanning
    # software writes it behind the image so the scan can be searched, which
    # means the characters are an OCR engine's reading of the pixels - and a
    # reading this pipeline did not do, cannot score for confidence, and would
    # otherwise hand on as `exact`: "not subject to reading error" (CLAUDE.md
    # s5). 25 pages of the two corpora were doing exactly that, 4,797 cells of
    # someone else's OCR that no one would ever review. The page is a scan and
    # is read as one.
    try:
        trace = page.get_texttrace()
    except Exception:
        trace = []
    if trace:
        invisible = sum(1 for span in trace if span.get("type") == 3)
        metrics["invisible_ratio"] = round(invisible / len(trace), 3)
        if metrics["invisible_ratio"] >= config.max_invisible_ratio:
            return (PageKind.IMAGE,
                    f"{metrics['invisible_ratio']:.0%} of the text layer is invisible: "
                    "an OCR layer over a scan, not the document's own text; "
                    "reading the page from its pixels", metrics)

    garbled = [t for t in texts if any(ord(c) > 126 and c not in _TYPOGRAPHIC for c in t)]
    metrics["garbled_ratio"] = round(len(garbled) / len(texts), 3) if texts else 0.0
    if len(texts) >= config.garbled_min_words and metrics["garbled_ratio"] >= config.max_garbled_ratio:
        return (PageKind.IMAGE,
                f"text layer is garbled ({metrics['garbled_ratio']:.1%} of words carry "
                f"stray symbols, e.g. {garbled[0]!r}); reading the page with OCR", metrics)

    return (PageKind.PDF_TEXT,
            f"{len(texts)} words with coordinates; text layer is usable", metrics)


def _classify_spreadsheet(path: Path) -> list[PageRef]:
    """One unit of work per sheet, so multi-sheet workbooks are not flattened."""
    from .excel_reader import sniff_format
    # The contents decide, not the name: `.xls` files that are really `.xlsx`.
    kind = sniff_format(path)
    if kind in ("docx", "html"):
        return [PageRef(path=path, kind=PageKind.EXCEL, page_index=0, page_count=1,
                        label=path.stem, reason=f"{kind} export with tables")]
    suffix = {"xlsx": ".xlsx", "xls": ".xls", "text": ".csv"}[kind]
    if suffix == ".csv":
        return [PageRef(path=path, kind=PageKind.EXCEL, page_index=0, page_count=1,
                        label=path.stem, reason="csv file")]

    names: list[str] = []
    try:
        if suffix == ".xls":
            import xlrd
            book = xlrd.open_workbook(str(path), on_demand=True)
            names = list(book.sheet_names())
            book.release_resources()
        else:
            import openpyxl
            book = openpyxl.load_workbook(io.BytesIO(path.read_bytes()), read_only=True, data_only=True)
            names = [ws.title for ws in book.worksheets if ws.sheet_state == "visible"]
            book.close()
    except Exception as exc:
        return [PageRef(path=path, kind=PageKind.EXCEL, page_index=0, page_count=1,
                        label=path.stem,
                        reason=f"sheet listing failed ({type(exc).__name__}: {exc})")]

    if not names:
        return [PageRef(path=path, kind=PageKind.EXCEL, page_index=0, page_count=1,
                        label=path.stem, reason="no visible sheets")]
    return [PageRef(path=path, kind=PageKind.EXCEL, page_index=i, page_count=len(names),
                    label=name, reason=f"sheet {i + 1} of {len(names)}")
            for i, name in enumerate(names)]


def classify_file(path: str | Path, config: RouterConfig | None = None) -> list[PageRef]:
    """Every unit of work in one file, each with the reader that should handle it."""
    config = config or RouterConfig()
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    suffix = path.suffix.lower()

    if suffix in SPREADSHEET_SUFFIXES:
        return _classify_spreadsheet(path)

    from .text_reader import TEXT_SUFFIXES, text_page_count
    if suffix in TEXT_SUFFIXES:
        total = text_page_count(path)
        return [PageRef(path=path, kind=PageKind.TEXT, page_index=i, page_count=total,
                        label=f"p{i + 1}", reason="plain-text report")
                for i in range(total)]

    if suffix in IMAGE_SUFFIXES:
        return [PageRef(path=path, kind=PageKind.IMAGE, page_index=0, page_count=1,
                        label=path.stem, reason=f"image file ({suffix})")]

    if suffix in PDF_SUFFIXES:
        return _classify_pdf(path, config)

    return _classify_by_content(path, config)


def _classify_pdf(path: Path, config: RouterConfig) -> list[PageRef]:
    """One unit of work per page, each routed by its own text layer."""
    import pymupdf
    refs: list[PageRef] = []
    with pymupdf.open(str(path)) as doc:
        total = doc.page_count
        for index in range(total):
            kind, reason, metrics = _probe_pdf_page(doc[index], config)
            refs.append(PageRef(path=path, kind=kind, page_index=index,
                                page_count=total, label=f"p{index + 1}",
                                reason=reason, metrics=metrics))
    return refs


def _classify_by_content(path: Path, config: RouterConfig) -> list[PageRef]:
    """A name the router does not know: decide from what the file holds.

    The MAY corpus has a PDF saved with no extension (`DOC-20260602-WA0053_`),
    a printer file named `.dat`, a text printout named `.Doc`, a Word export
    and an HTML page. Every one was refused by name although its contents are
    a kind this pipeline reads.
    """
    with open(path, "rb") as handle:
        head = handle.read(4096)
    if head.startswith(b"%PDF"):
        return _classify_pdf(path, config)
    if head.startswith(bytes([0xFF, 0xD8, 0xFF])) or head.startswith(bytes([0x89, 0x50, 0x4E, 0x47])):
        return [PageRef(path=path, kind=PageKind.IMAGE, page_index=0, page_count=1,
                        label=path.stem, reason="image, recognised from its contents")]
    from .excel_reader import sniff_format
    kind = sniff_format(path)
    if kind in ("docx", "html", "xlsx", "xls"):
        return _classify_spreadsheet(path)
    printable = sum(1 for b in head if 32 <= b < 127 or b in (9, 10, 12, 13, 27))
    if head and printable >= 0.9 * len(head):
        from .text_reader import text_page_count
        total = text_page_count(path)
        return [PageRef(path=path, kind=PageKind.TEXT, page_index=i, page_count=total,
                        label=f"p{i + 1}", reason="plain-text report, recognised from its contents")
                for i in range(total)]
    raise ValueError(f"unsupported file type: {path.suffix or '(none)'} for {path.name}")


def classify_paths(paths: Sequence[str | Path],
                   config: RouterConfig | None = None) -> list[PageRef]:
    refs: list[PageRef] = []
    for path in paths:
        refs.extend(classify_file(path, config))
    return refs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify pages by how to read them")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)

    for path in args.paths:
        try:
            refs = classify_file(path)
        except Exception as exc:
            print(f"{path}: {type(exc).__name__}: {exc}")
            continue
        counts: dict[str, int] = {}
        for ref in refs:
            counts[ref.kind.value] = counts.get(ref.kind.value, 0) + 1
        summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
        print(f"{Path(path).name}  ({len(refs)} unit(s): {summary})")
        for ref in refs:
            print(f"    {ref.label:<6} {ref.kind.value:<9} {ref.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
