import pytest

from ocrhub.adapters.pdfplumber_adapter import PdfplumberAdapter


def test_available_is_always_true():
    assert PdfplumberAdapter().available() is True


def test_extract_returns_text_from_born_digital_pdf(sample_born_digital_pdf_bytes):
    adapter = PdfplumberAdapter()
    result = adapter.extract(sample_born_digital_pdf_bytes, "sample.pdf")

    assert result.ok is True
    assert "OCRHUB" in result.text
    assert len(result.pages) == 1


def test_extract_rejects_non_pdf():
    adapter = PdfplumberAdapter()
    with pytest.raises(ValueError):
        adapter.extract(b"not a pdf", "photo.png")


def test_extract_returns_line_boxes_with_font_style(sample_born_digital_pdf_bytes):
    result = PdfplumberAdapter().extract(sample_born_digital_pdf_bytes, "sample.pdf")

    page = result.pages[0]
    assert page.width and page.height
    box = next(b for b in page.boxes if "OCRHUB" in b.text)
    assert box.style["size"] > 0
    assert box.style["font"]
    assert box.x1 > box.x0 and box.y1 > box.y0


def test_extract_splits_lines_into_styled_runs_with_spaces():
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 12)
    pdf.write(8, "Date: ")
    pdf.set_font("Helvetica", "", 12)
    pdf.write(8, "September 30 report")
    result = PdfplumberAdapter().extract(bytes(pdf.output()), "s.pdf")

    runs = result.pages[0].boxes[0].style["runs"]
    assert [r["text"] for r in runs] == ["Date:", "September 30 report"]
    assert runs[0]["bold"] is True and runs[1]["bold"] is False
    assert runs[1]["x0"] > runs[0]["x1"]


def test_extract_detects_tables_with_cell_alignment():
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    with pdf.table(text_align=("CENTER", "RIGHT")) as table:
        for cells in (("Region", "Q1"), ("North", "12,450"), ("South", "9,800")):
            row = table.row()
            for text in cells:
                row.cell(text)
    result = PdfplumberAdapter().extract(bytes(pdf.output()), "t.pdf")

    tables = [b for b in result.pages[0].boxes if b.region_type == "Table"]
    assert len(tables) == 1
    assert tables[0].html.count("<tr>") == 3
    assert 'align="right">12,450' in tables[0].html
    assert "North | 12,450" in tables[0].text
    # cell text must not also appear as free-standing line boxes
    assert not any(b.region_type == "Text" and "12,450" in b.text for b in result.pages[0].boxes)
