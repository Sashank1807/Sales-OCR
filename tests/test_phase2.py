"""Free goods, headings anchoring the stock equation, group labels, and photos.

The stock table used here is the user's own transcription of a photographed
KETAKI PHARMACEUTICALS statement (`1000517655.jpg`), supplied as an example of
the output format they wanted. Its figures balance as

    OB + PUR + FR(purchase) - SAL - FR(sale) = CB

which is what makes it a good fixture for free-quantity columns.
"""

from __future__ import annotations

import pytest

from column_mapper import map_grid
from readers.contract import Token
from readers.geometry import GeometryConfig, build_grid, straighten_page
from schema import CellStatus, Role, RowType, SectionKind
from validator import Validator

HEADER = ["SNO", "ITEM DESCRIPTION", "PACK", "OB", "PUR", "FR", "SAL", "FR", "CB", "RATE", "VALUE"]

#: sno, item, pack, ob, pur, fr_purchase, sal, fr_sale, cb, rate, value
KETAKI = [
    (1, "AD-100 CAP", "10S", 12, 40, 0, 30, 0, 22, "87.91", "1934.02"),
    (2, "AD-10 SACHETS", "10PCS", 41, 20, 0, 61, 0, 0, "93.20", "0.00"),
    (3, "BILASET 20MG TAB", "10S", 74, 0, 0, 30, 9, 35, "54.64", "1912.40"),
    (4, "BILASET M TAB", "10S", 158, 0, 0, 53, 15, 90, "70.07", "6306.30"),
    (5, "BILASET 40MG TAB", "10S", 65, 0, 0, 16, 4, 45, "109.23", "4915.35"),
    (6, "ETORO 90", "10S", 70, 20, 5, 0, 0, 95, "84.86", "8061.70"),
    (7, "ETORO TH", "10S", 26, 10, 3, 0, 0, 39, "153.60", "5990.40"),
    (8, "GENXVAST 10 TAB", "10'S", 20, 0, 0, 0, 0, 20, "13.35", "267.00"),
    (9, "GENXVAST-20MG TAB", "10'S", 16, 0, 0, 0, 0, 16, "19.13", "306.08"),
    (10, "GENXVAST-F TAB", "10S", 10, 0, 0, 0, 0, 10, "29.89", "298.90"),
    (11, "HERAFT SUSP", "150ML", 49, 50, 20, 30, 15, 74, "90.00", "6660.00"),
    (12, "ITBOR 100MG CAPS", "10S", 211, 0, 0, 30, 12, 169, "59.93", "10128.17"),
    (13, "ITBOR 200 MG CAPS", "10S", 86, 200, 80, 107, 42, 217, "117.12", "25415.04"),
    (14, "LAZINE 5MG TAB", "10S", 26, 0, 0, 0, 0, 26, "36.64", "952.64"),
    (15, "LAZINE M TAB", "10", 39, 0, 0, 30, 9, 0, "61.07", "0.00"),
    (16, "LAZ-500 TAB", "6S", 99, 0, 0, 30, 6, 63, "92.57", "5831.91"),
    (17, "LULIBOR CREAM", "30GM", 60, 0, 0, 20, 6, 34, "160.71", "5464.14"),
    (18, "LULIBOR LOTION", "30ML", 52, 0, 0, 32, 10, 10, "186.43", "1864.30"),
    (19, "LULIBOR CREAM", "15GM", 31, 100, 40, 24, 7, 140, "80.36", "11250.40"),
    (20, "LINQWIN 600MG TAB", "10S", 93, 0, 0, 8, 4, 81, "260.94", "21136.14"),
    (21, "MOISTE CREAM", "50GM", 50, 0, 0, 20, 4, 26, "92.59", "2407.34"),
]

#: Misreads of the kind the photo produced: a free quantity read as 300, one
#: never read, one read as 8 for 80, a closing stock off by a digit.
MISREADS = {7: (5, None), 8: (5, 300), 13: (5, 8), 19: (5, 4), 21: (8, 62)}


def _cell(text, x):
    return {"text": str(text), "confidence": 0.99, "bbox": [x, 0, x + 40, 10]}


def _grid(rows, header=HEADER, label=None, misreads=None):
    xs = [10 + 80 * i for i in range(len(HEADER))]
    grid_rows = [{"index": 0, "cells": [_cell(h, x) for h, x in zip(header, xs)]}]
    if label:
        grid_rows.append({"index": 1, "cells": [_cell(t, xs[i]) if t else _cell("", xs[i])
                                                 for i, t in enumerate(label)]})
    for n, values in enumerate(rows):
        values = list(values)
        if misreads and values[0] in misreads:
            position, wrong = misreads[values[0]]
            values[position] = "" if wrong is None else wrong
        grid_rows.append({"index": len(grid_rows),
                          "cells": [_cell(v, x) for v, x in zip(values, xs)]})
    return {"page": 1, "source": "ocr", "rows": grid_rows}


def _table(document):
    return next(s for s in document.sections if s.kind is SectionKind.TABULAR)


def _column(section, heading, occurrence=1):
    return [c for c in section.columns if c.header_text == heading][occurrence - 1].index


# -- free goods on both sides ------------------------------------------------


def test_free_goods_on_both_sides_balance_the_stock_equation():
    document = map_grid(_grid(KETAKI))
    section = _table(document)
    fr_purchase, fr_sale = _column(section, "FR", 1), _column(section, "FR", 2)
    assert sorted(section.adjustments) == sorted([(fr_purchase, 1, "qty"), (fr_sale, -1, "qty")])

    report = Validator().validate(document)
    equation = next(i for i in report.invariants if i.name == "row_equation_qty")
    assert equation.adopted
    for row in section.data_rows:
        for index in (_column(section, "OB"), fr_purchase, fr_sale, _column(section, "CB")):
            assert row.cell_at(index).status is CellStatus.VERIFIED


def test_misread_rows_are_flagged_and_never_verified():
    """The anchored equation confirms the rows that balance and flags the rest."""
    document = map_grid(_grid(KETAKI, misreads=MISREADS))
    section = _table(document)
    report = Validator().validate(document)
    assert next(i for i in report.invariants if i.name == "row_equation_qty").adopted

    positions = {3: "OB", 4: "PUR", 6: "SAL", 8: "CB"}
    for row, source in zip(section.data_rows, KETAKI):
        if source[0] not in MISREADS:
            continue
        position, _ = MISREADS[source[0]]
        index = (_column(section, "FR", 1) if position == 5
                 else _column(section, positions[position]))
        assert row.cell_at(index).status is not CellStatus.VERIFIED, source[1]
        assert row.cell_at(_column(section, "CB")).status is CellStatus.FLAGGED, source[1]


def test_without_headings_to_anchor_it_the_usual_threshold_still_applies():
    """Two-thirds agreement is not enough when arithmetic had to find the columns."""
    blank = [""] * len(HEADER)
    heavy = {**MISREADS, 3: (5, 1), 4: (5, 1), 12: (5, 1)}
    document = map_grid(_grid(KETAKI, header=blank, misreads=heavy))
    report = Validator().validate(document)
    equation = next((i for i in report.invariants if i.name == "row_equation_qty"), None)
    assert equation is None or not equation.adopted


# -- group labels and separated headings ------------------------------------


def test_a_group_label_under_the_header_titles_its_rows():
    label = ["", "HETERO GENX PHARMA LTD", "(GEN"] + [""] * (len(HEADER) - 3)
    document = map_grid(_grid(KETAKI, label=label))
    section = _table(document)
    assert not any("GEN" in c.header_text for c in section.columns)
    titles = [r for r in section.rows if r.row_type is RowType.SECTION_TITLE]
    assert titles and "HETERO GENX PHARMA LTD" in titles[0].text


def test_a_heading_one_band_away_from_its_figures_is_put_back():
    """`OB` in a band of its own, beside a band of figures with no heading."""
    xs = [10 + 80 * i for i in range(len(HEADER) + 1)]
    header = HEADER[:3] + ["OB", ""] + HEADER[4:]
    rows = [{"index": 0, "cells": [_cell(h, x) for h, x in zip(header, xs)]}]
    for n, values in enumerate(KETAKI, start=1):
        values = [str(v) for v in values]
        shifted = values[:3] + ["", values[3]] + values[4:]
        rows.append({"index": n, "cells": [_cell(v, x) for v, x in zip(shifted, xs)]})
    document = map_grid({"page": 1, "source": "ocr", "rows": rows})
    section = _table(document)
    assert section.columns[4].header_text == "OB"
    assert section.columns[4].role is Role.OPENING_QTY
    assert section.columns[3].header_text == ""


# -- photographed pages ------------------------------------------------------


def _sloping_tokens(slope_per_px: float, rows: int = 14, columns: int = 9,
                    pitch: float = 40.0, height: float = 30.0) -> list[Token]:
    tokens = []
    for r in range(rows):
        for c in range(columns):
            x = 50 + 250 * c
            y = 100 + pitch * r + slope_per_px * x
            tokens.append(Token(text=f"{r}.{c}", x0=x, y0=y, x1=x + 60, y1=y + height,
                                confidence=0.99, index=len(tokens)))
    return tokens


def test_sloping_rows_are_grouped_as_printed_and_keep_their_positions():
    """A drift of more than a row pitch across the page, as on a tilted photo."""
    tokens = _sloping_tokens(slope_per_px=0.03)          # 60 px over 2000 px, pitch 40
    flat = build_grid(tokens, page=1, source="ocr",
                      config=GeometryConfig(straighten_rows=False))
    level = build_grid(tokens, page=1, source="ocr")
    assert any(len({c.text.split(".")[0] for c in row.cells}) > 1 for row in flat.rows)
    assert all(len({c.text.split(".")[0] for c in row.cells}) == 1 for row in level.rows)
    by_index = {t.index: t for t in tokens}
    for row in level.rows:
        for cell in row.cells:
            (token,) = [by_index[i] for i in cell.token_ids]
            assert cell.bbox == token.bbox


def test_a_level_page_is_left_exactly_as_read():
    assert straighten_page(_sloping_tokens(slope_per_px=0.0)) is None


def test_a_text_layer_is_never_levelled():
    tokens = _sloping_tokens(slope_per_px=0.03)
    grid = build_grid(tokens, page=1, source="pdf_text")
    assert not any("levelled" in note for note in grid.notes)


#: Seven misreads on rows with movement: the equation holds on 10 of 17 (59%) -
#: above a majority, below the usual 70%.
SEVEN = {1: (8, 23), 3: (8, 36), 5: (8, 44), 11: (8, 75), 12: (8, 168), 16: (8, 64), 20: (8, 80)}


def _equation(document):
    return next(i for i in Validator().validate(document).invariants
                if i.name == "row_equation_qty")


def test_headings_let_a_majority_establish_the_equation():
    document = map_grid(_grid(KETAKI, misreads=SEVEN))
    equation = _equation(document)
    assert (equation.agreeing_rows, equation.informative_rows) == (10, 17)
    assert equation.adopted
    section = _table(document)
    closing = _column(section, "CB")
    for row, source in zip(section.data_rows, KETAKI):
        expected = CellStatus.FLAGGED if source[0] in SEVEN else CellStatus.VERIFIED
        assert row.cell_at(closing).status is expected, source[1]


def test_the_same_majority_is_not_enough_when_arithmetic_named_the_columns():
    from schema import MappingMethod
    document = map_grid(_grid(KETAKI, misreads=SEVEN))
    section = _table(document)
    for column in section.columns:
        if column.role in (Role.OPENING_QTY, Role.RECEIPT_QTY, Role.ISSUE_QTY, Role.CLOSING_QTY):
            column.method = MappingMethod.ARITHMETIC
    equation = _equation(document)
    assert (equation.agreeing_rows, equation.informative_rows) == (10, 17)
    assert not equation.adopted


# -- report details ------------------------------------------------------------


@pytest.mark.parametrize("line, expected", [
    ("From : 01/Aug/2026 To 31/Aug/2026", ("01/Aug/2026", "31/Aug/2026")),
    ("FROM DATE:01-06-2026 T0:30-06-2026", ("01-06-2026", "30-06-2026")),   # OCR's T0
    ("Group Wise Sales (From 01/06/2026 UpTo 30/06/2026)", ("01/06/2026", "30/06/2026")),
    ("Stock And Sales : 01/04/2026-30/06/2026", ("01/04/2026", "30/06/2026")),
    ("Page No.:1of1 Run Date:23/06/2026 Time:10:21AM ITEM 01/06/2028", None),
    ("Invoice 12/05/2026 Due 30/05/2026", None),
])
def test_two_dates_are_a_period_only_when_printed_as_a_range(line, expected):
    from column_mapper import _period_in
    assert _period_in(line) == expected


def test_report_details_are_read_from_a_heading_line_above_the_table():
    from exporter import build_report
    from pipeline import PageResult, PipelineResult
    from readers.router import PageKind, PageRef
    from pathlib import Path

    preamble = [["KETAKI PHARMACEUTICALS"],
                ["SALIPUR,CUTTACK ODISHA GST:21ABBPM2256L1ZV"],
                ["STOCK REPORT", "", "FROM DATE:01-06-2026 T0:30-06-2026"]]
    grid = _grid(KETAKI)
    grid["rows"] = ([{"index": i, "cells": [_cell(t, 10 + 300 * j) for j, t in enumerate(r)]}
                     for i, r in enumerate(preamble)]
                    + [{**row, "index": row["index"] + len(preamble)} for row in grid["rows"]])
    document = map_grid(grid)

    result = PipelineResult(path=Path("ketaki.jpg"))
    result.pages.append(PageResult(ref=PageRef(path=Path("ketaki.jpg"), kind=PageKind.IMAGE),
                                   document=document))
    report = build_report(result)
    assert report["report_entity"] == "KETAKI PHARMACEUTICALS"
    assert report["location"] == "SALIPUR,CUTTACK ODISHA"
    assert report["report_title"] == "STOCK REPORT"
    assert report["document_type"] == "STOCK_REPORT"
    assert report["report_period"] == {"from_date": "01-06-2026", "to_date": "30-06-2026"}


@pytest.mark.parametrize("title, expected", [
    ("Stock and Sale Report", "STOCK_AND_SALES_REPORT"),
    ("STOCK SUMMARY", "STOCK_REPORT"),
    ("Group Wise Sales", "SALES_REPORT"),
    (None, None),
])
def test_document_type_comes_from_the_reports_own_heading(title, expected):
    from exporter import _document_type
    assert _document_type(title) == expected


# -- structured report: row status, split headings, screen text --------------


def _report(document, name="ketaki.jpg"):
    from pathlib import Path
    from exporter import build_report
    from pipeline import PageResult, PipelineResult
    from readers.router import PageKind, PageRef
    result = PipelineResult(path=Path(name))
    result.pages.append(PageResult(ref=PageRef(path=Path(name), kind=PageKind.IMAGE),
                                   document=document))
    return build_report(result)


def _validated(grid):
    document = map_grid(grid)
    Validator().validate(document)
    return document


def _report_rows(report):
    return [r for t in report["tables"] for g in t["groups"] for r in g["rows"]]


def test_a_balanced_row_is_verified_although_its_item_name_cannot_be():
    report = _report(_validated(_grid(KETAKI, misreads=MISREADS)))
    rows = {r["sno"]: r for r in _report_rows(report)}
    assert rows[1]["status"] == "verified"
    assert rows[1]["needs_review"] == []
    assert set(rows[1]["unchecked_text"]) == {"sno", "item_description", "pack"}
    for misread in MISREADS:
        assert rows[misread]["status"] == "flagged"
    assert report["summary"]["rows_by_status"]["verified"] == len(KETAKI) - len(MISREADS)


def test_a_screens_button_bar_is_kept_apart_from_the_products():
    buttons = ["", "SAVEPDF", "OPEN TOP", "FIND", "PRINT", "", "CAL", "END", "SAVEXL",
               "SAVEDO", "EMAIL EXIT"]
    grid = _grid(KETAKI)
    xs = [10 + 80 * i for i in range(len(HEADER))]
    grid["rows"].append({"index": len(grid["rows"]),
                         "cells": [_cell(t, x) for t, x in zip(buttons, xs)]})
    report = _report(_validated(grid))
    table = report["tables"][0]
    assert len(_report_rows(report)) == len(KETAKI)
    assert [line["item_description"] for line in table["other_lines"]] == ["SAVEPDF"]
    assert table["other_lines"][0]["status"] == "flagged"


def test_a_product_with_no_movement_is_not_screen_text():
    grid = _grid(KETAKI + [(22, "NEW ITEM", "10S", "", "", "", "", "", "", "", "")])
    report = _report(_validated(grid))
    assert report["tables"][0]["other_lines"] == []
    assert len(_report_rows(report)) == len(KETAKI) + 1


def test_a_heading_read_across_two_columns_is_shared_between_them():
    xs = [10 + 80 * i for i in range(len(HEADER))]
    grid = _grid(KETAKI)
    header = [_cell(h, x) for h, x in zip(HEADER, xs)]
    header[0] = _cell("", xs[0])
    # one piece of text starting over the serial numbers (x 10-50) and running
    # over the items (x 90-130), stopping short of the pack column (x 170)
    header[1] = {"text": "SNO ITEM DESCRIPTION", "confidence": 0.99, "bbox": [40, 0, 168, 10]}
    grid["rows"][0]["cells"] = header
    section = _table(map_grid(grid))
    assert [c.header_text for c in section.columns[:2]] == ["SNO", "ITEM DESCRIPTION"]
    assert section.columns[1].role is Role.ITEM_DESCRIPTION


def test_a_heading_that_does_not_reach_the_unheaded_column_stays_whole():
    xs = [10 + 80 * i for i in range(len(HEADER))]
    grid = _grid(KETAKI)
    header = [_cell(h, x) for h, x in zip(HEADER, xs)]
    header[0] = _cell("", xs[0])
    header[1] = {"text": "SNO ITEM DESCRIPTION", "confidence": 0.99, "bbox": [90, 0, 330, 10]}
    grid["rows"][0]["cells"] = header
    section = _table(map_grid(grid))
    assert [c.header_text for c in section.columns[:2]] == ["", "SNO ITEM DESCRIPTION"]


@pytest.mark.parametrize("preamble, entity, location", [
    # a window caption above the letterhead
    (["Main.Report", "KETAKI PHARMACEUTICALS", "SALIPUR,CUTTACK ODISHA GST:21ABBPM2256L1ZV"],
     "KETAKI PHARMACEUTICALS", "SALIPUR,CUTTACK ODISHA"),
    # a PDF viewer's toolbar above it, and its buttons run onto the name's line
    (["E-Sign Sign in", "Find text or tools Q 8", "SHRI RAM MEDICAL HALL Share Ask",
      "MAIN ROAD ORAI ORAI JALAUN", "Phone : 05162-253251"],
     "SHRI RAM MEDICAL HALL", "MAIN ROAD ORAI ORAI JALAUN"),
    # nothing that looks like a business name: say nothing
    (["Main.Report", "Find text or tools"], None, None),
])
def test_the_company_is_the_line_that_reads_as_a_business_name(preamble, entity, location):
    grid = _grid(KETAKI)
    grid["rows"] = ([{"index": i, "cells": [_cell(t, 10)]} for i, t in enumerate(preamble)]
                    + [{**row, "index": row["index"] + len(preamble)} for row in grid["rows"]])
    report = _report(map_grid(grid))
    assert report["report_entity"] == entity
    assert report["location"] == location


def test_a_title_line_naming_few_columns_is_never_split():
    # DOC-20260703-WA0021.pdf p14: a company line and a division name taken
    # for the header, naming 2 of 11 columns. The division name reaches over
    # the unheaded pack column but is not two headings.
    xs = [10 + 80 * i for i in range(len(HEADER))]
    grid = _grid(KETAKI)
    header = [_cell("", x) for x in xs]
    header[0] = _cell("HETEROHEALTHCARELTD.ALL", xs[0])
    header[2] = {"text": "HETERO DERMA GLOW", "confidence": 0.99, "bbox": [120, 0, 248, 10]}
    grid["rows"][0]["cells"] = header
    section = _table(map_grid(grid))
    assert [c.header_text for c in section.columns[:3]] == [
        "HETEROHEALTHCARELTD.ALL", "", "HETERO DERMA GLOW"]


def test_a_heading_joined_from_several_pieces_is_never_split():
    xs = [10 + 80 * i for i in range(len(HEADER))]
    grid = _grid(KETAKI)
    header = [_cell(h, x) for h, x in zip(HEADER, xs)]
    header[0] = _cell("", xs[0])
    header[1] = {"text": "SNO ITEM DESCRIPTION", "confidence": 0.99, "bbox": [40, 0, 168, 10],
                 "token_ids": [4, 5]}
    grid["rows"][0]["cells"] = header
    section = _table(map_grid(grid))
    assert [c.header_text for c in section.columns[:2]] == ["", "SNO ITEM DESCRIPTION"]


def test_a_heading_spanning_three_columns_is_not_divided_between_two():
    xs = [10 + 80 * i for i in range(len(HEADER))]
    grid = _grid(KETAKI)
    header = [_cell(h, x) for h, x in zip(HEADER, xs)]
    header[0] = _cell("", xs[0])
    # reaches over the serial numbers, the items and the pack column
    header[1] = {"text": "SNO ITEM DESCRIPTION PACK", "confidence": 0.99, "bbox": [10, 0, 250, 10]}
    header[2] = _cell("", xs[2])
    grid["rows"][0]["cells"] = header
    section = _table(map_grid(grid))
    assert section.columns[0].header_text == ""
