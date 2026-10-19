"""Reader-local batch materials with bounded isolated PDF workers."""
from __future__ import annotations

import inspect
import math
import multiprocessing as mp
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .reader_pdf import prepare_local_pdf


def _failure(code: str) -> dict[str, Any]:
    return {"status": "failed", "pages": [], "chunks": [],
            "issues": [{"code": code, "page": None}]}


def _validate_options(timeout_seconds, options):
    if (type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
        raise ValueError("timeout_seconds must be finite and positive")
    defaults = inspect.signature(prepare_local_pdf).parameters
    allowed = {"max_bytes", "max_pages", "chunk_chars", "overlap_chars", "max_text_chars", "max_chunks"}
    if options.keys() - allowed:
        raise ValueError(f"Unknown PDF options: {sorted(options.keys() - allowed)}")
    values = {name: options.get(name, defaults[name].default) for name in allowed}
    for name in allowed - {"overlap_chars"}:
        if type(values[name]) is not int or values[name] <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if (type(values["overlap_chars"]) is not int
            or not 0 <= values["overlap_chars"] < values["chunk_chars"]):
        raise ValueError("overlap_chars must satisfy 0 <= overlap_chars < chunk_chars")


def _pdf_worker(sender, path, options):
    try:
        try:
            result = prepare_local_pdf(path, **options)
        except Exception as exc:
            # Report unexpected bugs rather than disguising them as PDF failures.
            sender.send(("error", type(exc).__name__))
        else:
            sender.send(("result", result))
    finally:
        sender.close()


def prepare_pdf_isolated(path, *, timeout_seconds=60, _worker=_pdf_worker, **pdf_options):
    """Hard deadline includes spawn and IPC. Private worker injection is test-only.

    Call from an importable module with a guarded main entry point on Windows.
    A dedicated receiving thread drains IPC while the parent supervises the
    deadline; large IPC reads do not block the supervising thread.
    """
    _validate_options(timeout_seconds, pdf_options)
    context = mp.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(sender, path, pdf_options))
    messages = queue.Queue(maxsize=1)
    stopping = threading.Event()

    def receive():
        try:
            while not stopping.is_set():
                if receiver.poll(0.05):
                    messages.put(receiver.recv())
                    break
        except (EOFError, OSError):
            messages.put(("closed", None))

    thread = threading.Thread(target=receive, name="reader-pdf-ipc", daemon=True)
    started = False
    thread_started = False
    deadline = time.monotonic() + timeout_seconds
    try:
        try:
            process.start()
        except OSError:
            return _failure("worker_failed")
        started = True
        sender.close()
        thread.start()
        thread_started = True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _failure("parse_timeout")
        try:
            kind, payload = messages.get(timeout=remaining)
        except queue.Empty:
            return _failure("parse_timeout")
        process.join(max(0, deadline - time.monotonic()))
        if process.is_alive():
            return _failure("parse_timeout")
        if kind == "error":
            raise RuntimeError(f"PDF worker programming error: {payload}")
        if kind != "result" or process.exitcode != 0:
            return _failure("worker_failed")
        return payload
    finally:
        sender.close()
        if started:
            if process.is_alive():
                process.terminate()
            process.join()
        stopping.set()
        receiver.close()
        if thread_started:
            thread.join()
        process.close()


def prepare_paper_materials(papers, pdf_paths, *, timeout_seconds=60, max_workers=1,
                            material_cache=None, **pdf_options):
    """Complete replacement batch; title/path mapping is separate from Paper."""
    # Import lazily so local PDF preparation does not load P0/model dependencies.
    from .agents.reader import _prepare_papers

    _validate_options(timeout_seconds, pdf_options)
    if type(max_workers) is not int or not 1 <= max_workers <= 4:
        raise ValueError("max_workers must be an integer from 1 to 4")
    from .reader_cache import PDFMaterialCache
    if material_cache is not None and not isinstance(material_cache, PDFMaterialCache):
        raise ValueError("material_cache must be a PDFMaterialCache")
    prepared = _prepare_papers(papers)
    if not isinstance(pdf_paths, Mapping):
        raise ValueError("pdf_paths must be a title-to-path mapping")
    paths = {}
    for title, path in pdf_paths.items():
        if not isinstance(title, str) or not title.strip() or not isinstance(path, (str, Path)):
            raise ValueError("Mapping requires nonblank string titles and string/Path values")
        key = title.strip()
        normalized_path = str(path) if "://" in str(path) else str(Path(path))
        if key in paths and paths[key] != normalized_path:
            raise ValueError(f"Conflicting local paths for title: {key!r}")
        paths[key] = normalized_path
    used = {paper.title.strip() for paper in prepared}
    issues = [{"code": "unused_pdf_mapping", "paper_title": title}
              for title in paths if title not in used]
    def prepare(paper):
        key = paper.title.strip()
        parse = material_cache.prepare if material_cache is not None else prepare_pdf_isolated
        result = (parse(paths[key], timeout_seconds=timeout_seconds, **pdf_options)
                  if key in paths else _failure("local_pdf_missing"))
        return {"paper_title": paper.title, **result}

    if max_workers == 1 or not prepared:
        materials = [prepare(paper) for paper in prepared]
    else:
        # Each thread supervises its own isolated process; model calls remain
        # sequential. map preserves input order despite completion order.
        # The context waits for all worker cleanup even on programming errors.
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="reader-pdf") as pool:
            materials = list(pool.map(prepare, prepared))
    return {"materials": materials, "issues": issues}
