import json

import pytest

from redsi.observability import EventBus, JsonlSink, MemorySink, Redactor


@pytest.mark.parametrize(
    "secret",
    [
        "sk-proj-abcdefghijklmnopqrstuvwxyz123456",
        "AKIAABCDEFGHIJKLMNOP",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "Bearer abcdefghijklmnopqrstuvwxyz",
    ],
)
def test_redacts_known_key_formats(secret: str) -> None:
    out = Redactor(include_env=False).text(f"value={secret} end")
    assert secret not in out
    assert "[REDACTED]" in out


def test_redacts_assignments_and_env_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_SERVICE_TOKEN", "super-private-value-123")
    r = Redactor()
    assert "super-private-value-123" not in r.text("token is super-private-value-123")
    assert r.text('password: "hunter2hunter2"') == 'password: "[REDACTED]"'


def test_leaves_ordinary_text_and_canaries_alone() -> None:
    r = Redactor(include_env=False)
    text = "The canary RSI-CANARY-7F3A9 must not leak; 2+2=4."
    assert r.text(text) == text


def test_redacts_nested_structures() -> None:
    r = Redactor(["topsecretvalue"], include_env=False)
    assert r.obj({"a": ["x topsecretvalue"], "n": 3}) == {"a": ["x [REDACTED]"], "n": 3}


def test_event_bus_redacts_and_isolates_sink_failures(tmp_path) -> None:
    class Broken:
        def handle(self, event):
            raise RuntimeError("boom")

    mem = MemorySink()
    path = tmp_path / "events.jsonl"
    bus = EventBus(
        [Broken(), mem, JsonlSink(path)],
        run_id="RUN-1",
        redactor=Redactor(["s3cr3t-value"], include_env=False),
    )
    bus.emit("model.call", prompt="key s3cr3t-value")
    assert mem.events[0].data["prompt"] == "key [REDACTED]"
    line = json.loads(path.read_text().splitlines()[0])
    assert line["run_id"] == "RUN-1" and "s3cr3t" not in path.read_text()
