# ADHD OneStep 

## Hướng dẫn tổng quan, cài đặt và chạy các dịch vụ

ADHD OneStep là hệ thống trợ lý nhận thức cá nhân gồm **OneStep Buddy**, **OneBand**, giao diện quản trị web, các dịch vụ giọng nói/thị giác và **Mô hình hành vi nhận thức cá nhân (PCBM)**.

Phiên bản này đã được refactor theo hướng mã nguồn tiếng Việt để thuận tiện cho việc học, trình bày và bảo trì. Tên bảng/cột SQLite, API, biến môi trường và định dạng dữ liệu vẫn được giữ ổn định để tương thích với dữ liệu cũ.

> **Lưu ý:** OneStep là hệ thống hỗ trợ quản lý nhiệm vụ và hành vi. PCBM chỉ tạo dự đoán/khuyến nghị hỗ trợ, không dùng để chẩn đoán ADHD hoặc đưa ra quyết định y khoa.

---

## 1. Thành phần chính

Hệ thống gồm các khối sau:

```text
Người dùng
   │
   ├── OneStep Buddy
   │      ├── Nhận dạng giọng nói
   │      ├── Tổng hợp giọng nói
   │      ├── Qwen qua Ollama
   │      ├── Quản lý nhiệm vụ
   │      └── Thị giác máy tính
   │
   ├── OneBand ESP32-S3
   │      └── Nhắc việc / phản hồi Memory Coaching
   │
   ├── Flask API + SQLite
   │      └── storage/onestep.db
   │
   ├── Giao diện quản trị Streamlit
   │
   └── PCBM
          ├── Dự đoán khả năng tự nhớ
          └── Dự đoán khả năng hoàn thành trong 30 phút
```

### Dịch vụ và cổng mặc định

| Thành phần | Lệnh chạy | Địa chỉ mặc định |
|---|---|---|
| Buddy + Flask API | `python khoi_dong.py` | `http://127.0.0.1:5000` |
| Giao diện quản trị | `python khoi_dong_quan_tri.py` | `http://127.0.0.1:8501` |
| Ollama | `ollama serve` | `http://127.0.0.1:11434` |

Nếu truy cập từ máy khác cùng mạng LAN, thay `127.0.0.1` bằng địa chỉ IP của Jetson.

---

## 2. Cấu trúc thư mục chính

```text
ADHD_OneStep_Buddy_OneBand_v9_9_3_Refactor_Code_TiengViet/
│
├── khoi_dong.py                 # Khởi động Buddy + Flask API
├── khoi_dong_quan_tri.py        # Khởi động giao diện Streamlit
├── giao_dien_quan_tri.py        # Giao diện quản trị
├── cau_hinh.py                  # Cấu hình toàn hệ thống
├── requirements.txt
│
├── tro_ly/                      # Ứng dụng Buddy và định tuyến ý định
├── dich_vu/                     # Các dịch vụ hệ thống
├── may_chu_web/                 # Flask API
├── huan_luyen_pcbm/             # Pipeline huấn luyện PCBM
├── cong_cu/                     # Script kiểm thử / nhập dữ liệu
│
├── arduino/                     # Firmware OneBand ESP32-S3
├── data/                        # Dữ liệu mẫu PCBM
├── models/                      # Model PCBM đã huấn luyện
├── storage/                     # SQLite + dữ liệu sinh trong quá trình chạy
└── faces/                       # Ảnh biểu cảm Buddy
```

---

## 3. Yêu cầu môi trường

Khuyến nghị:

- Ubuntu 22.04 / Jetson JetPack phù hợp.
- Python 3.10 trở lên.
- Ollama đang chạy cục bộ nếu sử dụng Qwen.
- Camera USB/CSI nếu bật chức năng thị giác.
- Microphone và loa nếu sử dụng giao tiếp giọng nói.
- OneBand là tùy chọn; hệ thống có thể chạy ở chế độ chỉ Buddy.

Các thư viện Python chính được khai báo trong `requirements.txt`, gồm Flask, PySide6, Streamlit, OpenCV, Ultralytics, scikit-learn, SpeechRecognition, Edge TTS và các thư viện hỗ trợ khác.

---

## 4. Cài đặt

### 4.1. Giải nén và vào thư mục dự án

```bash
cd ADHD_OneStep_Buddy_OneBand_v9_9_3_Refactor_Code_TiengViet
```

### 4.2. Tạo môi trường Python riêng

Khuyến nghị dùng virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Nâng cấp pip:

```bash
python -m pip install --upgrade pip
```

### 4.3. Cài thư viện Python

```bash
pip install -r requirements.txt
```

### 4.4. Cài và chuẩn bị Ollama

Kiểm tra Ollama:

```bash
ollama --version
```

Model mặc định trong `cau_hinh.py` là:

```text
qwen2.5:3b
```

Tải model:

```bash
ollama pull qwen2.5:3b
```

Khởi động Ollama:

```bash
ollama serve
```

Nếu Ollama đã được cấu hình chạy như một service thì không cần mở thêm tiến trình `ollama serve`.

Kiểm tra:

```bash
curl http://127.0.0.1:11434/api/tags
```

---

## 5. Cấu hình quan trọng

Cấu hình mặc định nằm trong:

```text
cau_hinh.py
```

Có thể thay đổi một số tùy chọn bằng biến môi trường trước khi chạy.

### 5.1. Ollama

```bash
export OLLAMA_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=qwen2.5:3b
```

### 5.2. Chế độ Memory Coaching

Bật cơ chế huấn luyện ghi nhớ:

```bash
export ADHD_MODE_ENABLED=1
```

Chỉ dùng Buddy:

```bash
export COACHING_DEVICE_MODE=home
```

Chỉ ưu tiên OneBand:

```bash
export COACHING_DEVICE_MODE=band
```

Buddy + OneBand:

```bash
export COACHING_DEVICE_MODE=both
```

### 5.3. PCBM

Bật PCBM:

```bash
export PCBM_ENABLED=1
```

Mặc định PCBM chỉ **dự đoán, ghi log và đưa khuyến nghị**, chưa tự thay đổi mức nhắc:

```bash
export PCBM_APPLY_PROMPT_LEVEL=0
```

Chỉ khi muốn thử nghiệm cho PCBM thực sự tác động đến mức nhắc:

```bash
export PCBM_APPLY_PROMPT_LEVEL=1
```

Khuyến nghị giữ `0` trong khi demo và đánh giá mô hình để dễ kiểm soát hành vi hệ thống.

### 5.4. Thị giác máy tính

Bật/tắt:

```bash
export VISION_ENABLED=1
```

Camera USB:

```bash
export VISION_CAMERA_SOURCE=usb
export VISION_CAMERA_ID=0
```

Camera CSI trên Jetson:

```bash
export VISION_CAMERA_SOURCE=csi
export VISION_CSI_SENSOR_ID=0
```

Nếu muốn buộc phần thị giác dùng CPU:

```bash
export VISION_DEVICE=cpu
export VISION_HALF=0
```

Nếu dùng GPU và môi trường CUDA/PyTorch của Jetson hoạt động đúng:

```bash
export VISION_DEVICE=0
```

### 5.5. Giao diện quản trị

```bash
export ONESTEP_API_URL=http://127.0.0.1:5000
export ONESTEP_ADMIN_PORT=8501
```

Đặt mật khẩu quản trị nếu cần:

```bash
export ONESTEP_ADMIN_PASSWORD='mat-khau-cua-ban'
```

Nếu không đặt `ONESTEP_ADMIN_PASSWORD`, giao diện quản trị không yêu cầu mật khẩu.

---

## 6. Cách chạy hệ thống

Khuyến nghị mở **3 terminal**.

### Terminal 1 – Ollama

```bash
ollama serve
```

Có thể bỏ qua terminal này nếu Ollama đã chạy dưới dạng service.

### Terminal 2 – OneStep Buddy + Flask API

```bash
cd ADHD_OneStep_Buddy_OneBand_v9_9_3_Refactor_Code_TiengViet
source .venv/bin/activate
python khoi_dong.py
```

Lệnh này khởi động:

- Flask API ở cổng `5000`;
- ứng dụng OneStep Buddy;
- các dịch vụ nhiệm vụ, giọng nói, Memory Coaching, PCBM và thị giác theo cấu hình hiện tại.

Kiểm tra API:

```bash
curl http://127.0.0.1:5000/api/health
```

### Terminal 3 – Giao diện quản trị

```bash
cd ADHD_OneStep_Buddy_OneBand_v9_9_3_Refactor_Code_TiengViet
source .venv/bin/activate
python khoi_dong_quan_tri.py
```

Hoặc:

```bash
./run_admin.sh
```

Mở trình duyệt:

```text
http://127.0.0.1:8501
```

Trên máy khác cùng mạng:

```text
http://<IP_JETSON>:8501
```

---

## 7. Chạy nhanh ở chế độ chỉ Buddy

Đây là cấu hình đơn giản nhất để demo khi chưa cần OneBand:

```bash
export ADHD_MODE_ENABLED=1
export COACHING_DEVICE_MODE=home
export PCBM_ENABLED=1
export PCBM_APPLY_PROMPT_LEVEL=0
python khoi_dong.py
```

Terminal khác:

```bash
python khoi_dong_quan_tri.py
```

---

## 8. Chạy Buddy + OneBand

Firmware OneBand nằm tại:

```text
arduino/OneStep_Band_ESP32S3_128_v91/OneStep_Band_ESP32S3_128_v91.ino
```

Sau khi nạp firmware cho ESP32-S3, chạy backend với:

```bash
export ADHD_MODE_ENABLED=1
export COACHING_DEVICE_MODE=both
python khoi_dong.py
```

Nếu chỉ muốn ưu tiên OneBand:

```bash
export COACHING_DEVICE_MODE=band
python khoi_dong.py
```

Memory Coaching sử dụng mức hỗ trợ:

```text
Level 2 → nhắc rõ nhiệm vụ
Level 1 → gợi ý chung, yêu cầu người dùng tự nhớ
Level 0 → không nhắc ngay; kiểm tra lại sau một khoảng thời gian
```

---

## 9. PCBM – Mô hình hành vi nhận thức cá nhân

PCBM sử dụng lịch sử sự kiện để xây dựng hai bài toán dự đoán:

1. **Khả năng người dùng tự nhớ nhiệm vụ**.
2. **Khả năng người dùng hoàn thành nhiệm vụ trong 30 phút**.

Model mặc định được lưu tại:

```text
models/pcbm_recall.joblib
models/pcbm_completion.joblib
models/pcbm_model_meta.json
```

Dữ liệu hành vi được lưu trong SQLite:

```text
storage/onestep.db
```

### Huấn luyện từ SQLite bằng giao diện

1. Chạy `python khoi_dong.py`.
2. Chạy `python khoi_dong_quan_tri.py`.
3. Mở trang **AI nhận thức cá nhân**.
4. Chọn **Huấn luyện mô hình cá nhân từ dữ liệu SQLite**.

API tương ứng:

```bash
curl -X POST http://127.0.0.1:5000/api/pcbm/train-db
```

### Nạp lại bộ 4.133 sự kiện thử nghiệm

Giao diện quản trị có chức năng nạp lại bộ dữ liệu thử nghiệm từ:

```text
data/sample_events_4133.jsonl
```

Hoặc có thể dùng script trong thư mục `cong_cu/`.

Bộ dữ liệu này là **dữ liệu mô phỏng để kiểm chứng pipeline**, không phải dữ liệu bệnh án hoặc dữ liệu thực nghiệm lâm sàng.

---

## 10. Các API PCBM quan trọng

```text
GET  /api/pcbm/status
POST /api/pcbm/train-sample
POST /api/pcbm/train-db
GET  /api/pcbm/recommend/current
GET  /api/pcbm/events
GET  /api/pcbm/predictions
```

Kiểm tra trạng thái:

```bash
curl http://127.0.0.1:5000/api/pcbm/status
```

---

## 11. Kiểm thử nhanh

Các script kiểm thử nằm trong:

```text
cong_cu/
```

Ví dụ:

### Kiểm thử trích xuất thông tin

```bash
python cong_cu/kiem_thu_trich_xuat_thong_tin_v97.py
```

### Kiểm thử Memory Coaching

```bash
python cong_cu/kiem_thu_huan_luyen_ghi_nho_v9.py
```

### Kiểm thử PCBM + SQLite

```bash
python cong_cu/kiem_thu_huan_luyen_pcbm_csdl.py
```

### Kiểm thử API OneBand

```bash
python cong_cu/kiem_thu_api_vong_deo.py
```

---

## 12. Một số câu lệnh thử với Buddy

Có thể thử các câu như:

```text
Nhắc tôi học Toán lúc 7 giờ tối.
Nhắc tôi uống nước lúc 9 giờ 30.
Việc tiếp theo là gì?
Mình làm xong rồi.
Nhắc lại sau 10 phút.
Hủy nhiệm vụ này.
```

Sau đó theo dõi:

- nhiệm vụ trên giao diện quản trị;
- lịch sử sự kiện trong SQLite;
- mức Memory Coaching;
- các dự đoán PCBM.

---

## 13. Dừng hệ thống

Tại từng terminal, nhấn:

```text
Ctrl+C
```

Không nên dùng `Ctrl+Z` để dừng ứng dụng vì tiến trình có thể vẫn giữ thiết bị âm thanh.

Nếu cần kiểm tra tiến trình đang chạy:

```bash
ps aux | grep -E 'khoi_dong.py|streamlit|ollama'
```

---

## 14. Xử lý một số lỗi thường gặp

### Không kết nối được Ollama

Kiểm tra:

```bash
curl http://127.0.0.1:11434/api/tags
```

Sau đó kiểm tra model:

```bash
ollama list
```

### Giao diện quản trị báo không kết nối API

Kiểm tra Flask:

```bash
curl http://127.0.0.1:5000/api/health
```

Kiểm tra biến:

```bash
echo $ONESTEP_API_URL
```

### Camera không mở được

Thử camera USB khác:

```bash
export VISION_CAMERA_ID=1
```

Hoặc tạm tắt thị giác:

```bash
export VISION_ENABLED=0
```

### PyTorch/CUDA trên Jetson gặp lỗi

Có thể chạy phần thị giác bằng CPU để kiểm tra hệ thống trước:

```bash
export VISION_DEVICE=cpu
export VISION_HALF=0
```

### Thiết bị âm thanh đang bận

Dừng hoàn toàn các phiên OneStep cũ bằng `Ctrl+C`, sau đó kiểm tra:

```bash
fuser -v /dev/snd/*
```

---

## 15. Trình tự chạy khuyến nghị khi demo

```text
1. Khởi động Jetson
2. Kiểm tra microphone / loa / camera
3. Kiểm tra hoặc khởi động Ollama
4. Chạy python khoi_dong.py
5. Kiểm tra /api/health
6. Chạy python khoi_dong_quan_tri.py
7. Mở Streamlit trên cổng 8501
8. Kiểm tra trạng thái PCBM
9. Nếu dùng OneBand, kiểm tra kết nối thiết bị
10. Bắt đầu demo
```

---

## 16. Các tài liệu bổ sung

Các file README theo phiên bản được giữ lại để tra cứu chi tiết từng chức năng:

```text
README_v9_MEMORY_COACHING.md
README_v91_ONEBAND.md
README_v95_VISION_OBJECT_MEMORY.md
README_v97_HYBRID_PARSER.md
README_v971_AUDIO_SAFE.md
README_v98_STREAMLIT_ADMIN.md
README_v99_PCBM_INTEGRATED.md
README_v991_PCBM_SQLITE_TRAINING.md
README_v992_VIETNAMESE_UI.md
README_REFACTOR_CODE_TIENG_VIET.md
```

Một số README lịch sử có thể còn nhắc tên file/thư mục của phiên bản trước khi refactor. Khi chạy **v9.9.3 Refactor Code Tiếng Việt**, ưu tiên tên file và lệnh trong README tổng quan này.

---

## 17. Lệnh chạy tối thiểu cần nhớ

### Buddy + API

```bash
python khoi_dong.py
```

### Giao diện quản trị

```bash
python khoi_dong_quan_tri.py
```

### Ollama

```bash
ollama serve
```

### Kiểm tra API

```bash
curl http://127.0.0.1:5000/api/health
```

### Mở giao diện

```text
http://127.0.0.1:8501
```
