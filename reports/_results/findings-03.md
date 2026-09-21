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
