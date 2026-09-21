# MAY, the whole corpus: one measuring pass, then two fixes

1,036 files, 1,957 pages, measured end to end before anything was changed, then
measured again after the two fixes that pass identified. No threshold was
tuned to make a number move, and the before column is a real run, not a
reconstruction.

## The corpus

| Reader | Pages | Unhealthy | Equation rows closing | Printed totals | Merged cells |
| --- | ---: | ---: | ---: | ---: | ---: |
| `pdf_text` | 990 | 37 | 12,294/13,451 | 591/1,551 | 1,161 |
| `image` | 688 | 29 | 8,691/9,276 | 660/1,607 | 2,018 |
| `excel` | 258 | 2 | 9,517/10,402 | 745/1,181 | 123 |
| `text` | 20 | 0 | 868/899 | 0/9 | 3 |

Three files are unreadable and stay that way: `Downloads.rar` (an archive, not
a report - rejected by design), `May SSS Vardhaman Washim.XLS` (a CSV of NUL
bytes) and `RAMESH PHARMA MAY KALOL.xls` (a truncated OLE2 container).

## Before and after

| Metric | Before | After | |
| --- | ---: | ---: | --- |
| Silent errors | 0 | **0** | the one that must not move |
| Coverage loss | 0 | **0** | |
| Verified cells | 39,531 | **53,958** | +14,427 |
| Review load | 130,419 | **116,729** | -13,690 |
| Flagged | 24,328 | 23,960 | -368 |
| Merged cells | 3,692 | **3,305** | -387 |
| Equation rows closing | 31,331 | 31,370 | +39 |
| Printed totals reconciled | 1,984 | 1,996 | +12 |
| Columns mapped | 16,380 | 16,409 | +29 |
| Unhealthy pages | 71 | **68** | 3 recovered, none lost |
| Structural flags | 10,771 | 10,771 | unchanged |

JUNE and the 29-page benchmark were re-run in full on the same code and the
gate passed: verified 3,474 → 5,286, review 18,443 → 16,823, merged cells
828 → 766, equation rows 3,545 → 3,563, nine pages no longer unhealthy, one no
longer failing, silent errors 0 throughout.

## Fix 1: a printed total confirms the whole column

A column whose figures add up to the total printed beneath it was read
correctly - a misread digit anywhere in it would have thrown the sum off. Until
now that match confirmed only the total line itself; the forty figures that
produced it stayed `unchecked`.

It now confirms every figure in the column, and it does so **for columns no
heading named**. That is the point. On a photographed page the header line is
what OCR destroys first - `ESKAY MAY.pdf` reads its closing-stock heading as
`Closing Sh.Exp Liqudation fr` - and once the four stock columns cannot be
identified, no row equation can run and the whole page sits unchecked awaiting
a human. The document's own footing does not need to know what the column
counts.

Guards: at least three rows must contribute (a total that equals one figure
above it is a coincidence), the sum must be non-zero, and the match must be
exact to 0.05. A cumulative total - carried forward from earlier pages, or
totalling every page so far - confirms the column the same way.

**What this claim is worth.** It is proof up to *compensating* errors: two
misreads that cancel would still add up. That is the same assumption the row
equation already rests on, and it is why these cells are `verified` (confirmed
by the document's own arithmetic) and not `exact` (from a deterministic
source). Nothing was promoted to `exact`.

Measured alone on 290 pages: verified 7,877 → 10,845, review down by the same
2,968, and every other metric - flags, equations, mapping, merged cells -
unchanged. Every page that moved is a photo or a scan.

## Fix 2: standing leaning columns upright

Photographed at an angle, a column drifts sideways as it runs down the page, so
two columns project into one band and their figures land in one cell. That was
the largest known cause of merged cells.

The correction is a shear searched for, not fitted: try each lean the page
could have and keep the one that packs the figures tightest. Three versions
were measured and two were thrown away.

1. **Scoring on every word: rejected.** Words differ in length and indentation,
   so sliding them makes them overlap for reasons that have nothing to do with
   columns. It reported 105 px of lean on a flatbed scan and 268 px on a photo
   that two other measures put at zero. On 290 pages: verified -835, merged
   cells +216, one page newly unhealthy. Not kept.
2. **Scoring on the right edges of figures: kept.** Figures are printed
   right-aligned and are uniform in size, so a column of them stacks its right
   edges on one x and a leaning column smears them across many. Corrections
   come out at 20-50 px rather than 100-270, and the measure abstains on pages
   where scoring words did damage. On 290 pages: merged cells 506 → 390,
   flagged -105, verified +78, totals +5, one page recovered.
3. **A guard, after it broke two pages.** The code claimed a shear could not
   destroy a gutter, because it moves every word on a line by the same amount.
   That is true *within a row* and false for the page-wide projection the band
   detector actually works from: tokens at different heights move by different
   amounts. A 14 px correction closed the only gutter the tables on
   `IMG-20260603-WA0025.jpg` and `IMG-20260606-WA0007.jpg` had, and both lost
   their table. The straightened page must now resolve into at least as many
   (row, band) cells as the page as photographed, or it is not adopted. Both
   pages are healthy again, and the guard has a test that fails when it is
   removed.

## What is still open

- **1,351 pages verify nothing** (192 of them photos and scans, down from 199).
  Most are `pdf_text` and `excel` pages where every cell is already `exact` and
  verification would add nothing. The photographed ones are the real backlog:
  no printed total to foot against, or headings too damaged to name the stock
  columns.
- **68 unhealthy pages**: 58 find no tabular section, 17 read tokens but
  resolve too few column bands. Mostly photos scoring just under the table
  threshold.
- **3,305 merged cells** remain after the shear fix. The residual is keystone
  rather than shear - a photographed page leans by different amounts on its
  left and right - which one global shear cannot correct.
- **Naming columns the vocabulary cannot match** is untouched and is still the
  job CLAUDE.md §11 reserves for a vision model: it supplies names, never
  digits.
