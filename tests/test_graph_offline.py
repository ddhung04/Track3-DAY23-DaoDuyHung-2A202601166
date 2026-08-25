"""Offline regression test for the bounded retry/dead-letter path."""

from langgraph_agent_lab.graph import build_graph
from langgraph_agent_lab.persistence import build_checkpointer
from langgraph_agent_lab.scenarios import load_scenarios
from langgraph_agent_lab.state import initial_state


def test_retry_limit_reaches_dead_letter(offline_llm: None) -> None:
    """S07 cannot loop forever when its retry budget is one."""
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    scenario = next(
        item
        for item in load_scenarios("data/sample/scenarios.jsonl")
        if item.id == "S07_dead_letter"
    )
    state = initial_state(scenario)
    result = graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    assert any(event["node"] == "dead_letter" for event in result["events"])
    assert result["attempt"] == scenario.max_attempts
