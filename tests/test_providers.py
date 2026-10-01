import json

import httpx
import pytest

from redsi.core.models import Message, ToolSpec
from redsi.providers import (
    AnthropicProvider,
    CachedProvider,
    ChatRequest,
    ModelRoles,
    OpenAICompatibleProvider,
    Pricing,
    ProviderError,
    ScriptedProvider,
    parse_json_object,
    provider_from_config,
)


async def test_scripted_provider_cycles_and_records() -> None:
    p = ScriptedProvider(["a", "b"])
    texts = [(await p.complete(ChatRequest.simple("q"))).text for _ in range(3)]
    assert texts == ["a", "b", "a"]
    assert len(p.requests) == 3


async def test_scripted_provider_accepts_async_function() -> None:
    async def respond(req: ChatRequest) -> str:
        return req.messages[-1].content[::-1]

    assert (await ScriptedProvider(respond).complete(ChatRequest.simple("abc"))).text == "cba"


async def test_openai_compatible_payload_and_parsing(monkeypatch) -> None:
    monkeypatch.setenv("TEST_OPENAI_KEY", "sk-test-1234567890abcdef")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "m-1",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {"function": {"name": "lookup", "arguments": '{"id": 7}'}}
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            },
        )

    p = OpenAICompatibleProvider(
        "m-1",
        api_key_env="TEST_OPENAI_KEY",
        pricing=Pricing(input_per_mtok=1.0, output_per_mtok=2.0),
        transport=httpx.MockTransport(handler),
    )
    req = ChatRequest(
        messages=[Message(role="user", content="hi")],
        json_mode=True,
        seed=3,
        tools=[ToolSpec(name="lookup")],
    )
    resp = await p.complete(req)
    await p.aclose()
    assert seen["auth"] == "Bearer sk-test-1234567890abcdef"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["tools"][0]["function"]["name"] == "lookup"
    assert resp.tool_calls[0].arguments == {"id": 7}
    assert resp.usage.cost_usd == pytest.approx(0.002)
    assert "TEST_OPENAI_KEY" in json.dumps(p.describe()) and "sk-test" not in json.dumps(
        p.describe()
    )


async def test_openai_compatible_retries_then_fails() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="busy")

    p = OpenAICompatibleProvider(
        "m",
        base_url="http://local.test/v1",
        api_key_env=None,
        max_retries=2,
        retry_base_delay=0,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError):
        await p.complete(ChatRequest.simple("q"))
    assert calls["n"] == 2


async def test_anthropic_payload_and_parsing(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-abcdefgh")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "hello"}],
                "usage": {"input_tokens": 3, "output_tokens": 1},
                "stop_reason": "end_turn",
            },
        )

    p = AnthropicProvider("claude-x", transport=httpx.MockTransport(handler))
    resp = await p.complete(ChatRequest.simple("q", system="be brief"))
    assert seen["body"]["system"] == "be brief"
    assert seen["body"]["messages"] == [{"role": "user", "content": "q"}]
    assert resp.text == "hello" and resp.usage.total_tokens == 4 and resp.usage.cost_usd is None


async def test_cached_provider_only_caches_deterministic_requests(tmp_path) -> None:
    inner = ScriptedProvider(["one", "two", "three"])
    cached = CachedProvider(inner, directory=tmp_path)
    a = await cached.complete(ChatRequest.simple("q"))
    b = await cached.complete(ChatRequest.simple("q"))
    assert a.text == b.text == "one" and b.cached and cached.hits == 1
    c = await cached.complete(ChatRequest.simple("q", temperature=0.7))
    assert c.text == "two"
    # Disk cache survives a new wrapper.
    again = await CachedProvider(ScriptedProvider(["other"]), directory=tmp_path).complete(
        ChatRequest.simple("q")
    )
    assert again.text == "one"


def test_provider_from_config_and_presets() -> None:
    p = provider_from_config("ollama:llama3.1")
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.base_url.startswith("http://localhost:11434") and p.api_key_env is None
    q = provider_from_config(
        {"type": "openai", "model": "x", "pricing": {"input_per_mtok": 1, "output_per_mtok": 1}}
    )
    assert q.pricing is not None
    roles = ModelRoles(generator=p, judges=[q])
    assert roles.describe()["judges"][0]["model"] == "x"


def test_parse_json_object_tolerates_fences() -> None:
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Sure: {"verdict": "pass"} thanks') == {"verdict": "pass"}
    with pytest.raises(ValueError):
        parse_json_object("no json")
