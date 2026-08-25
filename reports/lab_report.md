# Day 08 Lab Report

## 1. Team / student

- Name: Dao Duy Hung
- Repo/commit: `day08-langgraph-agent-lab` / `6d8252d3c349`
- Date: 2026-08-25

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
| Total scenarios | 7 |
| Success rate | 71.43% |
| Average nodes visited | 5.00 |
| Total retries | 3 |
| Total approval/HITL events | 0 |
| State-history recovery evidence | Có |

| Scenario | Expected route | Actual route | Success | Retries | Interrupts | Latency (ms) |
|---|---|---|---:|---:|---:|---:|
| S01_simple | simple | simple | Có | 0 | 0 | 7885 |
| S02_tool | tool | tool | Có | 0 | 0 | 7614 |
| S03_missing | missing_info | missing_info | Có | 0 | 0 | 4308 |
| S04_risky | risky | risky | Không | 0 | 0 | 4491 |
| S05_error | error | error | Có | 2 | 0 | 41603 |
| S06_delete | risky | risky | Không | 0 | 0 | 4135 |
| S07_dead_letter | error | error | Có | 1 | 0 | 5563 |

## 5. Failure analysis

1. **Transient tool failure → bounded retry/dead-letter.** Lỗi được mô phỏng tại
   `tool` bằng result bắt đầu `ERROR`; `evaluate` ghi `evaluation_result=needs_retry`
   và điều hướng vào `retry`. `attempt` tăng, event `retry` và danh sách `errors`
   là tín hiệu audit. Khi `attempt >= max_attempts`, graph chuyển sang `dead_letter`
   rồi `finalize`, nên không thể loop vô hạn. Lần chạy này ghi nhận
   3 retry và 1 dead-letter. Residual risk: tool mock
   chưa có retry backoff/jitter hoặc phân loại lỗi provider thật.

2. **Risky action không có approval hợp lệ.** Route `risky` bắt buộc qua
   `risky_action` rồi `approval` trước khi có thể tới `tool`; `proposed_action`,
   `approval` và event approval là tín hiệu audit. Có 2 scenario yêu cầu approval nhưng chỉ
0 decision được quan sát. Run đã dừng ở human interrupt trước khi node
ghi decision, nên không risky action nào tới `tool`. Đây là containment fail-closed: graph
không tự thực thi side effect khi chưa có quyết định. Residual risk là CLI batch hiện chưa
resume interrupt để hoàn tất các scenario cần HITL.

## 6. Persistence / recovery evidence

Mỗi scenario được invoke với `configurable.thread_id = thread-<scenario_id>` và
checkpointer từ config. Sau mỗi run, CLI đã gọi `get_state_history(thread_id)` và nhận được history không rỗng cho mọi scenario. Đây là proof cho checkpoint/state history,
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
