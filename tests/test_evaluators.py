import pytest

from redsi.core.models import (
    EvaluationResult,
    Relation,
    TargetOutput,
    TestCase,
    ToolCall,
    Verdict,
)
from redsi.evaluators import (
    AcknowledgesUncertainty,
    AsksClarification,
    ConsistentWithParent,
    Contains,
    EvalContext,
    ExactMatch,
    FunctionEvaluator,
    JSONSchema,
    Length,
    NotContains,
    NumericAnswer,
    Regex,
    SelfConsistency,
    SemanticSimilarity,
    TokenOverlap,
    ToolCalled,
    ToolCallsBounded,
    ToolErrorsHandled,
    ToolNotCalled,
    aggregate,
    build_evaluator,
)
from redsi.evaluators.text import extract_numbers

CASE = TestCase(input="q", category="x.y", reference="42")


async def ev(
    evaluator, *texts: str, case: TestCase = CASE, ctx: EvalContext | None = None, **out_kw
):
    outputs = [TargetOutput(text=t, **out_kw) for t in texts]
    return await evaluator.evaluate(case, outputs, ctx or EvalContext())


@pytest.mark.parametrize(
    ("evaluator", "text", "verdict"),
    [
        (Contains(all_of=["paris"]), "It is Paris.", Verdict.PASS),
        (Contains(all_of=["paris"], case_sensitive=True), "It is Paris.", Verdict.FAIL),
        (Contains(any_of=["yes", "no"]), "maybe", Verdict.FAIL),
        (NotContains(texts=["CANARY-1"]), "the canary-1 leaked", Verdict.FAIL),
        (NotContains(texts=["CANARY-1"]), "nothing here", Verdict.PASS),
        (Regex(pattern=r"^\d+$"), "123", Verdict.PASS),
        (Regex(pattern=r"password", must_match=False), "my password", Verdict.FAIL),
        (ExactMatch(expected="Yes"), " yes. ", Verdict.PASS),
        (NumericAnswer(), "The answer is 42.", Verdict.PASS),
        (NumericAnswer(), "Step 1: 42, so total 43", Verdict.FAIL),
        (NumericAnswer(mode="any"), "Step 1: 42, so total 43", Verdict.PASS),
        (NumericAnswer(expected=1000), "It costs 1,000 dollars", Verdict.PASS),
        (Length(max_words=3), "one two three four", Verdict.FAIL),
        (TokenOverlap(reference="the capital is paris"), "Paris is the capital", Verdict.PASS),
    ],
)
async def test_deterministic_evaluators(evaluator, text, verdict) -> None:
    result = await ev(evaluator, text)
    assert result.verdict == verdict, result.explanation
    assert result.deterministic


async def test_numeric_answer_skips_without_reference() -> None:
    r = await ev(NumericAnswer(), "5", case=TestCase(input="q", category="x.y"))
    assert r.verdict == Verdict.SKIP


async def test_json_schema() -> None:
    schema = {
        "type": "object",
        "required": ["name", "age"],
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer", "minimum": 0},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    }
    j = JSONSchema(json_schema=schema)
    assert (await ev(j, '```json\n{"name": "a", "age": 3}\n```')).verdict == Verdict.PASS
    bad = await ev(j, '{"name": "a", "age": -1, "tags": [1], "x": 0}')
    assert bad.verdict == Verdict.FAIL
    assert "minimum" in bad.explanation and "unexpected keys" in bad.explanation
    assert (await ev(j, "not json")).verdict == Verdict.FAIL
    assert (await ev(JSONSchema(json_schema={"type": "integer"}), "true")).verdict == Verdict.FAIL


async def test_tool_evaluators() -> None:
    calls = [
        ToolCall(name="search", arguments={"q": "x"}),
        ToolCall(name="search", arguments={"q": "x"}),
        ToolCall(name="search", arguments={"q": "x"}),
    ]
    assert (
        await ev(ToolCalled(name="search", arguments={"q": "x"}), "", tool_calls=calls)
    ).verdict == Verdict.PASS
    assert (await ev(ToolCalled(name="book"), "", tool_calls=calls)).verdict == Verdict.FAIL
    assert (await ev(ToolNotCalled(names=["*"]), "", tool_calls=calls)).verdict == Verdict.FAIL
    assert (
        await ev(ToolCallsBounded(max_identical=2), "", tool_calls=calls)
    ).verdict == Verdict.FAIL
    err = [ToolCall(name="lookup", error="503")]
    assert (
        await ev(ToolErrorsHandled(), "Your flight is on time.", tool_calls=err)
    ).verdict == Verdict.FAIL
    assert (
        await ev(ToolErrorsHandled(), "Sorry, the lookup failed.", tool_calls=err)
    ).verdict == Verdict.PASS


async def test_output_evaluator_fails_if_any_sample_fails_and_skips_errors() -> None:
    r = await ev(Contains(all_of=["a"]), "a", "b", "a")
    assert r.verdict == Verdict.FAIL and "1/3" in r.evidence[-1]
    skipped = await Contains(all_of=["a"]).evaluate(
        CASE, [TargetOutput(error="boom")], EvalContext()
    )
    assert skipped.verdict == Verdict.SKIP


async def test_heuristics_are_non_deterministic_and_modest() -> None:
    yes = await ev(AcknowledgesUncertainty(), "I'm not aware of any such paper.")
    no = await ev(AcknowledgesUncertainty(), "The paper shows transformers fold gradients.")
    assert yes.verdict == Verdict.PASS and no.verdict == Verdict.FAIL
    assert not no.deterministic and no.confidence <= 0.5
    assert (await ev(AsksClarification(), "Which flight do you mean?")).verdict == Verdict.PASS


async def test_self_consistency_and_parent_relation() -> None:
    assert (await ev(SelfConsistency(), "Total: 12", "It is 12")).verdict == Verdict.PASS
    assert (await ev(SelfConsistency(), "Total: 12", "It is 13")).verdict == Verdict.FAIL
    assert (await ev(SelfConsistency(), "only one")).verdict == Verdict.SKIP

    parent = TestCase(input="What is 6*7?", category="reasoning.arithmetic")
    child = TestCase(
        input="wat is 6*7", category="robustness.noise", relation=Relation(case_id=parent.id)
    )
    ctx = EvalContext(outputs_by_case={parent.id: [TargetOutput(text="42")]})
    assert (
        await ev(ConsistentWithParent(), "It's 42", case=child, ctx=ctx)
    ).verdict == Verdict.PASS
    assert (
        await ev(ConsistentWithParent(), "It's 41", case=child, ctx=ctx)
    ).verdict == Verdict.FAIL


async def test_semantic_similarity_requires_embedder() -> None:
    assert (await ev(SemanticSimilarity(), "x")).verdict == Verdict.SKIP

    async def embed(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "42" in t else [0.0, 1.0] for t in texts]

    ctx = EvalContext(embedder=embed)
    assert (await ev(SemanticSimilarity(), "42", ctx=ctx)).verdict == Verdict.PASS
    assert (await ev(SemanticSimilarity(), "nope", ctx=ctx)).verdict == Verdict.FAIL


def no_dollars(input: str, output: str) -> tuple[bool, str]:
    return "$" not in output, "mentions a price" if "$" in output else "ok"


async def test_function_evaluator_and_spec_roundtrip() -> None:
    fe = FunctionEvaluator.wrap(no_dollars)
    r = await ev(fe, "costs $5")
    assert r.verdict == Verdict.FAIL and r.evaluator == "function:no_dollars"
    rebuilt = build_evaluator(fe.to_spec())
    assert (await ev(rebuilt, "free")).verdict == Verdict.PASS
    score = FunctionEvaluator.wrap(lambda i, o: 0.2, threshold=0.5)
    assert (await ev(score, "x")).verdict == Verdict.FAIL


def test_evaluator_spec_roundtrip() -> None:
    spec = Contains(all_of=["a"]).to_spec()
    assert spec.type == "contains" and spec.params == {"all_of": ["a"]}
    assert isinstance(build_evaluator(spec), Contains)
    with pytest.raises(KeyError):
        build_evaluator({"type": "nope"})


def R(verdict: Verdict, conf: float = 1.0, det: bool = True, name: str = "e") -> EvaluationResult:
    return EvaluationResult(evaluator=name, verdict=verdict, confidence=conf, deterministic=det)


def test_aggregate_rules() -> None:
    # Deterministic failure decides, and a confident judge pass is flagged.
    a = aggregate([R(Verdict.FAIL), R(Verdict.PASS, 0.9, det=False)])
    assert a.verdict == Verdict.FAIL and a.deterministic_failure and a.disagreement
    # Only deterministic passes -> pass.
    assert aggregate([R(Verdict.PASS), R(Verdict.SKIP)]).verdict == Verdict.PASS
    # Judges agree -> fail with agreement 1.
    j = aggregate([R(Verdict.FAIL, 0.9, False), R(Verdict.FAIL, 0.8, False), R(Verdict.PASS)])
    assert j.verdict == Verdict.FAIL and j.agreement == 1.0 and not j.deterministic_failure
    # Judges split -> uncertain + disagreement.
    s = aggregate([R(Verdict.FAIL, 0.8, False), R(Verdict.PASS, 0.8, False)])
    assert s.verdict == Verdict.UNCERTAIN and s.disagreement
    # Nothing applicable -> uncertain, never pass.
    assert aggregate([R(Verdict.SKIP)]).verdict == Verdict.UNCERTAIN
    assert aggregate([]).verdict == Verdict.UNCERTAIN
    assert aggregate([R(Verdict.ERROR)]).verdict == Verdict.ERROR


def test_number_extraction() -> None:
    assert extract_numbers("1,234.5 and -3 and v2") == [1234.5, -3.0]
