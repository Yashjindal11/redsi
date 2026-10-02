# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Before 1.0, minor versions may
contain breaking changes; they are listed explicitly.

## [Unreleased]

## [0.1.0] - 2026-10-02

First public milestone. Everything is new; there is nothing to migrate from.

### Added
- Core schemas: `TestCase`, `TargetInput`/`TargetOutput`, `EvaluationResult`,
  `Assessment`, `Finding`, failure taxonomy (7 domains, 40 categories) and a
  configurable severity model.
- Target adapters: Python functions, import paths, isolated subprocess
  execution, HTTP endpoints, OpenAI-compatible / Anthropic / Ollama / Gemini /
  Hugging Face chat models, replayed recordings, custom adapters.
- Model provider layer with per-task roles (generator, judges, analyst),
  retries, user-supplied pricing and a deterministic-request cache.
- Evaluators: deterministic (contains, regex, exact, numeric, JSON schema,
  length, tool-use checks), heuristics, metamorphic consistency, token overlap,
  embedding similarity, function evaluators, LLM judge with evidence
  verification; confidence-weighted aggregation and judge calibration metrics.
- Built-in suites for reliability, factuality, reasoning, robustness, RAG,
  agent behaviour and canary-based security evaluation.
- Ten semantic mutation strategies plus a random baseline, LLM test
  generation and an adaptive fuzzer that attributes failures to strategies.
- Specification-driven testing with per-requirement coverage.
- Campaign engine with waves, concurrency, budgets, retries and early stopping.
- Findings with evidence-based root-cause hypotheses; reproduction with
  flakiness tracking; regression comparison and CI gates.
- JSON, Markdown and HTML reports; `redsi` CLI (`init`, `test`, `generate`,
  `evaluate`, `reproduce`, `compare`, `report`, `inspect`, `runs`, `triage`,
  `suites`, `targets`, `config`, `serve`, `benchmark`).
- Read-only web dashboard (FastAPI + React/TypeScript) with live campaign view.
- Planted-fault benchmark (`redsi benchmark`) with recorded results.
- Twelve offline examples, documentation, CI and release workflows.

### Fixed (during development)
- Wrapped function evaluators now survive the spec round-trip.
- Unknown `/api` paths return 404 instead of the dashboard page.
- Judge prompts are deterministic, so judge calls are cacheable.
- A failing generator model no longer aborts a campaign.

### Known limitations
- Severity on specification *seed* tests uses taxonomy defaults; per-requirement
  severity applies to that requirement's probes only.
- Heuristic evaluators (clarification, uncertainty, refusal) are English-only
  and produce false positives; they never yield `confirmed` findings on their own.
- Lexical consistency checks are weak for free-text answers; configure an
  embedder or judge for semantic comparison.
- Synchronous Python targets cannot be killed on timeout in-process; use
  `isolate=True` for hard timeouts.
- Test ids for evaluators defined in `__main__` scripts include the script's
  absolute path, so such tests do not match across machines.
- The dashboard has no authentication and is intended for localhost only.
- Not yet published to PyPI.

