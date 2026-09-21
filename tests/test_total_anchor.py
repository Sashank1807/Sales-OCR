"""A printed total that matches a column sum confirms the whole column.

The document's own footing is the only check that reaches a column no heading
named - which is the state a photographed page's columns are usually left in
when OCR mangles the header line.
"""

from __future__ import annotations

import pytest

from conftest import mapped
from readers.geometry import GeometryConfig, _fit_column_shear
from readers.contract import Token
from schema import Role
from validator import Validator, ValidatorConfig


def _unname(section, role: Role) -> int:
    """Take a mapped role away, leaving the figures with no heading."""
    index = section.role_index(role)
    assert index is not None
    for column in section.columns:
        if column.index == index:
            column.role = Role.UNKNOWN
            column.confidence = 0.0
    return index


def test_named_column_confirmed_by_its_printed_total(bansal_p1):
    """Bansal page 1 foots: every opening figure is confirmed by the TOTAL."""
    section = bansal_p1.sections[0]
    index = section.role_index(Role.OPENING_QTY)
    Validator().validate(bansal_p1)

    confirmed = [row for row in section.data_rows
                 if (cell := row.cell_at(index)) is not None and cell.is_numeric
                 and "column_sum_matches_printed_total" in cell.reasons]
    assert len(confirmed) >= 10


def test_unnamed_column_is_still_confirmed(bansal_p1):
    """No heading, no role, no row equation - and the column still checks out."""
    section = bansal_p1.sections[0]
    index = _unname(section, Role.OPENING_QTY)
    report = Validator().validate(bansal_p1)

    cells = [cell for row in section.data_rows
             if (cell := row.cell_at(index)) is not None and cell.is_numeric]
    assert cells, "expected figures in the unnamed column"
    for cell in cells:
        assert "column_sum_matches_printed_total" in cell.reasons
    assert any(f.check == "column_sum" for f in report.findings)


def test_a_short_column_is_not_confirmed(bansal_p1):
    """Matching a total against one or two figures is coincidence, not proof.

    Raising the bar above the rows available must withdraw the confirmation -
    without this the check would fire on a single figure printed above its own
    repetition.
    """
    section = bansal_p1.sections[0]
    index = _unname(section, Role.OPENING_QTY)
    config = ValidatorConfig()
    config.column_sum_min_rows = 10_000
    Validator(config).validate(bansal_p1)

    for row in section.data_rows:
        cell = row.cell_at(index)
        if cell is not None and cell.is_numeric:
            assert "column_sum_matches_printed_total" not in cell.reasons


def test_a_column_that_does_not_foot_is_not_confirmed(bansal_p1):
    """Change one figure and the column stops adding up to the printed total."""
    section = bansal_p1.sections[0]
    index = _unname(section, Role.OPENING_QTY)
    for row in section.data_rows:
        cell = row.cell_at(index)
        if cell is not None and cell.is_numeric:
            cell.value += 7
            break
    Validator().validate(bansal_p1)

    for row in section.data_rows:
        cell = row.cell_at(index)
        if cell is not None and cell.is_numeric:
            assert "column_sum_matches_printed_total" not in cell.reasons


# ---------------------------------------------------------------------------
# Leaning columns on a photographed page
# ---------------------------------------------------------------------------


def _grid(shear: float) -> list[Token]:
    """A four-column, twelve-row table photographed with the given lean."""
    tokens = []
    index = 0
    for r in range(12):
        y0 = 100.0 + 20.0 * r
        for c in range(4):
            x0 = 50.0 + 120.0 * c + shear * (y0 + 5.0 - 105.0)
            tokens.append(Token(text=f"{r}{c}", x0=x0, y0=y0, x1=x0 + 40.0,
                                y1=y0 + 10.0, confidence=0.99, index=index))
            index += 1
    return tokens


def test_shear_search_recovers_a_lean():
    found = _fit_column_shear(_grid(0.08), 10.0, GeometryConfig())
    assert found is not None
    shear, drift = found
    assert shear == pytest.approx(0.08, abs=0.02)
    assert drift > 10


def test_shear_search_leaves_an_upright_page_alone():
    assert _fit_column_shear(_grid(0.0), 10.0, GeometryConfig()) is None


def test_a_shear_that_costs_the_page_its_grid_is_refused(monkeypatch):
    """Straightening has to leave the table at least as well resolved.

    A shear keeps two columns apart within any one row, but the band detector
    projects the whole page, and tokens at different heights move by different
    amounts - so a shear can close the gutter a table depends on. Two MAY photos
    lost their table that way to a 14 px correction. Forcing a large bogus lean
    on an upright page must be refused rather than applied.
    """
    from readers import geometry

    monkeypatch.setattr(geometry, "_fit_column_shear", lambda *a, **k: (0.5, 500.0))
    assert geometry.straighten_page(_grid(0.0), GeometryConfig()) is None


# ---------------------------------------------------------------------------
# A scan someone else OCR'd is a scan
# ---------------------------------------------------------------------------


def _pdf_page(tmp_path, render_mode: int):
    """A one-page PDF whose text is drawn visibly or invisibly."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    for n in range(40):
        page.insert_text((60, 60 + n * 14), f"ITEM {n} 100 200 300",
                         fontsize=9, render_mode=render_mode)
    path = tmp_path / f"mode{render_mode}.pdf"
    doc.save(str(path))
    doc.close()
    return path


def test_an_invisible_text_layer_is_read_as_a_scan(tmp_path):
    """Invisible text is an OCR layer over a scan, not the document's own text.

    Passing it on as `exact` claims the digits could not have been misread,
    when in fact another engine read them off pixels and no one will review
    them. 25 pages of the two corpora were doing that with 4,797 cells.
    """
    from readers.router import PageKind, classify_file

    refs = classify_file(_pdf_page(tmp_path, 3))
    assert refs[0].kind is PageKind.IMAGE
    assert "invisible" in refs[0].reason


def test_an_ordinary_text_layer_is_still_read_as_text(tmp_path):
    """The discriminator must not send ordinary PDFs to OCR."""
    from readers.router import PageKind, classify_file

    refs = classify_file(_pdf_page(tmp_path, 0))
    assert refs[0].kind is PageKind.PDF_TEXT


# ---------------------------------------------------------------------------
# Empty declared columns are not columns the rows failed to fill
# ---------------------------------------------------------------------------


def _sparse_section(declared: int):
    """A table whose rows use a fraction of the columns the file declares."""
    from decimal import Decimal
    from schema import Cell, Row, RowType, Section

    section = Section(index=0, header_row_indices=[], header_rows=[])
    used = list(range(0, declared, 2))
    widths = [4, 9, 5, 10, 6, 8, 4, 9, 7, 10, 5, 8, 6, 9, 4, 10, 7, 8, 5, 9]
    for n, width in enumerate(widths):
        row = Row(index=n, row_type=RowType.DATA)
        # A name and a pack, as every stock statement has.
        row.cells.append(Cell(raw_text=f"ITEM {n}", column_index=used[0]))
        row.cells.append(Cell(raw_text="1*10", column_index=used[1]))
        for j in range(2, width):
            cell = Cell(raw_text=str(100 + n + j), column_index=used[j % 12])
            cell.value = Decimal(100 + n + j)
            row.cells.append(cell)
        section.rows.append(row)
    return section


def test_spacer_columns_do_not_cost_a_sheet_its_table():
    """A column no row reaches is not a column the rows failed to fill.

    A spreadsheet with merged headings declares a column for every cell the
    merge spans: `MUKTJIVAN MAY KALOL.xls` offers 52 for the 22 it uses, and
    its 80 rows of stock were thrown out as prose for "filling 11% of the 52
    columns".
    """
    from column_mapper import ColumnMapper

    section = _sparse_section(declared=52)
    assert ColumnMapper()._is_tabular(section, 52), section.tabular_signals


# ---------------------------------------------------------------------------
# A figure printed with a trailing point
# ---------------------------------------------------------------------------


def test_a_trailing_point_is_part_of_the_figure():
    """`34.` is the figure 34, as several billing packages print quantities.

    Read as prose it took the value with it: the cell carried no number, so no
    row equation and no column sum could run, and a page of them scored 23%
    numeric and lost its table (`PAVAN MAY MEHSANA.pdf` p1, 41 rows).
    """
    from schema import is_blank_text, parse_number

    assert parse_number("34.") == 34
    assert parse_number("1,234.") == 1234
    # A lone point is still the document saying nil, and units keep their dot.
    assert is_blank_text(".")
    assert parse_number(".") is None
    assert parse_number("500MG.") is None


def test_a_trailing_point_counts_as_a_figure_to_the_reader():
    from readers.geometry import _NUMERIC_RE

    assert _NUMERIC_RE.match("34.")
    assert not _NUMERIC_RE.match(".")
    assert not _NUMERIC_RE.match("MG.")
