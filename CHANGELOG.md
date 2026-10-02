# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Before 1.0, minor versions may
contain breaking changes; they are listed explicitly.

## [Unreleased]

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
- Ten mutation strategies, LLM test generation and an adaptive fuzzer that
  attributes failures to strategies.
- Specification-driven testing with per-requirement coverage.
- Campaign engine with waves, concurrency, budgets, retries and early stopping.
- Findings with evidence-based root-cause hypotheses; reproduction with
  flakiness tracking; regression comparison and CI gates.
- JSON, Markdown and HTML reports; `redsi` CLI.
- Twelve offline examples.
