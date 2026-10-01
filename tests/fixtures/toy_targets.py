"""Importable toy targets used by the test suite."""

import time

from redsi.core.models import TargetInput, TargetOutput


def echo(prompt: str) -> str:
    return f"echo: {prompt}"


def rag(prompt: str, context: list) -> dict:
    return {"answer": f"{prompt} | docs={len(context)}", "confidence": 0.9}


def full(input: TargetInput) -> TargetOutput:
    return TargetOutput(text=input.system or "", metadata={"n": len(input.context)})


def slow(prompt: str) -> str:
    time.sleep(30)
    return "late"


def agent(prompt: str) -> str:
    return "default agent"
