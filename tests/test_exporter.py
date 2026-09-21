"""The structured report: keys, values, statuses, and that no row goes missing."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import ROOT, mapped, row_named
from exporter import _first_metadata, _keys_for, _value, build_report
from pipeline import PageResult, PipelineResult
from readers.router import PageKind, PageRef
from schema import Cell, CellStatus, MetadataField, Role, RowType, SectionKind


def _result(*documents, name="report.pdf") -> PipelineResult:
    result = PipelineResult(path=Path(name))
    for index, document in enumerate(documents):
        ref = PageRef(path=Path(name), kind=PageKind.PDF_TEXT, page_index=index,
                      page_count=len(documents))
        result.pages.append(PageResult(ref=ref, document=document))
    return result


def _rows(report):
    return [row for table in report["tables"] for group in table["groups"]
            for row in group["rows"]]


def _source_rows(*documents) -> int:
    return sum(1 for d in documents for s in d.sections if s.kind is SectionKind.TABULAR
               for r in s.rows if r.row_type in (RowType.DATA, RowType.TOTAL))


def _key_for(report, role: Role) -> str:
    return next(c["key"] for c in report["tables"][0]["columns"] if c["role"] == role.value)


# -- keys and values ---------------------------------------------------------


def test_repeated_headings_are_numbered_and_blank_ones_take_their_position():
    assert _keys_for(["SNO", "FR", "OB", "FR", "", "Cl.Stock As On"]) == [
        "sno", "fr_1", "ob", "fr_2", "column_5", "cl_stock_as_on"]


@pytest.mark.parametrize("printed, expected", [
    ("12", 12),
    ("0.00", 0.0),
    ("1934.02", 1934.02),
    ("10'S", "10'S"),
    ("87.91 1934.02", "87.91 1934.02"),   # two figures in one cell stay as printed
    ("", None),
])
def test_values_follow_what_the_document_printed(printed, expected):
    value = _value(Cell(raw_text=printed, column_index=0))
    assert value == expected
    assert type(value) is type(expected)


def test_a_rule_of_dashes_is_not_a_company_name(bansal_p1):
    bansal_p1.metadata.distributor_name = MetadataField(value="-" * 40, confidence=0.5)
    assert _first_metadata([bansal_p1], "distributor_name") is None


# -- rows --------------------------------------------------------------------


def test_amar_rows_carry_the_documents_own_figures_under_the_right_roles(amar):
    """AD 10 SACHETS: 10 + 50 - 10 = 50 (CLAUDE.md s7)."""
    report = build_report(_result(amar))
    row = next(r for r in _rows(report)
               if "AD 10 SACHETS" in str(r[_key_for(report, Role.ITEM_DESCRIPTION)]))
    assert row[_key_for(report, Role.OPENING_QTY)] == 10
    assert row[_key_for(report, Role.RECEIPT_QTY)] == 50
    assert row[_key_for(report, Role.ISSUE_QTY)] == 10
    assert row[_key_for(report, Role.CLOSING_QTY)] == 50


def test_every_row_says_whether_it_needs_review(amar):
    for row in _rows(build_report(_result(amar))):
        assert row["status"] in {s.value for s in CellStatus}
        assert isinstance(row["needs_review"], list)


def test_two_pages_of_one_statement_are_one_table_and_no_row_is_lost(bansal_p1, bansal_p2):
    report = build_report(_result(bansal_p1, bansal_p2))
    assert len(report["tables"]) == 1
    assert report["tables"][0]["pages"] == [1, 2]
    exported = len(_rows(report)) + sum(len(t["totals"]) for t in report["tables"])
    assert exported == _source_rows(bansal_p1, bansal_p2)


def test_text_under_a_figures_heading_is_flagged_and_kept(amar):
    """A page footer read exactly is still not a product row."""
    section = next(s for s in amar.sections if s.kind is SectionKind.TABULAR)
    closing = section.role_index(Role.CLOSING_QTY)
    row = row_named(section, "AD 10 SACHETS")
    cell = row.cell_at(closing)
    cell.raw_text, cell.value = "Page 1 of 3", None

    report = build_report(_result(amar))
    key = _key_for(report, Role.CLOSING_QTY)
    exported = next(r for r in _rows(report) if r.get(key) == "Page 1 of 3")
    assert exported["status"] == CellStatus.FLAGGED.value
    assert key in exported["needs_review"]
    assert "figures" in exported["review_reasons"][key]


# -- saved OCR tokens --------------------------------------------------------


_TEXT_PDF = ROOT / "JUNE" / "11.pdf"


@pytest.mark.skipif(not _TEXT_PDF.is_file(), reason="JUNE corpus not present")
def test_saved_ocr_tokens_never_replace_a_text_layer():
    """s4.1: a page with a text layer is read from it, whatever OCR saw."""
    from pipeline import process_file
    from readers.contract import Token

    junk = [Token(text="999999", x0=0, y0=0, x1=10, y1=10, confidence=0.99, index=0)]
    plain = process_file(_TEXT_PDF, pages=[0])
    given = process_file(_TEXT_PDF, pages=[0], ocr_tokens={0: junk})

    def cells(result):
        return [(c.raw_text, c.status) for p in result.pages for s in p.document.sections
                for r in s.rows for c in r.cells]

    assert cells(given) == cells(plain)
    assert all(text != "999999" for text, _ in cells(given))
