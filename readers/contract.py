"""The grid contract every reader emits.

One shape, whatever the input was. ``Grid.to_dict()`` produces exactly the
payload ``schema.load_grid`` already consumes, so Stage A never learns which
reader produced a page.

The contract carries three things Stage A and Stage B depend on:

``bbox``        coordinates, which drive two-tier header merging and let a
                reviewer find the value on the page
``confidence``  per cell; 1.0 for Excel and PDF text layers, the recogniser's
                own score for OCR - never flattened
``tokens``      the atomic units the reader saw, which the coverage check
                compares against what reached the output
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

__all__ = ["Token", "GridCell", "GridRow", "Grid", "SOURCE_KINDS"]

#: The three ways a page can be read. Mirrors ``schema.Source``.
SOURCE_KINDS = ("excel", "pdf_text", "ocr")


@dataclass
class Token:
    """One atomic unit as the reader saw it, before any table structure."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float = 1.0
    index: int = -1

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "bbox": list(self.bbox),
                "confidence": self.confidence, "index": self.index}


@dataclass
class GridCell:
    text: str
    column: int
    bbox: tuple[float, float, float, float] | None = None
    confidence: float | None = None
    token_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": self.text, "column": self.column}
        if self.bbox is not None:
            payload["bbox"] = [round(v, 2) for v in self.bbox]
        if self.confidence is not None:
            payload["confidence"] = round(self.confidence, 4)
        if self.token_ids:
            payload["token_ids"] = list(self.token_ids)
        return payload


@dataclass
class GridRow:
    index: int
    cells: list[GridCell] = field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(c.text for c in self.cells if c.text.strip())

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"index": self.index,
                                   "cells": [c.to_dict() for c in self.cells]}
        if self.bbox is not None:
            payload["bbox"] = [round(v, 2) for v in self.bbox]
        return payload


@dataclass
class Grid:
    """A single page, reconstructed into rows and columns."""

    page: int = 1
    source: str = "ocr"
    rows: list[GridRow] = field(default_factory=list)
    tokens: list[Token] = field(default_factory=list)
    origin: str = ""
    page_label: str = ""
    notes: list[str] = field(default_factory=list)
    column_bands: list[tuple[float, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.source not in SOURCE_KINDS:
            raise ValueError(f"source must be one of {SOURCE_KINDS}, got {self.source!r}")

    def to_dict(self) -> dict[str, Any]:
        """The payload Stage A consumes. Nothing is added that it ignores."""
        return {
            "page": self.page,
            "source": self.source,
            "origin": self.origin,
            "page_label": self.page_label,
            "notes": list(self.notes),
            "tokens": [t.to_dict() for t in self.tokens],
            "rows": [r.to_dict() for r in self.rows],
        }

    def to_json(self, indent: int = 1) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @property
    def cell_count(self) -> int:
        return sum(len(r.cells) for r in self.rows)
