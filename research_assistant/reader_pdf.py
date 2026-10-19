"""Reader-internal local PDF preparation; no network, OCR or shared state writes."""
from __future__ import annotations

import re
import stat
from pathlib import Path
from typing import Any, BinaryIO, Callable


def _load_parser():
    # Lazy optional dependency: importing Reader P0 never requires pypdf.
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError
    return PdfReader, PyPdfError


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def prepare_local_pdf(
    path: str | Path, *, max_bytes: int = 20 * 1024 * 1024,
    max_pages: int = 300, chunk_chars: int = 3000, overlap_chars: int = 200,
    max_text_chars: int = 1_000_000, max_chunks: int = 5000,
    _parser_factory: Callable[[BinaryIO], Any] | None = None,
) -> dict[str, Any]:
    """Return status/pages/chunks/issues; offsets are end-exclusive cleaned characters.

    Expected I/O and pypdf errors are material failures. Unexpected programming
    errors propagate. The private parser factory supports synthetic offline tests.
    """
    for name, value in [("max_bytes", max_bytes), ("max_pages", max_pages), ("chunk_chars", chunk_chars),
                        ("max_text_chars", max_text_chars), ("max_chunks", max_chunks)]:
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if type(overlap_chars) is not int or not 0 <= overlap_chars < chunk_chars:
        raise ValueError("overlap_chars must satisfy 0 <= overlap_chars < chunk_chars")
    result: dict[str, Any] = {"status": "failed", "pages": [], "chunks": [], "issues": []}
    total_chars = 0

    def issue(code: str, page: int | None = None) -> None:
        result["issues"].append({"code": code, "page": page})

    if "://" in str(path):
        issue("local_file_required")
        return result
    source = Path(path)
    try:
        info = source.stat()
        if not stat.S_ISREG(info.st_mode) or source.is_symlink():
            issue("regular_file_required")
            return result
        if source.suffix.lower() != ".pdf":
            issue("pdf_required")
            return result
        if info.st_size > max_bytes:
            issue("size_limit")
            return result
        try:
            parser, pdf_error = _load_parser()
        except ImportError:
            issue("dependency_unavailable")
            return result
        expected = (OSError, pdf_error)
        with source.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                issue("invalid_pdf_header")
                return result
            stream.seek(0)
            try:
                reader = (_parser_factory or parser)(stream)
                if reader.is_encrypted:
                    issue("encrypted_pdf")
                    return result
                if len(reader.pages) > max_pages:
                    issue("page_limit")
                    return result
                for page_number in range(1, len(reader.pages) + 1):
                    try:
                        text = _clean_text(reader.pages[page_number - 1].extract_text() or "")
                    except expected:
                        issue("page_extraction_failed", page_number)
                        continue
                    if not text:
                        issue("no_text", page_number)
                        continue
                    total_chars += len(text)
                    if total_chars > max_text_chars:
                        result["pages"].clear()
                        result["chunks"].clear()
                        issue("text_limit")
                        return result
                    result["pages"].append({"page": page_number, "text": text})
                    start = 0
                    while start < len(text):
                        if len(result["chunks"]) >= max_chunks:
                            result["pages"].clear()
                            result["chunks"].clear()
                            issue("chunk_limit")
                            return result
                        end = min(start + chunk_chars, len(text))
                        result["chunks"].append({
                            "index": len(result["chunks"]) + 1, "page": page_number,
                            "start": start, "end": end, "text": text[start:end],
                        })
                        if end == len(text):
                            break
                        start = end - overlap_chars
            except expected:
                issue("pdf_parse_failed")
    except OSError:
        issue("file_access_failed")
    if result["pages"]:
        result["status"] = "partial" if result["issues"] else "ok"
    return result
