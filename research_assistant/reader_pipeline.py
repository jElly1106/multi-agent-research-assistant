"""Independent Reader orchestration. Default graph wiring remains unchanged."""
from __future__ import annotations

import copy
import json
import os
import tempfile

from .agents.reader import (
    LLMAbstractAnalyzer, LLMUnavailableError, SYSTEM_PROMPT, _prepare_papers, analyze_papers,
)
from .reader_budget import ReaderBudget
from .reader_fulltext import (
    ChunkExtraction, LLMChunkAnalyzer, PROMPT, analyze_fulltext_materials,
    LLMReconciler, Reconciliation, RECONCILE_PROMPT,
)
from .reader_materials import prepare_paper_materials
from .schemas import PaperAnalysis


def _preflight(papers, budget_options, pdf_options, fulltext_options):
    for name, options in [("budget_options", budget_options), ("pdf_options", pdf_options),
                          ("fulltext_options", fulltext_options)]:
        if options is not None and not isinstance(options, dict):
            raise ValueError(f"{name} must be a dict")
    if fulltext_options and fulltext_options.keys() - {"max_chunks", "max_chunk_chars", "max_total_chars", "reconcile"}:
        raise ValueError("fulltext_options only accepts per-paper input limits and reconcile")
    if pdf_options and "material_cache" in pdf_options:
        raise ValueError("pass material_cache separately from pdf_options")
    prepared = [p.model_dump(mode="json") for p in _prepare_papers(papers)]
    budget = ReaderBudget(**(budget_options or {}))
    # Validate P2 limits before preparation or any analyzer invocation.
    analyze_fulltext_materials([], [], **(fulltext_options or {}))
    return prepared, budget


def run_reader_with_downloads(papers, pdf_paths=None, *, download_options=None,
                              abstract_analyzer_factory=None, fulltext_analyzer_factory=None,
                              budget_options=None, pdf_options=None, fulltext_options=None,
                              material_cache=None, reconciler_factory=None):
    """Explicit arXiv acquisition, local analysis, then temporary-file cleanup."""
    from .reader_download import acquire_pdfs, validate_download_options
    if download_options is not None and not isinstance(download_options, dict):
        raise ValueError("download_options must be a dict")
    validate_download_options(**(download_options or {}))
    prepared, _ = _preflight(papers, budget_options, pdf_options, fulltext_options)
    local = {} if pdf_paths is None else pdf_paths
    prepare_paper_materials([], local, material_cache=material_cache, **(pdf_options or {}))
    with tempfile.TemporaryDirectory(prefix="reader-download-") as directory:
        paths, receipts = acquire_pdfs(prepared, local, directory, **(download_options or {}))
        result = run_reader(prepared, paths,
            abstract_analyzer_factory=abstract_analyzer_factory,
            fulltext_analyzer_factory=fulltext_analyzer_factory, budget_options=budget_options,
            pdf_options=pdf_options, fulltext_options=fulltext_options, material_cache=material_cache,
            reconciler_factory=reconciler_factory)
        result["acquisition"] = receipts
        return result


def run_reader(papers, pdf_paths=None, *, abstract_analyzer_factory=None,
               fulltext_analyzer_factory=None, budget_options=None, pdf_options=None,
               fulltext_options=None, material_cache=None, reconciler_factory=None):
    """Complete independent run: local preparation -> abstract -> fulltext merge.

    Default adapters disable automatic retries and cap model output. Injected
    analyzers must honor the same output/call contract themselves.
    """
    prepared, budget = _preflight(papers, budget_options, pdf_options, fulltext_options)
    # Validate mappings/options and finish local preparation before paid calls.
    batch = prepare_paper_materials(prepared, {} if pdf_paths is None else pdf_paths,
                                    material_cache=material_cache, **(pdf_options or {}))

    class AbstractAdapter:
        def __init__(self):
            self.analyzer = None

        def analyze(self, paper):
            if abstract_analyzer_factory is None and os.getenv("READER_USE_LLM", "1").strip() == "0":
                raise LLMUnavailableError("Reader disabled")
            budget.reserve(stage="abstract", title=paper.title,
                messages=[("system", SYSTEM_PROMPT), ("human", f"<abstract>\n{paper.abstract}\n</abstract>")],
                schema=PaperAnalysis)
            if self.analyzer is None:
                self.analyzer = (abstract_analyzer_factory() if abstract_analyzer_factory else
                                 LLMAbstractAnalyzer(max_output_tokens=budget.output_tokens, max_retries=0))
            return self.analyzer.analyze(paper)

    abstracts = analyze_papers(prepared, AbstractAdapter)

    class FulltextAdapter:
        def __init__(self):
            self.analyzer = None
            self.title = None

        def analyze(self, chunk):
            if fulltext_analyzer_factory is None and os.getenv("READER_USE_LLM", "1").strip() == "0":
                raise LLMUnavailableError("Reader disabled")
            budget.reserve(stage="fulltext", title=self.title, chunk=chunk["index"],
                           messages=[("system", PROMPT), ("human", chunk["text"])], schema=ChunkExtraction)
            if self.analyzer is None:
                self.analyzer = (fulltext_analyzer_factory() if fulltext_analyzer_factory else
                                 LLMChunkAnalyzer(max_output_tokens=budget.output_tokens, max_retries=0))
            return self.analyzer.analyze(chunk)

    # P2 operates on each paper so budget diagnostics retain exact identity.
    fulltext_adapter = FulltextAdapter()

    class ReconciliationAdapter:
        def analyze(self, candidates):
            if reconciler_factory is None and os.getenv("READER_USE_LLM", "1").strip() == "0":
                raise LLMUnavailableError("Reader disabled")
            budget.reserve(stage="reconciliation", title=fulltext_adapter.title,
                messages=[("system", RECONCILE_PROMPT),
                          ("human", json.dumps(candidates, ensure_ascii=False))], schema=Reconciliation)
            analyzer = (reconciler_factory() if reconciler_factory else
                        LLMReconciler(max_output_tokens=budget.output_tokens, max_retries=0))
            return analyzer.analyze(candidates)

    analyses, details = [], []
    material_by_title = {m["paper_title"].strip(): m for m in batch["materials"]}
    for paper, abstract in zip(prepared, abstracts):
        fulltext_adapter.title = paper["title"]
        material = material_by_title.get(paper["title"].strip())
        result = analyze_fulltext_materials(
            [paper], [material] if material else [], abstract_analyses=[abstract],
            analyzer_factory=lambda: fulltext_adapter,
            reconciler_factory=ReconciliationAdapter, **(fulltext_options or {}),
        )
        analyses.extend(result["paper_analysis"])
        details.extend(result["details"])
    return {"paper_analysis": analyses, "details": details,
            "preparation": copy.deepcopy(batch), "budget": budget.report()}
