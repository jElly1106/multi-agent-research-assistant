"""Explicit, bounded in-memory PDF material cache. No model responses are cached."""
from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path


class PDFMaterialCache:
    """Reuse parsed materials by exact PDF bytes and parsing options.

    Only immutable byte snapshots are parsed. Callers own the cache lifetime;
    nothing is persisted. Duplicate concurrent misses may parse independently.
    """

    def __init__(self, *, max_entries=16, max_bytes=8 * 1024 * 1024):
        for name, value in [("max_entries", max_entries), ("max_bytes", max_bytes)]:
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._items = OrderedDict()
        self._bytes = self._hits = self._misses = 0
        self._lock = threading.Lock()

    def clear(self):
        with self._lock:
            self._items.clear()
            self._bytes = self._hits = self._misses = 0

    def report(self):
        with self._lock:
            return {"entries": len(self._items), "bytes": self._bytes,
                    "hits": self._hits, "misses": self._misses}

    def prepare(self, path, *, timeout_seconds=60, **options):
        from .reader_materials import _validate_options, prepare_pdf_isolated
        _validate_options(timeout_seconds, options)
        # Invalid/missing sources retain the normal failure contract and never
        # hit stale entries even if an earlier file at that path was cached.
        source = Path(path)
        try:
            info = source.stat()
            if ("://" in str(path) or source.is_symlink() or not stat.S_ISREG(info.st_mode)
                    or source.suffix.lower() != ".pdf"
                    or info.st_size > options.get("max_bytes", 20 * 1024 * 1024)):
                return prepare_pdf_isolated(path, timeout_seconds=timeout_seconds, **options)
            with source.open("rb") as stream:
                data = stream.read(options.get("max_bytes", 20 * 1024 * 1024) + 1)
        except OSError:
            return prepare_pdf_isolated(path, timeout_seconds=timeout_seconds, **options)
        if len(data) > options.get("max_bytes", 20 * 1024 * 1024):
            from .reader_materials import _failure
            return _failure("size_limit")
        key = (hashlib.sha256(data).hexdigest(), json.dumps(options, sort_keys=True))
        with self._lock:
            if key in self._items:
                self._hits += 1
                self._items.move_to_end(key)
                return json.loads(self._items[key])
            self._misses += 1
        # Parse exactly the hashed bytes, rather than a path that could change
        # between hashing and the worker opening it. Temp copies are removed.
        try:
            with tempfile.TemporaryDirectory(prefix="reader-snapshot-") as directory:
                snapshot = Path(directory) / "material.pdf"
                snapshot.write_bytes(data)
                result = prepare_pdf_isolated(snapshot, timeout_seconds=timeout_seconds, **options)
        except OSError:
            from .reader_materials import _failure
            return _failure("file_access_failed")
        if result["status"] not in {"ok", "partial"}:
            return result
        encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
        if len(encoded) <= self.max_bytes:
            with self._lock:
                old = self._items.pop(key, None)
                if old is not None:
                    self._bytes -= len(old)
                self._items[key] = encoded
                self._bytes += len(encoded)
                while len(self._items) > self.max_entries or self._bytes > self.max_bytes:
                    _, removed = self._items.popitem(last=False)
                    self._bytes -= len(removed)
        return result
