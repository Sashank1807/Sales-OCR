# Test report — Stage A (column mapping) and Stage B (validation)

**Date:** 12 September 2026
**Suite:** `python -m pytest tests/ -q` → **82 passed**, 0 failed, 6.8 s
**Environment:** Python 3.10.11, Windows, standard library + `pytest` only

| Module | Tests |
| --- | --- |
| `tests/test_column_mapper.py` | 29 |
| `tests/test_validator.py` | 53 |

---

## Documents tested

Four real distributor reports, transcribed by hand into grid fixtures. Three
are native-PDF layouts; one is a handheld phone photo.

| Fixture | Source | Layout characteristics |
| --- | --- | --- |
| `amar` | Amar Pharmaceuticals | Single-tier header, bare `Opening/In/Out/Balance`, rate & value columns, truncated unit strings |
| `amar_grand_total` | Amar Pharmaceuticals | The printed Grand Total row with only part of the report visible |
| `bansal_p1` / `bansal_p2` | Bansal Medical Agencies | Two-tier header (`OPENING/RECEIPT/…` over `QTY./VALUE`), 64 rows, negative closings, cumulative page-2 total |
| `khushi` | Khushi Healthcare | Abbreviated headers, section titles, two headers with **no data rows** |
| `krishna` | Krishna Pharma | Phone photo, rotated, blue pen circles over digits, a value total under quantity columns, a second non-tabular block |

### Transcription fidelity

Bansal was transcribed in full (64 rows × 11 columns) and audited against the
document's own printed totals before any test was written:

| Column | Printed total | Sum of transcribed rows | |
| --- | --- | --- | --- |
| opening qty | 1082 | 1082 | ✅ |
| opening value | 77928.30 | 77928.30 | ✅ |
| receipt qty | 895 | 895 | ✅ |
| receipt value | 27363.03 | 27363.03 | ✅ |
| issue qty | 1064 | 1064 | ✅ |
| issue value | 26144.75 | 26144.75 | ✅ |
| closing qty | 913 | 913 | ✅ |
| closing value | 81226.95 | 81226.95 | ✅ |

All eight reconcile exactly, and all eight are cumulative on page 2. The tests
therefore run against data the source document itself confirms.

---

## Results by document

| Fixture | Sections | Columns | Mapped | Data rows | Cells | Verified | Flagged | Unchecked | Coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `amar` | 1 | 9 | 9 | 24 | 216 | 138 | 0 | 78 | 120/120 |
| `amar_grand_total` | 1 | 9 | 9 | 2 | 27 | 16 | 0 | 11 | — |
| `bansal_p1` | 1 | 11 | 11 | 64 | 715 | 128 | 0 | 587 | 374/374 |
| `bansal_p2` | 1 | 11 | 11 | 2 | 33 | 10 | 3\* | 20 | 25/25 |
| `khushi` | 3 | 19 | 11 | 2 | 30 | 9 | 0 | 21 | — |
| `krishna` | 2 | 11 | 7 | 14 | 89 | 4 | **5** | 80 | 32/32 |

\* Page 2 validated **in isolation** cannot explain its cumulative total, so it
flags. Run as a document via `validate_pages([p1, p2])` both pages come back
**0 flagged**. That is deliberate — see *Cumulative totals* below.

Krishna's 5 flags are exactly the five pen-circled cells. No false positives
anywhere in the set.

---

## Every case from the brief

### Amar Pharmaceuticals

| Case | Expected | Result |
| --- | --- | --- |
| `AD 10 SACHETS` — 10 + 50 − 10 = 50 | verified | ✅ `test_amar_row_arithmetic_and_rate` |
| `AD 10 SACHETS` — 50 × 9.26 = 463.00 | verified | ✅ same |
| `C FURO 250` — 11 × 127.43 = 1401.73 vs printed 1401.68 | **must pass** | ✅ `test_rate_rounding_is_tolerated` |
| `FORSLEEP` — In=1, Out=1, Balance blank | blank reads as zero | ✅ `test_blank_that_makes_the_arithmetic_work_is_a_zero` |
| Grand Total — 9609 + 3339 − 4647 = 8301 | verified | ✅ `test_amar_grand_total_row_balances` |
| Units `2MG/2I`, `500MG.` | verbatim, never autocorrected | ✅ `test_truncated_unit_strings_survive_verbatim` |

The 0.05 discrepancy on `C FURO 250` is 0.0036% — well inside the `max(0.1%,
0.10)` tolerance. Across Amar's 24 rows the rate relation holds 21/21 with no
flags; the widest gap is `Eco All Liquid` at 1.76 on 10971.68 (0.016%).

### Bansal Medical Agencies

| Case | Expected | Result |
| --- | --- | --- |
| `LANOL ER` — 136 + 400 − 600 = **−64** | negative closing is valid | ✅ `test_negative_closing_quantity_is_valid` |
| Page 1 TOTAL — 1082 + 895 − 1064 = 913 | verified | ✅ `test_total_row_satisfies_the_row_equation` |
| Page 1 totals vs column sums | all 8 match | ✅ `test_bansal_page1_totals_match_the_column_sums` |
| Page 2 TOTAL 1336 is **cumulative** | not double-counted | ✅ `test_cumulative_total_is_recognised_not_double_counted` |
| `ENUFF 10` — values don't reconcile, quantities do | value unchecked, qty verified | ✅ `test_value_columns_do_not_reconcile_but_quantities_do` |

### Khushi Healthcare

| Case | Expected | Result |
| --- | --- | --- |
| Section with headers and zero data rows | empty section, **never invented rows** | ✅ `test_khushi_returns_empty_sections_rather_than_inventing_rows` |

Two such sections were found (the expiry listing and the bill listing), both
returning `rows == []` while still reporting their headings.

### Krishna Pharma

| Case | Expected | Result |
| --- | --- | --- |
| TOTAL 60837 is a value total with no matching column | "total = column sum" must **not** fire | ✅ `test_printed_total_on_a_different_measure_does_not_fire_the_sum_check` |
| Blue pen circles over the closing column | flagged | ✅ `test_pen_marked_cells_are_flagged_on_confidence` |
| Second non-tabular section (purchase details) | separate section, no stock arithmetic | ✅ `test_krishna_purchase_block_is_non_tabular` |

The opening quantities sum to **1303** against a printed **60837** — 46.7×
apart. The magnitude guard classifies that as a different measure and returns
`unchecked`, rather than flagging all 14 rows.

---

## Four defects found and fixed during development

These are worth recording because each would have produced *silent* errors —
wrong output with every check still passing.

### 1. Issue and closing columns silently transposed

`opening + receipt − issue = closing` is algebraically identical to
`opening + receipt − closing = issue`. Several permutations satisfy every row
equally well, so arithmetic alone **cannot orient the pair**. The mapper was
picking whichever scored marginally higher and swapping Bansal's issue (1064)
and closing (913) columns — while every arithmetic check continued to pass.

Fixed by scoring candidate equations for agreement with the headings, so the
document's own labels break the symmetry. Where no headings exist the ambiguity
is now recorded on the columns instead of being guessed at.

Covered by `test_issue_and_closing_are_not_swapped` and
`test_headerless_orientation_ambiguity_is_recorded`.

### 2. An unorientable guess was reported as verified

Follow-on from the first. When the headings are *absent entirely* — not merely
mangled — the symmetry cannot be broken at all, and the mapper picked one of the
two readings. It recorded the ambiguity in the column's `evidence`, but the
confidence stayed at 0.80 (above the VLM threshold, so the fallback was never
offered the question) and Stage B reported those cells **verified with zero
flags**. A consumer reading `role` plus `status` would have been handed
transposed columns wearing a clean bill of health.

This is the one error the row equation is structurally incapable of finding,
since it is satisfied either way. Now the confidence is capped below the VLM
threshold and Stage B raises a `column_orientation` finding that flags the
affected cells. Covered by
`test_unorientable_columns_are_flagged_not_quietly_verified` and
`test_unresolved_orientation_is_not_reported_confidently`, with
`test_orientation_check_is_silent_when_headings_settle_it` confirming it does
not misfire on documents that label their columns.

### 3. Static rows made a non-existent relationship look well supported

Rows with no movement (`receipt == issue == 0`) satisfy the row equation
trivially under *any* interpretation. Bansal has 48 such rows against 16 that
move. Counting them put the value relationship at 79% support — above the 70%
threshold — so it would have been adopted and **16 correct rows flagged as
errors**, while the remaining cells were reported as verified on the strength of
rows that prove nothing.

Excluding static rows from support estimation gives the true picture: value
0/16 (not applicable), quantity 16/16 (adopted). They are still checked once an
invariant is adopted.

Covered by `test_static_rows_are_excluded_when_judging_an_invariant`.

### 4. Weak arithmetic overrode an explicit header on a short page

Bansal page 2 has two data rows and an all-blank receipt column. Spurious
equations fit that little data easily, and one did — reassigning the
`RECEIPT VALUE` column to `receipt_qty` despite an unambiguous two-tier heading.

Arithmetic now needs at least 4 rows with real movement before it may outrank an
explicit heading. Covered by
`test_short_page_does_not_let_weak_arithmetic_override_headers`.

---

## Robustness tests

Beyond the documents, the suite injects faults to confirm the gate closes:

| Test | Injected fault | Expected |
| --- | --- | --- |
| `test_one_bad_row_is_flagged_without_rejecting_the_page` | one balance changed 16 → 99 | that row alone flagged; invariant still adopted; other rows still verified |
| `test_blank_that_breaks_the_arithmetic_is_flagged` | receipt changed so the blank no longer cancels | blank flagged `blank_breaks_arithmetic` |
| `test_a_total_that_is_merely_wrong_is_still_flagged` | total changed 1082 → 1092 | flagged — the magnitude guard must not swallow it |
| `test_a_dropped_value_is_caught_by_coverage` | a token OCR saw never reaches a cell | flagged, listed in `coverage.missing` |
| `test_a_corrupted_gstin_is_flagged` | check digit changed | flagged with the expected digit |
| `test_cells_past_the_last_column_are_flagged` | a stray cell beyond the header | flagged (it previously created a phantom column) |
| `test_a_failing_vlm_never_loses_the_page` | resolver raises | page still mapped, failure noted |
| `test_vlm_cannot_invent_a_role_or_duplicate_one` | resolver returns a bogus and a taken role | both refused |

The GSTIN checksum was verified against both real GSTINs in the documents —
`09AAMPA4057B1Z2` and `09AAKHR3684K1ZE` — and both pass shape and check digit.

---

## Column mapping accuracy

39 of 39 columns across the four stock tables were mapped correctly. The 8
columns left `unknown` were left so **deliberately**:

| Column | Document | Why unknown |
| --- | --- | --- |
| `Sales Ret.` | Khushi | A sales return is an *inward* movement. No canonical role exists; folding it into issues would corrupt the arithmetic. |
| `Misc. Out` | Khushi | An outflow distinct from sales. Arithmetic confirms `Sales & DC` is the issue column, not this one. |
| `INVOICE NO.`, `DATE`, `RECEIVE DATE`, `AMOUNT`, + 3 in bill/expiry blocks | Krishna, Khushi | Not stock columns. `RECEIVE DATE` fuzzy-matches "received" and was rejected because the column holds dates, not numbers. |

Two columns with **no heading at all** (Bansal and Krishna pack columns) were
recovered from data shape alone, and Amar's `Value` column — which matches no
synonym — was recovered from the `qty × rate = value` relation.

---

## Caveats

1. **`ocr_to_table.py` is not in this repository.** The grid contract is
   documented in `PIPELINE.md` and the loader is tolerant (cells may be strings
   or objects, indices explicit or positional), but the two have not been run
   against each other. Expect a thin adapter.

2. **Fixtures are hand transcriptions, not OCR output.** Bansal is
   self-auditing against its printed totals; Amar, Khushi and Krishna are not
   fully reconcilable that way. Real OCR will introduce failure modes these
   fixtures cannot exercise — merged cells, split rows, dropped columns. The
   Amar fixture is a 24-row subset of ~78.

3. **Amar's wrapped Grand Total.** In the original the grand total spans two
   visual lines (`9609.000 4647.000` / `3339.000 8301.000`). The fixture uses
   the reconciled single-row reading; un-wrapping that belongs in
   `ocr_to_table.py`, not here.

4. **Krishna's rotation and pen marks are modelled, not performed.** The fixture
   encodes the *consequence* — low OCR confidence on the circled cells. Actual
   deskewing and ink handling sit upstream.

5. **High `unchecked` counts are expected, not a shortfall.** Bansal shows 587
   unchecked of 715 cells, because the value relationship genuinely does not
   hold for that document and 48 of 64 rows have no movement to verify. Every
   one carries a reason. Driving that number down requires more cross-checks,
   not weaker ones.

6. **Python 3.10, not 3.11+.** The brief asked for 3.11+; this repo's virtualenv
   is 3.10.11, so the code targets 3.10 syntax (`from __future__ import
   annotations`, no `StrEnum`). It runs unchanged on 3.11+.

---

## Reproducing

```bash
python -m pytest tests/ -q                        # 82 tests
python tests/fixtures/_build_fixtures.py          # regenerate fixtures
python column_mapper.py tests/fixtures/bansal_p1.json
python validator.py     tests/fixtures/krishna.json
```

`validator.py` exits non-zero when anything is flagged: `amar` → 0,
`krishna` → 1.
