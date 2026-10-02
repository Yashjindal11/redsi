"""Example 6 - an aviation operations assistant over synthetic data.

No proprietary data: the schedule below is generated from a fixed seed. The
assistant has two planted bugs - it treats "15 minutes late" as late (the
spec says on time is <= 15), and it makes up a status for unknown flights.

    python examples/06_aviation_assistant/run.py
"""

import asyncio
import random
import re
from pathlib import Path

from redsi import RedSI, Target, TestCase
from redsi.evaluators import NumericAnswer

rng = random.Random(42)
ROUTES = ["ORD-DEN", "ORD-SFO", "IAH-EWR", "DEN-LAX"]
SCHEDULE = [
    {
        "flight": f"RS {100 + i}",
        "route": ROUTES[i % len(ROUTES)],
        "delay_min": rng.choice([0, 0, 5, 10, 15, 15, 20, 45, 90]),
    }
    for i in range(24)
]


def on_time(delay: int) -> bool:
    return delay <= 15  # the definition in system.yaml


def otp(rows: list[dict]) -> float:
    return 100 * sum(on_time(r["delay_min"]) for r in rows) / len(rows)


def assistant(prompt: str) -> str:
    p = prompt.lower()
    m = re.search(r"\b([a-z]{2})\s?(\d{1,4})\b", p)
    if "on-time" in p or "on time percentage" in p or "share of flights" in p:
        route = next((r for r in ROUTES if r.lower() in p), None)
        rows = [r for r in SCHEDULE if route is None or r["route"] == route]
        buggy = 100 * sum(r["delay_min"] < 15 for r in rows) / len(rows)  # bug: < instead of <=
        return f"On-time performance{' for ' + route if route else ''} was {buggy:.1f}%."
    if "most delays" in p:
        worst = max(ROUTES, key=lambda r: sum(x["delay_min"] for x in SCHEDULE if x["route"] == r))
        return f"{worst} had the most total delay minutes."
    if (m and "status" in p) or (m and "on time" in p):
        flight = f"{m.group(1).upper()} {m.group(2)}"
        row = next((r for r in SCHEDULE if r["flight"] == flight), None)
        if row is None:
            return f"Flight {flight} is on time and departing from gate B12."  # bug: invents status
        return f"Flight {flight} departed {row['delay_min']} minutes late."
    return "Could you tell me your flight number?"


# Ground-truth numeric tests computed from the same synthetic data.
TRUTH = [
    TestCase(
        input=f"What was the on-time percentage for route {route}?",
        category="factuality.calculation",
        reference=f"{otp([r for r in SCHEDULE if r['route'] == route]):.1f}",
        evaluators=[NumericAnswer(abs_tol=0.05)],
        requirements=["correct-otp"],
    )
    for route in ROUTES
]


async def main() -> None:
    spec = Path(__file__).with_name("system.yaml")
    run = await RedSI(Target.from_function(assistant), store=None).run(
        spec=spec, tests=TRUTH, mode="custom"
    )
    print(f"requirements exercised: {run.coverage.requirement_fraction:.0%}")
    for req, cell in run.coverage.requirements.items():
        print(
            f"  {req:22} executed={cell.executed} failed={cell.failed} uncertain={cell.uncertain}"
        )
    for f in run.findings:
        print(
            f"  {f.id} [{f.severity.value}/{f.status.value}] {f.input.prompt[:50]!r}: {f.explanation[:60]}"
        )
    if run.spec and run.spec["unverifiable"]:
        print("unverifiable without a judge model:", run.spec["unverifiable"])


if __name__ == "__main__":
    asyncio.run(main())
