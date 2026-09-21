#!/usr/bin/env python3
"""Turn batch results into a Markdown report.

Written for whoever reviews the extraction - it names the files tested, what
each one produced, and where the output disagrees with itself. There is no
ground truth for this corpus (CLAUDE.md s8), so no per-cell accuracy is quoted
anywhere here; every number is something the documents assert about themselves.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

KIND_LABEL = {"pdf": "PDF", "scan": "Scanned image", "whatsapp": "WhatsApp image",
              "image": "Photo / scan", "sheet": "Spreadsheet / CSV", "other": "Other"}


def _load(numbers: list[int], results: Path) -> list[dict[str, Any]]:
    loaded = []
    for n in numbers:
        path = results / f"batch-{n:02d}.json"
        if not path.is_file():
            raise SystemExit(f"no results for batch {n}; run --batch {n} first")
        loaded.append(json.loads(path.read_text(encoding="utf-8")))
    return loaded


def _sum(batches: list[dict], key: str) -> int:
    return sum(p[key] for b in batches for p in b["pages"])


def _pct(part: int, whole: int) -> str:
    return f"{part / whole:.1%}" if whole else "n/a"


def write_report(numbers: list[int], results: Path, reports: Path,
                 corpus: str = "JUNE") -> Path:
    batches = _load(sorted(numbers), results)
    pages = [p for b in batches for p in b["pages"]]
    files = [f for b in batches for f in b["files"]]
    out: list[str] = []
    add = out.append

    span = f"{min(numbers):02d}-{max(numbers):02d}" if len(numbers) > 1 else f"{numbers[0]:02d}"
    add(f"# Extraction report — batch {span}")
    add("")
    add(f"Generated {datetime.now():%Y-%m-%d %H:%M}. "
        f"Corpus `{corpus}/`. {len(files)} file(s), {len(pages)} page(s), "
        f"{sum(b['seconds'] for b in batches):.0f}s total.")
    add("")
    add("**There is no ground truth for this corpus.** No per-cell accuracy is "
        "quoted below and none can be: the source documents are unlabelled, so "
        "every figure here is something a document asserts about itself — "
        "whether its rows keep their shape, whether the stock equation closes, "
        "whether a printed total reconciles with the column above it.")
    add("")

    # ---- headline ------------------------------------------------------
    cells = _sum(batches, "cells")
    pixel = _sum(batches, "pixel_cells")
    review = _sum(batches, "review")
    silent = sum(len(p["silent_errors"]) for p in pages)
    unhealthy = [p for p in pages if not p["healthy"]]
    errors = [p for p in pages if p["error"]]

    add("## Headline")
    add("")
    add("| Metric | Target | Result |")
    add("| --- | --- | ---: |")
    add(f"| **Silent errors** | 0 | **{silent}** |")
    add(f"| **Coverage loss** (numeric tokens read but unplaced) | 0 | "
        f"**{_sum(batches, 'coverage_loss')}** |")
    add(f"| **Pages that failed outright** | 0 | **{len(errors)}** |")
    add(f"| **Unhealthy pages** | 0 | **{len(unhealthy)}/{len(pages)}** |")
    add(f"| Cells extracted | — | {cells} |")
    add(f"| Deterministic (`exact`) | — | {_sum(batches, 'exact')} |")
    add(f"| Pixel-derived | — | {pixel} |")
    add(f"| Needing human review | as low as possible | {review} "
        f"({_pct(review, pixel)} of pixel cells) |")
    add(f"| Structural flags (deterministic cells) | as low as possible | "
        f"{_sum(batches, 'structural_flags')} |")
    add(f"| Column roles assigned | report | "
        f"{_sum(batches, 'columns_mapped')}/{_sum(batches, 'columns')} "
        f"({_pct(_sum(batches, 'columns_mapped'), _sum(batches, 'columns'))}) |")
    add("")

    # ---- what was tested ----------------------------------------------
    add("## Files tested")
    add("")
    for batch in batches:
        add(f"**Batch {batch['batch']}** — {batch['seconds']}s")
        add("")
        add("| File | Requested as | Router chose | Pages |")
        add("| --- | --- | --- | ---: |")
        for entry in batch["files"]:
            rows = [p for p in batch["pages"] if p["file"] == entry["name"]]
            routed = sorted({p["source"] or p["error"][:20] or "?" for p in rows})
            add(f"| `{entry['name']}` | {KIND_LABEL.get(entry['kind'], entry['kind'])} "
                f"| {', '.join(routed)} | {len(rows)} |")
        add("")

    # ---- per page ------------------------------------------------------
    add("## Extraction per page")
    add("")
    add("`eq` is how many mapped rows satisfy `opening + receipt − issue = "
        "closing`; `totals` is printed totals that reconcile against the column "
        "above them. A dash means no such check was available on that page.")
    add("")
    add("| File | Pg | Source | Cells | exact | ver | flag | unchk | Rows | Cols | eq | totals |")
    add("| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for p in pages:
        eq = f"{p['equation_ok']}/{p['equation_rows']}" if p["equation_rows"] else "—"
        tt = f"{p['totals_reconciled']}/{p['totals_checked']}" if p["totals_checked"] else "—"
        name = p["file"] if len(p["file"]) <= 34 else p["file"][:31] + "..."
        add(f"| `{name}` | {p['page']} | {p['source'] or '—'} | {p['cells']} | "
            f"{p['exact']} | {p['verified']} | {p['flagged']} | {p['unchecked']} | "
            f"{p['data_rows']} | {p['columns_mapped']}/{p['columns']} | {eq} | {tt} |")
    add("")

    # ---- alignment -----------------------------------------------------
    add("## Is the output correctly aligned?")
    add("")
    add("Four signals, none of which needs ground truth — each is the document "
        "disagreeing with itself about its own shape.")
    add("")
    add("| Signal | What it means | Count |")
    add("| --- | --- | ---: |")
    add(f"| Coverage loss | a numeric token was read and then never reached a "
        f"cell — data silently dropped | **{_sum(batches, 'coverage_loss')}** |")
    add(f"| Overflow rows | a row put cells beyond the last column its header "
        f"names | {_sum(batches, 'overflow_rows')} |")
    add(f"| Sparse rows | a row's populated-cell count differs from its own "
        f"section's most common width — usually a blank where the value is "
        f"zero, which is expected, not a fault | {_sum(batches, 'ragged_rows')} |")
    add(f"| Mixed-type columns | a column is numeric on some rows and prose on "
        f"others, so something landed in the wrong band | "
        f"{_sum(batches, 'mixed_type_columns')} |")
    add(f"| Unheaded columns | data sits under a column the header never named | "
        f"{_sum(batches, 'unheaded_columns')} |")
    add("")
    eq_rows, eq_ok = _sum(batches, "equation_rows"), _sum(batches, "equation_ok")
    add(f"Where a full stock quadruple was mapped, the row equation closes on "
        f"**{eq_ok} of {eq_rows}** rows ({_pct(eq_ok, eq_rows)}). That is the "
        f"strongest alignment evidence available: if a value had landed in the "
        f"wrong column, the arithmetic would not balance.")
    add("")

    add("Sparsity is counted but is **not** an alignment fault. `003063_.pdf` "
        "prints nothing where a movement is zero, so most of its rows populate "
        "7 of 13 columns while a busy row populates all 13. CLAUDE.md §7 "
        "requires exactly that reading — a blank balance is zero, not a missing "
        "cell. The real alignment signals are the three above it.")
    add("")

    worst = sorted(pages, key=lambda p: -(p["overflow_rows"] + p["mixed_type_columns"]))[:5]
    worst = [p for p in worst if p["overflow_rows"] + p["mixed_type_columns"]]
    if worst:
        add("Pages carrying genuine shape disagreement:")
        add("")
        for p in worst:
            add(f"- `{p['file']}` p{p['page']} — {p['overflow_rows']} overflow row(s), "
                f"{p['mixed_type_columns']} mixed-type column(s), "
                f"{p['ragged_rows']} sparse row(s)")
        add("")

    # ---- failures ------------------------------------------------------
    if errors or unhealthy:
        add("## Pages needing attention")
        add("")
        for p in errors:
            add(f"- **`{p['file']}` p{p['page']} failed:** {p['error']}")
        for p in unhealthy:
            if p["error"]:
                continue
            add(f"- **`{p['file']}` p{p['page']} unhealthy:** "
                f"{'; '.join(p['health_problems'])} "
                f"(read {p['tokens_seen']} numeric token(s), produced {p['cells']} cell(s))")
        add("")

    # Hand-written findings for these batches, if any were recorded.
    notes = []
    for n in sorted(numbers):
        path = results / f"findings-{n:02d}.md"
        if path.is_file():
            notes.append(path.read_text(encoding="utf-8").strip())
    if notes:
        add("## Defects found and corrected")
        add("")
        add("\n\n".join(notes))
        add("")

    if silent:
        add("## Silent errors")
        add("")
        for p in pages:
            for entry in p["silent_errors"]:
                add(f"- {entry}")
        add("")

    reports.mkdir(parents=True, exist_ok=True)
    target = reports / f"batch-{span}.md"
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    return target
