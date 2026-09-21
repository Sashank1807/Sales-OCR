"""Columns most rows leave blank, watermarks, total lines, and merged figures.

Found on `AAI PHARMA JUNE26.pdf`, where `STK VAL | MAY | APR | STK120 | EXP3M`
came out as one column holding `814 1`, marked exact. Each repair is tested on
the shape of the defect; one test reads the real file when it is present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from column_mapper import _best_flow, _decompact, _measure_from_header, map_grid
from readers.contract import GridCell, GridRow, Token
from readers.geometry import (
    GeometryConfig, recover_unbanded_columns, set_aside_oversized, split_merged_rows,
)
from schema import Cell, CellStatus, Role, RowType, SectionKind
from validator import Validator

AAI = Path(__file__).resolve().parent.parent / "JUNE" / "AAI PHARMA JUNE26.pdf"


def tok(text, x0, x1, y, height=11.0):
    return Token(text=text, x0=x0, y0=y, x1=x1, y1=y + height)


# -- sparse columns ----------------------------------------------------------


def _table_rows():
    """A title line, a header, five product rows; the last two columns are sparse."""
    rows = [[tok("TO : SOME DIVISION, A LONG ADDRESS LINE", 200, 470, 0)]]
    rows.append([tok("ITEM", 20, 60, 20), tok("OPEN", 200, 225, 20), tok("IN", 250, 265, 20),
                 tok("OUT", 275, 292, 20), tok("CLOSE", 300, 330, 20),
                 tok("MAY", 400, 418, 20), tok("APR", 430, 448, 20)])
    for i in range(5):
        y = 40 + 12 * i
        row = [tok(f"PRODUCT {i}", 20, 90, y), tok("10", 215, 225, y), tok("0", 260, 265, y),
               tok("0", 287, 292, y), tok("12", 320, 330, y)]
        if i in (1, 3):
            row.append(tok("4", 413, 418, y))
        if i in (2, 3):
            row.append(tok("7", 443, 448, y))
        rows.append(row)
    return rows


BANDS = [(20.0, 90.0), (200.0, 225.0), (250.0, 265.0), (275.0, 292.0), (300.0, 330.0)]


def test_figures_in_no_band_get_columns_of_their_own():
    recovered = recover_unbanded_columns(_table_rows(), BANDS, GeometryConfig())
    assert len(recovered) == len(BANDS) + 2
    assert recovered[-2][0] >= 400 and recovered[-2][1] <= 420
    assert recovered[-1][0] >= 428 and recovered[-1][1] <= 450


def test_a_lone_stray_figure_is_not_a_column():
    rows = _table_rows()
    rows[1][:] = [t for t in rows[1] if t.x0 < 400]     # no sparse headings
    for row in rows[2:]:
        row[:] = [t for t in row if t.x0 < 400]
    # two stray figures, far apart, one row each: neither is a column
    rows[3].append(tok("4", 413, 418, rows[3][0].y0))
    rows[5].append(tok("9", 520, 525, rows[5][0].y0))
    assert recover_unbanded_columns(rows, BANDS, GeometryConfig()) == BANDS


def test_lines_above_the_table_cannot_join_the_new_columns():
    rows = _table_rows()
    # an address line spanning the sparse columns, well above the figures
    rows.insert(0, [tok("Mobile 9321118749 Email someone@example.com", 380, 470, -40)])
    assert len(recover_unbanded_columns(rows, BANDS, GeometryConfig())) == len(BANDS) + 2


# -- a heading line is never split as two products ---------------------------


def test_a_heading_line_is_not_split_as_two_merged_products():
    def row(index, y, texts):
        return GridRow(index=index, bbox=(0, y, 500, y + 8), cells=[
            GridCell(text=t, column=c, bbox=(c * 50, y, c * 50 + 40, y + 8))
            for c, t in texts])
    rows = [row(0, 0, [(0, "ITEM"), (1, "OPEN"), (2, "CLOSE"), (3, "VAL"),
                       (4, "MAY"), (5, "APR"), (6, "STK120"), (7, "EXP")])]
    for i in range(1, 7):
        rows.append(row(i, 10 * i, [(0, f"P{i}"), (4, "1"), (5, "2"), (6, "3"), (7, "4")]))
    assert len(split_merged_rows(rows, GeometryConfig())) == len(rows)


# -- watermark ---------------------------------------------------------------


def test_a_watermark_word_is_set_aside_but_a_large_figure_is_not():
    tokens = [tok(f"W{i}", 10 * i, 10 * i + 8, 12 * i) for i in range(12)]
    tokens.append(tok("medica", 97, 499, 184, height=475))
    tokens.append(tok("12345", 97, 499, 184, height=475))
    kept, aside = set_aside_oversized(tokens, GeometryConfig().oversized_ratio)
    assert [t.text for t in aside] == ["medica"]
    assert "12345" in [t.text for t in kept]


# -- headings ----------------------------------------------------------------


@pytest.mark.parametrize("heading, flow, measure", [
    ("OPSTK", "opening", None),
    ("STK VAL", "closing", "value"),
    ("CL STK", "closing", None),
    ("OpQty", "opening", "qty"),
])
def test_stk_is_read_as_stock(heading, flow, measure):
    assert _best_flow(heading)[0] == flow
    assert _measure_from_header(_decompact(heading)) == measure


# -- total lines, empty columns, merged figures ------------------------------


def _cell(text, x):
    return {"text": str(text), "confidence": 0.99, "bbox": [x, 0, x + 40, 10]}


HEAD = ["ITEM", "PACK", "OPSTK", "PURCH", "SALE", "STOCK", "EXP"]
#: No purchases this month, as on `AAI PHARMA JUNE26.pdf`: with a blank read as
#: zero, "EXP + OPSTK - SALE = STOCK" balances exactly as well as the real
#: "OPSTK + PURCH - SALE = STOCK".
BODY = [("ALPHA", "5GM", 11, 0, 0, 11, ""), ("BETA", "1X30", 10, 0, 10, 0, ""),
        ("GAMMA", "60ML", 12, 0, 0, 12, ""), ("DELTA", "100ML", 35, 0, 8, 27, ""),
        ("EPSILON", "10TAB", 63, 0, 0, 63, ""), ("ZETA", "15GM", 8, 0, 3, 5, "")]


def _grid(extra_rows=()):
    xs = [10 + 80 * i for i in range(len(HEAD))]
    rows = [{"index": 0, "cells": [_cell(h, x) for h, x in zip(HEAD, xs)]}]
    for values in list(BODY) + list(extra_rows):
        rows.append({"index": len(rows), "cells": [_cell(v, x) for v, x in zip(values, xs)]})
    return {"page": 1, "source": "pdf_text", "rows": rows}


def _section(document):
    return next(s for s in document.sections if s.kind is SectionKind.TABULAR)


@pytest.mark.parametrize("label", [("", "Division Total"), ("End Of Report", "Total")])
def test_a_line_whose_label_ends_in_total_is_a_total(label):
    document = map_grid(_grid([(label[0], label[1], 131, 7, 18, 120, "")]))
    last = _section(document).rows[-1]
    assert last.row_type is RowType.TOTAL


def test_a_product_with_total_inside_its_name_stays_a_product():
    document = map_grid(_grid([("SKIN TOTAL CARE LOTION", "50ML", 1, 0, 0, 1, "")]))
    assert _section(document).rows[-1].row_type is RowType.DATA


def test_an_empty_column_never_takes_part_in_the_stock_equation():
    section = _section(map_grid(_grid()))
    roles = {c.header_text: c.role for c in section.columns}
    assert roles["OPSTK"] is Role.OPENING_QTY
    assert roles["STOCK"] is Role.CLOSING_QTY
    assert roles["EXP"] is Role.UNKNOWN


def test_several_figures_in_one_cell_are_flagged_even_from_a_text_layer():
    document = map_grid(_grid([("ETA", "15GM", 8, 0, 3, "5 678", "")]))
    Validator().validate(document)
    cell = _section(document).rows[-1].cell_at(5)
    assert cell.status is CellStatus.FLAGGED
    assert "several_figures_in_one_cell" in cell.reasons


def test_figures_inside_an_item_name_are_not_merged_columns():
    document = map_grid(_grid([("ZEBOR 20 15", "15GM", 8, 0, 3, 5, "")]))
    Validator().validate(document)
    cell = _section(document).rows[-1].cell_at(0)
    assert "several_figures_in_one_cell" not in cell.reasons


@pytest.mark.parametrize("text, several", [
    ("814 1", True), ("-2121 0 -482", True), ("28710 S 21547 E 0", True),
    ("60:0", False), ("1X15 GM", False), ("1,234.50", False), ("12", False),
])
def test_what_counts_as_several_figures(text, several):
    assert Cell(raw_text=text, column_index=0).holds_several_figures is several


# -- the real file -----------------------------------------------------------


@pytest.mark.skipif(not AAI.is_file(), reason="JUNE corpus not present")
def test_aai_pharma_reads_every_column_apart():
    from pipeline import process_file
    page = process_file(AAI).pages[0]
    section = _section(page.document)
    headings = [c.header_text for c in section.columns]
    # EXP3M holds a single figure on the whole page, too little to be told
    # apart from a stray; its heading joins the nearest column.
    assert headings[-4:-1] == ["STK VAL", "MAY", "APR"]
    assert headings[-1].startswith("STK120")
    roles = {c.header_text: c.role for c in section.columns}
    assert roles["OPSTK"] is Role.OPENING_QTY and roles["STOCK"] is Role.CLOSING_QTY
    assert not any(c.holds_several_figures for r in section.data_rows for c in r.cells)
    assert "medica" not in " ".join(r.text for r in section.rows)
    assert sum(1 for r in section.rows if r.row_type is RowType.TOTAL) == 2


def test_a_heading_keeps_its_flow_when_only_the_guessed_measure_disagrees():
    # `1000411296.jpg`: `Opening` printed with two decimals beside columns
    # printed with three, so its measure was guessed as value; arithmetic,
    # which cannot tell opening from receipt, then took the role away.
    head = ["Description", "Opening", "In", "Out", "Balance"]
    body = [("A", "51.00", "0.000", "51.000", "0.000"), ("B", "61.00", "0.000", "14.000", "47.000"),
            ("C", "61.00", "0.000", "0.000", "61.000"), ("D", "0.00", "30.000", "9.000", "21.000"),
            ("E", "0.00", "30.000", "0.000", "30.000"), ("F", "15.00", "0.000", "0.000", "15.000"),
            ("G", "20.00", "10.000", "12.000", "18.000")]
    xs = [10 + 80 * i for i in range(len(head))]
    rows = [{"index": 0, "cells": [_cell(h, x) for h, x in zip(head, xs)]}]
    for values in body:
        rows.append({"index": len(rows), "cells": [_cell(v, x) for v, x in zip(values, xs)]})
    section = _section(map_grid({"page": 1, "source": "ocr", "rows": rows}))
    roles = {c.header_text: c.role for c in section.columns}
    assert roles["Opening"] is Role.OPENING_QTY
    assert roles["In"] is Role.RECEIPT_QTY


@pytest.mark.parametrize("heading, flow", [
    ("EXPIRY STOCK", None),          # expired stock is not a term of the equation
    ("OPENING STOCK", "opening"),
    ("TRANSIT STOCK", "closing"),    # "stock" alone never makes it an opening column
    ("ISSLE QTY.", "issue"),         # one letter misread in a long word
    ("CLISING ETY.", "closing"),
    ("SAFE", None),                  # short words never drift
    ("BATCH", None),
])
def test_headings_read_through_misreads_but_not_through_shared_words(heading, flow):
    assert _best_flow(heading)[0] == flow


def test_text_in_a_balancing_row_is_flagged_not_verified():
    # OCR read `0` as `a`; the row balances with it counted as zero, but the
    # sum cannot confirm a cell that is not a figure.
    document = map_grid(_grid([("ETA", "15GM", 8, 0, 3, 5, "")]))
    document.sections[0].rows[-1].cells[3].raw_text = "a"
    rows = [r for s in document.sections for r in s.data_rows]
    rows[-1].cells[3].raw_text = "a"
    rows[-1].cells[3].value = None
    Validator().validate(document)
    cell = rows[-1].cells[3]
    assert cell.status is CellStatus.FLAGGED
    assert "not_a_figure" in cell.reasons


def test_a_running_total_across_pages_is_not_a_silent_error():
    from decimal import Decimal
    from benchmarks.benchmark import _probe_silent_errors
    grid = _grid([("TOTAL", "", 150, 2, 21, 131, "")])
    section = _section(map_grid(grid))
    Validator().validate(map_grid(grid))
    opening = next(c.role for c in section.columns if c.header_text == "OPSTK")
    # the rows here sum to 139 under a printed 150: 11 came from the page before
    _, reconciled, _ = _probe_silent_errors(section, "p2", {opening: Decimal(11)})
    _, without, _ = _probe_silent_errors(section, "p2")
    assert reconciled == without + 1


@pytest.mark.parametrize("heading, flow", [
    ("Opst Qty", "opening"), ("Clst", "closing"),
    ("Cost", None), ("Best", None), ("Last", None),       # words that merely end in "st"
    ("Purc Free", None), ("Sale Free", None),             # free goods are not the main flows
    ("Purc Qty", "receipt"), ("Sale Qty", "issue"),
])
def test_glued_stock_abbreviations_and_free_goods(heading, flow):
    assert _best_flow(heading)[0] == flow


def test_a_statement_listing_products_with_no_movement_is_still_a_table():
    # `pdf&rendition=1-3.pdf`: most products print a name and pack, some a
    # stray `0` in the last column, a few a full row of figures.
    head = ["Product name", "Unit", "Op", "Purc", "Sale", "WSale", "Apr", "Mar", "Cl", "Val"]
    full = lambda n: (f"FULL {n}", "10 TAB", 91, 210, 167, 50, 150, 146, 134, 2188)
    rows = []
    for n in range(4):
        rows += [full(n)] + [(f"ITEM {n}{k}", "10 TAB") for k in range(3)] + [(f"ZERO {n}", "10 CAP") + ("",) * 7 + ("0",)]
    xs = [10 + 80 * i for i in range(len(head))]
    grid = [{"index": 0, "cells": [_cell(h, x) for h, x in zip(head, xs)]}]
    for values in rows:
        values = tuple(values) + ("",) * (len(head) - len(values))
        grid.append({"index": len(grid), "cells": [_cell(v, x) for v, x in zip(values, xs)]})
    document = map_grid({"page": 1, "source": "pdf_text", "rows": grid})
    assert any(s.kind is SectionKind.TABULAR for s in document.sections)


def test_a_total_printed_once_for_every_page_reconciles():
    # A report that totals only on its last page totals every page, not that
    # page: 37 of 212 printed totals in the MAY corpus are this shape.
    from validator import validate_pages
    first = map_grid(_grid())
    last = map_grid(_grid([("TOTAL", "", 139 + 139, 0, 19 + 19, 120 + 120, "")]))
    reports = validate_pages([first, last])
    total_row = _section(last).rows[-1]
    opening = next(c.index for c in _section(last).columns if c.header_text == "OPSTK")
    # a deterministic cell keeps `exact` (s5); the match is on its record
    assert "total_of_every_page" in total_row.cell_at(opening).reasons
    assert total_row.cell_at(opening).status is CellStatus.EXACT
    assert any(f.check == "total_cumulative" for f in reports[1].findings)


def test_a_band_whose_heading_names_two_columns_is_split_by_the_heading():
    # `HETROSTOCK05-2026.pdf`: `QTY.` and `VALUE` set so close that a wide
    # value starts left of where a narrow quantity ends, so no gutter exists.
    from readers.geometry import GeometryConfig, cluster_rows, split_bands_by_headings
    def tok(text, x0, x1, y):
        return Token(text=text, x0=x0, y0=y, x1=x1, y1=y + 9.0)
    rows = [[tok("ITEM", 16, 40, 0), tok("OPENING", 176, 215, 0)],
            [tok("QTY.", 170, 186, 10), tok("VALUE", 196, 226, 10)]]
    figures = [("7", 174, 179, "1497.41", 191, 224), ("24", 171, 181, "5133.98", 192, 226),
               ("0", 186, 191, "0.00", 209, 227), ("149", 164, 180, "9247.24", 191, 225)]
    for n, (q, qa, qb, v, va, vb) in enumerate(figures):
        y = 22 + 11 * n
        rows.append([tok(f"ITEM{n}", 16, 60, y), tok(q, qa, qb, y), tok(v, va, vb, y),
                     tok(str(n), 300, 310, y)])
    bands = [(16.0, 60.0), (164.0, 227.0), (300.0, 310.0)]
    split = split_bands_by_headings(rows, bands, GeometryConfig())
    assert len(split) == 4
    assert split[1][1] <= 190 and split[2][0] >= 190


def test_a_heading_of_one_word_over_one_figure_is_left_alone():
    from readers.geometry import GeometryConfig, split_bands_by_headings
    def tok(text, x0, x1, y):
        return Token(text=text, x0=x0, y0=y, x1=x1, y1=y + 9.0)
    rows = [[tok("ITEM", 16, 40, 0), tok("CLOSING", 176, 215, 0)]]
    for n in range(5):
        y = 12 + 11 * n
        rows.append([tok(f"ITEM{n}", 16, 60, y), tok(str(10 + n), 180, 195, y),
                     tok(str(n), 300, 310, y), tok(str(n + 1), 340, 350, y)])
    bands = [(16.0, 60.0), (176.0, 215.0), (300.0, 310.0), (340.0, 350.0)]
    assert split_bands_by_headings(rows, bands, GeometryConfig()) == bands
