"""Reasoning: arithmetic, formal logic, causal claims, edge cases."""

from __future__ import annotations

from redsi.core.models import TestCase
from redsi.evaluators import KeywordSignal, LLMJudge, NumericAnswer, Regex
from redsi.suites.base import suite


def _num(prompt: str, answer: str, category: str = "reasoning.arithmetic") -> TestCase:
    return TestCase(input=prompt, category=category, reference=answer, evaluators=[NumericAnswer()])


def _yes_no(prompt: str, answer: str, why: str) -> TestCase:
    return TestCase(
        input=f"{prompt} Answer yes or no first.",
        category="reasoning.logic",
        expected_behavior=f"'{answer}' - {why}",
        evaluators=[Regex(pattern=rf"^\W*{answer}\b")],
    )


@suite(
    "reasoning",
    "Multi-step arithmetic, syllogisms, logical fallacies, causal reasoning and edge cases.",
)
def reasoning() -> list[TestCase]:
    return [
        _num(
            "I have 3 boxes with 12 apples each and give away 7 apples. How many apples do I have left?",
            "29",
        ),
        _num("What is 1234 multiplied by 5678?", "7006652"),
        _num(
            "A shirt costs $40 after a 20% discount. What was the original price in dollars?", "50"
        ),
        _num(
            "If 5 machines make 5 widgets in 5 minutes, how many minutes do 100 machines take to make 100 widgets?",
            "5",
        ),
        TestCase(
            input="A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. How much does the ball cost?",
            category="reasoning.arithmetic",
            expected_behavior="5 cents ($0.05), not 10 cents.",
            evaluators=[Regex(pattern=r"(\$\s?0?\.05\b|\b5\s*(cents|¢)|\bfive cents\b)")],
        ),
        _num(
            "How many times does the letter r appear in the word strawberry?",
            "3",
            "reasoning.edge_case",
        ),
        _num("What is 0 divided by 5?", "0", "reasoning.edge_case"),
        TestCase(
            input="What is 5 divided by 0?",
            category="reasoning.edge_case",
            expected_behavior="Explains that division by zero is undefined.",
            evaluators=[
                KeywordSignal(
                    any_of=[
                        "undefined",
                        "not defined",
                        "cannot divide",
                        "can't divide",
                        "infinity",
                        "impossible",
                    ],
                    confidence_miss=0.6,
                )
            ],
        ),
        _yes_no(
            "All bloops are razzies and all razzies are lazzies. Are all bloops definitely lazzies?",
            "yes",
            "transitivity.",
        ),
        _yes_no(
            "Some cats are black. Some black things are cars. Can we conclude that some cats are cars?",
            "no",
            "undistributed middle.",
        ),
        _yes_no(
            "If it rains, the ground gets wet. The ground is wet. Did it necessarily rain?",
            "no",
            "affirming the consequent.",
        ),
        TestCase(
            input="Ice cream sales and drowning incidents both rise in summer. Does eating ice cream cause drowning?",
            category="reasoning.causal",
            expected_behavior="No: both are driven by a confounder (warm weather / more swimming).",
            evaluators=[
                Regex(pattern=r"^\W*no\b"),
                LLMJudge(
                    rubric="The answer must say ice cream does not cause drowning and identify a common cause such as hot weather."
                ),
            ],
        ),
    ]
