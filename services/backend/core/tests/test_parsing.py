import pytest

from core.common.errors import ParseFailure
from core.materials.parsing import CHUNK_SIZE, ParsingStopped, parse_document
from core.tests.parse_samples import CSV_SAMPLE, docx_sample, pdf_sample


def test_pdf_physical_page_and_label():
    result = parse_document(pdf_sample(), "sample.pdf")
    assert len(result.chunks) == 2
    assert result.chunks[1]["text"] == "Self-authored result"
    assert result.chunks[1]["anchor"] == {
        "kind": "pdf",
        "page": 2,
        "page_label": "ii",
        "start": 0,
        "end": 20,
    }
    assert result.coverage == "text"
    with pytest.raises(ParseFailure, match="no_text"):
        parse_document(pdf_sample(blank=True), "scan.pdf")


def test_docx_paragraphs_headings_and_excluded_tables():
    result = parse_document(docx_sample(), "sample.docx")
    assert [c["text"] for c in result.chunks] == ["自制标题", "自制正文\t尾部"]
    assert result.chunks[0]["heading_level"] == 1
    assert result.chunks[1]["anchor"]["paragraph"] == 3
    assert "page" not in result.chunks[1]["anchor"]
    assert result.coverage == "partial" and result.warnings


def test_csv_schema_numbers_and_multiline_anchor():
    result = parse_document(CSV_SAMPLE, "sample.csv")
    anchor = result.chunks[0]["anchor"]
    assert anchor["record"] == 1 and anchor["line_start"] == 2 and anchor["line_end"] == 3
    assert anchor["fields"]["value"] == "0.9"
    for content, code in [
        (b"a,b\n1,2\n", "csv_schema"),
        (CSV_SAMPLE.replace(b"0.9", b"NaN"), "csv_value"),
    ]:
        with pytest.raises(ParseFailure, match=code):
            parse_document(content, "bad.csv")


def test_text_offsets_limit_cancel_and_checkpoint_errors():
    text = "a" * (CHUNK_SIZE + 10)
    chunks = parse_document(text.encode(), "sample.txt").chunks
    assert "".join(c["text"] for c in chunks) == text
    assert chunks[1]["anchor"]["start"] == CHUNK_SIZE
    with pytest.raises(ParseFailure, match="text_limit"):
        parse_document(b"a" * 1_000_001, "large.txt")
    with pytest.raises(ParsingStopped):
        parse_document(b"sample", "sample.txt", lambda _: False)

    def failed_database(_):
        raise RuntimeError("transient database failure")

    with pytest.raises(RuntimeError):
        parse_document(b"sample", "sample.txt", failed_database)
