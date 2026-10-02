# Contributing to RedSI

Thanks for helping make AI systems fail *before* they reach production.

## Ground rules

- **Scientific honesty.** Never present an inference as an observation, never
  invent benchmark numbers, never describe evaluation coverage as safety.
  If an evaluator can be wrong, it must be able to say `uncertain`.
- **Authorised testing only.** Contributions must target systems the user owns
  or is authorised to evaluate. We do not accept features whose primary use is
  attacking third parties, stealing credentials or bypassing real-world
  security controls.
- **No secrets** in code, fixtures, examples or artifacts.

## Development setup

```bash
git clone https://github.com/Yashjindal11/redsi && cd redsi
python3.11 -m venv .venv            # 3.11+
.venv/bin/pip install -e ".[dev]"
.venv/bin/pre-commit install
scripts/check.sh                    # format check, lint, mypy --strict, tests
python scripts/run_examples.py      # every example must run offline
```

Web dashboard: see [web/README.md](web/README.md).

## Where things live

| Package | Responsibility |
|---|---|
| `redsi.core` | Schemas, taxonomy, severity, plugin registry. No other RedSI imports. |
| `redsi.targets` | Adapters for the system under test. |
| `redsi.providers` | Models RedSI itself uses (judges, generators). |
| `redsi.evaluators` | Verdicts, confidence, aggregation, calibration. |
| `redsi.generators`, `redsi.fuzzing` | Mutation strategies, LLM generation, adaptive fuzzing. |
| `redsi.spec` | Specification model and compiler. |
| `redsi.campaign` | Execution engine and run artifact. |
| `redsi.findings` | Findings and root-cause hypotheses. |
| `redsi.regression`, `redsi.reproduce`, `redsi.reporting` | Prevent / reproduce / communicate. |
| `redsi.cli`, `redsi.server` | Interfaces. The engine never imports them. |

See [docs/architecture.md](docs/architecture.md) before changing anything in
`core` or `campaign`.

## Adding things

Most contributions should not need to touch the engine:

- **Evaluator**: subclass `OutputEvaluator` (or `Evaluator`), decorate with
  `@register("name")`. Mark heuristics `deterministic = False` and give them
  modest confidence. Add tests for a true positive **and** a false-positive
  case.
- **Mutation strategy**: subclass `Mutation`, use `derive(...)`, decide whether
  the answer must be preserved (`keep_answer`). Test determinism under a seed.
- **Suite**: `@suite("name", "description")` returning `TestCase`s. Every test
  needs an evaluator; prefer deterministic expectations. No third-party
  datasets without a compatible licence and a note in the suite docstring.
- **Target / provider**: implement the interface and register a builder in
  `target_kinds` / `providers`. Never store secret values in `ref()`/`describe()`.
- **Plugins in separate packages** use entry points: `redsi.evaluators`,
  `redsi.targets`, `redsi.providers`, `redsi.suites`, `redsi.mutations`.

## Commits and pull requests

- Conventional Commits (`feat(evaluation): ...`, `fix(cli): ...`, `docs: ...`).
- One logical change per commit; keep the project working at every commit.
- Update `CHANGELOG.md` under *Unreleased* when public behaviour changes.
- Fill in the PR template, including how you tested.

## Releases

1. Move *Unreleased* entries in `CHANGELOG.md` under a new version heading.
2. Bump `src/redsi/_version.py`.
3. Commit `chore: release vX.Y.Z`, tag `vX.Y.Z`, push the tag. The release
   workflow tests, builds and publishes the GitHub release with the changelog
   section as notes.
4. Before tagging, scan for secrets: `git grep -nE "sk-|AKIA|ghp_|BEGIN .*PRIVATE KEY"`.
