Batch 7 was tested and fixed in the same round as batches 4–6, so its defects
are recorded in full in [`batch-04-06.md`](batch-04-06.md), findings 9–14. The
ones found *on* batch 7's files:

- **`IMG20260714184904.heic` was rejected as an unsupported file type** — now
  read, 196 cells, healthy (finding 9).
- **`GENEX.pdf` p6: 45 data rows above the header became preamble**, 215
  numeric tokens in 1 cell — now 453 cells, healthy (finding 10).
- **`GENEX.pdf` headings merged one column to the left** on every page, and
  continuation pages inherited the wrong names (finding 11).
- **Arithmetic overruled `OPENING QTY.` and `RECEIPT VALUE`** with a fit it
  cannot distinguish from the heading's reading (finding 12).
- **Inherited roles duplicated a role, wrote into the raw layer, and kept an
  orientation flag the source heading had already settled** — 190 cells on four
  GENEX pages (finding 13).

Batch 7 is the first batch with **no unhealthy pages and no failures**.

**Open:** totals reconcile on only 1 of 26 printed totals. Most batch-7 totals
sit on `GENEX.pdf` and `genex (1).PDF`, whose total rows print quantity and
value pairs; this was not investigated in this round.
