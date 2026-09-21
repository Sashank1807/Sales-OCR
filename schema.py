"""Two-layer extraction schema with cell-level provenance.

The *raw layer* is every verbatim string the document actually contained, plus
the document's own column headings. It is never rewritten.

The *semantic layer* sits alongside it: canonical role tags, parsed numbers, and
validation status. Normalisation only ever adds fields; it never overwrites
``Cell.raw_text`` or ``ColumnMapping.header_text``.

Nothing in this module makes a network call, and no distributor-specific
constant appears anywhere in it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Iterator, Sequence

__all__ = [
    "Role", "CellStatus", "Source", "RowType", "SectionKind", "MappingMethod",
    "Provenance", "Cell", "ColumnProfile", "ColumnMapping", "Row", "Section",
    "DocumentMetadata", "MetadataField", "Document", "Finding",
    "parse_number", "is_blank_text", "normalise_header", "DETERMINISTIC_SOURCES",
    "QTY_ROLES", "VALUE_ROLES", "STOCK_FLOW_ROLES", "TEXTUAL_ROLES",
]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Role(str, Enum):
    """Canonical column roles. Deliberately generic - these are properties of
    stock statements in general, not of any particular distributor."""

    ITEM_DESCRIPTION = "item_description"
    CODE = "code"
    PACK = "pack"
    OPENING_QTY = "opening_qty"
    OPENING_VALUE = "opening_value"
    RECEIPT_QTY = "receipt_qty"
    RECEIPT_VALUE = "receipt_value"
    ISSUE_QTY = "issue_qty"
    ISSUE_VALUE = "issue_value"
    CLOSING_QTY = "closing_qty"
    CLOSING_VALUE = "closing_value"
    RATE = "rate"
    UNIT = "unit"
    DUMP_QTY = "dump_qty"
    UNKNOWN = "unknown"


QTY_ROLES = (Role.OPENING_QTY, Role.RECEIPT_QTY, Role.ISSUE_QTY, Role.CLOSING_QTY)
VALUE_ROLES = (Role.OPENING_VALUE, Role.RECEIPT_VALUE, Role.ISSUE_VALUE, Role.CLOSING_VALUE)
STOCK_FLOW_ROLES = frozenset(QTY_ROLES) | frozenset(VALUE_ROLES)
TEXTUAL_ROLES = frozenset({Role.ITEM_DESCRIPTION, Role.CODE, Role.PACK, Role.UNIT})


class CellStatus(str, Enum):
    """Per-cell outcome.

    The distinction that matters is between a value that *cannot* have been
    misread and one that merely has not been checked. Excel and a PDF text
    layer return the characters the file contains; there is no recognition step
    and therefore no reading error to catch. Collapsing that into
    ``UNCHECKED`` alongside a pixel-derived value nobody has verified overstates
    the review load enormously.

    ``UNCHECKED`` remains an honest answer for pixel-derived values: the
    document did not carry enough structure to verify this cell. It is never a
    synonym for "fine".
    """

    EXACT = "exact"           # deterministic source; not subject to misreading
    VERIFIED = "verified"     # recognised from pixels, then confirmed
    UNCHECKED = "unchecked"   # recognised from pixels, nothing to confirm it
    FLAGGED = "flagged"       # failed a check, or too uncertain to trust


#: Precedence when several checks touch the same cell.
#:
#: ``EXACT`` outranks ``VERIFIED`` so that confirming a deterministic cell by
#: arithmetic cannot quietly demote it to a weaker claim - the arithmetic adds
#: nothing to a value that was never in doubt. ``FLAGGED`` outranks everything,
#: because a deterministic cell can still sit in a row that does not balance.
_STATUS_RANK = {CellStatus.UNCHECKED: 0, CellStatus.VERIFIED: 1,
                CellStatus.EXACT: 2, CellStatus.FLAGGED: 3}


class Source(str, Enum):
    EXCEL = "excel"
    PDF_TEXT = "pdf_text"
    OCR = "ocr"
    VLM = "vlm"
    DERIVED = "derived"


#: Sources that return the characters a file contains rather than a reading of
#: pixels. A cell from one of these cannot be a misrecognition.
DETERMINISTIC_SOURCES = frozenset({Source.EXCEL, Source.PDF_TEXT})


class RowType(str, Enum):
    DATA = "data"
    HEADER = "header"
    TOTAL = "total"
    SECTION_TITLE = "section_title"
    METADATA = "metadata"
    BLANK = "blank"
    UNKNOWN = "unknown"


class SectionKind(str, Enum):
    TABULAR = "tabular"
    NON_TABULAR = "non_tabular"
    EMPTY = "empty"


class MappingMethod(str, Enum):
    HEADER_EXACT = "header_exact"
    HEADER_FUZZY = "header_fuzzy"
    ARITHMETIC = "arithmetic"
    HEADER_AND_ARITHMETIC = "header_and_arithmetic"
    PROFILE = "profile"
    VLM = "vlm"
    #: Taken from the header on an earlier page of the same file. A paginated
    #: report prints its column headings once; every page after the first
    #: carries the same columns under a repeated banner and nothing else.
    INHERITED = "inherited"
    NONE = "none"


# ---------------------------------------------------------------------------
# Text and number handling
# ---------------------------------------------------------------------------

#: Glyphs a report uses to mean "nil". Note these are *blank*, not zero - the
#: validator decides which blanks are genuine zeroes by testing the arithmetic.
_NIL_TOKENS = frozenset({"", "-", "--", "---", ".", "..", "...", "n/a", "na", "nil", "–", "—"})

_NUMBER_RE = re.compile(
    r"""^
    [(\[]?                       # optional bracket for negatives: (123)
    [+-]?                        # sign
    (?:\d{1,3}(?:,\d{2,3})+|\d+) # digits, tolerating Indian or Western grouping
    (?:\.\d*)?                   # decimals, or a bare trailing point: `34.`
    [)\]]?                       # closing bracket
    -?                           # trailing minus, as some ERPs print 123-
    $""",
    re.VERBOSE,
)

#: A quantity printed as a pair the parser cannot reduce to a single number:
#: ``60:0``, ``18:0``. Several ERPs write stock as ``units:free`` or
#: ``strips:loose``. The pair is recognised so that a row of them is not
#: mistaken for words, and deliberately never parsed - deciding which half is
#: the stock is the document's convention, not something to guess at.
_COMPOUND_QUANTITY_RE = re.compile(
    r"^[+-]?\d[\d,]*(?:\.\d+)?\s*:\s*\d[\d,]*(?:\.\d+)?$")
#: One printed figure, as a whitespace-separated part of a cell's text.
_PLAIN_FIGURE_RE = re.compile(r"^[+-]?(?:\d[\d,]*(?:\.\d*)?|\.\d+)$")


def is_blank_text(text: str | None) -> bool:
    """True for cells the document left empty, including its nil glyphs.

    A lone ``-`` means nil; ``-64`` is a negative number and is not blank.
    """
    if text is None:
        return True
    return text.strip().lower() in _NIL_TOKENS


def parse_number(text: str | None) -> Decimal | None:
    """Parse a cell into a Decimal, or None when it is not purely numeric.

    Anything carrying letters stays text, which is what keeps pack sizes
    (``1X10TAB``), units (``500MG.``, ``2MG/2I``) and codes out of the numeric
    pipeline entirely.
    """
    if text is None:
        return None
    raw = text.strip()
    if is_blank_text(raw):
        return None
    if not _NUMBER_RE.match(raw):
        return None

    negative = False
    if raw.startswith("(") and raw.endswith(")"):
        negative, raw = True, raw[1:-1]
    elif raw.startswith("[") and raw.endswith("]"):
        negative, raw = True, raw[1:-1]
    if raw.endswith("-"):
        negative, raw = True, raw[:-1]

    raw = raw.replace(",", "")
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return -value if negative else value


def normalise_header(text: str | None) -> str:
    """Lowercase, strip punctuation and collapse whitespace, for matching only.

    The original string is always retained on the column; this is a comparison
    key, not a replacement.
    """
    if not text:
        return ""
    cleaned = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


# ---------------------------------------------------------------------------
# Provenance and cells
# ---------------------------------------------------------------------------


@dataclass
class Provenance:
    """Where a value came from, precisely enough to go back and look."""

    source: Source = Source.OCR
    page: int = 1
    bbox: tuple[float, float, float, float] | None = None
    confidence: float | None = None
    token_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "page": self.page,
            "bbox": list(self.bbox) if self.bbox else None,
            "confidence": self.confidence,
            "token_ids": list(self.token_ids),
        }


@dataclass
class Cell:
    """One grid cell, raw layer and semantic layer together."""

    raw_text: str                                  # RAW - verbatim, immutable
    column_index: int
    provenance: Provenance = field(default_factory=Provenance)
    value: Decimal | None = None                   # SEMANTIC
    status: CellStatus = CellStatus.UNCHECKED
    reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.value is None:
            self.value = parse_number(self.raw_text)
        # The source decides this, once, at construction. Nothing downstream
        # may promote a pixel-derived cell to EXACT or demote a deterministic
        # one - which is why it is not left to the validator to assign.
        if self.status is CellStatus.UNCHECKED and self.is_deterministic:
            self.status = CellStatus.EXACT

    @property
    def is_deterministic(self) -> bool:
        """True when the value came from a file, not from reading pixels."""
        return self.provenance.source in DETERMINISTIC_SOURCES

    @property
    def needs_review(self) -> bool:
        """Whether a human has to look at this cell.

        A deterministic cell that failed a *structural* check still needs
        attention - but that is a layout or mapping fault, not a transcription
        one, so callers separate the two.
        """
        return self.status in (CellStatus.FLAGGED, CellStatus.UNCHECKED)

    @property
    def is_blank(self) -> bool:
        return is_blank_text(self.raw_text)

    @property
    def is_numeric(self) -> bool:
        return self.value is not None

    @property
    def is_compound_quantity(self) -> bool:
        """A figure pair the parser cannot reduce to one number, e.g. ``60:0``.

        Not numeric - there is no single value here - but not text either, and
        the difference matters: a row of these scored as prose, so a data row
        was mistaken for a header, split its table in two and took a genuine
        row of stock with it.
        """
        return bool(_COMPOUND_QUANTITY_RE.match(self.raw_text.strip()))

    @property
    def holds_several_figures(self) -> bool:
        """Two or more separate figures in one cell: `814 1`, `-2121 0 -482`.

        One cell holds one value. Several figures side by side mean the
        columns they belong to were not told apart, and each figure sits
        under a heading that is not its own. `28710 S 21547 E 0` counts too:
        most of its parts are figures. `60:0` does not - that is one compound
        quantity - and neither does `1X15 GM`.
        """
        if self.is_compound_quantity:
            return False
        parts = self.raw_text.split()
        figures = sum(1 for p in parts if _PLAIN_FIGURE_RE.match(p))
        return figures >= 2 and figures * 2 >= len(parts)

    @property
    def looks_quantitative(self) -> bool:
        """True for anything holding figures, whether or not it parsed."""
        return self.is_numeric or self.is_compound_quantity

    def mark(self, status: CellStatus, reason: str) -> None:
        """Record an outcome. Flags win over verifications; nothing is erased.

        ``EXACT`` is not assignable here. It is a statement about where the
        value came from, settled at construction, and precedence alone cannot
        protect it: EXACT outranks UNCHECKED, so a caller marking a
        pixel-derived cell EXACT would otherwise promote it and claim the value
        could not have been misread.
        """
        if reason and reason not in self.reasons:
            self.reasons.append(reason)
        if status is CellStatus.EXACT and not self.is_deterministic:
            return
        if _STATUS_RANK[status] > _STATUS_RANK[self.status]:
            self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "column_index": self.column_index,
            "value": str(self.value) if self.value is not None else None,
            "is_blank": self.is_blank,
            "is_numeric": self.is_numeric,
            "status": self.status.value,
            "reasons": list(self.reasons),
            "provenance": self.provenance.to_dict(),
        }


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------


@dataclass
class ColumnProfile:
    """What the data in a column actually looks like, independent of its label."""

    index: int
    total_cells: int = 0
    blank_cells: int = 0
    numeric_cells: int = 0
    text_cells: int = 0
    packlike_cells: int = 0
    max_decimals: int = 0
    modal_decimals: int = 0
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    mean_abs: Decimal | None = None
    has_negative: bool = False
    sample_texts: list[str] = field(default_factory=list)

    @property
    def populated(self) -> int:
        return self.total_cells - self.blank_cells

    @property
    def numeric_ratio(self) -> float:
        return self.numeric_cells / self.populated if self.populated else 0.0

    @property
    def is_numeric(self) -> bool:
        return self.populated > 0 and self.numeric_ratio >= 0.8

    @property
    def is_textual(self) -> bool:
        return self.populated > 0 and self.numeric_ratio <= 0.2

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for key in ("min_value", "max_value", "mean_abs"):
            d[key] = str(d[key]) if d[key] is not None else None
        d["numeric_ratio"] = round(self.numeric_ratio, 3)
        d["is_numeric"] = self.is_numeric
        return d


@dataclass
class ColumnMapping:
    """A column's raw heading and the semantic role inferred for it."""

    index: int
    header_text: str = ""                          # RAW - the document's words
    role: Role = Role.UNKNOWN
    confidence: float = 0.0
    method: MappingMethod = MappingMethod.NONE
    evidence: list[str] = field(default_factory=list)
    profile: ColumnProfile | None = None
    header_parts: list[str] = field(default_factory=list)
    #: True when the heading itself said "qty"/"value"; False when the measure
    #: was inferred from the data's shape and so is the weaker claim.
    measure_from_header: bool = False
    #: True when this column carries a stock movement the canonical role set
    #: cannot express (a transfer, an adjustment). It balances the row equation
    #: but has no role, and must not be forced into one.
    adjustment_column: bool = False
    #: True when this column's role was taken from an equation that cannot
    #: distinguish it from another column's role - the issue/closing pair with
    #: no heading to orient them. The values may be sound while the label is a
    #: coin flip, so the role must not be trusted downstream.
    orientation_ambiguous: bool = False

    def add_evidence(self, note: str) -> None:
        if note and note not in self.evidence:
            self.evidence.append(note)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "header_text": self.header_text,
            "header_parts": list(self.header_parts),
            "role": self.role.value,
            "confidence": round(self.confidence, 3),
            "method": self.method.value,
            "evidence": list(self.evidence),
            "profile": self.profile.to_dict() if self.profile else None,
        }


# ---------------------------------------------------------------------------
# Rows, sections, documents
# ---------------------------------------------------------------------------


@dataclass
class Row:
    index: int
    cells: list[Cell] = field(default_factory=list)
    row_type: RowType = RowType.UNKNOWN
    bbox: tuple[float, float, float, float] | None = None
    reasons: list[str] = field(default_factory=list)

    def cell_at(self, column_index: int) -> Cell | None:
        for cell in self.cells:
            if cell.column_index == column_index:
                return cell
        return None

    @property
    def text(self) -> str:
        return " ".join(c.raw_text for c in self.cells if c.raw_text.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "row_type": self.row_type.value,
            "bbox": list(self.bbox) if self.bbox else None,
            "reasons": list(self.reasons),
            "cells": [c.to_dict() for c in self.cells],
        }


@dataclass
class Section:
    """One table (or non-tabular block) on a page."""

    index: int
    kind: SectionKind = SectionKind.TABULAR
    title: str = ""
    header_row_indices: list[int] = field(default_factory=list)
    #: The header row objects themselves. Their cells belong to the page and
    #: must stay visible to the coverage check, even though their meaning is
    #: carried by ColumnMapping.header_text rather than by a data row.
    header_rows: list[Row] = field(default_factory=list)
    #: How many columns the header itself defines. Data rows reaching past this
    #: imply cells the header cannot account for.
    header_column_count: int = 0
    #: Columns past the last heading that most rows populate anyway. They are
    #: real columns the header failed to name, not cells that overflowed it,
    #: and the distinction decides whether their contents are flagged.
    unheaded_columns: list[int] = field(default_factory=list)
    columns: list[ColumnMapping] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Movement columns outside the canonical four that the row equation needs
    #: in order to balance, each as (column index, sign, "qty" | "value"). Stage
    #: B includes them so the equation can be verified rather than abandoned.
    #: Usually none or one (a transfer); two where a report prints free goods
    #: on both sides - free with purchase added, free with sale subtracted.
    adjustments: list[tuple[int, int, str]] = field(default_factory=list)
    #: The structural measurements behind the tabular/non-tabular verdict, so
    #: the decision can be audited rather than taken on trust.
    tabular_signals: dict[str, Any] = field(default_factory=dict)

    @property
    def data_rows(self) -> list[Row]:
        return [r for r in self.rows if r.row_type is RowType.DATA]

    @property
    def total_rows(self) -> list[Row]:
        return [r for r in self.rows if r.row_type is RowType.TOTAL]

    def column_for_role(self, role: Role) -> ColumnMapping | None:
        for col in self.columns:
            if col.role is role:
                return col
        return None

    def role_index(self, role: Role) -> int | None:
        col = self.column_for_role(role)
        return col.index if col else None

    def roles_present(self) -> set[Role]:
        return {c.role for c in self.columns if c.role is not Role.UNKNOWN}

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "kind": self.kind.value,
            "title": self.title,
            "header_row_indices": list(self.header_row_indices),
            "unheaded_columns": list(self.unheaded_columns),
            "notes": list(self.notes),
            "adjustments": [list(a) for a in self.adjustments],
            "tabular_signals": dict(self.tabular_signals),
            "columns": [c.to_dict() for c in self.columns],
            "rows": [r.to_dict() for r in self.rows],
        }


@dataclass
class MetadataField:
    value: str
    provenance: Provenance = field(default_factory=Provenance)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(self.confidence, 3),
            "provenance": self.provenance.to_dict(),
        }


@dataclass
class DocumentMetadata:
    distributor_name: MetadataField | None = None
    address: MetadataField | None = None
    phone: MetadataField | None = None
    email: MetadataField | None = None
    gstin: MetadataField | None = None
    manufacturer: MetadataField | None = None
    period_from: MetadataField | None = None
    period_to: MetadataField | None = None
    extra: dict[str, MetadataField] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in ("distributor_name", "address", "phone", "email", "gstin",
                    "manufacturer", "period_from", "period_to"):
            value = getattr(self, key)
            out[key] = value.to_dict() if value else None
        out["extra"] = {k: v.to_dict() for k, v in self.extra.items()}
        return out


@dataclass
class Document:
    page: int = 1
    source: Source = Source.OCR
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    sections: list[Section] = field(default_factory=list)
    tokens: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Rows above the first header - the letterhead, address, GSTIN, period.
    #: They belong to no table, but their numbers were still read, so the
    #: coverage check has to see them or it reports every phone number as lost.
    preamble_rows: list[Row] = field(default_factory=list)

    def iter_cells(self) -> Iterator[tuple[Section, Row, Cell]]:
        for section in self.sections:
            for row in section.rows:
                for cell in row.cells:
                    yield section, row, cell

    def iter_all_cells(self) -> Iterator[Cell]:
        """Every cell read from the page: preamble, headers and rows."""
        for row in self.preamble_rows:
            for cell in row.cells:
                yield cell
        for section in self.sections:
            for row in section.header_rows:
                for cell in row.cells:
                    yield cell
        for _, _, cell in self.iter_cells():
            yield cell

    def tabular_sections(self) -> list[Section]:
        return [s for s in self.sections if s.kind is SectionKind.TABULAR]

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "source": self.source.value,
            "metadata": self.metadata.to_dict(),
            "notes": list(self.notes),
            "sections": [s.to_dict() for s in self.sections],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Validation findings
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """One validation outcome, addressed to the cells it concerns."""

    check: str
    status: CellStatus
    message: str
    section_index: int | None = None
    row_index: int | None = None
    column_indices: list[int] = field(default_factory=list)
    expected: str | None = None
    actual: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "status": self.status.value,
            "message": self.message,
            "section_index": self.section_index,
            "row_index": self.row_index,
            "column_indices": list(self.column_indices),
            "expected": self.expected,
            "actual": self.actual,
        }


# ---------------------------------------------------------------------------
# Grid loading
# ---------------------------------------------------------------------------


def _cell_from_raw(raw: Any, index: int, page: int, default_source: Source) -> Cell:
    """Accept either a bare string or a full cell object from the grid."""
    if isinstance(raw, str):
        return Cell(raw_text=raw, column_index=index,
                    provenance=Provenance(source=default_source, page=page))
    if raw is None:
        return Cell(raw_text="", column_index=index,
                    provenance=Provenance(source=default_source, page=page))

    text = str(raw.get("text", raw.get("raw_text", "")) or "")
    bbox = raw.get("bbox")
    source_name = raw.get("source")
    try:
        source = Source(source_name) if source_name else default_source
    except ValueError:
        source = default_source
    return Cell(
        raw_text=text,
        column_index=int(raw.get("column", raw.get("column_index", index))),
        provenance=Provenance(
            source=source,
            page=page,
            bbox=tuple(bbox) if bbox else None,   # type: ignore[arg-type]
            confidence=raw.get("confidence"),
            token_ids=list(raw.get("token_ids", []) or []),
        ),
    )


def load_grid(payload: dict[str, Any]) -> tuple[list[Row], list[dict[str, Any]], int, Source]:
    """Load the grid emitted by ``ocr_to_table.py``.

    Expected shape (every field but ``rows`` is optional)::

        {
          "page": 1,
          "source": "ocr" | "pdf_text" | "excel",
          "tokens": [{"text": "...", "bbox": [...], "confidence": 0.97}],
          "rows": [
            {"index": 0, "bbox": [...], "cells": [
                {"text": "AD 10 SACHETS", "bbox": [...], "confidence": 0.98}
            ]}
          ]
        }

    Cells may also be bare strings, so a minimal grid is easy to hand-write.
    """
    page = int(payload.get("page", 1))
    try:
        source = Source(payload.get("source", "ocr"))
    except ValueError:
        source = Source.OCR

    rows: list[Row] = []
    for i, raw_row in enumerate(payload.get("rows", []) or []):
        if isinstance(raw_row, list):
            raw_cells: Sequence[Any] = raw_row
            bbox = None
            index = i
        else:
            raw_cells = raw_row.get("cells", []) or []
            bbox = raw_row.get("bbox")
            index = int(raw_row.get("index", i))
        cells = [_cell_from_raw(c, j, page, source) for j, c in enumerate(raw_cells)]
        rows.append(Row(index=index, cells=cells,
                        bbox=tuple(bbox) if bbox else None))  # type: ignore[arg-type]

    tokens = list(payload.get("tokens", []) or [])
    return rows, tokens, page, source


def load_grid_file(path: str) -> tuple[list[Row], list[dict[str, Any]], int, Source]:
    with open(path, "r", encoding="utf-8") as fh:
        return load_grid(json.load(fh))
