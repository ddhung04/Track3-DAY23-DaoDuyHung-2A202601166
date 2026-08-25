"""Shared deterministic LLM double for graph unit and smoke tests."""

import pytest


class FakeResponse:
    """Minimal LangChain-style response returned by the answer call."""

    content = "Grounded response from the offline integration test."


class FakeLLM:
    """Classifies intent for tests without changing production LLM behavior."""

    def __init__(self) -> None:
        self.schema: object | None = None

    def with_structured_output(self, schema: object) -> "FakeLLM":
        self.schema = schema
        return self

    def invoke(self, messages: object) -> object:
        if self.schema is None:
            return FakeResponse()
        query = str(messages)
        if isinstance(messages, list) and messages:
            last_message = messages[-1]
            if isinstance(last_message, tuple) and len(last_message) == 2:
                query = str(last_message[1])
        query = query.lower()
        if "refund" in query or "delete" in query:
            route = "risky"
        elif "lookup" in query or "order status" in query:
            route = "tool"
        elif "timeout" in query or "failure" in query:
            route = "error"
        elif "fix it" in query or "support request: fix it" in query:
            route = "missing_info"
        else:
            route = "simple"
        return {"route": route, "rationale": "offline test-double classification"}


@pytest.fixture
def offline_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route all node LLM calls through the deterministic test double."""
    monkeypatch.setattr("langgraph_agent_lab.nodes.get_llm", FakeLLM)
    monkeypatch.setenv("LANGGRAPH_INTERRUPT", "false")
