"""Two-line headers, and what may override a heading.

Both guarantees here were defects found on held-out documents:

* A header whose column labels *wrap* onto two lines was rejected outright,
  because the rule for a *spanning* header ("the parent has fewer cells than
  the tier it spans") is false for the wrapped shape. The row carrying the flow
  words was discarded, every column ended up labelled only ``Qty.`` or
  ``Value``, issue and closing became impossible to tell apart, and two whole
  columns per page were flagged.

* With the headings restored, the rate relation then overrode them: a column
  the document calls ``Repl. Qty.`` was assigned ``closing_value``, on a page
  reporting zero flags.
"""

from __future__ import annotations

import pytest

from column_mapper import map_grid
from schema import Role, SectionKind


def _grid(rows, source="pdf_text"):
    return {"page": 1, "source": source,
            "rows": [{"index": i, "cells": r} for i, r in enumerate(rows)]}


def _tabular(document):
    return next(s for s in document.sections if s.kind is SectionKind.TABULAR)


# ---------------------------------------------------------------------------
# Wrapped two-line headers
# ---------------------------------------------------------------------------

WRAPPED_TOP = ["PRODUCT NAME", "Op.", "Opening Bal", "Receipt", "Receipt/Pur",
               "Issue", "Issue/Sales", "Closing", "Closing Bal"]
WRAPPED_BOTTOM = ["", "Qty.", "Value", "Qty.", "Value", "Qty.", "Value",
                  "Qty.", "Value"]


def _wrapped_rows(count=8):
    rows = [WRAPPED_TOP, WRAPPED_BOTTOM]
    for n in range(1, count + 1):
        opening, receipt, issue = 100 * n, 50, 30
        closing = opening + receipt - issue
        rows.append([f"ITEM {n}", str(opening), str(opening * 10), str(receipt),
                     str(receipt * 10), str(issue), str(issue * 10),
                     str(closing), str(closing * 10)])
    return rows


def test_a_wrapped_header_is_joined_per_column():
    """The upper row has *more* cells than the lower one here.

    That is the case the spanning rule rejected, and it is common: each
    column's own label simply runs onto two lines.
    """
    section = _tabular(map_grid(_grid(_wrapped_rows())))
    headers = {c.index: c.header_text for c in section.columns}

    assert headers[1] == "Op. Qty."
    assert headers[2] == "Opening Bal Value"
    assert headers[7] == "Closing Qty."
    assert len(section.header_row_indices) == 2, "both lines are the header"


def test_a_wrapped_header_resolves_issue_against_closing():
    """The point of recovering the flow words.

    Without them every column reads ``Qty.`` or ``Value``, the stock equation
    is symmetric in issue and closing, and the mapper has nothing to orient
    them with.
    """
    section = _tabular(map_grid(_grid(_wrapped_rows())))
    roles = {c.index: c.role for c in section.columns}

    assert roles[1] is Role.OPENING_QTY
    assert roles[3] is Role.RECEIPT_QTY
    assert roles[5] is Role.ISSUE_QTY
    assert roles[7] is Role.CLOSING_QTY
    assert not [c for c in section.columns if c.orientation_ambiguous], \
        "the headings settle the orientation; nothing should be a coin flip"


def test_a_spanning_header_still_merges(bansal_p1):
    """The shape the old rule was written for must keep working."""
    section = bansal_p1.sections[0]
    assert section.columns[2].header_text == "OPENING QTY."
    assert section.columns[3].header_text == "OPENING VALUE"


def test_two_full_headers_are_not_merged_into_one(khushi):
    """Khushi's ``Bill No | Gross Amount`` is a header in its own right.

    It contains measure vocabulary but is not *made of* it, which is the test
    that survived; the cell-count rule was redundant with it.
    """
    headers = [[c.header_text for c in s.columns] for s in khushi.sections]
    assert ["Product", "Pkg", "BATCHNO", "EXPIRY", "Stock"] in headers
    assert ["Bill No", "Bill Date", "Gross Amount", "Net Amount"] in headers


# ---------------------------------------------------------------------------
# A heading outranks a coincidental product
# ---------------------------------------------------------------------------


def _rate_trap_rows(count=8):
    """A grid where `closing x receipt = value` holds by construction.

    The receipt column is headed ``In Qty.``, so the rate relation will propose
    it as the rate column. The document says it is a quantity.
    """
    rows = [["Item", "Op. Qty.", "In Qty.", "Out Qty.", "Cl. Qty.", "Amt Value"]]
    for n in range(1, count + 1):
        opening, receipt, issue = 10 * n, 5, 3
        closing = opening + receipt - issue
        rows.append([f"ITEM {n}", str(opening), str(receipt), str(issue),
                     str(closing), str(closing * receipt)])
    return rows


def test_a_column_the_document_calls_a_quantity_is_never_a_rate_or_a_value():
    section = _tabular(map_grid(_grid(_rate_trap_rows())))
    by_header = {c.header_text: c for c in section.columns}

    receipt = by_header["In Qty."]
    assert receipt.role is not Role.RATE
    assert not receipt.role.value.endswith("_value")
    assert any("heading says quantity" in e for e in receipt.evidence), \
        "the refusal must be recorded, not silent"


def test_no_role_contradicts_its_own_heading():
    """The general property, over every column of the trap grid."""
    from column_mapper import _measure_from_header

    section = _tabular(map_grid(_grid(_rate_trap_rows())))
    for column in section.columns:
        measure = _measure_from_header(column.header_text)
        if not measure or column.role is Role.UNKNOWN:
            continue
        role = column.role.value
        says_value = role.endswith("_value") or role == "rate"
        says_qty = role.endswith("_qty")
        assert not (measure == "qty" and says_value), \
            f"{column.header_text!r} says quantity but was mapped {role}"
        assert not (measure == "value" and says_qty), \
            f"{column.header_text!r} says value but was mapped {role}"
