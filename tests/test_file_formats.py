"""Files whose name does not say what they are, and printouts saved as text."""

from __future__ import annotations

import io

import pytest

from readers.excel_reader import read_excel, sniff_format
from readers.router import PageKind, classify_file

REPORT = """\
           SOME MEDICAL AGENCIES
From : 26/05/2026               STOCK AND  SALES STATEMENT
------------------------------------------------------------------------------
Code   Product Name             Packing  Opening  Receipts    Sales  Closing
------------------------------------------------------------------------------
GNX073 BORIT SB 130MG CAP       10'S         74          5        3       76
GNX092 BORIT SB 65 CAP          10'S         60          0       10       50
HET020 HETERONOX 1% CREAM       5GM          39          0        3       36
GNX090 MOIST LOTION             100 ML       73         10        3       80
HET017 TREBOR-0.25% OINT        20GMS         1          0        0        1
"""


def test_a_printout_saved_as_text_is_read_as_a_table(tmp_path):
    from pipeline import process_file
    from schema import CellStatus, Role, SectionKind
    path = tmp_path / "STOCK.TXT"
    path.write_bytes((REPORT + "\f" + REPORT).encode("cp1252"))
    refs = classify_file(path)
    assert [r.kind for r in refs] == [PageKind.TEXT, PageKind.TEXT]
    page = process_file(path).pages[0]
    section = next(s for s in page.document.sections if s.kind is SectionKind.TABULAR)
    roles = {c.header_text: c.role for c in section.columns}
    assert roles["Opening"] is Role.OPENING_QTY and roles["Closing"] is Role.CLOSING_QTY
    first = section.data_rows[0]
    assert "BORIT SB 130MG CAP" in first.text
    # the characters are the file's own: exact, never pixel-derived
    assert all(c.status is not CellStatus.UNCHECKED for c in first.cells if not c.is_blank)


def _xlsx_bytes():
    import openpyxl
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Item", "Opening", "Receipt", "Issue", "Closing"])
    for name, o, r, i in (("A", 10, 5, 3), ("B", 7, 0, 7), ("C", 1, 2, 0), ("D", 4, 4, 4)):
        sheet.append([name, o, r, i, o + r - i])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize("name", ["report.xls", "report.csv", "report.XLSX"])
def test_a_workbook_is_read_by_its_contents_whatever_its_name(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(_xlsx_bytes())
    assert sniff_format(path) == "xlsx"
    assert [r.kind for r in classify_file(path)] == [PageKind.EXCEL]
    grid = read_excel(path)
    assert grid.rows[0].cells[0].text == "Item"


def test_a_csv_exported_in_the_windows_code_page_is_read(tmp_path):
    path = tmp_path / "export.csv"
    path.write_bytes("Item,Opening,Closing\nCAFÉ CREAM,10,8\n".encode("cp1252"))
    grid = read_excel(path)
    assert grid.rows[1].cells[0].text == "CAFÉ CREAM"


def test_an_empty_sheet_is_blank_not_unhealthy(tmp_path):
    import openpyxl
    from pipeline import process_file
    book = openpyxl.Workbook()
    book.active.append(["Item", "Opening", "Closing"])
    for n in range(6):
        book.active.append([f"P{n}", n, n])
    book.create_sheet("Sheet2")
    path = tmp_path / "two sheets.xlsx"
    book.save(path)
    pages = process_file(path).pages
    assert pages[1].healthy
    assert "blank sheet" in " ".join(pages[1].health.warnings)


def test_a_printout_pasted_into_one_column_is_read_as_its_columns(tmp_path):
    import openpyxl
    from pipeline import process_file
    from schema import Role, SectionKind
    book = openpyxl.Workbook()
    for line in REPORT.splitlines():
        book.active.append([line.replace("  ", "  ")])
    path = tmp_path / "printout.xlsx"
    book.save(path)
    document = process_file(path).pages[0].document
    section = next(s for s in document.sections if s.kind is SectionKind.TABULAR)
    roles = {c.header_text: c.role for c in section.columns}
    assert roles["Closing"] is Role.CLOSING_QTY


def test_a_closing_page_holding_only_the_grand_total_is_not_a_failure(tmp_path):
    from pipeline import process_file
    path = tmp_path / "closing.txt"
    tail = ("GRAND TOTAL        264244     100356          0    364601\n"
            "Powered By Some ERP for Retail and Distribution\n")
    path.write_text(REPORT + "\f" + tail, encoding="utf-8")
    pages = process_file(path).pages
    assert pages[1].healthy
    assert "closing page" in " ".join(pages[1].health.warnings)



def test_a_printer_file_is_read_without_its_control_codes(tmp_path):
    from pipeline import process_file
    from schema import Role, SectionKind
    esc = chr(27)
    body = esc + "CH" + esc + "M" + chr(13) + chr(10) + chr(14) + REPORT.replace("STOCK AND", esc + "ESTOCK AND" + esc + "F")
    path = tmp_path / "STAT.dat"
    path.write_bytes(body.encode("cp1252"))
    assert [r.kind for r in classify_file(path)] == [PageKind.TEXT]
    section = next(s for s in process_file(path).pages[0].document.sections
                   if s.kind is SectionKind.TABULAR)
    assert {c.header_text: c.role for c in section.columns}["Closing"] is Role.CLOSING_QTY
    assert esc not in " ".join(r.text for r in section.rows)


def test_a_word_export_and_a_web_page_are_read_as_tables(tmp_path):
    import zipfile
    from pipeline import process_file
    from schema import Role, SectionKind
    rows = [["Item", "Opening", "Receipt", "Issue", "Closing"]] + [
        [f"P{n}", str(n + 5), str(n), "2", str(2 * n + 3)] for n in range(6)]
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    cell = lambda t: f'<w:tc><w:p><w:r><w:t>{t}</w:t></w:r></w:p></w:tc>'
    xml = (f'<w:document xmlns:w="{w}"><w:body><w:p><w:r><w:t>SOME AGENCIES</w:t></w:r></w:p><w:tbl>'
           + "".join("<w:tr>" + "".join(cell(t) for t in r) + "</w:tr>" for r in rows)
           + "</w:tbl></w:body></w:document>")
    docx = tmp_path / "statement.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", xml)
    html = tmp_path / "statement.htm"
    html.write_text("<html><body><p>SOME AGENCIES</p><table>" + "".join(
        "<tr>" + "".join(f"<td>{t}</td>" for t in r) + "</tr>" for r in rows) + "</table></body></html>")
    for path in (docx, html):
        section = next(s for s in process_file(path).pages[0].document.sections
                       if s.kind is SectionKind.TABULAR)
        roles = {c.header_text: c.role for c in section.columns}
        assert roles["Opening"] is Role.OPENING_QTY and roles["Closing"] is Role.CLOSING_QTY, path.name


def test_a_pdf_saved_without_an_extension_is_read_as_a_pdf(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in REPORT.splitlines():
        page.insert_text((36, y), line, fontname="cour", fontsize=8)
        y += 11
    path = tmp_path / "DOC-20260602-WA0053_"
    doc.save(path)
    refs = classify_file(path)
    assert refs and refs[0].kind is PageKind.PDF_TEXT


def _text_pdf(path, lines):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((36, y), line, fontname="cour", fontsize=8)
        y += 11
    doc.save(path)


def test_a_garbled_text_layer_is_read_with_ocr_instead(tmp_path):
    # `ratlam statement.pdf`: an overlay whose words carry stray symbols. The
    # clean copy of the same report keeps its text layer.
    clean = tmp_path / "clean.pdf"
    _text_pdf(clean, REPORT.splitlines())
    assert classify_file(clean)[0].kind is PageKind.PDF_TEXT
    import pymupdf
    garbled = tmp_path / "garbled.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    font = pymupdf.Font("helv")
    writer = pymupdf.TextWriter(page.rect)
    y = 72
    for n, line in enumerate(REPORT.splitlines()):
        words = line.split()
        if n % 2:
            words = [w + chr(0x2022) if i % 3 == 0 else w for i, w in enumerate(words)]
        writer.append((36, y), " ".join(words), font=font, fontsize=8)
        y += 11
    writer.write_text(page)
    doc.save(garbled)
    assert classify_file(garbled)[0].kind is PageKind.IMAGE


def test_a_blank_scanned_page_is_blank_not_unhealthy(tmp_path):
    import pymupdf
    from pipeline import process_file
    path = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page()                        # nothing on it at all
    doc.save(path)
    page = process_file(path).pages[0]
    assert page.ref.kind is PageKind.IMAGE
    assert page.healthy and "blank page" in " ".join(page.health.warnings)


def test_a_closing_page_with_its_heading_repeated_is_not_a_failure(tmp_path):
    from pipeline import process_file
    path = tmp_path / "closing.txt"
    tail = ("Page No.3   Sales & Stock Statement(From 01/05/2026 Upto 31/05/2026)   Jun 1,2026\n"
            "HETERO HEALTHCARE LTD\n"
            "PRODUCT NAME      PACKING    Opening    Receipt    Issue    Closing\n"
            "                  Rate       Qty.       Value      Qty.     Value\n"
            "GRAND TOTAL                  656167.44  110108.64  433818.94  300182.76\n")
    path.write_text(REPORT + "\f" + tail, encoding="utf-8")
    pages = process_file(path).pages
    assert pages[1].healthy and "closing page" in " ".join(pages[1].health.warnings)
