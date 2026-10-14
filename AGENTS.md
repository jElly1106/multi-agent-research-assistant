# Repository Guidance for Codex

## Scope and safety

- Start every change by checking `git branch --show-current` and `git status --short`.
- Do not make changes directly on `main`. Use the task branch agreed by the team.
- Keep changes narrowly scoped to the assigned member's responsibility. Do not change shared contracts (`INTERFACES.md`, `research_assistant/schemas.py`, `research_assistant/state.py`, or `research_assistant/graph.py`) without explicit team approval.
- Do not commit, push, install dependencies, or change environment files unless the task explicitly requests it.
- Never put API keys, local `.env` values, downloaded papers, or generated cache data under version control.

## Current architecture contract

- All graph nodes use `node(state: ResearchState) -> dict` and return only the fields they own.
- Cross-agent values must be JSON serializable. `ResearchState` currently carries dictionaries/lists at runtime; Pydantic models in `research_assistant/schemas.py` define the agreed shapes.
- The current graph is `Coordinator -> Search -> Reader -> Analyst -> Critic -> Writer`, with a Critic `FAIL` loop back to Search. See `INTERFACES.md` and `research_assistant/graph.py` before changing an agent.
- The only production agent currently present is Coordinator. The nodes in `research_assistant/demo_stubs.py` are demonstration-only and must not be represented as real research results.

## Reader Agent rules

- Reader owns only `paper_analysis`; it reads `papers` and returns `{"paper_analysis": [...]}`.
- Preserve the existing `Paper` and `PaperAnalysis` field names until a shared-contract change is approved.
- A feedback-loop run receives the complete, deduplicated `papers` list from Search. Reader must therefore return a complete replacement analysis for the current input, not an undocumented incremental update.
- Do not claim information that is absent from the available source. In the P0 abstract-only phase, unavailable values must use the agreed conservative fallback rather than invented content.
- Before adding network retrieval, PDF parsing, caching, or concurrency, follow the staged plan in `docs/reader-agent-design.md` and resolve its open team decisions.

## Verification and documentation

- Add or update tests together with implementation work. Keep test fixtures clearly synthetic and label them as such.
- Run only the checks supported by the installed environment, and report checks that could not be run rather than assuming success.
- Update the relevant engineering document when implementation changes an agreed behavior. Keep planned work distinct from implemented work.
