# Demo Coaching Mode - v10.7

- 3 hồ sơ demo tách riêng khỏi SQLite thật.
- Hồ sơ A (DEMO_STABLE): lịch sử tự nhớ tốt -> thường minh họa đề xuất giảm hỗ trợ.
- Hồ sơ B (DEMO_BALANCED): lịch sử trung bình -> thường minh họa giữ mức.
- Hồ sơ C (DEMO_NEEDS_SUPPORT): lịch sử khó khăn hơn -> thường minh họa tăng hỗ trợ.
- Dữ liệu seed: `demo_coaching/demo_profiles.jsonl`.
- Mỗi lần Reset Demo: lịch sử trong RAM quay về seed ban đầu.
- Demo không ghi vào `pcbm_events`, `pcbm_predictions` hoặc task thật.
- Model PCBM thật vẫn được dùng để tính xác suất và đề xuất Level.

Luồng: generic cue -> recall -> coaching bắt đầu nhỏ -> hesitation/start -> recovery khi mất tập trung -> complete -> PCBM đánh giá lại.
