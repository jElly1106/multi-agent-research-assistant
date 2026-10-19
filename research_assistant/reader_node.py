"""Reader-only full-text node factory; does not change the shared graph wiring."""
from __future__ import annotations

import copy

from .reader_materials import prepare_paper_materials
from .reader_pipeline import _preflight, run_reader, run_reader_with_downloads
from .state import ResearchState


def create_fulltext_reader_node(
    pdf_paths=None, *, download_arxiv=False, download_options=None,
    abstract_analyzer_factory=None, fulltext_analyzer_factory=None,
    reconciler_factory=None, budget_options=None, pdf_options=None,
    fulltext_options=None, material_cache=None,
):
    """Configure a node that reads papers and returns only paper_analysis.

    Local mappings and options are copied at construction; a deliberately shared
    material cache and injected factories retain their caller-owned lifetimes.
    Missing local mappings may use arXiv only when explicitly enabled. Diagnostics
    remain available through the standalone pipeline instead of shared state.
    """
    if type(download_arxiv) is not bool:
        raise ValueError("download_arxiv must be a boolean")
    if download_options is not None and not download_arxiv:
        raise ValueError("download_options requires download_arxiv=True")
    paths = copy.deepcopy({} if pdf_paths is None else pdf_paths)
    options = copy.deepcopy({"budget_options": budget_options, "pdf_options": pdf_options,
                             "fulltext_options": fulltext_options})
    # Check all static configuration at construction without parsing or paid calls.
    _preflight([], **options)
    prepare_paper_materials([], paths, material_cache=material_cache, **(pdf_options or {}))
    remote_options = copy.deepcopy(download_options)
    if download_arxiv:
        from .reader_download import validate_download_options
        if remote_options is not None and not isinstance(remote_options, dict):
            raise ValueError("download_options must be a dict")
        validate_download_options(**(remote_options or {}))

    def node(state: ResearchState) -> dict:
        runner = run_reader_with_downloads if download_arxiv else run_reader
        extra = {"download_options": remote_options} if download_arxiv else {}
        result = runner(state.get("papers", []), paths,
            abstract_analyzer_factory=abstract_analyzer_factory,
            fulltext_analyzer_factory=fulltext_analyzer_factory,
            reconciler_factory=reconciler_factory, material_cache=material_cache,
            **options, **extra)
        return {"paper_analysis": result["paper_analysis"]}

    return node
