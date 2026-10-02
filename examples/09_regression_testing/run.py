"""Example 9 - regression testing between two versions of a system.

Version 2 fixes one bug and introduces another. ``compare`` tells them
apart; the gate decides whether CI should fail. The CLI equivalent is::

    redsi test v1.py:bot --out baseline.json
    redsi test v2.py:bot --baseline baseline.json   # exits 1 on regression

    python examples/09_regression_testing/run.py
"""

import asyncio

from redsi import RedSI, Target
from redsi.regression import GateConfig, compare, evaluate_gate


def bot_v1(prompt: str) -> str:
    p = prompt.lower()
    if "capital" in p and "australia" in p:
        return "Sydney."  # v1 bug
    if "capit" in p and ("france" in p or "frnace" in p):
        return "Paris."
    if "15 + 27" in p:
        return "42"
    if "boil" in p:
        return "100 degrees Celsius."
    return "Could you clarify what you mean?"


def bot_v2(prompt: str) -> str:
    p = prompt.lower()
    if "capital" in p and "australia" in p:
        return "Canberra."  # fixed
    if "wat is teh" in p:
        return "I don't understand."  # new: stricter input parsing breaks noisy inputs
    return bot_v1(prompt)


async def main() -> None:
    v1 = await RedSI(Target.from_function(bot_v1, name="bot"), store=None).run(
        ["robustness"], mode="quick"
    )
    v2 = await RedSI(Target.from_function(bot_v2, name="bot"), store=None).run(
        ["robustness"], mode="quick"
    )
    cmp = compare(v1, v2)
    print(f"pass rate {cmp.pass_rate_before:.0%} -> {cmp.pass_rate_after:.0%}")
    for c in cmp.regressions:
        print(f"  REGRESSION {c.category}: {c.prompt}")
    for c in cmp.resolved:
        print(f"  resolved   {c.category}: {c.prompt}")
    gate = evaluate_gate(v2, GateConfig(max_regressions=0), cmp)
    print("gate:", "passed" if gate.passed else f"FAILED - {gate.violations}")


if __name__ == "__main__":
    asyncio.run(main())
