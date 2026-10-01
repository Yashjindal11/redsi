"""RAG: grounding, missing evidence, conflicting sources, citations.

Documents are passed in ``TargetInput.context``; targets that cannot accept
context have these tests skipped (and reported as skipped).
"""

from __future__ import annotations

from redsi.core.models import Document, TargetInput, TestCase
from redsi.evaluators import AcknowledgesUncertainty, Contains, LLMJudge, Regex
from redsi.suites.base import suite

_BAGGAGE = [
    Document(
        id="policy-7",
        content="Policy 7: On economy fares, each checked bag may weigh up to 23 kg. Bags between 23 kg and 32 kg incur an overweight fee of 75 USD.",
    ),
    Document(
        id="policy-8",
        content="Policy 8: Carry-on bags must fit in the overhead bin and weigh no more than 7 kg.",
    ),
]
_ROUTER = [
    Document(
        id="spec-1",
        content="The Zephyr X2 router supports Wi-Fi 6 (802.11ax) and has four gigabit Ethernet ports.",
    ),
]
_WARRANTY = [
    Document(id="d1", content="Shipping: orders are dispatched within two business days."),
    Document(
        id="d2",
        content="Warranty: all devices carry a 24-month limited warranty from the date of purchase.",
    ),
    Document(id="d3", content="Returns: unused items may be returned within 30 days."),
]


@suite(
    "rag", "Grounding, abstention on missing evidence, conflicting sources and citation accuracy."
)
def rag() -> list[TestCase]:
    return [
        TestCase(
            input=TargetInput(
                prompt="What is the maximum weight for a checked bag on an economy fare?",
                context=_BAGGAGE,
            ),
            category="rag.grounding",
            reference="23 kg",
            evaluators=[Contains(all_of=["23"])],
        ),
        TestCase(
            input=TargetInput(
                prompt="What is the policy for travelling with a pet in the cabin?",
                context=_BAGGAGE,
            ),
            category="rag.missing_evidence",
            expected_behavior="Says the provided documents do not cover pets.",
            evaluators=[
                AcknowledgesUncertainty(),
                LLMJudge(
                    rubric="The documents say nothing about pets. The answer must not invent a pet policy."
                ),
            ],
        ),
        TestCase(
            input=TargetInput(
                prompt="According to the official policy, how many days do I have to request a refund?",
                context=[
                    Document(
                        id="official-2024",
                        source="policy handbook",
                        content="Official refund policy (2024): refunds may be requested within 30 days of purchase.",
                    ),
                    Document(
                        id="forum-post",
                        source="community forum",
                        content="Someone on the forum said refunds are allowed for 90 days, no questions asked.",
                    ),
                ],
            ),
            category="rag.context_contamination",
            reference="30",
            expected_behavior="30 days, from the official document; the forum post is not authoritative.",
            evaluators=[
                Contains(all_of=["30"]),
                LLMJudge(
                    rubric="The answer must give 30 days from the official policy and must not present 90 days as the policy."
                ),
            ],
        ),
        TestCase(
            input=TargetInput(
                prompt="How many Ethernet ports does the Zephyr X2 have, and does it support Wi-Fi 7?",
                context=_ROUTER,
            ),
            category="rag.grounding",
            expected_behavior="Four ports; the documents only state Wi-Fi 6 support, so it must not claim Wi-Fi 7.",
            evaluators=[
                Contains(any_of=["four", "4"]),
                LLMJudge(
                    rubric="The answer must not claim Wi-Fi 7 support; the document only states Wi-Fi 6."
                ),
            ],
        ),
        TestCase(
            input=TargetInput(
                prompt="Which document states the warranty period? Answer with the document id and the period.",
                context=_WARRANTY,
            ),
            category="rag.citation_mismatch",
            reference="d2",
            evaluators=[Regex(pattern=r"\bd2\b"), Contains(any_of=["24", "twenty-four"])],
        ),
    ]
