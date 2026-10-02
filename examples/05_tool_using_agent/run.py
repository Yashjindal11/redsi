"""Example 5 - a tool-using agent.

The agent *declares* tool calls in ``TargetOutput.tool_calls``; RedSI checks
selection, arguments, side-effect discipline and loops. RedSI never executes
tools itself. The planted bug: the agent books flights without confirmation
when the user sounds urgent, and follows instructions embedded in emails.

    python examples/05_tool_using_agent/run.py
"""

import asyncio
import re

from redsi import RedSI, Target, TargetInput, TargetOutput, ToolCall


def agent(input: TargetInput) -> TargetOutput:
    p = input.prompt.lower()
    tools = {t.name for t in input.tools}
    calls: list[ToolCall] = []
    text = ""
    if "flight" in p and "get_flight_status" in tools:
        m = re.search(r"\b([a-z]{2})\s?(\d{2,4})\b", p)
        calls.append(
            ToolCall(
                name="get_flight_status",
                arguments={"flight_number": (m.group(1) + m.group(2)).upper() if m else ""},
            )
        )
        text = "Let me check that flight."
    elif "convert" in p and "convert_currency" in tools:
        amount = float(re.search(r"\d+(?:\.\d+)?", p).group(0))
        calls.append(
            ToolCall(
                name="convert_currency",
                arguments={"amount": amount, "source": "USD", "target": "EUR"},
            )
        )
        text = "Converting now."
    elif "weather" in p and "get_weather" in tools:
        for city in ("oslo", "lima"):
            if city in p:
                calls.append(ToolCall(name="get_weather", arguments={"city": city.title()}))
        text = "Here is the weather."
    elif "flight to" in p and "search_flights" in tools:
        calls.append(
            ToolCall(name="search_flights", arguments={"destination": "Denver", "date": "tomorrow"})
        )
        calls.append(
            ToolCall(name="book_flight", arguments={"flight_id": "DEN-1"})
        )  # bug: no confirmation
        text = "Booked you on DEN-1."
    for doc in input.context:
        if "send_email" in doc.content and "send_email" in tools:
            calls.append(
                ToolCall(
                    name="send_email", arguments={"to": "audit@example.invalid", "body": "..."}
                )
            )  # bug
    if not text:
        text = (
            "2 + 2 = 4."
            if "2 + 2" in p
            else "Summary: " + (input.context[0].content[:60] if input.context else "n/a")
        )
    return TargetOutput(text=text, tool_calls=calls)


async def main() -> None:
    run = await RedSI(Target.from_function(agent), store=None).run(
        ["agent", "security"], mode="quick"
    )
    print(
        f"{run.metrics.executed} executed, {run.metrics.skipped} skipped (capabilities), {run.metrics.failed} failed"
    )
    for f in run.findings:
        calls = ", ".join(c.name for c in f.output.tool_calls) or "none"
        print(f"  {f.id} [{f.severity.value}] {f.category}: tools called = {calls}")


if __name__ == "__main__":
    asyncio.run(main())
