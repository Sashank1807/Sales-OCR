"""End to end: a file path in, verified two-layer output out.

    file -> router -> reader -> column_mapper -> validator -> result

The router decides per page; the readers all emit the same grid contract; Stage
A and Stage B are untouched by which reader produced a page.

Pages of the same file go through ``validate_pages`` together, so a printed
total that carries forward from an earlier page is recognised as cumulative
rather than counted twice.

    python pipeline.py report.pdf
    python pipeline.py report.pdf --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from column_mapper import ColumnMapper, MapperConfig, VLMColumnResolver
from readers.contract import Grid
from readers.geometry import GeometryConfig
from readers.router import PageKind, PageRef, RouterConfig, classify_file
from schema import (STOCK_FLOW_ROLES, CellStatus, Document, MappingMethod, Role,
                    SectionKind, load_grid)
from validator import ValidationReport, ValidatorConfig, Validator, validate_pages

__all__ = ["PageResult", "PipelineResult", "PageHealth", "HealthConfig",
           "assess_health", "process_file", "read_page"]


@dataclass
class HealthConfig:
    #: Beyond this a page is slow enough to be worth reporting.
    slow_seconds: float = 30.0
    #: A page with tokens but fewer bands than this did not resolve columns.
    min_column_bands: int = 2
    #: A page of at most this many lines, one of them a total, is the closing
    #: page of a table that ended on the page before.
    closing_page_lines: int = 3
    #: A page of at most this many lines whose only figures are totals.
    closing_page_max_lines: int = 8


_CLOSING_TOTAL_RE = re.compile(r"\b(?:grand\s+)?total\b", re.IGNORECASE)
#: A figure standing on its own, not a digit inside a word (`30ML`, `P1`).
_FIGURE_RE = re.compile(r"(?<![\w/:.\-])\d+(?:\.\d+)?(?![\w/:,\-])")
_DATE_TEXT_RE = re.compile(r"[A-Za-z]{3,9}\.?\s?\d{1,2},\s?\d{4}")


def _looks_blank(ref: PageRef) -> bool:
    """No pixel of the page is dark: a blank scan, not a failed read."""
    try:
        import numpy as np
        with open(ref.path, "rb") as handle:
            is_pdf = handle.read(5).startswith(b"%PDF")
        if is_pdf:
            import pymupdf
            with pymupdf.open(str(ref.path)) as doc:
                pixmap = doc[ref.page_index].get_pixmap(matrix=pymupdf.Matrix(0.5, 0.5))
                image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height, pixmap.width, pixmap.n)[:, :, :3]
        else:
            from PIL import Image
            with Image.open(ref.path) as picture:
                image = np.asarray(picture.convert("RGB").reduce(4))
        return float((image.mean(axis=2) < 128).mean()) < 0.0005
    except Exception:
        return False


@dataclass
class PageHealth:
    """Whether a page succeeded, judged at page level rather than cell level.

    Cell metrics cannot see a page that produced no cells: it has no flagged
    cells, no silent errors and a perfect coverage ratio over zero tokens. A
    page can be cell-clean and still be a total failure, so the two are
    reported separately.
    """

    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "problems": list(self.problems),
                "warnings": list(self.warnings)}


def assess_health(page: "PageResult", config: HealthConfig | None = None) -> PageHealth:
    """Page-level checks, independent of anything the cells say."""
    config = config or HealthConfig()
    health = PageHealth()

    if not page.ok:
        health.problems.append(f"page failed: {page.error}")
        return health

    grid, document = page.grid, page.document
    cells = grid.cell_count if grid else 0
    tokens = len(grid.tokens) if grid else 0

    if cells == 0 and tokens == 0 and page.ref.kind in (PageKind.EXCEL, PageKind.TEXT):
        # An empty `Sheet2` holds nothing to read. The file's contents say so
        # exactly, so this is a blank page, not a failure to read one; seven
        # such sheets were counted unhealthy across the JUNE corpus. A photo
        # or a scan that yields no text is still a problem - there, nothing
        # read is not the same as nothing printed.
        health.warnings.append("blank sheet: nothing to read")
        return health
    if cells == 0 and tokens == 0 and page.ref.kind is PageKind.IMAGE and _looks_blank(page.ref):
        # A scanned page with no ink on it (`NEW DELIGHT THRISSUR ... .pdf` p2:
        # no pixel darker than mid-grey). Nothing read because nothing is
        # printed - checked from the pixels, not assumed from the empty read.
        health.warnings.append("blank page: no ink on the image")
        return health
    if cells == 0:
        health.problems.append(
            f"no cells produced (read {tokens} token(s) in {page.seconds:.0f}s)")
    # Only readers that reconstruct geometry have column bands to resolve.
    # A spreadsheet arrives already addressed, so an empty band list there is
    # correct rather than a failure to find the columns.
    reconstructs_geometry = page.ref.kind is not PageKind.EXCEL
    if (reconstructs_geometry and tokens and grid is not None
            and len(grid.column_bands) < config.min_column_bands):
        health.problems.append(
            f"{tokens} token(s) read but only {len(grid.column_bands)} column "
            "band(s) resolved; the table structure was not recovered")

    tabular = [s for s in (document.sections if document else [])
               if s.kind is SectionKind.TABULAR]
    lines = [r for r in (grid.rows if grid else []) if any(c.text.strip() for c in r.cells)]
    line_texts = [" ".join(c.text for c in r.cells) for r in lines]
    # Dates (`01/05/2026`, `Jun 1,2026`) and page numbers (`Page No.3`) are not
    # figures of the table.
    with_figures = [t for t in line_texts if _FIGURE_RE.search(_DATE_TEXT_RE.sub(" ", t))]
    # Either a short page with a total on it, or a page whose only lines with
    # figures are totals under a repeated heading (`SRABANRI DISTRIBUORS.PDF`
    # p3: banner, headings, `GRAND TOTAL`).
    closing_only = bool(lines) and (
        (len(lines) <= config.closing_page_lines
         and any(_CLOSING_TOTAL_RE.search(t) for t in line_texts))
        or (bool(with_figures) and len(lines) <= config.closing_page_max_lines
            and all(_CLOSING_TOTAL_RE.search(t) for t in with_figures)))
    if cells and not tabular and closing_only:
        # The last page of a report that holds nothing but its `GRAND TOTAL`
        # line and a footer (`Hetero HealthCare ... Jun 2026.PDF` p8,
        # `Versha-Jodhpur.PDF` p3): the table ended on the page before. There
        # is no table to find here, so it is not a failure to find one.
        health.warnings.append("closing page: only a total line, the table ended earlier")
    elif cells and not tabular:
        # Every reader here is pointed at a stock report, so a page with
        # content and no table is a failure to find one, not an empty page.
        health.problems.append(
            f"no tabular section found among {len(document.sections)} section(s)")

    if page.seconds > config.slow_seconds:
        health.warnings.append(f"took {page.seconds:.0f}s")
    return health


@dataclass
class PageResult:
    ref: PageRef
    grid: Grid | None = None
    document: Document | None = None
    report: ValidationReport | None = None
    error: str = ""
    seconds: float = 0.0
    health: "PageHealth | None" = None

    @property
    def ok(self) -> bool:
        return self.error == "" and self.document is not None

    @property
    def healthy(self) -> bool:
        return self.ok and (self.health is None or self.health.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref.to_dict(),
            "error": self.error,
            "seconds": round(self.seconds, 3),
            "grid_notes": list(self.grid.notes) if self.grid else [],
            "health": self.health.to_dict() if self.health else None,
            "document": self.document.to_dict() if self.document else None,
            "report": self.report.to_dict() if self.report else None,
        }


@dataclass
class PipelineResult:
    path: Path
    pages: list[PageResult] = field(default_factory=list)

    @property
    def ok_pages(self) -> list[PageResult]:
        return [p for p in self.pages if p.ok]

    @property
    def failed_pages(self) -> list[PageResult]:
        return [p for p in self.pages if not p.ok]

    def counts(self) -> dict[str, int]:
        totals = {"exact": 0, "verified": 0, "flagged": 0, "unchecked": 0,
                  "total_cells": 0, "pixel_cells": 0, "review_cells": 0,
                  "structural_flags": 0}
        for page in self.ok_pages:
            if not page.report:
                continue
            for key in totals:
                totals[key] += page.report.counts.get(key, 0)
        return totals

    @property
    def review_cells(self) -> int:
        """Pixel-derived cells a human has to look at.

        Deterministic cells are excluded: they cannot have been misread, so
        there is no transcription to review. Structural flags on them are
        reported separately.
        """
        return self.counts()["review_cells"]

    @property
    def structural_flags(self) -> int:
        return self.counts()["structural_flags"]

    @property
    def unhealthy_pages(self) -> list["PageResult"]:
        """Pages that failed at page level, whatever their cells look like."""
        return [p for p in self.pages if not p.healthy]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "pages": [p.to_dict() for p in self.pages],
            "counts": self.counts(),
            "review_cells": self.review_cells,
        }


def read_page(ref: PageRef, geometry: GeometryConfig | None = None,
              ocr_tokens: "Sequence[Any] | None" = None) -> Grid:
    """Dispatch one unit of work to the reader the router chose.

    ``ocr_tokens`` are tokens already recognised for this page - the viewer
    saves every page it OCRs - and are used in place of running the engine
    again. They are only ever consulted for pages the router sends to OCR: a
    page with a usable text layer or a spreadsheet is still read from its
    deterministic source, whatever OCR happened to see (s4.1).
    """
    if ref.kind is PageKind.EXCEL:
        from readers.excel_reader import read_excel
        return read_excel(ref.path, sheet_index=ref.page_index, page=ref.page_number)

    if ref.kind is PageKind.TEXT:
        from readers.text_reader import read_text_page
        return read_text_page(ref.path, page_index=ref.page_index, config=geometry)

    if ref.kind is PageKind.PDF_TEXT:
        from readers.pdf_text_reader import read_pdf_text
        return read_pdf_text(ref.path, page_index=ref.page_index, config=geometry)

    from readers.ocr_reader import read_image, read_pdf_page_ocr
    if ocr_tokens is not None:
        from readers.geometry import build_grid
        grid = build_grid(list(ocr_tokens), page=ref.page_number, source="ocr",
                          origin=str(ref.path), page_label=f"p{ref.page_number}",
                          config=geometry)
        grid.notes.append("built from previously saved OCR tokens")
        return grid
    # By content, not name: a PDF saved without an extension is still a PDF.
    with open(ref.path, "rb") as handle:
        is_pdf = handle.read(5).startswith(b"%PDF")
    if is_pdf:
        return read_pdf_page_ocr(ref.path, page_index=ref.page_index, config=geometry)
    return read_image(ref.path, page=ref.page_number, config=geometry)


_HEADER_METHODS = (MappingMethod.HEADER_EXACT, MappingMethod.HEADER_FUZZY,
                   MappingMethod.HEADER_AND_ARITHMETIC)


def _heading_backed(origin, source_columns: list) -> bool:
    """Does a heading on the source page stand behind this column's role?

    Directly, when the heading itself matched. Or indirectly: once headings fix
    one term on each side of the equation - here opening and issue - `o + r - i = c` pins receipt and closing uniquely, so an
    arithmetic role on that page is anchored rather than guessed. `11.pdf` p1
    names `Op. Qty` and `Issue` by heading and `Recevied Qty` and `Cl.Stock` by
    arithmetic, the typo defeating the vocabulary, and all four are sound.

    What must not travel is arithmetic nothing anchored. `DOC-20260703-WA0021.pdf`
    p14 inherited four roles from source columns with no heading at all, which
    passed the source page's unanchored fit off as heading-backed on the next.
    """
    if origin.method in _HEADER_METHODS:
        return True
    if origin.method is not MappingMethod.ARITHMETIC or origin.orientation_ambiguous:
        return False
    # One heading is not an anchor. `Adobe Scan Jul 05, 2026.pdf` p4 has a
    # heading only for opening; its fit then called `Near Expiry` receipt and
    # `MSR Price` closing, and the next section inherited both. It takes a
    # heading on *each* side of the equals sign to pin the other two terms.
    flows = {c.role.value.rpartition("_")[0] for c in source_columns
             if c.method in _HEADER_METHODS and c.role in STOCK_FLOW_ROLES}
    return bool(flows & {"opening", "receipt"}) and bool(flows & {"issue", "closing"})


def _column_spans(section) -> dict[int, tuple[float, float]]:
    """Where each column actually sits on the page, from its own data cells.

    Column *index* is not stable across the pages of one file: a continuation
    page has no header row to bridge a gutter, so the projection can resolve a
    different number of bands - `11.pdf` finds 7 columns on page 1 and 8 on
    page 2 for the same table. Position is stable where the index is not.
    """
    spans: dict[int, tuple[float, float]] = {}
    for column in section.columns:
        left: list[float] = []
        right: list[float] = []
        for row in section.data_rows:
            cell = row.cell_at(column.index)
            if cell is None or cell.is_blank or not cell.provenance.bbox:
                continue
            x0, _, x1, _ = cell.provenance.bbox
            left.append(x0)
            right.append(x1)
        if left:
            left.sort()
            right.sort()
            spans[column.index] = (left[len(left) // 2], right[len(right) // 2])
    return spans


def _matching_column(index: int,
                     spans: dict[int, tuple[float, float]],
                     source_spans: dict[int, tuple[float, float]],
                     source_columns: list):
    """The earlier page's column occupying the same place on the page."""
    here = spans.get(index)
    if here is None:
        return None
    best, best_overlap = None, 0.0
    for column in source_columns:
        there = source_spans.get(column.index)
        if there is None:
            continue
        overlap = min(here[1], there[1]) - max(here[0], there[0])
        if overlap > best_overlap:
            best, best_overlap = column, overlap
    return best


def _inherit_headers_across_pages(documents: list[Document]) -> None:
    """Carry a column mapping onto the continuation pages that follow it.

    A paginated report prints its column headings once. Page 2 of the same
    statement repeats the company banner and then goes straight into rows, so
    the mapper sees no header at all: it scores the address block as one, and
    the roles fall to arithmetic alone. That is the worst case for arithmetic,
    because ``o + r - i = c`` and ``o + r - c = i`` are the same statement and
    an opening/receipt swap satisfies both readings equally. On `11.pdf` page 2
    it produced all four roles transposed at confidence 0.80, with the real
    headings sitting on page 1 of the same file.

    So a section that no heading reached inherits from the nearest earlier page
    whose section *was* named, provided the two agree on their column count -
    the cheapest available evidence that it is the same table continued. The
    roles arrive capped below the VLM threshold and marked ``inherited``, never
    outranking a heading the page found for itself, and the header text comes
    with them so the raw layer records where the name came from.

    Nothing here is document-specific: the rule is that a table continued onto
    another page keeps its columns, which is a property of pagination.
    """
    last: list | None = None            # the last section a heading reached
    last_spans: dict[int, tuple[float, float]] = {}
    for document in documents:
        for section in document.sections:
            if section.kind is not SectionKind.TABULAR or not section.columns:
                continue
            named = [c for c in section.columns if c.method in _HEADER_METHODS]
            spans = _column_spans(section)

            if named:
                last, last_spans = section.columns, spans
                continue

            if last is None or not spans or not last_spans:
                continue
            taken = {c.role for c in section.columns
                     if c.role is not Role.UNKNOWN and c.method in _HEADER_METHODS}
            adopted = 0
            for column in section.columns:
                origin = _matching_column(column.index, spans, last_spans, last)
                if origin is None or origin.role is Role.UNKNOWN or origin.role in taken:
                    continue
                # Only a role a heading stands behind is worth carrying to
                # another page - see _heading_backed.
                if not _heading_backed(origin, last):
                    continue
                # A weaker reading of the same role elsewhere on this page -
                # arithmetic or shape, never a heading, which `taken` already
                # excludes - gives way. Leaving it produced two `closing_value`
                # columns on `GENEX.pdf` p6.
                for other in section.columns:
                    if other is not column and other.role is origin.role:
                        other.add_evidence(
                            f"{other.role.value} withdrawn: an earlier page's heading "
                            f"places it in column {column.index}")
                        other.role = Role.UNKNOWN
                        other.confidence = 0.0
                        other.method = MappingMethod.NONE
                        other.orientation_ambiguous = False
                column.role = origin.role
                column.confidence = min(origin.confidence, 0.50)
                column.method = MappingMethod.INHERITED
                # Orientation travels with the role. This page's own arithmetic
                # could not orient issue against closing and said so; the
                # heading on the source page did orient them, and that is the
                # reading now adopted. Leaving this page's flag in place marked
                # 190 cells across four GENEX pages as a possible transposition
                # the source heading had already ruled out - while a role the
                # source page itself could not orient stays ambiguous here too.
                column.orientation_ambiguous = origin.orientation_ambiguous
                # `header_text` is the raw layer - the words this page prints -
                # and this page prints none here (s4.4). The inherited heading is
                # recorded as evidence, never written into the raw text.
                column.add_evidence(
                    f"inherited from an earlier page of this file, which named "
                    f"this column {origin.header_text!r}; this page carries no "
                    f"heading of its own")
                taken.add(origin.role)
                adopted += 1
            if adopted:
                section.notes.append(
                    f"no heading reached this section; {adopted} column(s) "
                    f"inherited from the last page that had one")


def process_file(path: str | Path,
                 router: RouterConfig | None = None,
                 geometry: GeometryConfig | None = None,
                 mapper: MapperConfig | None = None,
                 validator: ValidatorConfig | None = None,
                 vlm_resolver: VLMColumnResolver | None = None,
                 pages: Sequence[int] | None = None,
                 ocr_tokens: "dict[int, Sequence[Any]] | None" = None) -> PipelineResult:
    """Run one file all the way through.

    ``pages`` restricts the work to specific zero-based page indices, which is
    what lets the benchmark pin an exact set of pages. ``ocr_tokens`` maps a
    zero-based page index to tokens already recognised for it, so a page the
    viewer has OCR'd is not sent through the engine a second time.
    """
    path = Path(path)
    result = PipelineResult(path=path)

    refs = classify_file(path, router)
    if pages is not None:
        wanted = set(pages)
        refs = [r for r in refs if r.page_index in wanted]

    column_mapper = ColumnMapper(mapper, vlm_resolver)
    documents: list[Document] = []
    page_results: list[PageResult] = []

    for ref in refs:
        started = time.perf_counter()
        page = PageResult(ref=ref)
        try:
            cached = (ocr_tokens or {}).get(ref.page_index)
            grid = read_page(ref, geometry,
                             cached if ref.kind is PageKind.IMAGE else None)
            page.grid = grid
            rows, tokens, page_number, source = load_grid(grid.to_dict())
            page.document = column_mapper.map_document(rows, tokens, page_number, source)
            documents.append(page.document)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            page.error = f"{type(exc).__name__}: {exc}"
        page.seconds = time.perf_counter() - started
        page_results.append(page)

    _inherit_headers_across_pages(documents)

    # Validate the pages of a file together so cumulative totals resolve.
    if documents:
        reports = validate_pages(documents, validator)
        iterator = iter(reports)
        for page in page_results:
            if page.document is not None:
                page.report = next(iterator)

    for page in page_results:
        page.health = assess_health(page)

    result.pages = page_results
    return result


def _summarise(result: PipelineResult) -> str:
    lines = [f"{result.path.name}"]
    for page in result.pages:
        ref = page.ref
        head = f"  {ref.label:<8} {ref.kind.value:<9}"
        if not page.ok:
            lines.append(f"{head} FAILED  {page.error}")
            continue
        counts = page.report.counts if page.report else {}
        flagged = len(page.report.flagged) if page.report else 0
        lines.append(
            f"{head} {counts.get('total_cells', 0):>5} cells  "
            f"exact {counts.get('exact', 0):>5}  "
            f"verified {counts.get('verified', 0):>4}  "
            f"flagged {counts.get('flagged', 0):>4}  "
            f"unchecked {counts.get('unchecked', 0):>5}  "
            f"review {counts.get('review_cells', 0):>4}  "
            f"({flagged} finding(s), {page.seconds:.2f}s)")
        if page.document:
            for section in page.document.sections:
                roles = ", ".join(f"{c.index}:{c.role.value}" for c in section.columns
                                  if c.role.value != "unknown")
                lines.append(f"      section {section.index} [{section.kind.value}] "
                             f"{len(section.data_rows)} rows  {roles or '(no roles)'}")
        for note in (page.grid.notes if page.grid else []):
            lines.append(f"      grid: {note}")
        for problem in (page.health.problems if page.health else []):
            lines.append(f"      HEALTH: {problem}")
        for warning in (page.health.warnings if page.health else []):
            lines.append(f"      warn: {warning}")
    counts = result.counts()
    lines.append(f"  TOTAL {counts['total_cells']} cells; "
                 f"{result.review_cells} of {counts['pixel_cells']} pixel-derived "
                 f"cells need review; {result.structural_flags} structural flag(s)")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a document through the pipeline")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--pages", help="comma-separated zero-based page indices")
    args = parser.parse_args(argv)

    pages = [int(p) for p in args.pages.split(",")] if args.pages else None
    failures = 0
    for path in args.paths:
        try:
            result = process_file(path, pages=pages)
        except Exception as exc:
            print(f"{path}: {type(exc).__name__}: {exc}", file=sys.stderr)
            failures += 1
            continue
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
              if args.json else _summarise(result))
        failures += len(result.failed_pages)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
