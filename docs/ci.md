# Regression testing in CI

A typical setup keeps a baseline artifact on the main branch and fails pull
requests that regress.

```yaml
# .github/workflows/redsi.yml (in *your* project)
name: RedSI
on: [pull_request]
jobs:
  redsi:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install "redsi @ git+https://github.com/Yashjindal11/redsi@v0.1.0"
      - name: Evaluate
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}   # only if you use model judges/targets
        run: |
          redsi test --mode standard --seed 0 \
            --baseline evals/baseline.json \
            --max-regressions 0 --max-critical 0 --min-pass-rate 0.85 \
            --report redsi-report.md
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: redsi
          path: |
            redsi-report.md
            .redsi/runs/
```

Refresh the baseline deliberately (e.g. after a release):

```bash
redsi test --mode standard --seed 0 --out evals/baseline.json
git add evals/baseline.json
```

## Making comparisons meaningful

* **Fix the seed.** Generated test ids are content hashes; the same seed
  regenerates the same tests, so runs compare test-by-test.
* **Keep RedSI pinned.** Built-in suites may change between versions;
  `compare` warns when runs were produced by different versions.
* **Watch `shared`.** A comparison only says something about tests both runs
  executed. Added/removed tests are reported separately.
* **Sampling noise.** For non-deterministic targets use `--samples 3` and
  reproduce suspected regressions (`redsi reproduce`) before acting on them.

## What the gate checks

`GateConfig` (in `redsi.yaml` under `gate:` or via flags):

| Field | Default | Meaning |
|---|---|---|
| `max_critical` | 0 | Confirmed/likely critical findings allowed |
| `max_high` | none | Confirmed/likely high findings allowed |
| `min_pass_rate` | none | Minimum pass rate (uncertain counts as not passed) |
| `max_regressions` | 0 | Tests that went pass → fail vs. baseline |
| `max_new_failures` | none | Failing tests not failing (or absent) in the baseline |
| `count_statuses` | confirmed, likely | Which finding statuses count toward severity limits |
