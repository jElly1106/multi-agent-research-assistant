"""Standalone Reader for supplied papers; optional arXiv PDF acquisition."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .reader_pipeline import run_reader, run_reader_with_downloads


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path,
                        help="JSON object with papers and optional pdf_paths/options")
    parser.add_argument("--output", type=Path, help="New result JSON file; existing files are refused")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Disable downloads and both default model adapters")
    mode.add_argument("--download-arxiv", action="store_true", help="Fetch supported arXiv PDFs before analysis")
    parser.add_argument("--no-llm", action="store_true",
                        help="Disable model analysis; may be combined with --download-arxiv")
    args = parser.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or "papers" not in payload:
        parser.error("input must be a JSON object containing papers")
    allowed = {"papers", "pdf_paths", "pdf_options", "fulltext_options", "budget_options"}
    if args.download_arxiv:
        allowed.add("download_options")
    if payload.keys() - allowed:
        parser.error("unknown input fields: " + ", ".join(sorted(payload.keys() - allowed)))
    # Reserve a new destination before any paid calls; never truncate a result.
    destination = args.output.open("x", encoding="utf-8") if args.output else None
    previous = os.environ.get("READER_USE_LLM")
    try:
        if args.offline or args.no_llm:
            os.environ["READER_USE_LLM"] = "0"
        result = (run_reader_with_downloads if args.download_arxiv else run_reader)(**payload)
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if destination:
            destination.write(rendered)
        else:
            # Legacy Windows consoles cannot encode all PDF characters. JSON
            # escapes preserve their exact values without changing stdout's
            # global encoding or failing after a completed analysis.
            encoding = getattr(sys.stdout, "encoding", None)
            if encoding:
                try:
                    rendered.encode(encoding)
                except UnicodeEncodeError:
                    rendered = json.dumps(result, ensure_ascii=True, indent=2) + "\n"
            print(rendered, end="")
    except BaseException:
        if destination:
            destination.close()
            args.output.unlink()
        raise
    finally:
        if destination:
            destination.close()
        if previous is None:
            os.environ.pop("READER_USE_LLM", None)
        else:
            os.environ["READER_USE_LLM"] = previous


if __name__ == "__main__":
    main()
