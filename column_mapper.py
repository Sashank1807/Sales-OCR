"""Stage A - discover what each column of a reconstructed grid means.

Consumes the geometric grid produced by ``ocr_to_table.py`` and produces a
:class:`~schema.Document`: sections, column role mappings with confidences, row
classifications, and document metadata.

Nothing here is distributor-specific. Column roles are discovered per document
from four independent passes whose results are reconciled rather than
short-circuited:

1. header-row detection, including two-tier headers spanning sub-columns
2. synonym matching against generic stock-statement vocabulary
3. data profiling (dtype, decimals, magnitude)
4. arithmetic discovery - which assignment of columns actually satisfies
   ``opening + receipt - issue = closing`` and ``qty x rate = value``

Pass 4 is what lets a document with missing or mangled headers still be mapped,
and it is also the tiebreak when two columns claim the same role.

Run standalone::

    python column_mapper.py grid.json --json
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any, Protocol, Sequence

from schema import (
    ColumnMapping, ColumnProfile, Document, DocumentMetadata, MappingMethod,
    MetadataField, Provenance, Role, Row, RowType, Section, SectionKind, Source,
    STOCK_FLOW_ROLES, load_grid, load_grid_file, normalise_header,
)

__all__ = [
    "ColumnMapper", "MapperConfig", "VLMColumnRequest", "VLMColumnResponse",
    "VLMColumnResolver", "map_grid", "map_grid_file",
]


# ---------------------------------------------------------------------------
# Vocabulary - generic stock-statement terms, not distributor names
# ---------------------------------------------------------------------------

#: Base concepts. Qty/value is decided separately from the tier-2 heading or,
#: failing that, from the data profile.
_FLOW_SYNONYMS: dict[str, tuple[str, ...]] = {
    "opening": ("opening", "open", "op", "opening balance", "opening stock",
                "open stock", "ob", "o b", "b f", "brought forward", "o stock"),
    "receipt": ("receipt", "receipts", "in", "inward", "purchase", "purch",
                "purchases", "received", "recd", "inwards", "added", "grn"),
    "issue": ("issue", "issues", "issued", "out", "outward", "sales", "sale",
              "sold", "outwards", "dispatch", "despatch", "consumption"),
    # "cl" mirrors "op": `Cl.Stock`, `Clqty` and `Clval` all appear in the JUNE
    # corpus, and without it `Cl.Stock` on `11.pdf` could only be reached by
    # arithmetic.
    "closing": ("closing", "close", "cl", "balance", "bal", "closing balance",
                "closing stock", "close stock", "cb", "c b", "stock",
                "c f", "carried forward", "c stock",
                # quantity on hand: `Qoh`
                "qoh", "on hand", "stock on hand"),
    # "expiry" is deliberately absent: a column headed EXPIRY in a batch
    # listing holds dates, not a dump quantity.
    "dump": ("dump", "damage", "damaged", "breakage", "non saleable"),
}

_SIMPLE_SYNONYMS: dict[Role, tuple[str, ...]] = {
    Role.ITEM_DESCRIPTION: ("item description", "description", "particulars",
                            "item", "item name", "product", "product name",
                            "goods description", "material", "name"),
    Role.CODE: ("code", "item code", "product code", "sku", "hsn", "article",
                "cat no", "catalog no"),
    Role.PACK: ("pack", "pkg", "packing", "pack size", "packsize", "pkt", "ps"),
    Role.UNIT: ("unit", "uom", "units", "measure", "unit of measure"),
    Role.RATE: ("rate", "price", "mrp", "unit rate", "unit price", "ptr", "pts",
                "cost", "rate per unit"),
}

#: Tokens that may accompany a synonym without changing its meaning.
_NEUTRAL_MODIFIERS = frozenset({
    "qty", "qnty", "quantity", "qty.", "nos", "no", "number", "value", "val",
    "amount", "amt", "stock", "total", "rs", "inr", "in", "of", "the", "and",
})

#: Tokens that reverse the direction of a flow. A "sales return" is an inward
#: movement, so it must not be tagged as an issue; there is no canonical role
#: for it, so the column stays UNKNOWN rather than being mislabelled.
_REVERSING_MODIFIERS = frozenset({"ret", "return", "returns", "rtn", "rej",
                                  "rejection", "rejected", "reversal"})

#: Stock that has expired or is about to is not part of the stock equation:
#: an `EXPIRY STOCK` column is neither the opening nor the closing stock.
_EXPIRY_MODIFIERS = frozenset({"expiry", "expired", "expiring", "exp"})
#: Free goods (`Purc Free`, `Sale Free`) move beside the main flows but are not
#: them; the stock equation carries them as adjustments. Taking them for the
#: receipt and issue columns pushed out `Purc Qty` and `Sale Qty` on
#: `MANAL PHARMA.htm`.
_FREE_MODIFIERS = frozenset({"free", "bonus", "scheme"})

_QTY_MARKERS = frozenset({"qty", "qnty", "quantity", "nos", "no", "number", "units"})
_VALUE_MARKERS = frozenset({"value", "val", "amount", "amt", "worth", "rs", "inr"})
#: Ways of writing "stock" that are glued to a flow abbreviation (`OpStk`).
_STOCK_WORDS = frozenset({"stk", "stock"})
_STOCK_ABBREVIATIONS = {"stk": "stock"}
_STOCK_PREFIXES = frozenset({"op", "cl", "o", "c"})

#: Vocabulary that marks a row as *some* table's header, even when the columns
#: carry no canonical role (an invoice block, an expiry listing). Generic
#: tabular words only - nothing tied to a particular vendor.
_GENERIC_HEADER_WORDS = frozenset({
    "date", "no", "number", "name", "amount", "value", "qty", "quantity",
    "total", "code", "unit", "rate", "pack", "pkg", "description", "item",
    "product", "particulars", "supplier", "invoice", "bill", "batch", "batchno",
    "expiry", "stock", "gross", "net", "opening", "closing", "balance",
})

#: A pack column often has no heading at all. These shapes identify one from
#: its data: "1X10TAB", "1*10", "30ML", "6S".
_PACK_LIKE_RE = re.compile(
    r"^\s*(?:\d+\s*[xX*]\s*\d*\s*[A-Za-z.]*|\d+\s*(?:GM|ML|MG|G|L|KG|S|SAC|TAB|CAP)\.?)\s*$",
    re.IGNORECASE,
)

_TOTAL_RE = re.compile(r"^\s*(grand\s+total|sub\s*[- ]?\s*total|total)\b", re.IGNORECASE)
_TOTAL_TAIL_RE = re.compile(r"\btotals?\s*[:.\-]*\s*$", re.IGNORECASE)
_CONTINUATION_RE = re.compile(r"continued|cont\.{0,3}\s*\d|page\s*no", re.IGNORECASE)

_GSTIN_STRICT = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b")
_GSTIN_LABELLED = re.compile(r"GSTIN?\s*(?:NO\.?)?\s*[:\-]?\s*([0-9A-Z]{15})", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE_RE = re.compile(r"phone\s*[:\-]?\s*([0-9][0-9,\s/+\-]{6,})", re.IGNORECASE)
_DATE_RE = re.compile(
    r"\b(\d{1,2})\s*[/-]\s*([A-Za-z]{3,9}|\d{1,2})\s*[/-]\s*(\d{2,4})\b"
)
_COMPANY_RE = re.compile(r"company\s*[:\-]\s*(.+)", re.IGNORECASE)
#: What joins the two ends of a reporting period. `t0` is how OCR reads `TO`.
_RANGE_JOIN_RE = re.compile(r"^\W*(?:t[o0]|upto|up\s*to|till|until)?\W*$", re.IGNORECASE)


def _period_in(line: str) -> tuple[str, str] | None:
    """Two dates on a line, but only when the line presents them as a range.

    Any two dates were taken as the period, so `Run Date:23/06/2026
    Time:10:21AM ... 01/06/2028` on a printout's footer became a reporting
    period two years long. Between the two dates there must be nothing but a
    range word - `to`, `upto`, `till` - or punctuation such as a dash.
    """
    matches = list(_DATE_RE.finditer(line))
    for first, second in zip(matches, matches[1:]):
        if _RANGE_JOIN_RE.match(line[first.end():second.start()]):
            return first.group(0), second.group(0)
    return None


#: What kind of report a heading line announces.
_REPORT_KIND_RE = re.compile(r"\b(stock|sales?|statement|summary|inventory)\b", re.IGNORECASE)
#: Where a report heading stops and its date range begins.
_TITLE_END_RE = re.compile(r"\bfrom\b|\(|-{3,}|:\s*\d|\d{1,2}\s*[/.-]\s*(?:\d{1,2}|[A-Za-z]{3})",
                           re.IGNORECASE)
#: Labelled details that often share the address line.
_LABELLED_TAIL_RE = re.compile(
    r"\b(?:GSTIN|GST|PH(?:ONE)?|MOB(?:ILE)?|TEL|FAX|E-?MAIL|D\.?\s*L\.?\s*N[O0])\b",
    re.IGNORECASE)
_PARENTHETICAL_RE = re.compile(r"\(([^)]{3,60})\)")

#: Words a pharmaceutical distributor's trading name is built from. Domain
#: vocabulary, not any one distributor's name (s4.3).
_TRADE_WORDS = frozenset({
    "pharma", "pharmaceutical", "pharmaceuticals", "pharmacy", "medical", "medicals",
    "medicos", "medicine", "medicines", "agency", "agencies", "distributor",
    "distributors", "traders", "trading", "enterprise", "enterprises", "healthcare",
    "drug", "drugs", "druggist", "druggists", "chemist", "chemists", "pvt", "private",
    "ltd", "limited", "llp", "company", "corporation", "corp", "store", "stores", "hall",
    "marketing", "associates", "surgical", "surgicals", "lifesciences", "remedies",
})
_CAPS_WORD_RE = re.compile(r"^[A-Z][A-Z&.'\-]*$")


def _caps_run(line: str) -> list[str]:
    """The leading run of words printed in capitals."""
    run = []
    for word in line.split():
        if not _CAPS_WORD_RE.match(word):
            break
        run.append(word)
    return run


def _business_name_score(line: str) -> int:
    """How much a line looks like a trading name: 0 means not at all.

    +2 for a trade word (`PHARMACEUTICALS`, `AGENCIES`, `MEDICAL`), +1 for
    opening with two or more words in capitals, as letterheads print names.
    Software text - `Main.Report`, `E-Sign Sign in`, `Find text or tools` -
    scores 0 and is never taken as the company.
    """
    words = [w.strip(".,:;()&'-").lower() for w in line.split()]
    if not any(len(w) >= 3 and w.isalpha() for w in words):
        return 0
    score = 2 if any(w in _TRADE_WORDS for w in words) else 0
    if len([w for w in _caps_run(line) if len(w) >= 2]) >= 2:
        score += 1
    return score


def _business_name_part(line: str) -> str:
    """The name without screen text run onto it.

    `SHRI RAM MEDICAL HALL Share Ask` is a letterhead in capitals followed by
    a viewer's `Share` and `Ask` buttons on the same line. When a line opens
    with a run of capitals that holds a trade word and then changes case, the
    run is the name.
    """
    run = _caps_run(line)
    if run and len(run) < len(line.split()) and \
            any(w.strip(".,:;()&'-").lower() in _TRADE_WORDS for w in run):
        return " ".join(run)
    return line


def _address_after(lines: list[tuple[int, str]], position: int,
                   field_for) -> "MetadataField | None":
    """The address printed under the company name, labelled details removed."""
    for offset, (index, line) in enumerate(lines[position + 1: position + 4]):
        if _REPORT_KIND_RE.search(line) or re.search(r"page\s*no", line, re.I):
            continue
        place = _LABELLED_TAIL_RE.split(line, maxsplit=1)[0].strip(" ,-:")
        if len(place) < 4 or not re.search(r"[A-Za-z]", place) or ":" in place:
            continue
        # An address carries a comma or a number - or, directly under the
        # name, is a line of place names in capitals (`MAIN ROAD ORAI JALAUN`).
        if re.search(r"[,\d]", place):
            return field_for(place, 0.6)
        if offset == 0 and len(_caps_run(place)) == len(place.split()) >= 2:
            return field_for(place, 0.5)
    return None


# ---------------------------------------------------------------------------
# VLM fallback interface (definition only - never required to run)
# ---------------------------------------------------------------------------


@dataclass
class VLMColumnRequest:
    """Everything a VLM needs to name the columns it is asked about.

    Deliberately carries no cell *values* it is expected to transcribe - the
    VLM supplies meaning, never digits.
    """

    page: int
    section_index: int
    header_texts: list[str]
    column_profiles: list[dict[str, Any]]
    sample_rows: list[list[str]]
    unresolved_columns: list[int]
    already_assigned: dict[int, str]
    allowed_roles: list[str] = field(default_factory=lambda: [r.value for r in Role])

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "section_index": self.section_index,
            "header_texts": self.header_texts,
            "column_profiles": self.column_profiles,
            "sample_rows": self.sample_rows,
            "unresolved_columns": self.unresolved_columns,
            "already_assigned": self.already_assigned,
            "allowed_roles": self.allowed_roles,
        }


@dataclass
class VLMColumnResponse:
    """Roles proposed by a VLM, keyed by column index."""

    roles: dict[int, str]
    confidence: dict[int, float] = field(default_factory=dict)
    note: str = ""


class VLMColumnResolver(Protocol):
    """Implement this to plug a VLM in behind the low-confidence path."""

    def resolve(self, request: VLMColumnRequest) -> VLMColumnResponse: ...


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class MapperConfig:
    header_accept: float = 0.60
    #: Below this, a column is eligible for the VLM fallback.
    vlm_threshold: float = 0.55
    #: Minimum data rows before arithmetic discovery is trusted at all.
    min_arithmetic_rows: int = 2
    #: Fraction of evaluable rows an equation must satisfy to be adopted.
    arithmetic_support: float = 0.70
    #: Small-sample rows must agree perfectly.
    small_sample_rows: int = 4
    #: Rows with real movement needed before a discovered equation may override
    #: an explicit heading. Short pages throw up coincidental fits.
    min_override_rows: int = 4
    #: Only look for an unmodelled movement column when the quadruple already
    #: explains at least this much; below it the fit is not worth rescuing.
    adjustment_floor: float = 0.40

    # -- what counts as a table ------------------------------------------
    #: Fewer rows than this and there is no pattern to read at all. Kept low:
    #: real stock tables can be two rows long.
    min_tabular_rows: int = 2
    #: Weighted score a section must reach to be treated as a table.
    tabular_threshold: float = 0.50
    #: Rows of a table fill a decent share of the columns detected for it.
    min_band_occupancy: float = 0.30
    #: A stock table is mostly figures; prose blocks are not.
    min_numeric_density: float = 0.15
    #: Rows of a table hold similar numbers of cells.
    min_row_consistency: float = 0.40
    #: Rows of a table use the same columns down the section.
    min_band_stability: float = 0.25
    #: A column past the last heading counts as a real, if unnamed, column when
    #: at least this fraction of data rows populate it. Below the line, the few
    #: rows reaching it are ragged and their cells are flagged instead.
    unheaded_column_support: float = 0.50
    numeric_tolerance: Decimal = Decimal("0.01")
    max_numeric_columns_for_search: int = 16
    header_lookahead: int = 6


# ---------------------------------------------------------------------------
# Header text matching
# ---------------------------------------------------------------------------


def _tokens(text: str) -> list[str]:
    return [t for t in normalise_header(text).split() if t]


def _match_score(header: str, synonym: str) -> float:
    """Score a header against one synonym. 0.0 means no usable match."""
    h_norm, s_norm = normalise_header(header), normalise_header(synonym)
    if not h_norm or not s_norm:
        return 0.0
    if h_norm == s_norm:
        return 0.95

    h_tokens, s_tokens = set(_tokens(header)), set(_tokens(synonym))
    if h_tokens & (_REVERSING_MODIFIERS | _EXPIRY_MODIFIERS | _FREE_MODIFIERS):
        return 0.0

    if s_tokens and s_tokens <= h_tokens:
        extras = h_tokens - s_tokens
        if not extras or extras <= _NEUTRAL_MODIFIERS:
            return 0.88
        return 0.68  # an unfamiliar modifier - plausible but not certain

    # Abbreviations: "purch." for "purchase", "bal" for "balance". A generic
    # word the synonym only carries alongside its real one does not count:
    # `EXPIRY STOCK` matched "open stock" on "stock" alone, scored 0.72 as
    # opening on `Latur statement.pdf` p4, and pushed out `OPENING STOCK`.
    distinctive = {t for t in s_tokens if t not in _NEUTRAL_MODIFIERS} or s_tokens
    for h in h_tokens:
        for s in distinctive:
            if len(h) >= 3 and len(s) >= 3 and (s.startswith(h) or h.startswith(s)):
                return 0.72

    ratio = SequenceMatcher(None, h_norm, s_norm).ratio()
    if ratio >= 0.82:
        return ratio * 0.8

    # One misread letter in a long word: OCR reads `ISSUE` as `ISSLE` and
    # `CLOSING` as `CLISING` on `IMG20260714184904.heic`, and with neither
    # heading matched arithmetic had to orient issue against closing alone -
    # which it cannot - and swapped them. Long words only, so `SALE` cannot
    # drift into `SAFE`; scored just above the acceptance floor.
    for h in h_tokens:
        for s in distinctive:
            if len(h) >= 5 and len(s) >= 5 and abs(len(h) - len(s)) <= 1 and \
                    SequenceMatcher(None, h, s).ratio() >= 0.8:
                return 0.62
    return 0.0


def _decompact(header: str) -> str:
    """`OpQty` -> `op qty`, for matching only.

    A narrow report drops the space between flow and measure. `Op Qty` scores
    0.88 against opening; `OpQty` and `Clqty` scored nothing, because the
    measure word glued to the end made the token unrecognisable. The prefix
    limit is `_measure_suffix`'s, so `approval` is left alone.

    `stk` is how narrow reports write *stock*, and it is glued on the same
    way: `OPSTK` and `STK VAL` on `AAI PHARMA JUNE26.pdf` matched nothing, so
    the opening column went unmapped and no row could be checked.
    """
    parts: list[str] = []
    for token in _tokens(header):
        for marker in sorted(_QTY_MARKERS | _VALUE_MARKERS | _STOCK_WORDS | {"st"},
                             key=len, reverse=True):
            if _measure_suffix(token, frozenset({marker})):
                # `st` only counts glued to an opening or closing abbreviation
                # (`Opst`, `Clst`): `Cost`, `Best` and `Last` end in it too.
                if marker == "st" and token[:-2] not in _STOCK_PREFIXES:
                    continue
                token = f"{token[:-len(marker)]} {'stock' if marker == 'st' else marker}"
                break
        parts.append(token)
    return " ".join(_STOCK_ABBREVIATIONS.get(p, p) for p in " ".join(parts).split())


def _best_flow(header: str) -> tuple[str | None, float]:
    best_key, best_score = None, 0.0
    forms = {header, _decompact(header)}
    for key, synonyms in _FLOW_SYNONYMS.items():
        for syn in synonyms:
            score = max(_match_score(form, syn) for form in forms)
            if score > best_score:
                best_key, best_score = key, score
    return best_key, best_score


def _best_simple(header: str) -> tuple[Role | None, float]:
    best_role, best_score = None, 0.0
    for role, synonyms in _SIMPLE_SYNONYMS.items():
        for syn in synonyms:
            score = _match_score(header, syn)
            if score > best_score:
                best_role, best_score = role, score
    return best_role, best_score


#: Longest prefix a compact abbreviation may put in front of its measure word
#: before the word stops being a suffix and starts being a coincidence.
_MEASURE_SUFFIX_PREFIX = 2


def _measure_suffix(token: str, markers: frozenset[str]) -> bool:
    """Does this one token end in a measure word, after a short prefix?

    Narrow reports abbreviate hard and drop the space: `BVal` and `SVal` are
    balance value and sales value, one token each, so whole-token matching
    cannot see the measure. Worse, `bval` scores 0.86 against both `val` and
    `bal` - identical - and the balance reading won, so a rupee column was
    mapped `closing_qty` on `003063_.pdf` while the real `Adj Bal.` went
    unmapped. The closing column then read 23742 against an opening of 133.

    Only a prefix of one or two characters counts, which is what an
    abbreviation uses (B, S, Op, Cl). Anything longer and the ending is
    accidental - `approval` must not read as a value column.
    """
    for marker in markers:
        if not token.endswith(marker):
            continue
        prefix = len(token) - len(marker)
        if 0 < prefix <= _MEASURE_SUFFIX_PREFIX:
            return True
    return False


def _measure_from_header(header: str) -> str | None:
    """'qty' or 'value' if the heading says so, else None."""
    toks = set(_tokens(header))
    if toks & _VALUE_MARKERS:
        return "value"
    if toks & _QTY_MARKERS:
        return "qty"
    # Fall back to the suffix reading only when no whole token decided it, so
    # an explicit "Qty" in the heading always outranks a compacted ending.
    if any(_measure_suffix(t, _VALUE_MARKERS) for t in toks):
        return "value"
    if any(_measure_suffix(t, _QTY_MARKERS) for t in toks):
        return "qty"
    return None


_ADDED_FLOWS = frozenset({"opening", "receipt"})
_SUBTRACTED_FLOWS = frozenset({"issue", "closing"})


def _arithmetic_cannot_decide(header_role: Role, arith_role: Role,
                              measure_from_header: bool) -> bool:
    """Would overruling this heading rest on nothing the data can show?

    `opening + receipt - issue = closing` cannot tell opening from receipt,
    because addition commutes, and it cannot tell issue from closing, because
    moving a term across the equals sign gives the same statement. A fit that
    swaps either pair is exactly as true as the heading's reading. On
    `GENEX.pdf` p1 the receipt-quantity column was blank, the fit borrowed the
    all-zero `RECEIPT VALUE` column in its place, and then swapped it with
    opening: `OPENING QTY.` became `receipt_qty` and a rupee column became
    `opening_qty`, at confidence 0.65, over two exact headings.

    The same holds for the measure. Where the heading itself says QTY or VALUE,
    a fit that needs the other measure was built from a column the document
    labels as something else.
    """
    h_flow, _, h_measure = header_role.value.rpartition("_")
    a_flow, _, a_measure = arith_role.value.rpartition("_")
    if measure_from_header and h_measure in ("qty", "value") and h_measure != a_measure:
        return True
    if h_measure != a_measure:
        return False
    return ({h_flow, a_flow} <= _ADDED_FLOWS
            or {h_flow, a_flow} <= _SUBTRACTED_FLOWS)


def _same_flow(a: Role, b: Role) -> bool:
    """True when two roles describe the same flow, differing only in measure."""
    a_flow = a.value.rsplit("_", 1)[0]
    b_flow = b.value.rsplit("_", 1)[0]
    return (a_flow == b_flow
            and a.value.rsplit("_", 1)[-1] in ("qty", "value")
            and b.value.rsplit("_", 1)[-1] in ("qty", "value"))


def _flow_role(flow: str, measure: str) -> Role:
    if flow == "dump":
        return Role.DUMP_QTY  # the canonical role set carries no dump value
    return Role(f"{flow}_{measure}")


# ---------------------------------------------------------------------------
# The mapper
# ---------------------------------------------------------------------------


class ColumnMapper:
    """Turns a geometric grid into a semantically mapped :class:`Document`."""

    def __init__(self, config: MapperConfig | None = None,
                 vlm_resolver: VLMColumnResolver | None = None) -> None:
        self.config = config or MapperConfig()
        self.vlm_resolver = vlm_resolver
        #: Rows with real movement behind the most recent equation discovery.
        self._arithmetic_strength = 0
        #: (column, sign) of a movement column outside the canonical four that
        #: the most recent discovery had to account for, if any.
        self._adjustment: list[tuple[int, int]] | None = None

    # -- entry point ------------------------------------------------------

    def map_document(self, rows: list[Row], tokens: list[dict[str, Any]] | None = None,
                     page: int = 1, source: Source = Source.OCR) -> Document:
        doc = Document(page=page, source=source, tokens=list(tokens or []))

        header_indices = self._find_header_rows(rows)
        preamble_end = header_indices[0] if header_indices else len(rows)
        preamble = list(rows[:preamble_end])

        # Rows *above* the first header are not all preamble. A page that
        # continues the previous page's table carries its rows first and only
        # then reaches a heading - `GENEX.pdf` p6 holds 45 rows of stock above a
        # header with nothing beneath it, and every one of them was filed as
        # address-block preamble: 215 numeric tokens, one cell. When enough of
        # the rows before the first header read as data, they are a headerless
        # section of their own, and the shape gate decides as it does for any
        # other; the genuine preamble lines stay preamble.
        leading: list[Row] = []
        if header_indices:
            data_before = [r for r in preamble
                           if self._classify_row(r, set()) is RowType.DATA]
            # Two numeric-looking lines in a letterhead (phone, GSTIN) must not
            # become a table, so this asks for the small-sample floor rather
            # than the bare two-row minimum a table below a heading gets.
            if len(data_before) >= self.config.small_sample_rows:
                leading = self._headerless_section(data_before)
                taken = {r.index for r in data_before}
                preamble = [r for r in preamble if r.index not in taken]

        doc.preamble_rows = preamble
        doc.metadata = self._extract_metadata(preamble, page, source)

        for section in leading + self._split_sections(rows, header_indices):
            section.index = len(doc.sections)
            self._map_section(section, page)
            doc.sections.append(section)

        self._fill_report_details(doc, page, source)

        if not doc.sections:
            doc.notes.append("no header row found; grid left unsectioned")
        return doc

    # -- header detection -------------------------------------------------

    def _row_numeric_ratio(self, row: Row) -> float:
        """How much of the row is figures rather than words.

        "Figures" deliberately includes shapes the number parser cannot reduce
        to a single Decimal, such as the ``60:0`` quantity-and-free pairs one
        ERP prints. Counting those as text made a row of stock look like a row
        of headings: it scored as a header, split its table in two, and the
        second half was mapped from a data row's values as though they were
        column names.
        """
        populated = [c for c in row.cells if not c.is_blank]
        if not populated:
            return 0.0
        return sum(1 for c in populated if c.looks_quantitative) / len(populated)

    def _header_keyword_hits(self, row: Row) -> int:
        hits = 0
        for cell in row.cells:
            if cell.is_blank or cell.is_numeric:
                continue
            flow, f_score = _best_flow(cell.raw_text)
            simple, s_score = _best_simple(cell.raw_text)
            if max(f_score, s_score) >= 0.68:
                hits += 1
            elif set(_tokens(cell.raw_text)) & _GENERIC_HEADER_WORDS:
                hits += 1
        return hits

    def _score_header_row(self, rows: list[Row], i: int) -> float:
        """Header rows are non-numeric themselves and sit above numeric rows."""
        row = rows[i]
        populated = [c for c in row.cells if not c.is_blank]
        if len(populated) < 2:
            return 0.0
        if self._row_numeric_ratio(row) > 0.25:
            return 0.0

        below = rows[i + 1: i + 1 + self.config.header_lookahead]
        numeric_below = [self._row_numeric_ratio(r) for r in below
                         if any(not c.is_blank for c in r.cells)]
        below_score = (sum(numeric_below) / len(numeric_below)) if numeric_below else 0.0

        hits = self._header_keyword_hits(row)
        non_numeric = 1.0 - self._row_numeric_ratio(row)
        score = 0.40 * non_numeric + 0.35 * below_score + 0.25 * min(1.0, hits / 3.0)
        # A row of pure prose with no recognised headings is a title, not a header.
        if hits == 0 and below_score < 0.5:
            return 0.0
        return score

    def _inside_figure_rows(self, rows: list[Row], i: int) -> bool:
        """Is a two-cell row part of a run of product rows below figures?

        Looks back past other narrow rows (products with no movement) to the
        nearest wider row: if that row carries figures, row ``i`` is inside a
        table, not the start of one.
        """
        if len([c for c in rows[i].cells if not c.is_blank]) > 2:
            return False
        # A banner over a second report's heading line is a header, not a
        # product: `HETERO HEALTCARE LTD.(FRENZA)` sits above the heading of
        # the second statement in `HETRO.XLS`. What follows tells them apart -
        # a product row is followed by more products, a banner by a heading.
        for k in range(i + 1, len(rows)):
            if not any(not c.is_blank for c in rows[k].cells):
                continue
            if self._score_header_row(rows, k) >= 0.55:
                return False
            break
        for k in range(i - 1, -1, -1):
            populated = [c for c in rows[k].cells if not c.is_blank]
            if len(populated) <= 2:
                continue
            return self._row_numeric_ratio(rows[k]) > 0.25
        return False

    def _find_header_rows(self, rows: list[Row]) -> list[int]:
        found: list[int] = []
        i = 0
        while i < len(rows):
            # A product with no movement prints only its name and pack - two
            # text cells - and, sitting above rows of figures, scored as a new
            # header, cutting its table into pieces (`pdf&rendition=1-3.pdf`:
            # `GENXVAST 5 MG | 10 CAP`). A header does not start in the middle
            # of a table, so a two-cell row inside a run of product rows below
            # figures is kept as data.
            if found and i > 0 and self._inside_figure_rows(rows, i):
                i += 1
                continue
            if self._score_header_row(rows, i) >= 0.55:
                found.append(i)
                # Step over a tier-2 row so it is not taken for a header of its
                # own; anything further along may legitimately start a section.
                i += 2 if (i + 1 < len(rows)
                           and self._is_subheader(rows[i + 1], rows[i])) else 1
            else:
                i += 1
        return found

    # -- two-tier headers --------------------------------------------------

    def _is_subheader(self, row: Row, parent: Row | None = None) -> bool:
        """A tier-2 row is non-numeric and made of *bare* measure words.

        The cells must consist of nothing but measure vocabulary - "QTY.",
        "VALUE". A heading that merely contains one, such as "Gross Amount" or
        "Bill No", is a header in its own right, not a sub-heading. That
        vocabulary test is the whole decision.

        There used to be a second rule here: that a spanning parent has fewer
        cells than the tier it spans. It held for a header like
        ``OPENING | RECEIPT`` sitting over ``QTY. | VALUE | QTY. | VALUE``, but
        it rejected the other common shape outright - a header whose column
        labels simply wrap onto two lines, one per column, where the upper row
        has *more* cells than the lower. Those pages then treated both rows as
        separate headers, discarded the row carrying the flow words, and left
        every column labelled only "Qty." or "Value" - which made issue and
        closing impossible to tell apart and flagged two whole columns per page.
        """
        populated = [c for c in row.cells if not c.is_blank]
        if len(populated) < 2 or self._row_numeric_ratio(row) > 0.1:
            return False
        markers = 0
        for c in populated:
            toks = set(_tokens(c.raw_text))
            if toks and toks <= (_QTY_MARKERS | _VALUE_MARKERS):
                markers += 1
        return markers >= max(2, len(populated) // 2)

    @staticmethod
    def _spanning_parent(child_cell: Cell, parent_cells: list[Cell],
                         nearest_left: Cell | None) -> Cell | None:
        """The spanning heading a sub-column sits under when it touches none.

        A heading printed *left-aligned* over its span starts above its first
        sub-column, so the nearest heading to the left is right for every
        sub-column after it - which is why that was the rule. A heading printed
        *centred* over `QTY. | VALUE` overlaps only the right-hand child; the
        left-hand one touches nothing, and the nearest heading to its left is
        the *previous* span. On `GENEX.pdf` that labelled opening quantity
        `ITEM DESCRIPTION QTY.`, issue quantity `RECEIPT QTY.` and closing
        quantity `ISSUE QTY.`, on every page, and every continuation page
        inherited the wrong names.

        The two layouts are told apart by the one heading that could be the
        answer on the right. If the next heading's span starts within this
        child's own width of it - it is centred over a group this child opens -
        that heading wins. Otherwise the left-hand rule stands.
        """
        if child_cell.provenance.bbox is None:
            return nearest_left
        cx0, _, cx1, _ = child_cell.provenance.bbox
        width = max(cx1 - cx0, 1.0)
        right = [pc for pc in parent_cells
                 if pc.provenance.bbox and pc.provenance.bbox[0] >= cx1]
        if not right:
            return nearest_left
        candidate = min(right, key=lambda pc: pc.provenance.bbox[0])  # type: ignore[index]
        px0, _, px1, _ = candidate.provenance.bbox  # type: ignore[misc]
        if px0 - cx1 <= width and (px0 + px1) / 2.0 - cx1 <= (px1 - px0) / 2.0 + width:
            return candidate
        return nearest_left

    def _merge_header_tiers(self, parent: Row, child: Row) -> dict[int, list[str]]:
        """Join a two-line header into one heading per column.

        Two shapes occur, and both have to work:

        *Spanning* - ``OPENING`` sits above ``QTY. | VALUE`` and covers both.
        The parent has fewer cells than the tier below, and is matched by
        x-overlap.

        *Wrapped* - each column's own label runs onto two lines, so
        ``Op. | Opening Bal | Receipt`` sits directly above
        ``Qty. | Value | Qty.`` with the two rows aligned one to one. Here the
        parent cell at the *same column index* is the right answer, and it is
        tried first: for a spanning header the parent sits at the leftmost
        column of its span, which is that span's first child column, so a
        direct hit is correct there too.
        """
        merged: dict[int, list[str]] = {}
        parent_cells = [c for c in parent.cells if not c.is_blank]
        have_boxes = all(c.provenance.bbox for c in parent_cells) and \
            all(c.provenance.bbox for c in child.cells if not c.is_blank)

        for child_cell in child.cells:
            parts: list[str] = []
            direct = parent.cell_at(child_cell.column_index)
            if direct is not None and direct.raw_text.strip():
                parts.append(direct.raw_text.strip())
            elif have_boxes and child_cell.provenance.bbox:
                cx0, _, cx1, _ = child_cell.provenance.bbox
                best, best_overlap = None, 0.0
                nearest_left, nearest_dx = None, float("inf")
                for pc in parent_cells:
                    px0, _, px1, _ = pc.provenance.bbox  # type: ignore[misc]
                    overlap = min(cx1, px1) - max(cx0, px0)
                    if overlap > best_overlap:
                        best, best_overlap = pc, overlap
                    if px0 <= cx0 and (cx0 - px0) < nearest_dx:
                        nearest_left, nearest_dx = pc, cx0 - px0
                chosen = best if best_overlap > 0 else self._spanning_parent(
                    child_cell, parent_cells, nearest_left)
                if chosen is not None:
                    parts.append(chosen.raw_text.strip())
            elif len(parent_cells) == len(child.cells):
                parts.append(parent_cells[child_cell.column_index].raw_text.strip())

            if child_cell.raw_text.strip():
                parts.append(child_cell.raw_text.strip())
            merged[child_cell.column_index] = [p for p in parts if p]
        return merged

    # -- sectioning --------------------------------------------------------

    def _classify_row(self, row: Row, header_indices: set[int]) -> RowType:
        if row.index in header_indices:
            return RowType.HEADER
        populated = [c for c in row.cells if not c.is_blank]
        if not populated:
            return RowType.BLANK
        first_text = populated[0].raw_text
        if _TOTAL_RE.match(first_text):
            return RowType.TOTAL
        # The label can also *end* in "total": `Division Total`, `End Of
        # Report Total` on `AAI PHARMA JUNE26.pdf`, where both were exported
        # as products and the table reported no totals at all. Only the words
        # before the first figure are read, and they must be a short label,
        # so a product line is not caught by a word elsewhere in it.
        label: list[str] = []
        for cell in populated:
            if cell.looks_quantitative:
                break
            label.append(cell.raw_text.strip())
        label_text = " ".join(label)
        if (label and len(label_text.split()) <= 5 and len(label) < len(populated)
                and _TOTAL_TAIL_RE.search(label_text)):
            return RowType.TOTAL
        if _CONTINUATION_RE.search(row.text) and len(populated) <= 2:
            return RowType.METADATA
        if len(populated) == 1 and not populated[0].is_numeric:
            return RowType.SECTION_TITLE
        return RowType.DATA

    def _names_a_figures_column(self, lower: Row, body: list[Row]) -> bool:
        """Does this header-like row sit over at least one column of figures?

        A second header line names columns - `Qty`, `atestPurchRate` - and the
        columns worth naming carry figures. A manufacturer or group label such
        as `HETERO GENX PHARMA LTD (GEN` sits in the first line of the body,
        over the description and pack columns only. Folding it into the header
        turned `PACK` into `PACK (GEN` on `1000517655.jpg` and filed the label
        as a heading rather than the group its rows belong to.
        """
        for cell in lower.cells:
            if cell.is_blank:
                continue
            below = [r.cell_at(cell.column_index) for r in body]
            filled = [c for c in below if c is not None and not c.is_blank]
            if filled and sum(1 for c in filled if c.looks_quantitative) * 2 >= len(filled):
                return True
        return False

    def _adjacent_header_tiers(self, rows: list[Row],
                               header_indices: list[int]) -> tuple[dict[int, int], set[int]]:
        """Header rows that are really the second line of the header above.

        When two detected header rows sit on consecutive lines, the upper one
        gets no body at all: ``end`` equals ``body_start``, so the two-tier
        branch in ``_split_sections`` is unreachable. The names are stranded in
        a section with no rows while the rows below it carry no names - one
        section holding every heading and nothing else, another holding every
        data row under blank headings.

        That is a split header, not two tables. The tier-2 vocabulary test in
        ``_is_subheader`` cannot see it, because a second header line may carry
        a group label ("HETERO - GENX") or a clipped word ("atestPurchRate")
        alongside its measure words, and those are not bare measure vocabulary.

        Two conditions separate that from the shapes which must be left alone.

        *The pair must have a body.* Khushi ends with two headers over no rows
        at all - "Product | Pkg | BATCHNO | EXPIRY | Stock" above "Bill No |
        Bill Date | Gross Amount | Net Amount" - and those are genuinely
        separate blocks that must each keep their own headings and return
        empty.

        *The upper row must be the one carrying the names.* A banner above a
        full header is the same two adjacent rows seen from the other side:
        "STOCKIST NAME | Validation Errors" sits over a complete sixteen-column
        header, and folding it in yields "STOCKIST NAME Opening Stock" and
        loses the mapping that the lower row alone gets right. Requiring the
        upper row to be the fuller of the two keeps this to the case the
        stranding actually describes, where the lower row is a fragment and
        the columns beneath it would otherwise have no names at all.
        """
        forced: dict[int, int] = {}
        labels: set[int] = set()
        header_set = set(header_indices)
        for i, start in enumerate(header_indices):
            nxt = header_indices[i + 1] if i + 1 < len(header_indices) else None
            if nxt is None or nxt in forced.values():
                continue
            # "Adjacent" means nothing but whitespace and labels in between. A
            # group name on its own line - `Manufacturer Mfac Name` above
            # `Manufacturer 000092HETERO` on `305313_.pdf` - separates the two
            # header lines by an index without separating the table, and
            # requiring literal adjacency missed 686 structural flags across
            # eight pages of one file.
            # A row carrying figures is never "nothing in between", whatever it
            # is classified as. `KHAN MAY.pdf` p2 prints its `TOTAL` line
            # between the column header and a `Purchase Invoice No.` header;
            # pairing those two as tiers swallowed the total row, and its seven
            # figures reached no cell at all - the only coverage loss in the
            # MAY corpus.
            if any(self._classify_row(rows[j], header_set) is RowType.DATA
                   or any(c.looks_quantitative for c in rows[j].cells)
                   for j in range(start + 1, nxt)):
                continue
            upper = sum(1 for c in rows[start].cells if not c.is_blank)
            lower = sum(1 for c in rows[nxt].cells if not c.is_blank)
            if upper <= lower:
                continue
            after = header_indices[i + 2] if i + 2 < len(header_indices) else len(rows)
            body = [rows[j] for j in range(nxt + 1, after)
                    if self._classify_row(rows[j], header_set) is RowType.DATA]
            if not body:
                continue
            if self._names_a_figures_column(rows[nxt], body):
                forced[start] = nxt
            else:
                labels.add(nxt)
        return forced, labels

    def _headerless_section(self, rows: list[Row]) -> list[Section]:
        """A page of rows that never prints a header is still a page of rows.

        A scanned report paginates its table without repeating the headings:
        page 2 of `all in one.pdf` opens straight onto
        `.BILASET SYP 60ML | 60MI | 0 | 0 | 0 | 0 | 0` and runs for 68 numeric
        tokens. With no header row to anchor a section, sectioning returned
        nothing at all and the whole page fell through to the raw layer as
        preamble - not lost, but never column-mapped, never arithmetic-checked
        and invisible to every cell metric.

        Emitting one unheaded section instead lets the shape gate decide, as it
        does everywhere else: a real grid becomes a table whose columns are
        simply unnamed, and a page of prose is rejected by `_is_tabular` and
        returns to being a non-tabular block. Naming those columns is then the
        cross-page inheritance in `pipeline.py`, which is the same problem this
        file already solves when a continuation page keeps its headings.
        """
        section = Section(index=0, header_row_indices=[], header_rows=[])
        section._merged_header_parts = None      # type: ignore[attr-defined]
        section._header_row = Row(index=-1)      # type: ignore[attr-defined]
        for row in rows:
            row.row_type = self._classify_row(row, set())
            if row.row_type is RowType.BLANK:
                continue
            section.rows.append(row)
        return [section] if section.rows else []

    def _split_sections(self, rows: list[Row], header_indices: list[int]) -> list[Section]:
        if not header_indices:
            return self._headerless_section(rows)

        tier_two, labels = self._adjacent_header_tiers(rows, header_indices)
        header_set = set(header_indices) - labels
        absorbed = set(tier_two.values()) | labels
        starts = [h for h in header_indices if h not in absorbed]
        sections: list[Section] = []

        for n, start in enumerate(starts):
            end = starts[n + 1] if n + 1 < len(starts) else len(rows)
            header_row = rows[start]
            body_start = start + 1

            # Absorb a tier-2 header row if one follows.
            header_rows = [start]
            merged_parts: dict[int, list[str]] | None = None
            child = tier_two.get(start)
            if child is None and body_start < end and self._is_subheader(rows[body_start]):
                child = body_start
            if child is not None:
                merged_parts = self._merge_header_tiers(header_row, rows[child])
                header_rows.append(child)
                header_set.add(child)
                body_start = child + 1

            section = Section(index=n, header_row_indices=header_rows,
                              header_rows=[rows[i] for i in header_rows])
            section._merged_header_parts = merged_parts  # type: ignore[attr-defined]
            section._header_row = header_row             # type: ignore[attr-defined]

            title_before = self._title_above(rows, start)
            if title_before:
                section.title = title_before

            for row in rows[body_start:end]:
                # A group label found under the header titles the rows below it.
                row.row_type = (RowType.SECTION_TITLE if row.index in labels
                                else self._classify_row(row, header_set))
                if row.row_type is RowType.BLANK:
                    continue
                section.rows.append(row)
            sections.append(section)
        return sections

    def _title_above(self, rows: list[Row], header_index: int) -> str:
        """A lone text row immediately above a header names its section."""
        for j in range(header_index - 1, max(-1, header_index - 3), -1):
            row = rows[j]
            populated = [c for c in row.cells if not c.is_blank]
            if not populated:
                continue
            if len(populated) == 1 and not populated[0].is_numeric:
                return populated[0].raw_text.strip()
            return ""
        return ""

    # -- profiling ---------------------------------------------------------

    def _adopt_orphan_headings(self, section: Section, columns: list[ColumnMapping],
                               header_row: Row) -> None:
        """Put a heading back over its figures when they landed a band apart.

        Headings and figures are aligned differently - a short heading centred
        or left-aligned, its figures right-aligned - and on a photographed page
        the gap between them can be wide enough for column detection to give
        each its own band. The result is a column with a heading and nothing
        under it, beside a column of figures with no heading: `OB` alone, and
        `12, 41, 74, ...` under nothing, on `1000517655.jpg`.

        Only that exact pattern is repaired: the heading's band holds no data
        at all and the neighbour holds no heading at all. Where both neighbours
        qualify, the one whose figures sit nearer the heading wins.
        """
        def centre_of_data(index: int) -> float | None:
            xs = sorted((c.provenance.bbox[0] + c.provenance.bbox[2]) / 2.0
                        for r in section.data_rows
                        for c in [r.cell_at(index)]
                        if c is not None and not c.is_blank and c.provenance.bbox)
            return xs[len(xs) // 2] if xs else None

        for col in columns:
            if not col.header_text or col.profile is None or col.profile.populated:
                continue
            heading = header_row.cell_at(col.index)
            if heading is None or not heading.provenance.bbox:
                continue
            hx = (heading.provenance.bbox[0] + heading.provenance.bbox[2]) / 2.0
            options = []
            for j in (col.index - 1, col.index + 1):
                if not 0 <= j < len(columns):
                    continue
                other = columns[j]
                if other.header_text or other.profile is None or not other.profile.populated:
                    continue
                centre = centre_of_data(j)
                if centre is not None:
                    options.append((abs(centre - hx), other))
            if not options:
                continue
            _, target = min(options, key=lambda o: o[0])
            target.header_text, target.header_parts = col.header_text, list(col.header_parts)
            target.add_evidence(
                f"heading {col.header_text!r} adopted from column {col.index}, which "
                "holds no data: the heading and its figures were separated into "
                "neighbouring bands")
            col.add_evidence(f"heading moved to column {target.index}, where its figures are")
            col.header_text, col.header_parts = "", []

    def _share_spanning_heading(self, section: Section, columns: list[ColumnMapping],
                                header_row: Row) -> None:
        """Give a data column the words of a neighbour's heading printed over it.

        Two headings set close together can be read as one piece of text:
        `SNO ITEM DESCRIPTION` on `1000517655.jpg` spans both the serial-number
        column and the item column, and landed on the item column alone. The
        serial numbers were left under no heading (`column_1`) and the item key
        became `sno_item_description`.

        Repaired only when a populated column has no heading, its neighbour's
        heading is a single piece of text of several words, and that text
        physically extends over the unheaded column's data. Each word's position
        is estimated from its place in the text; the words whose centre lies on
        the unheaded column's side of the gap between the two columns' data go
        to it. At least one word must stay on each side, or nothing moves.

        The header row must name most of the populated columns. A title line
        mistaken for a header (`HETEROHEALTHCARELTD.ALL ... HETERO DERMA GLOW`
        on `DOC-20260703-WA0021.pdf` p14, naming 2 of 11 columns) is not a row
        of headings, and splitting a manufacturer's name across its columns
        cost that page a reconciled total.
        """
        with_data = [c for c in columns
                     if any(cell is not None and not cell.is_blank
                            for r in section.data_rows for cell in [r.cell_at(c.index)])]
        if not with_data or sum(1 for c in with_data if c.header_text) * 2 <= len(with_data):
            return
        def data_extent(index: int) -> tuple[float, float] | None:
            boxes = [c.provenance.bbox for r in section.data_rows for c in [r.cell_at(index)]
                     if c is not None and not c.is_blank and c.provenance.bbox]
            if not boxes:
                return None
            left = sorted(b[0] for b in boxes)
            right = sorted(b[2] for b in boxes)
            return left[len(left) // 2], right[len(right) // 2]

        for col in columns:
            if col.header_text or col.profile is None or not col.profile.populated:
                continue
            mine = data_extent(col.index)
            if mine is None:
                continue
            for step in (1, -1):              # heading to the right, then to the left
                j = col.index + step
                if not 0 <= j < len(columns):
                    continue
                other = columns[j]
                heading = header_row.cell_at(j)
                # One recognised piece of text only. A heading joined from
                # several pieces has gaps whose width is unknown, so word
                # positions estimated from character counts land wrongly:
                # `PACKING OPENING STOCK RECEIPT` on `DOC-20260703-WA0021.pdf`
                # p13 was cut as `PACKING OPENING` / `STOCK RECEIPT`.
                if (len(other.header_parts) != 1 or heading is None
                        or not heading.provenance.bbox
                        or len(heading.provenance.token_ids) > 1):
                    continue
                theirs = data_extent(j)
                if theirs is None:
                    continue
                h0, _, h1, _ = heading.provenance.bbox
                text = heading.raw_text.strip()
                words = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"\S+", text)]
                if len(words) < 2 or h1 <= h0:
                    continue
                if step == 1:
                    boundary = (mine[1] + theirs[0]) / 2.0
                    reaches = h0 < boundary
                else:
                    boundary = (theirs[1] + mine[0]) / 2.0
                    reaches = h1 > boundary
                if not reaches:
                    continue
                # It covers these two columns and no third. On
                # `DOC-20260703-WA0021.pdf` p13 one piece of text,
                # `PACKING OPENING STOCK RECEIPT`, spans three columns;
                # dividing it between two cut `OPENING STOCK` in half.
                others = [data_extent(k) for k in range(len(columns))
                          if k not in (col.index, j)]
                if any(e is not None and min(h1, e[1]) > max(h0, e[0]) for e in others):
                    continue
                scale = (h1 - h0) / len(text)
                centres = [h0 + scale * (a + b) / 2.0 for _, a, b in words]
                if step == 1:
                    given = [w for w, c in zip(words, centres) if c < boundary]
                    kept = words[len(given):]
                else:
                    given = [w for w, c in zip(words, centres) if c > boundary]
                    kept = words[:len(words) - len(given)]
                # the words must split cleanly: all given words on one end
                if not given or not kept or (step == 1 and given != words[:len(given)]) \
                        or (step == -1 and given != words[len(kept):]):
                    continue
                mine_text = " ".join(w for w, _, _ in given)
                kept_text = " ".join(w for w, _, _ in kept)
                col.header_text, col.header_parts = mine_text, [mine_text]
                other.header_text, other.header_parts = kept_text, [kept_text]
                col.add_evidence(
                    f"heading {mine_text!r} taken from {text!r} over column {j}: the "
                    "text extends over this column's data, which had no heading")
                other.add_evidence(f"heading {text!r} shared: {mine_text!r} belongs to "
                                   f"column {col.index}")
                break

    def _profile_columns(self, section: Section, n_columns: int) -> list[ColumnProfile]:
        profiles = [ColumnProfile(index=i) for i in range(n_columns)]
        for row in section.data_rows:
            for cell in row.cells:
                if cell.column_index >= n_columns:
                    continue
                p = profiles[cell.column_index]
                p.total_cells += 1
                if cell.is_blank:
                    p.blank_cells += 1
                    continue
                if cell.is_numeric and cell.value is not None:
                    p.numeric_cells += 1
                    exponent = cell.value.as_tuple().exponent
                    decimals = -int(exponent) if isinstance(exponent, int) and exponent < 0 else 0
                    p.max_decimals = max(p.max_decimals, decimals)
                    p.sample_texts.append(cell.raw_text)
                    if cell.value < 0:
                        p.has_negative = True
                    p.min_value = cell.value if p.min_value is None else min(p.min_value, cell.value)
                    p.max_value = cell.value if p.max_value is None else max(p.max_value, cell.value)
                else:
                    p.text_cells += 1
                    if _PACK_LIKE_RE.match(cell.raw_text):
                        p.packlike_cells += 1
                    if len(p.sample_texts) < 5:
                        p.sample_texts.append(cell.raw_text)

        for p in profiles:
            numeric_texts = [t for t in p.sample_texts]
            decimals = []
            for t in numeric_texts:
                if "." in t:
                    decimals.append(len(t.rsplit(".", 1)[1]))
                else:
                    decimals.append(0)
            if decimals:
                p.modal_decimals = Counter(decimals).most_common(1)[0][0]
            p.sample_texts = p.sample_texts[:5]
        return profiles

    # -- arithmetic discovery ---------------------------------------------

    def _column_series(self, section: Section, n_columns: int) -> list[list[Decimal | None]]:
        """Per-column values over data rows; None where the cell was blank."""
        series: list[list[Decimal | None]] = [[] for _ in range(n_columns)]
        for row in section.data_rows:
            for i in range(n_columns):
                cell = row.cell_at(i)
                series[i].append(cell.value if cell and cell.is_numeric else None)
        return series

    def _discover_stock_equation(
        self, series: list[list[Decimal | None]], candidates: list[int],
        header_flows: dict[int, str] | None = None,
    ) -> tuple[tuple[int, int, int, int], float, int, int] | None:
        """Find (opening, receipt, issue, closing) satisfying o + r - i = c.

        The equation is symmetric under several permutations of its terms:
        ``o + r - i = c`` is equally true as ``o + r - c = i``. Arithmetic can
        therefore identify *which four columns* form the stock group, but it
        cannot by itself say which of them is the issue and which the closing.
        The headings break that tie, via ``header_flows``; with no headings to
        go on the orientation is genuinely undetermined and the caller records
        the ambiguity rather than guessing silently.
        """
        cfg = self.config
        n_rows = len(series[candidates[0]]) if candidates else 0
        if n_rows < cfg.min_arithmetic_rows:
            return None

        best: tuple[tuple[int, int, int, int], float, int, int] | None = None
        self._adjustment = None
        for o in candidates:
            for r in candidates:
                if r == o:
                    continue
                for i in candidates:
                    if i in (o, r):
                        continue
                    for c in candidates:
                        if c in (o, r, i):
                            continue
                        agree = evaluable = informative = 0
                        for k in range(n_rows):
                            outcome = _check_equation(
                                series[o][k], series[r][k], series[i][k], series[c][k],
                                cfg.numeric_tolerance)
                            if outcome is None:
                                continue
                            evaluable += 1
                            agree += 1 if outcome else 0
                            # A row with no movement satisfies the equation
                            # whatever the columns mean, so it is no evidence.
                            if (series[r][k] or Decimal(0)) != 0 or \
                                    (series[i][k] or Decimal(0)) != 0:
                                informative += 1
                        if evaluable < cfg.min_arithmetic_rows:
                            continue
                        support = agree / evaluable
                        required = 1.0 if evaluable <= cfg.small_sample_rows else cfg.arithmetic_support

                        # Real ERPs carry flows the canonical four cannot
                        # express - stock transfers, adjustments. If one extra
                        # column accounts for every residual, this quadruple is
                        # the true stock group and that column is a separate
                        # movement, not the receipt column.
                        #
                        # This has to be tested *before* the support gate: the
                        # correct quadruple can sit just under the threshold
                        # precisely because an unmodelled column is absorbing
                        # the difference.
                        # Break the permutation symmetry with the headings.
                        agreement = 0
                        if header_flows:
                            for idx, flow in ((o, "opening"), (r, "receipt"),
                                              (i, "issue"), (c, "closing")):
                                if header_flows.get(idx) == flow:
                                    agreement += 1

                        adjustment = None
                        if cfg.adjustment_floor <= support < 1.0:
                            single = self._match_residual_column(
                                series, candidates, (o, r, i, c), cfg.numeric_tolerance)
                            adjustment = [single] if single else None
                        if adjustment is None and support < 1.0 and agreement == 4:
                            adjustment = self._match_residual_pair(
                                series, candidates, (o, r, i, c), cfg.numeric_tolerance)
                        effective = 1.0 if adjustment else support
                        if effective < required:
                            continue


                        score = (effective * min(1.0, informative / 8.0)
                                 # Needing no extra column to balance is
                                 # the simpler explanation; prefer it.
                                 + (0.0 if adjustment else 0.02)
                                 + 0.05 * agreement
                                 + 0.001 * informative + 0.0001 * evaluable)
                        if best is None or score > best[1]:
                            best = ((o, r, i, c), score, evaluable, informative)
                            self._adjustment = adjustment

        # ``o + r - i = c`` and ``o + r - c = i`` are the same statement, so no
        # amount of arithmetic can prefer one over the other. The search ends up
        # settling it on tie-breaks - chiefly how many rows show movement, which
        # differs between the two only by accident and says nothing about which
        # column is the issue. Where the document names them, the naming decides.
        # Leaving this to the score sent a page headed
        # ``OPENING | RECEIPT | ISSUE | CLOSING`` back with issue and closing
        # transposed, reporting no flags at all.
        if best is not None and header_flows:
            (o, r, i, c), score, evaluable, informative = best

            def agreement(issue_col: int, closing_col: int) -> int:
                return ((header_flows.get(issue_col) == "issue")
                        + (header_flows.get(closing_col) == "closing"))

            if agreement(c, i) > agreement(i, c):
                i, c = c, i
                # Recount against the orientation actually being adopted. The
                # tally belongs to the reading it describes, and carrying the
                # rejected one forward claimed ten rows of movement for a
                # reading that has two - which is the number that decides
                # whether a discovered relation may overrule an explicit
                # heading, so a stale count disabled that protection outright.
                evaluable = informative = 0
                for k in range(n_rows):
                    if _check_equation(series[o][k], series[r][k], series[i][k],
                                       series[c][k], cfg.numeric_tolerance) is None:
                        continue
                    evaluable += 1
                    if (series[r][k] or Decimal(0)) != 0 or \
                            (series[i][k] or Decimal(0)) != 0:
                        informative += 1
                best = ((o, r, i, c), score, evaluable, informative)
        return best

    def _match_residual_column(
        self, series: list[list[Decimal | None]], candidates: list[int],
        quad: tuple[int, int, int, int], tolerance: Decimal,
    ) -> tuple[int, int] | None:
        """Find a column that explains what ``o + r - i = c`` leaves over.

        Returns ``(column, sign)`` where the equation becomes
        ``o + r - i + sign*column = c``, or None when no single column accounts
        for the residuals.
        """
        o, r, i, c = quad
        n_rows = len(series[o])
        residuals: list[Decimal] = []
        rows_used: list[int] = []
        for k in range(n_rows):
            values = [series[x][k] for x in quad]
            if sum(1 for v in values if v is not None) < 2:
                continue
            ov, rv, iv, cv = (v or Decimal(0) for v in values)
            residuals.append(cv - (ov + rv - iv))
            rows_used.append(k)

        if len(rows_used) < 4 or all(abs(d) <= tolerance for d in residuals):
            return None

        for column in candidates:
            if column in quad:
                continue
            for sign in (1, -1):
                if all(abs(residual - sign * (series[column][k] or Decimal(0)))
                       <= tolerance
                       for residual, k in zip(residuals, rows_used)):
                    return (column, sign)
        return None

    def _match_residual_pair(
        self, series: list[list[Decimal | None]], candidates: list[int],
        quad: tuple[int, int, int, int], tolerance: Decimal,
    ) -> list[tuple[int, int]] | None:
        """Two columns that together explain what ``o + r - i = c`` leaves over.

        A report that prints free goods on both sides of the movement - `FR`
        after purchases and `FR` after sales - needs both to balance:
        `74 + 0 + 0 - 30 - 9 = 35`. No single column explains that residual,
        and because most rows carry free goods the four-term equation alone
        holds on too few rows for the one-column search to be tried at all.

        That is only safe because of where it is called from: every one of the
        four columns is already named by a heading, so arithmetic is not
        choosing the stock columns here, only accounting for the remainder. It
        must still account for it on the usual share of rows, and on at least
        `small_sample_rows` rows where free goods actually moved - a column of
        zeros explains a zero residual trivially and proves nothing. It must
        explain a majority of rows, the same bar the validator applies to a
        heading-anchored equation. Rows it does not explain are left for the
        validator to flag, which is how a misread gets caught rather than excused.
        """
        cfg = self.config
        o, r, i, c = quad
        residuals: list[tuple[int, Decimal]] = []
        for k in range(len(series[o])):
            values = [series[x][k] for x in quad]
            if sum(1 for v in values if v is not None) < 3:
                continue
            ov, rv, iv, cv = (v or Decimal(0) for v in values)
            residuals.append((k, cv - (ov + rv - iv)))
        moving = [k for k, d in residuals if abs(d) > tolerance]
        if len(residuals) < cfg.small_sample_rows or len(moving) < cfg.small_sample_rows:
            return None

        others = [x for x in candidates if x not in quad]
        best: tuple[int, list[tuple[int, int]]] | None = None
        for a_pos, a in enumerate(others):
            for b in others[a_pos + 1:]:
                for sa in (1, -1):
                    for sb in (1, -1):
                        explained = explained_moving = 0
                        for k, residual in residuals:
                            av = series[a][k] or Decimal(0)
                            bv = series[b][k] or Decimal(0)
                            if abs(residual - (sa * av + sb * bv)) <= tolerance:
                                explained += 1
                                if abs(residual) > tolerance:
                                    explained_moving += 1
                        # A majority, not the usual support share: the four
                        # stock columns are named by headings (see above), which
                        # is the same ground on which the validator adopts the
                        # equation from a majority. Holding the column search to
                        # a stricter bar than the check it feeds meant a page
                        # with a few misread closing stocks lost its free-goods
                        # columns entirely, and then balanced on one row in 17.
                        if (explained * 2 > len(residuals)
                                and explained_moving >= cfg.small_sample_rows
                                and (best is None or explained > best[0])):
                            best = (explained, [(a, sa), (b, sb)])
        return best[1] if best else None

    def _discover_rate_triple(
        self, series: list[list[Decimal | None]], candidates: list[int],
        known_qty: int | None,
    ) -> tuple[int, int, int, float] | None:
        """Find (qty, rate, value) with qty x rate ~= value."""
        cfg = self.config
        n_rows = len(series[candidates[0]]) if candidates else 0
        best: tuple[int, int, int, float] | None = None
        qty_options = [known_qty] if known_qty is not None else list(candidates)

        for q in qty_options:
            if q is None or q not in candidates:
                continue
            for t in candidates:
                if t == q:
                    continue
                for v in candidates:
                    if v in (q, t):
                        continue
                    agree = evaluable = 0
                    for k in range(n_rows):
                        qv, tv, vv = series[q][k], series[t][k], series[v][k]
                        if qv is None or tv is None or vv is None:
                            continue
                        # A zero factor makes the product zero whatever the
                        # columns mean, so a row where either is zero is no
                        # evidence. Counting rows where only both were zero let
                        # `CB x PUR = FR` fit a stock sheet on its many rows of
                        # no purchases and no free goods; it then overruled the
                        # `PUR` heading and pushed the real `RATE` column out.
                        # A genuine price column is never zero.
                        if qv == 0 or tv == 0:
                            continue
                        evaluable += 1
                        if _within_product_tolerance(qv * tv, vv):
                            agree += 1
                    if evaluable < cfg.min_arithmetic_rows:
                        continue
                    support = agree / evaluable
                    required = 1.0 if evaluable <= cfg.small_sample_rows else cfg.arithmetic_support
                    if support < required:
                        continue
                    score = support * min(1.0, evaluable / 8.0)
                    if best is None or score > best[3]:
                        best = (q, t, v, score)
        return best

    # -- per-section mapping ----------------------------------------------

    def _map_section(self, section: Section, page: int) -> None:
        header_row: Row = section._header_row          # type: ignore[attr-defined]
        merged: dict[int, list[str]] | None = section._merged_header_parts  # type: ignore[attr-defined]

        header_columns = max((c.column_index for c in header_row.cells), default=-1) + 1
        if merged:
            header_columns = max(header_columns, max(merged) + 1)
        section.header_column_count = header_columns

        data_columns = max(
            (max((c.column_index for c in r.cells), default=-1) + 1
             for r in section.rows), default=0)
        n_columns = max(header_columns, data_columns)

        # A column past the last heading is one of two very different things.
        # If nearly every row puts something there, it is a *column* the header
        # failed to name: the cells are sound, only anonymous. If two rows out
        # of a hundred reach it, those rows are ragged. Reporting the first as
        # corruption flagged 194 exact cells on one sheet over what was a
        # single fact about the header.
        data_rows = section.data_rows
        if data_columns > header_columns and data_rows:
            for index in range(header_columns, data_columns):
                present = sum(1 for r in data_rows if r.cell_at(index) is not None)
                if present / len(data_rows) >= self.config.unheaded_column_support:
                    section.unheaded_columns.append(index)
            if section.unheaded_columns:
                section.notes.append(
                    f"columns {section.unheaded_columns} hold data under no "
                    f"heading: the header names {header_columns} columns, but "
                    "most rows populate these as well, so they are treated as "
                    "unnamed columns rather than as cells that overflowed")
            ragged = [i for i in range(header_columns, data_columns)
                      if i not in section.unheaded_columns]
            if ragged:
                section.notes.append(
                    f"columns {ragged} are reached by only a few rows while the "
                    f"header names {header_columns}; those cells are unaccounted for")

        columns: list[ColumnMapping] = []
        for i in range(n_columns):
            if merged is not None and i in merged:
                parts = merged[i]
            else:
                cell = header_row.cell_at(i)  # type: ignore[assignment]
                parts = [cell.raw_text.strip()] if cell and cell.raw_text.strip() else []
            columns.append(ColumnMapping(index=i, header_text=" ".join(parts),
                                         header_parts=list(parts)))
        section.columns = columns

        profiles = self._profile_columns(section, n_columns)
        for col, prof in zip(columns, profiles):
            col.profile = prof
        self._adopt_orphan_headings(section, columns, header_row)
        self._share_spanning_heading(section, columns, header_row)

        # Decide whether this is a table *before* trying to map it. An address
        # block or a page footer has headings and cells like any other section,
        # and mapping it produces nonsense roles, a meaningless column-mapping
        # denominator, and thousands of VLM questions about things that were
        # never columns.
        if not section.data_rows:
            section.kind = SectionKind.EMPTY
            section.notes.append("header present with no data rows; "
                                 "returned empty rather than inventing rows")
            return
        if not self._is_tabular(section, n_columns):
            section.kind = SectionKind.NON_TABULAR
            return

        self._apply_header_matching(columns)
        arithmetic = self._apply_arithmetic(section, columns, n_columns)
        self._resolve_conflicts(columns, arithmetic)
        self._penalise_unresolved_orientation(columns)
        self._apply_profile_fallbacks(columns)
        self._maybe_call_vlm(section, columns, page)
        self._classify_section_kind(section)

    def _is_tabular(self, section: Section, n_columns: int) -> bool:
        """Is this section a real table, or a block of prose in a grid?

        Five structural signals, none of which depends on what the columns are
        *called*. A table has enough rows to establish a pattern, fills its
        columns consistently, carries numbers, and uses the same columns all the
        way down. Address blocks and title blocks fail several at once.
        """
        cfg = self.config
        rows = section.data_rows
        # A cell printed as a nil glyph (`-`) is a quantity the document states
        # as none, not prose. Counting it as prose made a table of mostly-nil
        # rows read as an address block (`Balaji Narayan Chitale.pdf`).
        numeric = sum(1 for r in rows for c in r.cells
                      if c.is_numeric or (c.is_blank and c.raw_text.strip()))
        filled = sum(len([c for c in r.cells if c.raw_text.strip()]) for r in rows)

        # 1. Enough rows for a pattern to exist at all.
        row_count = len(rows)

        # A stock statement lists every product, and a product that did not
        # move prints only its name and pack. Those rows are part of the table
        # but say nothing about its column pattern; counted in, they made a
        # real table read as ragged (`pdf&rendition=1-3.pdf`: consistency 0.18,
        # score 0.45). The shape is measured on rows that carry figures, when
        # there are enough of them; an address block rarely has, and is
        # measured on all its rows as before.
        figure_rows = [r for r in rows if any(c.is_numeric for c in r.cells)]
        if len(figure_rows) >= max(cfg.min_tabular_rows, 3) and len(figure_rows) < row_count:
            shape_rows = figure_rows
            section.notes.append(
                f"{row_count - len(figure_rows)} row(s) with no figures (items with no "
                "movement) left out of the shape measures")
        else:
            shape_rows = rows
        populated = [len([c for c in r.cells if c.raw_text.strip()]) for r in shape_rows]
        shape_filled = sum(populated)
        shape_count = len(shape_rows)
        # 2. Rows of a table hold a similar number of cells.
        mean = shape_filled / shape_count if shape_count else 0.0
        if shape_count > 1 and mean:
            spread = (sum((p - mean) ** 2 for p in populated) / shape_count) ** 0.5
            consistency = max(0.0, 1.0 - spread / mean)
        else:
            consistency = 0.0
        # 3. Rows actually fill the columns that were detected - counting only
        # columns the data ever uses. A spreadsheet with merged headings
        # declares a column for every cell the merge spans, so `MUKTJIVAN MAY
        # KALOL.xls` offers 52 columns of which 22 hold anything; its 80 rows
        # were judged to "fill 11% of the 52 columns" and the sheet was thrown
        # out as prose. A column no row reaches is not a column the rows failed
        # to fill. Bands found from ink cannot be empty, so this changes
        # nothing for scans and photos.
        used = {c.column_index for r in shape_rows for c in r.cells if c.raw_text.strip()}
        effective_columns = len(used) or n_columns
        occupancy = mean / effective_columns if effective_columns else 0.0
        # 4. A stock table is mostly figures.
        density = numeric / filled if filled else 0.0
        # 5. The same columns are used down the section.
        signatures = Counter(tuple(sorted(c.column_index for c in r.cells
                                          if c.raw_text.strip())) for r in shape_rows)
        stability = signatures.most_common(1)[0][1] / shape_count if shape_count else 0.0

        failures: list[str] = []
        if row_count < cfg.min_tabular_rows:
            failures.append(f"only {row_count} data row(s)")
        if occupancy < cfg.min_band_occupancy:
            failures.append(f"rows fill {occupancy:.0%} of the {effective_columns} "
                            "column(s) the data uses")
        if density < cfg.min_numeric_density:
            failures.append(f"{density:.0%} of cells are numeric")
        if consistency < cfg.min_row_consistency:
            failures.append(f"cell counts vary widely (consistency {consistency:.2f})")
        if stability < cfg.min_band_stability and row_count >= cfg.min_tabular_rows:
            failures.append(f"only {stability:.0%} of rows share a column signature")

        section.tabular_signals = {
            "rows": row_count, "consistency": round(consistency, 3),
            "band_occupancy": round(occupancy, 3), "numeric_density": round(density, 3),
            "band_stability": round(stability, 3), "failures": list(failures),
        }

        # Weigh the signals rather than counting failures. A genuine table can
        # be short (Khushi's runs to two rows) or description-heavy, so no
        # single signal may veto on its own; but an address block is weak on
        # several at once and falls well below the line.
        score = (0.28 * min(1.0, occupancy) + 0.28 * density
                 + 0.18 * consistency + 0.18 * stability
                 + 0.08 * min(1.0, row_count / 5.0))
        section.tabular_signals["score"] = round(score, 3)
        section.tabular_signals["threshold"] = cfg.tabular_threshold

        if row_count < cfg.min_tabular_rows or score < cfg.tabular_threshold:
            # Saying "too few rows" whenever nothing failed outright was wrong,
            # and it sent the last round of triage after the wrong signal: a
            # section can clear every individual test and still not reach the
            # weighted line. Name what actually fell short.
            reason = "; ".join(failures) if failures else (
                f"no single signal failed, but the weighted score fell short "
                f"(occupancy {occupancy:.0%}, numeric {density:.0%}, "
                f"consistency {consistency:.2f}, stability {stability:.2f})")
            section.notes.append(
                f"not a table (score {score:.2f} < {cfg.tabular_threshold:.2f}): "
                + reason +
                ". Content kept in the raw layer; not column-mapped, not "
                "arithmetic-checked, not sent to the VLM.")
            return False
        if failures:
            section.notes.append(
                f"treated as a table (score {score:.2f}) despite: "
                + "; ".join(failures))
        return True

    def _apply_header_matching(self, columns: list[ColumnMapping]) -> None:
        cfg = self.config
        for col in columns:
            header = col.header_text
            if not header.strip():
                col.add_evidence("no header text")
                continue

            if set(_tokens(header)) & _REVERSING_MODIFIERS:
                col.add_evidence(f"'{header}' is a reversing flow (return/rejection); "
                                 "no canonical role exists, left unknown")
                continue

            simple_role, simple_score = _best_simple(header)
            flow, flow_score = _best_flow(header)

            if flow and flow_score >= simple_score and flow_score >= cfg.header_accept:
                # A stock flow is a number. If the column below holds dates or
                # names, the heading matched by accident ("RECEIVE DATE").
                if col.profile and col.profile.populated > 0 and not col.profile.is_numeric:
                    col.add_evidence(
                        f"header '{header}' looks like {flow}, but the column is "
                        "not numeric; flow role rejected")
                    continue
                header_measure = _measure_from_header(header)
                measure = header_measure or self._measure_from_profile(col)
                role = _flow_role(flow, measure)
                col.role = role
                col.confidence = flow_score if flow_score < 0.9 else 0.9
                col.method = (MappingMethod.HEADER_EXACT if flow_score >= 0.88
                              else MappingMethod.HEADER_FUZZY)
                col.measure_from_header = header_measure is not None
                col.add_evidence(f"header '{header}' -> {flow} ({flow_score:.2f}), "
                                 f"measure={measure}"
                                 + ("" if header_measure else " (inferred from data shape)"))
            elif simple_role and simple_score >= cfg.header_accept:
                col.role = simple_role
                col.confidence = simple_score if simple_score < 0.9 else 0.9
                col.method = (MappingMethod.HEADER_EXACT if simple_score >= 0.88
                              else MappingMethod.HEADER_FUZZY)
                col.add_evidence(f"header '{header}' -> {simple_role.value} ({simple_score:.2f})")
            else:
                col.add_evidence(f"header '{header}' matched nothing above "
                                 f"{cfg.header_accept:.2f}")

    def _measure_from_profile(self, col: ColumnMapping) -> str:
        """Decide qty vs value when the heading is bare (Amar's 'Opening').

        Value columns are conventionally money: two decimals. Quantity columns
        are counts, whether printed as integers or padded to three decimals.
        """
        p = col.profile
        if p is None or not p.is_numeric:
            return "qty"
        if p.modal_decimals == 2 and (p.mean_abs is None or True):
            return "value"
        return "qty"

    def _apply_arithmetic(self, section: Section, columns: list[ColumnMapping],
                          n_columns: int) -> dict[int, Role]:
        """Discover roles from the data. Returns column index -> role."""
        assigned: dict[int, Role] = {}
        self._arithmetic_strength = 0
        if not section.data_rows:
            return assigned

        series = self._column_series(section, n_columns)
        numeric_cols = [c.index for c in columns
                        if c.profile and c.profile.is_numeric]
        if len(numeric_cols) > self.config.max_numeric_columns_for_search:
            # Narrow the search using whatever the headers already suggested.
            hinted = [c.index for c in columns if c.role in
                      (Role.OPENING_QTY, Role.RECEIPT_QTY, Role.ISSUE_QTY,
                       Role.CLOSING_QTY, Role.OPENING_VALUE, Role.RECEIPT_VALUE,
                       Role.ISSUE_VALUE, Role.CLOSING_VALUE)]
            numeric_cols = hinted or numeric_cols[: self.config.max_numeric_columns_for_search]
        if len(numeric_cols) < 4:
            return assigned

        header_flows = {
            col.index: col.role.value.rsplit("_", 1)[0]
            for col in columns
            if col.role in STOCK_FLOW_ROLES
        }
        found = self._discover_stock_equation(series, numeric_cols, header_flows)
        if found:
            (o, r, i, c), score, evaluable, informative = found
            self._arithmetic_strength = informative
            # Headings elsewhere on the row do not settle *this* pair. Unless
            # one of the two columns is itself named, the assignment is a coin
            # flip - and testing only for the total absence of headings let a
            # page with four well-named columns and two anonymous ones report
            # the anonymous pair with full confidence.
            settled = (header_flows.get(i) == "issue"
                       or header_flows.get(c) == "closing")
            if not settled:
                for idx in (i, c):
                    columns[idx].orientation_ambiguous = True
                    columns[idx].add_evidence(
                        "issue/closing orientation is not determined by arithmetic "
                        "alone (the equation is symmetric); no heading named either "
                        "column, so the two may be transposed")
            measure = self._group_measure(columns, [o, r, i, c])
            for idx, flow in ((o, "opening"), (r, "receipt"), (i, "issue"), (c, "closing")):
                assigned[idx] = _flow_role(flow, measure)
                columns[idx].add_evidence(
                    f"arithmetic: columns ({o},{r},{i},{c}) satisfy "
                    f"opening+receipt-issue=closing on {evaluable} rows "
                    f"({informative} with actual movement)")
            section.notes.append(
                f"stock equation holds for columns ({o},{r},{i},{c}) over "
                f"{evaluable} rows, {informative} of them with movement")

            for extra, sign in self._adjustment or []:
                symbol = "+" if sign > 0 else "-"
                section.notes.append(
                    f"column {extra} is a further movement outside the canonical "
                    f"four: opening+receipt-issue {symbol} col{extra} = closing")
                section.adjustments.append((extra, sign, measure))
                columns[extra].adjustment_column = True
                columns[extra].add_evidence(
                    f"accounts for the residual of the stock equation "
                    f"({symbol}col{extra}); this is a movement the canonical role "
                    "set has no name for, so it is left unmapped rather than "
                    "mislabelled as a receipt or issue")

            rate = self._discover_rate_triple(series, numeric_cols, known_qty=c)
            if rate:
                q, t, v, r_score = rate
                # A heading that says "Qty." is a stronger claim about the
                # measure than an arithmetic fit is. `qty x rate = value` has
                # three numeric columns and several plausible assignments, and
                # on a wide report some unrelated pair multiplies out by
                # coincidence. Never label a column the document itself calls a
                # quantity as a rate or a value - that produced "Repl. Qty."
                # mapped to closing_value, on a page reporting zero flags.
                rate_ok = _measure_from_header(columns[t].header_text) != "qty"
                value_ok = _measure_from_header(columns[v].header_text) != "qty"

                if not rate_ok:
                    columns[t].add_evidence(
                        f"arithmetic proposed rate for {columns[t].header_text!r}, "
                        "but the heading says quantity; refused")
                elif columns[t].role is not Role.RATE:
                    assigned[t] = Role.RATE

                if not value_ok:
                    columns[v].add_evidence(
                        f"arithmetic proposed a value role for "
                        f"{columns[v].header_text!r}, but the heading says "
                        "quantity; refused")
                else:
                    assigned.setdefault(v, Role.CLOSING_VALUE)

                if rate_ok and value_ok:
                    columns[t].add_evidence(f"arithmetic: col{q} x col{t} ~= col{v}")
                    columns[v].add_evidence(f"arithmetic: col{q} x col{t} ~= col{v}")
                    section.notes.append(f"rate relation col{q} x col{t} = col{v}")
        return assigned

    def _group_measure(self, columns: list[ColumnMapping], indices: list[int]) -> str:
        """Is a discovered equation group the quantity set or the value set?"""
        votes = [_measure_from_header(columns[i].header_text) for i in indices]
        votes = [v for v in votes if v]
        if votes:
            return Counter(votes).most_common(1)[0][0]
        decimals = [columns[i].profile.modal_decimals for i in indices
                    if columns[i].profile]
        return "value" if decimals and Counter(decimals).most_common(1)[0][0] == 2 else "qty"

    def _resolve_conflicts(self, columns: list[ColumnMapping],
                           arithmetic: dict[int, Role]) -> None:
        """Reconcile header-derived and data-derived roles."""
        for col in columns:
            arith_role = arithmetic.get(col.index)
            if arith_role is None:
                continue
            if col.role is arith_role:
                col.confidence = min(0.99, max(col.confidence, 0.9) + 0.05)
                col.method = MappingMethod.HEADER_AND_ARITHMETIC
                col.add_evidence("header and arithmetic agree")
            elif col.role is Role.UNKNOWN:
                col.role = arith_role
                col.confidence = max(col.confidence, 0.80)
                col.method = MappingMethod.ARITHMETIC
                col.add_evidence("role recovered from arithmetic alone")
            elif _same_flow(col.role, arith_role) and not col.measure_from_header:
                # The heading named the flow and agrees; only the qty/value
                # split differed, and that came from profiling rather than from
                # the document. Arithmetic settles it - this is not a conflict.
                col.add_evidence(
                    f"header gave the flow, arithmetic settled the measure "
                    f"({col.role.value} -> {arith_role.value})")
                col.role = arith_role
                col.confidence = max(col.confidence, 0.92)
                col.method = MappingMethod.HEADER_AND_ARITHMETIC
            elif self._arithmetic_strength < self.config.min_override_rows:
                # Too few rows with real movement for the fit to outrank an
                # explicit heading: on a short page, spurious equations abound.
                col.add_evidence(
                    f"arithmetic suggested {arith_role.value}, but only "
                    f"{self._arithmetic_strength} row(s) with movement support it; "
                    f"keeping the header's {col.role.value}")
                col.confidence = min(col.confidence, 0.75)
            elif (not col.measure_from_header
                  and col.role in STOCK_FLOW_ROLES and arith_role in STOCK_FLOW_ROLES
                  and _arithmetic_cannot_decide(_flow_role(col.role.value.rpartition("_")[0],
                                                           arith_role.value.rpartition("_")[2]),
                                                arith_role, False)):
                # The flows commute (opening/receipt, issue/closing), so the
                # heading keeps the flow; the measure was only a guess from the
                # data's shape, so arithmetic settles that. On `1000411296.jpg`
                # `Opening` printed `51.00` beside `0.000` columns, was guessed
                # a rupee column, and lost its role to a swap with `In`: the
                # page could verify nothing.
                settled = _flow_role(col.role.value.rpartition("_")[0],
                                     arith_role.value.rpartition("_")[2])
                col.add_evidence(
                    f"arithmetic suggested {arith_role.value}; opening/receipt and "
                    f"issue/closing satisfy the equation equally, so the heading keeps "
                    f"the flow and arithmetic settles the measure ({col.role.value} -> "
                    f"{settled.value})")
                col.role = settled
                col.confidence = min(max(col.confidence, 0.80), 0.85)
                col.method = MappingMethod.HEADER_AND_ARITHMETIC
            elif _arithmetic_cannot_decide(col.role, arith_role, col.measure_from_header):
                # Overruling a heading is only justified by evidence the data
                # actually carries. These readings are the same equation, so the
                # data carries none - see _arithmetic_cannot_decide.
                col.add_evidence(
                    f"arithmetic suggested {arith_role.value}, but that reading and "
                    f"the header's {col.role.value} satisfy the equation equally; "
                    f"the heading decides")
                col.confidence = min(col.confidence, 0.85)
            else:
                # The data is evidence; a heading is only a label, and OCR
                # mangles labels. Keep both on the record.
                col.add_evidence(
                    f"CONFLICT: header suggested {col.role.value}, arithmetic "
                    f"suggests {arith_role.value} on {self._arithmetic_strength} "
                    f"rows with movement; arithmetic preferred")
                col.role = arith_role
                col.confidence = 0.65
                col.method = MappingMethod.ARITHMETIC

        # Two columns must not hold the same role.
        by_role: dict[Role, list[ColumnMapping]] = {}
        for col in columns:
            if col.role is not Role.UNKNOWN:
                by_role.setdefault(col.role, []).append(col)
        for role, claimants in by_role.items():
            if len(claimants) < 2 or role in (Role.UNKNOWN,):
                continue
            claimants.sort(key=lambda c: (
                c.index in arithmetic, c.confidence, -c.index), reverse=True)
            winner = claimants[0]
            for loser in claimants[1:]:
                loser.add_evidence(
                    f"duplicate role {role.value}; column {winner.index} won "
                    f"(conf {winner.confidence:.2f} vs {loser.confidence:.2f})")
                loser.role = Role.UNKNOWN
                loser.confidence = 0.0
                loser.method = MappingMethod.NONE

    def _penalise_unresolved_orientation(self, columns: list[ColumnMapping]) -> None:
        """Keep a coin-flip from being reported with a confident face.

        A role the arithmetic could not orient is a guess between two columns.
        Its confidence is pushed below the VLM threshold so the fallback is
        offered the question, and Stage B flags the cells: the numbers may be
        sound while the label on them is not, and a consumer reading the role
        would be misled in a way no arithmetic check can catch.
        """
        ceiling = min(0.50, self.config.vlm_threshold - 0.01)
        for col in columns:
            if col.orientation_ambiguous and col.confidence > ceiling:
                col.confidence = ceiling
                col.add_evidence(
                    f"confidence capped at {ceiling:.2f}: the role is one of two "
                    "equally consistent readings")

    def _apply_profile_fallbacks(self, columns: list[ColumnMapping]) -> None:
        """Last resort for still-unknown columns, using shape alone."""
        described = any(c.role is Role.ITEM_DESCRIPTION for c in columns)
        for col in columns:
            if col.role is not Role.UNKNOWN or col.profile is None:
                continue
            p = col.profile
            if p.populated == 0:
                col.add_evidence("column is empty")
                continue
            if p.text_cells and p.packlike_cells / p.text_cells >= 0.6:
                col.role = Role.PACK
                col.confidence = 0.55
                col.method = MappingMethod.PROFILE
                col.add_evidence(
                    f"{p.packlike_cells}/{p.text_cells} values look like pack sizes "
                    f"(e.g. {p.sample_texts[0]!r})" if p.sample_texts else "pack-shaped values")
                continue
            if not described and p.is_textual and col.index <= 1 and p.populated >= 2:
                col.role = Role.ITEM_DESCRIPTION
                col.confidence = 0.45
                col.method = MappingMethod.PROFILE
                col.add_evidence("leftmost all-text column; assumed item description")
                described = True

    def _maybe_call_vlm(self, section: Section, columns: list[ColumnMapping],
                        page: int) -> None:
        """Hand low-confidence columns to a VLM, if one was supplied."""
        unresolved = [c.index for c in columns
                      if c.confidence < self.config.vlm_threshold]
        if not unresolved:
            return
        section.notes.append(
            f"columns {unresolved} below VLM threshold "
            f"{self.config.vlm_threshold:.2f}")
        if self.vlm_resolver is None:
            return

        request = VLMColumnRequest(
            page=page,
            section_index=section.index,
            header_texts=[c.header_text for c in columns],
            column_profiles=[c.profile.to_dict() if c.profile else {} for c in columns],
            sample_rows=[[cell.raw_text for cell in row.cells]
                         for row in section.data_rows[:5]],
            unresolved_columns=unresolved,
            already_assigned={c.index: c.role.value for c in columns
                              if c.role is not Role.UNKNOWN},
        )
        try:
            response = self.vlm_resolver.resolve(request)
        except Exception as exc:  # a failed fallback must never lose the page
            section.notes.append(f"VLM resolver failed: {type(exc).__name__}: {exc}")
            return

        taken = {c.role for c in columns if c.role is not Role.UNKNOWN}
        for index, role_name in response.roles.items():
            if index not in unresolved or index >= len(columns):
                continue
            try:
                role = Role(role_name)
            except ValueError:
                section.notes.append(f"VLM proposed unknown role '{role_name}'; ignored")
                continue
            if role in taken and role is not Role.UNKNOWN:
                section.notes.append(
                    f"VLM proposed already-assigned role {role.value} for column "
                    f"{index}; ignored")
                continue
            columns[index].role = role
            columns[index].confidence = min(0.75, response.confidence.get(index, 0.6))
            columns[index].method = MappingMethod.VLM
            columns[index].add_evidence(f"VLM fallback: {role.value}. {response.note}".strip())
            taken.add(role)

    def _classify_section_kind(self, section: Section) -> None:
        stock_roles = section.roles_present() & set(
            list(Role.__members__.values())) & {
            Role.OPENING_QTY, Role.RECEIPT_QTY, Role.ISSUE_QTY, Role.CLOSING_QTY,
            Role.OPENING_VALUE, Role.RECEIPT_VALUE, Role.ISSUE_VALUE,
            Role.CLOSING_VALUE, Role.DUMP_QTY}
        if not section.data_rows:
            section.kind = SectionKind.EMPTY
            section.notes.append("header present with no data rows; "
                                 "returned empty rather than inventing rows")
            return

        # Whether this is a *table* was already settled by `_is_tabular`, on
        # shape alone. Whether it is a *stock* table is a different question,
        # and answering the first with the second was wrong: a clean six-column
        # sales table - `Company | QTY. | FREE | RATE | AMOUNT | (%)` on
        # `1000411295.jpg`, eight data rows under a header the reader found
        # exactly - was returned as a prose block, which made its page
        # unhealthy for having "no tabular section". The corpus holds sales and
        # purchase registers as well as stock statements (s1), and a table
        # without an opening/closing pair is still a table.
        section.kind = SectionKind.TABULAR
        if len(stock_roles) < 2:
            section.notes.append(
                "tabular, but no stock-flow columns: no row equation applies "
                "here, so these cells carry no arithmetic confirmation")
            # A lone stock-flow role in a block with no other is a stray
            # synonym hit, not a real column.
            for col in section.columns:
                if col.role in STOCK_FLOW_ROLES:
                    col.add_evidence(
                        f"{col.role.value} withdrawn: this block has no other "
                        "stock-flow columns, so the match was incidental")
                    col.role = Role.UNKNOWN
                    col.confidence = 0.0
                    col.method = MappingMethod.NONE

    # -- metadata ---------------------------------------------------------

    def _extract_metadata(self, rows: list[Row], page: int,
                          source: Source) -> DocumentMetadata:
        meta = DocumentMetadata()
        lines: list[tuple[int, str]] = []
        for row in rows:
            row.row_type = RowType.METADATA
            text = row.text.strip()
            if text:
                lines.append((row.index, text))

        def field_for(value: str, confidence: float) -> MetadataField:
            return MetadataField(
                value=value.strip(),
                confidence=confidence,
                provenance=Provenance(source=source, page=page),
            )

        used: set[int] = set()
        for index, line in lines:
            if meta.gstin is None:
                match = _GSTIN_STRICT.search(line.upper()) or _GSTIN_LABELLED.search(line.upper())
                if match:
                    value = match.group(0) if match.re is _GSTIN_STRICT else match.group(1)
                    meta.gstin = field_for(value, 0.9)
                    used.add(index)
            if meta.email is None:
                match = _EMAIL_RE.search(line)
                if match:
                    meta.email = field_for(match.group(0), 0.9)
                    used.add(index)
            if meta.phone is None:
                match = _PHONE_RE.search(line)
                if match:
                    meta.phone = field_for(match.group(1).strip(" ,"), 0.85)
                    used.add(index)
            if meta.manufacturer is None:
                match = _COMPANY_RE.search(line)
                if match:
                    value = re.split(r"\s{2,}", match.group(1).strip())[0]
                    meta.manufacturer = field_for(value, 0.85)
                    used.add(index)
                elif re.search(r"stock|analysis|summary|statement", line, re.IGNORECASE):
                    paren = _PARENTHETICAL_RE.search(line)
                    if paren:
                        meta.manufacturer = field_for(paren.group(1), 0.8)
                        used.add(index)
            if meta.period_from is None:
                period = _period_in(line)
                if period:
                    # As printed: `01-06-2026` stays `01-06-2026` (s4.4).
                    meta.period_from = field_for(period[0], 0.85)
                    meta.period_to = field_for(period[1], 0.85)
                    used.add(index)

        # The distributor name is the line that most looks like a business
        # name. It used to be the first substantial line, and on photos of a
        # screen that is the software's own text: `Main.Report` (a window
        # caption) on `1000517655.jpg`, `E-Sign (1) Sign in` (a PDF viewer's
        # toolbar) on `IMG-20260708-WA0018.jpg`, above `KETAKI PHARMACEUTICALS`
        # and `SHRI RAM MEDICAL HALL`.
        candidates = [(position, index, line) for position, (index, line) in enumerate(lines)
                      if index not in used and len(line) >= 4
                      and not re.search(r"stock|sales|analysis|summary|statement|page\s*no|from\s*:",
                                        line, re.IGNORECASE)]
        scored = [(_business_name_score(line), position, index, line)
                  for position, index, line in candidates]
        scored = [s for s in scored if s[0] > 0]
        if scored and meta.distributor_name is None:
            score, position, index, line = max(scored, key=lambda s: (s[0], -s[1]))
            meta.distributor_name = field_for(_business_name_part(line), 0.6 if score >= 2 else 0.4)
            used.add(index)
            if meta.address is None:
                meta.address = _address_after(lines, position, field_for)
        return meta


    def _fill_report_details(self, doc: Document, page: int, source: Source) -> None:
        """Report-level details from everything printed above the table.

        Metadata used to be read only from the lines before the first row that
        *looked* like a header. A report heading such as `STOCK REPORT   FROM
        DATE:01-06-2026 T0:30-06-2026` is itself header-shaped - short text in
        several cells - so it opened a section of its own and its dates were
        never read. The lines of every section that sits above the first real
        table are searched as well, and only fields still missing are filled.
        """
        lines: list[str] = [r.text.strip() for r in doc.preamble_rows if r.text.strip()]
        for section in doc.sections:
            if section.kind is SectionKind.TABULAR:
                break
            for row in list(section.header_rows) + list(section.rows):
                if row.text.strip():
                    lines.append(row.text.strip())
        meta = doc.metadata

        def field_for(value: str, confidence: float) -> MetadataField:
            return MetadataField(value=value.strip(), confidence=confidence,
                                 provenance=Provenance(source=source, page=page))

        if meta.period_from is None:
            for line in lines:
                period = _period_in(line)
                if period:
                    meta.period_from = field_for(period[0], 0.8)
                    meta.period_to = field_for(period[1], 0.8)
                    break

        if "report_title" not in meta.extra:
            for line in lines:
                if _REPORT_KIND_RE.search(line):
                    title = _TITLE_END_RE.split(line, maxsplit=1)[0].strip(" -:(")
                    if re.search(r"[A-Za-z]{3}", title):
                        meta.extra["report_title"] = field_for(title, 0.8)
                    break

        if meta.address is None and meta.distributor_name is not None:
            name = meta.distributor_name.value
            if name in lines:
                for line in lines[lines.index(name) + 1: lines.index(name) + 4]:
                    if _REPORT_KIND_RE.search(line) or re.search(r"page\s*no", line, re.I):
                        continue
                    place = _LABELLED_TAIL_RE.split(line, maxsplit=1)[0].strip(" ,-:")
                    # An address carries a comma or a number; a second line of
                    # the company name, or a window caption, carries neither.
                    if len(place) >= 4 and re.search(r"[A-Za-z]", place) and \
                            re.search(r"[,\d]", place):
                        meta.address = field_for(place, 0.6)
                        break


# ---------------------------------------------------------------------------
# Equation helpers
# ---------------------------------------------------------------------------


def _check_equation(o: Decimal | None, r: Decimal | None, i: Decimal | None,
                    c: Decimal | None, tolerance: Decimal) -> bool | None:
    """opening + receipt - issue == closing, with blanks read as zero.

    Returns None when there is too little on the row to judge - which is not
    the same as False, and must never be counted as a failure.
    """
    present = sum(1 for v in (o, r, i, c) if v is not None)
    if present < 2:
        return None
    ov = o or Decimal(0)
    rv = r or Decimal(0)
    iv = i or Decimal(0)
    cv = c or Decimal(0)
    return abs((ov + rv - iv) - cv) <= tolerance


def _within_product_tolerance(product: Decimal, printed: Decimal) -> bool:
    """qty x rate vs printed value, allowing for per-unit rounding.

    The tolerance is the larger of 0.1% and 0.10 absolute, because a rate
    rounded to paise accumulates error in proportion to quantity.
    """
    diff = abs(product - printed)
    return diff <= max(abs(printed) * Decimal("0.001"), Decimal("0.10"))


# ---------------------------------------------------------------------------
# Convenience + CLI
# ---------------------------------------------------------------------------


def map_grid(payload: dict[str, Any], config: MapperConfig | None = None,
             vlm_resolver: VLMColumnResolver | None = None) -> Document:
    rows, tokens, page, source = load_grid(payload)
    return ColumnMapper(config, vlm_resolver).map_document(rows, tokens, page, source)


def map_grid_file(path: str, config: MapperConfig | None = None,
                  vlm_resolver: VLMColumnResolver | None = None) -> Document:
    rows, tokens, page, source = load_grid_file(path)
    return ColumnMapper(config, vlm_resolver).map_document(rows, tokens, page, source)


def _summarise(doc: Document) -> str:
    out: list[str] = []
    meta = doc.metadata
    out.append(f"page {doc.page}  source={doc.source.value}")
    for key in ("distributor_name", "gstin", "manufacturer", "period_from", "period_to"):
        value = getattr(meta, key)
        if value:
            out.append(f"  {key:16} {value.value}")
    for section in doc.sections:
        out.append(f"\nsection {section.index}  kind={section.kind.value}  "
                   f"title={section.title!r}  rows={len(section.data_rows)} data / "
                   f"{len(section.total_rows)} total")
        for col in section.columns:
            out.append(f"  col {col.index:>2}  {col.role.value:<18} "
                       f"conf={col.confidence:.2f}  {col.method.value:<22} "
                       f"header={col.header_text!r}")
        for note in section.notes:
            out.append(f"  note: {note}")
    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Map grid columns to semantic roles")
    parser.add_argument("grid", help="path to a grid JSON file")
    parser.add_argument("--json", action="store_true", help="emit the full document as JSON")
    args = parser.parse_args(argv)

    doc = map_grid_file(args.grid)
    print(doc.to_json() if args.json else _summarise(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
