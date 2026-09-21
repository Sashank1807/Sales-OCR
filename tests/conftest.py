"""Shared fixtures: load the transcribed grids and run them through Stage A."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))

from column_mapper import map_grid          # noqa: E402
from schema import Document, Role, Row, Section  # noqa: E402


def load_raw(name: str) -> dict[str, Any]:
    """The grid JSON exactly as ``ocr_to_table.py`` would emit it."""
    with open(FIXTURES / f"{name}.json", "r", encoding="utf-8") as fh:
        return json.load(fh)


def mapped(name: str) -> Document:
    return map_grid(load_raw(name))


@pytest.fixture
def amar() -> Document:
    return mapped("amar")


@pytest.fixture
def amar_grand_total() -> Document:
    return mapped("amar_grand_total")


@pytest.fixture
def bansal_p1() -> Document:
    return mapped("bansal_p1")


@pytest.fixture
def bansal_p2() -> Document:
    return mapped("bansal_p2")


@pytest.fixture
def khushi() -> Document:
    return mapped("khushi")


@pytest.fixture
def krishna() -> Document:
    return mapped("krishna")


# -- helpers shared by both test modules ------------------------------------


def row_named(section: Section, needle: str) -> Row:
    """The data row whose description contains ``needle``."""
    for row in section.data_rows:
        if row.cells and needle.lower() in row.cells[0].raw_text.lower():
            return row
    raise AssertionError(f"no data row matching {needle!r}")


def value_of(section: Section, row: Row, role: Role):
    index = section.role_index(role)
    assert index is not None, f"{role.value} not mapped in this section"
    cell = row.cell_at(index)
    assert cell is not None, f"row has no cell for {role.value}"
    return cell


def roles_by_index(section: Section) -> dict[int, str]:
    return {c.index: c.role.value for c in section.columns}


def mutate_cell(raw: dict[str, Any], row_index: int, column: int, text: str) -> dict[str, Any]:
    """Copy a grid with one cell's text replaced, to simulate a misread."""
    grid = copy.deepcopy(raw)
    for row in grid["rows"]:
        if row.get("index") != row_index:
            continue
        for position, cell in enumerate(row["cells"]):
            index = cell.get("column", position) if isinstance(cell, dict) else position
            if index == column:
                if isinstance(cell, dict):
                    cell["text"] = text
                else:
                    row["cells"][position] = text
                return grid
    raise AssertionError(f"no cell at row {row_index} column {column}")
