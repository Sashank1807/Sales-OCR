"""Stage A tests - column role discovery, sectioning and metadata."""

from __future__ import annotations

import pytest

from column_mapper import (
    ColumnMapper, MapperConfig, VLMColumnRequest, VLMColumnResponse, map_grid,
)
from conftest import load_raw, mapped, roles_by_index, row_named
from schema import MappingMethod, Role, SectionKind


# ---------------------------------------------------------------------------
# Amar - single-tier header, bare Opening/In/Out/Balance
# ---------------------------------------------------------------------------


def test_amar_maps_every_column(amar):
    section = amar.sections[0]
    assert roles_by_index(section) == {
        0: "item_description", 1: "code", 2: "opening_qty", 3: "receipt_qty",
        4: "issue_qty", 5: "closing_qty", 6: "unit", 7: "rate", 8: "closing_value",
    }


def test_amar_opening_measure_settled_by_arithmetic(amar):
    """'Opening' prints two decimals like a money column, but it is a count.

    The heading names the flow and says nothing about the measure; the
    arithmetic settles it. The two must not be reported as a conflict.
    """
    column = amar.sections[0].columns[2]
    assert column.role is Role.OPENING_QTY
    assert column.method is MappingMethod.HEADER_AND_ARITHMETIC
    assert column.confidence >= 0.9
    assert not any("CONFLICT" in e for e in column.evidence)


def test_amar_value_column_recovered_from_the_rate_relation(amar):
    """'Value' matches no synonym; qty x rate = value identifies it."""
    column = amar.sections[0].columns[8]
    assert column.role is Role.CLOSING_VALUE
    assert column.method is MappingMethod.ARITHMETIC
    assert any("col7" in e for e in column.evidence)


def test_amar_metadata(amar):
    assert amar.metadata.distributor_name.value == "AMAR PHARMACEUTICALS"
    assert amar.metadata.period_from.value == "01/Aug/2026"
    assert amar.metadata.period_to.value == "31/Aug/2026"


@pytest.mark.parametrize("needle,expected", [
    ("MIKATERO", "500MG."),
    ("ONDATERO INJ", "2MG/2I"),
])
def test_truncated_unit_strings_survive_verbatim(amar, needle, expected):
    """The raw layer is never normalised, however broken the string looks."""
    section = amar.sections[0]
    cell = row_named(section, needle).cell_at(section.role_index(Role.UNIT))
    assert cell.raw_text == expected
    assert cell.value is None, "a unit string must not be parsed as a number"


# ---------------------------------------------------------------------------
# Bansal - two-tier header spanning QTY/VALUE sub-columns
# ---------------------------------------------------------------------------


def test_bansal_two_tier_header_merges(bansal_p1):
    section = bansal_p1.sections[0]
    assert roles_by_index(section) == {
        0: "item_description", 1: "pack",
        2: "opening_qty", 3: "opening_value",
        4: "receipt_qty", 5: "receipt_value",
        6: "issue_qty", 7: "issue_value",
        8: "closing_qty", 9: "closing_value",
        10: "dump_qty",
    }
    assert section.columns[2].header_text == "OPENING QTY."
    assert section.columns[3].header_text == "OPENING VALUE"
    assert section.columns[2].header_parts == ["OPENING", "QTY."]


def test_bansal_header_rows_are_not_data(bansal_p1):
    """Both tiers are consumed as headers, not mistaken for rows."""
    section = bansal_p1.sections[0]
    assert len(section.header_row_indices) == 2
    assert len(section.data_rows) == 64
    assert len(section.total_rows) == 1


def test_bansal_pack_column_has_no_heading_and_is_found_by_shape(bansal_p1):
    column = bansal_p1.sections[0].columns[1]
    assert column.header_text == ""
    assert column.role is Role.PACK
    assert column.method is MappingMethod.PROFILE


def test_bansal_metadata_includes_gstin_and_manufacturer(bansal_p1):
    assert bansal_p1.metadata.gstin.value == "09AAMPA4057B1Z2"
    assert bansal_p1.metadata.manufacturer.value == "HETERO HEALTHCARE LTD."
    assert bansal_p1.metadata.distributor_name.value == "BANSAL MEDICAL AGENCIES"


def test_issue_and_closing_are_not_swapped(bansal_p1):
    """``o + r - i = c`` is equally true as ``o + r - c = i``.

    Arithmetic alone cannot orient the pair, so the heading has to win. Getting
    this wrong silently transposes two columns of every row.
    """
    section = bansal_p1.sections[0]
    total = section.total_rows[0]
    assert total.cell_at(section.role_index(Role.ISSUE_QTY)).value == 1064
    assert total.cell_at(section.role_index(Role.CLOSING_QTY)).value == 913


def test_short_page_does_not_let_weak_arithmetic_override_headers(bansal_p2):
    """Page 2 has two rows and an empty receipt column.

    Several spurious equations fit that little data. An explicit two-tier
    heading outranks them.
    """
    section = bansal_p2.sections[0]
    assert roles_by_index(section)[4] == "receipt_qty"
    assert roles_by_index(section)[5] == "receipt_value"


# ---------------------------------------------------------------------------
# Khushi - abbreviations, reversing flows, and empty sections
# ---------------------------------------------------------------------------


def test_khushi_abbreviated_headers(khushi):
    roles = roles_by_index(khushi.sections[0])
    assert roles[2] == "opening_qty"    # "Open. Qty."
    assert roles[3] == "receipt_qty"    # "Purch. Qty."
    assert roles[7] == "closing_qty"    # "Close Stock"
    assert roles[9] == "issue_value"    # "Sales Value"


def test_sales_return_is_not_tagged_as_an_issue(khushi):
    """A sales return is an inward movement.

    There is no canonical role for it, so the column stays unknown rather than
    being folded into issues and corrupting the arithmetic.
    """
    column = khushi.sections[0].columns[4]
    assert column.header_text == "Sales Ret."
    assert column.role is Role.UNKNOWN
    assert any("reversing flow" in e for e in column.evidence)


def test_khushi_returns_empty_sections_rather_than_inventing_rows(khushi):
    empty = [s for s in khushi.sections if s.kind is SectionKind.EMPTY]
    assert len(empty) == 2
    for section in empty:
        assert section.rows == []
        assert section.columns, "an empty section still reports its headings"
        assert any("no data rows" in n for n in section.notes)


def test_khushi_expiry_header_is_its_own_section(khushi):
    """'Product | Pkg | BATCHNO | EXPIRY | Stock' must not be absorbed as a
    sub-heading of the block below it."""
    headers = [[c.header_text for c in s.columns] for s in khushi.sections]
    assert ["Product", "Pkg", "BATCHNO", "EXPIRY", "Stock"] in headers
    assert ["Bill No", "Bill Date", "Gross Amount", "Net Amount"] in headers


# ---------------------------------------------------------------------------
# Krishna - phone photo, second non-tabular block
# ---------------------------------------------------------------------------


def test_krishna_main_table(krishna):
    roles = roles_by_index(krishna.sections[0])
    assert roles[2] == "opening_qty"
    assert roles[5] == "closing_qty"
    assert krishna.metadata.gstin.value == "09AAKHR3684K1ZE"


def test_krishna_purchase_block_is_non_tabular(krishna):
    section = krishna.sections[1]
    assert section.kind is SectionKind.NON_TABULAR
    assert section.title == "PURCHASE DETAIL :-"
    assert not (section.roles_present() & {Role.RECEIPT_QTY, Role.ISSUE_QTY})


def test_receive_date_is_not_mistaken_for_a_receipt_column(krishna):
    """'RECEIVE DATE' fuzzy-matches 'received'; the column holds dates."""
    column = krishna.sections[1].columns[3]
    assert column.header_text == "RECEIVE DATE"
    assert column.role is Role.UNKNOWN


# ---------------------------------------------------------------------------
# Headerless recovery
# ---------------------------------------------------------------------------


def test_roles_recovered_with_no_headers_at_all():
    """Strip the headings and the arithmetic still finds the stock group."""
    grid = {
        "page": 1,
        "rows": [
            {"index": 0, "cells": ["Item", "A", "B", "C", "D"]},
            {"index": 1, "cells": ["ALPHA TAB", "10", "50", "10", "50"]},
            {"index": 2, "cells": ["BETA CAP", "9", "30", "9", "30"]},
            {"index": 3, "cells": ["GAMMA SYP", "122", "3", "5", "120"]},
            {"index": 4, "cells": ["DELTA INJ", "92", "6", "30", "68"]},
            {"index": 5, "cells": ["EPSILON TAB", "77", "124", "58", "143"]},
            {"index": 6, "cells": ["ZETA TAB", "26", "65", "14", "77"]},
        ],
    }
    section = map_grid(grid).sections[0]
    roles = roles_by_index(section)
    assert roles[1] == "opening_qty"
    assert roles[2] == "receipt_qty"
    assert roles[3] == "issue_qty"
    assert roles[4] == "closing_qty"
    assert section.columns[1].method is MappingMethod.ARITHMETIC


def test_headerless_orientation_ambiguity_is_recorded():
    """With no headings the issue/closing pair cannot be oriented.

    The mapper must say so rather than presenting a coin-flip as fact.
    """
    grid = {
        "page": 1,
        "rows": [
            {"index": 0, "cells": ["Item", "A", "B", "C", "D"]},
            {"index": 1, "cells": ["ALPHA TAB", "10", "50", "10", "50"]},
            {"index": 2, "cells": ["BETA CAP", "9", "30", "9", "30"]},
            {"index": 3, "cells": ["GAMMA SYP", "122", "3", "5", "120"]},
            {"index": 4, "cells": ["DELTA INJ", "92", "6", "30", "68"]},
        ],
    }
    section = map_grid(grid).sections[0]
    ambiguous = [c for c in section.columns if c.orientation_ambiguous]

    assert len(ambiguous) == 2
    assert {c.role for c in ambiguous} == {Role.ISSUE_QTY, Role.CLOSING_QTY}
    assert all(any("symmetric" in e for e in c.evidence) for c in ambiguous)


def test_unresolved_orientation_is_not_reported_confidently():
    """A guess between two columns must not carry a confident score.

    It is pushed below the VLM threshold so the fallback gets asked, rather
    than a coin flip being handed downstream at 0.80.
    """
    grid = {
        "page": 1,
        "rows": [
            {"index": 0, "cells": ["Item", "A", "B", "C", "D"]},
            {"index": 1, "cells": ["ALPHA TAB", "10", "50", "10", "50"]},
            {"index": 2, "cells": ["BETA CAP", "9", "30", "9", "30"]},
            {"index": 3, "cells": ["GAMMA SYP", "122", "3", "5", "120"]},
            {"index": 4, "cells": ["DELTA INJ", "92", "6", "30", "68"]},
        ],
    }
    mapper = ColumnMapper()
    section = mapper.map_document(*_grid_parts(grid)).sections[0]
    ambiguous = [c for c in section.columns if c.orientation_ambiguous]

    assert ambiguous
    for column in ambiguous:
        assert column.confidence < mapper.config.vlm_threshold
    assert any("VLM threshold" in n for n in section.notes)


def test_headings_settle_the_orientation_without_penalty(amar, bansal_p1):
    """Where the document labels its columns, nothing is ambiguous."""
    for document in (amar, bansal_p1):
        assert not [c for s in document.sections for c in s.columns
                    if c.orientation_ambiguous]


def _grid_parts(grid):
    from schema import load_grid
    return load_grid(grid)


# ---------------------------------------------------------------------------
# VLM fallback hook
# ---------------------------------------------------------------------------


class RecordingResolver:
    """Stand-in for a VLM. Records what it was asked, answers from a script."""

    def __init__(self, answers: dict[int, str], note: str = "test") -> None:
        self.answers = answers
        self.note = note
        self.requests: list[VLMColumnRequest] = []

    def resolve(self, request: VLMColumnRequest) -> VLMColumnResponse:
        self.requests.append(request)
        return VLMColumnResponse(roles=dict(self.answers), note=self.note)


def test_vlm_is_only_asked_about_low_confidence_columns():
    resolver = RecordingResolver({})
    mapper = ColumnMapper(vlm_resolver=resolver)
    rows, tokens, page, source = _load("khushi")
    mapper.map_document(rows, tokens, page, source)

    assert resolver.requests, "the resolver should have been consulted"
    request = resolver.requests[0]
    assert 4 in request.unresolved_columns       # 'Sales Ret.'
    assert 2 not in request.unresolved_columns   # 'Open. Qty.' is confident
    assert "opening_qty" in request.already_assigned.values()
    # It is asked for meaning, never for transcription.
    assert request.allowed_roles


def test_vlm_answer_is_applied_to_the_unresolved_column():
    resolver = RecordingResolver({6: "dump_qty"})
    mapper = ColumnMapper(vlm_resolver=resolver)
    rows, tokens, page, source = _load("khushi")
    document = mapper.map_document(rows, tokens, page, source)

    column = document.sections[0].columns[6]
    assert column.role is Role.DUMP_QTY
    assert column.method is MappingMethod.VLM
    assert column.confidence <= 0.75, "a VLM guess never outranks real evidence"


def test_vlm_cannot_invent_a_role_or_duplicate_one():
    resolver = RecordingResolver({4: "not_a_real_role", 6: "opening_qty"})
    mapper = ColumnMapper(vlm_resolver=resolver)
    rows, tokens, page, source = _load("khushi")
    document = mapper.map_document(rows, tokens, page, source)

    section = document.sections[0]
    assert section.columns[4].role is Role.UNKNOWN
    assert section.columns[6].role is Role.UNKNOWN, "opening_qty was already taken"
    assert [c.index for c in section.columns if c.role is Role.OPENING_QTY] == [2]


def test_a_failing_vlm_never_loses_the_page():
    class Exploding:
        def resolve(self, request):
            raise RuntimeError("service unavailable")

    mapper = ColumnMapper(vlm_resolver=Exploding())
    rows, tokens, page, source = _load("khushi")
    document = mapper.map_document(rows, tokens, page, source)

    assert document.sections[0].columns[2].role is Role.OPENING_QTY
    assert any("VLM resolver failed" in n for n in document.sections[0].notes)


def _load(name: str):
    from schema import load_grid
    return load_grid(load_raw(name))


# ---------------------------------------------------------------------------
# Raw layer integrity
# ---------------------------------------------------------------------------


def test_raw_layer_is_never_rewritten(bansal_p1):
    """Every cell's text must still match the source grid byte for byte."""
    raw = load_raw("bansal_p1")
    by_index = {r["index"]: r for r in raw["rows"]}
    section = bansal_p1.sections[0]

    for row in section.rows:
        source_row = by_index[row.index]
        for cell in row.cells:
            original = next(
                c for position, c in enumerate(source_row["cells"])
                if (c.get("column", position) if isinstance(c, dict) else position)
                == cell.column_index
            )
            text = original["text"] if isinstance(original, dict) else original
            assert cell.raw_text == text


def test_headers_keep_the_documents_own_words(khushi):
    headers = [c.header_text for c in khushi.sections[0].columns]
    assert "Sales & DC" in headers
    assert "Misc. Out" in headers
    assert "Open. Qty." in headers
