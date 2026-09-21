"""Reader-layer tests: the grid contract, the geometry, and the router.

The three repairs the reader layer owns each get a test built from the shape of
the real defect rather than from a real file, so they run without the source
documents present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from readers.contract import Grid, GridCell, GridRow, Token
from readers.geometry import (
    GeometryConfig, assign_columns, build_grid, cluster_rows, detect_column_bands,
    merge_wrapped_rows, split_merged_rows,
)
from readers.router import PageKind, RouterConfig, classify_file

CORPUS = Path("D:/OCR_testing/SS")


def tok(text, x0, y, width=None, conf=1.0):
    width = width if width is not None else max(6.0, len(text) * 5.0)
    return Token(text=text, x0=x0, y0=y, x1=x0 + width, y1=y + 8.0, confidence=conf)


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_grid_emits_what_stage_a_consumes():
    """The reader output must load straight into Stage A without adaptation."""
    from schema import load_grid

    grid = Grid(page=2, source="pdf_text", origin="x.pdf",
                rows=[GridRow(index=0, cells=[
                    GridCell(text="ITEM", column=0, bbox=(0, 0, 40, 8), confidence=1.0),
                    GridCell(text="10", column=2, bbox=(80, 0, 95, 8), confidence=1.0),
                ])],
                tokens=[Token("ITEM", 0, 0, 40, 8), Token("10", 80, 0, 95, 8)])

    rows, tokens, page, source = load_grid(grid.to_dict())
    assert page == 2 and source.value == "pdf_text"
    assert [c.column_index for c in rows[0].cells] == [0, 2]
    assert rows[0].cells[0].raw_text == "ITEM"
    assert rows[0].cells[1].provenance.bbox == (80, 0, 95, 8)
    assert len(tokens) == 2


def test_source_must_be_one_of_the_three():
    with pytest.raises(ValueError):
        Grid(source="magic")


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def test_rows_cluster_by_vertical_position():
    tokens = [tok("A", 0, 100), tok("B", 60, 101), tok("C", 0, 130), tok("D", 60, 129)]
    rows = cluster_rows(tokens)
    assert len(rows) == 2
    assert [t.text for t in rows[0]] == ["A", "B"]


def test_scrambled_reading_order_reconstructs_identically():
    """Khushi's text extraction comes out of order.

    Reconstruction is driven by coordinates, so the order a reader hands tokens
    over in cannot change the result.
    """
    tokens = [tok("ITEM", 0, 100), tok("10", 100, 100), tok("20", 160, 100),
              tok("NEXT", 0, 120), tok("30", 100, 120), tok("40", 160, 120)]
    forward = build_grid(list(tokens), 1, "pdf_text")
    shuffled = build_grid(list(reversed(tokens)), 1, "pdf_text")

    assert forward.to_dict()["rows"] == shuffled.to_dict()["rows"]
    assert [c.text for c in forward.rows[0].cells] == ["ITEM", "10", "20"]


def test_spanning_title_does_not_collapse_the_columns():
    """A full-width heading crosses every gutter.

    Projecting tokens alone would merge the whole table into one column; the
    projection counts rows instead, so one wide line cannot outvote many.
    """
    tokens = [tok("STOCK AND SALES ANALYSIS FOR THE PERIOD", 0, 10, width=260)]
    for n in range(12):
        y = 40 + n * 12
        tokens += [tok(f"ITEM{n}", 0, y, width=50), tok("10", 100, y, width=14),
                   tok("20", 160, y, width=14), tok("30", 220, y, width=14)]

    bands = detect_column_bands(cluster_rows(tokens))
    assert len(bands) >= 4, f"expected the columns to survive, got {bands}"


def test_right_aligned_columns_are_separated():
    """Figures of differing width leave no x position that is empty on every
    row; the ink floor has to be swept for the gutter to appear at all."""
    tokens = []
    for n, (a, b, c) in enumerate([("6", "1068", "192"), ("865", "4658", "3750"),
                                   ("41", "892", "1419"), ("17", "0", "2565"),
                                   ("336", "4280", "561"), ("181", "3613", "1203")]):
        y = 40 + n * 12
        tokens.append(tok(f"ITEM{n}", 0, y, width=50))
        for text, right in ((a, 120), (b, 175), (c, 230)):
            width = len(text) * 5.0
            tokens.append(tok(text, right - width, y, width=width))

    grid = build_grid(tokens, 1, "pdf_text")
    populated = [len([c for c in r.cells if c.text.strip()]) for r in grid.rows]
    assert max(populated) == 4, f"expected 4 columns per row, got {populated}"


def test_cell_confidence_is_the_weakest_token():
    """A cell is only as trustworthy as its least certain part."""
    # Adjacent enough to fall in one band, so they form a single cell.
    rows = [[tok("ABC", 0, 10, width=15, conf=0.99),
             tok("DEF", 16, 10, width=15, conf=0.42)]]
    bands = detect_column_bands(rows)
    grid_rows = assign_columns(rows, bands)
    assert grid_rows[0].cells[0].confidence == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# Wrapped total rows
# ---------------------------------------------------------------------------


def _wrapped_rows():
    """Amar's Grand Total: two lines, each filling different columns."""
    top = GridRow(index=0, bbox=(0, 100, 400, 108), cells=[
        GridCell(text="Grand Total :", column=0, bbox=(0, 100, 80, 108)),
        GridCell(text="9609.000", column=2, bbox=(150, 100, 200, 108)),
        GridCell(text="4647.000", column=4, bbox=(250, 100, 300, 108)),
    ])
    bottom = GridRow(index=1, bbox=(0, 110, 400, 118), cells=[
        GridCell(text="3339.000", column=3, bbox=(200, 110, 250, 118)),
        GridCell(text="8301.000", column=5, bbox=(300, 110, 350, 118)),
    ])
    return [top, bottom]


def test_wrapped_total_row_is_rejoined():
    merged = merge_wrapped_rows(_wrapped_rows(), band_count=6)
    assert len(merged) == 1
    texts = {c.column: c.text for c in merged[0].cells}
    assert texts[2] == "9609.000" and texts[3] == "3339.000"
    assert texts[4] == "4647.000" and texts[5] == "8301.000"
    assert any("wrapped row" in n for n in merged[0].notes)


def test_rows_sharing_a_column_are_never_merged():
    """Two ordinary sparse rows must stay two rows."""
    rows = [
        GridRow(index=0, bbox=(0, 100, 400, 108), cells=[
            GridCell(text="ALPHA", column=0, bbox=(0, 100, 80, 108)),
            GridCell(text="10", column=2, bbox=(150, 100, 200, 108))]),
        GridRow(index=1, bbox=(0, 110, 400, 118), cells=[
            GridCell(text="BETA", column=0, bbox=(0, 110, 80, 118)),
            GridCell(text="20", column=2, bbox=(150, 110, 200, 118))]),
    ]
    assert len(merge_wrapped_rows(rows, band_count=6)) == 2


def test_distant_rows_are_never_merged():
    rows = _wrapped_rows()
    rows[1].bbox = (0, 400, 400, 408)      # far down the page
    for cell in rows[1].cells:
        cell.bbox = (cell.bbox[0], 400, cell.bbox[2], 408)
    assert len(merge_wrapped_rows(rows, band_count=6)) == 2


# ---------------------------------------------------------------------------
# Merged product lines
# ---------------------------------------------------------------------------


def _numeric_row(index: int, description: str) -> GridRow:
    cells = [GridCell(text=description, column=0)]
    cells += [GridCell(text=str(10 * index + n), column=n) for n in range(1, 5)]
    return GridRow(index=index, cells=cells)


def test_two_products_on_one_line_are_split():
    rows = [_numeric_row(i, f"ITEM {i}") for i in range(6)]
    # Two products' worth of cells on one line: the second description lands
    # in a column that is numeric on every other row.
    merged = GridRow(index=6, cells=[
        GridCell(text="IMIDIL C VAG SUPP.", column=0),
        GridCell(text="0.00", column=1), GridCell(text="0.00", column=2),
        GridCell(text="IMIDIL CREAM", column=3),      # a new description, in a
        GridCell(text="1.00", column=4),              # column numeric elsewhere
        GridCell(text="2.00", column=5), GridCell(text="3.00", column=6),
        GridCell(text="4.00", column=7), GridCell(text="5.00", column=8),
    ])
    rows.append(merged)

    out = split_merged_rows(rows)
    assert len(out) == 8, "the merged line should have become two rows"
    tail = out[-1]
    assert tail.cells[0].text == "IMIDIL CREAM"
    assert out[-2].cells[0].text == "IMIDIL C VAG SUPP."
    assert any("merged line" in n for n in tail.notes)


def test_an_ambiguous_intruder_is_reported_not_split():
    """Guessing a row boundary is worse than reporting a suspicious row."""
    rows = [_numeric_row(i, f"ITEM {i}") for i in range(6)]
    rows.append(GridRow(index=6, cells=[
        GridCell(text="ITEM 6", column=0),
        GridCell(text="10", column=1),
        GridCell(text="N/A", column=2),               # text, but the row is normal
        GridCell(text="30", column=3),
    ]))
    out = split_merged_rows(rows)
    assert len(out) == 7
    assert any("left intact" in n for n in out[-1].notes)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def test_router_rejects_unknown_types(tmp_path):
    # The router reads a file by its contents, so a name it does not know is
    # not enough to refuse it; contents it cannot read - an archive - are.
    path = tmp_path / "Downloads.rar"
    path.write_bytes(bytes([0x52, 0x61, 0x72, 0x21, 0x1A, 0x07, 0x01, 0x00]) + bytes(range(256)))
    with pytest.raises(ValueError):
        classify_file(path)


def test_router_reads_a_csv(tmp_path):
    path = tmp_path / "stock.csv"
    path.write_text("Item,Opening,In,Out,Closing\nA,10,5,3,12\n", encoding="utf-8")
    refs = classify_file(path)
    assert len(refs) == 1 and refs[0].kind is PageKind.EXCEL


def test_a_stray_text_layer_does_not_pass_as_native():
    """A scanned page often carries a scrap of text - a stamp, a footer.

    Character count alone would be fooled; the word threshold is what keeps
    such a page on the OCR path.
    """
    config = RouterConfig()
    assert config.min_words >= 10
    assert 0 < config.min_alnum_ratio <= 1.0


@pytest.mark.skipif(not CORPUS.is_dir(), reason="sample corpus not present")
def test_pages_of_one_file_are_routed_separately():
    """A PDF can mix native and scanned pages; the verdict is per page."""
    path = CORPUS / "02_2060543_140_20260819095307562.PDF"
    if not path.is_file():
        pytest.skip("mixed-mode sample not present")

    refs = classify_file(path)
    kinds = [r.kind for r in refs]
    assert PageKind.PDF_TEXT in kinds and PageKind.IMAGE in kinds, (
        "this file is the mixed-mode case; a per-file verdict would be wrong")
    assert all(r.reason for r in refs), "every decision must state its reason"


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------


def test_excel_numbers_do_not_gain_a_decimal_place(tmp_path):
    """Excel stores 50 as 50.0; the raw layer must not invent precision."""
    openpyxl = pytest.importorskip("openpyxl")
    from readers.excel_reader import read_excel

    path = tmp_path / "book.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Item", "Opening", "Rate"])
    sheet.append(["ALPHA", 50, 9.26])
    book.save(path)

    grid = read_excel(path)
    texts = [c.text for c in grid.rows[1].cells]
    assert texts == ["ALPHA", "50", "9.26"]
    assert all(c.confidence == 1.0 for r in grid.rows for c in r.cells)


def test_merged_header_becomes_a_column_span(tmp_path):
    """A merged range is how Excel writes a two-tier header.

    The span has to survive as geometry or Stage A cannot attach the parent
    heading to the sub-columns beneath it.
    """
    openpyxl = pytest.importorskip("openpyxl")
    from readers.excel_reader import read_excel

    path = tmp_path / "twotier.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet["A1"] = "ITEM"
    sheet["B1"] = "OPENING"
    sheet.merge_cells("B1:C1")
    sheet.append(["", "QTY", "VALUE"])
    sheet.append(["ALPHA", 10, 100])
    book.save(path)

    grid = read_excel(path)
    header = grid.rows[0]
    opening = next(c for c in header.cells if c.text == "OPENING")
    qty_row = grid.rows[1]
    qty = next(c for c in qty_row.cells if c.text == "QTY")
    value = next(c for c in qty_row.cells if c.text == "VALUE")

    # The merged heading must span both sub-columns.
    assert opening.bbox[0] <= qty.bbox[0] and opening.bbox[2] >= value.bbox[0]
    assert len([c for c in header.cells if c.text.strip()]) == 2, \
        "a merged range must not repeat its value across the columns it covers"


# ---------------------------------------------------------------------------
# Coverage accounting
# ---------------------------------------------------------------------------


def test_coverage_counts_numbers_inside_merged_cells():
    """Geometry joins tokens with a space, so a cell can hold several.

    Comparing whole cells against tokens reported every merged cell as a lost
    value - 441 false losses across ten real pages before this was fixed.
    """
    from column_mapper import map_grid
    from validator import validate_document

    grid = {
        "page": 1,
        "source": "pdf_text",
        "tokens": [{"text": t, "confidence": 1.0} for t in
                   ["400086", "7045686005", "10", "50", "10", "50"]],
        "rows": [
            {"index": 0, "cells": ["Mumbai - 400086", "7045686005 / 007 Mobile"]},
            {"index": 1, "cells": ["Item", "Opening", "In", "Out", "Balance"]},
            {"index": 2, "cells": ["ALPHA", "10", "50", "10", "50"]},
        ],
    }
    report = validate_document(map_grid(grid))
    assert report.coverage.missing == [], (
        f"numbers merged into a cell were reported lost: "
        f"{report.coverage.missing}")
    assert report.coverage.complete


def test_coverage_still_catches_a_genuinely_lost_value():
    """The relaxation must not make the check toothless."""
    from column_mapper import map_grid
    from validator import validate_document

    grid = {
        "page": 1,
        "source": "pdf_text",
        "tokens": [{"text": t, "confidence": 1.0} for t in
                   ["10", "50", "10", "50", "99999"]],
        "rows": [
            {"index": 0, "cells": ["Item", "Opening", "In", "Out", "Balance"]},
            {"index": 1, "cells": ["ALPHA", "10", "50", "10", "50"]},
        ],
    }
    report = validate_document(map_grid(grid))
    assert "99999" in report.coverage.missing
    assert any(f.check == "coverage" for f in report.flagged)


def test_the_report_does_not_lose_its_caveats_on_regeneration():
    """The section arguing against the headline must be generated, not pasted.

    It was hand-appended to BENCHMARK.md once, which meant the next run would
    have silently deleted it - leaving a report that only flattered itself.
    """
    import benchmark

    fake = [
        benchmark.PageMetrics(file="a.pdf", page_index=0, expected_kind="pdf_text",
                              actual_kind="pdf_text", cells=100, verified=40,
                              flagged=1, unchecked=59, columns=10, columns_mapped=6,
                              tabular_sections=1, totals_checked=3,
                              totals_reconciled=1, tokens_seen=50, tokens_placed=50),
        # A page that produced nothing: the caveat must call it out.
        benchmark.PageMetrics(file="b.pdf", page_index=2, expected_kind="image",
                              actual_kind="image", cells=0, seconds=40.0),
    ]
    report = benchmark.format_markdown(fake)

    assert "## What these numbers do not say" in report
    assert "produced nothing at all" in report
    assert "b.pdf" in report, "the empty page should be named"
    assert "Totals reconciled: 1 of 3" in report, "figures must be computed"


def test_the_report_states_the_old_review_figure_correctly():
    """The correction must not be computed from the corrected counts.

    Reading `flagged + unchecked` off the new statuses reports a fraction of
    the old figure, because the cells the taxonomy reclassified as `exact` are
    exactly the ones the old definition counted. The report would then
    understate its own correction more than twentyfold.
    """
    import benchmark

    metrics = [benchmark.PageMetrics(
        file="a.xlsx", page_index=0, expected_kind="excel", actual_kind="excel",
        cells=10_000, exact=9_900, verified=100, flagged=0, unchecked=0,
        pixel_cells=0, review=0, tabular_sections=1, columns=5, columns_mapped=5)]
    report = benchmark.format_comparison(metrics, [])

    assert "up to 9,900" in report, "the old figure counts the exact cells too"
    assert "| 100 |" not in report.split("Review load")[1].split("Silent")[0]


def test_the_report_names_what_did_not_generalise():
    """A held-out set that only ever confirms the headline is decoration."""
    import benchmark

    def page(structural, review, pixel):
        return benchmark.PageMetrics(
            file="x.pdf", page_index=0, expected_kind="image",
            actual_kind="image", cells=100, exact=0, verified=10, flagged=0,
            unchecked=review, pixel_cells=pixel, structural_flags=structural,
            review=review, tabular_sections=1, columns=5, columns_mapped=2)

    report = benchmark.format_comparison([page(5, 40, 100)], [page(500, 100, 100)])
    assert "Structural flags rise from 5 to 500" in report
    assert "do not hold up" in report


def test_a_toolbar_with_as_many_columns_does_not_replace_the_table():
    # A screenshot of a PDF viewer: an eight-row, four-column table, and under
    # it the app's toolbar whose labels cross the table's gutters. Both splits
    # give four bands; only the table's gives each row four cells.
    config = GeometryConfig()
    table = [(20, 100), (200, 220), (260, 280), (300, 330)]
    rows = [[Token(text="x", x0=a, y0=20 * r, x1=b, y1=20 * r + 14) for a, b in table]
            for r in range(8)]
    rows.append([Token(text=t, x0=a, y0=300, x1=b, y1=314) for t, a, b in
                 (("AI Writer", 70, 155), ("Thumbnails", 199, 352),
                  ("Convert", 400, 476), ("All tools", 561, 639))])
    bands = detect_column_bands(rows, config)
    assert [(round(a), round(b)) for a, b in bands] == table
