"""Reliability: format, instruction following, consistency, context retention."""

from __future__ import annotations

from redsi.core.models import Message, TargetInput, TestCase
from redsi.evaluators import (
    Contains,
    ExactMatch,
    JSONSchema,
    Length,
    NumericAnswer,
    Regex,
    SelfConsistency,
)
from redsi.suites.base import suite


@suite(
    "reliability", "Output format, instruction following, self-consistency and context retention."
)
def reliability() -> list[TestCase]:
    return [
        TestCase(
            input='Return a JSON object with string keys "city" and "country" giving the location of the Eiffel Tower. Output only the JSON.',
            category="reliability.format",
            expected_behavior="Valid JSON object with string fields city and country.",
            evaluators=[
                JSONSchema(
                    json_schema={
                        "type": "object",
                        "required": ["city", "country"],
                        "properties": {"city": {"type": "string"}, "country": {"type": "string"}},
                    }
                ),
                Contains(all_of=["paris"]),
            ],
        ),
        TestCase(
            input="List exactly three primary colors of light as a JSON array of strings. Output only the JSON array.",
            category="reliability.format",
            expected_behavior="A JSON array of exactly three strings.",
            evaluators=[
                JSONSchema(
                    json_schema={
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 3,
                        "maxItems": 3,
                    }
                )
            ],
        ),
        TestCase(
            input="Answer with exactly one word: what color is a clear daytime sky?",
            category="reliability.instruction_following",
            expected_behavior="A single word, 'blue'.",
            evaluators=[Length(max_words=1), Contains(all_of=["blue"])],
        ),
        TestCase(
            input="Reply only with the word OK.",
            category="reliability.instruction_following",
            reference="OK",
            evaluators=[ExactMatch()],
        ),
        TestCase(
            input="Write the word banana in all capital letters and nothing else.",
            category="reliability.instruction_following",
            expected_behavior="Exactly 'BANANA'.",
            evaluators=[Regex(pattern=r"^\s*BANANA\s*\.?\s*$", flags="")],
        ),
        TestCase(
            input="Name the only even prime number. Answer with the number only.",
            category="reliability.inconsistency",
            reference="2",
            samples=3,
            evaluators=[NumericAnswer(), SelfConsistency()],
        ),
        TestCase(
            input="Is 91 a prime number? Answer yes or no, then give one sentence of justification.",
            category="reliability.inconsistency",
            expected_behavior="'No' (91 = 7 x 13), consistently across samples.",
            samples=3,
            evaluators=[Regex(pattern=r"^\W*no\b"), SelfConsistency()],
        ),
        TestCase(
            input=TargetInput(
                prompt="What is my booking code?",
                history=[
                    Message(
                        role="user", content="Hi, my name is Priya and my booking code is QX7-42."
                    ),
                    Message(
                        role="assistant", content="Thanks, Priya. I've noted your booking code."
                    ),
                ],
            ),
            category="reliability.context",
            expected_behavior="Recalls QX7-42 from earlier in the conversation.",
            evaluators=[Contains(all_of=["QX7-42"])],
        ),
        TestCase(
            input=TargetInput(
                prompt="What is the capital of Japan?", system="Always answer in French."
            ),
            category="reliability.instruction_following",
            expected_behavior="Answers 'Tokyo' in French.",
            evaluators=[
                Contains(any_of=["Tokyo", "Tokio"]),
                Regex(pattern=r"\b(la|le|est|capitale|du|de la)\b"),
            ],
        ),
    ]
