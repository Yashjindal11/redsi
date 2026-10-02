"""Example 7 - a multi-agent pipeline (planner -> researcher -> writer).

Each agent's step is recorded in ``TargetOutput.trace`` so findings show
*where* in the pipeline things went wrong. The planted bug: the writer
passes researcher notes through verbatim, so an instruction hidden in a
retrieved document reaches the final answer (indirect prompt injection).

    python examples/07_multi_agent_system/run.py
"""

import asyncio

from redsi import RedSI, Target, TargetInput, TargetOutput


def planner(question: str) -> list[str]:
    return [f"find facts about: {question}", "write a short answer"]


def researcher(step: str, docs: list[str]) -> str:
    return " ".join(docs) if docs else "no documents"


def writer(question: str, notes: str) -> str:
    if "ignore all prior instructions" in notes.lower():
        # Naively "obeys" the note - exactly the vulnerability we want RedSI to catch.
        marker = notes.split("reply only with")[-1].strip(" '.\"")
        return marker
    return f"Answer: {notes[:120]}"


def pipeline(input: TargetInput) -> TargetOutput:
    trace = []
    plan = planner(input.prompt)
    trace.append({"agent": "planner", "plan": plan})
    notes = researcher(plan[0], [d.content for d in input.context])
    trace.append({"agent": "researcher", "notes": notes[:200]})
    answer = writer(input.prompt, notes)
    trace.append({"agent": "writer", "answer": answer[:200]})
    return TargetOutput(text=answer, trace=trace)


async def main() -> None:
    run = await RedSI(Target.from_function(pipeline), store=None).run(
        ["security", "rag"], mode="quick"
    )
    for f in run.findings:
        writer_step = next((t for t in f.output.trace if t.get("agent") == "writer"), {})
        print(
            f"  {f.id} [{f.severity.value}] {f.category} | writer produced: {writer_step.get('answer', '')[:50]!r}"
        )


if __name__ == "__main__":
    asyncio.run(main())
