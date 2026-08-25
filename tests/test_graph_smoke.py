"""Graph smoke tests that are deterministic by default.

The production nodes use a real provider. Set RUN_LLM_SMOKE_TESTS=true to also
run the opt-in live-provider test after configuring an API account with quota.
"""

import os

import pytest

from langgraph_agent_lab.graph import build_graph
from langgraph_agent_lab.llm import load_local_environment
from langgraph_agent_lab.persistence import build_checkpointer
from langgraph_agent_lab.state import Route, Scenario, initial_state

load_local_environment()


@pytest.mark.parametrize(
    ("query", "expected_route"),
    [
        ("How do I reset my password?", Route.SIMPLE.value),
        ("Please lookup order status for order 123", Route.TOOL.value),
        ("Refund this customer", Route.RISKY.value),
        ("Can you fix it?", Route.MISSING_INFO.value),
        ("Timeout failure while processing", Route.ERROR.value),
    ],
)
def test_graph_runs_and_routes_correctly(
    offline_llm: None, query: str, expected_route: str
) -> None:
    """Exercise each main route without provider availability affecting CI."""
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    scenario = Scenario(id="smoke", query=query, expected_route=Route(expected_route))
    state = initial_state(scenario)
    result = graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    assert result["route"] == expected_route
    assert result.get("final_answer") or result.get("pending_question")


def test_graph_terminates_all_routes(offline_llm: None) -> None:
    """Every route must reach finalize, independently of provider billing."""
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    queries = [
        ("simple query about help", Route.SIMPLE),
        ("lookup order status 999", Route.TOOL),
        ("fix it", Route.MISSING_INFO),
        ("delete user account now", Route.RISKY),
        ("timeout error in system", Route.ERROR),
    ]
    for query, route in queries:
        scenario = Scenario(id=f"term-{route.value}", query=query, expected_route=route)
        state = initial_state(scenario)
        result = graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
        finalize_events = [event for event in result["events"] if event.get("node") == "finalize"]
        assert finalize_events, f"Route {route.value} did not reach finalize node"


@pytest.mark.skipif(
    os.getenv("RUN_LLM_SMOKE_TESTS", "false").lower() != "true",
    reason="Set RUN_LLM_SMOKE_TESTS=true to call a live LLM provider.",
)
def test_graph_live_provider() -> None:
    """Opt-in check that production classification and answer nodes call the provider."""
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    scenario = Scenario(
        id="live-provider",
        query="How do I reset my password?",
        expected_route=Route.SIMPLE,
    )
    state = initial_state(scenario)
    result = graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    assert result["route"] == Route.SIMPLE.value
    assert result.get("final_answer")
