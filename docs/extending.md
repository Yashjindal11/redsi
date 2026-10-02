# Extending RedSI

Everything below works without modifying RedSI. Components defined in your
own package can be published as plugins through entry points:

```toml
[project.entry-points."redsi.evaluators"]   # also: redsi.targets, redsi.providers,
no_pii = "my_pkg.checks:NoPII"               #       redsi.suites, redsi.mutations
```

## Custom target adapter

```python
from redsi import TargetAdapter, TargetInput, TargetOutput, ToolCall

class MyAgent(TargetAdapter):
    name = "my-agent"
    # Declare what you actually use. Tests needing more are skipped and reported.
    capabilities = frozenset({"text", "system", "history", "context", "tools"})
    timeout = 30

    async def run(self, input: TargetInput) -> TargetOutput:
        result = await my_client.chat(input.prompt, system=input.system, docs=input.context)
        return TargetOutput(
            text=result.answer,
            tool_calls=[ToolCall(name=c.name, arguments=c.args, error=c.error) for c in result.calls],
            retrieved=[...],          # enables retrieval_failure hypotheses
            trace=result.steps,       # shown in the dashboard
            usage=...,                # token/cost tracking
        )
```

For CLI use, export it from a file as `redsi_target = MyAgent()` and run
`redsi test my_agent.py`.

Plain functions are usually enough:

```python
def answer(prompt: str) -> str: ...                       # text only
def rag(prompt: str, context: list) -> dict: ...          # + context capability
def full(input: TargetInput) -> TargetOutput: ...         # everything
Target.from_function(answer)                              # in-process
Target.from_import("my_agent.py:answer", isolate=True)    # killable subprocess
Target.from_http("https://...", body={"q": "{{prompt}}"}, response_path="data.answer",
                 headers={"Authorization": "Bearer ${MY_API_KEY}"})
Target.from_openai("gpt-4o-mini", system="...")           # bare model
```

## Custom evaluator

```python
from redsi.evaluators import OutputEvaluator, register

@register("max_sentences")
class MaxSentences(OutputEvaluator):
    limit: int = 3                       # pydantic fields = serialisable params

    def check(self, case, output):
        n = output.text.count(".")
        return self.passed() if n <= self.limit else self.failed(f"{n} sentences > {self.limit}")
```

* Heuristics: set `deterministic = False` and pass a modest `confidence=`.
* Need all samples or other tests' outputs? Subclass `Evaluator` and implement
  `async evaluate(case, outputs, ctx)`; `ctx.outputs_by_case`, `ctx.models`
  and `ctx.embedder` are available. You may return a list (one result per voter).
* Quick checks: `FunctionEvaluator.wrap(fn)` with `fn(input, output) -> bool |
  float | (bool, reason)`. Module-level functions stay reproducible.
* In YAML/JSON tests: `{"type": "max_sentences", "params": {"limit": 2}}`.

Always add a false-positive test next to the true-positive one.

## Custom mutation strategy

```python
from redsi.generators import Mutation, derive, register_mutation

@register_mutation
class Politeness(Mutation):
    name = "politeness"

    async def mutate(self, seed, rng, models=None):
        prompt = f"{rng.choice(['Pretty please', 'Kindly'])}, {seed.input.prompt}"
        return derive(seed, self.name, prompt=prompt)   # keep_answer=True by default
```

`derive` copies lineage, keeps the seed's deterministic checks, and adds a
metamorphic consistency check if the seed had none. For behaviour-changing
mutations pass `keep_answer=False, evaluators=[...]`. Strategies must be
deterministic given `rng`.

## Custom suite

```python
from redsi.suites import suite
from redsi import TestCase

@suite("billing", "Billing assistant regressions")
def billing() -> list[TestCase]:
    return [TestCase(input="...", category="factuality.calculation", reference="42",
                     evaluators=[{"type": "numeric_answer"}])]
```

Or a file (`redsi test --tests billing.yaml`):

```yaml
- input: "What is 6 * 7?"
  category: reasoning.arithmetic
  reference: "42"
  evaluators: [{type: numeric_answer}]
```

## Custom provider

Subclass `ModelProvider` (`async complete(ChatRequest) -> ChatResponse`) and
register a factory: `providers.register("my_llm", lambda **kw: MyProvider(**kw))`.
Then `"my_llm:model-name"` works anywhere a model is accepted. Never return
secrets from `describe()`.

## Custom taxonomy categories

```python
from redsi.core import Category, Severity, register_category
register_category(Category("domain.billing_error", "Wrong invoice amount.", Severity.HIGH,
                           "Validate totals against the ledger."))
```
