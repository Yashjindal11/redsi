"""Example 2 - a RAG system with a planted retrieval bug.

The retriever only returns the single best keyword match, so questions whose
answer lives in a second document fail. Because the target reports what it
retrieved (``TargetOutput.retrieved``), RedSI can attach an evidence-based
``retrieval_failure`` hypothesis to the finding.

    python examples/02_rag_system/run.py
"""

import asyncio
import re

from redsi import Document, RedSI, Target, TargetInput, TargetOutput, TestCase
from redsi.evaluators import AcknowledgesUncertainty, Contains

KNOWLEDGE_BASE = [
    Document(id="kb-1", content="Standard shipping takes 3 to 5 business days within the country."),
    Document(
        id="kb-2",
        content="Express shipping is available for an extra 12 USD and arrives next business day.",
    ),
    Document(
        id="kb-3",
        content="International orders ship within 10 to 14 business days and may incur customs fees.",
    ),
    Document(
        id="kb-4",
        content="Returns are accepted within 30 days if the item is unused and in original packaging.",
    ),
]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower())) - {
        "the",
        "a",
        "is",
        "how",
        "what",
        "do",
        "i",
        "for",
        "to",
        "of",
        "and",
    }


def retrieve(query: str, docs: list[Document], k: int = 1) -> list[Document]:
    scored = sorted(docs, key=lambda d: len(_tokens(query) & _tokens(d.content)), reverse=True)
    return [d for d in scored[:k] if _tokens(query) & _tokens(d.content)]


def rag(input: TargetInput) -> TargetOutput:
    corpus = input.context or KNOWLEDGE_BASE  # suite tests bring their own documents
    hits = retrieve(input.prompt, corpus)
    if not hits:
        return TargetOutput(text="I could not find that in the documentation.", retrieved=[])
    return TargetOutput(text=f"According to our docs: {hits[0].content}", retrieved=hits)


def q(prompt: str, reference: str | None, category: str, *evaluators) -> TestCase:
    return TestCase(
        input=prompt, reference=reference, category=category, evaluators=list(evaluators)
    )


TESTS = [
    q(
        "How long does standard shipping take?",
        "3 to 5 business days",
        "rag.grounding",
        Contains(all_of=["3 to 5"]),
    ),
    q("How much does express shipping cost?", "12 USD", "rag.grounding", Contains(all_of=["12"])),
    # Needs kb-3 ("international orders"), but "shipping" + "days" pull kb-1 to the top.
    q(
        "How many days does shipping take abroad?",
        "10 to 14 business days",
        "rag.retrieval_failure",
        Contains(all_of=["10 to 14"]),
    ),
    q("Do you offer gift wrapping?", None, "rag.missing_evidence", AcknowledgesUncertainty()),
]


async def main() -> None:
    run = await RedSI(Target.from_function(rag), store=None).run(
        ["rag"], tests=TESTS, mode="custom"
    )
    print(f"pass rate {run.metrics.pass_rate:.0%} over {run.metrics.executed} tests")
    for f in run.findings:
        causes = ", ".join(f"{h.cause.value}({h.likelihood})" for h in f.hypotheses)
        print(f"  {f.id} {f.category} [{f.status.value}] -> hypotheses: {causes}")


if __name__ == "__main__":
    asyncio.run(main())
