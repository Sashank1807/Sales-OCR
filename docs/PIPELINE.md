# Extraction pipeline — Stages A and B

Column semantic mapping and the validation gate, for pharmaceutical distributor
stock & sales reports.

The goal is **not** perfect OCR. A dense page holds ~550 cells; at 99.9%
per-cell accuracy roughly 43% of pages still contain at least one error. The
goal is **zero silent errors**: every value is either proved consistent by
arithmetic or marked for a human. Nothing unverified passes through quietly.

---

## How the stages chain

```
                    ┌─ excel_reader ──┐
file ─► router ─────┼─ pdf_text_reader┼─► Grid ─► column_mapper ─► Document ─► validator ─► Document
   (per page:       └─ ocr_reader ────┘   (the     (Stage A:        (+roles)    (Stage B:     (+per-cell
    excel/pdf_text/     via readers/       grid     roles,                       checks)       status)
    image)              geometry.py        contract)sections)
```

`pipeline.py` is the single entry point:

```python
from pipeline import process_file
result = process_file("report.pdf")          # router -> reader -> A -> B
for page in result.ok_pages:
    print(page.ref.kind, page.report.counts, len(page.report.flagged))
print(result.review_cells, "cells need a human")
```

Stage B mutates the `Document` in place, stamping each `Cell` with a status and
reasons, and returns a `ValidationReport` describing what was tested.

```python
from column_mapper import map_grid_file
from validator import validate_document

document = map_grid_file("grid.json")     # Stage A
report = validate_document(document)      # Stage B

if report.flagged:
    for finding in report.flagged:
        print(finding.check, finding.message)
```

Multi-page documents go through `validate_pages`, which carries each page's
printed totals forward so the next page can recognise a cumulative total
instead of double-counting it:

```python
from validator import validate_pages
reports = validate_pages([page1, page2, page3])
```

Both modules are runnable on their own:

```bash
python column_mapper.py grid.json           # human-readable mapping summary
python column_mapper.py grid.json --json    # the full Document
python validator.py     grid.json           # validation report
python validator.py     grid.json --cells   # Document with per-cell status
python validator.py     grid.json --json    # report as JSON
```

`validator.py` exits non-zero when anything was flagged, so it drops into CI or
a shell pipeline unchanged.

---

## The reader layer

Three readers, one output shape. Stage A cannot tell which produced a page.

| Reader | Handles | Confidence | Recognition |
| --- | --- | --- | --- |
| `excel_reader` | `.xlsx` `.xlsm` `.xls` `.csv`, per sheet | 1.0 | none |
| `pdf_text_reader` | PDF pages with a usable text layer | 1.0 | none |
| `ocr_reader` | images, and PDF pages without one | per token | PaddleOCR |

### Routing is per page, not per file

A PDF routinely mixes native and scanned pages — in the sample corpus **6 of 79
do** — so a file-level verdict would send half a document down the wrong path.
The extension picks the family; whether a PDF page has a *usable* text layer is
measured: word count, alphanumeric density, and whether words carry real boxes.
A scanned page often carries a scrap of a text layer (a stamp, a footer), and
character count alone would be fooled by it.

### Shared geometry

`readers/geometry.py` does the reconstruction for both positioned-token
readers, so a native page and a scanned one produce grids of identical shape:

1. **Row clustering** by vertical centre, scaled to the median token height.
2. **Column bands** by projecting onto the x axis — counting *how many rows*
   put ink at each position, not how many tokens. That distinction matters: a
   full-width title line would otherwise bridge every gutter and collapse the
   table into one column. And because many reports right-align their figures,
   leaving no position empty on every row, the ink floor is **swept** upward
   until the columns resolve; the lowest floor that separates the most columns
   wins, so the split stays as conservative as the page allows.
3. **Cell assignment** by greatest x-overlap. A cell's confidence is its
   *weakest* token — a cell is only as trustworthy as its least certain part.

Because reconstruction is driven entirely by coordinates, **the order a reader
returns tokens in is irrelevant**. A scrambled extraction order is a non-issue
by construction rather than a case to repair.

### Two page-level repairs

Both are artefacts of layout rather than meaning, so both live in geometry:

- **Wrapped total rows.** A total printed across two lines, each filling
  different columns, is rejoined — but only when the rows are close together,
  each is sparse, *and* the columns they occupy are disjoint. A genuinely
  sparse row is never swallowed by its neighbour.
- **Merged product lines.** Two logical rows on one line are split where a
  description appears in a column that is numeric everywhere else. Anything
  less clear is annotated and left alone: inventing a row boundary is worse
  than reporting a suspicious one.

---

## Input contract

Every reader emits this, and `schema.load_grid` consumes it. Every field except
`rows` is optional, and cells may be bare strings, so a minimal grid is easy to
write by hand:

```json
{
  "page": 1,
  "source": "ocr",
  "tokens": [{"text": "463.00", "confidence": 0.97}],
  "rows": [
    {"index": 0, "cells": ["Description", "Opening", "In", "Out", "Balance"]},
    {"index": 1, "cells": [
      {"text": "AD 10 SACHETS", "bbox": [40, 120, 200, 132], "confidence": 0.98},
      {"text": "10.00",  "column": 1, "confidence": 0.99}
    ]}
  ]
}
```

- `column` addresses a cell explicitly; without it, position is used. Explicit
  indices let a row be legitimately sparse.
- `bbox` is `[x0, y0, x1, y1]`. It is what lets a spanning two-tier header be
  matched to the sub-columns beneath it.
- `tokens` is the OCR token stream. The coverage check compares it against what
  reached the output, so **omitting it silently disables that check** — the
  report will show `0/0`.

---

## The two-layer output

The raw layer is never rewritten by normalisation:

| Layer | Where it lives | Guarantee |
| --- | --- | --- |
| **Raw** | `Cell.raw_text`, `ColumnMapping.header_text` | Byte-for-byte what the document said. `500MG.`, `2MG/2I` and `1X10TAB` survive intact. |
| **Semantic** | `Cell.value`, `ColumnMapping.role` | Parsed `Decimal`, canonical role, confidence, method, evidence. |

Every cell carries `Provenance` — source, page, bounding box, OCR confidence,
token ids — plus its status and the reasons behind it.

`Decimal` throughout, never `float`: these are money and counts, and binary
rounding artefacts would contaminate the tolerance logic.

---

## Stage A — column mapping

Four passes, **reconciled** rather than short-circuited.

**1. Header detection.** Every row is scored on being non-numeric itself, on the
rows below it being numeric, and on keyword hits. Headers are found anywhere in
the grid, because multi-section pages have them mid-page.

**2. Two-tier merge.** `OPENING | RECEIPT | …` over `QTY. | VALUE | …` merges by
x-overlap of the parent bbox onto the child columns, producing `OPENING QTY.`.
A tier-2 row must be made of *bare* measure words; `Gross Amount` merely
contains one and is a header in its own right.

**3. Synonym matching.** Normalise, then exact → token-subset → prefix →
`difflib` fuzzy ≥ 0.82. Stdlib only.

**4. Arithmetic discovery.** For each ordered triple `(o, r, i)` the mapper
computes `o + r − i` per row and looks up which column matches — O(n³) with a
hash rather than O(n⁴). The same approach finds `qty × rate ≈ value`.

Reconciliation:

| Situation | Outcome |
| --- | --- |
| Header and arithmetic agree | confidence ≥ 0.95 |
| Header gave the flow, arithmetic settled qty/value | 0.92, not treated as a conflict |
| They disagree, ≥ 4 rows with movement back the arithmetic | arithmetic wins at 0.65, both recorded in `evidence` |
| They disagree on a short page | **header wins** — coincidental fits abound on little data |
| Only arithmetic | 0.80 |
| Neither | `unknown`, eligible for the VLM hook |

### Movements the four roles cannot name

Real ERPs post transfers and corrections in columns of their own, so the row
equation does not close on four terms. Where one extra column accounts for
every residual, Stage A reports the equation as
`opening + receipt − issue ± adjustment = closing`, keeps the receipt column
correctly assigned, and leaves the adjustment column **unmapped** rather than
mislabelling it. Stage B then includes it, so the rows verify instead of being
abandoned.

Without this the mapper picks whichever four-column subset fits best — on a
real page that meant tagging a transfer column as receipts and dropping the
actual purchase column.

### The symmetry that bites

`o + r − i = c` is algebraically identical to `o + r − c = i`. Arithmetic can
identify *which four columns* form the stock group but **cannot orient issue
against closing** — several permutations fit every row equally well. The
headings break the tie. With no headings at all the orientation is genuinely
undetermined, and the mapper records that on the columns rather than presenting
a coin-flip as fact.

Getting this wrong transposes two columns of every row while every check still
passes, which is precisely the silent error this pipeline exists to prevent. So
where the orientation cannot be settled, the mapper caps those columns'
confidence below the VLM threshold (routing the question to the fallback) and
Stage B raises a `column_orientation` finding that flags the affected cells.
Values that arithmetic vouches for are still only as trustworthy as the label
on them.

### Is this section a table at all?

Decided **before** column mapping, from five structural signals, none of which
depends on what the columns are called:

| Signal | A table | An address block |
| --- | --- | --- |
| row count | enough for a pattern | 2–6 |
| cell-count consistency | rows hold similar counts | ragged |
| band occupancy | rows fill the columns | a cell or two of many |
| numeric density | mostly figures | almost none |
| band stability | same columns down the section | varies per line |

They are weighed rather than counted, because a real table can be short
(Khushi's runs to two rows) or description-heavy, so no single signal may veto.
A worked example: the stock table on one page scored 0.86 (79% numeric, 89%
occupancy) against 0.37 for the address block above it (13% numeric, 52%).

A non-tabular section **keeps its content in the raw layer** and is not column
mapped, not arithmetic checked, and never sent to the VLM. Treating address
blocks as tables was the whole of a 3,833-column VLM census; the figure fell to
368 once they were excluded. `Section.tabular_signals` records the measurements
so the verdict can be audited.

### Also detected

- **Sections** — multiple tables on one page, each with its own header.
  Classified `TABULAR`, `NON_TABULAR` or `EMPTY` (headers with no rows).
- **Metadata** — distributor, address, phone, email, GSTIN, manufacturer,
  period, each with provenance.
- **Row types** — data, total, section title, metadata, blank.
- **Reversing flows** — a *sales return* is an inward movement. There is no
  canonical role for it, so the column stays `unknown` rather than being folded
  into issues and corrupting the arithmetic.

### VLM fallback

Defined, never required. Supply anything implementing `VLMColumnResolver`:

```python
from column_mapper import ColumnMapper, VLMColumnRequest, VLMColumnResponse

class MyResolver:
    def resolve(self, request: VLMColumnRequest) -> VLMColumnResponse:
        ...   # request carries headers, profiles and 5 sample rows
        return VLMColumnResponse(roles={4: "issue_qty"}, confidence={4: 0.7})

document = ColumnMapper(vlm_resolver=MyResolver()).map_document(rows)
```

It is consulted only for columns below `vlm_threshold` (0.55), it is asked for
*meaning* and never for transcription, and its answers are bounded: an
unrecognised role name is ignored, an already-assigned role is refused, and
confidence is capped at 0.75 so a VLM guess never outranks real evidence. A
resolver that raises is caught and noted — a failed fallback must not lose the
page.

---

## Stage B — validation

Every cell ends in one of four states. The distinction that matters is between
a value that *cannot* have been misread and one that merely has not been
checked:

| Status | Meaning | Review |
| --- | --- | --- |
| `exact` | from Excel or a PDF text layer — the characters are in the file, there was no recognition step | none |
| `verified` | recognised from pixels **and** confirmed by arithmetic or a printed total | none |
| `unchecked` | recognised from pixels, nothing available to confirm it | sampled |
| `flagged` | failed a check, or below the confidence threshold | every cell |

**`unchecked` is never a synonym for "fine"** — it means the document carried no
structure capable of testing this value.

The source decides `exact`, once, at construction. Precedence runs
`unchecked < verified < exact < flagged`, so confirming a deterministic cell by
arithmetic cannot quietly demote it — and `Cell.mark()` refuses to assign
`exact` to a pixel-derived cell outright, because precedence alone would let a
caller promote one.

**Review load** counts only pixel-derived cells (`flagged + unchecked`).
Counting Excel cells that cannot have been misread put the figure at roughly
16,200 across the development set when the real transcription load was 577, all
of it on image pages. Deterministic cells that fail a *structural* check — a row
that does not balance, a total that does not reconcile — are counted separately
as **structural flags**: those are layout or mapping faults, not something to
re-read.

### Invariants are tested, not assumed

The row equation is adopted only if it actually holds. If it holds on 68 of 70
rows, those 2 are flagged and the page stays usable. If it holds on none, the
relationship is declared inapplicable and those cells come back `unchecked`
rather than the page being buried in false positives.

**The subtlety that makes this work:** rows with no movement
(`receipt == issue == 0`) satisfy `o + r − i = c` trivially, under *any*
relationship. They are excluded when deciding whether an invariant applies, and
still checked once it has been adopted.

Without that exclusion, Bansal's value columns look 79% supported — 48 static
rows drown out the 16 that move — and the pipeline would flag 16 correct rows
while claiming to have verified the rest. With it, support is 0/16 and the value
relationship is correctly found not to apply, while the quantity relationship is
16/16 and adopted.

### Checks

| Check | Notes |
| --- | --- |
| `row_equation_qty` / `row_equation_value` | `opening + receipt − issue = closing`. Negative results are valid. Rows too sparse to judge are skipped, not failed. |
| `*_total_row` | The row equation applied to printed total rows in their own right. Enforced only for relationships the data established. |
| `rate_product` | `qty × rate ≈ value`, tolerance `max(0.1%, 0.10)` — a rate rounded to paise accumulates error with quantity. |
| `total` | Printed totals against column sums, with cumulative detection. |
| `coverage` | Every numeric token OCR saw must appear in the output. |
| `row_shape` | Cells past the last column are flagged; a sparse indexed row is reported, not flagged. |
| `gstin` | 15 characters, shape, and the base-36 check digit. |
| `date_format` | `dd/mm/yyyy`, `dd-mm-yyyy`, `dd/Mon/yyyy`, `yyyy-mm-dd`. |
| `confidence` | Any cell below `min_confidence` (default 0.80). |
| `column_orientation` | Columns whose role came from a symmetric equation with no heading to orient it. |
| `column_orientation` | Columns whose role came from a symmetric equation with no heading to orient it. |

### Blank versus zero

A blank that makes the arithmetic work is a genuine zero, recorded as
`blank_confirmed_zero`. A blank that breaks it is a missed read, flagged as
`blank_breaks_arithmetic`. Nil glyphs (`-`, `–`, `n/a`) are blank; `-64` is a
negative number.

### Totals

Three outcomes, in order:

1. Printed total equals the column sum → **verified**.
2. Printed total equals *carried + this page* → **verified** as cumulative, with
   a message saying not to add it to earlier pages again.
3. Neither. Then the magnitude decides: a printed total more than 10× away from
   the column sum is a **different measure** (`unchecked`), while anything
   closer is a real discrepancy (**flagged**).

That guard is what stops Krishna's `TOTAL 60837` — a value figure printed under
quantity columns that sum to 1303 — from flagging the whole page, while a total
of 1092 against a sum of 1082 is still caught.

---

## Page health

Cell metrics cannot see a page that produced no cells: it has no flagged cells,
no silent errors, and a perfect coverage ratio over zero tokens. A page can be
cell-clean and still be a total failure, so `pipeline.assess_health` judges
pages in their own right:

- no cells produced
- content read but no column bands resolved (skipped for Excel, which arrives
  already addressed and has no bands to resolve)
- no tabular section found on a page that has content
- slower than a threshold — a warning, not a failure

`benchmark.py` reports these in a **page health** table kept separate from the
cell metrics.

## Configuration

```python
from column_mapper import ColumnMapper, MapperConfig
from validator import Validator, ValidatorConfig

ColumnMapper(MapperConfig(header_accept=0.60, vlm_threshold=0.55,
                          arithmetic_support=0.70, min_override_rows=4))

Validator(ValidatorConfig(min_confidence=0.80, invariant_support=0.70,
                          rate_rel_tolerance=Decimal("0.001"),
                          total_magnitude_factor=Decimal("10")))
```

---

## Files

```
schema.py             Dataclasses, enums, number parsing, grid loading
readers/
  contract.py         Token / GridCell / GridRow / Grid - the shape all readers emit
  geometry.py         Row clustering, column bands, the two page repairs
  router.py           Per-page classification
  excel_reader.py     openpyxl / xlrd / csv
  pdf_text_reader.py  PyMuPDF word extraction
  ocr_reader.py       PaddleOCR, for images and scanned PDF pages
pipeline.py           file -> router -> reader -> Stage A -> Stage B
benchmark.py          Measurement against real pages; writes BENCHMARK.md
column_mapper.py      Stage A
validator.py          Stage B
tests/
  conftest.py                  fixtures and helpers
  test_column_mapper.py        29 tests
  test_validator.py            53 tests
  fixtures/_build_fixtures.py  transcriptions of the source documents
  fixtures/*.json              the generated grids
```

Fixtures are regenerated with `python tests/fixtures/_build_fixtures.py`. The
transcriptions live in compact row form in the builder so they can be audited
against the originals.

Run the suite with `python -m pytest tests/ -q`.

## Constraints honoured

- Standard library only, plus `pytest`. No network calls.
- Type hints throughout; `from __future__ import annotations` keeps the syntax
  valid on Python 3.10, which is what this repo's virtualenv runs.
- No hardcoded distributor names, and no hardcoded column positions — every role
  is discovered per document.
