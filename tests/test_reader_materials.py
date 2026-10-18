"""Synthetic batch records, PDFs and spawned failure workers; no network."""
import copy
import json
import multiprocessing as mp
import os
import time
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import research_assistant.reader_materials as materials
from research_assistant.reader_pdf import prepare_local_pdf
from test_reader_pdf import make_pdf


def paper(title):
    return {"title": title, "authors": [], "source": "synthetic", "year": 2026}


def slow_worker(sender, path, options):
    time.sleep(30)


def crash_worker(sender, path, options):
    os._exit(7)


def bug_worker(sender, path, options):
    sender.send(("error", "AttributeError"))
    sender.close()


def large_worker(sender, path, options):
    sender.send(("result", {"synthetic": "x" * 2_000_000}))
    sender.close()


@pytest.mark.parametrize("worker,code", [(slow_worker, "parse_timeout"),
                                         (crash_worker, "worker_failed")])
def test_workers_are_reaped(worker, code):
    before = {p.pid for p in mp.active_children()}
    result = materials.prepare_pdf_isolated("synthetic.pdf", timeout_seconds=10 if worker == crash_worker else 2, _worker=worker)
    assert result["issues"][0]["code"] == code
    assert {p.pid for p in mp.active_children()} == before


def test_worker_error_and_large_message():
    with pytest.raises(RuntimeError, match="AttributeError"):
        materials.prepare_pdf_isolated("synthetic.pdf", _worker=bug_worker)
    result = materials.prepare_pdf_isolated("synthetic.pdf", _worker=large_worker, timeout_seconds=10)
    assert len(result["synthetic"]) == 2_000_000
    assert not mp.active_children()


def test_actual_spawn_batch_and_replacement(tmp_path):
    path = tmp_path / "synthetic.pdf"
    make_pdf(path)
    blank = tmp_path / "partial.pdf"
    make_pdf(blank, texts=("Synthetic text", ""))
    papers = [paper(" First "), paper("Partial"), paper("Missing"), paper("Bad"), paper("First")]
    paths = {"First": path, "Partial": blank, "Bad": tmp_path / "missing.pdf", "Unused": "never-read.pdf"}
    original = copy.deepcopy((papers, paths))
    result = materials.prepare_paper_materials(papers, paths)
    assert [m["status"] for m in result["materials"]] == ["ok", "partial", "failed", "failed"]
    assert result["materials"][0]["paper_title"] == " First "
    assert result["materials"][2]["issues"][0]["code"] == "local_pdf_missing"
    assert result["issues"] == [{"code": "unused_pdf_mapping", "paper_title": "Unused"}]
    assert (papers, paths) == original
    assert json.loads(json.dumps(result)) == result
    rerun = materials.prepare_paper_materials([paper("New")], {})
    assert [m["paper_title"] for m in rerun["materials"]] == ["New"]


@pytest.mark.parametrize("paths", [None, {"": "p.pdf"}, {1: "p.pdf"}, {"A": 3},
                                    {"A": "a.pdf", " A ": "b.pdf"}])
def test_bad_mapping_before_parse(paths, monkeypatch):
    parse = Mock()
    monkeypatch.setattr(materials, "prepare_pdf_isolated", parse)
    with pytest.raises(ValueError):
        materials.prepare_paper_materials([paper("A")], paths)
    parse.assert_not_called()


def test_conflict_before_parse(monkeypatch):
    parse = Mock()
    monkeypatch.setattr(materials, "prepare_pdf_isolated", parse)
    second = paper(" A ")
    second["year"] = 2025
    with pytest.raises(ValueError):
        materials.prepare_paper_materials([paper("A"), second], {"A": "synthetic.pdf"})
    parse.assert_not_called()


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_bad_deadlines(timeout):
    with pytest.raises(ValueError):
        materials.prepare_paper_materials([], {}, timeout_seconds=timeout)


def test_option_validation_even_for_empty_batch():
    for options in [{"max_chunks": 0}, {"max_text_chars": False}, {"unknown": 1}, {"overlap_chars": 3000}]:
        with pytest.raises(ValueError):
            materials.prepare_paper_materials([], {}, **options)


def test_timeout_batch_continues(monkeypatch):
    actual = materials.prepare_pdf_isolated
    def isolated(path, **options):
        worker = slow_worker if path == "slow.pdf" else large_worker
        options["timeout_seconds"] = 1 if path == "slow.pdf" else 15
        return actual(path, _worker=worker, **options)
    monkeypatch.setattr(materials, "prepare_pdf_isolated", isolated)
    result = materials.prepare_paper_materials([paper("Slow"), paper("Next")],
        {"Slow": "slow.pdf", "Next": "next.pdf"}, timeout_seconds=2)
    assert result["materials"][0]["issues"][0]["code"] == "parse_timeout"
    assert len(result["materials"][1]["synthetic"]) == 2_000_000


def test_limits_clear_all_previously_prepared_material(tmp_path):
    path = tmp_path / "synthetic.pdf"
    make_pdf(path)
    factory = lambda stream: SimpleNamespace(is_encrypted=False, pages=[
        SimpleNamespace(extract_text=lambda: "abc"), SimpleNamespace(extract_text=lambda: "def")])
    assert prepare_local_pdf(path, max_text_chars=6, max_chunks=2, _parser_factory=factory)["status"] == "ok"
    for options, code in [({"max_text_chars": 5}, "text_limit"), ({"max_chunks": 1}, "chunk_limit")]:
        result = prepare_local_pdf(path, _parser_factory=factory, **options)
        assert result["status"] == "failed"
        assert result["pages"] == result["chunks"] == []
        assert result["issues"][-1]["code"] == code


@pytest.mark.parametrize("workers", [0, 5, True, 1.5, "2"])
def test_invalid_parallelism_precedes_work(workers, monkeypatch):
    parse = Mock()
    monkeypatch.setattr(materials, "prepare_pdf_isolated", parse)
    with pytest.raises(ValueError, match="max_workers"):
        materials.prepare_paper_materials([], {}, max_workers=workers)
    parse.assert_not_called()


def test_parallel_bound_order_and_cleanup(monkeypatch):
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    active = peak = 0
    def parse(path, **options):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            barrier.wait(timeout=5)
            return {"status": "ok", "pages": [], "chunks": [], "issues": []}
        finally:
            with lock:
                active -= 1
    monkeypatch.setattr(materials, "prepare_pdf_isolated", parse)
    papers = [paper(str(i)) for i in range(4)]
    result = materials.prepare_paper_materials(papers, {str(i): f"{i}.pdf" for i in range(4)}, max_workers=2)
    assert peak == 2 and active == 0
    assert [m["paper_title"] for m in result["materials"]] == [str(i) for i in range(4)]
    assert not any(t.name.startswith("reader-pdf") for t in threading.enumerate())


def test_parallel_real_spawn_and_failure_cleanup(tmp_path):
    before = {p.pid for p in mp.active_children()}
    path = tmp_path / "synthetic.pdf"
    make_pdf(path)
    result = materials.prepare_paper_materials([paper("A"), paper("Bad"), paper("B")],
        {"A": path, "Bad": tmp_path / "missing.pdf", "B": path}, max_workers=2)
    assert [m["status"] for m in result["materials"]] == ["ok", "failed", "ok"]
    assert {p.pid for p in mp.active_children()} == before


def test_parallel_programming_error_waits_for_cleanup(monkeypatch):
    barrier = threading.Barrier(2)
    done = threading.Event()
    def parse(path, **options):
        barrier.wait(timeout=5)
        if path == "bug.pdf":
            raise AttributeError("synthetic bug")
        done.set()
        return materials._failure("synthetic")
    monkeypatch.setattr(materials, "prepare_pdf_isolated", parse)
    with pytest.raises(AttributeError, match="synthetic bug"):
        materials.prepare_paper_materials([paper("Bug"), paper("Other")],
            {"Bug": "bug.pdf", "Other": "other.pdf"}, max_workers=2)
    assert done.is_set()
    assert not any(t.name.startswith("reader-pdf") for t in threading.enumerate())
