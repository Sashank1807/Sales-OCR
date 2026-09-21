# CLAUDE.md

Durable context for this project. Read this first in every session.

This file is the **only** standing context. There is no external reviewer —
§12 carries the review discipline that was previously applied from outside.
Keep §9 and §10 current as work lands; a stale status section is worse than
none.

---

## 1. What this is

An extraction system for pharmaceutical distributor **stock & sales reports**.
Inputs arrive as Excel files, native PDFs, scanned PDFs, and mobile phone
photos. Every distributor uses different billing software, so layouts vary
widely and no two reports look alike.

Output is structured, auditable data: what each report says, with every value
traceable to its source and carrying a status.

**Corpus:** 79 PDFs probed — 42 native, 31 scanned, 6 genuinely mixed (native
and scanned pages in one file). Routing is decided **per page**, never per
file.

## 2. The accuracy goal

**100% automatic accuracy is not the goal and is not achievable.** A dense page
holds ~550 cells; at 99.9% per-cell accuracy roughly 43% of pages still contain
an error. No model fixes this.

The goal is **zero silent errors**: the system never passes on a value it has
not either read deterministically or confirmed by arithmetic. Everything else
is flagged for a human.

A rise in flag rate is acceptable. A single silent error is not.

## 3. Hardware and stack

**Hardware:** NVIDIA RTX 2000 Ada, 16GB VRAM. 224 GB/s, 70W, entry-level.
GPU time is the scarce resource, not VRAM.

**Stack:** Python 3.10-compatible syntax (venv is 3.10.11; runs unchanged on
3.11+). PaddleOCR PP-OCRv6 medium (re-chosen over v5
server on 238 pages, §10 item 11), PyMuPDF, openpyxl/xlrd, pytest.
Qwen2.5-VL-7B-AWQ via vLLM is designed for but **not built** — see §11.

## 4. Architecture principles

Not negotiable. If a task appears to require breaking one, say so rather than
working around it.

1. **Digits come from deterministic sources, never from an LLM.**
   Excel → openpyxl. Native PDF → PyMuPDF text layer. Scans and photos →
   PaddleOCR. An LLM may supply *meaning* — layout, column semantics, section
   boundaries — never numbers.
2. **Grounding.** Any value an LLM emits must exist in the OCR token set near
   that position, or it is a hallucination and is rejected.
3. **No hardcoded layouts.** No distributor names, column positions, page
   templates or per-document rules. Structure is discovered per document.
   Domain knowledge (what a stock statement is, that quantities balance) is
   allowed and necessary. Document-specific knowledge is not.
4. **Two-layer output.** A *raw layer* of verbatim cell strings with the
   document's own headings, unmodified; and a *semantic layer* of canonical
   role tags with confidence. Never overwrite raw with normalised values.
5. **Cell-level provenance.** Every cell carries source, bounding box,
   confidence, status, and the reason for that status.
6. **Minimise LLM output tokens.** An LLM returns structure only (~100 tokens),
   never transcriptions. Full transcription runs only on flagged crops.
7. **Fail loudly.** Anything unverifiable is `flagged` or `unchecked`, never
   quietly accepted.

## 5. Cell status taxonomy

| Status | Meaning | Review |
| --- | --- | --- |
| `exact` | from a deterministic source; not subject to reading error | No |
| `verified` | recognised from pixels **and** confirmed by arithmetic or a printed total | No |
| `unchecked` | recognised from pixels, no check available | Sampled |
| `flagged` | failed a check, or below the confidence threshold | Every cell |

- Reader source alone determines `exact`. Nothing downstream may promote a
  pixel-derived cell to `exact` or demote a deterministic one. Precedence
  ordering is not sufficient protection — `Cell.mark()` needs an explicit
  guard, and once had this bug.
- An `exact` cell can still be `flagged` for a **structural** reason — a broken
  row equation, a total that will not reconcile. That is a layout or mapping
  fault, not a reading fault, and the reason must record which.
- **Review load** = (`flagged` + `unchecked`) over **pixel-derived cells only**.
  Report `exact` separately. Counting exact cells as review load overstated the
  figure by more than an order of magnitude and was a real defect.
- **Any metric that filters on status must be re-audited whenever the taxonomy
  changes.** The silent-error probe checked only `verified` and would have gone
  vacuous for 8 of 13 pages after the split.

## 6. Pipeline

```
file → router → reader → column_mapper → validator → result
                  │
    ┌─────────────┼─────────────┐
 excel_reader  pdf_text_reader  ocr_reader
 (openpyxl)    (PyMuPDF)        (PaddleOCR)
                  └── shared: readers/geometry.py
```

All readers emit the same **grid contract** (`PIPELINE.md`): sections, rows,
cells; each cell carrying text, bounding box, confidence, source. Row
clustering and column-gutter detection live in `readers/geometry.py`, shared,
never duplicated.

The Excel reader addresses cells directly and never runs band detection —
page-health checks must not expect column bands from it.

Multi-page documents go through `validate_pages([...])` so cumulative totals
resolve across pages.

## 7. Reference documents

Four hand-transcribed reports, held as fixtures in `tests/fixtures/`. The
original files are **not available and will not be** — the fixtures are the
whole of the ground truth, and every case below must keep passing.

### Amar Pharmaceuticals — clean render
Columns: Description, Code, Opening, In, Out, Balance, Unit, Rate, Value

- `AD 10 SACHETS`: 10 + 50 − 10 = 50; 50 × 9.26 = 463.00
- `C FURO 250 TAB`: 53 + (blank) − 42 = 11; 11 × 127.43 = 1401.73 vs printed
  1401.68 — **must pass** within tolerance (0.0036%)
- `FORSLEEP ORAL SPRAY`: In=1, Out=1, Balance blank → blank reads as zero
- Grand Total: 9609 + 3339 − 4647 = 8301
- Units are truncated in the source (`2MG/2I`, `500MG.`) — verbatim, never
  autocorrected
- Grand Total wraps across two visual lines — un-wrapping is the reader's job
- Fixture is a 24-row subset of ~78

### Bansal Medical Agencies — native PDF
Two-tier header (`OPENING/RECEIPT/…` over `QTY./VALUE`), 64 rows, 11 columns

- `LANOL ER TAB`: 136 + 400 − 600 = **−64** — negative closing is valid data
- Page 1 TOTAL: 1082 + 895 − 1064 = 913
- Page 2 TOTAL (1336) is **cumulative** — must not be double-counted
- `ENUFF 10`: quantities reconcile (95 + 100 − 160 = 35), values do **not**
  (960.45 + 1011.00 − 1710.00 ≠ 353.85) — issues are priced differently
- Two products merged into one text line (`...0.00 -IMIDIL CREAM`)
- All eight printed totals reconcile exactly against the transcription, so a
  mismatch is the reader's fault, never the fixture's

### Khushi Healthcare — native PDF
- Plain text extraction is **out of reading order**; reconstruction must be
  coordinate-based
- Sections with headers and **zero data rows** — return an empty section, never
  invent rows
- `Sales Ret.` (an inward movement) and `Misc. Out` have no canonical role and
  are deliberately `unknown` rather than folded into receipts or issues

### Krishna Pharma — phone photo
- Rotated 90°, handheld, blue pen circles over digits in the closing column
- TOTAL of 60837 is a **value** total under quantity columns; opening
  quantities sum to 1303, a 46.7× gap. The magnitude guard must classify this
  as a different measure rather than flagging all 14 rows
- A second non-tabular block (purchase details: supplier, invoice no., dates,
  amount)

## 8. Metrics

| Metric | Definition | Target |
| --- | --- | --- |
| **Silent error rate** | cells marked `exact` or `verified` that contradict the document's own printed total | **0** |
| **Coverage loss** | tokens read that never reached a cell | **0** |
| **Unhealthy pages** | pages failing a page-level check | **0** |
| Review load | (`flagged` + `unchecked`) pixel-derived cells | as low as possible |
| Structural flags | deterministic cells flagged for layout/mapping faults | as low as possible |
| Column mapping | roles correct ÷ columns of **tabular** sections | state the denominator |

Per-cell accuracy is **not computed and is not pending**. The §7 reference
documents exist as fixtures only, so reader output cannot be diffed against a
transcription, and the benchmark corpus is unlabelled by design. The ground
truth is what each report prints about itself — which is why the totals checks
and the magnitude guard are load-bearing rather than incidental. New pages
arrive unseen and are measured the same way.

Break every metric down by source (`excel` / `pdf_text` / `image`) and by
document. Report **development and held-out separately** — the gap is the only
honest measure of generalisation.

Page health is separate from cell metrics. A page can be cell-clean and still
be a failure: zero cells produced, no tabular section where one was expected,
or text detected with no column bands resolved.

## 9. Current status

*As of the 29-page benchmark (13 development, 16 held-out), re-run after the
unheaded-column, compound-quantity and orientation fixes. Both sets were
produced by the same code, uncontended. Update this section whenever the
numbers move.*

| Metric | Development | Held out |
| --- | ---: | ---: |
| Silent errors | 0 | 0 |
| Coverage loss | 0 | 0 |
| Routed correctly | 100% | 100% |
| Column mapping | 42.6% (270/634) | 44.4% (292/658) |
| Totals reconciled | 12/38 | 13/32 |
| Unhealthy pages | 1/13 | 1/16 |
| **Structural flags** | **88** (was 10) | **127** (was 386) |
| **Pixel cells needing review** | 60.8% | **63.6%** |

**What moved, in both directions.** Three defects were fixed (§10 item 2):
columns the header never *named* were flagged cell by cell as overflow;
quantities printed as pairs (`60:0`) counted as prose, so a row of them scored
as a header and split its table; and the issue/closing orientation was settled
by a tie-break rather than by the headings.

Held-out structural flags fell **386 → 127**. Development flags *rose* **10 →
88**, and the rise is the point: 80 of the 88 are one CSV page (`02_2060149`)
now flagged for an orientation it cannot justify. The mapping there is
genuinely wrong — `Purchase RTN` taken as opening, `Others` as closing,
`nonMoveQty` as issue, while the real `Opening`, `Sales` and `Closing` columns
sit unmapped beside them. It was mapped exactly as wrongly before and said
nothing. The flag is the system admitting it does not know.

**The silent error this round caught.** Fixing the table split on `02_2061231`
exposed a page returning `ISSUE → closing_qty` and `CLOSING → issue_qty` with
**zero flags**. `o + r - i = c` and `o + r - c = i` are the same statement, so
the search was settling orientation on how many rows showed movement — a count
that differs between the two readings by accident of which column holds zeros.
Headings now decide, and the movement count is recomputed against the reading
actually adopted: carrying the rejected one forward claimed 10 rows of support
for a reading that has 1, disabling the guard that stops arithmetic overruling
an explicit heading.

**What still does not hold.** 98 of the 127 held-out flags are one page,
`02_2060799`, whose headings are truncated **in the source file** — its raw PDF
text layer contains `enBalQty`, and a render confirms they are clipped on screen
too, so the missing letters are gone for good. But the headings never reach that
page's table either, and *that* part is a live bug (§10 item 2b). Zero silent
errors still partly reflects how
little is verified on unfamiliar documents: 100% of held-out pixel cells need
review, and `pdf_text` verifies nothing at all in either set.

**Review load:** 37,866 cells; 36,385 `exact`, 1,266 pixel-derived, **783
needing review**, confined to image pages. A further 215 deterministic cells
carry structural flags. Pixel-derived cells are **3.3%** of all cells — the
ceiling on everything PaddleOCR can affect.

The recogniser moved from PP-OCRv6_medium to **PP-OCRv5_server** on measured
evidence (§10 item 1). Verified cells 269 → **483**, review load 959 → **783**,
and the held-out set verifies something for the first time: 0 → **172**, with
its pixel review rate falling 100% → 63.6%. `unchecked` fell 902 → 618 while
`flagged` rose 272 → 380, which is the intended direction under §2 — cells
moved out of "no check was available" into a verdict. Silent errors stayed 0,
coverage loss 0, structural flags unchanged at 215.

Two caveats on that claim. It rests on **five image pages**, which is a small
sample. And `verified` means the row equation closed, not that a digit was
read correctly — there is still no ground truth (§8), so this is better
self-consistency, not measured accuracy.

**Performance:** PaddleOCR now runs on the **GPU**. This machine *does* have
the RTX 2000 Ada of §3 (driver 595.79, CC 8.9) — the previous note here claiming
no NVIDIA GPU was stale. `paddlepaddle-gpu` 3.3.1 (cu126) replaced the CPU
build; `paddle.device.is_compiled_with_cuda()` is now `True`.

The five image pages went **1243s → 17.6s (71×)**; the whole 29-page run went
**1280s → 38.2s (34×)**. Per page: 8.0s, 4.2s, 2.5s, 1.5s, 1.4s, against
551s, 328s, 168s, 158s and 37s on CPU. (These are the PP-OCRv5_server figures;
the lighter PP-OCRv6_medium ran the same pages in 14.6s total but verified far
less — see the review-load note above.) Image pages were 97% of runtime and
are now well under half, so **OCR is no longer the bottleneck** and the §6 note
that OCR is 84–100% of image-path cost no longer holds.

Accuracy was unchanged as §10 predicted, with **one** exception worth recording:
on `02_2061074` a single cell moved `verified` → `flagged`, so review load is
959 not 958. GPU and CPU convolution kernels round differently, and the 0.80
`min_confidence` threshold sits inside a dense cluster of recognition scores —
9 cells lie within 0.018 below it — so a borderline cell can land either side.
GPU output is deterministic run to run (byte-identical over two runs); it is
CPU vs GPU that differs. The move is in the safe direction (one more cell
reviewed, not one fewer) and silent errors stayed 0, but it is concrete
evidence for §10 item 7: that threshold is not scale- or platform-stable.

## 10. Backlog, in priority order

### P0 — the hardware move

1. **~~Install the CUDA build of PaddlePaddle.~~ Done.** `paddlepaddle-gpu`
   3.3.1 (cu126) is installed and verified on the RTX 2000 Ada. Image pages
   1243s → 14.6s (85×), full run 1280s → 33.9s (38×). §9 carries the figures.
   All 134 tests pass; every accuracy metric held except one borderline
   confidence cell (§9), which is a threshold-stability finding, not a
   regression. **OCR is no longer the dominant cost**, which re-prioritises the
   rest of this list: the remaining items are accuracy work, and experiments
   that were previously too slow to run — a heavier recognition model, a higher
   render scale, orientation classification — are now cheap enough to measure.

   **Those experiments have now been run**, as a sweep over the five image
   pages. `PP-OCRv5_server` won decisively and is now the default: verified
   269 → 483, review 959 → 783, at 9.8s against 8.6s. Document unwarping was
   the runner-up (422/788) but costs more and, combined with v5, made both
   *worse* (404/858) — the wins do not compound. Render scale 3.0 and 4.0 beat
   2.0 on the old recogniser but lose to it under v5, and 3.0 with v5 costs a
   page its health. Textline and document orientation classification changed
   nothing measurable on this corpus.

   One measurement bug found and worth repeating: `PDF_RENDER_SCALE` is a
   *default argument* of `read_pdf_page_ocr`, bound at import, so the first
   sweep's scale runs silently re-measured the baseline and reported three
   identical rows. Rebind `__defaults__`, not the module attribute.

   Two install notes, since the official index is unreachable from here:
   `www.paddlepaddle.org.cn` times out (DNS resolves to a Baidu WAF that drops
   the connection), so fetch wheels directly from
   `https://paddle-whl.bj.bcebos.com/stable/cu126/paddlepaddle-gpu/`. And the
   wheel's metadata pins `nvidia-cudnn-cu12==9.5.1.17` while the binary is
   compiled against cuDNN 9.9; 9.5 emits an incompatibility warning at every
   startup, so 9.9.0.52 is installed deliberately and pip will report a
   dependency conflict that is expected and correct.

### P1 — the generalisation gap

2. **~~Root-cause the held-out structural flags.~~ ~~Fix the three causes.~~
   Mostly done.** 2a and 2c are fixed; 2b is narrower than it looked but is
   still open. Held-out flags 575 → 386 → **127**. This settled the question
   the item was asked to settle: **item 4 is not the blocker.**

   - **2a. Unheaded columns. Fixed** — `02_2060596` flags 204 → 10. A column
     nearly every row fills is one the header failed to *name*; a column two
     rows out of a hundred reach is a ragged row. The check could not tell them
     apart and flagged 194 `exact` values over a single fact about the header.
     The distinction now lives in `Section.unheaded_columns`, and the check
     stays live for genuinely stray cells rather than going vacuous.
   - **2b. Structural half FIXED; naming half open, 98 flags.** The headings
     now reach the table: `_adjacent_header_tiers` treats two header rows on
     consecutive lines as one two-tier header when the upper row is the fuller
     of the two and the pair has a body. Previously `end` equalled
     `body_start`, so the existing two-tier branch was unreachable and the
     names were stranded. `02_2060799` goes 3 sections to 2, the 39 data rows
     get their headings, and columns mapped rise 5 to 6. Khushi is unaffected
     because its two header rows have no body at all, which is the
     discriminator; a banner over a full header (`STOCKIST NAME` above a
     16-column header on `02_2062237`) is excluded by the fuller-row test,
     without which columns mapped fell 261 to 180.

     The **98 flags remain**, and they are now squarely §11 job 1: arithmetic
     picks (3,4,1,8) while the headings say `enBalQty` is opening and
     `esBillQty` is sales. Both readings satisfy the equation; the truncated
     headings cannot outvote the arithmetic because the vocabulary cannot match
     them. Naming them is the VLM's job, exactly as this item predicted.
   - **2b-old. `02_2060799`: the glyphs are unrecoverable.** Rendering the page confirms the headings are
     clipped on screen exactly as in the text layer — `enBalQty` for
     OpenBalQty — so no reader and no VLM can recover the missing letters.
     *But* on that page the headings never reach the table at all: the reader
     emits one section holding every heading with zero data rows, and a second
     holding all 39 data rows with blank headings. Row 3 is the real header and
     row 4 is a second header line (`atestPurchRate`, `Qty`) that is not made
     of pure measure words, so the two-tier merge rejects it and starts a fresh
     section. Same family as the wrapped-header fix. Fixing it puts the
     mutilated-but-present headings onto the columns, after which naming them
     is a job for §11.
   - **2c. Compound quantities. Fixed** — `02_2061231` flags 40 → 0. `60:0` is
     units:free; the parser cannot reduce it to one number, so those cells
     counted as prose and a row of them scored as a *header*, splitting the
     table in two. They are now recognised as figures and deliberately never
     parsed — which half is the stock is the document's convention, not
     something to guess. Fixing this exposed a transposed issue/closing mapping
     reporting zero flags; see §9.

3. **Two pages find no tabular section, and one sheet maps the wrong
   quadruple.**

   - **3a. `02_2061290` fixed; `02_2060930` still open.** `02_2061290` now
     yields a table. The cause was not the band split at all: table-ness was
     being decided twice, and a section that passed the shape gate was demoted
     again by `_classify_section_kind` for having fewer than two *stock-flow*
     roles. That conflated "is a table" with "is a stock table", and §1 says
     the corpus holds sales and purchase registers too. The shape gate now
     decides alone. **This moved the column-mapping denominator** (1256 → 1292
     columns over more tabular sections), so rates before and after are not
     directly comparable.

     A band-split post-pass was built for the remaining page and **reverted**:
     loose enough to fix `02_2060799` (98 → 24 flags) it broke `02_2061231`
     (0 → 131), because a compound quantity's two halves are indistinguishable
     from two columns sharing a band on token geometry alone. That is §11 job
     3, confirmed rather than assumed.

     `02_2060930` still yields no table. The cause is now visible and it is *not*
     the threshold: geometry merges adjacent columns on these pages, so one
     cell reads `Purchase Goods Ret. Qty Qty` and another `109. 100.` — two
     headings, or two numbers, in one band. Rows then disagree on their column
     signature, band stability collapses and the score falls short. Fix the
     band split, not the threshold. This is the strongest candidate for the
     VLM (§11).
   - **3b. `02_2060149` maps a spurious stock quadruple** — 80 flags, the whole
     of the development-set rise. Arithmetic picks `Purchase RTN`, `Receipt`,
     `nonMoveQty` and `Others` while `Opening`, `Sales` and `Closing` sit
     unmapped beside them. The orientation check now catches it; the mapping
     itself is still wrong. A wide sheet with many numeric columns throws up
     coincidental fits, which is the same weakness item 6 describes.

5. **Continuation pages inherit their headings. Done.** A paginated report
   prints its column headings once; page 2 repeats the banner and goes straight
   into rows. The mapper saw no header, scored the *address block* as one, and
   left the roles to arithmetic — which cannot settle them, because
   `o + r - i = c` and `o + r - c = i` are the same statement. On `11.pdf` p2
   all four stock roles came out transposed at confidence 0.80 **with no extra
   flag**, reporting opening 1 / receipt 177 where the document says 177 / 1.

   `_inherit_headers_across_pages` in `pipeline.py` now carries a mapping onto
   sections no heading reached, from the nearest earlier page of the same file
   that was named. Matching is by **horizontal position, not column index**:
   `11.pdf` resolves 7 columns on page 1 and 8 on page 2 for the same table, so
   index-matching fails silently. Inherited roles are capped at 0.50, marked
   `inherited`, and never outrank a heading a page found itself.

   **`columns_mapped` did not move** — 4 before, 4 after. The count was never
   wrong, only the meaning, and no metric in the suite could see it. It took a
   multi-page file from an unfamiliar corpus to surface, which is the clearest
   argument yet that the current metrics cannot detect a wrong *role*.

6. **Headerless and stranded-header pages. Done.** Two more shapes of the
   §10 2b defect, both found on the `JUNE/` corpus:

   - *Stranded header with a label between the tiers.* `305313_.pdf` puts a
     lone `Manufacturer Mfac Name` row between its real header and the group
     name below it, so the two header rows are not literally adjacent. 686 of
     one batch's 731 flagged cells were this, on eight pages of one file.
     Adjacency now means no `DATA` row in between rather than no row at all.
     Structural flags 686 → **71**, overflow rows 69 → 3, equation rows 57 → 95.
   - *No header at all.* `all in one.pdf` p2 opens straight onto data and runs
     for 68 numeric tokens in a clean eight-column grid. `_split_sections`
     returned nothing without a header row, so the page produced zero cells and
     zero sections. The data was never lost — it fell to the raw layer as
     preamble, which is why coverage loss correctly read 0 — but no semantic
     layer was built. `_headerless_section` now emits one unheaded section and
     lets the shape gate decide, after which cross-page inheritance names what
     it can.

   A page reading `cells=0, seen=68, placed=68, loss=0` looks like a metric
   contradiction and was worth pulling on. It was not one: `iter_all_cells`
   counts preamble, the harness counted only section cells. Both were right and
   were measuring different things — which is the §12 failure mode exactly.

7. **JUNE corpus, batches 4–7. Done, with two changes reverted.** Full
   write-up in `reports/batch-04-06.md` (findings 9–14). Every change was
   re-measured across all seven batches and this corpus before it was kept.
   Across the batches: structural flags 611 → 377, verified 500 → 528,
   1,912 more cells structured, totals reconciled 28 → 31, file errors 2 → 0,
   silent errors 0 throughout.

   - `.jfif` and `.heic` phone photos are routed and decoded (Pillow,
     `pillow-heif`, EXIF rotation) instead of rejected.
   - Rows *above* the first header form a headerless section when at least
     `small_sample_rows` of them read as data (`GENEX.pdf` p6: 1 cell → 453).
   - `_spanning_parent`: a heading *centred* over `QTY. | VALUE` no longer hands
     its QTY child to the previous span. Bansal's left-aligned tiers still pass.
   - `_arithmetic_cannot_decide`: arithmetic no longer overrules a heading on
     opening vs receipt (addition commutes), issue vs closing, or a measure the
     heading states outright. **This removed some "verified" cells** — GENEX p1
     and `All Mehsana` p2 — that were verification of a wrong mapping.
   - Inheritance fixed three ways: it withdraws duplicate weaker roles, no longer
     writes into `header_text` (§4.4 — that is the raw layer), and carries a
     role only if a heading backs it directly or headings fix one term on each
     side of the equation. `orientation_ambiguous` now travels with the role;
     leaving it behind flagged 190 already-settled cells, which is the §5
     warning about filters going stale when an upstream value changes.
   - `_decompact` and a `cl` synonym: `Clqty`, `Clval`, `OpQty`, `Cl.Stock` match.

   **Reverted:** treating cross-flow ties in `_best_flow` as ambiguous (broke 19
   pages). **Open:** that tie itself — `Cl Stock Spoke` scores 0.72 for both
   opening and closing and goes to opening by table order; the duplicate
   tie-break ranking arithmetic participation above heading confidence, which
   lets an all-zero `WSale` beat `Sale` at 0.95 on `Auragabad` p3; and `Total
   In.Qty` read as receipt.

8. **Column-role labels and a regression gate. Built; labels not yet filled.**
   `labels.py make` writes `reports/labels/column_roles.xlsx`: 40 pages from 39
   files (20 text-layer PDFs, 7 scanned PDFs, 7 scanned photos, 6 WhatsApp
   photos), 414 columns pre-filled with the system's guesses. Labels are keyed
   on page position, not column index. Only pages marked reviewed are scored,
   and **wrong** roles (named, and named wrongly) are counted apart from
   **missed** ones (left unknown), because only the first misleads anyone. The
   scorer was checked with planted mistakes: 3 wrong and 2 missed planted, 3 and
   2 reported. That check caught a matcher bug - a narrow column inside a wider
   one's span tied on absolute overlap - so matching uses overlap relative to
   the combined span.

   `regression_check.py` was proven by reintroducing the `.jfif`/`.heic`
   rejection: rejected, exit 1, both pages named.

   **Measured costs of the next steps, on this machine (RTX 2000 Ada):**
   image preprocessing (deskew, CLAHE, blue-ink mask, perspective) costs a
   median 44 ms per phone photo, 321 ms worst case, against 0.7-2.9 s of OCR.
   Qwen2.5-VL-7B via Ollama: 5.5 GB VRAM; ~38 s for the first request after
   start-up, then 2.9-4.4 s per request on a new page (about 1.4 s reading the
   image and prompt, 1.5-2.7 s writing ~65-115 JSON tokens at ~42 tokens/s). An
   idle loaded model does not slow OCR (7.25 s vs 7.22 s over five images). The
   29-page benchmark would ask 90 questions if sent one per section, which is
   why calls must be batched per page and restricted to unresolved columns.

9. **Structured report output. Phase 1 done; phase 2 open.** `exporter.py`
   turns a pipeline result into the document's own table: row keys from the
   printed headings (`OB` -> `ob`, repeated `FR` -> `fr_1`/`fr_2`), a `columns`
   block giving each key its canonical role, and a `status` / `needs_review` /
   `review_reasons` on every row. Unfound report fields are `null`. A table
   continued across pages is one table (inherited roles, no heading, a majority
   of identical headings, or the same stock-column sequence), aligned by
   position. Rows with text under a figures heading (page footers, a screen's
   button bar) are flagged, never dropped; exported rows equal the pipeline's
   rows on every file checked. The viewer's JSON tab offers it as "Structured
   report" via `/api/structured/<doc>`, built from the page's saved OCR tokens
   (`process_file(ocr_tokens=...)`) in about 0.1 s rather than by running OCR
   again; text-layer PDF pages are still read from the text layer, which a test
   proves with deliberately wrong tokens.

   **Phase 2, not started:** `document_type`, `location` and `report_period`
   are still `null` on most reports (`FROM DATE ... T0 ...` is not parsed); a
   group label glues onto the heading or first row below it; `SNO` and item
   description share one heading; `Main.Report` window titles join the company
   name; `305313_.pdf` splits into 9 tables because its bands merge differently
   page to page.

10. **Phase 2 of the structured report. Partly done.** Gate passes against
    the 09:58 baseline (now at `reports/labels/_baseline.json`; use
    `--baseline`). Verified cells 1,011 → 1,509, rows where the equation holds
    430 → 490, printed totals reconciled 56 → 70, review load 8,399 → 8,027,
    structural flags 592 → 543, silent errors 0. Checked against the user's own
    transcription of `1000517655.jpg`: 113 cells verified, **0 verified wrong**.

    - **Free goods on both sides.** `_match_residual_pair`: two columns may
      balance the row (`OB + PUR + FR - SAL - FR = CB`), but only when headings
      name all four stock columns, on a majority of rows and at least 4 rows
      where free goods moved. `Section.adjustment` became `adjustments` (list);
      the validator verifies or flags the free-quantity cells with the row.
    - **Heading-anchored equation.** `anchored_invariant_support = 0.50`: when
      headings name all four columns the equation is adopted on a majority of
      rows with movement, and the rest are **flagged** instead of the whole
      table staying unchecked. The 70% bar is unchanged otherwise. Pinned by two
      tests at 10/17 that fail if either threshold moves.
    - **Photographed pages: rows levelled, columns not.** `straighten_page`
      fits text-line slope as a function of height (a keystone slopes in
      opposite directions top and bottom) and clusters rows on levelled copies;
      every cell gets its original coordinates back. Column-lean correction
      exists but is **off**: on six photos the lean model never explained the
      measurements (leftover scatter 0.9-2.6x raw; robust fit worse than
      assuming zero), and it broke two healthy pages. Row fits removed 64-80% of
      scatter on every page.
    - **Zero rows are not rate evidence.** `CB x PUR = FR` "held" on rows of
      zeros, overruled the `PUR` heading and evicted `RATE`. Rows with a zero
      factor no longer count.
    - **Group labels and separated headings.** A header-like row over text
      columns only is a group title, not a second header line; a heading alone
      in a band beside an unheaded band of figures moves over to them.
    - **Report details.** Lines of pre-table sections are searched; the period
      needs a range word or dash between its dates (a print footer's run date
      had become a two-year period); `report_title` feeds `document_type`;
      location is the line after the company name with GST/phone/DL stripped;
      dates kept as printed.

    **Open, measured:** the window caption `Main Report` becomes the company
    name on screen photos (text height does not separate it: perspective makes
    the address line tallest). With the pipeline's own OCR, that photo still
    verifies nothing — `RATE`/`VALUE` share a band and `OB` sits a band from its
    figures — because column lean is uncorrected; the saved PP-OCRv6 tokens
    happen not to trigger it. `Adobe Scan` p5 lost two correct roles to the
    zero-row fix (flagged, +28 structural flags). `1000411296.jpg` now pairs its
    rows correctly but merges `Unit` into `Opening`; before, its rows balanced
    with each item's name attached to the previous item's sub-total line.

11. **Recogniser re-chosen on the whole corpus: back to PP-OCRv6_medium.**
    The v5 choice in item 1 rested on five pages. Every image-routed page of
    JUNE plus the benchmark's image pages (238) was OCR'd once per det/rec pair
    and scored on the same saved tokens (`process_file(ocr_tokens=...)`), plus a
    cell-by-cell check against the user's transcription of `1000517655.jpg`.
    Final figures, with the tie-break fix below applied to both:

    | 238 pages | v5 server | **v6 medium** |
    | --- | ---: | ---: |
    | silent errors | 0 | 0 |
    | verified | 5,567 | **5,661** |
    | flagged | 3,249 | **1,530** |
    | equation rows closing | 1,015 | **1,197** |
    | totals reconciled | 118/206 | **121/209** |
    | unhealthy pages | **23** | 25 |
    | OCR time | 282 s | **225 s** |
    | `1000517655.jpg`: verified and right / verified and wrong | 101 / 0 | **108 / 0** |

    Mixed pairs (v5 det + v6 rec, v6 det + v5 rec) lost to both. v5 recognises
    every reference figure on that photo, v6 93.5%; v6 still wins because v5
    loses 8 of its 21 rows to layout.

    - **Column-band ties.** `detect_column_bands` kept the first split among
      equally many bands. On a PDF-viewer screenshot (`all in one.pdf` p4) the
      app toolbar crosses the table's gutters and its split was found first, so
      the table became one column. Ties now go to the split that forms more
      (row, band) cells. It helped both models (v5 unhealthy 25 → 23, v6 27 →
      25; v5 on the reference photo 0 → 101 verified-right).
    - **Word-level splitting tried and removed.** A first diagnosis blamed v6
      boxing whole lines; the tokens were in fact separate and the fault was
      the tie above. Splitting lines at word gaps (`return_word_box`) was still
      measured: at 0.55 line heights +27 verified but +3 unhealthy pages, at
      1.0 fewer verified. Not kept.
    - **Gate: REJECTED on 4 pages, not accepted.** Unhealthy 13 → 15 on the
      gate's 163 pages (4 new, 2 fixed); every soft metric better: verified
      1,011 → 1,772, equation rows 430 → 575, totals 56 → 79, review 8,399 →
      7,391, structural flags 592 → 578, silent errors 0. Newly unhealthy, all
      "no tabular section": `all in one.pdf` p6, `All Mehsana Statement (1).pdf`
      p7, `GANESH AGENCY ... .PDF` p2, and `Auragabad statement.pdf` p1, where v6
      does not detect the `-` placeholders in empty cells (163 tokens → 73), so
      the sparse table loses the ink that held its columns apart. The baseline
      is left for the user to accept.

12. **Structured report: row status, split headings, screen text. Done.**
    Found by reading the live `/api/structured` output after the v6 switch.

    - **Row status is the status of the row's figures.** Descriptive fields
      (textual roles, and serial-number columns detected as 1, 2, 3...) can
      never be verified by arithmetic, and a row took its worst field's status,
      so all 23 KETAKI rows read `unchecked` while the pipeline had verified
      123 figures. They now go to `unchecked_text` (sampled review, s5); a
      *flagged* descriptive field still counts. KETAKI: 0 → 14 rows verified,
      7 flagged, 0 verified rows wrong against the user's transcription.
    - **A heading read across two columns is shared.** `SNO ITEM DESCRIPTION`
      as one OCR piece over the serial and item columns now gives `sno` and
      `item_description`. The first version was too loose and was measured
      doing harm: it split a title line on `DOC-20260703-WA0021.pdf` p14 (a
      reconciled total lost) and cut `PACKING OPENING STOCK RECEIPT`, which
      spans three columns, in two on p13. Now it needs a header row naming most
      columns with data, a single OCR piece, and a heading that reaches no third
      column's data. Each rule has a test that fails without it.
    - **Screen text.** A row with words and no figures under the figure
      headings (a photographed button bar) goes to the table's `other_lines`,
      flagged, never dropped. The company is the line that scores as a trading
      name (a trade word such as `PHARMACEUTICALS`/`MEDICAL`/`AGENCIES`, or a
      run of capitals) instead of the first line: `Main.Report` → `KETAKI
      PHARMACEUTICALS`, `E-Sign Sign in` → `SHRI RAM MEDICAL HALL` (trailing
      `Share Ask` buttons trimmed), and the location is read under that name.
      Nothing name-like gives `null`.

    Gate totals identical to the run before these changes (verified 1,772,
    totals 79, silent errors 0); the same 4 hard failures from item 11 remain.
    `IMG-20260708-WA0018.jpg`'s table is still mis-split (`receipt_issue_closing`
    holding `-2121 0 -482`): a column-band problem, not addressed here.

13. **The whole JUNE folder, and the error list from `AAI PHARMA JUNE26.pdf`. Done.**
    Batches covered only 70 of 235 files; `batch_test.py` now adds remainder
    batches (8-23) so every file is measured, and `merged_cells` (cells
    holding several separate figures) is a gate metric. Before-run recorded as
    `reports/labels/_baseline_full_before.json`; after, accepted as
    `_baseline_full.json`. 476 pages, before -> after: failed 12 -> **1**
    (an incomplete `.crdownload`), unhealthy 38 -> **22**, silent errors 0 -> 0,
    equation rows 2,331 -> **3,545**, totals reconciled 343 -> **528**, columns
    mapped 3,086 -> **3,423**, merged cells 1,485 -> **828**, verified 3,261 ->
    **3,474**, structural flags 2,369 -> 2,805, review 18,323 -> 18,443.

    - **Sparse columns** (`recover_unbanded_columns`): figures in no band, on
      rows whose figures are mostly in bands, get bands of their own if two
      rows reach them and they sit a gutter clear. A first, looser version
      built columns from address words, heading words and `Batch :` sub-lines
      and was measured doing harm on 5 pages before being tightened.
    - **Merged figures flagged** (`_check_merged_figures`): a structural flag,
      so `814 1` from a text layer is no longer `exact` with nothing to review.
      This is most of the structural-flag rise, with newly readable files.
    - **Watermarks** set aside (words > 5x median height, never figures).
    - **A heading line is never split** as two merged products (both halves
      must hold figures); the split had produced `STK VAL MAY` headings.
    - **Headings**: `stk` = stock (`OPSTK`, `STK VAL`); `o stock`, `c stock`,
      `qoh`; `expiry` excludes a flow; a generic word (`stock`) no longer
      makes an abbreviation match (`EXPIRY STOCK` had become opening); one
      misread letter in a word of 5+ letters matches at 0.62 (`ISSLE`,
      `CLISING` - arithmetic had swapped issue and closing).
    - **Opening/receipt swaps keep the heading's flow** when only a guessed
      measure disagreed (`Opening` printed `51.00` beside `0.000`).
    - **Total lines** whose short label *ends* in total (`Division Total`,
      `S-Total`).
    - **File formats**: readers pick by content (`.xls`/`.csv` that are xlsx),
      CSV falls back to cp1252, `.TXT`/`.prn` printouts read as fixed-width text
      (`readers/text_reader.py`, `PageKind.TEXT`, deterministic), and a printout
      pasted into column A of a sheet is read the same way.
    - **Page health, redefined in two places - say so when comparing:** an
      empty spreadsheet sheet is blank, not unhealthy (7 pages); a page of <= 3
      lines holding only a total is a closing page (5 pages). Photos that read
      nothing are still unhealthy.
    - **Tried, kept, near-zero effect:** `split_merged_bands` (splits a
      figures-only band into sub-columns); 2 merged cells on `305313_.pdf`.
    - **Removed as unmeasured:** an empty-column guard in the equation search.

    **Losses judged, not fixed:** `305313_.pdf` p1/p4 and `IMG20260714184904
    .heic` lost "balancing" rows that rested on nonsense mappings; `June month
    ... .pdf` p2 is a photographed sheet whose table score sits at exactly
    0.50 once its sparse columns are found. **Open:** 22 unhealthy pages, mostly
    photos scored just under the table threshold (few figures; v6 does not read
    `-` nil marks); `305313_.pdf` headings and a banner run together, so it
    still splits into several tables; `HETRO.XLS`-style printouts in
    proportional fonts misalign their headings (flagged, orientation
    unresolved).

14. **MAY corpus, batches 1-4 (80 of 1,036 files). Done; JUNE not re-run.**
    `batch_test.py --corpus MAY --size 20` mixes batches in the corpus's own
    proportions (seeded shuffle) and writes to `reports/MAY/`, apart from
    JUNE's results, so the gate never mixes them. Report:
    `reports/MAY/batch-01-04.md`; first-run results kept in
    `reports/MAY/_results/before/`. 169 pages, first run -> after: silent
    errors 2 -> 0 (a probe bug), unreadable files 3 -> 0, unhealthy 7 -> 2,
    equation rows 2,501 -> 2,692, totals 151 -> 209, verified 4,880 -> 5,622,
    structural flags 1,140 -> 816. Checked on JUNE only by tests (237) and the
    29-page benchmark (gate passed, `02_2060930` healthy for the first time).
    **A full JUNE re-run is owed before the next baseline is accepted.**

    - Probe: a running total is judged against earlier pages' column sums
      (`_probe_silent_errors(carried=...)`).
    - Validator: text in a balancing row's figure column is `not_a_figure`,
      flagged, never verified (OCR's `a` for `0`).
    - Router: `max_garbled_ratio` 0.02 sends a garbled text layer to OCR
      (1,189 of 1,212 text pages have 0%; the garbled ones 2.5-7.4%). Unknown
      extensions are classified by content: PDF, image, docx/html
      (`readers/document_reader.py`), xls/xlsx, or text; printer control codes
      stripped (`.dat`).
    - Health: blank scanned pages (no dark pixels) and closing pages whose only
      figure lines are totals are not failures.
    - Shape gate measured on rows with figures when a statement lists products
      with no movement; a two-cell row inside a table is not a new header.
    - Headings: glued `st` after `op`/`cl`/`o`/`c`; `free`/`bonus`/`scheme`
      exclude the main flows.

    **Open:** leaning columns on photos (most of the 230 merged-figure cells;
    flagged, not silent) - needs image straightening before OCR.

15. **The whole MAY corpus, then two fixes: printed totals as an anchor, and
    leaning columns. Done.** 1,036 files, 1,957 pages measured end to end before
    anything changed, then again after. Report: `reports/MAY/full-corpus.md`;
    the before run is kept at `reports/MAY/_results_pass3_before/`. Before ->
    after: verified 39,531 -> **53,958**, review 130,419 -> **116,729**, merged
    cells 3,692 -> **3,305**, flagged 24,328 -> 23,960, equation rows 31,331 ->
    31,370, totals 1,984 -> 1,996, unhealthy 71 -> **68** (3 recovered, none
    lost), structural flags unchanged, silent errors **0**, coverage loss **0**.
    JUNE and the benchmark were re-run in full on the same code, the gate
    passed and the baseline was accepted (`_baseline_full.json`; the previous
    one is `_baseline_full_prev.json`): verified 3,474 -> 5,286, review 18,443
    -> 16,823, merged 828 -> 766, equation 3,545 -> 3,563, 9 pages no longer
    unhealthy, 1 no longer failing.

    - **A printed total confirms its whole column** (`_verify_column`). The
      match used to confirm only the total line; the figures that produced it
      stayed `unchecked`. It now reaches **columns no heading named**, which is
      the state OCR leaves a photographed page's headings in (`ESKAY MAY.pdf`
      reads closing stock as `Closing Sh.Exp Liqudation fr`), and is then the
      only check a page has. Guards: `column_sum_min_rows = 3`, a non-zero sum,
      an exact match to 0.05; cumulative totals confirm the same way. Measured
      alone on 290 pages: verified 7,877 -> 10,845, review down by the same
      2,968, **every other metric unchanged**. It is proof up to *compensating*
      errors, the same assumption the row equation rests on - hence `verified`,
      never `exact`.
    - **Leaning columns stood upright** (`_fit_column_shear`), by searching for
      the shear that packs the figures tightest rather than fitting word-to-word
      displacements (the model measured and shelved in item 10). Two versions
      were measured and thrown away first: scoring **every word's box** reported
      105 px of lean on a flatbed scan and 268 px on a photo two other measures
      put at zero - words differ in length and indentation, so sliding them
      makes them overlap for reasons unrelated to columns - and cost 835
      verified cells and 216 merged cells on 290 pages. Scoring the **right
      edges of figures** (uniform, right-aligned) gives 20-50 px corrections:
      merged 506 -> 390, flagged -105, verified +78 on the same pages.
    - **A shear can destroy a gutter after all, and did.** The code asserted it
      could not, since a shear moves every word on a line equally. True within a
      row; false for the page-wide projection the band detector uses, because
      tokens at different heights move by different amounts. A 14 px correction
      cost `IMG-20260603-WA0025.jpg` and `IMG-20260606-WA0007.jpg` their tables.
      A straightened page must now resolve into at least as many (row, band)
      cells as the photographed one (`_grid_cells`) or it is not adopted; both
      are healthy again and the guard has a mutation-checked test.

    **Open:** 1,351 pages verify nothing, 192 of them photos and scans - most of
    the rest are `exact` already and need no verification. 68 unhealthy pages
    (58 find no table, 17 resolve too few bands). The 3,305 merged cells that
    remain are **keystone**, not shear: a photo leans by different amounts left
    and right, which one global shear cannot correct. Naming columns the
    vocabulary cannot match is still s11's job for a VLM.

16. **Four defects found by chasing where the errors concentrate. Done.**
    Triage counted problems by kind rather than by page, which put the biggest
    blocks first. Gate passed and the baseline was accepted. JUNE + benchmark
    across items 15-16: verified 3,474 -> **6,358**, equation rows 3,545 ->
    **3,725**, columns mapped 3,423 -> **3,479**, structural flags 2,805 ->
    **2,711**, totals 528 -> **538**, merged 828 -> **748**, 6 pages recovered.
    MAY, 1,957 pages: unhealthy 71 -> **55**, verified 39,531 -> **55,821**,
    equation 31,331 -> **31,721**, columns 16,380 -> **16,647**, structural
    10,771 -> **10,440**, merged 3,692 -> **3,271**, silent errors **0**,
    coverage loss **0**.

    - **A scan someone else OCR'd was passing as a deterministic source.**
      25 pages of the two corpora carry an *invisible* text layer (PDF render
      mode 3): scanning software writes the characters behind the image so the
      file can be searched, and they are that software's reading of the pixels.
      The router saw text with coordinates and called the page native, so
      **4,797 cells were `exact`** - "not subject to reading error" (s5) - with
      no confidence, no check and no review. They are now read as scans.
      `max_invisible_ratio = 0.9`; the signal is binary, 382 of the first 400
      MAY text pages wholly visible and 18 wholly invisible, nothing between.
      Two of the 25 had lost their table outright: a full-page image with a
      100-character stamp for a text layer.
    - **`34.` was not a figure.** Several billing packages print whole
      quantities with a trailing point and no decimals. Read as prose the cell
      carried no value at all, so no row equation and no column sum could run,
      and a page of them scored 23% numeric and was thrown out (`PAVAN MAY
      MEHSANA.pdf` p1: score 0.495 -> 0.673, 40 rows; `A+N Apr'26 Statement.pdf`
      p8: 0.482 -> 0.599, 39 rows). The text layer prints `34.` itself - nothing
      was lost in reading, so parsing it as 34 is exact, not a guess. A lone `.`
      is still nil and `500MG.` is still text.
    - **Empty spreadsheet columns counted against the sheet.** A merged heading
      declares a column for every cell it spans, so `MUKTJIVAN MAY KALOL.xls`
      offers 52 for the 22 it uses and its 80 rows were discarded as prose for
      "filling 11% of the 52 columns". Occupancy is now measured against the
      columns the data reaches. Bands found from ink cannot be empty, so scans
      and photos are unaffected.
    - **Review load rose, and that is the fix working.** 116,729 -> 121,162 on
      MAY, almost all of it the de-`exact`ed scan pages (JUNE: `Adobe Scan Jul
      05` p3-p5 alone +858). Those cells were trusted without review; they are
      now counted honestly. The corroboration that this is a gain: our own
      reading of the same pages closes 351 more row equations and reconciles 12
      more printed totals than the borrowed text did.

    **Attribution error, recorded because it was reported before it was
    caught:** the trailing-point fix landed mid-run and the MAY batch process
    picked it up, so a set of numbers first reported as two fixes was three. The
    re-run came back byte-identical, which is how it surfaced - and is also
    evidence the pipeline is deterministic over 1,957 pages. **Save each run's
    results directory before starting the next**; `reports/MAY/_results_*` now
    does.

    **Open:** `PHARAMADEAL.pdf` p2 (0.491) and `DOC-20260603-WA0035 ambika.pdf`
    p1 (0.47) still lose their tables, cause not yet found. `KOLKATA MAY
    2026.pdf` holds 606 of the merged cells and is a low-resolution scan of a
    sheet whose *source* is unreadable - it prints `#####` where the columns
    were too narrow - so those cells are correctly flagged, not fixable.

### P2 — the known structural limits

4. **Invariant discovery.** The row equation is a fixed shape
   (`opening + receipt − issue = closing`). Reports with sales returns, free
   quantity, breakage or transfers do not fit — Khushi already has two such
   columns. Replace it with a search for a signed combination
   (`c1*col1 + ... + cn*coln = 0`, each coefficient in {+1, -1, 0}) that holds
   across moving rows. Prune with the column profiling already in place.
6. **Image preprocessing.** Rotation, deskew, perspective, contrast, and
   blue-ink removal via an HSV mask. Krishna against the real file is the
   specification; how it fails is the requirements list.
7. **Scale-invariant thresholds.** Gutter width, row tolerance, the 70% support
   threshold, the 4-row minimum and the 10× magnitude guard were all fitted on
   four documents. Express geometry relative to median token height rather than
   absolute pixels, and scale statistical thresholds with sample size.

### P3 — product

8. Review UI: document beside extracted grid, flagged cells highlighted,
   click-to-locate on the image, keyboard correction, every correction logged.
9. Storage, ingestion and API.

### P4

10. Fine-tuning, once corrections from real use exist.

## 11. Deliberately not built

- **The VLM path.** The census is **725** across the 29 benchmark pages (360
  development, 365 held-out), down from 3,833 once non-tabular sections were
  excluded. Most of the remainder are batch numbers, expiry dates and free-text
  notes for which no canonical role exists — a VLM would have nothing useful to
  return. Keep the resolver interface and its failure-safety tests.

  Item 2 was concrete reader and mapping bugs rather than a vocabulary gap, so
  the general case is *weaker* than it looked. Three specific jobs survive, and
  all three are meaning rather than digits, so §4.1 permits them:

  1. **Name columns the vocabulary cannot match** — item 3b, where `Opening`,
     `Sales` and `Closing` sit unmapped; and `02_2060799` once item 2b lands,
     where inferring `opening_qty` from `enBalQty` is exactly the inference a
     human reviewer makes at a glance.
  2. **Orient issue against closing** where no heading settles it. This is the
     one failure arithmetic is *structurally* incapable of catching, since
     `o + r - i = c` and `o + r - c = i` are the same statement.
  3. **Recover column boundaries** on the item-3a pages, where the text is
     present and correct and only the segmentation failed. The reader then
     re-splits tokens it already holds.

  It cannot recover `02_2060799`'s missing letters — the render confirms they
  are not on the page. Jobs 1 and 2 work against `VLMColumnResolver` as it
  stands; job 3 needs `VLMColumnRequest` to carry a crop of the header strip
  and a response of x-positions rather than roles.

  What it will *not* touch: the 958-cell review load, which is image
  transcription and is what the business actually pays for.
- **Review UI** — after the numbers stabilise.
- **Fine-tuning** — needs real corrections first.

## 12. Self-review discipline

There is no external reviewer. Apply these to your own output before reporting.

**Ask of every green metric: what would this look like if the system were
quietly broken?** Zero silent errors alongside a 5% verified rate means the
claim being made is small, not that the system is right.

**Check the denominator and the size of the claim.** A metric that filters on a
status, a source or a section type can go vacuous when any of those change.
Re-audit filters whenever an upstream definition moves.

**Distinguish fixing the system from redefining the measure.** Both are
legitimate; conflating them is not. When a number improves by more than an
order of magnitude, state which happened. Report old and new figures side by
side when a definition changes, because the old one is in circulation.

**Held-out results that match development are suspicious.** Either the system
generalises, or the held-out set is not really unseen. Check which.

**Prose goes stale faster than tables.** Narrative sections carried forward from
a previous run have twice reported figures contradicting the tables above them.
Regenerate commentary from the current numbers, or delete it.

**Report what you measured, not what you estimated.** If a figure needs ground
truth that does not exist, say so and report nothing. Never invent a number.

**A metric bug is worth reporting as loudly as a pipeline bug.** An unaudited
metric is worse than no metric. Five were found in one run.

## 13. Working conventions

- **Propose before implementing** anything structural. Say what you intend and
  why, then build.
- **Never weaken a test to make it pass.** If an assertion is wrong, say so and
  explain. All existing tests keep passing across changes.
- **Report defects you fix**, especially ones that would have produced silent
  errors.
- **Say when something is blocked** rather than working around it — a missing
  file, an unreachable document, a §4 principle the task appears to require
  breaking.
- **Do not tune a threshold to make a number look better** without first
  establishing what the number is measuring and why it moved.
- `--reuse` must keep working so metric changes never require a full re-run.
- **Every change goes through `python regression_check.py` before it is
  reported.** It rejects silent errors, coverage loss, newly failing or
  unhealthy pages, and - once pages are labelled - any rise in wrong column
  roles. Soft metrics (verified, structural flags, review load) are listed for
  judgement, not enforced: they move in the "better" direction when pages fail
  outright, which a deliberate regression test showed. Accept a new baseline
  with `--accept` only after reading the soft movements.

## 14. Commands

```bash
python -m pytest tests/ -q                     # full suite
python benchmark.py --set both --markdown      # full run, both sets
python benchmark.py --reuse                    # re-render from cache
python profile_image_path.py                   # stage timing breakdown
python tests/fixtures/_build_fixtures.py       # regenerate fixtures
python column_mapper.py tests/fixtures/bansal_p1.json
python validator.py     tests/fixtures/krishna.json   # exits non-zero if flagged
python batch_test.py --plan | --batch 1 2 3 | --report 1 2 3   # JUNE batches
python labels.py make | score                   # column-role labels (reports/labels/)
python regression_check.py [--reuse] [--accept] # the gate; see §13
python exporter.py report.pdf [-o out.json]     # structured report (one object per row)
```
