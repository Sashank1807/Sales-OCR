"""The four-state taxonomy, and what counts as a table.

Both exist to stop the pipeline overstating its own workload: one separates
values that cannot have been misread from values nobody has checked, the other
stops address blocks being treated as tables.
"""

from __future__ import annotations

import pytest

from column_mapper import ColumnMapper, VLMColumnResponse, map_grid
from schema import Cell, CellStatus, Provenance, Role, SectionKind, Source, load_grid
from validator import validate_document


# ---------------------------------------------------------------------------
# Status taxonomy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source,expected,deterministic", [
    (Source.EXCEL, CellStatus.EXACT, True),
    (Source.PDF_TEXT, CellStatus.EXACT, True),
    (Source.OCR, CellStatus.UNCHECKED, False),
])
def test_the_source_decides_whether_a_value_can_be_misread(source, expected,
                                                           deterministic):
    cell = Cell(raw_text="10", column_index=0, provenance=Provenance(source=source))
    assert cell.status is expected
    assert cell.is_deterministic is deterministic


def test_arithmetic_cannot_demote_a_deterministic_cell():
    """Confirming an exact value adds nothing; it must not weaken the claim."""
    cell = Cell(raw_text="10", column_index=0,
                provenance=Provenance(source=Source.PDF_TEXT))
    cell.mark(CellStatus.VERIFIED, "row_equation_qty")
    assert cell.status is CellStatus.EXACT
    assert "row_equation_qty" in cell.reasons, "the check is still recorded"


def test_nothing_can_promote_a_pixel_cell_to_exact():
    cell = Cell(raw_text="10", column_index=0,
                provenance=Provenance(source=Source.OCR))
    cell.mark(CellStatus.EXACT, "wishful")
    assert cell.status is not CellStatus.EXACT


def test_a_deterministic_cell_can_still_fail_a_structural_check():
    """A row that does not balance is a layout fault, not a reading fault."""
    cell = Cell(raw_text="10", column_index=0,
                provenance=Provenance(source=Source.PDF_TEXT))
    cell.mark(CellStatus.FLAGGED, "row_equation_qty_mismatch")
    assert cell.status is CellStatus.FLAGGED
    assert cell.needs_review


def _stock_rows(count=8):
    rows = [["Item", "Opening", "In", "Out", "Balance"]]
    rows += [[f"ITEM {n}", str(10 * n), "5", "3", str(10 * n + 2)]
             for n in range(1, count + 1)]
    return rows


def _grid(rows, source="pdf_text"):
    return {"page": 1, "source": source,
            "rows": [{"index": i, "cells": r} for i, r in enumerate(rows)]}


def test_review_load_excludes_values_that_cannot_have_been_misread():
    """The correction this taxonomy exists for.

    Under the old three-state scheme every unconfirmed Excel cell counted as
    review, which made a deterministic source look like the worst case.
    """
    rows = _stock_rows()
    deterministic = validate_document(map_grid(_grid(rows, "excel")))
    pixels = validate_document(map_grid(_grid(rows, "ocr")))

    assert deterministic.counts["exact"] > 0
    assert deterministic.counts["pixel_cells"] == 0
    assert deterministic.review_cells == 0, "Excel cells cannot have been misread"

    assert pixels.counts["exact"] == 0
    assert pixels.counts["pixel_cells"] > 0
    assert pixels.review_cells > 0, "the same grid read from pixels does carry load"


def test_structural_flags_are_counted_apart_from_review():
    """An exact cell in a broken row is a mapping fault, not a reading one."""
    rows = _stock_rows()
    rows.append(["BROKEN", "10", "5", "3", "999"])          # does not balance

    report = validate_document(map_grid(_grid(rows, "excel")))
    assert report.structural_flags > 0
    assert report.review_cells == 0, "nothing to re-read; the layout is at fault"
    assert any("row_equation" in f.check for f in report.flagged)


def test_counts_partition_every_cell():
    report = validate_document(map_grid(_grid(_stock_rows(2), "ocr")))
    c = report.counts
    assert c["exact"] + c["verified"] + c["flagged"] + c["unchecked"] == c["total_cells"]


# ---------------------------------------------------------------------------
# Tabular classification
# ---------------------------------------------------------------------------


ADDRESS_BLOCK = [
    ["P. VISHRAM DISTRIBUTOR", "", "", "TO : HETERO HEALTHCARE"],
    ["Gala No.6,23 and 8, 2Nd", "", "", "Unit No.Z-5,5and18,Shree"],
    ["Patanwala Estate, L.B.", "", "", "Opp Durgesh Park Kalhe"],
    ["Ghatkopar (W) Mumbai -", "", "", "Thane - 421302"],
    ["GSTIN : 27AAECP7444A1Z", "", "", "GSTIN :"],
]


def _page(*blocks):
    rows, index = [], 0
    for block in blocks:
        for record in block:
            rows.append({"index": index, "cells": record})
            index += 1
    return {"page": 1, "source": "pdf_text", "rows": rows}


def test_an_address_block_is_not_treated_as_a_table():
    """It has headings and cells like any section; it is still prose."""
    document = map_grid(_page(ADDRESS_BLOCK, _stock_rows()))
    address = document.sections[0]

    assert address.kind is SectionKind.NON_TABULAR
    assert address.tabular_signals["numeric_density"] < 0.2
    assert any("not a table" in n for n in address.notes)


def test_a_real_table_is_still_recognised():
    document = map_grid(_page(ADDRESS_BLOCK, _stock_rows()))
    table = next(s for s in document.sections if s.kind is SectionKind.TABULAR)
    assert table.tabular_signals["score"] >= table.tabular_signals["threshold"]
    assert table.roles_present() >= {Role.OPENING_QTY, Role.CLOSING_QTY}


def test_a_short_table_is_still_a_table():
    """Khushi's runs to two rows; a row-count veto would discard it."""
    short = [["Particulars", "Open. Qty.", "Purch. Qty.", "Close Stock"],
             ["HERAFT 150ML", "10", "140", "150"],
             ["TEDITRATE 200 MG", "20", "20", "40"]]
    assert map_grid(_page(short)).sections[0].kind is SectionKind.TABULAR


def test_non_tabular_sections_keep_their_content_in_the_raw_layer():
    document = map_grid(_page(ADDRESS_BLOCK, _stock_rows()))
    # Whether a prose line lands in the preamble or in a non-tabular section is
    # a detail; that it survives somewhere in the raw layer is the guarantee.
    texts = [c.raw_text for c in document.iter_all_cells() if c.raw_text.strip()]
    assert any("Gala No.6" in t for t in texts), "nothing may be discarded"
    assert any("27AAECP7444A1Z" in t for t in texts)


def test_a_non_tabular_section_is_never_column_mapped_or_sent_to_the_vlm():
    """The 3,833-column VLM census was almost entirely this bug."""

    class Recorder:
        def __init__(self):
            self.requests = []

        def resolve(self, request):
            self.requests.append(request)
            return VLMColumnResponse(roles={})

    recorder = Recorder()
    rows, tokens, page, source = load_grid(_page(ADDRESS_BLOCK, _stock_rows()))
    document = ColumnMapper(vlm_resolver=recorder).map_document(
        rows, tokens, page, source)

    address = document.sections[0]
    assert all(c.role is Role.UNKNOWN for c in address.columns)
    assert address.index not in {r.section_index for r in recorder.requests}, \
        "a prose block must not be put to the VLM"


def test_a_non_tabular_section_is_not_arithmetic_checked():
    document = map_grid(_page(ADDRESS_BLOCK, _stock_rows()))
    report = validate_document(document)
    assert not [f for f in report.findings
                if f.section_index == 0 and "row_equation" in f.check]


def test_the_verdict_is_auditable():
    """Every classification records the measurements behind it."""
    document = map_grid(_page(ADDRESS_BLOCK, _stock_rows()))
    for section in document.sections:
        if section.kind is SectionKind.EMPTY:
            continue
        assert {"rows", "consistency", "band_occupancy", "numeric_density",
                "band_stability", "score"} <= set(section.tabular_signals)
