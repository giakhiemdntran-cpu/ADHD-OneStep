from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "storage" / "onestep.db"
FACE_DIR = BASE_DIR / "faces"

HOST = "0.0.0.0"
PORT = 5000

DEFAULT_DELAY_MINUTES = 10
REMINDER_CHECK_MS = 2000

# Giọng nói / VAD thích nghi
AUTO_LISTEN = True
# Sample rate mục tiêu cho STT. Microphone được mở ở native sample rate rồi resample về giá trị này.
VOICE_SAMPLE_RATE = 16000
VOICE_BLOCK_SIZE = 1024
VOICE_START_TIMEOUT = 12.0
VOICE_SILENCE_DURATION = 1.2
VOICE_MAX_RECORD_SECONDS = 20.0
VOICE_NOISE_CALIBRATION_SECONDS = 0.8
VOICE_THRESHOLD_MULTIPLIER = 3.0
VOICE_MIN_THRESHOLD = 350
VOICE_MAX_THRESHOLD = 2500

# Ưu tiên STT trực tuyến; nếu lỗi thì dùng whisper.cpp dự phòng
STT_ONLINE_FIRST = True
WHISPER_EXE = BASE_DIR / "whisper.cpp" / "build" / "bin" / "whisper-cli"
WHISPER_MODEL = BASE_DIR / "whisper.cpp" / "models" / "ggml-base.bin"

# Ollama - mô hình ngôn ngữ chạy cục bộ
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_TIMEOUT = 90
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Ho_Chi_Minh")

# TTS - tổng hợp giọng nói
# Engine chính: VieNeu-TTS v3 Turbo streaming.
TTS_ENGINE = os.getenv("TTS_ENGINE", "vieneu").strip().lower()

# VieNeu v3 Turbo: PCM float32 native 48 kHz.
VIENEU_VOICE = os.getenv("VIENEU_VOICE", "Mai Anh")
VIENEU_BACKEND = os.getenv("VIENEU_BACKEND", "auto").strip().lower()
VIENEU_SAMPLE_RATE = 48000
VIENEU_START_BUFFER_MS = int(os.getenv("VIENEU_START_BUFFER_MS", "120"))
VIENEU_FIRST_AUDIO_TIMEOUT = float(os.getenv("VIENEU_FIRST_AUDIO_TIMEOUT", "2.0"))
VIENEU_STREAM_STALL_TIMEOUT = float(os.getenv("VIENEU_STREAM_STALL_TIMEOUT", "1.5"))
VIENEU_PRELOAD = os.getenv("VIENEU_PRELOAD", "1").lower() in {"1", "true", "yes", "on"}

# Fallback khi VieNeu lỗi trước khi phát được audio đầu tiên.
TTS_EDGE_FALLBACK = os.getenv("TTS_EDGE_FALLBACK", "1").lower() in {"1", "true", "yes", "on"}
TTS_PYTTSX3_FALLBACK = os.getenv("TTS_PYTTSX3_FALLBACK", "1").lower() in {"1", "true", "yes", "on"}
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "vi-VN-HoaiMyNeural")
EDGE_TTS_RATE = os.getenv("EDGE_TTS_RATE", "-5%")

# ---- v8: Thị giác máy tính ----
VISION_ENABLED = os.getenv("VISION_ENABLED", "1") == "1"
VISION_MODEL = os.getenv("VISION_MODEL", str(BASE_DIR / "models" / "yolov8n.pt"))
VISION_CAMERA_ID = int(os.getenv("VISION_CAMERA_ID", "0"))
VISION_CONFIDENCE = float(os.getenv("VISION_CONFIDENCE", "0.45"))
VISION_VERIFY_FRAMES = int(os.getenv("VISION_VERIFY_FRAMES", "3"))
VISION_FRAME_INTERVAL = float(os.getenv("VISION_FRAME_INTERVAL", "0.20"))
VISION_IMGSZ = int(os.getenv("VISION_IMGSZ", "640"))


# ---- v9.5: Tối ưu thị giác + bộ nhớ vật dụng ----
# USB: mở camera bằng cv2.VideoCapture(VISION_CAMERA_ID)
# CSI: dùng nvarguscamerasrc + GStreamer trên Jetson
VISION_CAMERA_SOURCE = os.getenv("VISION_CAMERA_SOURCE", "usb").strip().lower()
if VISION_CAMERA_SOURCE not in {"usb", "csi"}:
    VISION_CAMERA_SOURCE = "usb"

# Với YOLO .pt: đặt "0" để dùng CUDA GPU trên Jetson nếu PyTorch CUDA hoạt động.
# Với TensorRT .engine: Ultralytics sẽ dùng TensorRT engine.
VISION_DEVICE = os.getenv("VISION_DEVICE", "0")
VISION_HALF = os.getenv("VISION_HALF", "1") == "1"

VISION_CSI_SENSOR_ID = int(os.getenv("VISION_CSI_SENSOR_ID", "0"))
VISION_CSI_WIDTH = int(os.getenv("VISION_CSI_WIDTH", "1280"))
VISION_CSI_HEIGHT = int(os.getenv("VISION_CSI_HEIGHT", "720"))
VISION_CSI_FPS = int(os.getenv("VISION_CSI_FPS", "30"))

# Bộ nhớ vật dụng
VISION_RETENTION_HOURS = int(os.getenv("VISION_RETENTION_HOURS", "72"))
VISION_SIGHTING_DEDUPE_SECONDS = int(os.getenv("VISION_SIGHTING_DEDUPE_SECONDS", "60"))
VISION_SNAPSHOT_SECONDS = int(os.getenv("VISION_SNAPSHOT_SECONDS", "10"))
VISION_SNAPSHOT_LONG_SECONDS = int(os.getenv("VISION_SNAPSHOT_LONG_SECONDS", "30"))
VISION_SNAPSHOT_DIR = BASE_DIR / "storage" / "vision_snapshots"

# Không lưu video liên tục. Ảnh chụp chỉ phát sinh khi có một yêu cầu thị giác hữu ích.
VISION_SAVE_SNAPSHOTS = os.getenv("VISION_SAVE_SNAPSHOTS", "1") == "1"

# ---- v9: Huấn luyện ghi nhớ / giảm dần mức nhắc ----
# Khi bật, reminder được biến thành bài tập ghi nhớ 2 -> 1 -> 0.
ADHD_MODE_ENABLED = os.getenv("ADHD_MODE_ENABLED", "1") == "1"

# home: chỉ Buddy, không đẩy reminder sang OneBand
# band: ưu tiên OneBand

COACHING_DEVICE_MODE = os.getenv("COACHING_DEVICE_MODE", "home").strip().lower()
if COACHING_DEVICE_MODE not in {"home", "band", "both"}:
    COACHING_DEVICE_MODE = "home"

PROMPT_LEVEL_DEFAULT = 2
MEMORY_SUCCESS_TO_FADE = int(os.getenv("MEMORY_SUCCESS_TO_FADE", "3"))
MEMORY_LEVEL1_FAILURE_TO_RAISE = int(os.getenv("MEMORY_LEVEL1_FAILURE_TO_RAISE", "3"))
MEMORY_LEVEL0_FAILURE_TO_RAISE = int(os.getenv("MEMORY_LEVEL0_FAILURE_TO_RAISE", "2"))
MEMORY_LEVEL0_CHECK_DELAY_MINUTES = int(os.getenv("MEMORY_LEVEL0_CHECK_DELAY_MINUTES", "10"))


# ---------------- PCBM / Mô hình hành vi nhận thức cá nhân ----------------
PCBM_ENABLED = os.getenv("PCBM_ENABLED", "1").lower() in {"1", "true", "yes", "on"}
# Mặc định an toàn: mô hình chỉ dự đoán và ghi nhật ký; cơ chế huấn luyện ghi nhớ vẫn quyết định chính.
# Chỉ đặt bằng 1 khi muốn PCBM thực sự thay đổi mức nhắc.
PCBM_APPLY_PROMPT_LEVEL = os.getenv("PCBM_APPLY_PROMPT_LEVEL", "0").lower() in {"1", "true", "yes", "on"}
PCBM_SAMPLE_DATA = BASE_DIR / "data" / "sample_events.jsonl"
PCBM_RECALL_MODEL = BASE_DIR / "models" / "pcbm_recall.joblib"
PCBM_COMPLETION_MODEL = BASE_DIR / "models" / "pcbm_completion.joblib"
