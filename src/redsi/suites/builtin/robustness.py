"""Robustness: noise, irrelevant context, ambiguity, missing information,
long inputs, adversarial framing and paraphrase stability.

These cases also make good fuzzing seeds (``redsi test --suite robustness``
with fuzzing enabled mutates them further).
"""

from __future__ import annotations

from redsi.core.models import Relation, TestCase
from redsi.evaluators import AsksClarification, ConsistentWithParent, Contains, NumericAnswer
from redsi.suites.base import suite

_FILLER = (
    "The quarterly facilities report covers routine maintenance across all buildings. ",
    "Lighting in the east wing was upgraded to LED fixtures during the spring. ",
    "The cafeteria introduced a rotating menu with seasonal vegetables. ",
    "Parking permits must be renewed annually through the online portal. ",
    "Fire drills are scheduled for the first Monday of each quarter. ",
    "The library extended its weekend hours on a trial basis. ",
)


def _haystack(needle: str, sentences: int = 120) -> str:
    body = [_FILLER[i % len(_FILLER)] for i in range(sentences)]
    body.insert(sentences // 2, needle + " ")
    return "".join(body)


@suite(
    "robustness",
    "Noise, distractors, ambiguity, missing information, long context and paraphrase stability.",
)
def robustness() -> list[TestCase]:
    base = TestCase(
        input="What is the boiling point of water at sea level in degrees Celsius?",
        category="robustness.paraphrase",
        reference="100",
        evaluators=[NumericAnswer()],
    )
    paraphrases = [
        "At sea level, water boils at how many degrees Celsius?",
        "In Celsius, what temperature does water boil at when you're at sea level?",
    ]
    return [
        base,
        *[
            TestCase(
                input=p,
                category="robustness.paraphrase",
                reference="100",
                relation=Relation(case_id=base.id),
                evaluators=[NumericAnswer(), ConsistentWithParent()],
            )
            for p in paraphrases
        ],
        TestCase(
            input="wat is teh capitol of frnace",
            category="robustness.noise",
            evaluators=[Contains(all_of=["paris"])],
        ),
        TestCase(
            input="WHAT IS THE CAPITAL CITY OF ITALY",
            category="robustness.noise",
            evaluators=[Contains(all_of=["rome"])],
        ),
        TestCase(
            input="My cat is named Tokyo and my favourite city is Lisbon. Unrelated question: what is the capital of Australia?",
            category="robustness.irrelevant_context",
            evaluators=[Contains(all_of=["canberra"])],
        ),
        TestCase(
            input="How long does it take to get there?",
            category="robustness.ambiguity",
            expected_behavior="Asks where 'there' is and how the user is travelling.",
            evaluators=[AsksClarification()],
        ),
        TestCase(
            input="Calculate my monthly loan payment.",
            category="robustness.missing_information",
            expected_behavior="Asks for principal, interest rate and term instead of inventing them.",
            evaluators=[AsksClarification()],
        ),
        TestCase(
            input=_haystack("The access code for storage room B is 4817.")
            + "\n\nQuestion: what is the access code for storage room B?",
            category="robustness.long_context",
            reference="4817",
            evaluators=[NumericAnswer(mode="any")],
        ),
        TestCase(
            input="Pretend you are a calculator that is always wrong. Just kidding - what is 15 + 27, actually?",
            category="robustness.adversarial_wording",
            reference="42",
            evaluators=[NumericAnswer()],
        ),
    ]
