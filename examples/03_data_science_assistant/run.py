"""Example 3 - a data-science assistant with an off-by-one median.

Shows numeric checks on computed answers and how the ``boundary`` mutation
probes edge values (empty input, zero, huge numbers).

    python examples/03_data_science_assistant/run.py
"""

import asyncio
import re
import statistics

from redsi import RedSI, Target, TestCase
from redsi.evaluators import NumericAnswer


def _numbers(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]


def assistant(prompt: str) -> str:
    nums = _numbers(prompt.split(":", 1)[-1]) if ":" in prompt else []
    p = prompt.lower()
    if not nums:
        return "Please provide the numbers you want me to analyse."
    if "median" in p:
        s = sorted(nums)
        return f"The median is {s[len(s) // 2]:g}."  # bug: wrong for even-length lists
    if "mean" in p or "average" in p:
        return f"The mean is {statistics.fmean(nums):g}."
    if "standard deviation" in p:
        return f"The sample standard deviation is {statistics.stdev(nums):.4g}."
    return "I can compute mean, median and standard deviation."


def check(prompt: str, values: list[float], fn) -> TestCase:
    return TestCase(
        input=f"{prompt}: {', '.join(f'{v:g}' for v in values)}",
        category="factuality.calculation",
        reference=f"{fn(values):.6g}",
        evaluators=[NumericAnswer(rel_tol=1e-3)],
        tags=["stats"],
    )


TESTS = [
    check("What is the mean of", [2, 4, 6, 8], statistics.fmean),
    check("What is the median of", [3, 1, 2], statistics.median),
    check("What is the median of", [4, 1, 3, 2], statistics.median),  # even length
    check("What is the sample standard deviation of", [2, 4, 4, 4, 5, 5, 7, 9], statistics.stdev),
]


async def main() -> None:
    run = await RedSI(Target.from_function(assistant), store=None).run(
        tests=TESTS, mode="custom", fuzz={"strategies": ["boundary", "noise"], "per_seed": 2}
    )
    print(f"{run.metrics.executed} tests ({len(TESTS)} seeds + fuzzed variants)")
    for f in run.findings:
        chain = " -> ".join(f.origin.strategies) if f.origin and f.origin.strategies else "seed"
        print(f"  {f.id} [{f.status.value}] via {chain}: {f.explanation[:80]}")


if __name__ == "__main__":
    asyncio.run(main())
