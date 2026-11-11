# Robot Buddy – PCBM Coaching Flow Update

Bổ sung luồng demo đầy đủ cho PCBM:

1. Tạo nhiệm vụ -> ghi `TASK_CREATED` + `SUPPORT_RECOMMENDED`.
2. Hỏi mức hỗ trợ -> Buddy đọc Current Level + Recommended Level từ model thật.
3. Hỏi “Tại sao?” -> giải thích từ feature/history thật, không để LLM bịa số liệu.
4. Người dùng chấp nhận -> mới ghi `SUPPORT_ACCEPTED` và đổi Current Level.
5. Level 0 + user chủ động bắt đầu -> ghi `USER_REMEMBERED`.
6. Hoàn thành -> ghi `TASK_COMPLETED`.
7. “Lần này Buddy đánh giá thế nào?” -> tổng kết session.
8. Feedback “vừa đủ/quá nhiều/chưa đủ” -> ghi `REMINDER_FEEDBACK`.

Current Level được lưu theo từng user trong `storage/user_settings.json` tại `pcbm_support_levels`.
Mặc định `test_U036 = Level 1`.
