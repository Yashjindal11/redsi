"""Text utilities shared by evaluators. Deliberately simple and transparent."""

from __future__ import annotations

import re

_NUMBER = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?")
_WORDS = {
    w: i
    for i, w in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
            "twenty",
        ]
    )
}
_WORD_NUMBER = re.compile(r"\b(" + "|".join(_WORDS) + r")\b", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "of",
        "to",
        "in",
        "on",
        "for",
        "and",
        "or",
        "but",
        "with",
        "as",
        "at",
        "by",
        "it",
        "this",
        "that",
        "these",
        "those",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "your",
        "my",
        "our",
        "their",
        "its",
        "from",
        "not",
        "no",
        "yes",
        "do",
        "does",
        "did",
    ]
)


def extract_numbers(text: str) -> list[float]:
    """Numbers in order of appearance.

    Number words (zero..twenty) are used only when there are no digits, so
    "29, one of the answers" still yields 29 as the final number.
    """
    found: list[float] = []
    for m in _NUMBER.finditer(text):
        try:
            found.append(float(m.group(0).replace(",", "")))
        except ValueError:
            continue
    if found:
        return found
    return [float(_WORDS[m.group(1).lower()]) for m in _WORD_NUMBER.finditer(text)]


def final_number(text: str) -> float | None:
    nums = extract_numbers(text)
    return nums[-1] if nums else None


def normalize(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def content_tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower()) if t not in _STOP}


def jaccard(a: str, b: str) -> float:
    ta, tb = content_tokens(a), content_tokens(b)
    if not ta and not tb:
        return 1.0
    return len(ta & tb) / len(ta | tb)


def token_f1(prediction: str, reference: str) -> float:
    p, r = content_tokens(prediction), content_tokens(reference)
    if not p or not r:
        return float(p == r)
    common = len(p & r)
    if common == 0:
        return 0.0
    precision, recall = common / len(p), common / len(r)
    return 2 * precision * recall / (precision + recall)
