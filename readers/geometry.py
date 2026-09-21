"""Shared table geometry: tokens with coordinates in, a grid out.

Every reader calls this. The Excel reader already knows its cell addresses and
skips the clustering, but PDF text layers and OCR output both arrive as a bag
of positioned tokens and need the same reconstruction:

1. cluster tokens into rows by vertical position
2. find column bands by projecting tokens onto the x axis and locating the
   whitespace gutters between them
3. assign each token to a band and concatenate

Because reconstruction is driven entirely by coordinates, the order in which a
reader hands over its tokens is irrelevant - which is what makes a scrambled
extraction order a non-issue rather than a special case.

Two page-level repairs live here too, since both are artefacts of how a page
was laid out rather than of what it means: wrapped total rows, and two logical
rows printed on one line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median
from typing import Sequence

from .contract import Grid, GridCell, GridRow, Token

__all__ = [
    "GeometryConfig", "cluster_rows", "detect_column_bands", "assign_columns",
    "build_grid", "merge_wrapped_rows", "split_merged_rows", "recover_unbanded_columns",
    "set_aside_oversized", "split_merged_bands", "split_bands_by_headings",
    "straighten_page",
]

# `34.` is the figure 34: several billing packages print whole quantities with
# a trailing point and no decimals (`PAVAN MAY MEHSANA.pdf`, `A+N Apr'26
# Statement.pdf`). Read as prose, a page of them scored 23% numeric and lost its
# table, and no cell carried a value, so no row equation and no column sum could
# run on it at all. A lone `.` is still nil, since digits are required first.
_NUMERIC_RE = re.compile(r"^[(\[]?[+-]?[\d,]+(?:\.\d*)?[)\]]?-?$")
_ALPHA_RE = re.compile(r"[A-Za-z]")


@dataclass
class GeometryConfig:
    #: A token joins a row if its centre is within this many median token
    #: heights of the row's centre.
    line_tolerance: float = 0.60
    #: A whitespace run must be at least this many median token heights wide to
    #: count as a column gutter rather than an inter-word space.
    gutter_ratio: float = 0.55
    #: If the first pass finds fewer bands than this, retry with a narrower
    #: gutter - some reports set their columns very tight.
    min_expected_bands: int = 3
    #: Fractions of the row count to try as the ink floor. The lowest one that
    #: resolves the most columns wins. The first entries ignore spanning title
    #: lines; the later ones cope with right-aligned figures that leave ink in
    #: the gap on some rows.
    coverage_floors: tuple[float, ...] = (0.0, 0.03, 0.08, 0.15, 0.25, 0.35, 0.45)
    #: Sanity cap: beyond this a "column" is really a word boundary.
    max_bands: int = 40
    #: Floor for the retry, to stop a runaway split of every word.
    min_gutter_absolute: float = 1.5
    #: Rows closer together than this many median row heights may be a single
    #: row that wrapped.
    wrap_gap_ratio: float = 1.8
    #: A wrapped fragment occupies no more than this fraction of the bands.
    wrap_sparse_ratio: float = 0.70
    merge_wrapped: bool = True
    split_merged: bool = True
    #: Straighten sloping text lines before clustering rows (photos only).
    straighten_rows: bool = True
    #: Also straighten leaning columns. Off: measured on six photographed pages,
    #: the lean model never explained the column measurements (leftover scatter
    #: 0.9-2.6x the raw scatter), where the row model removed 64-80% of it.
    straighten_columns: bool = False
    #: Straighten leaning columns by searching for the shear that packs each
    #: column into the least width (`_fit_column_shear`), rather than by
    #: fitting word-to-word displacements. On by default: the measurement is
    #: made against the same quantity the band detector uses, so a shear that
    #: scores better here is one the bands can use.
    straighten_column_shear: bool = True
    #: How far down the page a column may be assumed to drift, as a multiple of
    #: median text height. Wider costs only search time.
    shear_search_drift: float = 8.0
    #: Steps per text height in that search.
    shear_search_steps: float = 4.0
    #: The best shear must pack the figure edges at least this much tighter
    #: than leaving the page as photographed, or the page is left alone.
    shear_min_gain: float = 0.10
    #: Figures needed before a lean may be measured from them.
    shear_min_figures: int = 20
    #: Below this much vertical drift across the page, in median token heights,
    #: lines are treated as level and left exactly as read.
    straighten_min_drift: float = 0.35
    #: Figures that fall in no column band are given bands of their own.
    recover_sparse_columns: bool = True
    #: Words taller than this many median token heights are a watermark or a
    #: stamp, not a line of the table.
    oversized_ratio: float = 5.0


# ---------------------------------------------------------------------------
# Row clustering
# ---------------------------------------------------------------------------


def _median_height(tokens: Sequence[Token]) -> float:
    heights = [t.height for t in tokens if t.height > 0]
    return median(heights) if heights else 10.0


def cluster_rows(tokens: Sequence[Token],
                 config: GeometryConfig | None = None) -> list[list[Token]]:
    """Group tokens into visual rows by vertical centre.

    Sorting is by coordinate, never by the order the reader supplied, so a
    scrambled extraction order reconstructs identically.
    """
    config = config or GeometryConfig()
    if not tokens:
        return []

    height = _median_height(tokens)
    tolerance = max(config.line_tolerance * height, 0.5)

    ordered = sorted(tokens, key=lambda t: (t.cy, t.x0))
    rows: list[list[Token]] = []
    current: list[Token] = [ordered[0]]
    centre = ordered[0].cy

    for token in ordered[1:]:
        if abs(token.cy - centre) <= tolerance:
            current.append(token)
            centre = sum(t.cy for t in current) / len(current)
        else:
            rows.append(sorted(current, key=lambda t: t.x0))
            current = [token]
            centre = token.cy

    rows.append(sorted(current, key=lambda t: t.x0))
    return rows


# ---------------------------------------------------------------------------
# Column bands
# ---------------------------------------------------------------------------


def detect_column_bands(rows: Sequence[Sequence[Token]],
                        config: GeometryConfig | None = None
                        ) -> list[tuple[float, float]]:
    """Find column bands from the whitespace gutters between columns.

    The projection counts *how many rows* put ink at each x position, not how
    many tokens. That distinction is what makes this work on a real report: the
    title and address lines at the top of every page span the full width and
    would otherwise bridge every gutter, collapsing the table into a single
    column. A handful of full-width lines cannot outvote sixty table rows.

    A gutter must also be wider than an inter-word space, so the threshold is
    scaled to the text size rather than fixed.
    """
    config = config or GeometryConfig()
    flat = [t for row in rows for t in row]
    if not flat:
        return []

    height = _median_height(flat)
    x_min = min(t.x0 for t in flat)
    x_max = max(t.x1 for t in flat)
    if x_max <= x_min:
        return [(x_min, x_max)]

    step = max((x_max - x_min) / 2000.0, 0.25)
    bins = int((x_max - x_min) / step) + 1
    coverage = [0] * bins

    for row in rows:
        covered: set[int] = set()
        for token in row:
            start = int((token.x0 - x_min) / step)
            end = int((token.x1 - x_min) / step)
            covered.update(range(max(0, start), min(bins - 1, end) + 1))
        for index in covered:
            coverage[index] += 1

    def bands_for(min_gutter: float, floor: float) -> list[tuple[float, float]]:
        """Bands are the runs above ``floor``, split by gaps wide enough to be
        gutters rather than inter-word spaces."""
        min_bins = max(1, int(min_gutter / step))
        found: list[tuple[float, float]] = []
        run_start: int | None = None
        gap = 0
        for index in range(bins):
            if coverage[index] > floor:
                if run_start is None:
                    run_start = index
                gap = 0
            else:
                if run_start is None:
                    continue
                gap += 1
                if gap >= min_bins:
                    found.append((x_min + run_start * step,
                                  x_min + (index - gap + 1) * step))
                    run_start, gap = None, 0
        if run_start is not None:
            found.append((x_min + run_start * step, x_max))
        return found

    gutter = max(config.gutter_ratio * height, config.min_gutter_absolute)

    def cells_formed(bands: list[tuple[float, float]]) -> int:
        """How many distinct (row, band) cells these bands give the page."""
        return sum(len({i for token in row for i, (b0, b1) in enumerate(bands)
                        if min(token.x1, b1) - max(token.x0, b0) > 0})
                   for row in rows)

    def better(candidate: list[tuple[float, float]], best: list[tuple[float, float]]) -> bool:
        """More columns wins; between equally many, the split rows fill more of.

        A tie used to go to whichever floor was tried first. On a phone
        screenshot of a PDF viewer (`all in one.pdf` p4) the app's toolbar -
        `AI Writer | Thumbnails | Convert | All tools` - splits into as many
        bands as the four-column table above it, and under PP-OCRv6 the
        toolbar's split was found first: the table collapsed into one column
        and the page lost its only table. Counting the cells each split forms
        settles it: the toolbar's split gives each table row one or two cells,
        the table's split gives it four.
        """
        if len(candidate) > config.max_bands:
            return False
        if len(candidate) != len(best):
            return len(candidate) > len(best)
        return cells_formed(candidate) > cells_formed(best)

    # Many reports right-align their figures, so a narrow column leaves ink in
    # the gap on some rows and there is no x position that is empty on all of
    # them. Sweeping the floor upward finds those columns; the lowest floor
    # that resolves the most columns wins, so the split stays as conservative
    # as the page allows.
    best: list[tuple[float, float]] = []
    for fraction in config.coverage_floors:
        floor = len(rows) * fraction
        candidate = bands_for(gutter, floor)
        if better(candidate, best):
            best = candidate

    # Still nothing separated? The columns are tighter than an inter-word gap.
    shrinking = gutter
    while len(best) < config.min_expected_bands and shrinking > config.min_gutter_absolute:
        shrinking = max(shrinking * 0.6, config.min_gutter_absolute)
        for fraction in config.coverage_floors:
            candidate = bands_for(shrinking, len(rows) * fraction)
            if len(candidate) > len(best) and len(candidate) <= config.max_bands:
                best = candidate
            elif len(candidate) == len(best) and better(candidate, best):
                best = candidate

    return best or [(x_min, x_max)]


def recover_unbanded_columns(rows: Sequence[Sequence[Token]],
                             bands: list[tuple[float, float]],
                             config: GeometryConfig | None = None
                             ) -> list[tuple[float, float]]:
    """Add the columns band detection missed: figures that sit in no band.

    Gutters are found by how many rows leave a strip empty, so a column most
    rows leave blank is outvoted. On `AAI PHARMA JUNE26.pdf` the last four
    columns - `MAY`, `APR`, `STK120`, `EXP3M` - hold a value on four rows or
    fewer, no band was found for them, and every figure there was put in the
    nearest band: `814 1` under `STK VAL`, marked exact.

    Only *figures* are used, and only from the table's own rows - three or
    more figures, most already inside a band - so address words, headings and
    differently laid-out sub-lines cannot make columns. Gutters among them are
    found the usual way. A new band needs figures on at least two of those
    rows and must sit a full gutter clear of every existing band.
    """
    config = config or GeometryConfig()
    if not bands or not rows:
        return bands

    def overlaps(token: Token, band: tuple[float, float]) -> bool:
        return min(token.x1, band[1]) - max(token.x0, band[0]) > 0

    def is_figure(token: Token) -> bool:
        return bool(_NUMERIC_RE.match(token.text.strip()))

    # Rows of the table itself: three or more figures, most of them already
    # inside a band. An address line, a heading, or a `Batch : ... Value :
    # 2970.00` sub-line laid out differently from the products is not one.
    table_rows = []
    for row in rows:
        figures = [t for t in row if is_figure(t)]
        inside = sum(1 for t in figures if any(overlaps(t, b) for b in bands))
        if len(figures) >= 3 and inside * 2 > len(figures):
            table_rows.append([t for t in figures if not any(overlaps(t, b) for b in bands)])
    orphans = [row for row in table_rows if row]
    if len(orphans) < 2:
        return bands

    height = _median_height([t for row in rows for t in row])
    gutter = max(config.gutter_ratio * height, config.min_gutter_absolute)
    local = GeometryConfig(**{**config.__dict__, "min_expected_bands": 1})
    added: list[tuple[float, float]] = []
    for band in detect_column_bands(orphans, local):
        support = sum(1 for row in orphans if any(overlaps(t, band) for t in row))
        # A full gutter clear of every existing band: a right-aligned digit a
        # few points outside its own column is not a column of its own.
        clear = all(band[0] - b[1] >= gutter or b[0] - band[1] >= gutter for b in bands)
        if support >= 2 and clear:
            added.append(band)
    if not added or len(bands) + len(added) > config.max_bands:
        return bands
    return sorted(bands + added)


def split_merged_bands(rows: Sequence[Sequence[Token]],
                       bands: list[tuple[float, float]],
                       config: GeometryConfig | None = None
                       ) -> list[tuple[float, float]]:
    """Split a band of figures that holds two columns side by side.

    Band detection counts how many rows leave a strip empty, so two sparse
    columns next to each other - most rows blank in one or both - can come out
    as one band. `305313_.pdf` prints 19 headings over 11 or 12 bands, and a
    row put `100 19` into one cell.

    Only figures on the table's own rows are looked at, and only bands where
    figures are nearly everything those rows put there, so an item description
    with numbers in it (`BILASET 20MG`) is never cut. Inside such a band the
    figures must form separate runs a full gutter apart, each reached by at
    least two rows. A compound quantity (`60:0`) is not a plain figure, so a
    band of them is left whole - the band-split tried before broke exactly that.
    """
    config = config or GeometryConfig()
    if not bands or not rows:
        return bands

    def overlaps(token: Token, band: tuple[float, float]) -> bool:
        return min(token.x1, band[1]) - max(token.x0, band[0]) > 0

    def is_figure(token: Token) -> bool:
        return bool(_NUMERIC_RE.match(token.text.strip()))

    table_rows = [row for row in rows if sum(1 for t in row if is_figure(t)) >= 3]
    if len(table_rows) < 3:
        return bands
    height = _median_height([t for row in rows for t in row])
    gutter = max(config.gutter_ratio * height, config.min_gutter_absolute)
    local = GeometryConfig(**{**config.__dict__, "min_expected_bands": 1})

    result: list[tuple[float, float]] = []
    for band in bands:
        inside = [[t for t in row if overlaps(t, band)] for row in table_rows]
        tokens = [t for row in inside for t in row]
        figures = [[t for t in row if is_figure(t)] for row in inside]
        figures = [row for row in figures if row]
        if not tokens or sum(len(r) for r in figures) < 0.9 * len(tokens) or len(figures) < 4:
            result.append(band)
            continue
        parts = detect_column_bands(figures, local)
        supported = [p for p in parts
                     if sum(1 for row in figures if any(overlaps(t, p) for t in row)) >= 2]
        apart = all(b[0] - a[1] >= gutter for a, b in zip(supported, supported[1:]))
        # every figure must fall in one of the parts, or the split drops a value
        placed = all(any(overlaps(t, p) for p in supported) for row in figures for t in row)
        if len(supported) >= 2 and apart and placed:
            result.extend(supported)
        else:
            result.append(band)
    if len(result) > config.max_bands:
        return bands
    return result


def split_bands_by_headings(rows: Sequence[Sequence[Token]],
                            bands: list[tuple[float, float]],
                            config: GeometryConfig | None = None
                            ) -> list[tuple[float, float]]:
    """Split a band whose heading names two columns and whose cells hold two.

    Where a report sets `QTY.` and `VALUE` close together, the figures beneath
    overlap in x - a four-digit value starts left of where a three-digit
    quantity ends - so no whitespace gutter exists on the page and the two come
    out as one cell (`7 1497.41` on `HETROSTOCK05-2026.pdf`, 110 such cells on
    one page). The heading still separates them: two words, each over its own
    figures.

    The band is replaced by the spans of its heading words, and each figure
    then goes to the word it overlaps or, failing that, the nearest one. Only
    bands that *are* merged qualify: at least two rows must put two figures in
    the band.
    """
    config = config or GeometryConfig()
    if not bands or not rows:
        return bands

    def overlaps(token: Token, band: tuple[float, float]) -> bool:
        return min(token.x1, band[1]) - max(token.x0, band[0]) > 0

    def is_figure(token: Token) -> bool:
        return bool(_NUMERIC_RE.match(token.text.strip()))

    height = _median_height([t for row in rows for t in row])
    gutter = max(config.gutter_ratio * height, config.min_gutter_absolute)
    # Headings sit above the figures and carry none themselves.
    first_figure = next((i for i, row in enumerate(rows)
                         if sum(1 for t in row if is_figure(t)) >= 3), None)
    if first_figure is None:
        return bands
    heading_rows = [row for row in rows[:first_figure]
                    if len(row) >= 2 and not any(is_figure(t) for t in row)]
    data_rows = [row for row in rows[first_figure:]
                 if sum(1 for t in row if is_figure(t)) >= 3]
    if not heading_rows or len(data_rows) < 3:
        return bands

    result: list[tuple[float, float]] = []
    for band in bands:
        # One heading line at a time: a tier-1 word (`OPENING`) sits across the
        # tier-2 words (`QTY.`, `VALUE`) it spans, and mixing the lines groups
        # all three into one. The line that names the most columns wins.
        groups: list[list[Token]] = []
        for heading_row in heading_rows:
            words = sorted((t for t in heading_row if overlaps(t, band)), key=lambda t: t.x0)
            line: list[list[Token]] = []
            for word in words:
                if line and word.x0 - line[-1][-1].x1 < gutter:
                    line[-1].append(word)
                else:
                    line.append([word])
            if len(line) > len(groups):
                groups = line
        merged_rows = sum(1 for row in data_rows
                          if sum(1 for t in row if is_figure(t) and overlaps(t, band)) >= 2)
        if len(groups) < 2 or merged_rows < 2:
            result.append(band)
            continue
        spans = [(min(t.x0 for t in g), max(t.x1 for t in g)) for g in groups]
        # Only where the headings are as many as the figures crowded together.
        widest = max(sum(1 for t in row if is_figure(t) and overlaps(t, band))
                     for row in data_rows)
        if len(spans) != widest:
            result.append(band)
            continue
        result.extend(spans)
    if len(result) > config.max_bands or len(result) == len(bands):
        return bands
    return sorted(result)


def set_aside_oversized(tokens: Sequence[Token], ratio: float
                        ) -> tuple[list[Token], list[Token]]:
    """Separate text drawn far larger than the page's lines: a watermark.

    `AAI PHARMA JUNE26.pdf` carries a diagonal `medica` watermark in its text
    layer, one word 475 points tall behind a table of 11-point text. Clustered
    as a row it joined the division total line, exporting `medica` as a
    product description. Only words without digits are set aside, so no figure
    is ever removed from the page.
    """
    if len(tokens) < 10:
        return list(tokens), []
    height = _median_height(tokens)
    kept, aside = [], []
    for token in tokens:
        if token.height > ratio * height and not re.search(r"\d", token.text):
            aside.append(token)
        else:
            kept.append(token)
    return kept, aside


def _band_for(token: Token, bands: Sequence[tuple[float, float]]) -> int:
    """The band a token belongs to: greatest x-overlap, else nearest."""
    best, best_overlap = -1, 0.0
    for i, (b0, b1) in enumerate(bands):
        overlap = min(token.x1, b1) - max(token.x0, b0)
        if overlap > best_overlap:
            best, best_overlap = i, overlap
    if best >= 0:
        return best

    nearest, nearest_distance = 0, float("inf")
    for i, (b0, b1) in enumerate(bands):
        distance = min(abs(token.cx - b0), abs(token.cx - b1))
        if distance < nearest_distance:
            nearest, nearest_distance = i, distance
    return nearest


def assign_columns(rows: Sequence[Sequence[Token]],
                   bands: Sequence[tuple[float, float]]) -> list[GridRow]:
    """Place each row's tokens into column bands."""
    grid_rows: list[GridRow] = []

    for index, row_tokens in enumerate(rows):
        buckets: dict[int, list[Token]] = {}
        for token in row_tokens:
            buckets.setdefault(_band_for(token, bands), []).append(token)

        cells: list[GridCell] = []
        for column in sorted(buckets):
            group = sorted(buckets[column], key=lambda t: t.x0)
            confidences = [t.confidence for t in group if t.confidence is not None]
            cells.append(GridCell(
                text=" ".join(t.text for t in group).strip(),
                column=column,
                bbox=(min(t.x0 for t in group), min(t.y0 for t in group),
                      max(t.x1 for t in group), max(t.y1 for t in group)),
                # A cell is only as trustworthy as its least certain token.
                confidence=min(confidences) if confidences else None,
                token_ids=[t.index for t in group if t.index >= 0],
            ))

        bbox = None
        if row_tokens:
            bbox = (min(t.x0 for t in row_tokens), min(t.y0 for t in row_tokens),
                    max(t.x1 for t in row_tokens), max(t.y1 for t in row_tokens))
        grid_rows.append(GridRow(index=index, cells=cells, bbox=bbox))

    return grid_rows


# ---------------------------------------------------------------------------
# Page-level repairs
# ---------------------------------------------------------------------------


def _occupied(row: GridRow) -> set[int]:
    return {c.column for c in row.cells if c.text.strip()}


def merge_wrapped_rows(rows: list[GridRow], band_count: int,
                       config: GeometryConfig | None = None) -> list[GridRow]:
    """Rejoin a row that the report printed across two lines.

    Amar's Grand Total is the case: ``9609.000 4647.000`` on one line and
    ``3339.000 8301.000`` on the next, each fragment filling a different set of
    columns. Two consecutive rows are rejoined only when they are close
    together, each is sparse, and the columns they occupy are **disjoint** -
    so a genuinely sparse row is never swallowed by its neighbour.
    """
    config = config or GeometryConfig()
    if not config.merge_wrapped or len(rows) < 2 or band_count <= 0:
        return rows

    heights = [r.bbox[3] - r.bbox[1] for r in rows if r.bbox]
    row_height = median(heights) if heights else 10.0
    limit = config.wrap_gap_ratio * row_height
    sparse_limit = max(1, int(band_count * config.wrap_sparse_ratio))

    merged: list[GridRow] = []
    skip = False

    for i, row in enumerate(rows):
        if skip:
            skip = False
            continue
        if i + 1 >= len(rows):
            merged.append(row)
            continue

        nxt = rows[i + 1]
        here, there = _occupied(row), _occupied(nxt)
        if not here or not there:
            merged.append(row)
            continue

        gap = (nxt.bbox[1] - row.bbox[3]) if (row.bbox and nxt.bbox) else limit + 1
        if (here & there or len(here) > sparse_limit or len(there) > sparse_limit
                or gap > limit):
            merged.append(row)
            continue

        combined = GridRow(
            index=row.index,
            cells=sorted(row.cells + nxt.cells, key=lambda c: c.column),
            bbox=(min(row.bbox[0], nxt.bbox[0]), min(row.bbox[1], nxt.bbox[1]),
                  max(row.bbox[2], nxt.bbox[2]), max(row.bbox[3], nxt.bbox[3]))
            if (row.bbox and nxt.bbox) else row.bbox,
            notes=[f"wrapped row: rejoined with the line below "
                   f"(columns {sorted(here)} + {sorted(there)})"],
        )
        merged.append(combined)
        skip = True

    for position, row in enumerate(merged):
        row.index = position
    return merged


def split_merged_rows(rows: list[GridRow], config: GeometryConfig | None = None
                      ) -> list[GridRow]:
    """Separate two logical rows that were printed on one line.

    A description appearing inside a band that is otherwise numeric is the
    signal. The split is only performed where it is unambiguous; anything less
    clear is annotated and left alone, because inventing a row boundary is
    worse than reporting a suspicious one.
    """
    config = config or GeometryConfig()
    if not config.split_merged or not rows:
        return rows

    # Which bands hold numbers, judged across the whole page.
    numeric_bands: dict[int, list[int]] = {}
    for row in rows:
        for cell in row.cells:
            if not cell.text.strip():
                continue
            tally = numeric_bands.setdefault(cell.column, [0, 0])
            tally[1] += 1
            if _NUMERIC_RE.match(cell.text.strip()):
                tally[0] += 1
    mostly_numeric = {band for band, (hits, total) in numeric_bands.items()
                      if total >= 4 and hits / total >= 0.8}

    counts = [len([c for c in r.cells if c.text.strip()]) for r in rows]
    modal = median(counts) if counts else 0

    out: list[GridRow] = []
    for row in rows:
        intruders = [c for c in row.cells
                     if c.column in mostly_numeric and _ALPHA_RE.search(c.text)
                     and not _NUMERIC_RE.match(c.text.strip())]
        populated = len([c for c in row.cells if c.text.strip()])

        if intruders and modal and populated > modal * 1.5:
            boundary = min(c.column for c in intruders)
            first = [c for c in row.cells if c.column < boundary]
            second = [c for c in row.cells if c.column >= boundary]
            # Each half of a genuine merge is a product line with figures of
            # its own. A heading line has none: `... STK VAL MAY APR STK120
            # EXP3M` on `AAI PHARMA JUNE26.pdf` was cut in two once its
            # sparse columns got bands, and the halves read as a two-tier
            # header (`STK VAL MAY`, `STK VAL APR`, ...).
            def has_figure(cells):
                return any(_NUMERIC_RE.match(c.text.strip()) for c in cells)
            if first and second and has_figure(first) and has_figure(second):
                out.append(GridRow(index=row.index, cells=first, bbox=row.bbox,
                                   notes=[f"merged line split at column {boundary}"]))
                # The trailing fragment keeps its own columns; it is not
                # re-mapped onto column 0, because where it truly belongs is
                # Stage A's decision, not geometry's.
                out.append(GridRow(index=row.index, cells=second, bbox=row.bbox,
                                   notes=[f"trailing fragment of a merged line "
                                          f"(from column {boundary})"]))
                continue
        if intruders:
            row.notes.append(
                f"text found in numeric column(s) "
                f"{sorted({c.column for c in intruders})}; row left intact")
        out.append(row)

    for position, row in enumerate(out):
        row.index = position
    return out


# ---------------------------------------------------------------------------
# Whole-page assembly
# ---------------------------------------------------------------------------


def _fit_line_slope(tokens: Sequence[Token], height: float
                    ) -> tuple[float, float, int] | None:
    """How steeply text lines slope, as a function of height on the page.

    Returns ``(a, b, pairs)`` with slope ``dy/dx = a + b * y``, or None when
    there is not enough evidence to say.

    Evidence comes from *neighbouring* words on one line. Across a whole row a
    photographed page can drift further than the gap between rows, so no
    row-level measurement is safe - but two adjacent words are a few hundred
    pixels apart, their drift is a fraction of a line, and a pair from two
    different lines is a full row pitch apart and easily excluded.

    Letting the slope vary with height is what makes it work on a photo of a
    screen taken at an angle. On `1000517655.jpg` the first row rises 25 px
    from left to right while row 21 falls 58 px: a keystone, not a rotation,
    and no single deskew angle straightens both.
    """
    ordered = sorted(tokens, key=lambda t: t.cx)
    samples: list[tuple[float, float]] = []
    for a in ordered:
        best = None
        for b in ordered:
            if b.x0 <= a.cx or b.cx - a.cx <= 0:
                continue
            if b.x0 - a.x1 > 8 * height:
                continue
            if abs(b.cy - a.cy) >= 0.45 * height:
                continue
            if best is None or b.cx < best.cx:
                best = b
        if best is not None:
            samples.append(((a.cy + best.cy) / 2.0,
                            (best.cy - a.cy) / (best.cx - a.cx)))
    if len(samples) < 20:
        return None

    def fit(points):
        n = len(points)
        my = sum(y for y, _ in points) / n
        ms = sum(sl for _, sl in points) / n
        var = sum((y - my) ** 2 for y, _ in points)
        b = sum((y - my) * (sl - ms) for y, sl in points) / var if var else 0.0
        return ms - b * my, b

    a, b = fit(samples)
    residuals = sorted(abs(sl - (a + b * y)) for y, sl in samples)
    mad = residuals[len(residuals) // 2] or 1e-9
    kept = [(y, sl) for y, sl in samples if abs(sl - (a + b * y)) <= 3.0 * mad + 1e-6]
    if len(kept) < 20:
        return None
    a, b = fit(kept)
    return a, b, len(kept)


def _fit_column_lean(tokens: Sequence[Token], height: float
                     ) -> tuple[float, float, int] | None:
    """How far columns lean sideways as they run down the page.

    Returns ``(c, d, pairs)`` with lean ``dx/dy = c + d * x``, or None.

    The same keystone that makes rows slope makes columns lean: photographed
    at an angle, a column's position drifts as it goes down the page, and by
    different amounts on the left and right of the page. On `1000517655.jpg`
    that put the `PACK` and `OB` headings one band to the left of their own
    figures and closed the gutter between `RATE` and `VALUE`, so two columns
    projected as one.

    Evidence comes from a word and the word directly beneath it. Figures are
    right-aligned and text left-aligned, so of the two edges the one that moved
    less is the aligned edge, and that is the one measured.
    """
    ordered = sorted(tokens, key=lambda t: t.cy)
    samples: list[tuple[float, float]] = []
    for position, a in enumerate(ordered):
        below = None
        for b in ordered[position + 1:]:
            if b.cy - a.cy <= 0.5 * height:
                continue
            if b.y0 - a.y1 > 2.5 * height:
                break
            if min(a.x1, b.x1) - max(a.x0, b.x0) <= 0:
                continue
            below = b
            break
        if below is None:
            continue
        shifts = (below.x0 - a.x0, below.x1 - a.x1)
        dx = min(shifts, key=abs)
        dy = below.cy - a.cy
        samples.append(((a.cx + below.cx) / 2.0, dx / dy))
    if len(samples) < 20:
        return None

    def fit(points):
        n = len(points)
        mx = sum(x for x, _ in points) / n
        ml = sum(v for _, v in points) / n
        var = sum((x - mx) ** 2 for x, _ in points)
        d = sum((x - mx) * (v - ml) for x, v in points) / var if var else 0.0
        return ml - d * mx, d

    c, d = fit(samples)
    residuals = sorted(abs(v - (c + d * x)) for x, v in samples)
    mad = residuals[len(residuals) // 2] or 1e-9
    kept = [(x, v) for x, v in samples if abs(v - (c + d * x)) <= 3.0 * mad + 1e-6]
    if len(kept) < 20:
        return None
    c, d = fit(kept)
    return c, d, len(kept)


def _edge_spread(figures: Sequence[Token], shear: float, y_ref: float,
                 bin_size: float) -> int:
    """How far the right edges of a page's figures are spread across the x axis.

    Counted in bins that any figure's right edge falls in, once every figure has
    been slid sideways by ``shear`` per unit of height. Figures are printed
    right-aligned, so a column of them stacks its right edges on one x; a column
    that leans smears them across many. The shear that gathers them into the
    fewest bins is the one that stands the columns upright.

    Whole words were tried here first and measured doing harm: a page's words
    differ in length and indentation, so sliding them makes them overlap for
    reasons that have nothing to do with columns, and the search reported 105 px
    of lean on a flatbed scan and 268 px on a photo that two other measures put
    at zero. Figures are uniform and aligned, and say it cleanly.

    A shear moves every token on a line by the same amount, so two columns keep
    their distance *within a row*. They do not keep it in the page-wide
    projection the band detector works from, because tokens at different heights
    move by different amounts - so a shear can close a gutter after all, and on
    two photographed pages it closed the only one the table had. Nothing in this
    measure can see that; the caller checks it (`_grid_cells`).
    """
    covered = set()
    for token in figures:
        covered.add(int((token.x1 - shear * (token.cy - y_ref)) // bin_size))
    return len(covered)


def _grid_cells(tokens: Sequence[Token], config: GeometryConfig) -> int:
    """How many distinct (row, band) cells this page's tokens resolve into.

    The same count `detect_column_bands` uses to settle a tie between two
    splits, applied here to settle whether straightening the page helped it.
    """
    rows = cluster_rows(tokens, config)
    bands = detect_column_bands(rows, config)
    if not bands:
        return 0
    return sum(len({i for token in row for i, (b0, b1) in enumerate(bands)
                    if min(token.x1, b1) - max(token.x0, b0) > 0})
               for row in rows)


def _fit_column_shear(tokens: Sequence[Token], height: float,
                      config: GeometryConfig) -> tuple[float, float] | None:
    """Search for the shear that packs the page's columns into the least width.

    Returns ``(shear, drift in pixels down the page)``, or None when the page
    is upright already or the gain is too small to act on.

    This replaces fitting the displacement between a word and the word beneath
    it (`_fit_column_lean`). That fit was measured on six photographed pages
    and never explained its own measurements - right-aligned figures of
    different widths move both edges, so the aligned edge cannot be identified
    word by word. A whole column's worth of words says it clearly.
    """
    if len(tokens) < 20:
        return None
    figures = [t for t in tokens if _NUMERIC_RE.match(t.text.strip())]
    if len(figures) < config.shear_min_figures:
        return None
    ys = [t.cy for t in figures]
    y_ref = min(ys)
    depth = max(ys) - y_ref
    if depth < 4 * height:
        return None

    bin_size = max(1.0, 0.25 * height)
    limit = config.shear_search_drift * height / depth
    step = height / (config.shear_search_steps * depth)
    candidates = []
    shear = -limit
    while shear <= limit + 1e-12:
        candidates.append(shear)
        shear += step

    upright = _edge_spread(figures, 0.0, y_ref, bin_size)
    best = min(candidates, key=lambda c: (_edge_spread(figures, c, y_ref, bin_size), abs(c)))
    width = _edge_spread(figures, best, y_ref, bin_size)
    if upright and (upright - width) / upright < config.shear_min_gain:
        return None
    drift = abs(best) * depth
    if drift < config.straighten_min_drift * height:
        return None
    return best, drift


def straighten_page(tokens: Sequence[Token], config: GeometryConfig | None = None
                    ) -> tuple[list[Token], list[str]] | None:
    """Level a photographed page: rows made horizontal, columns made vertical.

    Returns ``(levelled copies, notes)``, or None when the page is already level
    enough to leave exactly as read. Rows are levelled first, since column lean
    is measured most cleanly between rows that are already level.

    The copies are only for working out structure. ``build_grid`` restores every
    cell's original coordinates afterwards, so no position that reaches a cell
    is ever an adjusted one and click-to-locate still lands on the page as it
    was photographed (CLAUDE.md s4.5).
    """
    config = config or GeometryConfig()
    if len(tokens) < 20:
        return None
    height = _median_height(tokens)
    notes: list[str] = []
    work = list(tokens)

    slope = _fit_line_slope(work, height)
    if slope is not None:
        a, b, _ = slope
        x_ref = min(t.x0 for t in work)
        width = max(t.x1 for t in work) - x_ref
        ys = [t.cy for t in work]
        drift = max(abs(a + b * y) for y in (min(ys), max(ys))) * width
        if drift >= config.straighten_min_drift * height:
            levelled = []
            for t in work:
                shift = (a + b * t.cy) * (t.cx - x_ref)
                levelled.append(Token(text=t.text, x0=t.x0, y0=t.y0 - shift, x1=t.x1,
                                      y1=t.y1 - shift, confidence=t.confidence,
                                      index=t.index))
            work = levelled
            notes.append(f"levelled sloping rows (up to {drift:.0f} px of drift across the page)")

    if config.straighten_column_shear:
        found = _fit_column_shear(work, height, config)
        if found is not None:
            shear, drift = found
            y_ref = min(t.cy for t in work)
            upright = [Token(text=t.text, x0=t.x0 - shear * (t.cy - y_ref), y0=t.y0,
                             x1=t.x1 - shear * (t.cy - y_ref), y1=t.y1,
                             confidence=t.confidence, index=t.index)
                       for t in work]
            # Tighter figure columns are the *evidence* for a lean; the page's
            # table is what actually has to come out better. On two photographed
            # pages a 14 px correction cost the page its table altogether, so
            # the straightened page has to resolve into at least as many cells
            # as the page as photographed, or it is not adopted.
            if _grid_cells(upright, config) >= _grid_cells(work, config):
                work = upright
                notes.append(f"stood leaning columns upright ({drift:.0f} px of "
                             "drift down the page)")

    lean = _fit_column_lean(work, height) if config.straighten_columns else None
    if lean is not None:
        c, d, _ = lean
        y_ref = min(t.cy for t in work)
        depth = max(t.cy for t in work) - y_ref
        xs = [t.cx for t in work]
        drift = max(abs(c + d * x) for x in (min(xs), max(xs))) * depth
        if drift >= config.straighten_min_drift * height:
            levelled = []
            for t in work:
                shift = (c + d * t.cx) * (t.cy - y_ref)
                levelled.append(Token(text=t.text, x0=t.x0 - shift, y0=t.y0,
                                      x1=t.x1 - shift, y1=t.y1, confidence=t.confidence,
                                      index=t.index))
            work = levelled
            notes.append(f"straightened leaning columns (up to {drift:.0f} px of drift down the page)")

    return (work, notes) if notes else None


def _restore_positions(rows: list[GridRow], originals: dict[int, Token]) -> list[GridRow]:
    """Give every cell and row the coordinates it has on the page as read."""
    for row in rows:
        boxes = []
        for cell in row.cells:
            source = [originals[i] for i in cell.token_ids if i in originals]
            if source:
                cell.bbox = (min(t.x0 for t in source), min(t.y0 for t in source),
                             max(t.x1 for t in source), max(t.y1 for t in source))
            if cell.bbox is not None:
                boxes.append(cell.bbox)
        if boxes:
            row.bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                        max(b[2] for b in boxes), max(b[3] for b in boxes))
    return rows


def build_grid(tokens: Sequence[Token], page: int, source: str, origin: str = "",
               page_label: str = "", config: GeometryConfig | None = None) -> Grid:
    """Tokens with coordinates in, a complete :class:`Grid` out."""
    config = config or GeometryConfig()
    for position, token in enumerate(tokens):
        if token.index < 0:
            token.index = position

    notes: list[str] = []
    straight = None
    # Only a photograph or scan can slope or lean. A text layer and a
    # spreadsheet place their text exactly, and are never adjusted.
    if source == "ocr" and config.straighten_rows:
        straight = straighten_page(tokens, config)
    work: Sequence[Token] = tokens
    if straight is not None:
        work, straight_notes = straight
        notes.extend(straight_notes)

    work, aside = set_aside_oversized(work, config.oversized_ratio)
    if aside:
        notes.append(f"set aside {len(aside)} oversized word(s) as a watermark or stamp: "
                     + ", ".join(repr(t.text) for t in aside[:5]))

    clustered = cluster_rows(work, config)
    bands = detect_column_bands(clustered, config)
    if config.recover_sparse_columns:
        found = len(bands)
        bands = recover_unbanded_columns(clustered, bands, config)
        if len(bands) != found:
            notes.append(f"found {len(bands) - found} sparse column(s) that most rows leave blank")
        found = len(bands)
        bands = split_merged_bands(clustered, bands, config)
        if len(bands) != found:
            notes.append(f"split {len(bands) - found} band(s) holding two columns of figures")
        found = len(bands)
        bands = split_bands_by_headings(clustered, bands, config)
        if len(bands) != found:
            notes.append(f"split {len(bands) - found} band(s) whose heading names "
                         "two columns")
    rows = assign_columns(clustered, bands)

    before = len(rows)
    rows = merge_wrapped_rows(rows, len(bands), config)
    if len(rows) != before:
        notes.append(f"rejoined {before - len(rows)} wrapped row(s)")

    before = len(rows)
    rows = split_merged_rows(rows, config)
    if len(rows) != before:
        notes.append(f"split {len(rows) - before} merged line(s)")

    if straight is not None:
        rows = _restore_positions(rows, {t.index: t for t in tokens})

    return Grid(page=page, source=source, rows=rows, tokens=list(tokens),
                origin=origin, page_label=page_label, notes=notes,
                column_bands=list(bands))
