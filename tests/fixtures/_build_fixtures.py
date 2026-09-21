"""Build the grid fixtures used by the test suite.

Each fixture is transcribed by hand from the corresponding source document so
that the tests run against real layouts rather than invented ones. Keeping the
transcription here, in compact row form, makes it auditable against the
original; the emitted JSON is what ``ocr_to_table.py`` would hand to Stage A.

Run::

    python tests/fixtures/_build_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Any cell whose text is one of these is nil in the source document.
NIL = "-"


def cell(text: str, column: int | None = None, bbox=None, confidence=None):
    payload: dict = {"text": text}
    if column is not None:
        payload["column"] = column
    if bbox is not None:
        payload["bbox"] = list(bbox)
    if confidence is not None:
        payload["confidence"] = confidence
    return payload


def numeric_tokens(rows: list[list[str]]) -> list[dict]:
    """Every numeric string in the grid, as OCR would have emitted it.

    The coverage check compares this multiset against what reached the output,
    so it must be built from the same source text.
    """
    from decimal import Decimal, InvalidOperation

    tokens = []
    for row in rows:
        for text in row:
            value = text.strip()
            if not value or value == NIL:
                continue
            try:
                Decimal(value.replace(",", ""))
            except (InvalidOperation, ValueError):
                continue
            tokens.append({"text": value, "confidence": 0.97})
    return tokens


# ---------------------------------------------------------------------------
# Amar Pharmaceuticals - single-tier header, bare Opening/In/Out/Balance
# Columns: Description, Code, Opening, In, Out, Balance, Unit, Rate, Value
# ---------------------------------------------------------------------------

AMAR_HEADER = ["Description", "Code", "Opening", "In", "Out", "Balance",
               "Unit", "Rate", "Value"]

AMAR_ROWS = [
    ["AD 10 SACHETS", "", "10.00", "50.000", "10.000", "50.000", "1 GM", "9.26", "463.00"],
    ["AD 100 CAP", "", "9.00", "30.000", "9.000", "30.000", "1*10", "87.77", "2633.10"],
    ["BILASTERO 20 TAB", "", "53.00", NIL, NIL, "53.000", "1*10", "44.84", "2376.41"],
    ["BILASTERO M TAB", "", "65.00", NIL, NIL, "65.000", "1*10", "85.98", "5588.51"],
    ["C FURO 250 TAB", "", "53.00", NIL, "42.000", "11.000", "1*10", "127.43", "1401.68"],
    ["C FURO 500TAB", "", "122.00", "3.000", "5.000", "120.000", "1*10", "238.08", "28569.96"],
    ["C FURO CV 625 TAB", "", "25.00", "10.000", "25.000", "10.000", "1*6", "204.77", "2047.68"],
    ["C FURO DRY SYP", "", "92.00", "6.000", "30.000", "68.000", "30ML", "96.12", "6535.96"],
    ["CARITERO TAB", "", "11.00", NIL, "2.000", "9.000", "1*15", "212.57", "1913.12"],
    ["DA SUTRA 30X TAB", "", "49.00", NIL, "25.000", "24.000", "1*4", "33.94", "814.61"],
    ["ECO ALL GOLD CAP", "", "77.00", "124.000", "58.000", "143.000", "1*10", "99.08", "14168.87"],
    ["Eco All Liquid", "", "1431.00", NIL, "845.000", "586.000", "5ML", "18.72", "10971.68"],
    ["FAROCE 200 TAB", "", NIL, "40.000", NIL, "40.000", "1*10", "369.43", "14777.20"],
    ["FEXONA TAB", "", "20.00", NIL, "10.000", "10.000", "1*10", "79.79", "797.94"],
    # In=1, Out=1, Balance blank: the blank has to read as zero for this to work.
    ["FORSLEEP ORAL SPRAY", "", NIL, "1.000", "1.000", NIL, "15G", "133.39", NIL],
    ["HETCLARI 250 TAB", "", "15.00", "130.000", NIL, "145.000", "1*10", "105.56", "15305.48"],
    ["ITBOR 100 CAP", "", NIL, "74.000", "14.000", "60.000", "1*10", "42.81", "2568.42"],
    ["LYCEFT 1 GM INJ", "", "263.00", NIL, "200.000", "63.000", "1GM", "18.36", "1156.93"],
    # Truncated unit strings must survive verbatim.
    ["MIKATERO INJ", "", "800.00", "800.000", "800.000", "800.000", "500MG.", "20.43", "16344.00"],
    ["NERVOK HP INJ", "", "105.00", NIL, "105.000", NIL, "2ML", "12.98", NIL],
    ["ONDATERO INJ 2MG/2ML INJ", "", "1243.00", "1000.000", "750.000", "1493.000",
     "2MG/2I", "1.92", "2865.07"],
    ["ONDATERO MD 4 TAB", "", "40.00", "130.000", "39.000", "131.000", "1*10", "28.91", "3786.95"],
    ["OPOX 100 DT TAB", "", NIL, "2.000", "2.000", NIL, "1*10", "94.50", NIL],
    ["PANTIN 40 TAB", "", "25.00", NIL, "9.000", "16.000", "1*15", "47.58", "761.22"],
]

AMAR_PREAMBLE = [
    ["AMAR PHARMACEUTICALS"],
    ["SHOP NO.7,KAPOOR MARKET,KUCHA DAI KHANA"],
    ["KATRA SHER SINGH-AMRITSAR"],
    ["From : 01/Aug/2026 To 31/Aug/2026"],
    ["STOCK SUMMARY"],
]


def build_amar() -> dict:
    rows = [{"index": i, "cells": r} for i, r in enumerate(AMAR_PREAMBLE)]
    offset = len(rows)
    rows.append({"index": offset, "cells": AMAR_HEADER})
    for i, r in enumerate(AMAR_ROWS):
        rows.append({"index": offset + 1 + i, "cells": r})
    return {"page": 1, "source": "pdf_text", "rows": rows,
            "tokens": numeric_tokens(AMAR_ROWS)}


def build_amar_grand_total() -> dict:
    """Header, two data rows, and the document's real printed Grand Total.

    The visible rows cannot reproduce a grand total drawn from the whole
    report, which is exactly the situation when only part of a document has
    been processed. The total row's own arithmetic still has to verify.
    """
    body = AMAR_ROWS[:2]
    grand = ["Grand Total :", "", "9609.000", "3339.000", "4647.000", "8301.000",
             "", "", "324115.760"]
    rows = [{"index": 0, "cells": AMAR_HEADER}]
    for i, r in enumerate(body):
        rows.append({"index": 1 + i, "cells": r})
    rows.append({"index": 1 + len(body), "cells": grand})
    return {"page": 1, "source": "pdf_text", "rows": rows}


# ---------------------------------------------------------------------------
# Bansal Medical Agencies - two-tier header, QTY/VALUE under each flow
# ---------------------------------------------------------------------------

BANDS = {
    0: (40, 200), 1: (210, 280), 2: (300, 350), 3: (360, 430), 4: (450, 500),
    5: (510, 580), 6: (600, 650), 7: (660, 730), 8: (750, 800), 9: (810, 880),
    10: (900, 950),
}
BANSAL_PARENT = [(0, "ITEM DESCRIPTION", (40, 200)), (2, "OPENING", (300, 430)),
                 (4, "RECEIPT", (450, 580)), (6, "ISSUE", (600, 730)),
                 (8, "CLOSING", (750, 880)), (10, "DUMP", (900, 950))]
BANSAL_CHILD = [(2, "QTY."), (3, "VALUE"), (4, "QTY."), (5, "VALUE"), (6, "QTY."),
                (7, "VALUE"), (8, "QTY."), (9, "VALUE"), (10, "QTY.")]

Z = NIL  # nil quantity
ZV = "0.00"  # the report prints zero values explicitly

# item, pack, o_qty, o_val, r_qty, r_val, i_qty, i_val, c_qty, c_val, dump
BANSAL_P1_ROWS = [
    ["BALOTERO 100MG TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["BILASET 20 TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["BILASET M TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["BIXIVA TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["DIRAB-10 TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["DIRAB-D CAP", "1X10", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["ENUFF 10 1GM", "1X1SAC", "95", "960.45", "100", "1011.00", "160", "1710.00", "35", "353.85", Z],
    ["ENUFF 100MG CAP", "1X10CAP", "19", "2106.15", "20", "2217.00", "20", "2235.35", "19", "2106.15", "9"],
    ["ENUFF 15 1.5GM", "1XSAC.", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["ENUFF 30 3GM", "1X1SAC", "50", "576.00", "100", "1152.00", "80", "977.36", "70", "806.40", "30"],
    ["ENUFF XTRA 1GM", "1X1SAC", "100", "2041.00", Z, ZV, Z, ZV, "100", "2041.00", "100"],
    ["ENUFF-10DT TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["ENUFF-30DT TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["ENUFF-O SUP", "1X30ML", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["ETORO 90MG SOFTGEL", "1X10CAP", "22", "1866.92", Z, ZV, Z, ZV, "22", "1866.92", "22"],
    ["ETORO-TH SOFTGELS", "1X10CAP", "-1", "-109.29", Z, ZV, Z, ZV, "-1", "-109.29", Z],
    ["FAS 3 KIT TAB", "1X4TAB", "16", "1743.04", Z, ZV, "1", "103.48", "15", "1634.10", "15"],
    ["FIXAR TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["FLUVIR 75MG TAB", "1XTAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["FLUVIR SUP", "1X75ML", "36", "13188.24", Z, ZV, "4", "1547.13", "32", "11722.88", "32"],
    ["HERAFT SUP", "1X150ML", "91", "8190.00", Z, ZV, Z, ZV, "91", "8190.00", "91"],
    ["HETPARIN 40MG INJ", "1X1ML", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["HETPARIN 60MG INJ", "1X1ML", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["HETRAN 10MG TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["HETRAN 20MG TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["HIFEN 100 DRY SUP", "1X30ML", "1", "51.27", Z, ZV, Z, ZV, "1", "51.27", "1"],
    ["HIFEN 100 DT TAB", "1X10TAB", "27", "1203.93", "30", "1203.93", "40", "1679.56", "17", "758.03", "7"],
    ["HIFEN 200 DT TAB", "1X10TAB", "90", "6759.90", Z, ZV, "20", "1255.82", "70", "5257.70", "40"],
    ["HIFEN 50 DRY SUP", "1X30ML", "6", "209.28", Z, ZV, Z, ZV, "6", "209.28", "6"],
    ["HIFEN 50 DT TAB", "1X10TAB", "50", "1573.50", Z, ZV, "31", "927.67", "19", "597.93", "19"],
    ["HIFEN AZ 250MG TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["HIFEN LX 200 TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["HIFEN PLUS 100MG TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["HIFEN PLUS 200MG TAB", "1X10TAB", "31", "2928.26", "50", "3778.40", "43", "3484.88", "38", "3589.48", "1"],
    ["HIFEN-50 REDIMIX SUP", "1X30ML", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["IMIDIL C VAG SUPP.", "1X3CAP", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["IMIDIL CREAM", "1X15GM", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["KUTUB 30X TAB", "1X4TAB", "90", "12725.10", Z, ZV, "20", "596.98", "70", "9897.30", "70"],
    # Negative closing quantity - real data, must not be rejected.
    ["LANOL ER TAB", "1X10TA", "136", "1995.12", "400", "5281.20", "600", "8370.96", "-64", "-938.88", Z],
    ["LEVOCET 10 TAB", "1X15TAB", "26", "1755.00", Z, ZV, Z, ZV, "26", "1755.00", "26"],
    ["LEVOCET 5 TAB", "1X10TA", "26", "943.02", "65", "1813.50", "14", "535.98", "77", "2792.79", "13"],
    ["LEVOCET 60ML SUP", "1X60ML", "-6", "-389.40", Z, ZV, "3", "203.35", "-9", "-584.10", Z],
    ["LEVOCET M KID TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["LEVOCET M TAB", "1X10TAB", "71", "5452.80", Z, ZV, "9", "730.43", "62", "4761.60", "5"],
    ["LEVOCET SUP", "1X30ML", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["LEVOCET-M SUP", "1X60ML", "28", "2178.12", Z, ZV, Z, ZV, "28", "2178.12", "28"],
    ["LINOWIN-300ML INJ", "1X300ML", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["LINOWIN-600MG TAB", "1X10TAB", "29", "7438.50", Z, ZV, Z, ZV, "29", "7438.50", "29"],
    ["LORNOXI 8MG INJ", "1XVAIL", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["LULIBOR CREAM 15MG", "1X15MG", "1", "80.36", Z, ZV, Z, ZV, "1", "80.36", "1"],
    ["MENTHOPAS PATCH", "1XPATCH", "3", "190.92", Z, ZV, Z, ZV, "3", "190.92", "3"],
    ["MOISTE CREAM 100ML", "1X100ML", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["MOVFOR 200 CAP", "1X40CAP", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["MPOX-CV KT DT", "1X6TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["MPX CV 1GM TAB", "1X10TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["MPX CV 625 TAB", "1X10TAB", "3", "359.37", "65", "5989.50", Z, ZV, "68", "8145.72", "3"],
    ["MPX CV FORTE SUP", "1X30ML", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["MPX-CV 375 TAB", "1X6TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["MPX-CV 625 TAB", "1X6TAB", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["MPX-CV KT TAB", "1X6TAB", "20", "565.80", Z, ZV, Z, ZV, "20", "565.80", "20"],
    ["RABETERO-L CAP", "1X10CAP", "6", "589.98", "65", "4916.50", "19", "1785.80", "52", "5113.16", "3"],
    ["RABETERO-L CAP", "1X15CAP", Z, ZV, Z, ZV, Z, ZV, Z, ZV, Z],
    ["SANITIZER-5 LTR", "1X500LT", "-1", "-450.00", Z, ZV, Z, ZV, "-1", "-450.00", Z],
    ["VETORY-D TAB", "1X10TAB", "17", "1204.96", Z, ZV, Z, ZV, "17", "1204.96", "17"],
]

BANSAL_P1_TOTAL = ["TOTAL", "", "1082", "77928.30", "895", "27363.03", "1064",
                   "26144.75", "913", "81226.95", "0"]

BANSAL_P2_ROWS = [
    ["VETORY-P TAB", "1X10TAB", "65", "1689.35", Z, ZV, "15", "372.98", "50", "1299.50", "50"],
    ["VETORY-SP TAB", "1X10TAB", "189", "8864.10", Z, ZV, "52", "1903.49", "137", "6425.30", "49"],
]
# Cumulative: 1082 carried from page 1, plus 65 + 189 from this page.
BANSAL_P2_TOTAL = ["TOTAL", "", "1336", "88481.75", "895", "27363.03", "1131",
                   "28421.22", "1100", "88951.75", "0"]

BANSAL_PREAMBLE = [
    ["BANSAL MEDICAL AGENCIES"],
    ["59/70, LEADER ROAD PRAYAGRAJ"],
    ["Phone : 9415639508,9005357778"],
    ["GSTIN : 09AAMPA4057B1Z2 TIN. No. : 09613201519 FOOD.Lic.No. : 22724597000205"],
    ["STOCK & SALES ANALYSIS (HETERO HEALTHCARE LTD.) 01/08/2026 - 31/08/2026"],
]


def _bansal_rows(data_rows, total_row, preamble, page):
    rows: list[dict] = []
    index = 0
    for line in preamble:
        rows.append({"index": index, "cells": line})
        index += 1

    rows.append({"index": index, "cells": [
        cell(text, column=col, bbox=(x0, 10 * page, x1, 10 * page + 8))
        for col, text, (x0, x1) in BANSAL_PARENT]})
    index += 1
    rows.append({"index": index, "cells": [
        cell(text, column=col, bbox=(BANDS[col][0], 10 * page + 10,
                                     BANDS[col][1], 10 * page + 18))
        for col, text in BANSAL_CHILD]})
    index += 1

    rows.append({"index": index, "cells": ["HETERO HEALTHCARE LTD."]})
    index += 1

    for record in data_rows:
        rows.append({"index": index, "cells": [
            cell(text, column=col,
                 bbox=(BANDS[col][0], 20 * index, BANDS[col][1], 20 * index + 12))
            for col, text in enumerate(record)]})
        index += 1

    rows.append({"index": index, "cells": [
        cell(text, column=col,
             bbox=(BANDS[col][0], 20 * index, BANDS[col][1], 20 * index + 12))
        for col, text in enumerate(total_row)]})
    return rows


def build_bansal_p1() -> dict:
    return {"page": 1, "source": "pdf_text",
            "rows": _bansal_rows(BANSAL_P1_ROWS, BANSAL_P1_TOTAL, BANSAL_PREAMBLE, 1),
            "tokens": numeric_tokens(BANSAL_P1_ROWS + [BANSAL_P1_TOTAL])}


def build_bansal_p2() -> dict:
    preamble = [["BANSAL MEDICAL AGENCIES"], ["Page No..2"],
                ["HETERO HEALTHCARE LTD."],
                ["STOCK & SALES ANALYSIS (HETERO HEALTHCARE LTD.)"]]
    return {"page": 2, "source": "pdf_text",
            "rows": _bansal_rows(BANSAL_P2_ROWS, BANSAL_P2_TOTAL, preamble, 2),
            "tokens": numeric_tokens(BANSAL_P2_ROWS + [BANSAL_P2_TOTAL])}


# ---------------------------------------------------------------------------
# Khushi Healthcare - section titles, and two headers with no data beneath
# ---------------------------------------------------------------------------

KHUSHI_HEADER = ["Particulars", "Pkg.", "Open. Qty.", "Purch. Qty.", "Sales Ret.",
                 "Sales & DC", "Misc. Out", "Close Stock", "Closing Value", "Sales Value"]


def build_khushi() -> dict:
    rows: list[dict] = []
    index = 0

    for line in [["KHUSHI HEALTHCARE"],
                 ["P. N. 33 AND 34, BANSIDHAR NAGAR,CANOL ROAD, BEED"],
                 ["Stock and sales Statement from : 01/04/2026 to 05/09/2026"],
                 ["Company : HETRO HEALTHCARE LTD   Report type All Item Report   Page : 1"]]:
        rows.append({"index": index, "cells": line})
        index += 1

    rows.append({"index": index, "cells": KHUSHI_HEADER})
    index += 1
    for line in [["SYP"],
                 ["HERAFT 150ML", "1", NIL, "140", NIL, "140", NIL, NIL, NIL, "14000.00"],
                 ["TABLETS"],
                 ["TEDITRATE 200 MG TAB", "6S", NIL, "20", NIL, "20", NIL, NIL, NIL, "13333.40"],
                 ["Grand Total.", "", "", "", "", "", "", "", "0.00", "27333.40"]]:
        rows.append({"index": index, "cells": line})
        index += 1

    # A header with nothing under it. The mapper must return an empty section
    # rather than inventing rows.
    rows.append({"index": index, "cells": ["List of Items with expiry between 05/09/2026 and 03/01/2027"]})
    index += 1
    rows.append({"index": index, "cells": ["Product", "Pkg", "BATCHNO", "EXPIRY", "Stock"]})
    index += 1
    rows.append({"index": index, "cells": ["Bill No", "Bill Date", "Gross Amount", "Net Amount"]})
    return {"page": 1, "source": "pdf_text", "rows": rows}


# ---------------------------------------------------------------------------
# Krishna Pharma - phone photo. Pen circles over the closing column, and a
# printed TOTAL that is a value figure, not any column's sum.
# ---------------------------------------------------------------------------

# item, pack, opening, receipt, issue, closing, closing confidence
KRISHNA_ROWS = [
    ["HETERO KRIS PLUS", "1X10", "64", NIL, NIL, "64", 0.96],
    ["BILASTERO M TABS", "1X10", "131", NIL, NIL, "131", 0.95],
    ["HETCLARI 125MG DRY SYRUP", "30ML", "40", NIL, NIL, "40", 0.94],
    ["HETCLARI 250MG TABLET", "1X10", "1", NIL, NIL, "1", 0.93],
    ["HETCLARI 500MG TAB", "1X10", "490", NIL, NIL, "490", 0.41],   # pen circle
    ["LYCEPT PLUS 1.5 GM INJ", "1X10", "188", NIL, NIL, "188", 0.36],  # pen circle
    ["NERVOK CLD", "2ML", "5", NIL, NIL, "5", 0.44],                # pen circle
    ["OFFICE CZ TAB", "1X10", "3", NIL, NIL, "3", 0.52],            # pen circle
    ["ONDATERO MD 4MG TABLET", "1X10", "52", NIL, NIL, "52", 0.91],
    ["ULFREE 1XGM TUBE MLISS", "30ML", "2", NIL, NIL, "2", 0.9],
    ["X-TIV CAPS", "1X10", "94", NIL, NIL, "94", 0.49],             # pen circle
    ["X-TIV SRYP", "200ML", "125", NIL, NIL, "125", 0.92],
    ["MENVOK CAP", "1X10", "108", NIL, NIL, "108", 0.9],
]


def build_krishna() -> dict:
    rows: list[dict] = []
    index = 0
    for line in [["KRISHNA PHARMA"],
                 ["AUD-H,C.C.RANI BAZAR GONDA-271002"],
                 ["Phone : 9554589902,9707364722 E-Mail : krishnapharmacc@gmail.com"],
                 ["GSTIN : 09AAKHR3684K1ZE"],
                 ["STOCK & SALES ANALYSIS (HETERO KRIS PLUS) 01-08-2026 - 26-08-2026"]]:
        rows.append({"index": index, "cells": line})
        index += 1

    rows.append({"index": index, "cells": [
        "ITEM DESCRIPTION", "", "OPENING", "RECEIPT", "ISSUE", "CLOSING"]})
    index += 1

    for record in KRISHNA_ROWS:
        *values, closing_conf = record
        cells = [cell(values[0], column=0, confidence=0.95),
                 cell(values[1], column=1, confidence=0.93),
                 cell(values[2], column=2, confidence=0.95),
                 cell(values[3], column=3, confidence=0.95),
                 cell(values[4], column=4, confidence=0.95),
                 cell(values[5], column=5, confidence=closing_conf)]
        rows.append({"index": index, "cells": cells})
        index += 1

    # A value total printed under quantity columns.
    rows.append({"index": index, "cells": [
        cell("TOTAL", column=0, confidence=0.97),
        cell("", column=1), cell("60837", column=2, confidence=0.9),
        cell("0", column=3, confidence=0.95), cell("0", column=4, confidence=0.95),
        cell("60837", column=5, confidence=0.9)]})
    index += 1

    # A second, non-tabular block on the same page.
    rows.append({"index": index, "cells": ["PURCHASE DETAIL :-"]})
    index += 1
    rows.append({"index": index, "cells": [
        "SUPPLIER NAME", "INVOICE NO.", "DATE", "RECEIVE DATE", "AMOUNT"]})
    index += 1
    rows.append({"index": index, "cells": [
        "HETERO HEALTHCARE LTD - LICKNO", "5048751327", "31-07-2026",
        "05-08-2026", "53745.00"]})

    token_rows = [[r[2], r[3], r[4], r[5]] for r in KRISHNA_ROWS]
    token_rows.append(["60837", "0", "0", "60837"])
    token_rows.append(["5048751327", "53745.00"])
    return {"page": 1, "source": "ocr", "rows": rows,
            "tokens": numeric_tokens(token_rows)}


# ---------------------------------------------------------------------------

BUILDERS = {
    "amar.json": build_amar,
    "amar_grand_total.json": build_amar_grand_total,
    "bansal_p1.json": build_bansal_p1,
    "bansal_p2.json": build_bansal_p2,
    "khushi.json": build_khushi,
    "krishna.json": build_krishna,
}


def main() -> None:
    for name, builder in BUILDERS.items():
        path = HERE / name
        path.write_text(json.dumps(builder(), indent=1, ensure_ascii=False),
                        encoding="utf-8")
        print(f"wrote {path.relative_to(HERE.parent.parent)}")


if __name__ == "__main__":
    main()
