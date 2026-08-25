"""Node functions for the LangGraph support-ticket workflow."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field

from .llm import get_llm
from .state import AgentState, make_event


class Classification(BaseModel):
    """Structured response required from the intent-classification model."""

    route: Literal["simple", "tool", "missing_info", "risky", "error"]
    rationale: str = Field(description="Brief explanation of the selected route")


def _response_text(response: object) -> str:
    """Extract non-empty text from a LangChain chat response."""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            else:
                parts.append(str(item))
        text = " ".join(parts).strip()
    else:
        text = str(content).strip()
    if not text:
        raise RuntimeError("LLM returned an empty response")
    return text


def intake_node(state: AgentState) -> dict[str, object]:
    """Normalize raw query and create the first audit event."""
    query = state.get("query", "").strip()
    return {
        "query": query,
        "messages": [f"intake:{query[:40]}"],
        "events": [make_event("intake", "completed", "query normalized")],
    }


def classify_node(state: AgentState) -> dict[str, object]:
    """Classify support intent through an LLM structured-output call."""
    classifier = get_llm().with_structured_output(Classification)
    prompt = """You classify support-ticket requests. Return exactly one route.

Routes, in priority order when more than one could apply:
1. risky: any requested action with side effects, including refunds, deletes,
   cancellations, account changes, or sending emails.
2. tool: an information lookup such as order status, tracking, or search.
3. missing_info: the request is too vague to act on safely.
4. error: reports a system failure, timeout, crash, or unavailable service.
5. simple: a general question answerable without tools or actions.

Do not use scenario IDs; decide from the request itself."""
    result = classifier.invoke(
        [
            ("system", prompt),
            ("human", f"Support request: {state.get('query', '')}"),
        ]
    )
    classification = (
        result if isinstance(result, Classification) else Classification.model_validate(result)
    )
    risk_level = "high" if classification.route == "risky" else "low"
    return {
        "route": classification.route,
        "risk_level": risk_level,
        "events": [
            make_event(
                "classify",
                "completed",
                "intent classified",
                route=classification.route,
                rationale=classification.rationale,
            )
        ],
    }


def tool_node(state: AgentState) -> dict[str, object]:
    """Execute a deterministic mock support tool, including transient failures."""
    attempt = int(state.get("attempt", 0))
    route = str(state.get("route", ""))
    if route == "error" and attempt < 2:
        result = f"ERROR: transient service timeout on attempt {attempt}"
        event_type = "failed"
    elif route == "risky":
        result = "SUCCESS: approved requested action was queued for secure execution"
        event_type = "completed"
    else:
        result = f"SUCCESS: tool lookup completed for request: {state.get('query', '')}"
        event_type = "completed"
    return {
        "tool_results": [result],
        "events": [
            make_event(
                "tool",
                event_type,
                "mock tool executed",
                attempt=attempt,
                result_status="error" if result.startswith("ERROR") else "success",
            )
        ],
    }


def evaluate_node(state: AgentState) -> dict[str, object]:
    """Gate the retry loop by evaluating the latest mock-tool result."""
    results = state.get("tool_results", [])
    latest = results[-1] if results else "ERROR: no tool result"
    evaluation_result = "needs_retry" if "ERROR" in latest.upper() else "success"
    return {
        "evaluation_result": evaluation_result,
        "events": [
            make_event(
                "evaluate",
                "completed",
                "tool result evaluated",
                evaluation_result=evaluation_result,
            )
        ],
    }


def answer_node(state: AgentState) -> dict[str, object]:
    """Generate a helpful, grounded final response through the configured LLM."""
    tool_results = state.get("tool_results", [])
    approval = state.get("approval")
    context = "\n".join(f"- {result}" for result in tool_results) or "- No tool was needed."
    approval_context = approval if approval is not None else "No approval was required."
    response = get_llm().invoke(
        [
            (
                "system",
                "You are a careful support agent. Answer only using the supplied request and "
                "context. Do not claim an action was performed unless the context says SUCCESS. "
                "Keep the answer concise and state any limitation clearly.",
            ),
            (
                "human",
                f"Request:\n{state.get('query', '')}\n\nTool context:\n{context}\n\n"
                f"Approval context:\n{approval_context}",
            ),
        ]
    )
    final_answer = _response_text(response)
    return {
        "final_answer": final_answer,
        "events": [make_event("answer", "completed", "grounded response generated")],
    }


def ask_clarification_node(state: AgentState) -> dict[str, object]:
    """Ask for the minimum information needed to safely continue."""
    question = (
        "Could you share the affected account or order, what happened, and the exact error "
        f"or outcome you need help with? Your request was: {state.get('query', '')}"
    )
    return {
        "pending_question": question,
        "final_answer": question,
        "events": [make_event("clarify", "completed", "clarification requested")],
    }


def risky_action_node(state: AgentState) -> dict[str, object]:
    """Describe a side-effecting action before it can reach a tool."""
    proposed_action = f"Proposed action requiring human approval: {state.get('query', '')}"
    return {
        "proposed_action": proposed_action,
        "events": [make_event("risky_action", "pending_approval", "risky action prepared")],
    }


def approval_node(state: AgentState) -> dict[str, object]:
    """Collect an approval decision, with deterministic offline approval by default."""
    interrupt_enabled = os.getenv("LANGGRAPH_INTERRUPT", "false").lower() == "true"
    if interrupt_enabled:
        from langgraph.types import interrupt

        decision = interrupt(
            {
                "kind": "approval_required",
                "proposed_action": state.get("proposed_action", ""),
            }
        )
        if isinstance(decision, dict):
            approved = bool(decision.get("approved", False))
            reviewer = str(decision.get("reviewer", "human-reviewer"))
            comment = str(decision.get("comment", "interactive decision"))
        else:
            approved = bool(decision)
            reviewer = "human-reviewer"
            comment = "interactive decision"
    else:
        approved = True
        reviewer = "mock-reviewer"
        comment = "Approved automatically for repeatable offline scenarios"
    approval = {"approved": approved, "reviewer": reviewer, "comment": comment}
    return {
        "approval": approval,
        "events": [
            make_event(
                "approval",
                "approved" if approved else "rejected",
                "approval decision recorded",
                reviewer=reviewer,
            )
        ],
    }


def retry_or_fallback_node(state: AgentState) -> dict[str, object]:
    """Increment a bounded retry counter and retain an audit trail."""
    attempt = int(state.get("attempt", 0)) + 1
    error = f"Retry attempt {attempt} recorded for route {state.get('route', '')}"
    return {
        "attempt": attempt,
        "errors": [error],
        "events": [
            make_event("retry", "scheduled", "retry or fallback evaluated", attempt=attempt)
        ],
    }


def dead_letter_node(state: AgentState) -> dict[str, object]:
    """Finish unresolvable requests after the retry bound is exhausted."""
    message = (
        "We could not complete this request after the allowed retry attempts. "
        "It has been recorded for support follow-up."
    )
    return {
        "final_answer": message,
        "errors": ["Request moved to dead letter after retry limit"],
        "events": [make_event("dead_letter", "completed", "retry limit exhausted")],
    }


def finalize_node(state: AgentState) -> dict[str, object]:
    """Emit the mandatory terminating audit event for every graph path."""
    return {
        "events": [
            make_event(
                "finalize",
                "completed",
                "workflow finished",
                route=str(state.get("route", "")),
            )
        ]
    }
