# Extraction report — batch 07

Generated 2026-09-17 09:24. Corpus `JUNE/`. 10 file(s), 18 page(s), 8s total.

**There is no ground truth for this corpus.** No per-cell accuracy is quoted below and none can be: the source documents are unlabelled, so every figure here is something a document asserts about itself — whether its rows keep their shape, whether the stock equation closes, whether a printed total reconciles with the column above it.

## Headline

| Metric | Target | Result |
| --- | --- | ---: |
| **Silent errors** | 0 | **0** |
| **Coverage loss** (numeric tokens read but unplaced) | 0 | **0** |
| **Pages that failed outright** | 0 | **0** |
| **Unhealthy pages** | 0 | **0/18** |
| Cells extracted | — | 4516 |
| Deterministic (`exact`) | — | 3899 |
| Pixel-derived | — | 597 |
| Needing human review | as low as possible | 509 (85.3% of pixel cells) |
| Structural flags (deterministic cells) | as low as possible | 20 |
| Column roles assigned | report | 141/237 (59.5%) |

## Files tested

**Batch 7** — 8.1s

| File | Requested as | Router chose | Pages |
| --- | --- | --- | ---: |
| `genex (1).PDF` | PDF | pdf_text | 2 |
| `GENEX.pdf` | PDF | pdf_text | 7 |
| `Get_MR_MSS36202675214718.pdf` | PDF | pdf_text | 1 |
| `GS DIST JUNE26.pdf` | PDF | pdf_text | 1 |
| `HD.pdf` | PDF | pdf_text | 2 |
| `Bansal barelly.jpeg` | Scanned image | image | 1 |
| `CARE PHARMA JUNE26.jpeg` | Scanned image | image | 1 |
| `IMG20260714184904.heic` | Scanned image | image | 1 |
| `WhatsApp Image 2026-07-06 at 6.06.19 PM.jpeg` | WhatsApp image | image | 1 |
| `WhatsApp Image 2026-07-07 at 1.04.24 PM.jpeg` | WhatsApp image | image | 1 |

## Extraction per page

`eq` is how many mapped rows satisfy `opening + receipt − issue = closing`; `totals` is printed totals that reconcile against the column above them. A dash means no such check was available on that page.

| File | Pg | Source | Cells | exact | ver | flag | unchk | Rows | Cols | eq | totals |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `genex (1).PDF` | 1 | pdf_text | 248 | 248 | 0 | 0 | 0 | 36 | 6/7 | 35/35 | — |
| `genex (1).PDF` | 2 | pdf_text | 61 | 53 | 0 | 8 | 0 | 7 | 6/7 | 7/7 | 0/8 |
| `GENEX.pdf` | 1 | pdf_text | 427 | 427 | 0 | 0 | 0 | 42 | 10/11 | — | — |
| `GENEX.pdf` | 2 | pdf_text | 412 | 412 | 0 | 0 | 0 | 39 | 19/22 | 2/2 | — |
| `GENEX.pdf` | 3 | pdf_text | 543 | 535 | 0 | 8 | 0 | 49 | 10/11 | — | 0/9 |
| `GENEX.pdf` | 4 | pdf_text | 440 | 440 | 0 | 0 | 0 | 40 | 10/11 | 3/3 | — |
| `GENEX.pdf` | 5 | pdf_text | 413 | 413 | 0 | 0 | 0 | 39 | 20/24 | — | — |
| `GENEX.pdf` | 6 | pdf_text | 453 | 453 | 0 | 0 | 0 | 40 | 8/12 | — | — |
| `GENEX.pdf` | 7 | pdf_text | 144 | 144 | 0 | 0 | 0 | 17 | 6/16 | — | — |
| `Get_MR_MSS36202675214718.pdf` | 1 | pdf_text | 229 | 225 | 0 | 4 | 0 | 25 | 6/33 | — | — |
| `GS DIST JUNE26.pdf` | 1 | pdf_text | 158 | 158 | 0 | 0 | 0 | 23 | 5/10 | — | — |
| `HD.pdf` | 1 | pdf_text | 348 | 348 | 0 | 0 | 0 | 33 | 9/20 | 17/23 | — |
| `HD.pdf` | 2 | pdf_text | 43 | 43 | 0 | 0 | 0 | 11 | 1/4 | — | — |
| `Bansal barelly.jpeg` | 1 | image | 67 | 0 | 15 | 4 | 48 | 16 | 11/12 | — | 0/3 |
| `CARE PHARMA JUNE26.jpeg` | 1 | image | 141 | 0 | 72 | 9 | 60 | 20 | 6/8 | 18/18 | 0/4 |
| `IMG20260714184904.heic` | 1 | image | 196 | 0 | 1 | 41 | 154 | 23 | 4/10 | — | 1/2 |
| `WhatsApp Image 2026-07-06 at 6....` | 1 | image | 44 | 0 | 0 | 3 | 41 | 8 | 1/9 | — | — |
| `WhatsApp Image 2026-07-07 at 1....` | 1 | image | 149 | 0 | 0 | 0 | 149 | 17 | 3/10 | — | — |

## Is the output correctly aligned?

Four signals, none of which needs ground truth — each is the document disagreeing with itself about its own shape.

| Signal | What it means | Count |
| --- | --- | ---: |
| Coverage loss | a numeric token was read and then never reached a cell — data silently dropped | **0** |
| Overflow rows | a row put cells beyond the last column its header names | 0 |
| Sparse rows | a row's populated-cell count differs from its own section's most common width — usually a blank where the value is zero, which is expected, not a fault | 157 |
| Mixed-type columns | a column is numeric on some rows and prose on others, so something landed in the wrong band | 14 |
| Unheaded columns | data sits under a column the header never named | 90 |

Where a full stock quadruple was mapped, the row equation closes on **82 of 88** rows (93.2%). That is the strongest alignment evidence available: if a value had landed in the wrong column, the arithmetic would not balance.

Sparsity is counted but is **not** an alignment fault. `003063_.pdf` prints nothing where a movement is zero, so most of its rows populate 7 of 13 columns while a busy row populates all 13. CLAUDE.md §7 requires exactly that reading — a blank balance is zero, not a missing cell. The real alignment signals are the three above it.

Pages carrying genuine shape disagreement:

- `WhatsApp Image 2026-07-06 at 6.06.19 PM.jpeg` p1 — 0 overflow row(s), 3 mixed-type column(s), 6 sparse row(s)
- `Get_MR_MSS36202675214718.pdf` p1 — 0 overflow row(s), 2 mixed-type column(s), 2 sparse row(s)
- `genex (1).PDF` p1 — 0 overflow row(s), 1 mixed-type column(s), 1 sparse row(s)
- `GENEX.pdf` p2 — 0 overflow row(s), 1 mixed-type column(s), 14 sparse row(s)
- `GENEX.pdf` p5 — 0 overflow row(s), 1 mixed-type column(s), 12 sparse row(s)

## Defects found and corrected

Batch 7 was tested and fixed in the same round as batches 4–6, so its defects
are recorded in full in [`batch-04-06.md`](batch-04-06.md), findings 9–14. The
ones found *on* batch 7's files:

- **`IMG20260714184904.heic` was rejected as an unsupported file type** — now
  read, 196 cells, healthy (finding 9).
- **`GENEX.pdf` p6: 45 data rows above the header became preamble**, 215
  numeric tokens in 1 cell — now 453 cells, healthy (finding 10).
- **`GENEX.pdf` headings merged one column to the left** on every page, and
  continuation pages inherited the wrong names (finding 11).
- **Arithmetic overruled `OPENING QTY.` and `RECEIPT VALUE`** with a fit it
  cannot distinguish from the heading's reading (finding 12).
- **Inherited roles duplicated a role, wrote into the raw layer, and kept an
  orientation flag the source heading had already settled** — 190 cells on four
  GENEX pages (finding 13).

Batch 7 is the first batch with **no unhealthy pages and no failures**.

**Open:** totals reconcile on only 1 of 26 printed totals. Most batch-7 totals
sit on `GENEX.pdf` and `genex (1).PDF`, whose total rows print quantity and
value pairs; this was not investigated in this round.

