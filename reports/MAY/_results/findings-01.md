### What these four batches found, and what was done about it

Batches 1-4 of `MAY/` (80 of 1,036 files, 169 pages) were run once on the code
as it stood after the JUNE work, the problems below were fixed, and the same
80 files were run again. Nothing was tuned on these files by name: every fix is
a general rule with a test that fails without it. JUNE was **not** re-run in
full, as requested; the fixes were checked with the test suite (237 passing)
and the 29-page benchmark, which passed the regression gate against the JUNE
baseline and turned one long-standing failed page (`02_2060930`) healthy.

| 169 pages | First run | After fixes |
| --- | ---: | ---: |
| Silent errors | 2 | **0** |
| Files that could not be opened | 3 | **0** |
| Unhealthy pages | 7 | **2** |
| Rows where the stock equation closes | 2,501 / 2,686 | **2,692 / 2,882** |
| Printed totals reconciled | 151 / 412 | **209 / 465** |
| Verified cells | 4,880 | **5,622** |
| Flagged cells | 2,422 | 2,148 |
| Structural flags | 1,140 | **816** |
| Cells holding several figures (merged columns) | 241 | 230 |
| Pixel cells needing review | 13,517 | 14,525 |
| Column roles assigned | 1,214 / 2,200 | 1,182 / 2,068 |

**Two numbers moved the "wrong" way, both for a good reason.** Review load rose
by about 1,000 cells because four PDFs with a garbled text layer are now read
by OCR: before, their garbled characters were passed as `exact`, which is worse
than any review load. Column roles fell because `Copy-HETERO 31.05.2025.xlsx`
now comes out as one 322-row table instead of many small ones that each counted
the same eight columns again.

#### Problems found and fixed

1. **Two reported silent errors were a measurement bug, not wrong data.**
   `New Doc 06-01-2026 08.28.pdf` p2 prints a *running* total: 1,906 from page 1
   plus 7,507 on page 2 = 9,413. The pipeline already recognised it as
   cumulative; the checker compared it with page 2 alone. The checker now
   carries each column's sum across a file's pages.
2. **A cell reading `a` (OCR for `0`) was marked verified.** Text in a figure
   column counts as zero in the stock equation, so the row balanced whatever
   the cell said. Such cells are now flagged `not_a_figure`.
3. **Garbled text layers were trusted.** `ratlam statement.pdf`,
   `khargone statement.pdf`, `New N.C Medical Agency.pdf` and `NTC Pharma.pdf`
   carry a text layer full of stray symbols (`PRODUCT 0£.SCKIPTIO.S`). A page
   where 2% or more of the words carry such symbols is now read with OCR.
   Measured over 1,212 text-layer pages: 1,189 have none at all. Result on
   `ratlam`: 0 -> 113 rows where the equation closes, 0 -> 21 totals reconciled.
4. **Files named for something they are not.** A PDF with no extension, a
   printer file saved as `.dat` (with printer control codes inside), a text
   printout named `.Doc`, a Word `.docx` export and an `.htm` web page were all
   refused by name. Files are now recognised by their contents; Word and HTML
   tables are read as addressed cells like a spreadsheet, and printer codes
   are stripped. `GENX STAT.dat`: 60 of 60 rows close; the `.docx`: 23 of 23.
   Only `Downloads.rar` (an archive) is still refused, as it should be.
5. **A blank scanned page counted as a failure.** `NEW DELIGHT THRISSUR ... .pdf`
   p2 has no ink on it; checked from the pixels, it is now a blank page.
6. **A closing page with its heading repeated counted as a failure.**
   `SRABANRI DISTRIBUORS.PDF` p3 holds only the banner, headings and the
   `GRAND TOTAL` line. Dates and page numbers no longer count as figures when
   deciding this.
7. **Sparse statements were not recognised as tables.** A statement that lists
   every product prints only name and pack for items with no movement. Those
   rows made a real table look ragged, and a name-and-pack row was even taken
   for a new header, cutting the table up (`pdf&rendition=1-3.pdf`). The table
   shape is now judged on rows that carry figures, and a two-cell row inside a
   table is never a new header.
8. **Column names.** `Opst` (opening stock) was not recognised; `Purc Free` and
   `Sale Free` (free goods) took the receipt and issue roles away from
   `Purc Qty` and `Sale Qty` (`MANAL PHARMA.htm`: 0 -> 24 rows closing).
   A first version also read `Cost`, `Best` and `Last` as stock words; that was
   caught and restricted before running the batches again.

#### Still open

- **Leaning columns on photos.** `NATH Lko.jpeg`, `SRI BALAJI KADAP.jpeg`,
  `May Junagadh.pdf` and `indore statement.pdf` hold most of the 230 cells
  with several figures in one cell. The photo was taken at a slight angle, so
  a column drifts sideways down the page and runs into its neighbour. These
  cells are **flagged**, never passed as correct. Fixing it needs the image
  straightened before OCR; loosening the column rules instead was measured to
  create false columns on other files.
- **Two pages still find no table**, and both are correct to say so:
  `VENKATESH ENTERPRISE MAY.pdf` p1 is a screenshot of a PDF viewer's toolbar,
  and `78352685.PDF` p2 is a pending-order note with no stock table.
- **72% of pixel-derived cells still need review.** Photos and scans verify
  only where the stock equation or a printed total can confirm a value.
