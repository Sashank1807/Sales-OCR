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
