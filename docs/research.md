# Research layer

RedSI is usable without any of this. This page describes how the framework
supports *measuring* failure-discovery methods, and what has and has not been
measured so far.

## Why a planted-fault benchmark

On a real system the set of failures is unknown, so "method A found more
failures than method B" cannot be checked for false positives or missed
faults. `redsi benchmark` uses a synthetic target
([`redsi.benchmark.target`](../src/redsi/benchmark/target.py)) with eight
planted faults. When a fault fires, the target records it in the output
metadata and corrupts its answer, which gives ground truth for:

| Metric | Definition |
|---|---|
| Faults discovered | Planted faults that at least one *failing* test triggered |
| Precision | Failing tests in which some fault actually fired (the rest are evaluator false positives) |
| Detection recall | Tests in which a fault fired that were flagged as failing |
| Tests to discovery | Position of the first failing test that exposed each fault |

The faults are modelled on documented LLM-application failure modes (typo
sensitivity, distractors, long inputs, role-play leakage, false premises,
boundary values, ambiguity, casing). They are deliberately simple and
rule-triggered.

## Protocol

```bash
redsi benchmark --repeats 5 --budget 120 --out benchmarks/results/planted-faults.md
# with real models, also runs llm_generation:
redsi benchmark --generator openai:gpt-4o-mini --judge openai:gpt-4o-mini
```

* All methods use the same target, the same eight hand-written seed tests and
  the same test budget. Fuzzing methods keep generating rounds until the budget
  is reached; the static method has a fixed size.
* Each method is repeated with seeds `0..repeats-1`; results report mean and
  standard deviation. Everything offline is deterministic given the seed.
* Methods: `static` (seeds only), `random_fuzz` (semantics-free character
  edits), `mutation_fuzz` (the ten semantic strategies, uniform sampling),
  `adaptive_fuzz` (same strategies, reweighted toward productive ones between
  rounds), `spec_driven` (specification seeds/probes plus adaptive fuzzing),
  `llm_generation` (model-written tests, only when models are configured).

## Results so far (RedSI 0.1.0, synthetic target only)

The full output is in [benchmarks/results/planted-faults.md](../benchmarks/results/planted-faults.md)
(JSON alongside). Summary of that run (5 repeats, budget 120):

| Method | Faults found / 8 | Precision | Detection recall |
|---|---|---|---|
| static | 1.0 | 100% | 100% |
| random_fuzz | 3.0 | 86% | 65% |
| mutation_fuzz | 6.6 ± 0.5 | 87% | 86% |
| adaptive_fuzz | 6.6 ± 0.5 | 89% | 87% |
| spec_driven | 6.0 | 88% | 80% |
| llm_generation | not run (no model configured) | | |

What this does and does not show:

* Semantic mutation strategies found far more planted faults than the static
  seed set or random character edits **on this target**.
* Random edits were the only method to find `F8-shouting` (all-caps input):
  none of the semantic strategies upper-cases text. Coverage of the mutation
  space matters, and a "smarter" method is not uniformly better.
* Adaptive reweighting did **not** beat uniform sampling here. With eight
  seeds and a 120-test budget there is little room for adaptation to pay off;
  whether it helps on larger, real targets is an open question.
* About 11-14% of failing tests were false positives with respect to the
  planted faults, mostly heuristic evaluators (e.g. "asks for clarification")
  flagging acceptable answers. This is why heuristic-only failures are never
  reported as `confirmed`.
* None of this says anything about real models. The faults are rule-based
  and the target is tiny.

## Open research questions

These are questions the architecture is designed to support. No results are
claimed for them.

1. **Test generation.** Does LLM-generated or specification-driven testing
   discover failures that static suites miss, per unit cost?
2. **Fuzzing.** Which mutation strategies yield the most *unique* failures on
   real systems, and does adaptive allocation help at realistic budgets?
   (`artifact.fuzz["strategies"]` records per-strategy yield for every run.)
3. **Judge reliability.** How well do LLM judges agree with each other and
   with human labels? `redsi.evaluators.calibration` computes agreement, Cohen's
   kappa and precision/recall against human triage (`redsi triage`).
4. **Coverage.** Does evaluation coverage (taxonomy, requirements, strategies)
   correlate with failure discovery?
5. **Reproducibility.** How often do LLM failures reproduce?
   `redsi reproduce` records attempts/failures and flakiness per finding.
6. **Model diversity.** Do different judge or generator models surface
   different failure classes? (`ModelRoles` lets each role use a different model.)
7. **Regression.** Does test-level comparison catch regressions earlier than
   aggregate metrics?

## Extending the benchmark

* Add a fault: give it an id and category in `FAULTS`, a trigger in
  `PlantedFaultTarget.run`, record it with `fire(...)`, and add a trigger test
  in `tests/test_benchmark.py`.
* Add a method: add an entry to the `plan` in `run_benchmark` that returns
  seed cases and a fuzz configuration.
* A benchmark over *real* systems needs human-labelled ground truth; the
  calibration utilities and `redsi triage` are the intended building blocks.
