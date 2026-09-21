#!/usr/bin/env python3
"""Refuse a change that makes extraction worse.

    python regression_check.py              # run everything, compare to the baseline
    python regression_check.py --reuse      # compare cached results, run nothing
    python regression_check.py --accept     # make the current results the baseline

Runs the test suite, the 29-page benchmark, every JUNE batch and the labelled
column roles, then compares against `reports/_baseline.json`. Exits non-zero on
a regression and writes `reports/regression-latest.md`.

Two tiers, because not every movement is a regression:

**Hard - the change is rejected.** Tests failing; any silent error; any
coverage loss; more pages failing or unhealthy than the baseline; and, on
labelled pages, more *wrong* roles, fewer correct roles, or labelled columns no
longer found. These are the outcomes CLAUDE.md s2 and s8 say must not get worse.

**Soft - reported, not rejected.** Verified cells, structural flags, mapped
columns, equation rows, reconciled totals, review load. These move for good
reasons as well as bad ones: a fix that stops arithmetic overruling a heading
*removes* verified cells when that verification rested on a wrong mapping, and
it did exactly that on `GENEX.pdf`. Only the labels can say which movement is
which, so these are listed with the pages that moved, for a person to judge.

Before any pages are labelled, the hard tier cannot see a wrong role at all.
The report says so rather than passing silently.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
BASELINE = ROOT / "reports" / "_baseline.json"
REPORT = ROOT / "reports" / "regression-latest.md"
RESULTS = ROOT / "reports" / "_results"
BENCH_CACHE = ROOT / "benchmarks" / "cache"
LABEL_SCORE = RESULTS / "labels-score.json"

SOFT_KEYS = ("verified", "structural_flags", "columns_mapped", "equation_ok", "merged_cells",
             "totals_reconciled", "review")
#: For these, a *rise* is the bad direction.
RISE_IS_BAD = {"structural_flags", "review", "merged_cells"}


def _run(args: list[str], label: str) -> tuple[int, str]:
    print(f"[*] {label} ...", flush=True)
    started = time.perf_counter()
    proc = subprocess.run([PYTHON, *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    print(f"    exit {proc.returncode} in {time.perf_counter() - started:.0f}s", flush=True)
    return proc.returncode, proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# Collect
# ---------------------------------------------------------------------------


def _page_record(page: dict[str, Any], failed: bool) -> dict[str, Any]:
    record = {k: page.get(k, 0) for k in SOFT_KEYS}
    record.update({
        "silent_errors": len(page.get("silent_errors", [])),
        "coverage_loss": page.get("coverage_loss", 0),
        "healthy": bool(page.get("healthy", False)),
        "failed": failed,
    })
    return record


def collect(label_summary: dict[str, Any] | None) -> dict[str, Any]:
    pages: dict[str, dict[str, Any]] = {}
    for tag in ("dev", "heldout"):
        path = BENCH_CACHE / f"benchmark_cache_{tag}.json"
        if not path.is_file():
            continue
        for page in json.loads(path.read_text(encoding="utf-8")):
            key = f"benchmark/{tag} | {page['file']} p{page['page_index'] + 1}"
            pages[key] = _page_record(page, failed=not page.get("ok", True))
    for path in sorted(RESULTS.glob("batch-*.json")):
        batch = json.loads(path.read_text(encoding="utf-8"))
        for page in batch["pages"]:
            key = f"JUNE/batch-{batch['batch']:02d} | {page['file']} p{page['page']}"
            pages[key] = _page_record(page, failed=bool(page.get("error")))
    return {"generated": datetime.now().isoformat(timespec="seconds"),
            "pages": pages, "labels": label_summary or {}}


def totals(snapshot: dict[str, Any]) -> dict[str, int]:
    out = {k: 0 for k in (*SOFT_KEYS, "silent_errors", "coverage_loss")}
    out["unhealthy"] = out["failed"] = 0
    for record in snapshot["pages"].values():
        for key in (*SOFT_KEYS, "silent_errors", "coverage_loss"):
            out[key] += record[key]
        out["unhealthy"] += not record["healthy"]
        out["failed"] += record["failed"]
    out["pages"] = len(snapshot["pages"])
    return out


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------


def compare(current: dict[str, Any], baseline: dict[str, Any] | None,
            tests_ok: bool, tests_tail: str) -> tuple[list[str], list[str], list[str]]:
    """Return (hard failures, soft movements, notes)."""
    hard: list[str] = []
    soft: list[str] = []
    notes: list[str] = []
    now = totals(current)

    if not tests_ok:
        hard.append(f"test suite failed:\n```\n{tests_tail}\n```")
    if now["silent_errors"]:
        offenders = [k for k, r in current["pages"].items() if r["silent_errors"]]
        hard.append(f"{now['silent_errors']} silent error(s): " + "; ".join(offenders[:10]))
    if now["coverage_loss"]:
        offenders = [k for k, r in current["pages"].items() if r["coverage_loss"]]
        hard.append(f"coverage loss {now['coverage_loss']}: " + "; ".join(offenders[:10]))

    if baseline is None:
        notes.append("No baseline yet: only the absolute checks ran. "
                      "Run with --accept to record one.")
    else:
        was = totals(baseline)
        before, after = baseline["pages"], current["pages"]
        missing = sorted(set(before) - set(after))
        if missing:
            hard.append(f"{len(missing)} page(s) in the baseline were not produced: "
                        + "; ".join(missing[:10]))
        def bad(record: dict[str, Any], kind: str) -> bool:
            return record["failed"] if kind == "failing" else not record["healthy"]

        for kind in ("failing", "unhealthy"):
            shared = [k for k in after if k in before]
            got_worse = [k for k in shared if bad(after[k], kind) and not bad(before[k], kind)]
            got_better = [k for k in shared if bad(before[k], kind) and not bad(after[k], kind)]
            new_pages = [k for k in after if k not in before and bad(after[k], kind)]
            if got_worse:
                hard.append(f"{len(got_worse)} page(s) newly {kind}: " + "; ".join(got_worse[:10]))
            if new_pages:
                notes.append(f"{len(new_pages)} page(s) not in the baseline are {kind}: "
                             + "; ".join(new_pages[:10]))
            if got_better:
                soft.append(f"{len(got_better)} page(s) no longer {kind}: "
                            + "; ".join(got_better[:10]))

        for key in SOFT_KEYS:
            if now[key] == was[key]:
                continue
            worse = (now[key] > was[key]) == (key in RISE_IS_BAD)
            movers = sorted(((after[k][key] - before[k][key], k) for k in after
                             if k in before and after[k][key] != before[k][key]),
                            key=lambda m: -abs(m[0]))
            detail = "; ".join(f"{k} ({d:+d})" for d, k in movers[:6])
            soft.append(f"{key}: {was[key]} -> {now[key]} "
                        f"({'worse' if worse else 'better'} on its face). {detail}")

    labels_now = current.get("labels") or {}
    labels_was = (baseline or {}).get("labels") or {}
    if not labels_now.get("labelled_columns"):
        notes.append("**No reviewed column labels.** The hard tier cannot see a wrong "
                     "role until pages in reports/labels/column_roles.xlsx are marked Y.")
    else:
        if labels_was.get("labelled_columns") and \
                labels_was.get("labelled_pages") != labels_now.get("labelled_pages"):
            notes.append(f"The labelled set changed ({labels_was.get('labelled_pages')} -> "
                         f"{labels_now.get('labelled_pages')} pages) since the baseline, so "
                         "role counts are not comparable; accept a new baseline after labelling.")
        elif labels_was.get("labelled_columns"):
            for key, direction in (("wrong", 1), ("correct", -1), ("not_found", 1)):
                a, b = labels_was.get(key, 0), labels_now.get(key, 0)
                if (b - a) * direction > 0:
                    new = sorted(set(labels_now.get("mistakes", [])) -
                                 set(labels_was.get("mistakes", [])))
                    hard.append(f"labelled roles: {key} {a} -> {b}. New: " + "; ".join(new[:10]))
                elif b != a:
                    soft.append(f"labelled roles: {key} {a} -> {b} (better)")
    return hard, soft, notes


def write_report(current, baseline, hard, soft, notes) -> None:
    now = totals(current)
    lines = ["# Regression check", "",
             f"Run {current['generated']}. Baseline: "
             f"{baseline['generated'] if baseline else 'none'}.", "",
             f"**Result: {'REJECTED' if hard else 'PASSED'}**", ""]
    if notes:
        lines += [f"- {n}" for n in notes] + [""]
    lines += ["## Totals", "", "| Metric | Baseline | Now |", "| --- | ---: | ---: |"]
    was = totals(baseline) if baseline else {}
    for key in ("pages", "failed", "unhealthy", "silent_errors", "coverage_loss", *SOFT_KEYS):
        lines.append(f"| {key} | {was.get(key, '—')} | {now[key]} |")
    labels = current.get("labels") or {}
    if labels.get("labelled_columns"):
        lines += ["", "## Labelled column roles", "",
                  f"- Correct: **{labels['correct']}** of {labels['columns_with_a_role']} "
                  "columns that have a role",
                  f"- Wrong: **{labels['wrong']}** of {labels['roles_assigned']} roles assigned",
                  f"- Missed: {labels['missed']} left unknown, {labels['not_found']} not found"]
    lines += ["", "## Hard failures", ""] + ([f"- {h}" for h in hard] or ["None."])
    lines += ["", "## Soft movements — judge these", ""] + ([f"- {s}" for s in soft] or ["None."])
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reuse", action="store_true",
                        help="compare cached results without re-running the pipeline")
    parser.add_argument("--accept", action="store_true",
                        help="record the current results as the new baseline")
    parser.add_argument("--force", action="store_true",
                        help="with --accept: record even if hard checks fail")
    parser.add_argument("--no-labels", action="store_true",
                        help="skip scoring the labelled column roles")
    parser.add_argument("--baseline", type=Path, default=BASELINE,
                        help=f"baseline file to compare against (default {BASELINE.relative_to(ROOT)})")
    args = parser.parse_args(argv)
    baseline_path = args.baseline if args.baseline.is_absolute() else ROOT / args.baseline

    code, out = _run(["-m", "pytest", "tests/", "-q"], "test suite")
    tests_ok = code == 0
    tests_tail = "\n".join(out.strip().splitlines()[-15:])

    if not args.reuse:
        code, out = _run(["benchmark.py", "--set", "both", "--markdown"], "29-page benchmark")
        if code != 0:
            print(out[-2000:])
        sys.path.insert(0, str(ROOT))
        from batch_test import plan_batches
        batches = [str(n) for n in range(1, len(plan_batches()) + 1)]
        code, out = _run(["batch_test.py", "--batch", *batches], f"JUNE batches 1-{len(batches)}")
        if code != 0:
            print(out[-2000:])

    label_summary = None
    if not args.no_labels:
        if args.reuse and LABEL_SCORE.is_file():
            label_summary = json.loads(LABEL_SCORE.read_text(encoding="utf-8"))
        else:
            _run(["labels.py", "score", "--json", str(LABEL_SCORE)], "labelled column roles")
            if LABEL_SCORE.is_file():
                label_summary = json.loads(LABEL_SCORE.read_text(encoding="utf-8"))

    current = collect(label_summary)
    baseline = (json.loads(baseline_path.read_text(encoding="utf-8"))
                if baseline_path.is_file() else None)
    if baseline is None:
        print(f"note: no baseline at {baseline_path}")
    hard, soft, notes = compare(current, baseline, tests_ok, tests_tail)
    write_report(current, baseline, hard, soft, notes)

    print()
    for note in notes:
        print(f"note: {note}")
    for item in soft:
        print(f"soft: {item[:220]}")
    for item in hard:
        print(f"HARD: {item[:400]}")
    print(f"\n{'REJECTED' if hard else 'PASSED'} - see {REPORT.relative_to(ROOT)}")

    if args.accept:
        if hard and not args.force:
            print("baseline NOT updated: hard checks failed (use --force to override)")
            return 1
        baseline_path.write_text(json.dumps(current, indent=1), encoding="utf-8")
        print(f"baseline recorded: {baseline_path}")
        return 0
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
