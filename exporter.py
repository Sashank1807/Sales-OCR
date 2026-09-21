#!/usr/bin/env python3
"""A structured report: the document's own table, one object per row.

    python exporter.py report.pdf              # print the structured report
    python exporter.py report.pdf -o out.json

Built from the pipeline's result, not from the OCR line list, and shaped for
whoever consumes the extraction rather than for auditing it:

* **Row keys are the document's own headings**, lowercased (`OB` -> `ob`,
  `OPENING QTY.` -> `opening_qty`). Every distributor names its columns
  differently, so the keys change from report to report.
* **`columns` says what each key means.** `ob` on one report and `op_stk` on
  another both carry `"role": "opening_qty"`. Code that compares reports reads
  the role; a person reading one report reads the key.
* **Every row carries its status.** `status` is the worst status among the
  row's figures; `needs_review` names the fields that need a person, and
  `review_reasons` says why for the flagged ones. Descriptive text that no
  arithmetic can confirm - item name, pack, serial number - is listed in
  `unchecked_text` (sampled review) instead of holding every row at
  `unchecked`.
* **Lines that are not products** - a screen's button bar photographed under
  the table - go to the table's `other_lines`, flagged, never dropped. A value is never presented as trustworthy just because it
  sits in a tidy JSON object - that is the silent error CLAUDE.md s2 forbids.
* **A field the system could not find is `null`**, never a guess.

Nothing here reads a document-specific layout (s4.3): keys come from whatever
headings the page prints, groups from whatever label rows it contains.

The audit record - verbatim cell text, bounding boxes, per-cell provenance - is
unchanged in the pipeline's own output. This is a view of it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from schema import (CellStatus, MappingMethod, Role, RowType, SectionKind, STOCK_FLOW_ROLES,
                    TEXTUAL_ROLES)

SCHEMA_VERSION = 1

_HEADER_METHODS = (MappingMethod.HEADER_EXACT, MappingMethod.HEADER_FUZZY,
                   MappingMethod.HEADER_AND_ARITHMETIC)

#: Roles whose cells must hold a figure. Text in one of them - a footer's
#: "Page 1 of 3" under a closing-stock heading - is a row that is not what it
#: claims to be, however exactly its characters were read.
_NUMERIC_ROLES = frozenset(STOCK_FLOW_ROLES) | {Role.RATE}

#: Worst first. A row takes the worst status of any cell in it.
_STATUS_ORDER = (CellStatus.FLAGGED, CellStatus.UNCHECKED, CellStatus.VERIFIED,
                 CellStatus.EXACT)


# ---------------------------------------------------------------------------
# Keys and values
# ---------------------------------------------------------------------------


def _slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")


def _keys_for(headings: list[str]) -> list[str]:
    """One unique key per column, from the heading the document prints.

    A heading printed twice (`FR` for free-with-purchase and free-with-sale)
    becomes `fr_1` and `fr_2`, numbered left to right. A column with no heading
    at all becomes `column_<position>`.
    """
    bases = [_slug(h) or f"column_{i}" for i, h in enumerate(headings, 1)]
    seen: dict[str, int] = {}
    totals = {b: bases.count(b) for b in bases}
    keys = []
    for base in bases:
        if totals[base] > 1:
            seen[base] = seen.get(base, 0) + 1
            keys.append(f"{base}_{seen[base]}")
        else:
            keys.append(base)
    return keys


def _value(cell) -> Any:
    """The cell as JSON: a number where the document printed one, else text.

    `1934.02` and `0.00` stay decimals and `12` stays whole, following what was
    printed. Anything the number parser does not reduce to a single figure -
    `10'S`, `60:0`, `87.91 1934.02` - stays as printed text rather than being
    coerced, because a coerced value would look more certain than it is.
    """
    if cell is None or cell.is_blank:
        return None
    if cell.is_numeric and cell.value is not None:
        value: Decimal = cell.value
        if "." in cell.raw_text:
            return float(value)
        try:
            return int(value)
        except (ValueError, OverflowError):
            return float(value)
    return cell.raw_text.strip()


def _has_text(value: str | None) -> bool:
    """Letters or digits, not just a rule of dashes or dots."""
    return bool(value) and bool(re.search(r"[A-Za-z0-9]", value))


def _serial_columns(section) -> set[int]:
    """Columns that number the rows: 1, 2, 3, ... down the table.

    A serial number is read from pixels like any figure, but nothing in the
    document can confirm it by arithmetic, so it would hold every row at
    `unchecked` over a field no one needs checked. Most adjacent rows must
    step by exactly one.
    """
    serial = set()
    for column in section.columns:
        values = []
        for row in section.data_rows:
            cell = row.cell_at(column.index)
            if cell is None or cell.is_blank:
                continue
            if not (cell.is_numeric and cell.value is not None
                    and cell.value == cell.value.to_integral_value()):
                values = []
                break
            values.append(int(cell.value))
        steps = [b - a for a, b in zip(values, values[1:])]
        if len(values) >= 3 and sum(1 for d in steps if d == 1) >= 0.8 * len(steps):
            serial.add(column.index)
    return serial


def _row_status(cells_by_key: dict[str, Any], roles_by_key: dict[str, str],
                descriptive: frozenset[str] = frozenset()
                ) -> tuple[str, list[str], dict[str, str], list[str]]:
    """A row's status, the fields to review, why, and text left unchecked.

    ``status`` is the worst status among the row's *figures*. Descriptive
    fields - item name, pack, code, serial number - have no arithmetic that
    could ever verify them, and counting them held every row of a photo at
    `unchecked`: `AD-100 CAP`, whose 12 + 40 - 30 = 22 the stock equation
    confirms, reported unchecked like all 23 rows of its table. They are
    listed in ``unchecked_text`` instead, which is sampled review under
    CLAUDE.md s5. A descriptive field that is *flagged* (low OCR confidence)
    still counts against the row.
    """
    present = {k: c for k, c in cells_by_key.items() if c is not None and not c.is_blank}
    if not present:
        return CellStatus.EXACT.value, [], {}, []
    judged = [c.status for k, c in present.items()
              if k not in descriptive or c.status is CellStatus.FLAGGED]
    statuses = judged or [c.status for c in present.values()]
    worst = next(s for s in _STATUS_ORDER if s in statuses)
    needs = [k for k, c in present.items()
             if c.status is CellStatus.FLAGGED
             or (c.status is CellStatus.UNCHECKED and k not in descriptive)]
    unchecked_text = [k for k, c in present.items()
                      if c.status is CellStatus.UNCHECKED and k in descriptive]
    reasons = {k: "; ".join(dict.fromkeys(c.reasons)) for k, c in cells_by_key.items()
               if c is not None and c.status is CellStatus.FLAGGED and c.reasons}

    # A value can be read exactly and still be the wrong kind of thing. The
    # footer "7/2/2026 9:08:14 PM ... Page 1 of 3" on `11.pdf` arrived as a row
    # with `exact` status and nothing to review. Its closing-stock field holds
    # text, which no genuine row does, so the row is flagged rather than passed
    # on as a product. It is not dropped: deciding it is not data is a person's
    # call, and silently removing rows is coverage loss by another name.
    for key, cell in cells_by_key.items():
        if cell is None or cell.is_blank or cell.looks_quantitative:
            continue
        role = roles_by_key.get(key)
        if role is not None and Role(role) in _NUMERIC_ROLES:
            worst = CellStatus.FLAGGED
            if key not in needs:
                needs.append(key)
            reasons[key] = "text where the column holds figures"
    return worst.value, needs, reasons, unchecked_text


def _is_screen_text(row, roles: dict[int, str]) -> bool:
    """Words under the figure headings and no figures anywhere under them.

    On a photo of a screen the software's own text lines up under the table:
    `SAVEPDF OPEN TOP FIND PRINT CAL END SAVEXL` and the taskbar's `Desktop`
    on `1000517655.jpg`. Such a line is not a product. A product with no stock
    movement has *blank* figure fields, never words, so it is unaffected.
    """
    words = figures = 0
    for cell in row.cells:
        if cell.is_blank:
            continue
        role = roles.get(cell.column_index)
        if role is None or Role(role) not in _NUMERIC_ROLES:
            continue
        if cell.looks_quantitative:
            figures += 1
        else:
            words += 1
    return words > 0 and figures == 0


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class _Table:
    """One logical table, possibly continued across several pages."""

    def __init__(self, section, page: int) -> None:
        ordered = sorted(section.columns, key=lambda c: c.index)
        self.headings = [c.header_text.strip() for c in ordered]
        keys = _keys_for(self.headings)
        self.columns = [{"key": k, "heading": h or None, "role": c.role.value,
                         "confidence": round(c.confidence, 2)}
                        for k, h, c in zip(keys, self.headings, ordered)]
        self.pages = [page]
        self.groups: list[dict[str, Any]] = []
        self.totals: list[dict[str, Any]] = []
        self.other_lines: list[dict[str, Any]] = []
        self.last_section = section
        self.key_by_index = {c.index: k for k, c in zip(keys, ordered)}
        self.flow_roles = [c.role for c in ordered
                           if c.role in _NUMERIC_ROLES and c.role is not Role.RATE]
        # The index -> key mapping of whichever section was added last. A
        # continuation page is aligned against *that* page, whose column
        # indices can differ from the first page's.
        self.last_keys = dict(self.key_by_index)

    @property
    def keys(self) -> list[str]:
        return [c["key"] for c in self.columns]

    def extra_key(self, index: int, role: str) -> str:
        """A column this table did not have before - an unheaded band on a
        continuation page, or a cell beyond the last heading."""
        key = f"column_{index + 1}"
        while key in self.keys:
            key += "_x"
        self.columns.append({"key": key, "heading": None, "role": role, "confidence": 0.0})
        return key

    def add_rows(self, section, page: int, key_by_index: dict[int, str]) -> None:
        if page not in self.pages:
            self.pages.append(page)
        roles = {c.index: c.role.value for c in section.columns}
        descriptive_indices = _serial_columns(section) | {
            c.index for c in section.columns if c.role in TEXTUAL_ROLES}
        group = self.groups[-1] if self.groups else None
        for row in section.rows:
            if row.row_type is RowType.SECTION_TITLE:
                # A rule of dashes between blocks is layout, not a group name.
                if _has_text(row.text):
                    group = {"group": row.text.strip(), "rows": []}
                    self.groups.append(group)
                continue
            if row.row_type not in (RowType.DATA, RowType.TOTAL):
                continue
            cells: dict[str, Any] = {}
            for cell in row.cells:
                key = key_by_index.get(cell.column_index)
                if key is None and cell.is_blank:
                    continue
                if key is None:
                    key = self.extra_key(cell.column_index, roles.get(cell.column_index, "unknown"))
                    key_by_index[cell.column_index] = key
                cells[key] = cell
            record: dict[str, Any] = {}
            if row.row_type is RowType.TOTAL:
                label = next((c.raw_text.strip() for c in row.cells
                              if not c.is_blank and not c.is_numeric), None)
                record["label"] = label
            for key in self.keys:
                if key in cells:
                    record[key] = _value(cells[key])
            roles_by_key = {c["key"]: c["role"] for c in self.columns}
            descriptive = frozenset(key_by_index[i] for i in descriptive_indices
                                    if i in key_by_index)
            status, needs, reasons, unchecked_text = _row_status(cells, roles_by_key, descriptive)
            record["page"] = page
            record["status"] = status
            record["needs_review"] = needs
            if unchecked_text:
                record["unchecked_text"] = unchecked_text
            if reasons:
                record["review_reasons"] = reasons
            if row.row_type is RowType.DATA and _is_screen_text(row, roles):
                # Kept, never dropped (coverage), but not among the products.
                record["status"] = CellStatus.FLAGGED.value
                self.other_lines.append(record)
                continue
            if row.row_type is RowType.TOTAL:
                self.totals.append(record)
                continue
            if group is None:
                group = {"group": None, "rows": []}
                self.groups.append(group)
            group["rows"].append(record)
        self.last_section = section
        self.last_keys = dict(key_by_index)

    def to_dict(self) -> dict[str, Any]:
        # A label with nothing under it is not a group - on a photo of a
        # screen, the taskbar's "Desktop" arrives as one.
        groups = [g for g in self.groups if g["rows"]]
        return {"pages": self.pages, "headers": [c["heading"] or c["key"] for c in self.columns],
                "columns": self.columns, "groups": groups, "totals": self.totals,
                "other_lines": self.other_lines}


def _continues(table: "_Table", section) -> bool:
    """Is this section the previous table carried onto another page?

    Three signs, any one enough:

    * **Its roles were inherited.** The mapper only inherits when a page has no
      heading of its own, which is what a continuation page is.
    * **It prints no heading at all.**
    * **It repeats most of the same headings.** `11.pdf` reprints its header
      on page 3, but the item heading picked up a group name
      (`Product Name LAMBENT BETA LARENON` against `Product Name HETERO
      HEALTHCARE LTD`), so an exact comparison split one statement into
      separate tables. A majority of identical headings in the same order, over
      the same number of columns, is the same table.

    Page 2 of `11.pdf` needs the first: the mapper took its address block for a
    header, so it *looks* headed.
    """
    if any(c.method is MappingMethod.INHERITED for c in section.columns):
        return True
    ordered = sorted(section.columns, key=lambda c: c.index)
    headings = [c.header_text.strip() for c in ordered]
    if not any(headings):
        return True
    # The same stock columns in the same order. `GENEX.pdf` repeats its header
    # for every manufacturer block, and one page resolves 15 bands where the
    # others resolve 12, so neither the column count nor the heading text
    # lines up - but opening, receipt, issue and closing, quantity and value,
    # come in the same sequence every time.
    flows = [c.role for c in ordered if c.role in _NUMERIC_ROLES and c.role is not Role.RATE]
    if len(flows) >= 2 and flows == table.flow_roles:
        return True
    if len(headings) != len(table.headings):
        return False
    shared = sum(1 for a, b in zip(headings, table.headings) if a and a == b)
    return shared * 2 > len(headings)


def _align_to(table: _Table, section) -> dict[int, str]:
    """Map a continuation page's columns onto the table it continues, by position.

    Column indices are not stable from page to page - `11.pdf` resolves 7
    columns on page 1 and 8 on page 2 for the same table - so each column is
    matched to the earlier column occupying the same place on the page.
    """
    from pipeline import _column_spans, _matching_column

    spans = _column_spans(section)
    source_spans = _column_spans(table.last_section)
    source_keys = table.last_keys
    mapping: dict[int, str] = {}
    taken: set[str] = set()
    for column in sorted(section.columns, key=lambda c: c.index):
        origin = _matching_column(column.index, spans, source_spans, table.last_section.columns)
        key = source_keys.get(origin.index) if origin is not None else None
        if key and key not in taken:
            mapping[column.index] = key
            taken.add(key)
    return mapping


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


def _first_metadata(documents, name: str) -> Any:
    """A report-level field, taken from the first page only.

    A report prints who it is from and for what period at the top of page 1.
    Looking further let a later page answer instead: with GENEX.pdf's page-1
    value rejected as a rule of dashes, page 6 supplied a product row -
    `HETROBACT 5GM TUBE 1'S ...` - as the company name. Nothing is better
    than that.
    """
    if not documents:
        return None
    field = getattr(documents[0].metadata, name, None)
    if field is not None and _has_text(field.value):
        return field.value.strip()
    return None


def _document_type(title: str | None) -> str | None:
    """Stock, sales, or both - from the report's own heading, never guessed."""
    if not title:
        return None
    lowered = title.lower()
    stock = bool(re.search(r"\b(stock|statement|summary|inventory)\b", lowered))
    sales = bool(re.search(r"\bsales?\b", lowered))
    if stock and sales:
        return "STOCK_AND_SALES_REPORT"
    if stock:
        return "STOCK_REPORT"
    if sales:
        return "SALES_REPORT"
    return None


def build_report(result) -> dict[str, Any]:
    """The structured report for one pipeline result (a whole file)."""
    tables: list[_Table] = []
    documents = []
    pages_info = []
    for position, page in enumerate(result.pages, 1):
        number = page.ref.page_index + 1
        pages_info.append({
            "page": number,
            "read_as": getattr(page.ref.kind, "value", str(page.ref.kind)),
            "healthy": page.healthy,
            "problems": list(page.health.problems) if page.health else ([page.error] if page.error else []),
        })
        if page.document is None:
            continue
        documents.append(page.document)
        for section in page.document.sections:
            if section.kind is not SectionKind.TABULAR or not section.data_rows:
                continue
            previous = tables[-1] if tables else None
            if previous is not None and _continues(previous, section):
                previous.add_rows(section, number, _align_to(previous, section))
                continue
            candidate = _Table(section, number)
            candidate.add_rows(section, number, candidate.key_by_index)
            tables.append(candidate)

    rows = [r for t in tables for g in t.groups for r in g["rows"]]
    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1

    title = None
    if documents:
        field = documents[0].metadata.extra.get("report_title")
        title = field.value.strip() if field is not None and _has_text(field.value) else None
    period_from = _first_metadata(documents, "period_from")
    period_to = _first_metadata(documents, "period_to")
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "document_type": _document_type(title),
        "report_title": title,
        "report_entity": _first_metadata(documents, "distributor_name"),
        "location": _first_metadata(documents, "address"),
        "report_period": ({"from_date": period_from, "to_date": period_to}
                          if period_from or period_to else None),
        "gstin": _first_metadata(documents, "gstin"),
        "source": {"file": result.path.name, "pages": pages_info},
        "tables": [t.to_dict() for t in tables],
        "summary": {
            "tables": len(tables),
            "rows": len(rows),
            "rows_by_status": by_status,
            "rows_needing_review": sum(1 for r in rows if r["needs_review"]),
            "fields_needing_review": sum(len(r["needs_review"]) for r in rows),
            "other_lines": sum(len(t.other_lines) for t in tables),
        },
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path")
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args(argv)

    from pipeline import process_file
    report = build_report(process_file(args.path))
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
