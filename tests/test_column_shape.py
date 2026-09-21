"""Columns the header never named, and figures the parser cannot reduce.

Both guarantees here were defects found on held-out documents:

* Every cell of two columns on one spreadsheet was flagged as corruption -
  194 of them, all ``exact`` values read straight out of the file - because
  the header named 14 columns and the rows filled 16. A column that nearly
  every row populates is one the header failed to *name*; only a column one
  or two stray rows reach is a ragged row. The check could not tell the two
  apart.

* One ERP prints stock as ``units:free`` - ``60:0``, ``18:0``. The number
  parser cannot reduce that to a single value, so those cells counted as
  prose, and a row made of them scored as a *header*: it split its table in
  two and the second half took its column names from a row of stock values.
"""

from __future__ import annotations

from column_mapper import map_grid
from schema import Cell, CellStatus, RowType
from validator import validate_document


def _grid(rows, source="pdf_text"):
    return {"page": 1, "source": source,
            "rows": [{"index": i, "cells": r} for i, r in enumerate(rows)]}


HEADER = ["ITEM", "OPENING", "RECEIPT", "ISSUE", "CLOSING"]


def _stock_row(n):
    opening, receipt, issue = 100 * n, 50, 30
    return [f"ITEM {n}", str(opening), str(receipt), str(issue),
            str(opening + receipt - issue)]


def _reasons(document):
    return [reason
            for section in document.sections
            for row in section.rows
            for cell in row.cells
            for reason in cell.reasons]


# ---------------------------------------------------------------------------
# A column the header did not name
# ---------------------------------------------------------------------------


def test_a_column_every_row_fills_is_not_flagged_as_overflow():
    """The header names five columns; all eight rows carry a sixth.

    That sixth column is real - the header simply has no word for it. Its
    cells came from a deterministic source and are not in doubt.
    """
    rows = [HEADER] + [_stock_row(n) + [f"BATCH{n}"] for n in range(1, 9)]
    document = map_grid(_grid(rows))
    section = document.sections[0]
    report = validate_document(document)

    assert section.unheaded_columns == [5]
    assert "row_shape_overflow" not in _reasons(document)

    reported = [f for f in report.findings
                if f.check == "row_shape" and 5 in (f.column_indices or [])]
    assert reported, "an unnamed column must still be reported, just not flagged"
    assert reported[0].status is CellStatus.UNCHECKED


def test_a_column_a_single_row_reaches_is_still_flagged():
    """The other half of the distinction, and the reason it stays live.

    If any trailing column counted as a column, nothing could ever overflow
    and the check would quietly become vacuous.
    """
    rows = [HEADER] + [_stock_row(n) for n in range(1, 9)]
    rows[3] = rows[3] + ["STRAY"]
    document = map_grid(_grid(rows))
    section = document.sections[0]
    report = validate_document(document)

    assert section.unheaded_columns == []
    assert "row_shape_overflow" in _reasons(document)
    assert any(f.check == "row_shape" and f.status is CellStatus.FLAGGED
               for f in report.findings)


# ---------------------------------------------------------------------------
# Figures the parser cannot reduce to one number
# ---------------------------------------------------------------------------


def test_a_compound_quantity_is_recognised_but_never_parsed():
    """Recognised as a figure; deliberately left unparsed.

    Deciding which half of ``60:0`` is the stock is the document's own
    convention. Guessing it would be exactly the silent error the system
    exists to prevent, so the value stays ``None``.
    """
    compound = Cell(raw_text="60:0", column_index=0)
    assert compound.value is None
    assert compound.is_compound_quantity
    assert compound.looks_quantitative

    plain = Cell(raw_text="60", column_index=0)
    assert plain.looks_quantitative and not plain.is_compound_quantity

    pack = Cell(raw_text="1X10TAB", column_index=0)
    assert not pack.looks_quantitative


def test_a_row_of_compound_quantities_is_not_mistaken_for_a_header():
    """A row of stock must not be read as a row of column names."""
    header = ["ITEM", "PACK", "OPENING", "RECEIPT", "ISSUE", "CLOSING"]
    rows = [header]
    for n in range(1, 5):
        rows.append([f"ITEM {n}", "10", "0", "0", "0", "0"])
    rows.append(["LAZ 500MG", "1*6", "18:0", "0", "1:0", "17:0"])
    for n in range(5, 10):
        rows.append([f"ITEM {n}", "10", "0", "0", "0", "0"])

    document = map_grid(_grid(rows))

    assert len(document.sections) == 1, \
        "the compound row must not start a second section"
    compound = [r for s in document.sections for r in s.rows
                if r.cells and r.cells[0].raw_text == "LAZ 500MG"]
    assert compound, "the compound row must survive as a row of the table"
    assert compound[0].row_type is RowType.DATA
