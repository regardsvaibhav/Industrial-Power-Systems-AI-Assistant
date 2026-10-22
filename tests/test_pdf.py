import pymupdf
import pytest

from app.rag.pdf import PDFError, chunk_pdf, normalise_text, parse_pdf
from tests.conftest import CORPUS, make_pdf


def test_parse_and_chunk_corpus_document():
    data = (CORPUS / "IPS-03_transformer_loading.pdf").read_bytes()
    parsed = parse_pdf(data, "IPS-03.pdf")
    assert parsed.page_count == 3
    assert parsed.title.startswith("IPS-03")
    chunks = chunk_pdf(parsed, "IPS-03.pdf")
    assert chunks
    assert {c.page for c in chunks} == {1, 2, 3}
    for c in chunks:
        assert c.metadata["page"] == c.page
        assert c.chunk_id.startswith(parsed.doc_id)
        assert len(c.text) <= 900 + 200  # size plus carried overlap
    # every chunk's text really is on its page (citations are page-accurate)
    doc = pymupdf.open(stream=data, filetype="pdf")
    for c in chunks:
        page_text = normalise_text(doc[c.page - 1].get_text())
        first_words = " ".join(c.text.split()[:4])
        assert " ".join(page_text.split()).find(first_words) >= 0


def test_doc_id_is_content_hash():
    a = make_pdf(["Hello transformer world " * 5])
    assert parse_pdf(a, "a.pdf").doc_id == parse_pdf(a, "renamed.pdf").doc_id


def test_ligatures_and_controls_normalised():
    assert normalise_text("eﬃciency\x00 test") == "efficiency test"


@pytest.mark.parametrize(
    "data,msg",
    [
        (b"hello world", "Not a PDF"),
        (b"%PDF-1.7 garbage that is not a pdf", "Could not open"),
    ],
)
def test_rejects_non_pdfs(data, msg):
    with pytest.raises(PDFError, match=msg):
        parse_pdf(data, "x.pdf")


def test_rejects_oversize_and_too_many_pages():
    data = make_pdf(["page one text here"] * 3)
    with pytest.raises(PDFError, match="pages"):
        parse_pdf(data, "x.pdf", max_pages=2)
    with pytest.raises(PDFError, match="MB"):
        parse_pdf(data, "x.pdf", max_bytes=100)


def test_rejects_encrypted_pdf():
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "secret")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    with pytest.raises(PDFError, match="Encrypted"):
        parse_pdf(data, "x.pdf")


def test_rejects_textless_pdf():
    doc = pymupdf.open()
    doc.new_page()
    with pytest.raises(PDFError, match="No extractable text"):
        parse_pdf(doc.tobytes(), "x.pdf")
