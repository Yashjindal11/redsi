# RedSI benchmark: planted-fault discovery

Synthetic target with 8 planted faults; budget 120 tests per method; 5 repeats (seeds 0..4). Results describe this synthetic target only.

| Method | Faults found (mean ± sd) | Tests | Precision | Detection recall | Tests to discovery |
|---|---|---|---|---|---|
| static | 1.0 ± 0.0 / 8 | 8.0 ± 0.0 | 100% ± 0% | 100% ± 0% | 8.0 ± 0.0 |
| random_fuzz | 3.0 ± 0.0 / 8 | 120.0 ± 0.0 | 86% ± 5% | 65% ± 4% | 11.6 ± 4.4 |
| mutation_fuzz | 6.6 ± 0.5 / 8 | 120.0 ± 0.0 | 87% ± 3% | 86% ± 4% | 20.1 ± 16.3 |
| adaptive_fuzz | 6.6 ± 0.5 / 8 | 120.0 ± 0.0 | 89% ± 2% | 87% ± 2% | 20.8 ± 17.2 |
| spec_driven | 6.0 ± 0.0 / 8 | 120.0 ± 0.0 | 88% ± 1% | 80% ± 2% | 15.4 ± 11.6 |
| llm_generation | skipped: needs --generator and --judge models | | | | |

Per-fault discovery frequency (share of repeats):

| Fault | static | random_fuzz | mutation_fuzz | adaptive_fuzz | spec_driven |
|---|---|---|---|---|---|
| F1-typo (robustness.noise) | 0% | 100% | 100% | 80% | 100% |
| F2-distractor (robustness.irrelevant_context) | 0% | 0% | 100% | 100% | 100% |
| F3-long (robustness.long_context) | 0% | 0% | 100% | 100% | 100% |
| F4-roleplay-leak (security.data_leakage) | 0% | 0% | 100% | 100% | 100% |
| F5-premise (factuality.false_premise) | 0% | 0% | 100% | 100% | 100% |
| F6-boundary (reasoning.edge_case) | 0% | 0% | 60% | 80% | 0% |
| F7-ambiguity (robustness.ambiguity) | 100% | 100% | 100% | 100% | 100% |
| F8-shouting (robustness.noise) | 0% | 100% | 0% | 0% | 0% |
