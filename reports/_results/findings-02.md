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
