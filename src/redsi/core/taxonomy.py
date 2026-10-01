"""Failure taxonomy.

Categories are identified by ``"<domain>.<name>"`` strings so users can add
their own without touching this module (``register_category``). The built-in
entries describe *observable* failure modes; root causes live elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from redsi.core.severity import Severity


@dataclass(frozen=True, slots=True)
class Category:
    id: str
    description: str
    default_severity: Severity = Severity.MEDIUM
    recommendation: str = ""

    @property
    def domain(self) -> str:
        return self.id.split(".", 1)[0]


_S = Severity

_BUILTIN: tuple[Category, ...] = (
    # Reliability
    Category(
        "reliability.inconsistency",
        "Different answers to the same input across samples.",
        _S.MEDIUM,
        "Lower sampling temperature or add answer normalisation; check for nondeterministic retrieval.",
    ),
    Category(
        "reliability.contradiction",
        "Answer contradicts itself or an earlier answer.",
        _S.MEDIUM,
        "Add self-consistency checks or constrain the output structure.",
    ),
    Category(
        "reliability.instruction_following",
        "Ignores an explicit instruction.",
        _S.MEDIUM,
        "Make instructions explicit in the system prompt and validate the output.",
    ),
    Category(
        "reliability.format",
        "Output does not match the required format or schema.",
        _S.MEDIUM,
        "Use structured output / JSON mode and validate before returning.",
    ),
    Category(
        "reliability.context",
        "Loses or misuses information provided earlier in the conversation.",
        _S.MEDIUM,
        "Review context window management and conversation truncation.",
    ),
    Category(
        "reliability.availability",
        "Target errors, times out, or returns an empty response.",
        _S.HIGH,
        "Add retries, fallbacks and timeouts in the serving path.",
    ),
    # Factuality
    Category(
        "factuality.hallucination",
        "States facts about entities or events that do not exist.",
        _S.HIGH,
        "Ground answers in retrieved sources and allow the model to say it does not know.",
    ),
    Category(
        "factuality.unsupported_claim",
        "Makes claims not supported by provided evidence.",
        _S.MEDIUM,
        "Require citations to provided context; reject answers without support.",
    ),
    Category(
        "factuality.fabricated_citation",
        "Invents references, quotes or sources.",
        _S.HIGH,
        "Only allow citations drawn from a verified source list.",
    ),
    Category(
        "factuality.calculation",
        "Produces an incorrect numeric result.",
        _S.MEDIUM,
        "Route arithmetic to a calculator tool.",
    ),
    Category(
        "factuality.false_premise",
        "Accepts a false assumption embedded in the question.",
        _S.MEDIUM,
        "Instruct the system to check and correct premises.",
    ),
    # Reasoning
    Category(
        "reasoning.logic",
        "Draws an invalid logical inference.",
        _S.MEDIUM,
        "Ask for explicit reasoning steps or use a verifier.",
    ),
    Category(
        "reasoning.arithmetic",
        "Fails multi-step arithmetic or quantitative reasoning.",
        _S.MEDIUM,
        "Use tool-assisted computation for multi-step numeric problems.",
    ),
    Category(
        "reasoning.causal",
        "Confuses correlation with causation or misattributes causes.",
        _S.MEDIUM,
        "Add domain guidance about causal claims.",
    ),
    Category(
        "reasoning.edge_case",
        "Fails on boundary or degenerate inputs.",
        _S.MEDIUM,
        "Add explicit handling and tests for boundary values.",
    ),
    # Robustness
    Category(
        "robustness.paraphrase",
        "Answer changes when the question is reworded.",
        _S.MEDIUM,
        "Evaluate with paraphrase sets; consider canonicalising inputs.",
    ),
    Category(
        "robustness.ambiguity",
        "Guesses instead of asking for clarification on ambiguous input.",
        _S.LOW,
        "Teach the system to ask clarifying questions.",
    ),
    Category(
        "robustness.missing_information",
        "Answers confidently despite missing required information.",
        _S.MEDIUM,
        "Detect missing slots and request them.",
    ),
    Category(
        "robustness.noise",
        "Fails on typos, casing or formatting noise.",
        _S.LOW,
        "Normalise inputs; add noisy examples to evaluation.",
    ),
    Category(
        "robustness.irrelevant_context",
        "Distracted by irrelevant context.",
        _S.MEDIUM,
        "Filter context; instruct the system to ignore unrelated material.",
    ),
    Category(
        "robustness.long_context",
        "Degrades when the input is long.",
        _S.MEDIUM,
        "Chunk or summarise long inputs; test near the context limit.",
    ),
    Category(
        "robustness.adversarial_wording",
        "Changes behaviour under adversarial framing or role-play.",
        _S.MEDIUM,
        "Harden the system prompt; test role-play framings.",
    ),
    # RAG
    Category(
        "rag.retrieval_failure",
        "Relevant evidence was not retrieved.",
        _S.HIGH,
        "Inspect retriever recall; tune chunking and embeddings.",
    ),
    Category(
        "rag.irrelevant_retrieval",
        "Retrieved documents are unrelated to the question.",
        _S.MEDIUM,
        "Add re-ranking or relevance thresholds.",
    ),
    Category(
        "rag.missing_evidence",
        "Answers although the context lacks the needed evidence.",
        _S.HIGH,
        "Instruct the model to abstain when evidence is missing.",
    ),
    Category(
        "rag.grounding",
        "Answer is not grounded in the retrieved context.",
        _S.HIGH,
        "Require quoting or citing context passages.",
    ),
    Category(
        "rag.citation_mismatch",
        "Cited passage does not support the claim.",
        _S.MEDIUM,
        "Verify citations against the cited passage before returning.",
    ),
    Category(
        "rag.context_contamination",
        "Conflicting or poisoned context changes the answer.",
        _S.HIGH,
        "Track document provenance; prefer authoritative sources.",
    ),
    # Agent behaviour
    Category(
        "agent.tool_selection",
        "Chooses the wrong tool or no tool when one is required.",
        _S.MEDIUM,
        "Improve tool descriptions; add routing examples.",
    ),
    Category(
        "agent.tool_arguments",
        "Calls a tool with invalid or wrong arguments.",
        _S.MEDIUM,
        "Validate tool arguments against schemas before execution.",
    ),
    Category(
        "agent.tool_misuse",
        "Calls a tool it should not call in this situation.",
        _S.HIGH,
        "Add authorisation checks around side-effecting tools.",
    ),
    Category(
        "agent.recovery",
        "Does not recover from a tool error.",
        _S.MEDIUM,
        "Return structured tool errors and test recovery paths.",
    ),
    Category(
        "agent.looping",
        "Repeats tool calls without progress.",
        _S.HIGH,
        "Cap iterations and detect repeated calls.",
    ),
    Category(
        "agent.unnecessary_tool_use",
        "Calls tools when none are needed.",
        _S.LOW,
        "Add negative routing examples.",
    ),
    # Security-oriented evaluation (authorised testing only)
    Category(
        "security.prompt_injection",
        "Follows instructions injected into user input.",
        _S.HIGH,
        "Separate instructions from data; treat user content as untrusted.",
    ),
    Category(
        "security.indirect_prompt_injection",
        "Follows instructions embedded in retrieved or tool content.",
        _S.CRITICAL,
        "Mark retrieved content as data; restrict actions triggered by it.",
    ),
    Category(
        "security.instruction_conflict",
        "Resolves conflicting instructions in favour of the wrong party.",
        _S.HIGH,
        "Define and enforce an instruction hierarchy.",
    ),
    Category(
        "security.data_leakage",
        "Reveals confidential context such as system prompts or canary data.",
        _S.CRITICAL,
        "Do not place secrets in prompts; filter outputs for confidential markers.",
    ),
    Category(
        "security.unsafe_tool_invocation",
        "Triggers a side-effecting tool from untrusted input.",
        _S.CRITICAL,
        "Require confirmation for side-effecting tools.",
    ),
    Category(
        "security.malicious_input",
        "Mishandles malicious-looking input (markup, encodings).",
        _S.MEDIUM,
        "Sanitise and escape inputs and outputs.",
    ),
)

_REGISTRY: dict[str, Category] = {c.id: c for c in _BUILTIN}

DOMAINS: tuple[str, ...] = (
    "reliability",
    "factuality",
    "reasoning",
    "robustness",
    "rag",
    "agent",
    "security",
)


def register_category(category: Category, *, replace: bool = False) -> None:
    if category.id in _REGISTRY and not replace:
        raise ValueError(f"category {category.id!r} already registered")
    if "." not in category.id:
        raise ValueError("category ids must look like '<domain>.<name>'")
    _REGISTRY[category.id] = category


def get_category(category_id: str) -> Category:
    """Return a registered category, or a generic one for unknown ids."""
    found = _REGISTRY.get(category_id)
    if found is not None:
        return found
    return Category(category_id, "User-defined category.")


def categories(domain: str | None = None) -> list[Category]:
    return [c for c in _REGISTRY.values() if domain is None or c.domain == domain]
