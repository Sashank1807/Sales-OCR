"""Which column is the issue and which the closing.

``opening + receipt - issue = closing`` and ``opening + receipt - closing =
issue`` are the same statement. Arithmetic can therefore find *which four
columns* form the stock group, and can never say which way round the last two
go. Only the headings can, and these are the two ways that went wrong:

* The search settled the orientation on its tie-breaks - chiefly how many rows
  show movement. That count differs between the two readings by accident of
  which column happens to hold zeros, and it outweighed the headings. A page
  headed ``OPENING | RECEIPT | ISSUE | CLOSING`` came back with issue and
  closing transposed, and reported **no flags at all** - the values were right,
  the labels on them were wrong, and nothing said so.

* The ambiguity was only recorded when the page had no headings whatsoever. A
  page whose other columns were well named but whose issue and closing pair was
  anonymous reported a coin flip at full confidence.
"""

from __future__ import annotations

from column_mapper import map_grid
from schema import Role, SectionKind


def _grid(rows, source="pdf_text"):
    return {"page": 1, "source": source,
            "rows": [{"index": i, "cells": r} for i, r in enumerate(rows)]}


def _tabular(document):
    return next(s for s in document.sections if s.kind is SectionKind.TABULAR)


def _rows(header):
    """Mostly static stock, with two rows that actually move.

    The shape matters. On a static row receipt and issue are both zero while
    closing is not, so reading the closing column *as* the issue column makes
    far more rows look like rows with movement - which is exactly the tie-break
    the search used to reward. The headings are the only honest signal here.
    """
    rows = [header]
    for n in range(1, 9):
        rows.append([f"ITEM {n}", str(100 * n), "0", "0", str(100 * n)])
    rows.append(["MOVER A", "100", "50", "30", "120"])
    rows.append(["MOVER B", "200", "10", "40", "170"])
    rows.append(["MOVER C", "300", "25", "75", "250"])
    rows.append(["MOVER D", "400", "60", "20", "440"])
    return rows


NAMED = ["ITEM", "OPENING", "RECEIPT", "ISSUE", "CLOSING"]
ANONYMOUS = ["ITEM", "OPENING", "RECEIPT", "", ""]


def test_the_headings_decide_the_orientation_not_the_row_counts():
    section = _tabular(map_grid(_grid(_rows(NAMED))))
    roles = {c.index: c.role for c in section.columns}

    assert roles[1] is Role.OPENING_QTY
    assert roles[2] is Role.RECEIPT_QTY
    assert roles[3] is Role.ISSUE_QTY, "the column headed ISSUE is the issue"
    assert roles[4] is Role.CLOSING_QTY, "the column headed CLOSING is the closing"


def test_a_settled_orientation_is_not_reported_as_ambiguous():
    section = _tabular(map_grid(_grid(_rows(NAMED))))
    assert not [c for c in section.columns if c.orientation_ambiguous], \
        "the headings settle this; nothing here is a coin flip"


def test_an_unnamed_pair_is_ambiguous_even_when_other_columns_are_named():
    """Headings on *other* columns say nothing about this pair."""
    section = _tabular(map_grid(_grid(_rows(ANONYMOUS))))

    ambiguous = {c.index for c in section.columns if c.orientation_ambiguous}
    assert ambiguous == {3, 4}, (
        "opening and receipt are named, but nothing names either of the last "
        "two, so their orientation is a guess and must be recorded as one")
    for index in (3, 4):
        column = section.columns[index]
        assert column.confidence < 0.55, \
            "a coin flip must fall below the threshold that asks for help"
