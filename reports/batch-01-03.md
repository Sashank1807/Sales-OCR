# Extraction report — batch 01-03

Generated 2026-09-17 09:24. Corpus `JUNE/`. 30 file(s), 63 page(s), 48s total.

**There is no ground truth for this corpus.** No per-cell accuracy is quoted below and none can be: the source documents are unlabelled, so every figure here is something a document asserts about itself — whether its rows keep their shape, whether the stock equation closes, whether a printed total reconciles with the column above it.

## Headline

| Metric | Target | Result |
| --- | --- | ---: |
| **Silent errors** | 0 | **0** |
| **Coverage loss** (numeric tokens read but unplaced) | 0 | **0** |
| **Pages that failed outright** | 0 | **0** |
| **Unhealthy pages** | 0 | **7/63** |
| Cells extracted | — | 9665 |
| Deterministic (`exact`) | — | 6659 |
| Pixel-derived | — | 2827 |
| Needing human review | as low as possible | 2596 (91.8% of pixel cells) |
| Structural flags (deterministic cells) | as low as possible | 179 |
| Column roles assigned | report | 296/592 (50.0%) |

## Files tested

**Batch 1** — 13.5s

| File | Requested as | Router chose | Pages |
| --- | --- | --- | ---: |
| `-__ Leo Group - The Leaders in Logistics __-(28).PDF` | PDF | pdf_text | 1 |
| `002621_160-61 (2).pdf` | PDF | pdf_text | 1 |
| `003063_.pdf` | PDF | pdf_text | 1 |
| `11.pdf` | PDF | pdf_text | 3 |
| `300176_.pdf` | PDF | pdf_text | 1 |
| `1000411293.jpg` | Scanned image | image | 1 |
| `1000411294.jpg` | Scanned image | image | 1 |
| `1000411295.jpg` | Scanned image | image | 1 |
| `IMG-20260630-WA0015 .jpg` | WhatsApp image | image | 1 |
| `IMG-20260707-WA0001.jpg` | WhatsApp image | image | 1 |

**Batch 2** — 7.7s

| File | Requested as | Router chose | Pages |
| --- | --- | --- | ---: |
| `305313_.pdf` | PDF | pdf_text | 11 |
| `305725_d_usp_stock_sale_item_code_305725.pdf` | PDF | pdf_text | 1 |
| `_Sales And Stock (Summary) 0107261198809.pdf` | PDF | pdf_text | 1 |
| `AAI PHARMA JUNE26.pdf` | PDF | pdf_text | 1 |
| `ADITYA.pdf` | PDF | pdf_text | 1 |
| `1000411296.jpg` | Scanned image | image | 1 |
| `1000411297.jpg` | Scanned image | image | 1 |
| `1000411298.jpg` | Scanned image | image | 1 |
| `IMG-20260707-WA0012.jpg` | WhatsApp image | image | 1 |
| `IMG-20260708-WA0011.jpg` | WhatsApp image | image | 1 |

**Batch 3** — 27.1s

| File | Requested as | Router chose | Pages |
| --- | --- | --- | ---: |
| `Adobe Scan Jul 05, 2026.pdf` | PDF | image, pdf_text | 5 |
| `all in one.pdf` | PDF | image | 12 |
| `All Mehsana Statement (1).pdf` | PDF | image | 7 |
| `AMI ENTERPRISE JUNE26.pdf` | PDF | pdf_text | 1 |
| `ASSAM-1.pdf` | PDF | pdf_text | 1 |
| `1000489931.jpg` | Scanned image | image | 1 |
| `1000507222.jpg` | Scanned image | image | 1 |
| `1000507225.jpg` | Scanned image | image | 1 |
| `IMG-20260708-WA0018.jpg` | WhatsApp image | image | 1 |
| `WhatsApp Image 2026-07-06 at 3.08.08 PM (1).jpeg` | WhatsApp image | image | 1 |

## Extraction per page

`eq` is how many mapped rows satisfy `opening + receipt − issue = closing`; `totals` is printed totals that reconcile against the column above them. A dash means no such check was available on that page.

| File | Pg | Source | Cells | exact | ver | flag | unchk | Rows | Cols | eq | totals |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `-__ Leo Group - The Leaders in ...` | 1 | pdf_text | 293 | 290 | 0 | 3 | 0 | 17 | 7/17 | 7/17 | — |
| `002621_160-61 (2).pdf` | 1 | pdf_text | 193 | 193 | 0 | 0 | 0 | 24 | 4/10 | — | — |
| `003063_.pdf` | 1 | pdf_text | 320 | 320 | 0 | 0 | 0 | 38 | 4/13 | — | — |
| `11.pdf` | 1 | pdf_text | 387 | 387 | 0 | 0 | 0 | 56 | 5/7 | 55/55 | — |
| `11.pdf` | 2 | pdf_text | 300 | 300 | 0 | 0 | 0 | 44 | 5/8 | 42/42 | — |
| `11.pdf` | 3 | pdf_text | 168 | 168 | 0 | 0 | 0 | 25 | 5/7 | 24/24 | — |
| `300176_.pdf` | 1 | pdf_text | 120 | 102 | 0 | 18 | 0 | 21 | 5/10 | — | — |
| `1000411293.jpg` | 1 | image | 105 | 0 | 0 | 7 | 98 | 15 | 5/9 | — | — |
| `1000411294.jpg` | 1 | image | 25 | 0 | 2 | 2 | 21 | 4 | 3/5 | — | 2/2 |
| `1000411295.jpg` | 1 | image | 76 | 0 | 0 | 1 | 75 | 8 | 2/6 | — | — |
| `IMG-20260630-WA0015 .jpg` | 1 | image | 70 | 0 | 0 | 12 | 58 | 9 | 4/8 | — | 0/1 |
| `IMG-20260707-WA0001.jpg` | 1 | image | 238 | 0 | 58 | 6 | 174 | 18 | 6/16 | — | — |
| `305313_.pdf` | 1 | pdf_text | 207 | 207 | 0 | 0 | 0 | 24 | 8/11 | 16/17 | — |
| `305313_.pdf` | 2 | pdf_text | 487 | 487 | 0 | 0 | 0 | 49 | 6/12 | — | — |
| `305313_.pdf` | 3 | pdf_text | 277 | 221 | 0 | 56 | 0 | 31 | 6/11 | — | — |
| `305313_.pdf` | 4 | pdf_text | 400 | 400 | 0 | 0 | 0 | 49 | 6/11 | 45/46 | — |
| `305313_.pdf` | 5 | pdf_text | 397 | 397 | 0 | 0 | 0 | 49 | 5/10 | — | — |
| `305313_.pdf` | 6 | pdf_text | 407 | 407 | 0 | 0 | 0 | 49 | 6/11 | 1/4 | — |
| `305313_.pdf` | 7 | pdf_text | 79 | 76 | 0 | 3 | 0 | 10 | 12/22 | — | — |
| `305313_.pdf` | 8 | pdf_text | 151 | 151 | 0 | 0 | 0 | 24 | 5/11 | 0/1 | — |
| `305313_.pdf` | 9 | pdf_text | 402 | 402 | 0 | 0 | 0 | 49 | 6/11 | — | — |
| `305313_.pdf` | 10 | pdf_text | 359 | 356 | 0 | 3 | 0 | 39 | 8/12 | — | — |
| `305313_.pdf` | 11 | pdf_text | 93 | 93 | 0 | 0 | 0 | 12 | 6/12 | — | — |
| `305725_d_usp_stock_sale_item_co...` | 1 | pdf_text | 124 | 124 | 0 | 0 | 0 | 21 | 4/10 | — | — |
| `_Sales And Stock (Summary) 0107...` | 1 | pdf_text | 79 | 70 | 0 | 9 | 0 | 10 | 6/8 | 9/9 | 0/5 |
| `AAI PHARMA JUNE26.pdf` | 1 | pdf_text | 99 | 99 | 0 | 0 | 0 | 17 | 8/9 | — | — |
| `ADITYA.pdf` | 1 | pdf_text | 147 | 147 | 0 | 0 | 0 | 14 | 1/12 | — | — |
| `1000411296.jpg` | 1 | image | 79 | 0 | 41 | 9 | 29 | 15 | 6/6 | 6/6 | 0/3 |
| `1000411297.jpg` | 1 | image | 76 | 0 | 35 | 14 | 27 | 14 | 11/12 | 7/7 | 0/4 |
| `1000411298.jpg` | 1 | image | 29 | 0 | 0 | 1 | 28 | 8 | 4/6 | — | 0/1 |
| `IMG-20260707-WA0012.jpg` | 1 | image | 126 | 0 | 0 | 20 | 106 | 20 | 4/6 | — | 0/2 |
| `IMG-20260708-WA0011.jpg` | 1 | image | 176 | 0 | 52 | 1 | 123 | 16 | 11/12 | 5/5 | — |
| `Adobe Scan Jul 05, 2026.pdf` | 1 | pdf_text | 173 | 173 | 0 | 0 | 0 | 18 | 12/22 | — | 1/5 |
| `Adobe Scan Jul 05, 2026.pdf` | 2 | image | 96 | 0 | 6 | 14 | 76 | 8 | 8/11 | — | 6/6 |
| `Adobe Scan Jul 05, 2026.pdf` | 3 | pdf_text | 386 | 373 | 0 | 13 | 0 | 58 | 1/10 | — | — |
| `Adobe Scan Jul 05, 2026.pdf` | 4 | pdf_text | 359 | 285 | 0 | 74 | 0 | 45 | 14/22 | 5/6 | — |
| `Adobe Scan Jul 05, 2026.pdf` | 5 | pdf_text | 310 | 310 | 0 | 0 | 0 | 38 | 14/22 | 0/16 | 0/5 |
| `all in one.pdf` | 1 | image | 97 | 0 | 0 | 22 | 75 | 17 | 6/10 | — | — |
| `all in one.pdf` | 2 | image | 74 | 0 | 0 | 0 | 74 | 11 | 3/8 | — | — |
| `all in one.pdf` | 3 | image | 62 | 0 | 0 | 0 | 62 | 13 | 1/6 | — | — |
| `all in one.pdf` | 4 | image | 30 | 0 | 0 | 1 | 29 | 10 | 1/4 | — | — |
| `all in one.pdf` | 5 | image | 32 | 0 | 0 | 2 | 30 | 5 | 0/0 | — | — |
| `all in one.pdf` | 6 | image | 81 | 0 | 0 | 1 | 80 | 13 | 2/11 | — | — |
| `all in one.pdf` | 7 | image | 44 | 0 | 0 | 7 | 37 | 10 | 0/0 | — | — |
| `all in one.pdf` | 8 | image | 63 | 0 | 0 | 2 | 61 | 12 | 2/6 | — | — |
| `all in one.pdf` | 9 | image | 39 | 0 | 0 | 0 | 39 | 7 | 2/14 | — | — |
| `all in one.pdf` | 10 | image | 155 | 0 | 0 | 1 | 154 | 28 | 0/0 | — | — |
| `all in one.pdf` | 11 | image | 56 | 0 | 0 | 0 | 56 | 7 | 1/13 | — | — |
| `all in one.pdf` | 12 | image | 161 | 0 | 1 | 24 | 136 | 15 | 7/15 | 3/4 | 1/3 |
| `All Mehsana Statement (1).pdf` | 1 | image | 109 | 0 | 14 | 27 | 68 | 17 | 5/9 | 1/1 | — |
| `All Mehsana Statement (1).pdf` | 2 | image | 51 | 0 | 0 | 0 | 51 | 9 | 5/7 | 0/4 | 0/4 |
| `All Mehsana Statement (1).pdf` | 3 | image | 52 | 0 | 22 | 4 | 26 | 8 | 5/7 | 2/2 | 0/4 |
| `All Mehsana Statement (1).pdf` | 4 | image | 37 | 0 | 0 | 0 | 37 | 7 | 1/6 | — | — |
| `All Mehsana Statement (1).pdf` | 5 | image | 40 | 0 | 0 | 1 | 39 | 7 | 0/0 | — | — |
| `All Mehsana Statement (1).pdf` | 6 | image | 82 | 0 | 0 | 9 | 73 | 20 | 0/0 | — | — |
| `All Mehsana Statement (1).pdf` | 7 | image | 116 | 0 | 0 | 4 | 112 | 15 | 2/11 | — | — |
| `AMI ENTERPRISE JUNE26.pdf` | 1 | pdf_text | 112 | 112 | 0 | 0 | 0 | 19 | 5/9 | — | — |
| `ASSAM-1.pdf` | 1 | pdf_text | 9 | 9 | 0 | 0 | 0 | 3 | 1/3 | — | — |
| `1000489931.jpg` | 1 | image | 49 | 0 | 0 | 4 | 45 | 7 | 5/10 | — | — |
| `1000507222.jpg` | 1 | image | 69 | 0 | 0 | 7 | 62 | 17 | 3/8 | — | — |
| `1000507225.jpg` | 1 | image | 47 | 0 | 0 | 11 | 36 | 15 | 0/0 | — | — |
| `IMG-20260708-WA0018.jpg` | 1 | image | 18 | 0 | 0 | 5 | 13 | 2 | 0/0 | — | — |
| `WhatsApp Image 2026-07-06 at 3....` | 1 | image | 167 | 0 | 0 | 4 | 163 | 23 | 6/17 | — | — |

## Is the output correctly aligned?

Four signals, none of which needs ground truth — each is the document disagreeing with itself about its own shape.

| Signal | What it means | Count |
| --- | --- | ---: |
| Coverage loss | a numeric token was read and then never reached a cell — data silently dropped | **0** |
| Overflow rows | a row put cells beyond the last column its header names | 21 |
| Sparse rows | a row's populated-cell count differs from its own section's most common width — usually a blank where the value is zero, which is expected, not a fault | 426 |
| Mixed-type columns | a column is numeric on some rows and prose on others, so something landed in the wrong band | 66 |
| Unheaded columns | data sits under a column the header never named | 27 |

Where a full stock quadruple was mapped, the row equation closes on **228 of 266** rows (85.7%). That is the strongest alignment evidence available: if a value had landed in the wrong column, the arithmetic would not balance.

Sparsity is counted but is **not** an alignment fault. `003063_.pdf` prints nothing where a movement is zero, so most of its rows populate 7 of 13 columns while a busy row populates all 13. CLAUDE.md §7 requires exactly that reading — a blank balance is zero, not a missing cell. The real alignment signals are the three above it.

Pages carrying genuine shape disagreement:

- `Adobe Scan Jul 05, 2026.pdf` p3 — 12 overflow row(s), 3 mixed-type column(s), 33 sparse row(s)
- `1000411293.jpg` p1 — 6 overflow row(s), 2 mixed-type column(s), 7 sparse row(s)
- `ADITYA.pdf` p1 — 0 overflow row(s), 6 mixed-type column(s), 5 sparse row(s)
- `305313_.pdf` p7 — 3 overflow row(s), 2 mixed-type column(s), 4 sparse row(s)
- `all in one.pdf` p9 — 0 overflow row(s), 4 mixed-type column(s), 2 sparse row(s)

## Pages needing attention

- **`all in one.pdf` p5 unhealthy:** no tabular section found among 1 section(s) (read 6 numeric token(s), produced 32 cell(s))
- **`all in one.pdf` p7 unhealthy:** no tabular section found among 2 section(s) (read 16 numeric token(s), produced 44 cell(s))
- **`all in one.pdf` p10 unhealthy:** no tabular section found among 3 section(s) (read 37 numeric token(s), produced 155 cell(s))
- **`All Mehsana Statement (1).pdf` p5 unhealthy:** no tabular section found among 1 section(s) (read 20 numeric token(s), produced 40 cell(s))
- **`All Mehsana Statement (1).pdf` p6 unhealthy:** no tabular section found among 5 section(s) (read 41 numeric token(s), produced 82 cell(s))
- **`1000507225.jpg` p1 unhealthy:** no tabular section found among 2 section(s) (read 9 numeric token(s), produced 47 cell(s))
- **`IMG-20260708-WA0018.jpg` p1 unhealthy:** no tabular section found among 1 section(s) (read 10 numeric token(s), produced 18 cell(s))

## Defects found and corrected

### 1. Continuation pages lost their column headings — **fixed**

**Where:** `11.pdf` page 2. The same fault will affect any multi-page report.

A paginated statement prints its column headings once. `11.pdf` page 1 carries
`Product Name | Strength | Op. Qty | Recevied Qty | Total Qty | Issue |
Cl.Stock`. Page 2 repeats only the company banner and then goes straight into
rows, so the mapper found no header, scored the **address block** as one
(`13, Erenda Road, Egra, Purba`, `Medinipur, West`, `721429`), and left the
roles to arithmetic alone.

Arithmetic cannot settle this. `o + r - i = c` and `o + r - c = i` are the same
statement, and swapping opening with receipt satisfies both readings equally.
All four roles came out transposed:

| Column | Real heading (page 1) | Role assigned | Correct role |
| --- | --- | --- | --- |
| 2 | `Op. Qty` | `receipt_value` | `opening_qty` |
| 3 | `Recevied Qty` | `opening_value` | `receipt_qty` |
| 6 | `Issue` | `closing_value` | `issue_qty` |
| 7 | `Cl.Stock` | `issue_value` | `closing_qty` |

Two of them were reported at confidence **0.80**, and the page raised **no
extra flag** for any of it — the equation balanced under the wrong reading, so
nothing downstream could tell. A consumer reading `opening_qty` off page 2 would
have got the receipt column. On row 1 that is opening 1 and receipt 177, where
the document says opening 177 and receipt 1.

**Fix:** `_inherit_headers_across_pages` in `pipeline.py`. A tabular section
that no heading reached inherits its roles from the nearest earlier page of the
same file whose section *was* named. Matching is by **horizontal position**, not
column index: a continuation page has no header row to bridge a gutter, so band
detection resolves 7 columns on page 1 of `11.pdf` and 8 on page 2 for the same
table, and index-matching silently fails. Inherited roles arrive capped at 0.50
confidence, marked `inherited`, carrying the originating page's header text, and
never outrank a heading a page found for itself.

Nothing about this is document-specific (CLAUDE.md s4.3): the rule is that a
table continued onto another page keeps its columns, which is a property of
pagination.

**Effect:** all four roles on `11.pdf` p2 now correct. Rows with a full mapped
quadruple rose 96 to 138 across the batch, of which 135 satisfy the equation.
All 134 existing tests still pass.

**Worth noting for the metrics:** `columns_mapped` did **not** move — it was 4
before and 4 after. The count was never wrong; only the meaning was. No metric
in the suite could see this, which is why it survived until a multi-page file
from a new corpus exposed it.

### 2. A coverage-loss figure of 60 was a bug in the test harness — **fixed**

The first run of this batch reported 60 numeric tokens read but never placed,
against a target of 0. That was wrong. `batch_test.py` was counting any token
containing a digit, so invoice numbers, pack sizes and dates all scored as lost
data. Switched to the validator's own `CoverageReport`, which is the accounting
CLAUDE.md s8 actually targets. **Real coverage loss for this batch is 0.**

### 3. A sales table was returned as prose, making its page unhealthy — **fixed**

**Where:** `1000411295.jpg`. Also `02_2061290` in the previous corpus, an item
that has been open in the backlog as §10 item 3a.

`Company | QTY. | FREE | RATE | AMOUNT | (%)` — eight data rows under a header
the reader found exactly — was classified `non_tabular`, so the page reported
"no tabular section found" and failed its health check.

The cause was that table-ness was being decided twice. `_is_tabular` settles it
on shape alone (occupancy, numeric density, consistency, band stability), and
that gate passed. Then `_classify_section_kind` demoted the section anyway for
having fewer than two *stock-flow* roles. That conflates "is this a table" with
"is this a stock table". §1 says the corpus holds sales and purchase registers
as well as stock statements, and a table without an opening/closing pair is
still a table.

**Fix:** the shape gate now decides table-ness on its own. A tabular section
with no stock-flow columns is still tabular; it simply carries a note that no
row equation applies, so its cells get no arithmetic confirmation. The existing
withdrawal of stray single stock-role matches is kept.

**Effect:** batch 1 unhealthy 1 → **0**. Previous corpus unhealthy 3 → **2**,
with `02_2061290` yielding a table for the first time.

**Denominator warning (§12).** This changes what counts as a tabular section,
and column mapping is reported over tabular sections. Both numerator and
denominator grew, so the *rate* barely moved while the counts did — the old and
new figures are not directly comparable:

| | Before | After |
| --- | --- | --- |
| Batch 1 | 53/110 (48.2%) | 55/116 (47.4%) |
| Previous corpus | 544/1256 (43.3%) | 559/1292 (43.3%) |

This is partly a genuine fix and partly a redefinition of the measure. Both,
stated separately, as §12 requires.

### 4. A rupee column was mapped as closing **quantity** — **fixed**

**Where:** `003063_.pdf`. `BVal` (balance value) was mapped `closing_qty` at
0.69 while the real balance column, `Adj Bal.`, went unmapped. The closing
column then read 23742 against an opening of 133 — a 178× gap.

`BVal` is one token, so whole-token matching never saw the `val` inside it. The
fuzzy matcher scored `bval` against `bal` at 0.857 → 0.686. It scores `bval`
against `val` at *exactly the same* 0.857, so the two readings tied and the
balance reading won on ordering alone. Meanwhile `adjbal` vs `bal` scores 0.667,
under the 0.82 floor, so the correct column could not compete.

**Fix:** `_measure_suffix` in `column_mapper.py`. A single token ending in a
measure word after a prefix of one or two characters carries that measure —
`BVal`, `SVal`, `OpQty`. The prefix limit is what keeps it honest: `approval`
must not read as a value column. Whole-token matches still win outright, so an
explicit `Qty` in a heading always outranks a compacted ending.

**Effect:** `BVal` now maps `closing_value`, which is what it is. `Adj Bal.`
remains unmapped at 0.667 — that is the vocabulary gap §11 job 1 exists for, and
forcing it here would mean tuning a threshold to make one page look better.

### 5. "Overflow rows" was double-counting a fact the reader already handles — **fixed**

The first run reported 59 overflow rows, 44 of them on `11.pdf` p2. Those rows
were populating columns 6 and 7, which the section had *already* recorded in
`unheaded_columns` — the distinction §10 item 2a was written to draw: a column
nearly every row fills is one the header failed to name, not a row that spilled.
The harness was counting that single fact about the header once per row beneath
it. Excluding known-unheaded columns: **59 → 6**.

"Ragged rows" is also not an alignment fault, and the report no longer presents
it as one. `003063_.pdf` prints nothing where a movement is zero, so most rows
populate 7 of 13 columns. §7 requires exactly that reading — a blank balance is
zero. It is now reported as sparsity, descriptively.

### 6. A stranded header cost 686 structural flags across one file — **fixed**

**Where:** `305313_.pdf`, eight of its ten pages. 686 of batch 2's 731 flagged
cells came from this one file.

Each page laid out as: report title (row 2), the real eleven-column header
(row 3), a lone label `Manufacturer Mfac Name` (row 4), the manufacturer group
`Manufacturer 000092HETERO` (row 5), then 49 data rows. Rows 3 and 5 were both
scored as headers, so row 3's names were stranded in a section with no rows
while all 49 data rows sat under row 5's two cells — five columns reported as
`unheaded`, and every deterministic cell in them structurally flagged.

This is the same defect as batch 1's finding 1 and §10 item 2b, but the fix
from batch 1 did not catch it: it required the two header rows to be *literally
adjacent*, and here a single-cell label sits between them at row 4.

**Fix:** adjacency now means nothing but whitespace and labels in between —
the rows between the two headers must contain no `DATA` row. The other two
guards are unchanged and still do the work they were added for: the pair must
have a body (which is what keeps Khushi's two trailing headers separate), and
the upper row must be the fuller of the two (which is what keeps a banner like
`STOCKIST NAME` from folding into a complete header below it).

**Effect, batch 2:**

| | Before | After |
| --- | ---: | ---: |
| Structural flags | 686 | **71** |
| Flagged cells | 731 | **116** |
| Overflow rows | 69 | **3** |
| Columns mapped | 115 | **130** |
| Rows with a mapped quadruple | 57 | **95** |
| Equation closes | 45 | **89** |

**Still wrong on this file, and not fixed:** the bands are merged. `Pur SP` is
two columns in one band, `SS Br Bsc qt Cr` is four, `Db Adj Bal.` is two. The
headings now reach the table but several name a band holding more than one
column, so `Db Adj Bal.` maps `opening_qty` when the real opening is `Op.`.
That is §10 item 3a, and the band-split attempt earlier in this session was
reverted for breaking a page it was not aimed at.

### 7. Pages with data but no header produced nothing — **fixed**

**Where:** `all in one.pdf` p2 and p12, and the same shape on any scanned
report that paginates without repeating its headings.

Page 2 opens straight onto `.BILASET SYP 60ML | 60MI | 0 | 0 | 0 | 0 | 0` and
runs for 68 numeric tokens in a clean eight-column grid. It produced **zero
cells and zero sections**, because `_split_sections` returned nothing when no
header row was detected.

The data was not lost — it fell through to the raw layer as preamble rows,
which is why coverage loss correctly reported 0. But nothing was column-mapped,
nothing was arithmetic-checked, and every cell metric read zero for the page.
The two-layer design (§4.4) held; the semantic layer was simply never built.

**Worth stating plainly, because it nearly fooled this report:** a page showing
`cells=0, tokens seen=68, placed=68, loss=0` looks like a metric contradiction
and was the thread worth pulling. It was not a contradiction — `iter_all_cells`
counts preamble rows, and the harness's `cells` figure counts only section
cells. Both were right and they were measuring different things.

**Fix:** `_headerless_section` emits one unheaded section instead of nothing.
The shape gate then decides, as it does everywhere else: a real grid becomes a
table whose columns are merely unnamed, and a page of prose is rejected by
`_is_tabular` and stays a non-tabular block. Cross-page inheritance then names
what it can — on `all in one.pdf` p2 it recovered `Receipt` and `Closing` from
an earlier page.

**Effect, batch 3:** unhealthy 9 → **7**, cells 3031 → **3132**, columns
113/261. Review load rose 1667 → 1759, which is the honest direction: those
cells are now part of an extracted table and so genuinely need review, where
before they were invisible.

### 8. Seven pages still find no table — **open**

All seven produce sections but no tabular one. They are not all the same case
and should not be treated as one number:

- **`all in one.pdf` p10 is a real table being rejected.** Section 2 holds 27
  data rows of ten numeric columns and scores **0.45 against the 0.50 gate** —
  occupancy 42%, numeric 24%, consistency 0.62, stability 0.41. It is a scanned
  page and OCR noise leaves rows of uneven length, which the consistency and
  stability signals punish. This is §10 item 7: those weights and that
  threshold were fitted on four documents. Lowering the gate would admit this
  page and an unknown number of prose blocks with it, so it is **not** being
  tuned here — §13 forbids moving a threshold to improve a number without first
  establishing what else moves.
- **`all in one.pdf` p5 and p7, `1000507225.jpg`, `IMG-20260708-WA0018.jpg`**
  carry 6 to 16 numeric tokens each. These look genuinely sparse rather than
  misread, and "no tabular section" may be the correct answer for them. The
  health check assumes every page of a stock report contains a table
  (`pipeline.py`), which is not true of a 12-page scan that includes covers and
  summary pages. Deciding this needs the source pages looked at, not more code.

