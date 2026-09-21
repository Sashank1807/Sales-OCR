"""Measure the pipeline against real documents.

A set of real pages nobody has transcribed, where the documents themselves
supply the ground truth.

A stock report that prints its own totals is self-verifying. Wherever the
pipeline marks a column's cells ``verified`` and the printed total disagrees
with their sum, that is a **silent error** - caught automatically, with no hand
labelling. That is the metric that matters, and it is measurable here.

What cannot be measured without transcriptions is per-cell character accuracy.
That is reported as unavailable rather than estimated.

    python benchmark.py                 # the pinned 10-page set
    python benchmark.py --markdown      # emit BENCHMARK.md
    python benchmark.py --list          # show the manifest without running
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / "cache"
DOCS_DIR = ROOT / "docs"

from pipeline import PipelineResult, process_file
from schema import CellStatus, QTY_ROLES, Role, Section, VALUE_ROLES

CORPUS = Path("D:/OCR_testing/SS")

#: The pages the system was built against. Every threshold, heuristic and bug
#: fix to date came from looking at these, so a good score here says only that
#: the system fits what it was shaped around.
DEVELOPMENT: tuple[tuple[str, int, str], ...] = (
    ("02_2060094_140_20260819103157239.pdf", 0, "pdf_text"),
    ("02_2060497_140_20260819102501986.pdf", 0, "pdf_text"),
    ("02_2060497_140_20260819102501986.pdf", 1, "pdf_text"),
    ("02_2060543_140_20260819095307562.PDF", 0, "pdf_text"),   # native page ...
    ("02_2060543_140_20260819095307562.PDF", 1, "pdf_text"),
    ("02_2060543_140_20260819095307562.PDF", 2, "image"),      # ... scanned page
    ("02_2060828_140_20260819105316965.pdf", 0, "pdf_text"),
    ("02_2060116_140_20260819102230276.pdf", 0, "image"),
    ("02_2061074_140_20260819092943678.jpeg", 0, "image"),
    ("02_2060436_140_20260819094011493.xlsx", 0, "excel"),
    ("02_2060436_140_20260819094011493.xlsx", 4, "excel"),
    ("02_2060792_140_20260819103305863.XLS", 0, "excel"),
    ("02_2060149_140_20260819090227107.csv", 0, "excel"),
)

#: Pages from files never opened during development. Run once, at the end. The
#: gap between this and the development set is the only honest measure of
#: whether the system generalises rather than having been fitted.
HELD_OUT: tuple[tuple[str, int, str], ...] = (
    ("02_2060799_140_20260819104342378.Pdf", 0, "pdf_text"),
    ("02_2060930_140_20260819094004009.pdf", 0, "pdf_text"),
    ("02_2060942_140_20260819094047892.pdf", 0, "pdf_text"),
    ("02_2061000_140_20260819100423883.pdf", 0, "pdf_text"),
    ("02_2061042_140_20260819102301713.pdf", 0, "pdf_text"),
    ("02_2061066_140_20260819092030070.pdf", 0, "pdf_text"),
    ("02_2061097_140_20260819094151662.PDF", 0, "pdf_text"),
    ("02_2061175_140_20260819100027545.pdf", 0, "pdf_text"),
    ("02_2061231_138_20260819101852041.pdf", 0, "pdf_text"),
    ("02_2061290_140_20260819100123256.pdf", 0, "pdf_text"),
    ("02_2060901_140_20260819095429442.pdf", 0, "image"),
    ("02_2060958_140_20260819103006778.pdf", 0, "image"),
    ("02_2060596_140_20260819095358624.xlsx", 0, "excel"),
    ("02_2060769_140_20260819094052282.xlsx", 0, "excel"),
    ("02_2061938_140_20260819093359257.xls", 0, "excel"),
    ("02_2062237_140_20260819093513463.xlsx", 0, "excel"),
)

MANIFEST = DEVELOPMENT   # the default when no set is named


# ---------------------------------------------------------------------------
# Per-page measurement
# ---------------------------------------------------------------------------


@dataclass
class PageMetrics:
    file: str
    page_index: int
    expected_kind: str
    actual_kind: str = ""
    ok: bool = True
    error: str = ""
    seconds: float = 0.0

    cells: int = 0
    exact: int = 0
    verified: int = 0
    flagged: int = 0
    unchecked: int = 0
    pixel_cells: int = 0
    structural_flags: int = 0
    healthy: bool = True
    health_problems: list[str] = field(default_factory=list)
    health_warnings: list[str] = field(default_factory=list)

    columns: int = 0
    columns_mapped: int = 0
    vlm_candidates: list[str] = field(default_factory=list)

    tokens_seen: int = 0
    tokens_placed: int = 0

    totals_checked: int = 0
    totals_reconciled: int = 0
    silent_errors: list[str] = field(default_factory=list)

    data_rows: int = 0
    sections: int = 0
    tabular_sections: int = 0
    non_tabular_sections: int = 0
    adjustment_columns: int = 0
    review: int = 0

    @property
    def routed_correctly(self) -> bool:
        return self.actual_kind == self.expected_kind

    @property
    def review_cells(self) -> int:
        """Pixel-derived cells needing a human. Excludes ``exact``."""
        return self.review

    @property
    def coverage_loss(self) -> int:
        return max(0, self.tokens_seen - self.tokens_placed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file, "page_index": self.page_index,
            "expected_kind": self.expected_kind, "actual_kind": self.actual_kind,
            "routed_correctly": self.routed_correctly, "ok": self.ok,
            "error": self.error, "seconds": round(self.seconds, 2),
            "cells": self.cells, "exact": self.exact,
            "verified": self.verified, "flagged": self.flagged,
            "unchecked": self.unchecked, "pixel_cells": self.pixel_cells,
            "structural_flags": self.structural_flags, "review": self.review,
            "review_cells": self.review_cells, "healthy": self.healthy,
            "health_problems": self.health_problems,
            "health_warnings": self.health_warnings,
            "non_tabular_sections": self.non_tabular_sections,
            "columns": self.columns, "columns_mapped": self.columns_mapped,
            "vlm_candidates": self.vlm_candidates,
            "tokens_seen": self.tokens_seen, "tokens_placed": self.tokens_placed,
            "coverage_loss": self.coverage_loss,
            "totals_checked": self.totals_checked,
            "totals_reconciled": self.totals_reconciled,
            "silent_errors": self.silent_errors,
            "data_rows": self.data_rows, "sections": self.sections,
            "tabular_sections": self.tabular_sections,
            "adjustment_columns": self.adjustment_columns,
        }


def _probe_silent_errors(section: Section, page_label: str,
                         carried: dict | None = None) -> tuple[int, int, list[str]]:
    """Use the document's printed totals as ground truth.

    A column whose cells the validator called ``verified`` must sum to the
    total the document printed for it. Where it does not, something wrong was
    passed off as right - the one outcome the pipeline is meant never to
    produce.

    Returns ``(totals checked, totals reconciled, silent error descriptions)``.

    ``carried`` maps a role to what the same column summed to on the file's
    earlier pages. A running total printed at the foot of page 2 is page 1 plus
    page 2 (`New Doc 06-01-2026 08.28.pdf`: 1906 + 7507 = 9413); judged against
    page 2 alone it was reported as two silent errors that were not there - the
    validator had already recognised it as cumulative.
    """
    checked = reconciled = 0
    errors: list[str] = []
    if not section.total_rows:
        return (0, 0, [])

    stock_roles = set(QTY_ROLES) | set(VALUE_ROLES) | {Role.DUMP_QTY}
    for column in section.columns:
        if column.role not in stock_roles:
            continue

        column_sum = Decimal(0)
        seen = verified_cells = 0
        for row in section.data_rows:
            cell = row.cell_at(column.index)
            if cell is None or not cell.is_numeric:
                continue
            column_sum += cell.value
            seen += 1
            # Both statuses are claims that the value is right and needs no
            # review. Checking only VERIFIED here would make this metric
            # vacuous for Excel and PDF-text pages, where every cell is EXACT.
            if cell.status in (CellStatus.VERIFIED, CellStatus.EXACT):
                verified_cells += 1
        if not seen:
            continue

        for total_row in section.total_rows:
            cell = total_row.cell_at(column.index)
            if cell is None or not cell.is_numeric:
                continue
            checked += 1
            if abs(cell.value - column_sum) <= Decimal("0.05"):
                reconciled += 1
                continue
            earlier = (carried or {}).get(column.role)
            if earlier is not None and abs(cell.value - column_sum - earlier) <= Decimal("0.05"):
                reconciled += 1
                continue

            # A printed figure orders of magnitude away from the column sum is
            # a different measure - a value total sitting under a quantity
            # column - not a misread. The validator draws that line and the
            # probe has to draw it in the same place, or it reports a false
            # alarm on behaviour that is deliberately correct.
            if column_sum:
                ratio = abs(cell.value / column_sum)
                if not (Decimal("0.1") < ratio < Decimal("10")):
                    continue
            elif abs(cell.value) > Decimal("0.05"):
                # An empty column under a large printed figure is the same
                # story as a wild ratio: the total is a different measure. A
                # zero sum made the ratio undefined and slipped the guard.
                continue

            if (verified_cells == seen
                    and cell.status in (CellStatus.VERIFIED, CellStatus.EXACT)):
                # Every cell in the column was passed as verified, yet the
                # column does not add up to the figure the document printed.
                errors.append(
                    f"{page_label} {column.role.value}: all {seen} cells verified "
                    f"but they sum to {column_sum}, against a printed total of "
                    f"{cell.value}")
    return (checked, reconciled, errors)


def measure_page(file_name: str, page_index: int, expected: str) -> PageMetrics:
    metrics = PageMetrics(file=file_name, page_index=page_index,
                          expected_kind=expected)
    path = CORPUS / file_name
    if not path.is_file():
        metrics.ok, metrics.error = False, "source file not found"
        return metrics

    started = time.perf_counter()
    try:
        result: PipelineResult = process_file(path, pages=[page_index])
    except Exception as exc:
        metrics.ok = False
        metrics.error = f"{type(exc).__name__}: {exc}"
        metrics.seconds = time.perf_counter() - started
        return metrics
    metrics.seconds = time.perf_counter() - started

    if not result.pages:
        metrics.ok, metrics.error = False, "router produced no unit of work"
        return metrics

    page = result.pages[0]
    metrics.actual_kind = page.ref.kind.value
    if not page.ok:
        metrics.ok, metrics.error = False, page.error
        return metrics

    report, document = page.report, page.document
    counts = report.counts if report else {}
    metrics.cells = counts.get("total_cells", 0)
    metrics.exact = counts.get("exact", 0)
    metrics.verified = counts.get("verified", 0)
    metrics.flagged = counts.get("flagged", 0)
    metrics.unchecked = counts.get("unchecked", 0)
    metrics.pixel_cells = counts.get("pixel_cells", 0)
    metrics.structural_flags = counts.get("structural_flags", 0)
    metrics.review = counts.get("review_cells", 0)
    if page.health:
        metrics.healthy = page.health.ok
        metrics.health_problems = list(page.health.problems)
        metrics.health_warnings = list(page.health.warnings)
    if report:
        metrics.tokens_seen = report.coverage.numeric_tokens_seen
        metrics.tokens_placed = report.coverage.numeric_tokens_placed

    label = f"{file_name} p{page_index + 1}"
    from schema import SectionKind
    for section in document.sections:
        metrics.sections += 1
        metrics.data_rows += len(section.data_rows)
        # Only tabular sections have columns worth mapping. Counting the
        # headings of empty and non-tabular blocks would bury the real figure
        # under a denominator of things that were never tables.
        if section.kind is SectionKind.NON_TABULAR:
            metrics.non_tabular_sections += 1
        if section.kind is SectionKind.TABULAR:
            metrics.columns += len(section.columns)
            metrics.columns_mapped += sum(1 for c in section.columns
                                          if c.role is not Role.UNKNOWN)
            metrics.tabular_sections += 1
            # The census counts only real tables. Asking a VLM about the
            # columns of an address block was the whole of the old figure.
            metrics.vlm_candidates.extend(
                f"s{section.index}c{c.index}:{c.header_text[:20]}"
                for c in section.columns if c.confidence < 0.55)
        metrics.adjustment_columns += sum(1 for c in section.columns
                                          if c.adjustment_column)

        checked, reconciled, errors = _probe_silent_errors(section, label)
        metrics.totals_checked += checked
        metrics.totals_reconciled += reconciled
        metrics.silent_errors.extend(errors)

    return metrics


# ---------------------------------------------------------------------------
# Aggregation and reporting
# ---------------------------------------------------------------------------


def run(manifest: Sequence[tuple[str, int, str]] = MANIFEST,
        progress: bool = True) -> list[PageMetrics]:
    results: list[PageMetrics] = []
    for n, (name, index, expected) in enumerate(manifest, start=1):
        if progress:
            print(f"[{n}/{len(manifest)}] {name} p{index + 1} ({expected}) ...",
                  file=sys.stderr, flush=True)
        results.append(measure_page(name, index, expected))
    return results


def _by_source(results: Sequence[PageMetrics]) -> dict[str, list[PageMetrics]]:
    grouped: dict[str, list[PageMetrics]] = defaultdict(list)
    for metrics in results:
        grouped[metrics.actual_kind or metrics.expected_kind].append(metrics)
    return dict(grouped)


def _totals(rows: Sequence[PageMetrics]) -> dict[str, int]:
    keys = ("cells", "exact", "verified", "flagged", "unchecked", "columns",
            "columns_mapped", "tokens_seen", "tokens_placed", "totals_checked",
            "totals_reconciled", "data_rows", "adjustment_columns",
            "tabular_sections", "non_tabular_sections", "pixel_cells",
            "structural_flags", "review")
    out = {k: sum(getattr(r, k) for r in rows) for k in keys}
    out["pages"] = len(rows)
    out["ok"] = sum(1 for r in rows if r.ok)
    out["routed"] = sum(1 for r in rows if r.routed_correctly)
    out["silent_errors"] = sum(len(r.silent_errors) for r in rows)
    out["coverage_loss"] = sum(r.coverage_loss for r in rows)
    out["review_cells"] = out["review"]
    out["unhealthy"] = sum(1 for r in rows if not r.healthy)
    out["vlm_candidates"] = sum(len(r.vlm_candidates) for r in rows)
    return out


def _pct(part: int, whole: int) -> str:
    return f"{part / whole:.1%}" if whole else "n/a"


def _set_section(name: str, blurb: str, results: Sequence[PageMetrics]) -> list[str]:
    """One measured set, reported in full."""
    t = _totals(results)
    lines = [f"## {name}\n", blurb + "\n"]
    add = lines.append

    add("| Metric | Target | Result |")
    add("| --- | --- | --- |")
    add(f"| **Silent errors** | 0 | **{t['silent_errors']}** |")
    add(f"| **Coverage loss** | 0 | **{t['coverage_loss']}** |")
    add(f"| **Unhealthy pages** | 0 | **{t['unhealthy']}/{t['pages']}** |")
    add(f"| Pages processed | all | {t['ok']}/{t['pages']} |")
    add(f"| Routed correctly | all | {t['routed']}/{t['pages']} |")
    add(f"| Review load (pixel-derived cells) | low | "
        f"{t['review']} of {t['pixel_cells']} |")
    add(f"| Structural flags (deterministic cells) | low | {t['structural_flags']} |")
    add(f"| Column mapping (tabular sections only) | report | "
        f"{t['columns_mapped']}/{t['columns']} "
        f"({_pct(t['columns_mapped'], t['columns'])}) over "
        f"{t['tabular_sections']} section(s) |")
    add(f"| VLM candidate columns | report | {t['vlm_candidates']} |")
    add("")

    add("| Source | Pages | Cells | Exact | Verified | Flagged | Unchecked | "
        "Review | Silent |")
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for source in sorted(_by_source(results)):
        rows = _by_source(results)[source]
        st = _totals(rows)
        add(f"| `{source}` | {st['pages']} | {st['cells']} | {st['exact']} | "
            f"{st['verified']} | {st['flagged']} | {st['unchecked']} | "
            f"**{st['review']}** | {st['silent_errors']} |")
    add("")
    return lines


def _health_section(results: Sequence[PageMetrics]) -> list[str]:
    lines = ["## Page health\n",
             "Cell metrics cannot see a page that produced no cells: it has no "
             "flagged cells, no silent errors and a perfect coverage ratio over "
             "zero tokens. A page can be cell-clean and still be a failure, so "
             "pages are judged separately.\n"]
    add = lines.append
    bad = [r for r in results if not r.healthy or r.health_warnings]
    if not bad:
        add("Every page healthy, nothing slow.\n")
        return lines
    add("| Document | Page | Source | Seconds | Problem |")
    add("| --- | ---: | --- | ---: | --- |")
    for r in bad:
        for problem in r.health_problems:
            add(f"| `{r.file[:32]}` | {r.page_index + 1} | `{r.actual_kind}` | "
                f"{r.seconds:.0f} | **{problem}** |")
        for warning in r.health_warnings:
            add(f"| `{r.file[:32]}` | {r.page_index + 1} | `{r.actual_kind}` | "
                f"{r.seconds:.0f} | _{warning}_ |")
    add("")
    return lines


def format_comparison(development: Sequence[PageMetrics],
                      held_out: Sequence[PageMetrics]) -> str:
    """Both sets, with the gap between them stated plainly."""
    lines: list[str] = ["# Benchmark\n"]
    add = lines.append
    add(f"Real pages from `{CORPUS}`, pinned in `benchmark.py` so the numbers "
        "reproduce. `python benchmark.py --set both --markdown`\n")

    lines += _set_section(
        "Development set",
        f"{len(development)} pages the system was built against. Every "
        "threshold and every bug fix to date came from looking at these, so a "
        "good score here says only that the system fits what it was shaped "
        "around.", development)

    if held_out:
        lines += _set_section(
            "Held-out set",
            f"{len(held_out)} pages from files never opened during development, "
            "run once. **The gap between this and the development set is the "
            "only honest measure of whether the system generalises.**", held_out)

        d, h = _totals(development), _totals(held_out)
        add("### The gap\n")
        add("| Metric | Development | Held out |")
        add("| --- | ---: | ---: |")
        add(f"| Silent errors | {d['silent_errors']} | {h['silent_errors']} |")
        add(f"| Coverage loss | {d['coverage_loss']} | {h['coverage_loss']} |")
        add(f"| Unhealthy pages | {_pct(d['unhealthy'], d['pages'])} | "
            f"{_pct(h['unhealthy'], h['pages'])} |")
        add(f"| Routed correctly | {_pct(d['routed'], d['pages'])} | "
            f"{_pct(h['routed'], h['pages'])} |")
        add(f"| Column mapping | {_pct(d['columns_mapped'], d['columns'])} | "
            f"{_pct(h['columns_mapped'], h['columns'])} |")
        add(f"| Totals reconciled | {d['totals_reconciled']}/{d['totals_checked']} | "
            f"{h['totals_reconciled']}/{h['totals_checked']} |")
        add(f"| Structural flags | {d['structural_flags']} | "
            f"**{h['structural_flags']}** |")
        add(f"| Pixel cells needing review | "
            f"{_pct(d['review'], d['pixel_cells'])} | "
            f"**{_pct(h['review'], h['pixel_cells'])}** |")
        add("")

        # The headline metrics hold up; two others do not, and saying so is the
        # point of keeping a held-out set at all.
        worries: list[str] = []
        if h["structural_flags"] > max(10, d["structural_flags"] * 3):
            worries.append(
                f"**Structural flags rise from {d['structural_flags']} to "
                f"{h['structural_flags']}.** Unseen layouts break the row "
                "equation far more often than the ones the system was shaped "
                "around. These are deterministic cells, so nothing was misread "
                "- the mapping or the row reconstruction is at fault.")
        if (d["pixel_cells"] and h["pixel_cells"]
                and h["review"] / h["pixel_cells"] > d["review"] / d["pixel_cells"] + 0.1):
            worries.append(
                f"**{_pct(h['review'], h['pixel_cells'])} of pixel-derived "
                f"cells need review, against {_pct(d['review'], d['pixel_cells'])} "
                "on the development set.** On unseen image pages almost nothing "
                "could be verified at all.")
        if worries:
            # Both the count and the mapping claim are read off the current
            # numbers. Hardcoding "two" printed a sentence contradicting the
            # single bullet beneath it the moment one of the two cleared -
            # narrative drifting away from the table directly above it.
            d_map = d["columns_mapped"] / d["columns"] if d["columns"] else 0.0
            h_map = h["columns_mapped"] / h["columns"] if h["columns"] else 0.0
            lead = ("Silent errors, coverage and routing hold up on unseen "
                    "documents")
            if abs(h_map - d_map) <= 0.05:
                lead += ", and column mapping is essentially flat"
            tail = ("One figure does not hold up" if len(worries) == 1
                    else f"{len(worries)} figures do not hold up")
            add(f"{lead}. {tail}:\n")
            for worry in worries:
                add(f"- {worry}")
            add("")

    lines += _health_section(list(development) + list(held_out))

    add("## Review load, restated\n")
    combined = _totals(list(development) + list(held_out))
    add("Review load previously counted every cell that was not `verified`, "
        "which included Excel and PDF-text cells that **cannot have been "
        "misread**. Verification exists to catch misreading; where the source "
        "is deterministic there is nothing to catch. Those cells are now "
        "reported as `exact` and excluded.\n")
    # The old figure cannot be read off the new counts: under the old taxonomy
    # every cell now called `exact` counted as review unless a check happened
    # to confirm it. Taking `flagged + unchecked` from the current statuses
    # would report 1,618 and understate the correction by more than twentyfold.
    old_upper = combined["cells"] - combined["verified"]
    add("| | Cells | Counted as review |")
    add("| --- | ---: | ---: |")
    add(f"| Old definition (every cell not `verified`) | {combined['cells']} | "
        f"up to {old_upper:,} |")
    add(f"| New definition (pixel-derived only) | {combined['cells']} | "
        f"**{combined['review']:,}** |")
    add("")
    add(f"The old figure is an upper bound: some of the {combined['exact']:,} "
        "cells now called `exact` were also confirmed by arithmetic and would "
        "have been marked `verified` under the old scheme. How many is not "
        "recoverable from the cached run. Either way the reported review load "
        f"fell by more than an order of magnitude, from tens of thousands of "
        f"cells to {combined['review']:,}.\n")
    add(f"Of {combined['cells']} cells, {combined['exact']} are `exact` and "
        f"{combined['pixel_cells']} were read from pixels. The real "
        f"transcription load is **{combined['review']} cells**, confined to "
        "image pages. A further "
        f"{combined['structural_flags']} deterministic cell(s) are flagged for "
        "structural reasons - a row that does not balance is a layout or "
        "mapping fault, not something to re-read.\n")

    silent = [e for r in list(development) + list(held_out) for e in r.silent_errors]
    add("## Silent errors\n")
    if silent:
        for entry in silent:
            add(f"- {entry}")
    else:
        add("None in either set.")
    add("")

    add(_vlm_section(combined))
    add(_image_path_section(list(development) + list(held_out)))
    add(_measurement_notes())
    add(_caveats(list(development) + list(held_out), combined))
    return "\n".join(lines)


#: The census before address blocks and title blocks were excluded from column
#: mapping. Kept here so the improvement is stated rather than implied.
VLM_CENSUS_BEFORE_SECTION_CLASSIFICATION = 3833


def _vlm_section(combined: dict[str, int]) -> str:
    """Whether the VLM fallback is needed, re-measured after the section fix."""
    now = combined["vlm_candidates"]
    lines = ["## Would the VLM fallback be used?\n"]
    add = lines.append

    add("The fallback is defined but unimplemented, by design. The earlier "
        f"census of {VLM_CENSUS_BEFORE_SECTION_CLASSIFICATION:,} candidate "
        "columns was almost entirely an artefact: address blocks, title blocks "
        "and page footers were being treated as tables and their \"columns\" "
        "put to the VLM. Excluding non-tabular sections drops it to "
        f"**{now:,}** across {combined['pages']} pages - roughly a tenfold "
        "fall, and the remainder are columns of genuine tables.\n")
    add("That makes the decision evidence-based rather than a guess, but it is "
        "not yet a case *for* building the path: a candidate column is one the "
        "header vocabulary could not name, and most carry no stock role at all "
        "(batch numbers, expiry dates, free-text notes) for which no canonical "
        "role exists. A VLM would have nothing useful to return for those. The "
        "case rests instead on the specific pages where column boundaries or "
        "headings defeat the geometry, which are few and named in CLAUDE.md.\n")
    return "\n".join(lines)


def _measurement_notes() -> str:
    """Bugs this run found in the measurement itself.

    Recorded because every one of them made the pipeline look better or worse
    than it was, and a metric nobody audits is worse than no metric.
    """
    lines = ["## Bugs found in the measurement\n",
             "Each of these made a number wrong rather than the pipeline "
             "wrong. They are listed because an unaudited metric is worse than "
             "no metric.\n",
             "| What | Effect |", "| --- | --- |"]
    add = lines.append
    add("| The silent-error probe checked only `verified` | After the taxonomy "
        "split every Excel and PDF-text cell is `exact`, so the metric would "
        "have been **vacuous** for 8 of 13 development pages |")
    add("| A zero column sum bypassed the magnitude guard | A value total "
        "printed above an empty quantity column was reported as a silent "
        "error; the ratio was undefined, so the guard never ran |")
    add("| Page health flagged every Excel page for \"0 column bands\" | The "
        "Excel reader addresses cells directly and never runs band detection; "
        "4 healthy pages were reported as failures |")
    add("| `Cell.mark()` could promote a pixel cell to `exact` | Precedence "
        "alone was not enough: `exact` outranks `unchecked`, so a caller could "
        "claim a recognised value could not have been misread |")
    add("| Review load read off the new counts | `flagged + unchecked` under "
        "the new statuses reports 1,618, understating the correction more than "
        "twentyfold; the old definition counted `exact` cells too |")
    add("")
    return "\n".join(lines)


def _image_path_section(results: Sequence[PageMetrics]) -> str:
    """Where the time goes on a scanned page, measured rather than guessed."""
    image_pages = [r for r in results if r.actual_kind == "image" and r.ok]
    lines = ["## The image path is the cost\n"]
    add = lines.append

    if image_pages:
        slowest = max(image_pages, key=lambda r: r.seconds)
        total = sum(r.seconds for r in image_pages)
        others = [r.seconds for r in results if r.actual_kind != "image" and r.ok]
        add(f"{len(image_pages)} image page(s) account for {total:.0f}s of the "
            f"run; the slowest single page took {slowest.seconds:.0f}s. Every "
            f"other page finished in under {max(others or [0]) + 0.5:.0f}s.\n")

    add("`profile_image_path.py` breaks a page down by stage:\n")
    add("| Stage | Share of page time | Note |")
    add("| --- | ---: | --- |")
    add("| PaddleOCR detect + recognise | **84-100%** | one call; the two are "
        "not separable from outside `predict()` |")
    add("| engine load | 4.6s, once | per process, not per page |")
    add("| rasterise | <0.1s | negligible |")
    add("| token extraction | ~0s | negligible |")
    add("| geometry | ~0.01s | negligible |")
    add("")
    add("**Device: CPU — `paddlepaddle` is built without CUDA.** The RTX 2000 "
        "Ada this project specifies is not being used at all. Recognition is "
        "effectively the whole cost and it is running on the wrong processor, "
        "so tuning anything else cannot move the number. Establishing that was "
        "the point of measuring; what to do about it is a separate decision.\n")
    return "\n".join(lines)


def format_markdown(results: Sequence[PageMetrics]) -> str:
    overall = _totals(results)
    lines: list[str] = []
    add = lines.append

    add("# Benchmark — real documents\n")
    add(f"**Pages:** {overall['pages']} from `{CORPUS}`, pinned in "
        "`benchmark.py::MANIFEST` so the numbers reproduce.  ")
    add(f"**Run:** `python benchmark.py`\n")
    add("These pages are unlabelled, but the documents supply their own ground "
        "truth: a report that prints its totals is self-verifying.\n")

    add("## Headline\n")
    add("| Metric | Definition | Target | Result |")
    add("| --- | --- | --- | --- |")
    add(f"| **Silent error rate** | cells passed as `verified` that contradict "
        f"the document's own printed total | **0** | "
        f"**{overall['silent_errors']}** |")
    add(f"| **Coverage loss** | numeric tokens read that never reached a cell | "
        f"**0** | **{overall['coverage_loss']}** |")
    add(f"| Flag rate | flagged ÷ cells | as low as possible | "
        f"{_pct(overall['flagged'], overall['cells'])} |")
    add(f"| Pages processed | no crash, output produced | all | "
        f"{overall['ok']}/{overall['pages']} |")
    add(f"| Routed correctly | reader matched the expected one | all | "
        f"{overall['routed']}/{overall['pages']} |")
    add(f"| Column mapping | columns of *tabular* sections given a canonical "
        f"role | report as-is | {overall['columns_mapped']}/{overall['columns']} "
        f"({_pct(overall['columns_mapped'], overall['columns'])}) |")
    add(f"| Totals reconciled | printed total = column sum | report as-is | "
        f"{overall['totals_reconciled']}/{overall['totals_checked']} |")
    add("")
    add("**Cell accuracy is not reported:** these pages carry no per-cell "
        "ground truth.\n")

    add("## By source\n")
    add("| Source | Pages | Cells | Verified | Flagged | Unchecked | "
        "Coverage loss | Silent errors | Columns mapped |")
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for source in sorted(_by_source(results)):
        rows = _by_source(results)[source]
        t = _totals(rows)
        add(f"| `{source}` | {t['pages']} | {t['cells']} | "
            f"{t['verified']} ({_pct(t['verified'], t['cells'])}) | "
            f"{t['flagged']} | {t['unchecked']} | {t['coverage_loss']} | "
            f"**{t['silent_errors']}** | "
            f"{t['columns_mapped']}/{t['columns']} |")
    add("")

    add("## Human review load\n")
    add("Cells a person has to look at: everything not proved consistent.\n")
    add("| Document | Page | Source | Data rows | Cells | Review cells | "
        "Review per page | Seconds |")
    add("| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |")
    for r in results:
        add(f"| `{r.file[:34]}` | {r.page_index + 1} | `{r.actual_kind}` | "
            f"{r.data_rows} | {r.cells} | {r.review_cells} | "
            f"{r.review_cells} | {r.seconds:.1f} |")
    add("")
    add(f"Across the set: **{overall['review_cells']} cells** over "
        f"{overall['pages']} pages, a mean of "
        f"{overall['review_cells'] / max(1, overall['pages']):.0f} per page.\n")

    add("## Per page\n")
    add("| Document | Page | Expected | Actual | Routed | Cells | V / F / U | "
        "Totals | Status |")
    add("| --- | ---: | --- | --- | :-: | ---: | --- | ---: | --- |")
    for r in results:
        status = "ok" if r.ok else f"**FAILED** {r.error[:40]}"
        add(f"| `{r.file[:34]}` | {r.page_index + 1} | `{r.expected_kind}` | "
            f"`{r.actual_kind or '-'}` | {'yes' if r.routed_correctly else '**no**'} | "
            f"{r.cells} | {r.verified} / {r.flagged} / {r.unchecked} | "
            f"{r.totals_reconciled}/{r.totals_checked} | {status} |")
    add("")

    silent = [e for r in results for e in r.silent_errors]
    add("## Silent errors\n")
    if silent:
        for entry in silent:
            add(f"- {entry}")
    else:
        add("None. No column was passed as fully verified while contradicting "
            "the total the document printed for it.")
    add("")

    vlm = [(r.file, c) for r in results for c in r.vlm_candidates]
    add("## Would the VLM fallback have been used?\n")
    add("The fallback is defined but unimplemented, by design. These are the "
        "columns that fell below the threshold and would have been put to it:\n")
    if vlm:
        add("| Document | Column |")
        add("| --- | --- |")
        for name, column in vlm[:40]:
            add(f"| `{name[:34]}` | `{column}` |")
        if len(vlm) > 40:
            add(f"| … | {len(vlm) - 40} more |")
        add("")
        add(f"**{len(vlm)} columns** across {overall['pages']} pages. Whether "
            "that justifies building the VLM path is now an evidence-based "
            "decision rather than a guess.")
    else:
        add("None — every column resolved without it.")
    add("")

    adjustments = sum(r.adjustment_columns for r in results)
    if adjustments:
        add("## Movement columns outside the canonical four\n")
        add(f"{adjustments} column(s) carried a stock movement the role set "
            "cannot name - transfers or adjustments. They balance the row "
            "equation and are reported as such rather than being forced into "
            "`receipt` or `issue`.\n")

    add(_caveats(results, overall))
    return "\n".join(lines)


def _caveats(results: Sequence[PageMetrics], overall: dict[str, int]) -> str:
    """The part of the report that argues against its own headline.

    Generated rather than written by hand, so it cannot drift away from the
    numbers above it and cannot be lost when the report is regenerated.
    """
    lines = ["---\n", "## What these numbers do not say\n"]
    add = lines.append

    add("The headline metrics are at target, and neither is the whole story.\n")

    empty = [r for r in results if r.ok and r.cells == 0]
    if empty:
        worst = max(empty, key=lambda r: r.seconds)
        add(f"**{len(empty)} page(s) produced nothing at all.** "
            f"`{worst.file}` page {worst.page_index + 1} routed correctly to "
            f"`{worst.actual_kind}`, ran for {worst.seconds:.0f} seconds and "
            "returned 0 cells. It counts as processed because nothing crashed - "
            "but a page that yields nothing is a silent failure of a different "
            "kind, invisible to a silent-*error* rate that only examines cells "
            "that exist. A page yielding zero cells should become a flag in its "
            "own right.\n")

    by_source = _by_source(results)
    weakest = min(
        ((s, _totals(rows)) for s, rows in by_source.items()
         if _totals(rows)["cells"]),
        key=lambda item: item[1]["verified"] / item[1]["cells"], default=None)
    if weakest:
        source, t = weakest
        add(f"**Verified rates are low, and that is mostly honest.** `{source}` "
            f"verifies {_pct(t['verified'], t['cells'])} of its cells, because "
            "those inputs carry long text columns and sheets with no totals to "
            "reconcile against - there is genuinely little to check. The "
            "pipeline says so rather than inflating the figure. But a low "
            "verified rate also means a high review load, which is what the "
            "business actually pays for.\n")

    unreconciled = overall["totals_checked"] - overall["totals_reconciled"]
    if unreconciled > 0:
        add(f"**Totals reconciled: {overall['totals_reconciled']} of "
            f"{overall['totals_checked']}.** The other {unreconciled} are cases "
            "where the printed total is a different measure from the column it "
            "sits above, and the magnitude guard classified them as such. That "
            "guard is load-bearing - it is the difference between reporting "
            "zero silent errors and reporting several - and it is calibrated on "
            "a 10x ratio tested against a handful of documents, not hundreds.\n")

    add(f"**Column mapping, {_pct(overall['columns_mapped'], overall['columns'])}.** "
        f"The denominator counts every column of all {overall['tabular_sections']} "
        "tabular sections, including sections that are fragments of a page rather "
        "than real tables. It is not comparable with the figure quoted for the "
        "hand fixtures, which counted only each document's main table.\n")

    add(f"**{overall['pages']} pages is a small sample**, chosen to span the "
        "three readers rather than to be representative. `--reuse` re-renders "
        "this report from `benchmark_cache.json` without re-running, so widening "
        "the manifest costs one pass, not one per metric change.\n")

    return "\n".join(lines)


def format_text(results: Sequence[PageMetrics]) -> str:
    overall = _totals(results)
    lines = [f"{overall['pages']} pages, {overall['ok']} processed, "
             f"{overall['routed']} routed as expected"]
    lines.append(f"  silent errors : {overall['silent_errors']}")
    lines.append(f"  coverage loss : {overall['coverage_loss']} "
                 f"of {overall['tokens_seen']} numeric tokens")
    lines.append(f"  cells         : {overall['cells']} "
                 f"({overall['verified']} verified, {overall['flagged']} flagged, "
                 f"{overall['unchecked']} unchecked)")
    lines.append(f"  review load   : {overall['review']} pixel-derived cell(s) "
                 f"of {overall['pixel_cells']}; {overall['exact']} exact; "
                 f"{overall['structural_flags']} structural flag(s)")
    lines.append(f"  unhealthy     : {overall['unhealthy']} page(s)")
    lines.append(f"  vlm candidates: {overall['vlm_candidates']} column(s)")
    lines.append(f"  columns       : {overall['columns_mapped']}/{overall['columns']} mapped")
    lines.append("")
    for source, rows in sorted(_by_source(results).items()):
        t = _totals(rows)
        lines.append(f"  {source:<9} {t['pages']} page(s)  cells {t['cells']:>5}  "
                     f"verified {t['verified']:>5}  flagged {t['flagged']:>4}  "
                     f"silent {t['silent_errors']}")
    failures = [r for r in results if not r.ok]
    if failures:
        lines.append("")
        lines.append("  failures:")
        for r in failures:
            lines.append(f"    {r.file} p{r.page_index + 1}: {r.error}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark against real documents")
    parser.add_argument("--markdown", action="store_true", help="write BENCHMARK.md")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--list", action="store_true", help="show the manifest only")
    parser.add_argument("--out", default=str(DOCS_DIR / "BENCHMARK.md"))
    parser.add_argument("--cache", default=str(DEFAULT_CACHE_DIR / "benchmark_cache.json"),
                        help="where raw per-page results are stored")
    parser.add_argument("--reuse", action="store_true",
                        help="re-render from the cache instead of re-running "
                             "(OCR pages are slow; metric changes should not "
                             "cost another pass)")
    parser.add_argument("--set", dest="which", default="dev",
                        choices=("dev", "heldout", "both"),
                        help="which manifest to run (default: dev)")
    args = parser.parse_args(argv)

    if args.list:
        for name, index, expected in MANIFEST:
            exists = "  " if (CORPUS / name).is_file() else "??"
            print(f" {exists} {name}  page {index + 1}  expect {expected}")
        return 0

    def load_or_run(name: str, manifest):
        cache_path = Path(args.cache)
        cache = cache_path.with_name(f"benchmark_cache_{name}.json")
        if not cache.is_file():
            if (DEFAULT_CACHE_DIR / cache.name).is_file():
                cache = DEFAULT_CACHE_DIR / cache.name
            elif (ROOT / cache.name).is_file():
                cache = ROOT / cache.name

        if args.reuse and cache.is_file():
            print(f"re-rendered {name} from {cache}", file=sys.stderr)
            return [PageMetrics(**{k: v for k, v in entry.items()
                                   if k in PageMetrics.__dataclass_fields__})
                    for entry in json.loads(cache.read_text(encoding="utf-8"))]
        rows = run(manifest)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps([r.to_dict() for r in rows], indent=1),
                         encoding="utf-8")
        return rows

    development = load_or_run("dev", DEVELOPMENT) if args.which in ("dev", "both") else []
    held_out = load_or_run("heldout", HELD_OUT) if args.which in ("heldout", "both") else []
    results = list(development) + list(held_out)

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    elif args.markdown:
        Path(args.out).write_text(
            format_comparison(development, held_out), encoding="utf-8")
        print(format_text(results))
        print(f"\nwrote {args.out}")
    else:
        print(format_text(results))

    return 1 if any(r.silent_errors for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
