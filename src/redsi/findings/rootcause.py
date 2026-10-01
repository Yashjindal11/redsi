"""Evidence-based root-cause *hypotheses*.

Each rule fires only when the trace contains concrete evidence, and every
hypothesis carries that evidence. Hypotheses are inferences, reported
separately from observed behaviour. When nothing fires, the answer is
``unknown`` - which is the honest default.
"""

from __future__ import annotations

from redsi.core.models import CaseRecord, Hypothesis, RootCause, Verdict
from redsi.evaluators.text import normalize


def analyze(
    record: CaseRecord, records_by_id: dict[str, CaseRecord] | None = None
) -> list[Hypothesis]:
    case = record.case
    outputs = record.outputs
    hyps: list[Hypothesis] = []

    if outputs and all(not o.ok for o in outputs):
        err = outputs[0].error or ""
        hyps.append(
            Hypothesis(
                cause=RootCause.WORKFLOW_ISSUE,
                likelihood="medium",
                evidence=[f"every call errored: {err[:200]}"],
            )
        )
        return hyps

    out = next((o for o in outputs if o.ok), None)
    if out is not None:
        failed_tools = [c for c in out.tool_calls if c.error]
        if failed_tools:
            hyps.append(
                Hypothesis(
                    cause=RootCause.TOOL_FAILURE,
                    likelihood="medium",
                    evidence=[
                        f"tool {c.name!r} returned error: {c.error}" for c in failed_tools[:3]
                    ],
                )
            )
        if case.reference and (out.retrieved or case.input.context):
            ref = normalize(case.reference)
            if out.retrieved:
                retrieved = normalize(" ".join(d.content for d in out.retrieved))
                if ref and ref not in retrieved:
                    hyps.append(
                        Hypothesis(
                            cause=RootCause.RETRIEVAL_FAILURE,
                            likelihood="medium",
                            evidence=[
                                f"reference answer {case.reference!r} does not occur in the "
                                f"{len(out.retrieved)} retrieved document(s)"
                            ],
                        )
                    )
                elif ref:
                    hyps.append(
                        Hypothesis(
                            cause=RootCause.CONTEXT_FAILURE,
                            likelihood="low",
                            evidence=["reference answer was retrieved but the answer still failed"],
                        )
                    )

    channel = case.metadata.get("injection_channel")
    if record.verdict == Verdict.FAIL and channel:
        hyps.append(
            Hypothesis(
                cause=RootCause.PROMPT_WEAKNESS,
                likelihood="low",
                evidence=[f"system acted on instructions placed in the {channel} channel"],
            )
        )

    if record.assessment.disagreement:
        hyps.append(
            Hypothesis(
                cause=RootCause.EVALUATION_ERROR,
                likelihood="low",
                evidence=["evaluators disagreed on this test; the failure may be a false positive"],
            )
        )

    if case.relation and records_by_id:
        parent = records_by_id.get(case.relation.case_id)
        if parent is not None and parent.verdict == Verdict.PASS and case.origin:
            chain = " -> ".join(case.origin.strategies) or "mutation"
            hyps.append(
                Hypothesis(
                    cause=RootCause.MODEL_LIMITATION,
                    likelihood="low",
                    evidence=[f"original input passed; variant produced by {chain} failed"],
                )
            )

    return hyps or [Hypothesis(cause=RootCause.UNKNOWN, likelihood="low", evidence=[])]
