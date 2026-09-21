"""Stage B - verify every value the document's own structure permits.

The contract is *zero silent errors*, not perfect extraction. Every cell leaves
this stage as one of:

``verified``   arithmetic or a cross-check proved it consistent
``flagged``    something is demonstrably wrong, or could not be trusted
``unchecked``  the document carried no structure capable of testing it

``unchecked`` is never a synonym for "fine". It is a statement that a human
must look if this value matters.

Invariants are *tested*, not assumed. The row equation is adopted only if it
actually holds across a document's rows; when it holds on 68 of 70 rows, the
two exceptions are flagged rather than the page being rejected.

One subtlety drives most of the correctness here: rows with no movement
(``receipt == issue == 0``) satisfy ``opening + receipt - issue = closing``
trivially, under *any* relationship. Counting them when deciding whether an
invariant applies would make value columns that never reconcile look as if they
do. They are therefore excluded from support estimation, but still checked once
an invariant has been adopted.

Run standalone::

    python validator.py grid.json --report
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Sequence

from schema import (
    Cell, CellStatus, Document, Finding, MappingMethod, Role, Row, RowType, Section,
    SectionKind,
    QTY_ROLES, TEXTUAL_ROLES, VALUE_ROLES, parse_number,
)
from column_mapper import map_grid_file

__all__ = [
    "Validator", "ValidatorConfig", "ValidationContext", "ValidationReport",
    "InvariantResult", "CoverageReport", "gstin_check_digit", "is_valid_gstin",
    "validate_document", "validate_pages",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class ValidatorConfig:
    #: OCR confidence below which a cell is flagged regardless of arithmetic.
    min_confidence: float = 0.80
    #: Absolute tolerance for quantity-style equality.
    numeric_tolerance: Decimal = Decimal("0.01")
    #: Rate check: the larger of these two wins.
    rate_rel_tolerance: Decimal = Decimal("0.001")     # 0.1%
    rate_abs_tolerance: Decimal = Decimal("0.10")
    #: Fraction of informative rows an invariant must satisfy to be adopted.
    invariant_support: float = 0.70
    #: The same, when headings name every column of the stock equation. The
    #: support threshold guards against adopting a relationship that only holds
    #: by coincidence; when the document itself labels opening, receipt, issue
    #: and closing, that the stock equation applies is given, and the rows only
    #: have to show that the columns were read where they sit. A majority does
    #: that, and every row outside it is flagged rather than left unchecked.
    anchored_invariant_support: float = 0.50
    #: Rows with movement needed before the anchored threshold may be used.
    anchored_min_rows: int = 4
    #: Fewer informative rows than this and the invariant is left untested.
    min_rows_for_invariant: int = 2
    #: Printed total further than this multiple from the column sum is taken to
    #: be a different measure entirely rather than an extraction error.
    total_magnitude_factor: Decimal = Decimal("10")
    #: Tolerance for matching a printed total against a column sum.
    total_tolerance: Decimal = Decimal("0.05")
    #: Rows a column must contribute before an unnamed column's sum may be
    #: matched against a printed figure. A total that equals the sum of three
    #: or more figures is arithmetic; one that equals a single figure below it
    #: is a coincidence waiting to happen.
    column_sum_min_rows: int = 3


@dataclass
class ValidationContext:
    """Carried between pages so cumulative totals can be recognised."""

    #: role value -> running total printed on earlier pages of this document
    previous_totals: dict[str, Decimal] = field(default_factory=dict)
    #: role value -> sum of the data rows on earlier pages of this document.
    #: A report that prints its total once, on the last page, totals every page
    #: rather than the page it sits on: measured over 61 multi-page files of
    #: the MAY corpus, 37 of 212 printed totals are this and no other rule
    #: recognised them.
    previous_row_sums: dict[str, Decimal] = field(default_factory=dict)
    page_label: str = ""


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class InvariantResult:
    name: str
    adopted: bool
    informative_rows: int
    agreeing_rows: int
    degenerate_rows: int
    reason: str = ""

    @property
    def support(self) -> float:
        return self.agreeing_rows / self.informative_rows if self.informative_rows else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "adopted": self.adopted,
            "informative_rows": self.informative_rows,
            "agreeing_rows": self.agreeing_rows,
            "degenerate_rows": self.degenerate_rows,
            "support": round(self.support, 3),
            "reason": self.reason,
        }


@dataclass
class CoverageReport:
    tokens_seen: int = 0
    numeric_tokens_seen: int = 0
    numeric_tokens_placed: int = 0
    missing: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def ratio(self) -> float:
        if not self.numeric_tokens_seen:
            return 1.0
        return self.numeric_tokens_placed / self.numeric_tokens_seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens_seen": self.tokens_seen,
            "numeric_tokens_seen": self.numeric_tokens_seen,
            "numeric_tokens_placed": self.numeric_tokens_placed,
            "ratio": round(self.ratio, 4),
            "complete": self.complete,
            "missing": list(self.missing[:50]),
        }


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)
    invariants: list[InvariantResult] = field(default_factory=list)
    coverage: CoverageReport = field(default_factory=CoverageReport)
    counts: dict[str, int] = field(default_factory=dict)
    totals_by_role: dict[str, str] = field(default_factory=dict)

    @property
    def flagged(self) -> list[Finding]:
        return [f for f in self.findings if f.status is CellStatus.FLAGGED]

    @property
    def ok(self) -> bool:
        """True only when nothing at all was flagged."""
        return not self.flagged

    @property
    def review_cells(self) -> int:
        """Pixel-derived cells a human must look at. Excludes ``exact``."""
        return self.counts.get("review_cells", 0)

    @property
    def structural_flags(self) -> int:
        """Deterministic cells flagged for a layout or mapping fault."""
        return self.counts.get("structural_flags", 0)

    def invariant(self, name: str) -> InvariantResult | None:
        for inv in self.invariants:
            if inv.name == name:
                return inv
        return None

    def findings_for_check(self, check: str) -> list[Finding]:
        return [f for f in self.findings if f.check == check]

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": dict(self.counts),
            "coverage": self.coverage.to_dict(),
            "invariants": [i.to_dict() for i in self.invariants],
            "totals_by_role": dict(self.totals_by_role),
            "findings": [f.to_dict() for f in self.findings],
        }


# ---------------------------------------------------------------------------
# GSTIN
# ---------------------------------------------------------------------------

_GSTIN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_GSTIN_SHAPE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")


def gstin_check_digit(first_fourteen: str) -> str:
    """Compute the 15th character of a GSTIN.

    Each character's value in base 36 is multiplied by an alternating factor of
    1 and 2; the digits of each product (in base 36) are summed, and the check
    character is whatever brings that sum up to the next multiple of 36.
    """
    if len(first_fourteen) != 14:
        raise ValueError("GSTIN prefix must be exactly 14 characters")
    total = 0
    for position, char in enumerate(first_fourteen.upper()):
        try:
            value = _GSTIN_ALPHABET.index(char)
        except ValueError as exc:
            raise ValueError(f"invalid GSTIN character {char!r}") from exc
        factor = 2 if position % 2 else 1
        product = value * factor
        total += product // 36 + product % 36
    return _GSTIN_ALPHABET[(36 - total % 36) % 36]


def is_valid_gstin(gstin: str) -> bool:
    """Shape plus checksum. Both must hold."""
    candidate = (gstin or "").strip().upper()
    if len(candidate) != 15 or not _GSTIN_SHAPE.match(candidate):
        return False
    try:
        return gstin_check_digit(candidate[:14]) == candidate[14]
    except ValueError:
        return False


_DATE_PATTERNS = (
    (re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$"), "dmy"),
    (re.compile(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$"), "ymd"),
    (re.compile(r"^(\d{1,2})[/-]([A-Za-z]{3,9})[/-](\d{4})$"), "dMy"),
)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def is_valid_date(text: str) -> bool:
    candidate = (text or "").strip()
    for pattern, order in _DATE_PATTERNS:
        match = pattern.match(candidate)
        if not match:
            continue
        a, b, c = match.groups()
        if order == "dmy":
            day, month, year = int(a), int(b), int(c)
        elif order == "ymd":
            year, month, day = int(a), int(b), int(c)
        else:
            month = _MONTHS.get(b[:3].lower(), 0)
            day, year = int(a), int(c)
        return 1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2999
    return False


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

_ROLE_GROUPS: tuple[tuple[str, tuple[Role, Role, Role, Role]], ...] = (
    ("row_equation_qty", QTY_ROLES),
    ("row_equation_value", VALUE_ROLES),
)


class Validator:
    """Runs every check the document's structure permits."""

    def __init__(self, config: ValidatorConfig | None = None) -> None:
        self.config = config or ValidatorConfig()

    # -- entry point ------------------------------------------------------

    def validate(self, doc: Document,
                 context: ValidationContext | None = None) -> ValidationReport:
        context = context or ValidationContext()
        report = ValidationReport()

        for section in doc.sections:
            self._check_row_shape(section, report)
            self._check_unmodelled_quantities(section, report)
            if section.kind is SectionKind.EMPTY:
                report.findings.append(Finding(
                    check="empty_section", status=CellStatus.UNCHECKED,
                    section_index=section.index,
                    message="section has column headers but no data rows; "
                            "returned empty"))
                continue
            if section.kind is SectionKind.NON_TABULAR:
                self._mark_section(section, CellStatus.UNCHECKED,
                                   "non_tabular_section")
                report.findings.append(Finding(
                    check="non_tabular_section", status=CellStatus.UNCHECKED,
                    section_index=section.index,
                    message="no stock-flow columns; arithmetic checks not applicable"))
                continue

            for name, roles in _ROLE_GROUPS:
                invariant = self._check_row_equation(section, roles, name, report)
                self._check_total_row_equation(section, roles, name, report, invariant)
            self._check_column_orientation(section, report)
            self._check_rate(section, report)
            self._check_totals(section, report, context)
            self._check_merged_figures(section, report)

        self._check_confidence(doc, report)
        self._check_metadata_formats(doc, report)
        self._check_coverage(doc, report)
        self._tally(doc, report)
        return report

    # -- row shape --------------------------------------------------------

    def _check_row_shape(self, section: Section, report: ValidationReport) -> None:
        """Compare each row's shape against the header.

        The grid addresses cells by column index, so a *sparse* row is a
        legitimate way to express blanks and is reported without being flagged.

        "Past the last column" used to mean past the last *heading*, which
        conflated two faults of very different kinds. A column that almost
        every row populates is one the header failed to name - Stage A records
        those in ``unheaded_columns``, and their cells are sound, merely
        anonymous. Flagging them cost 194 exact cells on a single sheet for
        what was one fact about the header. What remains - a column one or two
        rows reach and nobody else does - is a genuinely ragged row, and that
        is what is flagged here.
        """
        headed = section.header_column_count or len(section.columns)
        if not headed:
            return
        known = set(range(headed)) | set(section.unheaded_columns)
        width = len(known)

        if section.unheaded_columns:
            report.findings.append(Finding(
                check="row_shape", status=CellStatus.UNCHECKED,
                section_index=section.index,
                column_indices=list(section.unheaded_columns),
                message=f"columns {section.unheaded_columns} hold data under no "
                        "heading; the values are read, but nothing names them, "
                        "so they carry no role and take part in no check",
                expected=f"{headed} headed column(s)",
                actual=f"{width} column(s) in use"))

        for row in section.rows:
            if row.row_type not in (RowType.DATA, RowType.TOTAL):
                continue
            actual = len(row.cells)
            overflow = [c for c in row.cells if c.column_index not in known]

            if overflow or actual > width:
                for cell in (overflow or row.cells):
                    cell.mark(CellStatus.FLAGGED, "row_shape_overflow")
                report.findings.append(Finding(
                    check="row_shape", status=CellStatus.FLAGGED,
                    section_index=section.index, row_index=row.index,
                    column_indices=[c.column_index for c in overflow],
                    message=f"row carries {actual} cells against {width} columns"
                            + (f", {len(overflow)} in no column the section has"
                               if overflow else ""),
                    expected=str(width), actual=str(actual)))
            elif actual != width:
                report.findings.append(Finding(
                    check="row_shape", status=CellStatus.UNCHECKED,
                    section_index=section.index, row_index=row.index,
                    message=f"row is sparse: {actual} of {width} columns present",
                    expected=str(width), actual=str(actual)))

    # -- quantities the parser cannot reduce -------------------------------

    def _check_unmodelled_quantities(self, section: Section,
                                     report: ValidationReport) -> None:
        """Report columns printed as figure pairs that cannot be parsed.

        ``60:0`` is a quantity and a free quantity in one cell. Which half is
        the stock is the document's own convention, so it is never guessed at.
        But a column full of them takes part in no arithmetic, and without
        this the page would pass as clean ``exact`` cells that nothing had
        actually understood - the reading is right and the meaning is absent,
        which is precisely the case a green metric hides.
        """
        for column in section.columns:
            cells = [row.cell_at(column.index) for row in section.rows
                     if row.row_type in (RowType.DATA, RowType.TOTAL)]
            present = [c for c in cells if c is not None and not c.is_blank]
            if len(present) < 2:
                continue
            compound = [c for c in present if c.is_compound_quantity]
            if not compound:
                continue

            for cell in compound:
                cell.mark(CellStatus.UNCHECKED, "compound_quantity_not_modelled")
            report.findings.append(Finding(
                check="unmodelled_quantity", status=CellStatus.UNCHECKED,
                section_index=section.index, column_indices=[column.index],
                message=f"column {column.index} ({column.header_text!r}) is "
                        f"printed as quantity pairs such as "
                        f"{compound[0].raw_text!r}. The text is read verbatim, "
                        "but splitting it would mean guessing which half is the "
                        "stock, so the column takes part in no arithmetic check",
                expected="one number per cell",
                actual=f"{len(compound)} of {len(present)} cells are pairs"))

    # -- row equation -----------------------------------------------------

    def _group_cells(self, section: Section, row: Row,
                     roles: Sequence[Role]) -> list[Cell | None] | None:
        indices = [section.role_index(r) for r in roles]
        if any(i is None for i in indices):
            return None
        return [row.cell_at(i) for i in indices]  # type: ignore[arg-type]

    def _adjustment_for(self, section: Section, name: str) -> list[tuple[int, int]]:
        """The extra movement columns this role group has to account for.

        Some ERPs post transfers, corrections or free goods in columns of their
        own. Stage A discovers them; ignoring them here would fail every row
        that used one.
        """
        return [(column, sign) for column, sign, measure in section.adjustments
                if name == f"row_equation_{measure}"]

    @staticmethod
    def _adjustment_value(row: Row, adjustment: list[tuple[int, int]]) -> Decimal:
        total = Decimal(0)
        for column, sign in adjustment or []:
            cell = row.cell_at(column)
            value = cell.value if cell is not None and cell.is_numeric else None
            total += sign * (value or Decimal(0))
        return total

    @staticmethod
    def _with_adjustments(row: Row, cells: list[Cell | None],
                          adjustment: list[tuple[int, int]]) -> list[Cell | None]:
        """The cells a row's equation outcome speaks for.

        A free-quantity column that balances the row took part in the check as
        much as the closing column did: if the row holds, it is confirmed; if
        the row fails, it is as likely as any of the four to be the misread.
        """
        return list(cells) + [row.cell_at(column) for column, _ in adjustment or []]

    def _check_row_equation(self, section: Section, roles: Sequence[Role],
                            name: str, report: ValidationReport) -> InvariantResult:
        """Test, then adopt or reject, ``opening + receipt - issue = closing``."""
        cfg = self.config
        indices = [section.role_index(r) for r in roles]
        if any(i is None for i in indices):
            missing = InvariantResult(
                name=name, adopted=False, informative_rows=0, agreeing_rows=0,
                degenerate_rows=0,
                reason="required columns not all present in this section")
            report.invariants.append(missing)
            return missing

        adjustment = self._adjustment_for(section, name)
        informative = agreeing = degenerate = 0
        outcomes: list[tuple[Row, bool | None, bool]] = []

        for row in section.data_rows:
            cells = self._group_cells(section, row, roles)
            if cells is None:
                continue
            o, r, i, c = (_val(x) for x in cells)
            present = sum(1 for v in (o, r, i, c) if v is not None)
            if present < 2:
                outcomes.append((row, None, False))
                continue

            ov, rv, iv, cv = (v or Decimal(0) for v in (o, r, i, c))
            av = self._adjustment_value(row, adjustment)
            holds = abs((ov + rv - iv + av) - cv) <= cfg.numeric_tolerance
            # A row with no movement satisfies the equation under any
            # relationship, so it says nothing about whether one exists.
            is_degenerate = rv == 0 and iv == 0 and av == 0
            outcomes.append((row, holds, is_degenerate))
            if is_degenerate:
                degenerate += 1
            else:
                informative += 1
                agreeing += 1 if holds else 0

        # Whether headings - not arithmetic - named all four columns.
        anchored = all(
            section.columns[i].method in _HEADER_METHODS
            for i in indices if i is not None and i < len(section.columns))
        support_needed = (cfg.anchored_invariant_support
                          if anchored and informative >= cfg.anchored_min_rows
                          else cfg.invariant_support)

        if informative < cfg.min_rows_for_invariant:
            result = InvariantResult(
                name=name, adopted=False, informative_rows=informative,
                agreeing_rows=agreeing, degenerate_rows=degenerate,
                reason=f"only {informative} rows with actual movement; "
                       "too few to establish the relationship")
        elif (agreeing / informative) >= support_needed and agreeing * 2 > informative:
            result = InvariantResult(
                name=name, adopted=True, informative_rows=informative,
                agreeing_rows=agreeing, degenerate_rows=degenerate,
                reason=("relationship holds across the section"
                        if support_needed == cfg.invariant_support else
                        "headings name every column of the equation, and it holds "
                        "on most rows; the rest are flagged as likely misreads"))
        else:
            result = InvariantResult(
                name=name, adopted=False, informative_rows=informative,
                agreeing_rows=agreeing, degenerate_rows=degenerate,
                reason=f"relationship holds on only {agreeing}/{informative} rows "
                       "with movement; not an invariant for this document")
        report.invariants.append(result)

        column_indices = [i for i in indices if i is not None]
        if not result.adopted:
            for row, _, _ in outcomes:
                cells = self._group_cells(section, row, roles)
                for cell in cells or []:
                    if cell is not None:
                        cell.mark(CellStatus.UNCHECKED, f"{name}_not_applicable")
            report.findings.append(Finding(
                check=name, status=CellStatus.UNCHECKED,
                section_index=section.index, column_indices=column_indices,
                message=result.reason,
                actual=f"{agreeing}/{informative} informative rows"))
            return result

        report.findings.append(Finding(
            check=name, status=CellStatus.VERIFIED,
            section_index=section.index, column_indices=column_indices,
            message=f"{result.reason} ({agreeing}/{informative} informative rows, "
                    f"{degenerate} with no movement)"))

        for row, holds, _ in outcomes:
            cells = self._group_cells(section, row, roles)
            if cells is None:
                continue
            quad = cells
            cells = self._with_adjustments(row, cells, adjustment)
            if holds is None:
                for cell in cells:
                    if cell is not None:
                        cell.mark(CellStatus.UNCHECKED, f"{name}_row_too_sparse")
                continue
            if holds:
                for cell in cells:
                    if cell is None:
                        continue
                    if cell.is_blank:
                        # The equation works with this read as zero, so it is a
                        # genuine zero rather than a missed read.
                        cell.mark(CellStatus.VERIFIED, "blank_confirmed_zero")
                    elif not cell.is_numeric:
                        # Text where a figure belongs counts as zero in the sum,
                        # so the row balances whatever it says. `a` - OCR's
                        # reading of `0` on `New Doc 06-01-2026 08.28.pdf` - was
                        # verified and exported as `"a"`. The sum does not
                        # confirm what the cell reads, only what it might be.
                        cell.mark(CellStatus.FLAGGED, "not_a_figure")
                    else:
                        cell.mark(CellStatus.VERIFIED, name)
            else:
                o, r, i, c = (_val(x) for x in quad)
                expected = ((o or Decimal(0)) + (r or Decimal(0)) - (i or Decimal(0))
                            + self._adjustment_value(row, adjustment))
                for cell in cells:
                    if cell is None:
                        continue
                    reason = ("blank_breaks_arithmetic" if cell.is_blank
                              else f"{name}_mismatch")
                    cell.mark(CellStatus.FLAGGED, reason)
                report.findings.append(Finding(
                    check=name, status=CellStatus.FLAGGED,
                    section_index=section.index, row_index=row.index,
                    column_indices=column_indices,
                    message="row does not satisfy opening + receipt - issue = closing",
                    expected=str(expected),
                    actual=str(c if c is not None else "blank")))
        return result

    def _check_total_row_equation(self, section: Section, roles: Sequence[Role],
                                  name: str, report: ValidationReport,
                                  invariant: InvariantResult | None = None) -> None:
        """Apply the row equation to printed total rows in their own right.

        A totals line is self-contained arithmetic, so it can be verified even
        when the page shows only part of a longer report. It is only *enforced*
        for relationships the document's own data established: where value
        columns never reconcile row by row, a totals line that does not
        reconcile either is expected, and is reported as unchecked rather than
        flagged.
        """
        cfg = self.config
        indices = [section.role_index(r) for r in roles]
        if any(i is None for i in indices):
            return
        enforce = invariant is not None and invariant.adopted

        check = f"{name}_total_row"
        adjustment = self._adjustment_for(section, name)
        for row in section.total_rows:
            cells = self._group_cells(section, row, roles)
            if cells is None:
                continue
            o, r, i, c = (_val(x) for x in cells)
            if sum(1 for v in (o, r, i, c) if v is not None) < 3:
                continue

            ov, rv, iv, cv = (v or Decimal(0) for v in (o, r, i, c))
            expected = ov + rv - iv + self._adjustment_value(row, adjustment)
            if abs(expected - cv) <= cfg.numeric_tolerance:
                for cell in cells:
                    if cell is not None:
                        cell.mark(CellStatus.VERIFIED, check)
                report.findings.append(Finding(
                    check=check, status=CellStatus.VERIFIED,
                    section_index=section.index, row_index=row.index,
                    column_indices=[x for x in indices if x is not None],
                    message="printed total row satisfies "
                            "opening + receipt - issue = closing",
                    expected=str(expected), actual=str(cv)))
            elif enforce:
                for cell in cells:
                    if cell is not None:
                        cell.mark(CellStatus.FLAGGED, f"{check}_mismatch")
                report.findings.append(Finding(
                    check=check, status=CellStatus.FLAGGED,
                    section_index=section.index, row_index=row.index,
                    column_indices=[x for x in indices if x is not None],
                    message="printed total row does not balance, although the "
                            "relationship holds for the rows above it",
                    expected=str(expected), actual=str(cv)))
            else:
                for cell in cells:
                    if cell is not None:
                        cell.mark(CellStatus.UNCHECKED, f"{check}_not_applicable")
                report.findings.append(Finding(
                    check=check, status=CellStatus.UNCHECKED,
                    section_index=section.index, row_index=row.index,
                    column_indices=[x for x in indices if x is not None],
                    message="printed total row does not balance, but the "
                            "relationship does not hold for this document's rows "
                            "either, so nothing is proven",
                    expected=str(expected), actual=str(cv)))

    def _check_column_orientation(self, section: Section,
                                  report: ValidationReport) -> None:
        """Flag columns whose role the mapper could not orient.

        ``opening + receipt - issue = closing`` is symmetric: it is equally
        satisfied with issue and closing exchanged. Where no heading settled
        which is which, the arithmetic will verify the row either way, so this
        is the one error the row checks are structurally incapable of finding.
        The values may be right; the label on them is a guess.
        """
        ambiguous = [c for c in section.columns if c.orientation_ambiguous]
        if not ambiguous:
            return

        indices = [c.index for c in ambiguous]
        names = ", ".join(f"column {c.index} as {c.role.value}" for c in ambiguous)
        for column in ambiguous:
            for row in section.rows:
                cell = row.cell_at(column.index)
                if cell is not None:
                    cell.mark(CellStatus.FLAGGED, "column_role_orientation_unresolved")

        report.findings.append(Finding(
            check="column_orientation", status=CellStatus.FLAGGED,
            section_index=section.index, column_indices=indices,
            message=f"{names}: the stock equation is symmetric in issue and "
                    "closing, and no heading was available to orient them, so "
                    "these two roles may be transposed. Arithmetic cannot "
                    "detect this - a human or a VLM must decide.",
            expected="a heading, or a VLM ruling, to orient the pair",
            actual=f"roles assigned from a symmetric equation: {names}"))

    # -- rate -------------------------------------------------------------

    def _check_rate(self, section: Section, report: ValidationReport) -> None:
        """qty x rate ~= value, for whichever quantity column pairs with it."""
        cfg = self.config
        rate_idx = section.role_index(Role.RATE)
        if rate_idx is None:
            return

        value_role = next((r for r in VALUE_ROLES if section.role_index(r) is not None), None)
        qty_role = next((r for r in QTY_ROLES if section.role_index(r) is not None), None)
        # Closing quantity is the conventional partner for a closing valuation.
        if section.role_index(Role.CLOSING_QTY) is not None:
            qty_role = Role.CLOSING_QTY
        if value_role is None or qty_role is None:
            return

        q_idx = section.role_index(qty_role)
        v_idx = section.role_index(value_role)
        agreeing = evaluable = 0
        pending: list[tuple[Row, Decimal, Decimal]] = []

        for row in section.data_rows:
            q_cell, r_cell, v_cell = (row.cell_at(q_idx), row.cell_at(rate_idx),   # type: ignore[arg-type]
                                      row.cell_at(v_idx))                          # type: ignore[arg-type]
            q, rate, v = _val(q_cell), _val(r_cell), _val(v_cell)
            if q is None or rate is None or v is None:
                continue
            if q == 0 and v == 0:
                continue
            evaluable += 1
            product = q * rate
            if _within(product, v, cfg.rate_rel_tolerance, cfg.rate_abs_tolerance):
                agreeing += 1
            else:
                pending.append((row, product, v))

        if evaluable < cfg.min_rows_for_invariant:
            report.invariants.append(InvariantResult(
                name="rate_product", adopted=False, informative_rows=evaluable,
                agreeing_rows=agreeing, degenerate_rows=0,
                reason="too few rows carrying quantity, rate and value together"))
            return

        adopted = (agreeing / evaluable) >= cfg.invariant_support
        report.invariants.append(InvariantResult(
            name="rate_product", adopted=adopted, informative_rows=evaluable,
            agreeing_rows=agreeing, degenerate_rows=0,
            reason=(f"{qty_role.value} x rate = {value_role.value}" if adopted
                    else "quantity x rate does not explain the printed value")))

        if not adopted:
            for row in section.data_rows:
                for idx in (q_idx, rate_idx, v_idx):
                    cell = row.cell_at(idx)  # type: ignore[arg-type]
                    if cell is not None:
                        cell.mark(CellStatus.UNCHECKED, "rate_product_not_applicable")
            report.findings.append(Finding(
                check="rate_product", status=CellStatus.UNCHECKED,
                section_index=section.index,
                column_indices=[q_idx, rate_idx, v_idx],  # type: ignore[list-item]
                message="quantity x rate does not reconcile with the printed value "
                        "for this document"))
            return

        for row in section.data_rows:
            q_cell, r_cell, v_cell = (row.cell_at(q_idx), row.cell_at(rate_idx),   # type: ignore[arg-type]
                                      row.cell_at(v_idx))                          # type: ignore[arg-type]
            q, rate, v = _val(q_cell), _val(r_cell), _val(v_cell)
            if q is None or rate is None or v is None:
                continue
            if _within(q * rate, v, cfg.rate_rel_tolerance, cfg.rate_abs_tolerance):
                for cell in (q_cell, r_cell, v_cell):
                    if cell is not None:
                        cell.mark(CellStatus.VERIFIED, "rate_product")

        for row, product, printed in pending:
            for idx in (q_idx, rate_idx, v_idx):
                cell = row.cell_at(idx)  # type: ignore[arg-type]
                if cell is not None:
                    cell.mark(CellStatus.FLAGGED, "rate_product_mismatch")
            report.findings.append(Finding(
                check="rate_product", status=CellStatus.FLAGGED,
                section_index=section.index, row_index=row.index,
                column_indices=[q_idx, rate_idx, v_idx],  # type: ignore[list-item]
                message="quantity x rate does not match the printed value",
                expected=str(product), actual=str(printed)))

    # -- totals -----------------------------------------------------------

    def _check_totals(self, section: Section, report: ValidationReport,
                      context: ValidationContext) -> None:
        cfg = self.config
        total_rows = section.total_rows
        role_by_index = {c.index: c.role for c in section.columns
                         if c.role is not Role.UNKNOWN}
        summed_roles = set(QTY_ROLES) | set(VALUE_ROLES) | {Role.DUMP_QTY}

        sums: dict[int, Decimal] = {}
        rows_summed: dict[int, int] = {}
        for column in section.columns:
            role = role_by_index.get(column.index, Role.UNKNOWN)
            # A column the headings never named is summed too: its arithmetic
            # does not depend on knowing what it counts.
            if role is not Role.UNKNOWN and role not in summed_roles:
                continue
            column_sum = Decimal(0)
            seen = 0
            for row in section.data_rows:
                value = _val(row.cell_at(column.index))
                if value is not None:
                    column_sum += value
                    seen += 1
            if not seen:
                continue
            sums[column.index] = column_sum
            rows_summed[column.index] = seen
            if role is not Role.UNKNOWN:
                report.totals_by_role[role.value] = str(column_sum)

        if not total_rows:
            return

        for row in total_rows:
            for index, computed in sums.items():
                cell = row.cell_at(index)
                printed = _val(cell)
                if cell is None or printed is None:
                    continue
                role = role_by_index.get(index)

                if role is None:
                    # No heading matched this column, so no equation could ever
                    # reach it and every figure in it sits `unchecked`. The
                    # document still says what the column adds up to, and that
                    # is a check in its own right - the one kind of proof
                    # available on a page whose headings the camera destroyed.
                    if (rows_summed[index] >= cfg.column_sum_min_rows
                            and computed != 0
                            and abs(printed - computed) <= cfg.total_tolerance):
                        cell.mark(CellStatus.VERIFIED, "total_matches_column_sum")
                        self._verify_column(section, index, report,
                                            "column_sum_matches_printed_total",
                                            "every figure in this unnamed column is "
                                            f"confirmed by the printed total {printed}")
                        report.findings.append(Finding(
                            check="column_sum", status=CellStatus.VERIFIED,
                            section_index=section.index, row_index=row.index,
                            column_indices=[index],
                            message="printed total matches the sum of a column no "
                                    "heading named",
                            expected=str(computed), actual=str(printed)))
                    continue

                carried = context.previous_totals.get(role.value)

                if abs(printed - computed) <= cfg.total_tolerance:
                    cell.mark(CellStatus.VERIFIED, "total_matches_column_sum")
                    self._verify_column(section, index, report,
                                        "column_sum_matches_printed_total",
                                        f"every figure in the {role.value} column is "
                                        f"confirmed by the printed total {printed}")
                    report.findings.append(Finding(
                        check="total", status=CellStatus.VERIFIED,
                        section_index=section.index, row_index=row.index,
                        column_indices=[index],
                        message=f"printed total for {role.value} matches the column sum",
                        expected=str(computed), actual=str(printed)))
                    continue

                if carried is not None and abs(printed - (computed + carried)) <= cfg.total_tolerance:
                    cell.mark(CellStatus.VERIFIED, "cumulative_total")
                    self._verify_column(section, index, report,
                                        "column_sum_matches_cumulative_total",
                                        f"every figure in the {role.value} column is "
                                        f"confirmed by the cumulative total {printed}")
                    report.findings.append(Finding(
                        check="total_cumulative", status=CellStatus.VERIFIED,
                        section_index=section.index, row_index=row.index,
                        column_indices=[index],
                        message=f"printed total for {role.value} is cumulative: "
                                f"carried {carried} + page {computed}; "
                                "do not add it to earlier pages again",
                        expected=str(computed + carried), actual=str(printed)))
                    continue

                earlier_rows = context.previous_row_sums.get(role.value)
                if earlier_rows is not None and \
                        abs(printed - (computed + earlier_rows)) <= cfg.total_tolerance:
                    cell.mark(CellStatus.VERIFIED, "total_of_every_page")
                    self._verify_column(section, index, report,
                                        "column_sum_matches_cumulative_total",
                                        f"every figure in the {role.value} column is "
                                        f"confirmed by the total {printed} of every page")
                    report.findings.append(Finding(
                        check="total_cumulative", status=CellStatus.VERIFIED,
                        section_index=section.index, row_index=row.index,
                        column_indices=[index],
                        message=f"printed total for {role.value} totals every page so "
                                f"far: {earlier_rows} from earlier pages + {computed} "
                                "here; do not add it to those pages again",
                        expected=str(computed + earlier_rows), actual=str(printed)))
                    continue

                # Krishna's TOTAL is a value figure printed under a quantity
                # column. A sum that is orders of magnitude away is a different
                # measure, not a misread digit.
                if computed != 0:
                    ratio = abs(printed / computed) if computed else None
                    if ratio is not None and (ratio > cfg.total_magnitude_factor
                                              or ratio < 1 / cfg.total_magnitude_factor):
                        cell.mark(CellStatus.UNCHECKED, "total_is_different_measure")
                        report.findings.append(Finding(
                            check="total", status=CellStatus.UNCHECKED,
                            section_index=section.index, row_index=row.index,
                            column_indices=[index],
                            message=f"printed total {printed} is {ratio:.1f}x the "
                                    f"{role.value} column sum; treated as a different "
                                    "measure, not a column sum",
                            expected=str(computed), actual=str(printed)))
                        continue
                elif abs(printed) > cfg.total_tolerance:
                    cell.mark(CellStatus.UNCHECKED, "total_is_different_measure")
                    report.findings.append(Finding(
                        check="total", status=CellStatus.UNCHECKED,
                        section_index=section.index, row_index=row.index,
                        column_indices=[index],
                        message=f"printed total {printed} against an empty "
                                f"{role.value} column; treated as a different measure",
                        expected="0", actual=str(printed)))
                    continue

                cell.mark(CellStatus.FLAGGED, "total_mismatch")
                report.findings.append(Finding(
                    check="total", status=CellStatus.FLAGGED,
                    section_index=section.index, row_index=row.index,
                    column_indices=[index],
                    message=f"printed total for {role.value} does not match the "
                            "column sum",
                    expected=str(computed), actual=str(printed)))

    def _verify_column(self, section: Section, index: int,
                       report: ValidationReport, reason: str, message: str) -> None:
        """A column that adds up to its printed total was read correctly.

        Every figure in the column took part in the sum, so a misread digit in
        any one of them would have thrown the sum off. The match is therefore a
        statement about each cell, not only about the total line - which is
        what a bookkeeper means by a column that foots.

        It is the only check that reaches a page whose headings OCR mangled:
        no role, no row equation, nothing else to test the figures against.
        Cells already flagged keep their flag (`Cell.mark` never lowers a
        status), and a deterministic cell stays `exact`.
        """
        verified = 0
        for row in section.data_rows:
            cell = row.cell_at(index)
            if cell is None or not cell.is_numeric:
                continue
            cell.mark(CellStatus.VERIFIED, reason)
            verified += 1
        if verified:
            report.findings.append(Finding(
                check="column_sum_cells", status=CellStatus.VERIFIED,
                section_index=section.index, column_indices=[index],
                message=f"{message} ({verified} cells)"))

    # -- confidence -------------------------------------------------------

    def _check_merged_figures(self, section: Section, report: ValidationReport) -> None:
        """Flag a cell holding several separate figures under one heading.

        A cell holds one value. `814 1` on `AAI PHARMA JUNE26.pdf` was two
        columns' figures in one cell, read from the text layer and so marked
        `exact` with nothing to review - correct characters under the wrong
        heading. That is a structural fault (s5): the reading is sound, the
        column split is not. Descriptive columns are exempt, since an item
        name can carry numbers (`ZEBOR 20% 15 GM`).
        """
        textual = {c.index for c in section.columns if c.role in TEXTUAL_ROLES}
        for row in section.rows:
            if row.row_type not in (RowType.DATA, RowType.TOTAL):
                continue
            for cell in row.cells:
                if cell.column_index in textual or not cell.holds_several_figures:
                    continue
                cell.mark(CellStatus.FLAGGED, "several_figures_in_one_cell")
                report.findings.append(Finding(
                    check="merged_figures", status=CellStatus.FLAGGED,
                    section_index=section.index, row_index=row.index,
                    column_indices=[cell.column_index],
                    message=f"{cell.raw_text!r} holds several figures: neighbouring "
                            "columns were not separated, so they may sit under the "
                            "wrong heading (layout fault, not a reading fault)"))

    def _check_confidence(self, doc: Document, report: ValidationReport) -> None:
        threshold = self.config.min_confidence
        for section, row, cell in doc.iter_cells():
            if row.row_type not in (RowType.DATA, RowType.TOTAL):
                continue
            confidence = cell.provenance.confidence
            if confidence is None or cell.is_blank:
                continue
            if confidence < threshold:
                cell.mark(CellStatus.FLAGGED, "low_ocr_confidence")
                report.findings.append(Finding(
                    check="confidence", status=CellStatus.FLAGGED,
                    section_index=section.index, row_index=row.index,
                    column_indices=[cell.column_index],
                    message=f"OCR confidence {confidence:.2f} below threshold "
                            f"{threshold:.2f} for {cell.raw_text!r}",
                    expected=f">={threshold:.2f}", actual=f"{confidence:.2f}"))

    # -- metadata formats -------------------------------------------------

    def _check_metadata_formats(self, doc: Document, report: ValidationReport) -> None:
        meta = doc.metadata
        if meta.gstin:
            value = meta.gstin.value.strip().upper()
            if is_valid_gstin(value):
                report.findings.append(Finding(
                    check="gstin", status=CellStatus.VERIFIED,
                    message=f"GSTIN {value} passes shape and checksum"))
            else:
                expected = None
                if len(value) == 15 and _GSTIN_SHAPE.match(value):
                    try:
                        expected = gstin_check_digit(value[:14])
                    except ValueError:
                        expected = None
                report.findings.append(Finding(
                    check="gstin", status=CellStatus.FLAGGED,
                    message=f"GSTIN {value!r} failed validation",
                    expected=(f"check digit {expected}" if expected else "15-char GSTIN"),
                    actual=value))

        for label, field_value in (("period_from", meta.period_from),
                                   ("period_to", meta.period_to)):
            if field_value is None:
                continue
            if is_valid_date(field_value.value):
                report.findings.append(Finding(
                    check="date_format", status=CellStatus.VERIFIED,
                    message=f"{label} {field_value.value} parses as a date"))
            else:
                report.findings.append(Finding(
                    check="date_format", status=CellStatus.FLAGGED,
                    message=f"{label} {field_value.value!r} is not a recognisable date",
                    actual=field_value.value))

    # -- coverage ---------------------------------------------------------

    def _check_coverage(self, doc: Document, report: ValidationReport) -> None:
        """Every numeric token OCR saw must appear somewhere in the output."""
        coverage = report.coverage
        tokens = doc.tokens or []
        coverage.tokens_seen = len(tokens)
        if not tokens:
            return

        seen: list[str] = []
        for token in tokens:
            text = str(token.get("text", "")).strip()
            if parse_number(text) is not None:
                seen.append(_canonical_number(text))
        coverage.numeric_tokens_seen = len(seen)

        # A cell is built by joining tokens with a space, so a cell can hold
        # several of them ("- 400086", "1 47"). Comparing whole cells against
        # tokens would report every merged cell as a loss, so the count is made
        # over the numeric pieces inside each cell.
        placed: dict[str, int] = {}
        for cell in doc.iter_all_cells():
            for piece in cell.raw_text.split():
                if parse_number(piece) is not None:
                    key = _canonical_number(piece)
                    placed[key] = placed.get(key, 0) + 1

        missing: list[str] = []
        remaining = dict(placed)
        for key in seen:
            if remaining.get(key, 0) > 0:
                remaining[key] -= 1
            else:
                missing.append(key)
        coverage.numeric_tokens_placed = len(seen) - len(missing)
        coverage.missing = missing

        if missing:
            report.findings.append(Finding(
                check="coverage", status=CellStatus.FLAGGED,
                message=f"{len(missing)} numeric token(s) OCR read never reached the "
                        f"output: {', '.join(missing[:10])}",
                expected=str(coverage.numeric_tokens_seen),
                actual=str(coverage.numeric_tokens_placed)))
        else:
            report.findings.append(Finding(
                check="coverage", status=CellStatus.VERIFIED,
                message=f"all {coverage.numeric_tokens_seen} numeric tokens accounted for"))

    # -- helpers ----------------------------------------------------------

    def _mark_section(self, section: Section, status: CellStatus, reason: str) -> None:
        for row in section.rows:
            for cell in row.cells:
                cell.mark(status, reason)

    def _tally(self, doc: Document, report: ValidationReport) -> None:
        """Count outcomes, and separate the two kinds of review.

        Review load used to be every cell that was not verified, which counted
        Excel and PDF-text cells that cannot have been misread. Those are
        reported as ``exact`` and excluded: verification exists to catch
        misreading, and where the source is deterministic there is nothing to
        catch.

        A deterministic cell can still be flagged, but only for a *structural*
        reason - a row that does not balance, a total that does not reconcile.
        That is a layout or mapping fault rather than a transcription one, so
        it is counted separately.
        """
        counts = {"exact": 0, "verified": 0, "flagged": 0, "unchecked": 0,
                  "blank": 0, "total_cells": 0, "pixel_cells": 0,
                  "review_cells": 0, "structural_flags": 0}
        for _, row, cell in doc.iter_cells():
            if row.row_type not in (RowType.DATA, RowType.TOTAL):
                continue
            counts["total_cells"] += 1
            if cell.is_blank:
                counts["blank"] += 1
            counts[cell.status.value] += 1

            if cell.is_deterministic:
                if cell.status is CellStatus.FLAGGED:
                    counts["structural_flags"] += 1
            else:
                counts["pixel_cells"] += 1
                if cell.needs_review:
                    counts["review_cells"] += 1
        report.counts = counts


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


_HEADER_METHODS = (MappingMethod.HEADER_EXACT, MappingMethod.HEADER_FUZZY,
                   MappingMethod.HEADER_AND_ARITHMETIC)


def _val(cell: Cell | None) -> Decimal | None:
    return cell.value if cell is not None and cell.is_numeric else None


def _within(actual: Decimal, expected: Decimal,
            rel: Decimal, absolute: Decimal) -> bool:
    """Tolerance is the larger of the relative and absolute allowances."""
    return abs(actual - expected) <= max(abs(expected) * rel, absolute)


def _canonical_number(text: str) -> str:
    value = parse_number(text)
    return format(value.normalize(), "f") if value is not None else text.strip()


def validate_document(doc: Document, config: ValidatorConfig | None = None,
                      context: ValidationContext | None = None) -> ValidationReport:
    return Validator(config).validate(doc, context)


def validate_pages(docs: Sequence[Document],
                   config: ValidatorConfig | None = None
                   ) -> list[ValidationReport]:
    """Validate consecutive pages, carrying totals forward.

    This is what lets page 2 recognise that its printed total already contains
    page 1's, rather than double-counting it.
    """
    reports: list[ValidationReport] = []
    carried: dict[str, Decimal] = {}
    row_sums: dict[str, Decimal] = {}
    validator = Validator(config)

    for doc in docs:
        context = ValidationContext(previous_totals=dict(carried),
                                    previous_row_sums=dict(row_sums))
        report = validator.validate(doc, context)
        reports.append(report)

        for section in doc.tabular_sections():
            for column in section.columns:
                if column.role is Role.UNKNOWN:
                    continue
                for data_row in section.data_rows:
                    value = _val(data_row.cell_at(column.index))
                    if value is not None:
                        row_sums[column.role.value] = \
                            row_sums.get(column.role.value, Decimal(0)) + value
            for row in section.total_rows:
                for column in section.columns:
                    if column.role is Role.UNKNOWN:
                        continue
                    printed = _val(row.cell_at(column.index))
                    if printed is not None:
                        carried[column.role.value] = printed
    return reports


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _format_report(doc: Document, report: ValidationReport) -> str:
    lines: list[str] = []
    counts = report.counts
    lines.append(f"page {doc.page}: {counts.get('total_cells', 0)} cells  "
                 f"exact={counts.get('exact', 0)}  "
                 f"verified={counts.get('verified', 0)}  "
                 f"flagged={counts.get('flagged', 0)}  "
                 f"unchecked={counts.get('unchecked', 0)}")
    lines.append(f"  review load: {counts.get('review_cells', 0)} pixel-derived "
                 f"cell(s) of {counts.get('pixel_cells', 0)}; "
                 f"{counts.get('structural_flags', 0)} structural flag(s) on "
                 "deterministic cells")
    lines.append("")
    lines.append("invariants:")
    for inv in report.invariants:
        state = "ADOPTED" if inv.adopted else "not adopted"
        lines.append(f"  {inv.name:<22} {state:<12} "
                     f"support={inv.support:.0%} "
                     f"({inv.agreeing_rows}/{inv.informative_rows} informative, "
                     f"{inv.degenerate_rows} static)  {inv.reason}")
    lines.append("")
    lines.append(f"coverage: {report.coverage.numeric_tokens_placed}/"
                 f"{report.coverage.numeric_tokens_seen} numeric tokens placed")
    flagged = report.flagged
    lines.append("")
    lines.append(f"flagged findings ({len(flagged)}):")
    for finding in flagged[:40]:
        where = f"s{finding.section_index}"
        if finding.row_index is not None:
            where += f"/r{finding.row_index}"
        lines.append(f"  [{finding.check}] {where}: {finding.message}")
        if finding.expected is not None:
            lines.append(f"      expected {finding.expected}, got {finding.actual}")
    if not flagged:
        lines.append("  none")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a mapped grid and report per-cell status")
    parser.add_argument("grid", help="path to a grid JSON file")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    parser.add_argument("--cells", action="store_true",
                        help="emit the full document with per-cell status")
    parser.add_argument("--min-confidence", type=float, default=None,
                        help="override the OCR confidence threshold")
    args = parser.parse_args(argv)

    config = ValidatorConfig()
    if args.min_confidence is not None:
        config.min_confidence = args.min_confidence

    doc = map_grid_file(args.grid)
    report = Validator(config).validate(doc)

    if args.cells:
        print(doc.to_json())
    elif args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(_format_report(doc, report))
    return 1 if report.flagged else 0


if __name__ == "__main__":
    sys.exit(main())
