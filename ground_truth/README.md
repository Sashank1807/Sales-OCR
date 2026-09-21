# Ground truth: what to put here

This is the first real ground truth the project will have. Everything measured
so far is the documents checking themselves; this is the only thing that can say
whether a digit was read correctly.

## Layout

```
ground_truth/
  images/            the 30 source files, exactly as they came
  transcriptions/    one .xlsx per source file, named to match
```

`images/KETAKI MAY.jpg` pairs with `transcriptions/KETAKI MAY.xlsx`. Same base
name, any extension on the image. One workbook per source file; if a report runs
to several pages, one **sheet per page**, named `p1`, `p2`, ...

## What to type in each sheet

Row 1: the column headings **as the document prints them** - `OB`, `PUR`, `FR`,
`SALE`, `CB`, whatever it says. Don't translate them into what they mean; that
is the system's job to work out, and comparing against your headings is how its
column naming gets scored.

Then one row per product line, in the order they appear, including:

- the item description and pack exactly as printed
- every figure column, **verbatim as printed**
- the printed TOTAL row, if the page has one

## The one rule that matters

**Type what the document shows, not what it should show.**

- If it prints `34.` with a trailing dot, type `34.`
- If a cell is blank, leave it blank. If it prints `-`, type `-`
- If it prints `#####` because the column was too narrow, type `#####`
- If the document's own arithmetic is wrong, leave it wrong

The value of this set is that it is what is on the page. Corrections destroy it.

## How much is enough

A full page is ideal. If a page has 80 rows, **the first 20 rows is plenty** -
accuracy per cell does not need every row, and 30 files at 20 rows is 600 rows
and several thousand cells, far more than exists today. Say in the sheet if you
stopped early (a row reading `... stopped here` is fine).

## Which 30 files

A spread beats 30 easy ones. Roughly:

- 8-10 phone photos, including ones taken at an angle
- 5 screenshots of a billing screen
- 8-10 scanned PDFs
- 5 Excel or clean text-layer PDFs

Include a few you consider hard. Files that are already easy tell us least.

## Please do not correct the system's output

It is tempting to export what the system produced and fix it up - much less
typing. But a wrong value that looks plausible would survive that process, and
those are exactly the errors worth finding. Typed independently, the sheet is
evidence. Corrected from output, it is only a structure check.

If independent typing is too slow, say so and do the corrected version for some
of them - it still scores column naming and structure honestly, and I will
report those files separately rather than mixing the two.

## What happens next

15 files are used to find and fix problems. **15 are sealed and only scored
once, at the end.** The gap between the two is the only honest measure of
whether a fix generalises (CLAUDE.md §8), so please do not tell me which are
which - I will split them by name and record the split before looking.

Then you get, per file and by source type:

- per-cell accuracy, and how many wrong values were passed as `exact` or
  `verified` - the true silent error rate, which today is unmeasured
- column roles correct, wrong, and missed
- how much of the review load was necessary
