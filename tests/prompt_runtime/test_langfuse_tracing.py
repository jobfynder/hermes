import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

from app.prompt_runtime.models import PromptRenderedMessage, PromptRunRequest, PromptRunResult
from app.prompt_runtime.service import _langfuse_usage_details, send_langfuse_trace


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_requires_langfuse_version_with_v4_ingestion_header():
    requirements = (REPOSITORY_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "langfuse>=4.7,<5" in requirements


class FakeObservation:
    def __init__(self, calls: list, kwargs: dict):
        self.calls = calls
        self.kwargs = kwargs

    def __enter__(self):
        self.calls.append(("enter", self.kwargs))
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.calls.append(("exit", self.kwargs))


class FakeLangfuse:
    def __init__(self):
        self.calls = []

    def create_trace_id(self, *, seed: str) -> str:
        self.calls.append(("trace_id", seed))
        return "a" * 32

    def start_as_current_observation(self, **kwargs):
        self.calls.append(("observation", kwargs))
        return FakeObservation(self.calls, kwargs)


def _result() -> PromptRunResult:
    return PromptRunResult(
        runtime_version="test",
        run_id="prompt-run-123",
        prompt_id="candidate-summary",
        prompt_version="1",
        mode_requested="live",
        mode_effective="live",
        provider="litellm",
        decision="completed",
        output_text="A concise summary",
        usage={
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "total_tokens": 20,
            "model_used": "gpt-test",
        },
    )


def test_usage_details_normalizes_token_names_and_ignores_non_numeric_values():
    assert _langfuse_usage_details(_result().usage) == {
        "input": 12,
        "output": 8,
        "total": 20,
    }


def test_send_langfuse_trace_uses_v4_nested_otel_observations(monkeypatch):
    fake_client = FakeLangfuse()
    propagated = []
    fake_module = ModuleType("langfuse")
    fake_module.get_client = lambda: fake_client

    @contextmanager
    def propagate_attributes(**kwargs):
        propagated.append(kwargs)
        yield

    fake_module.propagate_attributes = propagate_attributes
    monkeypatch.setitem(sys.modules, "langfuse", fake_module)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    request = PromptRunRequest(
        prompt_id="candidate-summary",
        variables={"candidate": "Alex"},
        mode="live",
        correlation_id="request-42",
        actor_id="user-7",
        source="api",
    )
    messages = [PromptRenderedMessage(role="user", content="Summarize Alex")]
    send_langfuse_trace(_result(), messages, request)

    observations = [call[1] for call in fake_client.calls if call[0] == "observation"]
    assert fake_client.calls[0] == ("trace_id", "prompt-run-123")
    assert len(observations) == 2
    assert observations[0]["as_type"] == "span"
    assert observations[0]["trace_context"] == {"trace_id": "a" * 32}
    assert observations[1]["as_type"] == "generation"
    assert observations[1]["model"] == "gpt-test"
    assert observations[1]["usage_details"] == {"input": 12, "output": 8, "total": 20}
    assert propagated == [{
        "trace_name": "candidate-summary",
        "user_id": "user-7",
        "session_id": "request-42",
        "tags": ["hermes", "prompt_runtime", "candidate-summary"],
    }]


def test_send_langfuse_trace_remains_best_effort(monkeypatch):
    fake_module = ModuleType("langfuse")
    fake_module.get_client = lambda: (_ for _ in ()).throw(RuntimeError("exporter unavailable"))
    fake_module.propagate_attributes = lambda **kwargs: None
    monkeypatch.setitem(sys.modules, "langfuse", fake_module)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    send_langfuse_trace(
        _result(),
        [],
        PromptRunRequest(prompt_id="candidate-summary"),
    )
