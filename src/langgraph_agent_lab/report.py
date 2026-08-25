"""Evidence-backed Markdown report generation for the lab."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from .metrics import MetricsReport


def _commit_id() -> str:
    """Read the local commit reference without invoking Git or exposing config."""
    root = Path(__file__).resolve().parents[2]
    head_path = root / ".git" / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            ref_path = root / ".git" / head.removeprefix("ref: ")
            head = ref_path.read_text(encoding="utf-8").strip()
        return head[:12] if head else "unavailable"
    except OSError:
        return "unavailable"


def _cell(value: object) -> str:
    """Make a value safe for a compact Markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_report(metrics: MetricsReport) -> str:
    """Render a complete submission report from the measured metrics only."""
    student_name = os.getenv("STUDENT_NAME", "Dao Duy Hung")
    approval_required = sum(item.approval_required for item in metrics.scenario_metrics)
    approvals_observed = sum(item.approval_observed for item in metrics.scenario_metrics)
    dead_letters = sum(
        any("dead letter" in error.lower() for error in item.errors)
        for item in metrics.scenario_metrics
    )
    history_evidence = (
        "Sau mỗi run, CLI đã gọi `get_state_history(thread_id)` và nhận được history "
        "không rỗng cho mọi scenario."
        if metrics.resume_success
        else "Không có bằng chứng state history cho toàn bộ scenario trong lần chạy này."
    )
    if approvals_observed < approval_required:
        approval_analysis = f"""Có {approval_required} scenario yêu cầu approval nhưng chỉ
{approvals_observed} decision được quan sát. Run đã dừng ở human interrupt trước khi node
ghi decision, nên không risky action nào tới `tool`. Đây là containment fail-closed: graph
không tự thực thi side effect khi chưa có quyết định. Residual risk là CLI batch hiện chưa
resume interrupt để hoàn tất các scenario cần HITL."""
    else:
        approval_analysis = f"""Có {approval_required} scenario yêu cầu approval và
{approvals_observed} approval decision được quan sát. Với mọi decision rejected, conditional
edge đi tới `clarify → finalize`, do đó risky action không thể tới `tool`. Residual risk:
mock approval chỉ chứng minh luồng tự động; vẫn cần UI/resume cho reviewer thật."""
    rows = "\n".join(
        "| {scenario} | {expected} | {actual} | {success} | {retry} | {interrupt} | "
        "{latency} |".format(
            scenario=_cell(item.scenario_id),
            expected=_cell(item.expected_route),
            actual=_cell(item.actual_route or "n/a"),
            success="Có" if item.success else "Không",
            retry=item.retry_count,
            interrupt=item.interrupt_count,
            latency=item.latency_ms,
        )
        for item in metrics.scenario_metrics
    )
    return f"""# Day 08 Lab Report

## 1. Team / student

- Name: {student_name}
- Repo/commit: `day08-langgraph-agent-lab` / `{_commit_id()}`
- Date: {date.today().isoformat()}

Report này được sinh tự động từ `outputs/metrics.json`; không chứa environment dump,
API key, database credential hoặc secret.

## 2. Architecture

Workflow có 11 node: `intake`, `classify`, `tool`, `evaluate`, `answer`, `clarify`,
`risky_action`, `approval`, `retry`, `dead_letter`, và `finalize`.

Fixed edges là `START → intake → classify`, `tool → evaluate`,
`risky_action → approval`, cùng `answer|clarify|dead_letter → finalize → END`.
Conditional edges là `classify` (chọn route), `evaluate` (success/retry), `retry`
(bounded retry/dead-letter), và `approval` (approved/rejected). Vì mọi nhánh terminal
đều phải đi qua `finalize`, graph có termination rõ ràng.

## 3. State schema

| Field | Reducer | Lý do |
|---|---|---|
| `messages`, `tool_results`, `errors`, `events` | append (`add`) | Giữ audit trail và nhiều lần tool/retry, không ghi đè evidence cũ. |
| `route`, `risk_level`, `attempt`, `evaluation_result` | overwrite | Phản ánh quyết định/trạng thái hiện tại của workflow. |
| `final_answer`, `pending_question`, `proposed_action`, `approval` | overwrite | Chỉ cần outcome/decision mới nhất, vẫn có event append-only để audit. |
| `thread_id`, `scenario_id`, `query`, `max_attempts` | overwrite/immutable by convention | Định danh run và ràng buộc retry của scenario. |

## 4. Scenario results

| Metric | Observed value |
|---|---:|
| Total scenarios | {metrics.total_scenarios} |
| Success rate | {metrics.success_rate:.2%} |
| Average nodes visited | {metrics.avg_nodes_visited:.2f} |
| Total retries | {metrics.total_retries} |
| Total approval/HITL events | {metrics.total_interrupts} |
| State-history recovery evidence | {"Có" if metrics.resume_success else "Không"} |

| Scenario | Expected route | Actual route | Success | Retries | Interrupts | Latency (ms) |
|---|---|---|---:|---:|---:|---:|
{rows}

## 5. Failure analysis

1. **Transient tool failure → bounded retry/dead-letter.** Lỗi được mô phỏng tại
   `tool` bằng result bắt đầu `ERROR`; `evaluate` ghi `evaluation_result=needs_retry`
   và điều hướng vào `retry`. `attempt` tăng, event `retry` và danh sách `errors`
   là tín hiệu audit. Khi `attempt >= max_attempts`, graph chuyển sang `dead_letter`
   rồi `finalize`, nên không thể loop vô hạn. Lần chạy này ghi nhận
   {metrics.total_retries} retry và {dead_letters} dead-letter. Residual risk: tool mock
   chưa có retry backoff/jitter hoặc phân loại lỗi provider thật.

2. **Risky action không có approval hợp lệ.** Route `risky` bắt buộc qua
   `risky_action` rồi `approval` trước khi có thể tới `tool`; `proposed_action`,
   `approval` và event approval là tín hiệu audit. {approval_analysis}

## 6. Persistence / recovery evidence

Mỗi scenario được invoke với `configurable.thread_id = thread-<scenario_id>` và
checkpointer từ config. {history_evidence} Đây là proof cho checkpoint/state history,
không chỉ là tuyên bố đã khởi tạo `MemorySaver`. Checkpointer SQLite cũng được hỗ trợ
khi cài extra `.[sqlite]`; nó bật WAL, nhưng không được claim là đã chạy trong report
này trừ khi config thực sự chọn `sqlite`.

## 7. Extension work

Không claim bonus extension chưa chạy. Khả năng đã triển khai nhưng chưa được tính là
evidence trong run này: SQLite checkpointer và `LANGGRAPH_INTERRUPT=true` cho human
approval thật. Evidence được ghi ở report chỉ là state history do cấu hình hiện tại tạo ra.

## 8. Improvement plan

Ưu tiên productionize tiếp theo là durable SQLite/Postgres checkpointer cùng CLI/UI resume
cho human approval và test sau process restart. Core graph hiện đã có route, bounded retry,
audit events và metrics; completion an toàn của HITL/recovery là khoảng trống còn lại có ảnh
hưởng trực tiếp tới thao tác side-effecting.
"""


def write_report(metrics: MetricsReport, output_path: str | Path) -> None:
    """Write the metrics-derived report to the configured submission path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(metrics), encoding="utf-8")
