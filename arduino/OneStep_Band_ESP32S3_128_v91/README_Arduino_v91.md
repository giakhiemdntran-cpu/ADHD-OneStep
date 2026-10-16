# OneStep Band ESP32-S3 v9.1

Board:
- Waveshare ESP32-S3-Touch-LCD-1.28
- GC9A01A 240x240
- CST816S touch

## Libraries
- Arduino_GFX_Library
- ArduinoJson
- WiFi (ESP32 core)
- HTTPClient (ESP32 core)
- Wire (ESP32 core)

## Arduino IDE board
Chọn: ESP32S3 Dev Module

## Sửa trước khi upload
Trong file `.ino`:
```cpp
const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASSWORD = "YOUR_PASSWORD";
const char* SERVER = "http://IP_JETSON:5000";
```

## Memory Coaching
- MEMORY2: hiện rõ task, nút NHO / XONG / KHONG
- MEMORY1: chỉ báo có một việc, không lộ tên task, nút NHO / KHONG
- MEMORY0: chỉ xuất hiện sau delayed check, nút XONG / NHO (nhưng chưa làm) / KHONG

## Nút BACK
BACK đã được làm lớn và đưa vào trong:
- tâm ~ (38,36)
- bán kính 25px
- hitbox lớn hơn vùng hiển thị

## Backend mode
Ở Jetson:
```bash
export ADHD_MODE_ENABLED=1
export COACHING_DEVICE_MODE=band
python start.py
```

Hoặc:
```bash
export COACHING_DEVICE_MODE=both
```

`home` sẽ không gửi reminder sang Band.

## Level 1
Bấm NHO trên Band ở Level 1 chỉ là self-report. Backend KHÔNG giảm 1→0 từ nút này,
vì Band không thể kiểm tra người dùng có recall đúng tên task hay không.
Muốn giảm 1→0, người dùng cần trả lời tên task qua Buddy.

## Level 0
v9.1 backend đã bổ sung MEMORY0 cho Band:
- đến giờ: không rung, không popup
- sau `MEMORY_LEVEL0_CHECK_DELAY_MINUTES`: Band mới nhận MEMORY0 self-check.
