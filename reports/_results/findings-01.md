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
