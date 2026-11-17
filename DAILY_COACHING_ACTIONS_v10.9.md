# OneStep v10.9 — Daily Coaching Plan tương tác

Nâng cấp trực tiếp từ ZIP v10.8 TOUCH_KEYBOARD_OFF. Giữ nguyên cấu hình chặn bàn phím cảm ứng.

## Chạy

Khởi động như v10.8 theo README hiện tại. Vào **Demo Coaching Mode**, chọn A/B/C và nhấn **Bắt đầu Demo**. Trên trang mặt robot, nhấn dải vàng **🗓 Gợi ý hôm nay (chạm để thao tác)**. Chọn từng gợi ý, sau đó chọn Bắt đầu ngay / Nhắc lại sau / Đã hoàn thành / Bỏ qua.

- Mỗi hồ sơ A/B/C lưu riêng trong `demo_coaching/daily_actions.sqlite3` (tạo tự động khi chạy).
- Reset hồ sơ trong Demo Coaching Mode cũng xóa các thao tác gợi ý của hồ sơ đó.
- Bắt đầu demo cũng reset trạng thái để tái hiện demo nhất quán, giống luồng demo hiện có.
- Khi hoãn, có thể chọn 1–1440 phút. Khi hết giờ, dải vàng hiện biểu tượng 🔔 và bật hộp thoại nhắc lại (nếu giao diện chính đang hiển thị).
- Các nút chỉ ghi dữ liệu **demo**, không ghi `pcbm_events`, `pcbm_predictions`, task thật hay phát sinh sự kiện coaching giả.
- Tên gợi ý và lời coaching lấy từ `demo_coaching/profiles.json`.
- Trạng thái gợi ý gắn với ngày hiện tại (ngày mới tự có gợi ý mới).

## Các file sửa

- `tro_ly/ung_dung.py`: chuyển dải vàng thành nút, mở dialog, quản lý timer.
- `tro_ly/daily_coaching_widget.py`: giao diện 4 thao tác.
- `dich_vu/coaching_actions.py`: lưu trạng thái, lịch sử và reset riêng theo hồ sơ.
- `VERSION.txt`, tài liệu này.

## Lưu ý

Đây là tương tác với **gợi ý mô phỏng**, không phải tương tác với task thật. Chức năng nhắc lại dựa trên timer của UI; không gửi qua OneBand/Telegram hoặc nhắc khi ứng dụng tắt. Không thay đổi tính năng PCBM hay voice coaching gốc.
