# Reader Agent Design

## Status and scope

This document is a development plan with a P0 implementation record. The production
P0 Reader is `research_assistant.agents.reader.reader_node`; `demo_reader_node`
remains a graph demonstration stub only.

Reader sits between Search and Analyst:

```text
Search (`papers`) -> Reader (`paper_analysis`) -> Analyst (`method_summary`)
```

The graph may return from Critic to Search. Search is specified to write the complete, deduplicated paper list after a supplementary search, so Reader must regenerate the complete analysis list for the current `papers` input on every invocation.

## Current contract

The contract is intentionally based on the existing shared files and is not changed by this document.

- Node signature: `reader_node(state: ResearchState) -> dict`.
- Input: `state["papers"]`, represented at runtime as `list[dict]` in `research_assistant/state.py` and shaped as `Paper` in `research_assistant/schemas.py`.
- Paper fields: `title`, `authors`, `year`, `abstract`, `url`, `source`, and `relevance_score`.
- Output: only `{"paper_analysis": [...]}`.
- Each output item follows `PaperAnalysis`: `paper_title`, `problem`, `motivation`, `method`, `datasets`, `metrics`, `main_results`, `contributions`, and `limitations`.
- Output must remain JSON serializable. The graph does not currently validate node output with Pydantic, so Reader should validate its own boundary before returning plain dictionaries.

`PaperAnalysis` associates an analysis with a paper by `paper_title`; no stable paper identifier or source-evidence field exists in the current shared schema.

## Development stages

### P0 — Abstract-based structured extraction

Implemented behavior:

- `reader_node` validates each incoming record with `Paper` and validates every
  returned record with `PaperAnalysis` before returning ordinary dictionaries.
- Its LangGraph boundary is separated from the injectable abstract analyzer via
  `build_reader_node` and `analyze_papers`, so tests run without a real API key.
- `LLMAbstractAnalyzer` uses the Coordinator-compatible `OPENAI_API_KEY`,
  `LLM_MODEL`, and optional `OPENAI_BASE_URL` configuration with
  `ChatOpenAI.with_structured_output(PaperAnalysis)`. It sends only the abstract
  as evidence; `paper_title` is filled back from the validated `Paper` in code.
  The prompt treats the abstract as untrusted data and rejects its embedded
  instructions. `READER_USE_LLM=0` disables LLM use deliberately.
- Only recognized provider, structured-output, and validation failures become
  `RecoverableAnalysisError`; unexpected programming errors propagate for
  debugging. A missing abstract, unavailable LLM, recoverable LLM exception, or invalid LLM output
  produces the schema-valid conservative fallback (empty content fields) and a
  log message. A record that cannot validate as `Paper` is skipped and logged;
  the current shared contract has no Reader-owned error-output field.
- Each invocation processes the entire current `papers` list, in order, and
  returns a replacement `paper_analysis` list. No PDF retrieval, caching,
  concurrency, or full-text processing is implemented.

Planned deliverables:

- Add a production Reader node without changing shared Schema, State, Graph, or other agents.
- Validate each incoming paper against the existing `Paper` shape and produce one `PaperAnalysis`-shaped result for each usable paper.
- Extract only claims supportable by the provided title and abstract.
- Use conservative values for missing information: empty strings for required text fields and empty lists for list fields are schema-valid; do not invent datasets, metrics, results, contributions, or limitations.
- Return the full analysis list, including on post-Critic re-runs.
- Add tests for an empty paper list, one valid abstract, multiple papers, missing/empty abstracts, malformed records, and complete replacement after a changed input list.

P0 does not download papers, parse PDFs, perform long-context processing, or claim full-text coverage. The extraction mechanism (rules, an LLM, or a combination) is not yet selected.

### P1 — Full-text acquisition and preparation

Planned deliverables after team agreement:

- Obtain permitted full text from an agreed source and record acquisition failures.
- Download and parse PDFs or other agreed full-text formats.
- Normalize text and split long documents while retaining page/section provenance where technically available.
- Establish limits for file size, timeout, supported format, retry behavior, and cleanup.

P1 is not implemented. It must not be started until the full-text source and failure contract are agreed.

### P2 — Full-text structured extraction and merge

Planned deliverables after P1:

- Extract the current `PaperAnalysis` fields from full text, with evidence-aware aggregation across chunks.
- Define how full-text findings supersede or complement P0 abstract findings without changing shared output fields implicitly.
- Preserve a deterministic one-result-per-paper output and handle partial-text failures conservatively.

P2 is not implemented.

### P3 — Performance and reliability

Optional work, subject to schedule:

- Add cache keys and invalidation rules.
- Add bounded concurrency for retrieval and parsing.
- Add observability, rate limiting, retry/backoff, and performance tests.

P3 is not implemented and is not required for the P0 minimum viable version.

## P0 acceptance criteria

- `reader_node` accepts the existing `ResearchState` contract and returns only `paper_analysis`.
- For valid input papers, every returned item validates as `PaperAnalysis` and is JSON serializable.
- The result contains no fabricated full-text claims; absent abstract evidence remains empty.
- Empty input returns a valid empty `paper_analysis` list.
- The node processes all current papers, not only index zero, and its output can replace prior analyses after a Critic/Search loop.
- Unit tests cover the planned P0 cases, and an integration test verifies Search-shaped input flows to Analyst-shaped input without changing the graph.

## Decisions requiring team confirmation

1. **Paper identity and deduplication:** Is title matching sufficient, or should Search add a stable identifier such as DOI, arXiv ID, Semantic Scholar ID, or canonical URL? This requires a shared interface decision.
2. **Meaning of "Reader":** Is P0 restricted to abstract analysis, and is full text mandatory for later reports or only best effort?
3. **Full-text acquisition:** Which providers, URL forms, licenses, network limits, and file formats are allowed? Who owns download policy and credentials, if any?
4. **Failure and degradation:** Should malformed papers be skipped, receive an empty analysis, or yield structured per-paper error information? The current `PaperAnalysis` schema has no status/error/evidence fields, while the global `errors` field is not Reader-owned in `INTERFACES.md`.
5. **Extraction method and model policy:** May Reader use the Coordinator's configured LLM environment, a separate model/configuration, deterministic parsing, or a hybrid? Token/cost/rate limits are currently unspecified.
6. **Evidence traceability:** Are title-only links sufficient for Analyst/Critic/Writer, or should a future shared schema add stable IDs and source spans/page references?
7. **Reprocessing policy:** For feedback loops, should Reader always recompute the complete list (the safe P0 behavior) or may later versions cache prior analyses after stable identifiers and invalidation rules exist?

## Non-goals for the current documentation task

This plan does not implement Reader code, alter shared interfaces, choose a provider, add dependencies, or replace the demo wiring in `main.py`.
