# Benchmark

Real pages from `D:\OCR_testing\SS`, pinned in `benchmark.py` so the numbers reproduce. `python benchmark.py --set both --markdown`

## Development set

13 pages the system was built against. Every threshold and every bug fix to date came from looking at these, so a good score here says only that the system fits what it was shaped around.

| Metric | Target | Result |
| --- | --- | --- |
| **Silent errors** | 0 | **0** |
| **Coverage loss** | 0 | **0** |
| **Unhealthy pages** | 0 | **0/13** |
| Pages processed | all | 13/13 |
| Routed correctly | all | 13/13 |
| Review load (pixel-derived cells) | low | 286 of 807 |
| Structural flags (deterministic cells) | low | 16 |
| Column mapping (tabular sections only) | report | 269/636 (42.3%) over 44 section(s) |
| VLM candidate columns | report | 373 |

| Source | Pages | Cells | Exact | Verified | Flagged | Unchecked | Review | Silent |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `excel` | 4 | 15641 | 15635 | 0 | 6 | 0 | **0** | 0 |
| `image` | 3 | 807 | 0 | 521 | 59 | 227 | **286** | 0 |
| `pdf_text` | 6 | 1610 | 1600 | 0 | 10 | 0 | **0** | 0 |

## Held-out set

16 pages from files never opened during development, run once. **The gap between this and the development set is the only honest measure of whether the system generalises.**

| Metric | Target | Result |
| --- | --- | --- |
| **Silent errors** | 0 | **0** |
| **Coverage loss** | 0 | **0** |
| **Unhealthy pages** | 0 | **0/16** |
| Pages processed | all | 16/16 |
| Routed correctly | all | 16/16 |
| Review load (pixel-derived cells) | low | 286 of 487 |
| Structural flags (deterministic cells) | low | 111 |
| Column mapping (tabular sections only) | report | 301/680 (44.3%) over 49 section(s) |
| VLM candidate columns | report | 394 |

| Source | Pages | Cells | Exact | Verified | Flagged | Unchecked | Review | Silent |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `excel` | 4 | 16492 | 16484 | 0 | 8 | 0 | **0** | 0 |
| `image` | 2 | 487 | 0 | 201 | 17 | 269 | **286** | 0 |
| `pdf_text` | 10 | 2915 | 2812 | 0 | 103 | 0 | **0** | 0 |

### The gap

| Metric | Development | Held out |
| --- | ---: | ---: |
| Silent errors | 0 | 0 |
| Coverage loss | 0 | 0 |
| Unhealthy pages | 0.0% | 0.0% |
| Routed correctly | 100.0% | 100.0% |
| Column mapping | 42.3% | 44.3% |
| Totals reconciled | 15/43 | 13/35 |
| Structural flags | 16 | **111** |
| Pixel cells needing review | 35.4% | **58.7%** |

Silent errors, coverage and routing hold up on unseen documents, and column mapping is essentially flat. 2 figures do not hold up:

- **Structural flags rise from 16 to 111.** Unseen layouts break the row equation far more often than the ones the system was shaped around. These are deterministic cells, so nothing was misread - the mapping or the row reconstruction is at fault.
- **58.7% of pixel-derived cells need review, against 35.4% on the development set.** On unseen image pages almost nothing could be verified at all.

## Page health

Cell metrics cannot see a page that produced no cells: it has no flagged cells, no silent errors and a perfect coverage ratio over zero tokens. A page can be cell-clean and still be a failure, so pages are judged separately.

| Document | Page | Source | Seconds | Problem |
| --- | ---: | --- | ---: | --- |
| `02_2060543_140_20260819095307562` | 3 | `image` | 5 | _closing page: only a total line, the table ended earlier_ |

## Review load, restated

Review load previously counted every cell that was not `verified`, which included Excel and PDF-text cells that **cannot have been misread**. Verification exists to catch misreading; where the source is deterministic there is nothing to catch. Those cells are now reported as `exact` and excluded.

| | Cells | Counted as review |
| --- | ---: | ---: |
| Old definition (every cell not `verified`) | 37952 | up to 37,230 |
| New definition (pixel-derived only) | 37952 | **572** |

The old figure is an upper bound: some of the 36,531 cells now called `exact` were also confirmed by arithmetic and would have been marked `verified` under the old scheme. How many is not recoverable from the cached run. Either way the reported review load fell by more than an order of magnitude, from tens of thousands of cells to 572.

Of 37952 cells, 36531 are `exact` and 1294 were read from pixels. The real transcription load is **572 cells**, confined to image pages. A further 127 deterministic cell(s) are flagged for structural reasons - a row that does not balance is a layout or mapping fault, not something to re-read.

## Silent errors

None in either set.

## Would the VLM fallback be used?

The fallback is defined but unimplemented, by design. The earlier census of 3,833 candidate columns was almost entirely an artefact: address blocks, title blocks and page footers were being treated as tables and their "columns" put to the VLM. Excluding non-tabular sections drops it to **767** across 29 pages - roughly a tenfold fall, and the remainder are columns of genuine tables.

That makes the decision evidence-based rather than a guess, but it is not yet a case *for* building the path: a candidate column is one the header vocabulary could not name, and most carry no stock role at all (batch numbers, expiry dates, free-text notes) for which no canonical role exists. A VLM would have nothing useful to return for those. The case rests instead on the specific pages where column boundaries or headings defeat the geometry, which are few and named in CLAUDE.md.

## The image path is the cost

5 image page(s) account for 13s of the run; the slowest single page took 5s. Every other page finished in under 6s.

`profile_image_path.py` breaks a page down by stage:

| Stage | Share of page time | Note |
| --- | ---: | --- |
| PaddleOCR detect + recognise | **84-100%** | one call; the two are not separable from outside `predict()` |
| engine load | 4.6s, once | per process, not per page |
| rasterise | <0.1s | negligible |
| token extraction | ~0s | negligible |
| geometry | ~0.01s | negligible |

**Device: CPU — `paddlepaddle` is built without CUDA.** The RTX 2000 Ada this project specifies is not being used at all. Recognition is effectively the whole cost and it is running on the wrong processor, so tuning anything else cannot move the number. Establishing that was the point of measuring; what to do about it is a separate decision.

## Bugs found in the measurement

Each of these made a number wrong rather than the pipeline wrong. They are listed because an unaudited metric is worse than no metric.

| What | Effect |
| --- | --- |
| The silent-error probe checked only `verified` | After the taxonomy split every Excel and PDF-text cell is `exact`, so the metric would have been **vacuous** for 8 of 13 development pages |
| A zero column sum bypassed the magnitude guard | A value total printed above an empty quantity column was reported as a silent error; the ratio was undefined, so the guard never ran |
| Page health flagged every Excel page for "0 column bands" | The Excel reader addresses cells directly and never runs band detection; 4 healthy pages were reported as failures |
| `Cell.mark()` could promote a pixel cell to `exact` | Precedence alone was not enough: `exact` outranks `unchecked`, so a caller could claim a recognised value could not have been misread |
| Review load read off the new counts | `flagged + unchecked` under the new statuses reports 1,618, understating the correction more than twentyfold; the old definition counted `exact` cells too |

---

## What these numbers do not say

The headline metrics are at target, and neither is the whole story.

**Verified rates are low, and that is mostly honest.** `pdf_text` verifies 0.0% of its cells, because those inputs carry long text columns and sheets with no totals to reconcile against - there is genuinely little to check. The pipeline says so rather than inflating the figure. But a low verified rate also means a high review load, which is what the business actually pays for.

**Totals reconciled: 28 of 78.** The other 50 are cases where the printed total is a different measure from the column it sits above, and the magnitude guard classified them as such. That guard is load-bearing - it is the difference between reporting zero silent errors and reporting several - and it is calibrated on a 10x ratio tested against a handful of documents, not hundreds.

**Column mapping, 43.3%.** The denominator counts every column of all 93 tabular sections, including sections that are fragments of a page rather than real tables. It is not comparable with the figure quoted for the hand fixtures, which counted only each document's main table.

**29 pages is a small sample**, chosen to span the three readers rather than to be representative. `--reuse` re-renders this report from `benchmark_cache.json` without re-running, so widening the manifest costs one pass, not one per metric change.
