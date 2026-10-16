import threading
import time

# Một khóa âm thanh dùng chung toàn tiến trình cho STT và TTS.
# Khóa này ngăn PortAudio/sounddevice và pygame/ALSA chiếm card âm thanh cùng lúc.
audio_lock = threading.RLock()

# Khoảng chờ ngắn giúp ALSA/PortAudio giải phóng thiết bị ổn định hơn trên Jetson.
INPUT_RELEASE_DELAY = 0.30
OUTPUT_RELEASE_DELAY = 0.35


def sau_dau_vao_giai_phong():
    time.sleep(INPUT_RELEASE_DELAY)


def sau_dau_ra_giai_phong():
    time.sleep(OUTPUT_RELEASE_DELAY)
