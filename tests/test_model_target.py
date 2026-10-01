from redsi.core.models import Message, TargetInput, ToolSpec
from redsi.providers import ChatRequest, ChatResponse, ScriptedProvider
from redsi.targets import ModelTarget, Target


async def test_model_target_builds_messages_and_passes_tools() -> None:
    seen: list[ChatRequest] = []

    def respond(req: ChatRequest) -> ChatResponse:
        seen.append(req)
        return ChatResponse(text="ok", model="m")

    t = Target.from_model(ScriptedProvider(respond), system="You are terse.")
    out = await t.run(
        TargetInput(
            prompt="q",
            system="extra",
            history=[Message(role="user", content="earlier")],
            context=[{"content": "doc body", "id": "d1"}],
            tools=[ToolSpec(name="lookup")],
        )
    )
    req = seen[0]
    assert out.text == "ok"
    assert req.messages[0].role == "system"
    assert "You are terse." in req.messages[0].content and "doc body" in req.messages[0].content
    assert [m.content for m in req.messages[1:]] == ["earlier", "q"]
    assert req.tools[0].name == "lookup"
    assert not t.ref().reproducible  # provider instance, no config


def test_from_openai_ref_is_reproducible_without_secrets() -> None:
    t = Target.from_openai("gpt-test", base_url="http://localhost:9999/v1", system="S")
    ref = t.ref()
    assert ref.reproducible
    assert ref.params["provider"]["api_key_env"] == "OPENAI_API_KEY"
    rebuilt = Target.from_ref(ref)
    assert isinstance(rebuilt, ModelTarget) and rebuilt.system == "S"


def test_load_shorthand_model_targets() -> None:
    t = Target.load("ollama:llama3.1:8b")
    assert isinstance(t, ModelTarget)
    assert t.provider.model == "llama3.1:8b"
    assert t.ref().params["provider"] == {"type": "ollama", "model": "llama3.1:8b"}
