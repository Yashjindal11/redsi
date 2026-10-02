"""Example 12 - a custom target adapter.

Implement one coroutine and declare capabilities. This adapter wraps a
*stateful* session-based chatbot: it replays the conversation history into a
fresh session for every call, so tests stay independent.

    python examples/12_custom_target_adapter/run.py
"""

import asyncio

from redsi import RedSI, TargetAdapter, TargetInput, TargetOutput
from redsi.targets import TargetRef


class SessionBot:
    """Stand-in for a third-party SDK with sessions."""

    def __init__(self) -> None:
        self.memory: dict[str, str] = {}

    def send(self, text: str) -> str:
        lower = text.lower()
        if "my booking code is" in lower:
            self.memory["code"] = text.rsplit(" is ", 1)[-1].strip(" .").split()[0]
            return "Noted."
        if "booking code" in lower:
            return f"Your code is {self.memory.get('code', 'unknown')}."
        return "OK."


class SessionTarget(TargetAdapter):
    name = "session-bot"
    capabilities = frozenset({"text", "history"})
    timeout = 10

    async def run(self, input: TargetInput) -> TargetOutput:
        bot = SessionBot()  # fresh session per test = no cross-test leakage
        for m in input.history:
            if m.role == "user":
                bot.send(m.content)
        reply = await asyncio.to_thread(bot.send, input.prompt)
        return TargetOutput(text=reply, metadata={"replayed_turns": len(input.history)})

    def ref(self) -> TargetRef:
        # Importable class path makes runs reproducible with `redsi reproduce`.
        return TargetRef(
            kind="custom",
            name=self.name,
            params={"class": f"{__name__}:SessionTarget"},
            reproducible=False,
        )


async def main() -> None:
    run = await RedSI(SessionTarget(), store=None).run(["reliability"], mode="quick")
    ctx = next(r for r in run.cases if r.case.category == "reliability.context")
    print(f"context test: {ctx.verdict.value} -> {ctx.outputs[0].text!r}")
    print(
        f"{run.metrics.executed} executed, {run.metrics.skipped} skipped (needs system/context/tools)"
    )


if __name__ == "__main__":
    asyncio.run(main())
