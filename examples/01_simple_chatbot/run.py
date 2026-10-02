"""Example 1 - a simple chatbot.

The smallest useful RedSI program: wrap a function, run two built-in suites,
look at what failed. Runs offline.

    python examples/01_simple_chatbot/run.py
"""

import asyncio

from redsi import RedSI, Target


def chatbot(prompt: str) -> str:
    """A toy bot with realistic weaknesses: brittle matching and sloppy arithmetic."""
    p = prompt.lower()
    if "capital of japan" in p:
        return "Tokyo."
    if "even prime" in p:
        return "2"
    if "reply only with the word ok" in p:
        return "OK!"  # extra punctuation breaks the exact-match instruction
    if "multiplied" in p or "*" in p:
        return "About 7 million."  # rounds instead of computing
    if "how many" in p:
        return "I think the answer is 2."
    return "Sorry, I am not sure about that."


async def main() -> None:
    redsi = RedSI(Target.from_function(chatbot), store=None)
    run = await redsi.run(["reliability", "reasoning"], mode="quick")
    m = run.metrics
    print(f"{m.executed} tests, {m.passed} passed, {m.failed} failed, {m.skipped} skipped")
    for f in run.findings[:8]:
        print(f"  {f.id} [{f.severity.value}/{f.status.value}] {f.category}: {f.explanation[:70]}")
    # Tests needing capabilities the bot lacks (system prompt, history) are skipped, not faked:
    skipped = {r.skipped_reason for r in run.cases if r.skipped_reason}
    print("skipped because:", skipped)


if __name__ == "__main__":
    asyncio.run(main())
