"""Construction of the support-ticket LangGraph workflow."""

from __future__ import annotations

from typing import cast

from langgraph.graph.state import CompiledStateGraph

from .nodes import (
    answer_node,
    approval_node,
    ask_clarification_node,
    classify_node,
    dead_letter_node,
    evaluate_node,
    finalize_node,
    intake_node,
    retry_or_fallback_node,
    risky_action_node,
    tool_node,
)
from .persistence import Checkpointer
from .routing import (
    route_after_approval,
    route_after_classify,
    route_after_evaluate,
    route_after_retry,
)
from .state import AgentState


def build_graph(checkpointer: Checkpointer | None = None) -> CompiledStateGraph:
    """Build and compile the complete, terminating StateGraph.

    Every branch reaches ``finalize`` before ``END``. Conditional routing owns
    the retry bound and the approval gate so node implementations stay focused
    on state updates.
    """
    from langgraph.graph import END, START, StateGraph

    workflow = StateGraph(AgentState)
    workflow.add_node("intake", intake_node)
    workflow.add_node("classify", classify_node)
    workflow.add_node("tool", tool_node)
    workflow.add_node("evaluate", evaluate_node)
    workflow.add_node("answer", answer_node)
    workflow.add_node("clarify", ask_clarification_node)
    workflow.add_node("risky_action", risky_action_node)
    workflow.add_node("approval", approval_node)
    workflow.add_node("retry", retry_or_fallback_node)
    workflow.add_node("dead_letter", dead_letter_node)
    workflow.add_node("finalize", finalize_node)

    workflow.add_edge(START, "intake")
    workflow.add_edge("intake", "classify")
    workflow.add_conditional_edges("classify", route_after_classify)
    workflow.add_edge("tool", "evaluate")
    workflow.add_conditional_edges("evaluate", route_after_evaluate)
    workflow.add_conditional_edges("retry", route_after_retry)
    workflow.add_edge("risky_action", "approval")
    workflow.add_conditional_edges("approval", route_after_approval)
    workflow.add_edge("answer", "finalize")
    workflow.add_edge("clarify", "finalize")
    workflow.add_edge("dead_letter", "finalize")
    workflow.add_edge("finalize", END)
    return cast(CompiledStateGraph, workflow.compile(checkpointer=checkpointer))
