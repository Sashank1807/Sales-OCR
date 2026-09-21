#!/usr/bin/env python3
"""Batch-wise evaluation over an unlabelled corpus.

    python batch_test.py --plan                 # show how the corpus splits
    python batch_test.py --batch 1              # run one batch
    python batch_test.py --batch 1 2 3          # run several
    python batch_test.py --report 1 2 3         # write reports/batches-01-03.md
    python batch_test.py --corpus MAY --size 20 --batch 1 2 3 4 --report 1 2 3 4

`--corpus` names a folder in the workspace other than `JUNE/`. Its batches are
`--size` files mixed in the corpus's own proportions (see `mixed_batches`),
and its results and reports go to `reports/<corpus>/`, apart from JUNE's, so
the regression gate never mixes the two.

A batch is 5 PDFs, 3 scanned photographs and 2 WhatsApp images, in that fixed
shape, so each batch exercises all three readers rather than whichever files
happen to sort first. Composition is by *file name* - a WhatsApp export is
named `IMG-<date>-WA####` or `WhatsApp Image <date>` - which describes the test
set, not the documents. Nothing here looks at a distributor, a layout or a
column position; CLAUDE.md s4.3 is about extraction, and extraction sees only
what the pipeline sees.

There is no ground truth for this corpus (s8), so nothing below claims a
per-cell accuracy. What it reports is what the documents say about themselves:
coverage, whether rows keep their column shape, whether the stock equation
closes, and whether printed totals reconcile.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "JUNE"
RESULTS = ROOT / "reports" / "_results"
REPORTS = ROOT / "reports"

#: A WhatsApp export names itself. Both of the shapes the platform produces.
_WHATSAPP_RE = re.compile(r"(?:^IMG-\d{8}-WA\d+|whatsapp[ _]image)", re.IGNORECASE)
_IMAGE_EXT = {".jpg", ".jpeg", ".jfif", ".heic", ".png", ".bmp", ".tif", ".tiff"}
_PDF_EXT = {".pdf"}

#: Per batch, in this shape.
RECIPE = (("pdf", 5), ("scan", 3), ("whatsapp", 2))


_SHEET_EXT = {".xls", ".xlsx", ".xlsm", ".csv"}


def classify(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _PDF_EXT:
        return "pdf"
    if suffix in _IMAGE_EXT:
        return "whatsapp" if _WHATSAPP_RE.search(path.name) else "scan"
    return "other"


def mixed_kind(path: Path) -> str:
    """pdf, image, sheet or other - the grouping used for a mixed batch."""
    kind = classify(path)
    if kind in ("scan", "whatsapp"):
        return "image"
    if kind == "other" and path.suffix.lower() in _SHEET_EXT:
        return "sheet"
    return kind


def mixed_batches(corpus: Path, size: int, seed: int = 20260917) -> list[list[Path]]:
    """Batches of `size` files in the corpus's own proportions, reproducibly.

    Each kind is shuffled with a fixed seed - so a batch is not every file
    whose name starts with a digit - and batches are filled in the ratio the
    kinds occur, rounded, with at least one of every kind while it lasts. The
    same corpus and seed always give the same batches.
    """
    import random
    files = sorted((p for p in corpus.iterdir() if p.is_file()), key=lambda p: p.name.lower())
    pools: dict[str, list[Path]] = {}
    for path in files:
        pools.setdefault(mixed_kind(path), []).append(path)
    rng = random.Random(seed)
    for pool in pools.values():
        rng.shuffle(pool)
    total = sum(len(v) for v in pools.values())
    order = sorted(pools, key=lambda k: -len(pools[k]))
    quota = {k: max(1, round(size * len(pools[k]) / total)) for k in order}
    while sum(quota.values()) > size:
        biggest = max(quota, key=quota.get)
        quota[biggest] -= 1
    while sum(quota.values()) < size:
        quota[order[0]] += 1
    batches: list[list[Path]] = []
    cursor = {k: 0 for k in order}
    while any(cursor[k] < len(pools[k]) for k in order):
        batch: list[Path] = []
        for k in order:
            take = pools[k][cursor[k]:cursor[k] + quota[k]]
            cursor[k] += len(take)
            batch.extend(take)
        # top up from whatever is left when a kind runs out
        for k in order:
            while len(batch) < size and cursor[k] < len(pools[k]):
                batch.append(pools[k][cursor[k]])
                cursor[k] += 1
        batches.append(batch)
    return batches


def pools() -> dict[str, list[Path]]:
    """Group the corpus by kind, sorted so batches reproduce exactly."""
    grouped: dict[str, list[Path]] = {"pdf": [], "scan": [], "whatsapp": [], "other": []}
    for entry in sorted(CORPUS.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_file():
            grouped[classify(entry)].append(entry)
    return grouped


#: Files per batch once the recipe can no longer be filled.
REMAINDER_BATCH_SIZE = 10


def plan_batches() -> list[list[Path]]:
    """Recipe batches while every kind lasts, then the rest of the corpus.

    The recipe ran out of scans and WhatsApp photos after 7 batches and the
    other 165 files - 112 PDFs, 9 photos and every spreadsheet - were never
    tested. They now follow in batches of their own, so every file in the
    folder is measured. Recipe batches keep their numbers, so earlier
    results stay comparable.
    """
    grouped = pools()
    cursors = {kind: 0 for kind, _ in RECIPE}
    batches: list[list[Path]] = []
    while True:
        batch: list[Path] = []
        for kind, count in RECIPE:
            available = grouped[kind][cursors[kind]:cursors[kind] + count]
            if len(available) < count:
                batch = []
                break
            batch.extend(available)
            cursors[kind] += count
        if not batch:
            break
        batches.append(batch)
    rest = [p for kind in ("pdf", "scan", "whatsapp") for p in grouped[kind][cursors[kind]:]]
    rest += grouped["other"]
    for start in range(0, len(rest), REMAINDER_BATCH_SIZE):
        batches.append(rest[start:start + REMAINDER_BATCH_SIZE])
    return batches


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


@dataclass
class PageRow:
    file: str
    kind: str                 # how the batch recipe classified the file
    page: int
    source: str = ""          # what the router actually chose
    error: str = ""
    seconds: float = 0.0
    cells: int = 0
    exact: int = 0
    verified: int = 0
    flagged: int = 0
    unchecked: int = 0
    pixel_cells: int = 0
    review: int = 0
    structural_flags: int = 0
    tokens_seen: int = 0
    tokens_placed: int = 0
    coverage_loss: int = 0
    sections: int = 0
    tabular_sections: int = 0
    data_rows: int = 0
    columns: int = 0
    columns_mapped: int = 0
    healthy: bool = True
    health_problems: list[str] = field(default_factory=list)
    totals_checked: int = 0
    totals_reconciled: int = 0
    silent_errors: list[str] = field(default_factory=list)
    # alignment
    overflow_rows: int = 0
    unheaded_columns: int = 0
    ragged_rows: int = 0
    mixed_type_columns: int = 0
    equation_rows: int = 0
    equation_ok: int = 0
    #: cells holding several separate figures - columns that merged
    merged_cells: int = 0


def _alignment(document) -> dict[str, int]:
    """Signals that a row's cells did not land under the right headings.

    None of this needs ground truth. A row carrying more cells than the header
    names them, a column that is numeric on some rows and prose on others, a
    row whose populated count differs from the section's own mode - each is the
    document disagreeing with itself about its own shape.
    """
    from schema import SectionKind

    overflow = ragged = mixed = unheaded = 0
    for section in document.sections:
        if section.kind is not SectionKind.TABULAR:
            continue
        unheaded += len(section.unheaded_columns)
        # A column the header never named is not an overflow. The reader
        # already draws that distinction deliberately (CLAUDE.md s10 2a): a
        # column nearly every row fills is one the header failed to name, and
        # flagging those rows again here double-counts a fact about the header
        # as a fault in every row beneath it. On `11.pdf` p2 that alone
        # accounted for 44 of the batch's 59 "overflow" rows.
        known = set(section.unheaded_columns)
        named = section.header_column_count or len(section.columns)
        counts = Counter()
        for row in section.data_rows:
            populated = [c for c in row.cells if not c.is_blank]
            counts[len(populated)] += 1
            highest = max((c.column_index for c in populated
                           if c.column_index not in known), default=-1)
            if named and highest >= named:
                overflow += 1
        if counts:
            mode = counts.most_common(1)[0][0]
            ragged += sum(n for width, n in counts.items() if width != mode)

        for column in section.columns:
            numeric = text = 0
            for row in section.data_rows:
                cell = row.cell_at(column.index)
                if cell is None or cell.is_blank:
                    continue
                if cell.is_numeric:
                    numeric += 1
                else:
                    text += 1
            if numeric and text and min(numeric, text) >= 0.2 * (numeric + text):
                mixed += 1
    return {"overflow_rows": overflow, "ragged_rows": ragged,
            "mixed_type_columns": mixed, "unheaded_columns": unheaded}


def _equation_closure(document) -> tuple[int, int]:
    """How often the stock equation actually closes, where one was mapped."""
    from schema import Role, SectionKind

    rows = ok = 0
    for section in document.sections:
        if section.kind is not SectionKind.TABULAR:
            continue
        roles = {c.role: c.index for c in section.columns}
        need = (Role.OPENING_QTY, Role.RECEIPT_QTY, Role.ISSUE_QTY, Role.CLOSING_QTY)
        if not all(r in roles for r in need):
            continue
        o, r, i, c = (roles[x] for x in need)
        for row in section.data_rows:
            cells = [row.cell_at(x) for x in (o, r, i, c)]
            if any(x is None or not x.is_numeric for x in cells):
                continue
            rows += 1
            if abs((cells[0].value + cells[1].value - cells[2].value) - cells[3].value) <= 0.05:
                ok += 1
    return rows, ok


def measure_file(path: Path, kind: str) -> list[PageRow]:
    from pipeline import process_file
    from schema import CellStatus, SectionKind, Source
    from benchmarks.benchmark import _probe_silent_errors

    started = time.perf_counter()
    try:
        result = process_file(path)
    except Exception as exc:                        # a bad file must not stop the batch
        return [PageRow(file=path.name, kind=kind, page=1,
                        error=f"{type(exc).__name__}: {exc}",
                        seconds=round(time.perf_counter() - started, 2))]

    out: list[PageRow] = []
    # Column sums of earlier pages, by role, so a running total can be judged.
    carried: dict = {}
    for index, page in enumerate(result.pages, start=1):
        row = PageRow(file=path.name, kind=kind, page=index,
                      source=getattr(page.ref.kind, "value", str(page.ref.kind)),
                      seconds=round(page.seconds, 2), error=page.error)
        if not page.ok or page.document is None:
            out.append(row)
            continue

        document = page.document
        cells = [c for s in document.sections for r in s.rows for c in r.cells]
        row.cells = len(cells)
        row.exact = sum(1 for c in cells if c.status is CellStatus.EXACT)
        row.verified = sum(1 for c in cells if c.status is CellStatus.VERIFIED)
        row.flagged = sum(1 for c in cells if c.status is CellStatus.FLAGGED)
        row.unchecked = sum(1 for c in cells if c.status is CellStatus.UNCHECKED)
        pixel = [c for c in cells if not c.is_deterministic]
        row.pixel_cells = len(pixel)
        row.review = sum(1 for c in pixel
                         if c.status in (CellStatus.FLAGGED, CellStatus.UNCHECKED))
        row.structural_flags = sum(1 for c in cells
                                   if c.is_deterministic and c.status is CellStatus.FLAGGED)
        # Coverage is the validator's own accounting, not a count of tokens
        # that happen to contain a digit. The looser definition counted an
        # invoice number and a date as lost data and reported 60 losses on a
        # batch the validator scores at 0.
        if page.report is not None:
            row.tokens_seen = page.report.coverage.numeric_tokens_seen
            row.tokens_placed = page.report.coverage.numeric_tokens_placed
            row.coverage_loss = max(0, row.tokens_seen - row.tokens_placed)
        row.sections = len(document.sections)
        row.tabular_sections = sum(1 for s in document.sections
                                   if s.kind is SectionKind.TABULAR)
        row.data_rows = sum(len(s.data_rows) for s in document.sections)
        tabular = [s for s in document.sections if s.kind is SectionKind.TABULAR]
        row.columns = sum(len(s.columns) for s in tabular)
        row.columns_mapped = sum(1 for s in tabular for c in s.columns
                                 if c.role.value != "unknown")
        if page.health is not None:
            row.healthy = page.health.ok
            row.health_problems = list(page.health.problems)

        label = f"{path.name} p{index}"
        for section in tabular:
            checked, reconciled, errors = _probe_silent_errors(section, label, carried)
            row.totals_checked += checked
            row.totals_reconciled += reconciled
            row.silent_errors.extend(errors)

        for section in tabular:
            for column in section.columns:
                if column.role.value == "unknown":
                    continue
                for data_row in section.data_rows:
                    cell = data_row.cell_at(column.index)
                    if cell is not None and cell.is_numeric:
                        carried[column.role] = carried.get(column.role, 0) + cell.value
        row.__dict__.update(_alignment(document))
        row.equation_rows, row.equation_ok = _equation_closure(document)
        row.merged_cells = sum(1 for c in cells if c.holds_several_figures)
        out.append(row)
    return out


def run_batch(number: int, batches: list[list[Path]],
              results: Path | None = None) -> dict[str, Any]:
    if number < 1 or number > len(batches):
        raise SystemExit(f"batch {number} out of range (1..{len(batches)})")
    files = batches[number - 1]
    kinds = {path.name: (classify(path) if results is None else mixed_kind(path))
             for path in files}

    print(f"=== batch {number}: {len(files)} file(s) ===")
    rows: list[PageRow] = []
    started = time.perf_counter()
    for path in files:
        kind = kinds[path.name]
        print(f"  [{kind:8}] {path.name} ...", flush=True)
        page_rows = measure_file(path, kind)
        for r in page_rows:
            flag = "ERROR" if r.error else ("UNHEALTHY" if not r.healthy else "ok")
            print(f"      p{r.page} {r.source or '-':9} cells={r.cells:5} "
                  f"rows={r.data_rows:4} cols={r.columns_mapped}/{r.columns} {flag}")
        rows.extend(page_rows)

    payload = {
        "batch": number,
        "seconds": round(time.perf_counter() - started, 1),
        "files": [{"name": p.name, "kind": kinds[p.name]} for p in files],
        "pages": [asdict(r) for r in rows],
    }
    out_dir = results or RESULTS
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"batch-{number:02d}.json"
    target.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"--- wrote {target.relative_to(ROOT)} in {payload['seconds']}s")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", action="store_true", help="show the split and exit")
    parser.add_argument("--batch", type=int, nargs="+", help="batch number(s) to run")
    parser.add_argument("--report", type=int, nargs="+", help="batch number(s) to report on")
    parser.add_argument("--corpus", default="JUNE", help="corpus folder in the workspace")
    parser.add_argument("--size", type=int, default=20, help="files per batch (not JUNE)")
    args = parser.parse_args(argv)

    if args.corpus != "JUNE":
        corpus = ROOT / args.corpus
        if not corpus.is_dir():
            print(f"[!] corpus not found: {corpus}")
            return 1
        reports = REPORTS / args.corpus
        results = reports / "_results"
        batches = mixed_batches(corpus, args.size)
        if args.plan or not (args.batch or args.report):
            counts: dict[str, int] = {}
            for path in corpus.iterdir():
                if path.is_file():
                    counts[mixed_kind(path)] = counts.get(mixed_kind(path), 0) + 1
            print(f"corpus: {corpus}  {counts}")
            print(f"batches of {args.size}: {len(batches)}")
            for i, batch in enumerate(batches[:10], start=1):
                mix: dict[str, int] = {}
                for path in batch:
                    mix[mixed_kind(path)] = mix.get(mixed_kind(path), 0) + 1
                print(f"  batch {i:2}: {mix}  {', '.join(p.name[:22] for p in batch[:6])} ...")
            return 0
        for number in args.batch or []:
            run_batch(number, batches, results)
        if args.report:
            from reports_writer import write_report
            path = write_report(args.report, results, reports, corpus=args.corpus)
            print(f"--- wrote {path.relative_to(ROOT)}")
        return 0

    if not CORPUS.is_dir():
        print(f"[!] corpus not found: {CORPUS}")
        return 1

    batches = plan_batches()

    if args.plan or not (args.batch or args.report):
        grouped = pools()
        print(f"corpus: {CORPUS}")
        for kind in ("pdf", "scan", "whatsapp", "other"):
            print(f"  {kind:9} {len(grouped[kind]):4}")
        print(f"batches of {sum(n for _, n in RECIPE)} "
              f"({', '.join(f'{n} {k}' for k, n in RECIPE)}): {len(batches)}")
        for i, batch in enumerate(batches, start=1):
            print(f"  batch {i:2}: {', '.join(p.name[:26] for p in batch)}")
        return 0

    for number in args.batch or []:
        run_batch(number, batches)

    if args.report:
        from reports_writer import write_report
        path = write_report(args.report, RESULTS, REPORTS)
        print(f"--- wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
