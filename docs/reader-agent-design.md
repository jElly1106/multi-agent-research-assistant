# Reader Agent Design

Current delivery state and acceptance limits: [reader-status.md](reader-status.md).
The dated records below retain earlier development context.

## Status and scope

This document is a development plan with a P0 implementation record. The production
P0 Reader is `research_assistant.agents.reader.reader_node`; `demo_reader_node`
remains a graph demonstration stub only.

2026-10-17: P0 independent development and P1 local PDF preparation are complete
under synthetic offline acceptance. See [Reader delivery record](reader-delivery.md)
for configuration, local PDF API, validation results and pending real-data checks.

Independent orchestration is now available as run_reader in reader_pipeline.py:
local preparation, abstract fallback, full-text merge and batch admission budgets.
See [pipeline and token-budget semantics](reader-pipeline.md). The default graph
node remains unchanged. Exact model tokenizer configuration and provider usage
validation remain separate from synthetic acceptance.

The core independent implementation is now ready for real-data acceptance within
the documented abstract/local-text-PDF/arXiv scope. The full-text node factory is
`research_assistant.reader_node.create_fulltext_reader_node`; default graph wiring
is unchanged. See [independent acceptance preparation](reader-acceptance.md).
High-end performance work is not part of this completion scope.

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
- Before creating an analyzer, Reader validates the entire input list. Blank
  titles are skipped with a warning. Titles are compared after stripping outer
  whitespace, case-sensitively; all other validated Paper fields must match.
  Identical duplicates are analyzed once in first-occurrence order, retaining
  the first original title. Conflicting records raise ValueError before any
  model call. No input records are modified.
- The prompt asks for input modalities, fusion mechanism and backbone in the
  existing method string only when supported by the abstract. Unknown details
  remain absent; no new schema fields are introduced.

P0 implementation checklist (code and synthetic tests are present; live quality acceptance is pending):

- Add a production Reader node without changing shared Schema, State, Graph, or other agents.
- Validate each incoming paper against the existing `Paper` shape and produce one `PaperAnalysis`-shaped result for each usable paper.
- Extract only claims supportable by the provided abstract; restore the title from input in code.
- Use conservative values for missing information: empty strings for required text fields and empty lists for list fields are schema-valid; do not invent datasets, metrics, results, contributions, or limitations.
- Return the full analysis list, including on post-Critic re-runs.
- Add tests for an empty paper list, one valid abstract, multiple papers, missing/empty abstracts, malformed records, and complete replacement after a changed input list.

P0 does not download papers, parse PDFs, perform long-context processing, or claim full-text coverage. The current implementation uses an LLM with conservative empty fallbacks. Runtime validation establishes schema correctness, not factual grounding of generated claims.

## Analyst compatibility review

See [Reader–Analyst integration review](reader-analyst-integration.md) for the
2026-10-17 review against main commit `4939019abe2a032ae63633b5d8bc8cdba3eed33f`.
The shared schemas, state and graph are unchanged between the reviewed branches.
Field shapes are compatible. Reader title validation and conflict rejection are
implemented; upstream metadata validity, shared model configuration and
production-to-production integration tests still need attention.
The Analyst implementation is present on the reviewed main, not yet merged into
this Reader branch. The existing Reader integration test uses a synthetic Analyst
function and does not establish compatibility with member 4's implementation.

### P1 — Full-text acquisition and preparation

Planned deliverables after team agreement:

- Obtain permitted full text from an agreed source and record acquisition failures.
- Download and parse PDFs or other agreed full-text formats.
- Normalize text and split long documents while retaining page/section provenance where technically available.
- Establish limits for file size, timeout, supported format, retry behavior, and cleanup.

P1 local-file preparation is implemented in `research_assistant/reader_pdf.py`.
The initial source for this increment was local PDF only; status/pages/chunks/issues
are internal material, not shared state. On 2026-10-18 the user confirmed Reader's
original acquisition responsibility. Opt-in arXiv official PDF downloads and
temporary paper-to-file mapping are now implemented; see [download policy](reader-download.md).
Other network sources and section-level provenance remain unimplemented. The local
failure contract and limits are documented in the delivery record.

P1 continuation implements explicit title-to-local-path batch mapping with full
replacement output, sequential spawned workers and a per-file hard deadline.
Text and chunk limits fail the entire document without truncation. These APIs
remain Reader-internal and do not write shared state or extract PaperAnalysis.
See the delivery record for failure semantics and Windows entry-point usage.

### P2 — Full-text structured extraction and merge

Planned deliverables after P1:

- Extract the current `PaperAnalysis` fields from full text, with evidence-aware aggregation across chunks.
- Define how full-text findings supersede or complement P0 abstract findings without changing shared output fields implicitly.
- Preserve a deterministic one-result-per-paper output and handle partial-text failures conservatively.

P2 has an opt-in independent implementation in research_assistant/reader_fulltext.py.
It validates P1 chunk provenance, extracts quote-bearing claims and deterministically
merges values into the existing PaperAnalysis. Missing/full-text failures preserve
supplied abstract fields. Internal evidence and status stay outside shared state.
See [P2 full-text extraction](reader-fulltext.md) for merge policy and character
budgets. The default graph node remains abstract-only; token-specific budgeting,
real-model quality acceptance remain pending. Optional source-constrained semantic
coordination is now implemented via reconcile=True, including abstention and
budgeted fallback; see reader-fulltext.md. Default source-order merging is unchanged.

### P3 — Performance and reliability

Optional work, subject to schedule:

- Add cache keys and invalidation rules.
- Add bounded concurrency for retrieval and parsing.
- Add observability, rate limiting, retry/backoff, and performance tests.

2026-10-18: P3 now includes opt-in bounded PDF preparation concurrency (1–4
workers), an explicitly owned bounded in-memory PDF material cache, and a
standalone CLI. See [standalone usage and reliability](reader-standalone.md).
Model-response caching, network rate limiting/backoff and measured throughput
benchmarks remain unimplemented. Reader owns acquisition for already discovered
papers under the user-confirmed original division; it does not repeat Search's discovery.

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
3. **Full-text acquisition:** The user confirmed Reader ownership on 2026-10-18.
   The current opt-in increment supports official arXiv PDFs with bounded,
   sequential acquisition and temporary files, as documented in reader-download.md.
   Other providers, credentials and persistent full-text storage remain undecided.
4. **Failure and degradation:** Should malformed papers be skipped, receive an empty analysis, or yield structured per-paper error information? The current `PaperAnalysis` schema has no status/error/evidence fields, while the global `errors` field is not Reader-owned in `INTERFACES.md`.
5. **Model policy:** P0 currently uses the shared environment variable names through its own LLM constructor. Main now has a Coordinator/Analyst model factory; Reader alignment remains planned (see integration review). Token/cost/rate limits remain unspecified.
6. **Evidence traceability:** Are title-only links sufficient for Analyst/Critic/Writer, or should a future shared schema add stable IDs and source spans/page references?
7. **Reprocessing policy:** Reader always returns the complete current list and
   recomputes analyses. Only PDF preparation has an explicitly owned, bounded
   content-keyed memory cache. Reuse of model analyses remains unimplemented.

## Non-goals for the current documentation task

The independent Reader increment does not modify shared interfaces, environment
files or the demo wiring in `main.py`. It adds Reader-local configuration support,
PDF preparation and an optional dependency. Cross-agent integration remains pending.
