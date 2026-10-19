"""Synthetic cache content identity, bounds, isolation and snapshot tests."""
import json

import pytest

from research_assistant.reader_cache import PDFMaterialCache
from research_assistant import reader_materials
from test_reader_pdf import make_pdf


def test_actual_pdf_cache_content_options_and_copy_isolation(tmp_path):
    path = tmp_path / "synthetic.pdf"
    make_pdf(path, texts=("Synthetic first",))
    cache = PDFMaterialCache()
    first = cache.prepare(path)
    assert first["status"] == "ok"
    first["pages"].clear()
    assert cache.prepare(path)["pages"][0]["text"] == "Synthetic first"
    assert cache.report()["hits"] == 1
    make_pdf(path, texts=("Synthetic changed",))
    assert cache.prepare(path)["pages"][0]["text"] == "Synthetic changed"
    cache.prepare(path, chunk_chars=500)
    assert cache.report()["misses"] == 3
    path.unlink()
    assert cache.prepare(path)["status"] == "failed"
    assert cache.report()["hits"] == 1
    cache.clear()
    assert cache.report() == {"entries": 0, "bytes": 0, "hits": 0, "misses": 0}


def test_snapshot_is_exact_and_removed_on_error(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-synthetic before")
    seen = []
    def parse(snapshot, **options):
        seen.append(snapshot)
        path.write_bytes(b"%PDF-synthetic after")
        assert snapshot.read_bytes() == b"%PDF-synthetic before"
        raise AttributeError("synthetic bug")
    monkeypatch.setattr(reader_materials, "prepare_pdf_isolated", parse)
    cache = PDFMaterialCache()
    with pytest.raises(AttributeError):
        cache.prepare(path)
    assert seen and not seen[0].exists()
    assert cache.report()["entries"] == 0


def test_lru_byte_bounds_and_failures_not_cached(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.pdf"
    result = {"status": "ok", "pages": [], "chunks": [], "issues": []}
    monkeypatch.setattr(reader_materials, "prepare_pdf_isolated", lambda *a, **kw: dict(result))
    cache = PDFMaterialCache(max_entries=1)
    for data in [b"%PDF-one", b"%PDF-two", b"%PDF-one"]:
        path.write_bytes(data)
        cache.prepare(path)
    assert cache.report()["entries"] == 1 and cache.report()["misses"] == 3
    assert cache.report()["bytes"] == len(json.dumps(result).encode())
    tiny = PDFMaterialCache(max_bytes=1)
    tiny.prepare(path)
    assert tiny.report()["entries"] == 0
    result["status"] = "failed"
    failed = PDFMaterialCache()
    failed.prepare(path)
    failed.prepare(path)
    assert failed.report()["misses"] == 2 and failed.report()["hits"] == 0


def test_snapshot_io_failure_is_uncached_material_failure(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-synthetic")
    def fail(*args, **kwargs):
        raise PermissionError("synthetic snapshot access failure")
    monkeypatch.setattr("research_assistant.reader_cache.tempfile.TemporaryDirectory", fail)
    cache = PDFMaterialCache()
    result = cache.prepare(path)
    assert result["issues"][0]["code"] == "file_access_failed"
    assert cache.report()["entries"] == 0


def test_parallel_batch_cache_and_pipeline(tmp_path):
    from research_assistant.reader_pipeline import run_reader
    path = tmp_path / "synthetic.pdf"
    make_pdf(path)
    papers = [{"title": "Synthetic", "authors": [], "source": "synthetic"}]
    cache = PDFMaterialCache()
    first = run_reader(papers, {"Synthetic": path}, material_cache=cache,
                       pdf_options={"max_workers": 2})
    second = run_reader(papers, {"Synthetic": path}, material_cache=cache)
    assert first == second
    assert cache.report()["hits"] == 1
    with pytest.raises(ValueError):
        reader_materials.prepare_paper_materials([], {}, material_cache={})


@pytest.mark.parametrize("options", [{"max_entries": 0}, {"max_bytes": True}])
def test_invalid_cache_limits(options):
    with pytest.raises(ValueError):
        PDFMaterialCache(**options)
