# OneStep v10.9.1 — fix màn hình bị che/cắt (800 × 480)

## Triệu chứng
Ảnh chụp có Terminal màu tím che từ khoảng y=364 xuống dưới. Bản sửa đặt cửa sổ fullscreen luôn ở phía trước và thu gọn vùng mặt/PCBM/footer. Thanh nút phía trên cuộn ngang khi màn hình hẹp để nút Thoát vẫn truy cập được.

## Cài trên phiên bản v10.9 (đã nâng từ v10.6 hoặc bản v10.9 ZIP)
1. Sao lưu thư mục dự án.
2. Giải nén patch sang một thư mục riêng.
3. Chạy từ thư mục patch:
   `python apply_patch.py --target /path/to/ADHD_OneStep_v10.6 --dry-run`
   `python apply_patch.py --target /path/to/ADHD_OneStep_v10.6`
   (Nếu giải nén bản v10.9 đầy đủ, thư mục có thể tên `ADHD_OneStep_v10.8`.)
4. Khởi động lại ứng dụng như trước.

Trình áp dụng chỉ thay `tro_ly/ung_dung.py` và sẽ từ chối file nguồn không khớp SHA256.
Backup tự động lưu ở `.backup_before_v10_9_1_display_fix/`.

## Kiểm tra
- Sau khi khởi động, Terminal không che phần dưới giao diện.
- Chuyển sang Demo A/B/C; dòng trạng thái và nhiệm vụ cuối trang vẫn thấy được.
- Thanh trên có thể cuộn ngang khi cửa sổ hẹp, sử dụng F2/F3/Ctrl+Q như cũ.
- Nhấn Gợi ý hôm nay -> 4 thao tác vẫn hoạt động.
- Chức năng tắt bàn phím ảo giữ nguyên.

Nếu Terminal vẫn phủ trên cửa sổ sau khi cập nhật, hãy kiểm tra chế độ "Always on top" của cửa sổ Terminal trong window manager / kiosk.
