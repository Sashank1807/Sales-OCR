"""Stage B tests - arithmetic, totals, coverage and formats.

Every numeric expectation here was checked by hand against the source
documents before being written down.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from column_mapper import map_grid
from conftest import load_raw, mapped, mutate_cell, row_named, value_of
from schema import CellStatus, Role, SectionKind
from validator import (
    ValidationContext, Validator, ValidatorConfig, gstin_check_digit,
    is_valid_date, is_valid_gstin, validate_document, validate_pages,
)


def report_for(document):
    return Validator().validate(document)


def assert_confirmed_by(cell, check: str):
    """The named check ran on this cell and did not fail it.

    Asserting the *reason* rather than the status is deliberate. Since the
    taxonomy split, a cell from a PDF text layer is ``exact`` whether or not
    arithmetic touched it - so checking the status alone would no longer prove
    the check ran. The reason does.
    """
    assert check in cell.reasons, (
        f"expected {check!r} among {cell.reasons!r}")
    assert cell.status is not CellStatus.FLAGGED, (
        f"cell was flagged: {cell.reasons!r}")
    assert not cell.needs_review


# ---------------------------------------------------------------------------
# Row arithmetic
# ---------------------------------------------------------------------------


def test_amar_row_arithmetic_and_rate(amar):
    """AD 10 SACHETS: 10 + 50 - 10 = 50, and 50 x 9.26 = 463.00."""
    report = report_for(amar)
    section = amar.sections[0]
    row = row_named(section, "AD 10 SACHETS")

    assert value_of(section, row, Role.CLOSING_QTY).value == Decimal("50.000")
    assert value_of(section, row, Role.CLOSING_VALUE).value == Decimal("463.00")
    for role in (Role.OPENING_QTY, Role.RECEIPT_QTY, Role.ISSUE_QTY, Role.CLOSING_QTY):
        assert_confirmed_by(value_of(section, row, role), "row_equation_qty")
    assert report.invariant("row_equation_qty").adopted


def test_rate_rounding_is_tolerated(amar):
    """C FURO 250: 11 x 127.43 = 1401.73 against a printed 1401.68.

    A rate rounded to paise accumulates error with quantity. 0.05 is rounding,
    not a misread, and must not be flagged.
    """
    section = amar.sections[0]
    row = row_named(section, "C FURO 250")
    qty = value_of(section, row, Role.CLOSING_QTY).value
    rate = value_of(section, row, Role.RATE).value
    printed = value_of(section, row, Role.CLOSING_VALUE).value

    assert qty * rate == Decimal("1401.73")
    assert printed == Decimal("1401.68")
    report_for(amar)
    assert_confirmed_by(value_of(section, row, Role.CLOSING_VALUE), "rate_product")


def test_blank_that_makes_the_arithmetic_work_is_a_zero(amar):
    """FORSLEEP: In=1, Out=1, Balance blank. 0 + 1 - 1 = 0, so blank is zero."""
    report_for(amar)
    section = amar.sections[0]
    row = row_named(section, "FORSLEEP")

    closing = value_of(section, row, Role.CLOSING_QTY)
    assert closing.is_blank
    assert_confirmed_by(closing, "blank_confirmed_zero")


def test_blank_that_breaks_the_arithmetic_is_flagged(amar):
    """The same blank, with a receipt that no longer cancels the issue."""
    grid = load_raw("amar")
    forsleep = next(r["index"] for r in grid["rows"]
                    if r["cells"] and str(r["cells"][0]).startswith("FORSLEEP"))
    broken = mutate_cell(grid, forsleep, 3, "7.000")   # In: 1 -> 7

    document = map_grid(broken)
    validate_document(document)
    section = document.sections[0]
    closing = value_of(section, row_named(section, "FORSLEEP"), Role.CLOSING_QTY)

    assert closing.is_blank
    assert closing.status is CellStatus.FLAGGED
    assert "blank_breaks_arithmetic" in closing.reasons


def test_negative_closing_quantity_is_valid(bansal_p1):
    """LANOL ER: 136 + 400 - 600 = -64. Real data goes negative."""
    report_for(bansal_p1)
    section = bansal_p1.sections[0]
    row = row_named(section, "LANOL ER")

    closing = value_of(section, row, Role.CLOSING_QTY)
    assert closing.value == Decimal("-64")
    assert_confirmed_by(closing, "row_equation_qty")


def test_one_bad_row_is_flagged_without_rejecting_the_page(amar):
    """The invariant holds on the rest, so only the offending row is flagged."""
    grid = load_raw("amar")
    target = next(r["index"] for r in grid["rows"]
                  if r["cells"] and str(r["cells"][0]).startswith("PANTIN"))
    broken = mutate_cell(grid, target, 5, "99.000")   # Balance 16 -> 99

    document = map_grid(broken)
    report = validate_document(document)
    section = document.sections[0]

    assert report.invariant("row_equation_qty").adopted, "the page is still usable"
    flagged_rows = {f.row_index for f in report.flagged if f.check == "row_equation_qty"}
    assert flagged_rows == {target}
    assert_confirmed_by(value_of(section, row_named(section, "AD 10 SACHETS"),
                                 Role.CLOSING_QTY), "row_equation_qty")


# ---------------------------------------------------------------------------
# Which relationships actually hold
# ---------------------------------------------------------------------------


def test_value_columns_do_not_reconcile_but_quantities_do(bansal_p1):
    """ENUFF 10: 960.45 + 1011.00 - 1710.00 != 353.85, yet 95 + 100 - 160 = 35.

    The value relationship must be found not to apply, so the value cells come
    back unchecked rather than flagged across the whole document.
    """
    report = report_for(bansal_p1)
    section = bansal_p1.sections[0]
    row = row_named(section, "ENUFF 10")

    assert report.invariant("row_equation_qty").adopted
    assert not report.invariant("row_equation_value").adopted

    assert_confirmed_by(value_of(section, row, Role.CLOSING_QTY), "row_equation_qty")
    closing_value = value_of(section, row, Role.CLOSING_VALUE)
    assert "row_equation_value_not_applicable" in closing_value.reasons
    assert "row_equation_value" not in closing_value.reasons


def test_static_rows_are_excluded_when_judging_an_invariant(bansal_p1):
    """Rows with no movement satisfy the equation whatever the columns mean.

    Counting them would let the value relationship look well supported when it
    holds on none of the rows that actually move.
    """
    report = report_for(bansal_p1)
    value_invariant = report.invariant("row_equation_value")

    assert value_invariant.degenerate_rows > 40
    assert value_invariant.informative_rows == 16
    assert value_invariant.agreeing_rows == 0
    assert value_invariant.support == 0.0


def test_quantity_invariant_uses_only_moving_rows(bansal_p1):
    report = report_for(bansal_p1)
    qty = report.invariant("row_equation_qty")
    assert qty.adopted
    assert qty.agreeing_rows == qty.informative_rows == 16
    assert qty.degenerate_rows == 14


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------


def test_bansal_page1_totals_match_the_column_sums(bansal_p1):
    """1082 + 895 - 1064 = 913, and each printed total is its column's sum."""
    report = report_for(bansal_p1)
    verified = {tuple(f.column_indices) for f in report.findings
                if f.check == "total" and f.status is CellStatus.VERIFIED}
    assert {(2,), (3,), (4,), (5,), (6,), (7,), (8,), (9,)} <= verified
    assert report.totals_by_role["opening_qty"] == "1082"
    assert report.totals_by_role["closing_qty"] == "913"


def test_total_row_satisfies_the_row_equation(bansal_p1):
    report = report_for(bansal_p1)
    findings = [f for f in report.findings if f.check == "row_equation_qty_total_row"]
    assert findings and findings[0].status is CellStatus.VERIFIED
    assert findings[0].expected == "913"


def test_cumulative_total_is_recognised_not_double_counted(bansal_p1, bansal_p2):
    """Page 2's printed 1336 already contains page 1's 1082.

    1082 carried + (65 + 189) on this page = 1336. Summing the two printed
    totals would count page 1 twice.
    """
    reports = validate_pages([bansal_p1, bansal_p2])
    page2 = reports[1]

    cumulative = {f.column_indices[0]: f for f in page2.findings
                  if f.check == "total_cumulative"}
    assert 2 in cumulative
    assert cumulative[2].status is CellStatus.VERIFIED
    assert cumulative[2].expected == "1336"
    assert "do not add it to earlier pages again" in cumulative[2].message

    assert 8 in cumulative, "closing quantity is cumulative too"
    assert cumulative[8].expected == "1100"
    assert not page2.flagged


def test_without_page_context_a_cumulative_total_is_not_silently_accepted(bansal_p2):
    """Validated alone, page 2's total cannot be explained and must surface."""
    report = Validator().validate(bansal_p2, ValidationContext())
    unexplained = [f for f in report.findings
                   if f.check == "total" and f.status is not CellStatus.VERIFIED]
    assert unexplained, "an unexplainable total must never pass as verified"


def test_printed_total_on_a_different_measure_does_not_fire_the_sum_check(krishna):
    """Krishna's TOTAL of 60837 is a value figure with no matching column.

    The opening quantities sum to 1303. Asserting "total = column sum" here
    would flag every row on the page for no reason.
    """
    report = report_for(krishna)
    section = krishna.sections[0]
    opening = section.role_index(Role.OPENING_QTY)
    column_sum = sum(r.cell_at(opening).value for r in section.data_rows
                     if r.cell_at(opening).is_numeric)
    assert column_sum == 1303

    findings = [f for f in report.findings
                if f.check == "total" and f.column_indices == [opening]]
    assert len(findings) == 1
    assert findings[0].status is CellStatus.UNCHECKED
    assert "different measure" in findings[0].message
    assert findings[0].status is not CellStatus.FLAGGED


def test_a_total_that_is_merely_wrong_is_still_flagged(bansal_p1):
    """The magnitude guard must not swallow a plausible-looking error."""
    grid = load_raw("bansal_p1")
    total_index = max(r["index"] for r in grid["rows"])
    broken = mutate_cell(grid, total_index, 2, "1092")   # 1082 -> 1092

    report = validate_document(map_grid(broken))
    flagged = [f for f in report.flagged if f.check == "total"]
    assert flagged, "a ten-unit discrepancy is an error, not a different measure"
    assert flagged[0].expected == "1082"
    assert flagged[0].actual == "1092"


def test_amar_grand_total_row_balances(amar_grand_total):
    """9609 + 3339 - 4647 = 8301, verified from the total row alone.

    The visible rows cannot reproduce a grand total taken over the whole
    report, and that must not be reported as an error.
    """
    report = report_for(amar_grand_total)
    findings = [f for f in report.findings if f.check == "row_equation_qty_total_row"]

    assert len(findings) == 1
    assert findings[0].status is CellStatus.VERIFIED
    assert findings[0].expected == "8301.000"
    assert not report.flagged


# ---------------------------------------------------------------------------
# Empty and non-tabular sections
# ---------------------------------------------------------------------------


def test_empty_section_yields_no_rows_and_no_invented_data(khushi):
    report = report_for(khushi)
    empty = [s for s in khushi.sections if s.kind is SectionKind.EMPTY]

    assert len(empty) == 2
    assert all(s.rows == [] for s in empty)
    notes = [f for f in report.findings if f.check == "empty_section"]
    assert len(notes) == 2
    assert all(f.status is CellStatus.UNCHECKED for f in notes)


def test_non_tabular_block_is_not_run_through_stock_arithmetic(krishna):
    report = report_for(krishna)
    findings = [f for f in report.findings if f.check == "non_tabular_section"]

    assert findings and findings[0].status is CellStatus.UNCHECKED
    purchase = krishna.sections[1]
    assert all(c.status is CellStatus.UNCHECKED
               for row in purchase.rows for c in row.cells)


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def test_pen_marked_cells_are_flagged_on_confidence(krishna):
    """Blue pen circles over the closing column depress OCR confidence."""
    report = report_for(krishna)
    findings = [f for f in report.findings if f.check == "confidence"]

    assert len(findings) == 5
    assert all(f.status is CellStatus.FLAGGED for f in findings)
    flagged_texts = {f.message.split("for ")[1] for f in findings}
    assert "'490'" in flagged_texts and "'188'" in flagged_texts


def test_confidence_threshold_is_configurable(krishna):
    report = Validator(ValidatorConfig(min_confidence=0.30)).validate(krishna)
    assert not [f for f in report.findings if f.check == "confidence"]


def test_krishna_quantities_are_unchecked_not_assumed_correct(krishna):
    """Nothing moved on this page, so the arithmetic proves nothing.

    Reporting these as verified would be exactly the silent error the pipeline
    exists to prevent.
    """
    report = report_for(krishna)
    qty = report.invariant("row_equation_qty")

    assert not qty.adopted
    assert qty.informative_rows == 0
    assert qty.degenerate_rows == 13

    section = krishna.sections[0]
    row = row_named(section, "BILASTERO M TABS")
    assert value_of(section, row, Role.CLOSING_QTY).status is CellStatus.UNCHECKED


# ---------------------------------------------------------------------------
# The error the row checks cannot find
# ---------------------------------------------------------------------------


HEADERLESS_GRID = {
    "page": 1,
    "rows": [
        {"index": 0, "cells": ["Item", "A", "B", "C", "D"]},
        {"index": 1, "cells": ["ALPHA TAB", "10", "50", "10", "50"]},
        {"index": 2, "cells": ["BETA CAP", "9", "30", "9", "30"]},
        {"index": 3, "cells": ["GAMMA SYP", "122", "3", "5", "120"]},
        {"index": 4, "cells": ["DELTA INJ", "92", "6", "30", "68"]},
        {"index": 5, "cells": ["EPSILON TAB", "77", "124", "58", "143"]},
    ],
}


def test_unorientable_columns_are_flagged_not_quietly_verified():
    """With no heading, issue and closing may be transposed.

    The row equation is satisfied either way, so this is the one error the
    arithmetic is structurally incapable of catching. Reporting those cells as
    verified would be a silent error of exactly the kind this gate exists to
    prevent.
    """
    document = map_grid(HEADERLESS_GRID)
    report = validate_document(document)
    section = document.sections[0]

    findings = [f for f in report.findings if f.check == "column_orientation"]
    assert len(findings) == 1
    assert findings[0].status is CellStatus.FLAGGED
    assert "may be transposed" in findings[0].message

    for index in findings[0].column_indices:
        for row in section.data_rows:
            assert row.cell_at(index).status is CellStatus.FLAGGED


def test_orientation_check_is_silent_when_headings_settle_it(amar, bansal_p1):
    for document in (amar, bansal_p1):
        report = validate_document(document)
        assert not [f for f in report.findings if f.check == "column_orientation"]


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,expected", [
    ("amar", 120), ("bansal_p1", 374), ("krishna", 32),
])
def test_every_numeric_token_reaches_the_output(name, expected):
    report = report_for(mapped(name))
    assert report.coverage.numeric_tokens_seen == expected
    assert report.coverage.numeric_tokens_placed == expected
    assert report.coverage.complete


def test_a_dropped_value_is_caught_by_coverage():
    """OCR read a number that never landed in a cell: the gate must notice."""
    grid = load_raw("amar")
    grid["tokens"].append({"text": "77777.77", "confidence": 0.99})

    report = validate_document(map_grid(grid))
    findings = [f for f in report.flagged if f.check == "coverage"]

    assert findings, "a token that never reached a cell must be flagged"
    assert "77777.77" in report.coverage.missing
    assert not report.coverage.complete


# ---------------------------------------------------------------------------
# Row shape
# ---------------------------------------------------------------------------


def test_cells_past_the_last_column_are_flagged():
    grid = {
        "page": 1,
        "rows": [
            {"index": 0, "cells": ["Item", "Opening", "In", "Out", "Balance"]},
            {"index": 1, "cells": ["ALPHA", "10", "50", "10", "50"]},
            {"index": 2, "cells": ["BETA", "9", "30", "9", "30"]},
            {"index": 3, "cells": ["GAMMA", "122", "3", "5", "120"]},
            {"index": 4, "cells": ["DELTA", "92", "6", "30", "68", "STRAY"]},
        ],
    }
    report = validate_document(map_grid(grid))
    flagged = [f for f in report.flagged if f.check == "row_shape"]
    assert flagged and flagged[0].row_index == 4


def test_a_sparse_row_is_reported_without_being_flagged(khushi):
    report = report_for(khushi)
    shape = [f for f in report.findings if f.check == "row_shape"]
    assert all(f.status is CellStatus.UNCHECKED for f in shape)


# ---------------------------------------------------------------------------
# Formats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("gstin", ["09AAMPA4057B1Z2", "09AAKHR3684K1ZE"])
def test_real_gstins_pass_the_checksum(gstin):
    assert is_valid_gstin(gstin)
    assert gstin_check_digit(gstin[:14]) == gstin[14]


@pytest.mark.parametrize("gstin", [
    "09AAMPA4057B1Z9",   # check digit wrong
    "09AAMPA4057B1Z",    # too short
    "",
    "9AAMPA4057B1Z2X",   # wrong shape
])
def test_bad_gstins_are_rejected(gstin):
    assert not is_valid_gstin(gstin)


def test_gstin_is_validated_in_the_report(bansal_p1):
    report = report_for(bansal_p1)
    findings = [f for f in report.findings if f.check == "gstin"]
    assert findings and findings[0].status is CellStatus.VERIFIED


def test_a_corrupted_gstin_is_flagged():
    grid = load_raw("bansal_p1")
    for row in grid["rows"]:
        if row["cells"] and "GSTIN" in str(row["cells"][0]):
            row["cells"][0] = str(row["cells"][0]).replace("09AAMPA4057B1Z2",
                                                           "09AAMPA4057B1Z9")
    report = validate_document(map_grid(grid))
    findings = [f for f in report.flagged if f.check == "gstin"]
    assert findings
    assert "check digit 2" in findings[0].expected


@pytest.mark.parametrize("text,valid", [
    ("01/08/2026", True), ("31-08-2026", True), ("01/Aug/2026", True),
    ("2026-08-01", True), ("32/08/2026", False), ("01/13/2026", False),
    ("not a date", False), ("", False),
])
def test_date_formats(text, valid):
    assert is_valid_date(text) is valid


def test_period_dates_are_validated(amar):
    report = report_for(amar)
    findings = [f for f in report.findings if f.check == "date_format"]
    assert len(findings) == 2
    assert all(f.status is CellStatus.VERIFIED for f in findings)


# ---------------------------------------------------------------------------
# Overall guarantees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["amar", "bansal_p1", "khushi", "amar_grand_total"])
def test_clean_documents_produce_no_flags(name):
    assert not report_for(mapped(name)).flagged


def test_every_data_cell_carries_a_status_and_provenance(bansal_p1):
    """No cell may leave the pipeline unaccounted for."""
    report_for(bansal_p1)
    seen = 0
    for section, row, cell in bansal_p1.iter_cells():
        assert cell.status in (CellStatus.EXACT, CellStatus.VERIFIED,
                               CellStatus.FLAGGED, CellStatus.UNCHECKED)
        assert cell.provenance.source is not None
        assert cell.provenance.page == 1
        if cell.status in (CellStatus.VERIFIED, CellStatus.FLAGGED):
            assert cell.reasons, "a decision must record why"
        seen += 1
    assert seen > 500


def test_counts_add_up(bansal_p1):
    report = report_for(bansal_p1)
    counts = report.counts
    assert (counts["exact"] + counts["verified"] + counts["flagged"]
            + counts["unchecked"] == counts["total_cells"])


def test_document_serialises_to_json(amar):
    report_for(amar)
    payload = amar.to_json()
    assert '"raw_text"' in payload and '"status"' in payload
    assert '"provenance"' in payload and '"role"' in payload
