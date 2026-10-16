# ADHD OneStep v9 changes

- Prompt fading đổi từ 3→2→1→0 thành **2→1→0**.
- Level 2: nhắc rõ task và hỏi nhớ/không nhớ/đã làm.
- Level 1: chỉ nói “Bạn có một việc cần làm”; nếu người dùng nói nhớ thì yêu cầu recall tên việc.
- Level 0: không nhắc tại thời điểm task; sau 10 phút mới kiểm tra đã nhớ/làm chưa.
- Một lần quên ở level 1 không tăng lại level 2; mặc định 3 lần quên liên tiếp mới tăng.
- Level 0 mặc định 2 lần quên liên tiếp mới tăng lên level 1.
- Câu trả lời nhớ/không nhớ, recall text và execution result được lưu vào `memory_checks`.
- `habit_profiles` thêm memory success/failure streak và kết quả gần nhất.
- Home mode mặc định không push notification sang OneBand.
- Band backend vẫn hỗ trợ REMEMBER/FORGOT/DONE khi chuyển `COACHING_DEVICE_MODE=band|both`.
- Normal task vẫn là 1 bước ngắn; chỉ `coach_task` mới chia nhỏ bằng Qwen.
- Vision YOLO event-driven của v8 được giữ nguyên.
