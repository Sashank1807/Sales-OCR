# Extraction report — batch 04-06

Generated 2026-09-17 09:24. Corpus `JUNE/`. 30 file(s), 53 page(s), 52s total.

**There is no ground truth for this corpus.** No per-cell accuracy is quoted below and none can be: the source documents are unlabelled, so every figure here is something a document asserts about itself — whether its rows keep their shape, whether the stock equation closes, whether a printed total reconciles with the column above it.

## Headline

| Metric | Target | Result |
| --- | --- | ---: |
| **Silent errors** | 0 | **0** |
| **Coverage loss** (numeric tokens read but unplaced) | 0 | **0** |
| **Pages that failed outright** | 0 | **0** |
| **Unhealthy pages** | 0 | **4/53** |
| Cells extracted | — | 7678 |
| Deterministic (`exact`) | — | 2787 |
| Pixel-derived | — | 4713 |
| Needing human review | as low as possible | 4504 (95.6% of pixel cells) |
| Structural flags (deterministic cells) | as low as possible | 178 |
| Column roles assigned | report | 320/654 (48.9%) |

## Files tested

**Batch 4** — 20.3s

| File | Requested as | Router chose | Pages |
| --- | --- | --- | ---: |
| `Auragabad statement.pdf` | PDF | image | 5 |
| `Baheti Solapur.pdf` | PDF | pdf_text | 1 |
| `Balaji Kolhapur.pdf` | PDF | pdf_text | 1 |
| `Balaji Narayan Chitale.pdf` | PDF | pdf_text | 1 |
| `Baldawa Enterprises.pdf` | PDF | pdf_text | 3 |
| `1000513781.jpg` | Scanned image | image | 1 |
| `1000517651.jpg` | Scanned image | image | 1 |
| `1000517653.jpg` | Scanned image | image | 1 |
| `WhatsApp Image 2026-07-06 at 3.08.08 PM.jpeg` | WhatsApp image | image | 1 |
| `WhatsApp Image 2026-07-06 at 3.08.09 PM (1).jpeg` | WhatsApp image | image | 1 |

**Batch 5** — 19.3s

| File | Requested as | Router chose | Pages |
| --- | --- | --- | ---: |
| `CHIMANLAL-HD-1924-HETERO- DERMAGLOW-01-Jul-26-1108.PDF` | PDF | pdf_text | 1 |
| `CHiNTAN_AGENCiES-HH-1008-HETERO_HEALTHCARE_-_DERMA_GLOW-30-Jun-26-1745.PDF` | PDF | pdf_text | 1 |
| `CRYSTAL JUNE26.pdf` | PDF | pdf_text | 1 |
| `DEEPALI DRUG JUNE26.pdf` | PDF | pdf_text | 1 |
| `DOC-20260703-WA0021.pdf` | PDF | image, pdf_text | 14 |
| `1000517655.jpg` | Scanned image | image | 1 |
| `1000517666.jpg` | Scanned image | image | 1 |
| `1000517669.jpg` | Scanned image | image | 1 |
| `WhatsApp Image 2026-07-06 at 3.08.09 PM (2).jpeg` | WhatsApp image | image | 1 |
| `WhatsApp Image 2026-07-06 at 3.08.09 PM.jpeg` | WhatsApp image | image | 1 |

**Batch 6** — 12.8s

| File | Requested as | Router chose | Pages |
| --- | --- | --- | ---: |
| `DocScanner 05-Jul-2026 12-27 PM.pdf` | PDF | image | 4 |
| `DPLUS JUNE26.pdf` | PDF | pdf_text | 1 |
| `Elisan.pdf` | PDF | pdf_text | 1 |
| `GANESH AGENCY-H2-2707-HETERO HEALTHCARE LIMITED 2-30-Jun-26-1731.PDF` | PDF | image, pdf_text | 2 |
| `garimakota.PDF` | PDF | pdf_text | 1 |
| `1000517796.jpg` | Scanned image | image | 1 |
| `30ba5a25-8370-45b5-896b-2cc65561835c.jfif` | Scanned image | image | 1 |
| `Agarwal Jaipur.jpeg` | Scanned image | image | 1 |
| `WhatsApp Image 2026-07-06 at 3.08.10 PM.jpeg` | WhatsApp image | image | 1 |
| `WhatsApp Image 2026-07-06 at 6.06.19 PM (1).jpeg` | WhatsApp image | image | 1 |

## Extraction per page

`eq` is how many mapped rows satisfy `opening + receipt − issue = closing`; `totals` is printed totals that reconcile against the column above them. A dash means no such check was available on that page.

| File | Pg | Source | Cells | exact | ver | flag | unchk | Rows | Cols | eq | totals |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `Auragabad statement.pdf` | 1 | image | 129 | 0 | 0 | 22 | 107 | 14 | 2/11 | — | — |
| `Auragabad statement.pdf` | 2 | image | 253 | 0 | 56 | 9 | 188 | 16 | 7/17 | 15/15 | — |
| `Auragabad statement.pdf` | 3 | image | 138 | 0 | 0 | 5 | 133 | 10 | 7/15 | 0/9 | — |
| `Auragabad statement.pdf` | 4 | image | 189 | 0 | 0 | 38 | 151 | 23 | 8/29 | — | — |
| `Auragabad statement.pdf` | 5 | image | 11 | 0 | 0 | 0 | 11 | 3 | 0/0 | — | — |
| `Baheti Solapur.pdf` | 1 | pdf_text | 46 | 46 | 0 | 0 | 0 | 5 | 6/11 | — | — |
| `Balaji Kolhapur.pdf` | 1 | pdf_text | 231 | 231 | 0 | 0 | 0 | 16 | 7/16 | 13/14 | — |
| `Balaji Narayan Chitale.pdf` | 1 | pdf_text | 49 | 47 | 0 | 2 | 0 | 11 | 5/14 | — | — |
| `Baldawa Enterprises.pdf` | 1 | pdf_text | 472 | 446 | 0 | 26 | 0 | 62 | 13/39 | — | — |
| `Baldawa Enterprises.pdf` | 2 | pdf_text | 18 | 18 | 0 | 0 | 0 | 2 | 5/10 | — | — |
| `Baldawa Enterprises.pdf` | 3 | pdf_text | 60 | 60 | 0 | 0 | 0 | 8 | 3/8 | — | — |
| `1000513781.jpg` | 1 | image | 51 | 0 | 12 | 9 | 30 | 5 | 9/10 | — | — |
| `1000517651.jpg` | 1 | image | 332 | 0 | 0 | 3 | 329 | 32 | 2/11 | — | — |
| `1000517653.jpg` | 1 | image | 240 | 0 | 0 | 18 | 222 | 24 | 7/11 | 6/17 | — |
| `WhatsApp Image 2026-07-06 at 3....` | 1 | image | 212 | 0 | 0 | 8 | 204 | 80 | 4/15 | — | — |
| `WhatsApp Image 2026-07-06 at 3....` | 1 | image | 256 | 0 | 0 | 29 | 227 | 14 | 4/20 | — | 0/2 |
| `CHIMANLAL-HD-1924-HETERO- DERMA...` | 1 | pdf_text | 109 | 98 | 0 | 11 | 0 | 15 | 21/27 | 2/2 | — |
| `CHiNTAN_AGENCiES-HH-1008-HETERO...` | 1 | pdf_text | 96 | 81 | 0 | 15 | 0 | 12 | 7/10 | — | — |
| `CRYSTAL JUNE26.pdf` | 1 | pdf_text | 79 | 79 | 0 | 0 | 0 | 14 | 7/11 | 3/4 | — |
| `DEEPALI DRUG JUNE26.pdf` | 1 | pdf_text | 168 | 168 | 0 | 0 | 0 | 22 | 9/13 | — | — |
| `DOC-20260703-WA0021.pdf` | 1 | pdf_text | 240 | 201 | 0 | 39 | 0 | 24 | 6/13 | — | — |
| `DOC-20260703-WA0021.pdf` | 2 | pdf_text | 114 | 114 | 0 | 0 | 0 | 13 | 6/9 | 8/13 | — |
| `DOC-20260703-WA0021.pdf` | 3 | image | 227 | 0 | 2 | 78 | 147 | 21 | 7/12 | — | 4/4 |
| `DOC-20260703-WA0021.pdf` | 4 | image | 156 | 0 | 0 | 78 | 78 | 23 | 2/9 | — | — |
| `DOC-20260703-WA0021.pdf` | 5 | image | 60 | 0 | 0 | 2 | 58 | 12 | 3/6 | — | — |
| `DOC-20260703-WA0021.pdf` | 6 | image | 103 | 0 | 0 | 2 | 101 | 15 | 3/8 | — | — |
| `DOC-20260703-WA0021.pdf` | 7 | image | 87 | 0 | 0 | 2 | 85 | 14 | 2/7 | — | — |
| `DOC-20260703-WA0021.pdf` | 8 | image | 119 | 0 | 0 | 2 | 117 | 18 | 4/8 | — | — |
| `DOC-20260703-WA0021.pdf` | 9 | image | 49 | 0 | 0 | 2 | 47 | 11 | 2/6 | — | — |
| `DOC-20260703-WA0021.pdf` | 10 | pdf_text | 174 | 174 | 0 | 0 | 0 | 20 | 2/9 | — | — |
| `DOC-20260703-WA0021.pdf` | 11 | pdf_text | 116 | 90 | 0 | 26 | 0 | 13 | 6/9 | 11/13 | — |
| `DOC-20260703-WA0021.pdf` | 12 | pdf_text | 159 | 159 | 0 | 0 | 0 | 19 | 3/13 | — | — |
| `DOC-20260703-WA0021.pdf` | 13 | image | 63 | 0 | 10 | 19 | 34 | 13 | 7/9 | — | — |
| `DOC-20260703-WA0021.pdf` | 14 | image | 76 | 0 | 14 | 26 | 36 | 8 | 5/10 | 5/5 | 3/4 |
| `1000517655.jpg` | 1 | image | 195 | 0 | 0 | 5 | 190 | 22 | 7/11 | — | — |
| `1000517666.jpg` | 1 | image | 92 | 0 | 0 | 17 | 75 | 28 | 0/0 | — | — |
| `1000517669.jpg` | 1 | image | 57 | 0 | 0 | 7 | 50 | 18 | 0/0 | — | — |
| `WhatsApp Image 2026-07-06 at 3....` | 1 | image | 195 | 0 | 0 | 53 | 142 | 108 | 2/16 | — | — |
| `WhatsApp Image 2026-07-06 at 3....` | 1 | image | 156 | 0 | 0 | 13 | 143 | 96 | 0/8 | — | — |
| `DocScanner 05-Jul-2026 12-27 PM...` | 1 | image | 92 | 0 | 11 | 13 | 68 | 8 | 6/13 | 1/1 | 4/4 |
| `DocScanner 05-Jul-2026 12-27 PM...` | 2 | image | 50 | 0 | 0 | 0 | 50 | 11 | 5/6 | — | 0/2 |
| `DocScanner 05-Jul-2026 12-27 PM...` | 3 | image | 278 | 0 | 0 | 27 | 251 | 51 | 11/18 | — | — |
| `DocScanner 05-Jul-2026 12-27 PM...` | 4 | image | 312 | 0 | 0 | 7 | 305 | 27 | 9/12 | — | — |
| `DPLUS JUNE26.pdf` | 1 | pdf_text | 190 | 190 | 0 | 0 | 0 | 26 | 8/11 | 9/14 | — |
| `Elisan.pdf` | 1 | pdf_text | 80 | 76 | 0 | 4 | 0 | 16 | 7/8 | — | — |
| `GANESH AGENCY-H2-2707-HETERO HE...` | 1 | pdf_text | 489 | 448 | 0 | 41 | 0 | 60 | 36/65 | 12/13 | — |
| `GANESH AGENCY-H2-2707-HETERO HE...` | 2 | image | 15 | 0 | 0 | 0 | 15 | 3 | 4/9 | — | — |
| `garimakota.PDF` | 1 | pdf_text | 75 | 61 | 0 | 14 | 0 | 5 | 7/12 | 5/5 | 6/10 |
| `1000517796.jpg` | 1 | image | 36 | 0 | 5 | 4 | 27 | 3 | 6/11 | 2/2 | 1/2 |
| `30ba5a25-8370-45b5-896b-2cc6556...` | 1 | image | 127 | 0 | 31 | 32 | 64 | 18 | 7/10 | 5/7 | 2/5 |
| `Agarwal Jaipur.jpeg` | 1 | image | 202 | 0 | 32 | 84 | 86 | 26 | 6/8 | 14/14 | 0/4 |
| `WhatsApp Image 2026-07-06 at 3....` | 1 | image | 115 | 0 | 36 | 16 | 63 | 12 | 8/10 | 9/10 | 0/3 |
| `WhatsApp Image 2026-07-06 at 6....` | 1 | image | 40 | 0 | 0 | 4 | 36 | 12 | 0/0 | — | — |

## Is the output correctly aligned?

Four signals, none of which needs ground truth — each is the document disagreeing with itself about its own shape.

| Signal | What it means | Count |
| --- | --- | ---: |
| Coverage loss | a numeric token was read and then never reached a cell — data silently dropped | **0** |
| Overflow rows | a row put cells beyond the last column its header names | 22 |
| Sparse rows | a row's populated-cell count differs from its own section's most common width — usually a blank where the value is zero, which is expected, not a fault | 320 |
| Mixed-type columns | a column is numeric on some rows and prose on others, so something landed in the wrong band | 59 |
| Unheaded columns | data sits under a column the header never named | 55 |

Where a full stock quadruple was mapped, the row equation closes on **120 of 158** rows (75.9%). That is the strongest alignment evidence available: if a value had landed in the wrong column, the arithmetic would not balance.

Sparsity is counted but is **not** an alignment fault. `003063_.pdf` prints nothing where a movement is zero, so most of its rows populate 7 of 13 columns while a busy row populates all 13. CLAUDE.md §7 requires exactly that reading — a blank balance is zero, not a missing cell. The real alignment signals are the three above it.

Pages carrying genuine shape disagreement:

- `Baldawa Enterprises.pdf` p1 — 13 overflow row(s), 7 mixed-type column(s), 47 sparse row(s)
- `1000513781.jpg` p1 — 0 overflow row(s), 9 mixed-type column(s), 1 sparse row(s)
- `Auragabad statement.pdf` p4 — 0 overflow row(s), 6 mixed-type column(s), 13 sparse row(s)
- `Auragabad statement.pdf` p1 — 0 overflow row(s), 5 mixed-type column(s), 10 sparse row(s)
- `WhatsApp Image 2026-07-06 at 3.08.09 PM (2).jpeg` p1 — 3 overflow row(s), 2 mixed-type column(s), 16 sparse row(s)

## Pages needing attention

- **`Auragabad statement.pdf` p5 unhealthy:** no tabular section found among 1 section(s) (read 10 numeric token(s), produced 11 cell(s))
- **`1000517666.jpg` p1 unhealthy:** no tabular section found among 2 section(s) (read 33 numeric token(s), produced 92 cell(s))
- **`1000517669.jpg` p1 unhealthy:** no tabular section found among 2 section(s) (read 30 numeric token(s), produced 57 cell(s))
- **`WhatsApp Image 2026-07-06 at 6.06.19 PM (1).jpeg` p1 unhealthy:** no tabular section found among 3 section(s) (read 17 numeric token(s), produced 40 cell(s))

## Defects found and corrected

Findings from batches 4–7 are recorded here once, and every fix below was
re-measured across **all seven batches and the previous 29-page corpus** before
it was kept. Two changes were built and **reverted** in this round because they
made the totals worse; they are listed too.

### 9. Two phone photos were rejected before a pixel was read — **fixed**

`30ba5a25-….jfif` (batch 6) and `IMG20260714184904.heic` (batch 7) failed with
`unsupported file type`. `.jfif` is a JPEG under another name; `.heic` is what an
iPhone camera saves by default. The router allowed neither, and the OCR engine
decides what it can open by extension, so neither would have worked even if
routed. Both are now accepted, decoded with Pillow (`pillow-heif` for HEIC,
added to `requirements.txt`) with EXIF rotation applied, and handed to the
engine as pixels. **Result: 107 and 196 cells, both pages healthy.**

### 10. A page of 45 data rows above its header became preamble — **fixed**

`GENEX.pdf` p6 holds 45 rows of stock and then a header with nothing beneath it.
Everything above the first header was filed as address-block preamble: **215
numeric tokens, 1 cell**, page unhealthy. Coverage loss correctly read 0 — the
rows were in the raw layer — but nothing was mapped or checked.

When at least four rows above the first header read as data (the small-sample
floor, not the bare two-row minimum, so a phone number and a GSTIN line cannot
become a table), they now form a headerless section; the shape gate decides and
cross-page inheritance names the columns. **p6: 1 cell → 453, healthy.**

### 11. A centred two-tier header was merged one column to the left — **fixed**

On every page of `GENEX.pdf` the header is `OPENING | RECEIPT | ISSUE | CLOSING`
*centred* over `QTY. | VALUE` pairs. A centred heading overlaps only the VALUE
child, so the QTY child fell back to the nearest heading on its *left* — the
previous span. The merged headings read `ITEM DESCRIPTION QTY.` for opening,
`RECEIPT QTY.` for issue and `ISSUE QTY.` for closing, and every continuation
page inherited the wrong names.

`_spanning_parent` now tells a centred layout from a left-aligned one by
whether the next heading starts within the child's own width. Bansal's
left-aligned two-tier fixtures (§7) still pass. **GENEX headings now match the
page exactly.**

### 12. Arithmetic overruled headings it cannot possibly contradict — **fixed**

With GENEX's headings correct, the mapper still reported `OPENING QTY.` as
`receipt_qty` and the rupee column `RECEIPT VALUE` as `opening_qty`, at 0.65,
over two exact headings. The receipt-quantity column was blank, so the fit
borrowed the all-zero value column and swapped it with opening.

`opening + receipt` commutes, so arithmetic can never tell opening from receipt
— the same blindness as issue/closing, on the other side of the equals sign.
And a fit that needs a quantity where the heading itself says VALUE was built
from a column the document labels as something else. In both cases the data
carries no evidence against the heading, so the heading now decides.

**Consequence worth stating:** GENEX p1's "equation closes" count went 6 → 0 and
`All Mehsana Statement` p2 lost 16 verified cells. Both were verification of a
*wrong* mapping — a blank column standing in for opening, a value column for
receipt. On All Mehsana the heading now keeps `Opening Qty` as opening, the
vocabulary then misreads `Total In.Qty` as receipt (it is opening + inward), and
the equation fails on 0 of 4 rows — flagged, not passed. A hidden mis-mapping
became a visible one. That is the direction §2 asks for.

### 13. Inheritance: duplicates, a raw-layer write, and inherited guesses — **fixed**

Three defects in the batch-1 inheritance fix, all mine:

- **Duplicate roles.** `GENEX.pdf` p6 carried `closing_value` twice — one from
  its own arithmetic, one inherited. An inherited role now withdraws a weaker
  (arithmetic or shape) claim to the same role on that page.
- **It wrote into the raw layer.** Inheritance copied the source page's heading
  into `header_text`, which is marked *the document's words*. A continuation
  page prints no heading there, so that broke §4.4. The inherited heading now
  lives in the column's evidence only.
- **It passed guesses off as headings.** `DOC-20260703-WA0021.pdf` p14 inherited
  four roles from source columns whose heading was empty. A role now travels only
  if a heading stands behind it: directly, or because headings on the source page
  fix one term on **each** side of the equation, which pins the other two. One
  heading is not enough — `Adobe Scan` p4 has only `Op.Bal. Qty.`, and its fit
  called `Near Expiry` receipt and `MSR Price` closing.

**And a filter the new method slipped past.** The validator flags a column whose
issue/closing orientation arithmetic could not settle, via
`orientation_ambiguous`. Inherited columns kept *this* page's flag although the
source heading had settled it, so 190 cells on four GENEX pages were flagged as a
possible transposition already ruled out. Orientation now travels with the role.
This is §5's warning in practice: a new method value, and a check that filters
on mapping state went stale.

### 14. Compacted headings — **fixed**, and one latent tie bug — **open**

`Clqty`, `Clval` and `OpQty` scored nothing, because the measure word glued on
hides the flow (`Op Qty` scores 0.88). `_decompact` now splits it off for
matching only. `Cl` joins the closing vocabulary, mirroring `Op` for opening —
`Cl.Stock` on `11.pdf` was previously reachable only by arithmetic.
`Class`, `Clearance` and `approval` still match nothing.
**Effect:** `Balaji Kolhapur.pdf` equation 9/14 → 13/14, `Elisan.pdf` structural
flags 12 → 4, previous corpus 559 → 562 mapped columns.

It also **exposed a pre-existing bug** and cost the Leo Group statement 7 of its
14 closing rows: `Cl Stock Spoke` scores *exactly* 0.72 against both
`opening stock` and `closing stock`, and ties go to whichever flow the synonym
table lists first — opening. Previously `Cl Stock` had the same tie and masked it.

**Reverted:** treating every cross-flow tie as "names neither". It fixed Leo and
broke 19 other pages — equation rows 512 → 405, structural flags 385 → 539 —
because many correct headings tie on fuzzy scores. The tie needs a better
discriminator than rejection; it is left open with this evidence.

### What this round did not fix

- **`Auragabad statement.pdf` p3 — equation 0/9.** Headings are all present and
  correct (`Op | Purc | Sale | WSale | … | Clqty`), and `Sale` matches issue at
  0.95 — but it loses a duplicate contest to `WSale` (0.71) because the
  tie-break ranks *taking part in the arithmetic* above heading confidence, and
  `WSale` is an all-zero column that fits any equation. Near-expiry columns then
  fill receipt and closing. Flagged, not silent. Changing that precedence moves
  every page, so it needs its own measured round.
- **`Total In.Qty` read as receipt** (All Mehsana). A "total in" column is
  opening + inward. The vocabulary does not know this; a rule for it has not been
  measured.
- **Unhealthy images with 10–33 numeric tokens** (`1000517666.jpg`,
  `1000517669.jpg`, a WhatsApp image, `Auragabad` p5) — the same sparse-page
  question as batches 1–3, needing the source pages looked at.

