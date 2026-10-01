import asyncio
import json
from pathlib import Path

import httpx
import pytest

from redsi.core.models import TargetInput, TargetOutput
from redsi.targets import Target, TargetAdapter, coerce_output, invoke

FIXTURE = str(Path(__file__).parent / "fixtures" / "toy_targets.py")


async def test_function_target_prompt_mode() -> None:
    t = Target.from_function(lambda prompt: prompt.upper(), name="upper")
    out = await invoke(t, TargetInput(prompt="hi"))
    assert out.text == "HI" and out.latency_ms is not None
    assert t.capabilities == {"text"}
    assert not t.ref().reproducible  # lambdas cannot be re-imported


async def test_function_target_kwargs_declare_capabilities() -> None:
    async def rag(prompt: str, context: list) -> str:
        return f"{len(context)} docs"

    t = Target.from_function(rag)
    assert t.capabilities == {"text", "context"}
    out = await t.run(TargetInput(prompt="q", context=[{"content": "a"}, {"content": "b"}]))
    assert out.text == "2 docs"
    assert t.missing_capabilities(TargetInput(prompt="q", system="s")) == {"system"}


async def test_function_target_input_mode_and_flatten() -> None:
    def full(input: TargetInput) -> str:
        return input.system or ""

    assert (await Target.from_function(full).run(TargetInput(prompt="q", system="S"))).text == "S"
    flat = Target.from_function(lambda p: p, flatten=True)
    out = await flat.run(TargetInput(prompt="q", system="S"))
    assert "S" in out.text and "q" in out.text


async def test_invoke_captures_exceptions_and_timeouts() -> None:
    def boom(prompt: str) -> str:
        raise ValueError("bad")

    out = await invoke(Target.from_function(boom), TargetInput(prompt="x"))
    assert out.error == "ValueError: bad"

    async def slow(prompt: str) -> str:
        await asyncio.sleep(5)
        return "late"

    out = await invoke(Target.from_function(slow), TargetInput(prompt="x"), timeout=0.05)
    assert out.error and "timeout" in out.error


def test_coerce_output_shapes() -> None:
    assert coerce_output("a").text == "a"
    assert coerce_output(None).text == ""
    out = coerce_output({"answer": "x", "confidence": 0.3})
    assert out.text == "x" and out.metadata["confidence"] == 0.3
    assert coerce_output(TargetOutput(text="t")).text == "t"


async def test_import_from_file_with_and_without_attr() -> None:
    t = Target.from_import(f"{FIXTURE}:rag")
    assert t.capabilities == {"text", "context"}
    out = await t.run(TargetInput(prompt="q", context=[{"content": "a"}]))
    assert out.text == "q | docs=1" and out.metadata["confidence"] == 0.9
    assert (await Target.from_import(FIXTURE).run(TargetInput(prompt="q"))).text == "default agent"


async def test_import_ref_roundtrip() -> None:
    t = Target.from_import(f"{FIXTURE}:echo")
    ref = t.ref()
    assert ref.kind == "import" and ref.reproducible
    rebuilt = Target.from_ref(ref.model_dump())
    assert (await rebuilt.run(TargetInput(prompt="x"))).text == "echo: x"


async def test_isolated_target_runs_and_kills_on_timeout() -> None:
    t = Target.from_import(f"{FIXTURE}:echo", isolate=True)
    assert (await invoke(t, TargetInput(prompt="x"))).text == "echo: x"
    slow = Target.from_import(f"{FIXTURE}:slow", isolate=True, timeout=1)
    out = await invoke(slow, TargetInput(prompt="x"))
    assert out.error and "killed" in out.error


async def test_custom_adapter_needs_no_core_changes() -> None:
    class Reverse(TargetAdapter):
        name = "reverse"

        async def run(self, input: TargetInput) -> TargetOutput:
            return TargetOutput(text=input.prompt[::-1])

    assert (await invoke(Reverse(), TargetInput(prompt="abc"))).text == "cba"
    assert not Reverse().ref().reproducible


async def test_http_target_renders_template_and_extracts_path(monkeypatch) -> None:
    monkeypatch.setenv("TOY_API_KEY", "k-123456789")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"answer": "pong"}})

    t = Target.from_http(
        "https://example.test/chat",
        body={"q": "{{prompt}}", "docs": "{{context}}", "note": "sys={{system}}"},
        headers={"Authorization": "Bearer ${TOY_API_KEY}"},
        response_path="data.answer",
        transport=httpx.MockTransport(handler),
    )
    assert t.capabilities == {"text", "context", "system"}
    out = await t.run(TargetInput(prompt="ping", system="S", context=[{"content": "d"}]))
    await t.aclose()
    assert out.text == "pong"
    assert seen["auth"] == "Bearer k-123456789"
    assert seen["body"]["q"] == "ping" and seen["body"]["docs"][0]["content"] == "d"
    assert seen["body"]["note"] == "sys=S"
    assert t.ref().params["headers"]["Authorization"] == "Bearer ${TOY_API_KEY}"


async def test_http_target_reports_errors_and_does_not_follow_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"location": "https://elsewhere.test/"})
        return httpx.Response(500, text="kaput")

    transport = httpx.MockTransport(handler)
    err = await Target.from_http("https://x.test/err", transport=transport).run(
        TargetInput(prompt="q")
    )
    assert err.error and err.error.startswith("HTTP 500")
    redir = await Target.from_http("https://x.test/redirect", transport=transport).run(
        TargetInput(prompt="q")
    )
    assert redir.metadata["status_code"] == 302


def test_load_parses_specs() -> None:
    assert Target.load("https://x.test/api").kind == "http"
    assert Target.load(f"{FIXTURE}:echo").name == "echo"
    with pytest.raises(ValueError):
        Target.from_ref({"kind": "function", "name": "x", "reproducible": False})
