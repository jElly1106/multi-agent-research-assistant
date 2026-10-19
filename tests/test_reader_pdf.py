"""Synthetic PDFs only; generated in pytest temporary directories."""
import builtins
import hashlib
import json
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from pypdf.errors import PdfReadError

from research_assistant.reader_pdf import prepare_local_pdf, _clean_text


def make_pdf(path, texts=("Synthetic first page", "Synthetic second page"), encrypted=False):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=400, height=400)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 20 200 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("synthetic-password")
    writer.write(path)


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "synthetic.pdf"
    make_pdf(path)
    return path


def test_real_parser_and_chunks_preserve_source(pdf):
    original = hashlib.sha256(pdf.read_bytes()).digest()
    result = prepare_local_pdf(pdf, chunk_chars=10, overlap_chars=3)
    assert result["status"] == "ok"
    assert [page["page"] for page in result["pages"]] == [1, 2]
    assert "Synthetic first page" in result["pages"][0]["text"]
    for page in result["pages"]:
        chunks = [c for c in result["chunks"] if c["page"] == page["page"]]
        assert chunks[0]["start"] == 0
        assert chunks[-1]["end"] == len(page["text"])
        for chunk in chunks:
            assert chunk["text"] == page["text"][chunk["start"]:chunk["end"]]
        for left, right in zip(chunks, chunks[1:]):
            assert left["end"] - right["start"] == 3
    assert json.loads(json.dumps(result)) == result
    assert hashlib.sha256(pdf.read_bytes()).digest() == original


def test_unicode_cleaning():
    assert _clean_text("  合成\t文本\x00\r\n\r\n段落\u00a0二  ") == "合成 文本\n\n段落 二"


def test_partial_pages(pdf):
    class Page:
        def __init__(self, value):
            self.value = value
        def extract_text(self):
            if isinstance(self.value, Exception):
                raise self.value
            return self.value
    factory = lambda stream: SimpleNamespace(is_encrypted=False, pages=[
        Page("Synthetic usable"), Page(""), Page(PdfReadError("synthetic failure")),
        Page("合成\t文本"),
    ])
    result = prepare_local_pdf(pdf, _parser_factory=factory)
    assert result["status"] == "partial"
    assert [p["page"] for p in result["pages"]] == [1, 4]
    assert result["issues"] == [{"code": "no_text", "page": 2}, {"code": "page_extraction_failed", "page": 3}]


def test_empty_and_encrypted(tmp_path):
    blank = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(blank)
    assert prepare_local_pdf(blank)["status"] == "failed"
    encrypted = tmp_path / "encrypted.pdf"
    make_pdf(encrypted, encrypted=True)
    assert prepare_local_pdf(encrypted)["issues"][0]["code"] == "encrypted_pdf"


@pytest.mark.parametrize("kwargs,code", [({"max_bytes": 1}, "size_limit"), ({"max_pages": 1}, "page_limit")])
def test_limits(pdf, kwargs, code):
    result = prepare_local_pdf(pdf, **kwargs)
    assert result["status"] == "failed" and result["pages"] == []
    assert result["issues"][0]["code"] == code


def test_bad_sources(tmp_path):
    assert prepare_local_pdf(tmp_path / "missing.pdf")["issues"][0]["code"] == "file_access_failed"
    assert prepare_local_pdf(tmp_path)["issues"][0]["code"] == "regular_file_required"
    assert prepare_local_pdf("https://synthetic.invalid/p.pdf")["status"] == "failed"
    wrong = tmp_path / "synthetic.txt"
    wrong.write_text("Synthetic", encoding="utf-8")
    assert prepare_local_pdf(wrong)["issues"][0]["code"] == "pdf_required"
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    assert prepare_local_pdf(broken)["issues"][0]["code"] == "invalid_pdf_header"
    broken.write_bytes(b"%PDF-1.4\nbroken synthetic pdf")
    assert prepare_local_pdf(broken)["issues"][0]["code"] == "pdf_parse_failed"


@pytest.mark.parametrize("kwargs", [{"max_pages": 0}, {"max_bytes": True}, {"chunk_chars": 0}, {"overlap_chars": -1}, {"chunk_chars": 3, "overlap_chars": 3}])
def test_invalid_options(pdf, kwargs):
    with pytest.raises(ValueError):
        prepare_local_pdf(pdf, **kwargs)


def test_optional_dependency_and_programming_error(pdf, monkeypatch):
    import research_assistant.reader_pdf as module
    def bug(stream):
        raise AttributeError("synthetic bug")
    with pytest.raises(AttributeError):
        prepare_local_pdf(pdf, _parser_factory=bug)
    original = builtins.__import__
    def importing(name, *args, **kwargs):
        if name == "pypdf" or name.startswith("pypdf."):
            raise ImportError("synthetic missing PDF dependency")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", importing)
    assert module.prepare_local_pdf(pdf)["issues"][0]["code"] == "dependency_unavailable"
    from research_assistant.agents.reader import reader_node
    assert reader_node({"papers": []}) == {"paper_analysis": []}
