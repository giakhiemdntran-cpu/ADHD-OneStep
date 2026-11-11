import json
import threading
from copy import deepcopy
from pathlib import Path

from cau_hinh import (
    BASE_DIR,
    VIENEU_START_BUFFER_MS,
    VIENEU_FIRST_AUDIO_TIMEOUT,
    VIENEU_STREAM_STALL_TIMEOUT,
    VIENEU_VOICE,
    VISION_CAMERA_SOURCE,
    VISION_CAMERA_ID,
    VISION_CSI_SENSOR_ID,
)

SETTINGS_PATH = BASE_DIR / "storage" / "user_settings.json"
_LOCK = threading.RLock()

DEFAULT_HELP_PROMPTS = {
    "Bắt đầu & tìm hiểu Buddy": [
        "Bạn là ai?",
        "Bạn có thể giúp mình những gì?",
        "Hôm nay bạn có thể hỗ trợ mình như thế nào?",
    ],
    "Tạo nhiệm vụ & chia nhỏ công việc": [
        "Nhắc mình làm bài tập lúc 7 giờ tối.",
        "Tạo nhiệm vụ hoàn thành báo cáo trước 4 giờ chiều.",
        "Giúp mình chia nhỏ việc dọn bàn học thành các bước.",
        "Mình cần hoàn thành bài thuyết trình trước ngày mai, hãy giúp mình lập các bước.",
    ],
    "Bắt đầu / hoàn thành / kiểm tra nhiệm vụ": [
        "Bắt đầu công việc hiện tại.",
        "Bây giờ mình cần làm việc gì?",
        "Mình đã hoàn thành bước này.",
        "Mình làm xong rồi.",
    ],
    "Hoãn hoặc hủy nhiệm vụ": [
        "Nhắc lại cho mình sau 5 phút.",
        "Để việc này sau 15 phút nhé.",
        "Hủy nhiệm vụ hiện tại.",
        "Không cần nhắc việc này nữa.",
    ],
    "Tập trung & ADHD coaching": [
        "Giúp mình bắt đầu việc này từng bước một.",
        "Mình đang bị mất tập trung, hãy giúp mình quay lại việc đang làm.",
        "Cho mình biết tiến độ luyện thói quen gần đây.",
        "Mức hỗ trợ hiện tại của em là bao nhiêu?",
        "Tại sao Buddy lại đề xuất mức hỗ trợ này?",
        "Được, Buddy có thể nhắc ít hơn.",
        "Mức nhắc này vừa đủ.",
        "Nhắc nhiều quá.",
        "Em cần nhắc rõ hơn.",
        "Lần này Buddy đánh giá thế nào?",
    ],
    "Camera – kiểm tra vật dụng": [
        "Kiểm tra giúp mình đã có đủ đồ dùng học tập chưa.",
        "Bạn có thấy đủ các vật dụng cần thiết không?",
        "Kiểm tra bàn học giúp mình.",
    ],
    "Camera – tìm đồ vật": [
        "Tìm giúp mình cây bút ở đâu.",
        "Bạn có thấy quyển vở của mình không?",
        "Tìm giúp mình điện thoại.",
        "Cái kính của mình đâu rồi?",
    ],
    "Camera – xem lại hình": [
        "Cho mình xem lại hình vừa chụp.",
        "Hiển thị hình vừa rồi lâu hơn.",
    ],
    "Hội thoại tự nhiên": [
        "Mình hơi mệt, giúp mình chọn một việc nhỏ để bắt đầu.",
        "Giải thích ngắn gọn việc mình đang cần làm.",
        "Khuyến khích mình hoàn thành bước tiếp theo nhé.",
    ],
}


DEFAULTS = {
    "active_user_id": "test_U036",
    "pcbm_support_levels": {"test_U036": 1},
    "audio_input_device": None,
    "audio_output_device": None,
    "camera_source": VISION_CAMERA_SOURCE,
    "camera_id": int(VISION_CAMERA_ID),
    "csi_sensor_id": int(VISION_CSI_SENSOR_ID),
    "vieneu_voice": VIENEU_VOICE,
    "vieneu_start_buffer_ms": int(VIENEU_START_BUFFER_MS),
    "vieneu_first_audio_timeout": float(VIENEU_FIRST_AUDIO_TIMEOUT),
    "vieneu_stream_stall_timeout": float(VIENEU_STREAM_STALL_TIMEOUT),
    "vieneu_output_blocksize": 2048,
    "help_prompts": deepcopy(DEFAULT_HELP_PROMPTS),
}


def _sanitize(data):
    result = deepcopy(DEFAULTS)
    if isinstance(data, dict):
        result.update(data)

    for key in ("audio_input_device", "audio_output_device"):
        value = result.get(key)
        if value in ("", "default", None):
            result[key] = None
        else:
            try:
                result[key] = int(value)
            except (TypeError, ValueError):
                result[key] = None

    source = str(result.get("camera_source", "usb")).strip().lower()
    result["camera_source"] = source if source in {"usb", "csi"} else "usb"

    for key, lo, hi in (
        ("camera_id", 0, 99),
        ("csi_sensor_id", 0, 9),
        ("vieneu_start_buffer_ms", 50, 2000),
        ("vieneu_output_blocksize", 0, 8192),
    ):
        try:
            result[key] = max(lo, min(hi, int(result.get(key, DEFAULTS[key]))))
        except (TypeError, ValueError):
            result[key] = DEFAULTS[key]

    for key, lo, hi in (
        ("vieneu_first_audio_timeout", 0.5, 15.0),
        ("vieneu_stream_stall_timeout", 0.5, 15.0),
    ):
        try:
            result[key] = max(lo, min(hi, float(result.get(key, DEFAULTS[key]))))
        except (TypeError, ValueError):
            result[key] = DEFAULTS[key]

    result["vieneu_voice"] = str(result.get("vieneu_voice") or VIENEU_VOICE).strip() or VIENEU_VOICE
    result["active_user_id"] = str(result.get("active_user_id") or "test_U036").strip() or "test_U036"

    raw_levels = result.get("pcbm_support_levels")
    clean_levels = {}
    if isinstance(raw_levels, dict):
        for uid, level in raw_levels.items():
            uid = str(uid).strip()
            if not uid:
                continue
            try:
                clean_levels[uid] = max(0, min(2, int(level)))
            except (TypeError, ValueError):
                clean_levels[uid] = 1
    if "test_U036" not in clean_levels:
        clean_levels["test_U036"] = 1
    result["pcbm_support_levels"] = clean_levels

    raw_prompts = result.get("help_prompts")
    prompts = {}
    if isinstance(raw_prompts, dict):
        for group, items in raw_prompts.items():
            group_name = str(group).strip()
            if not group_name or not isinstance(items, list):
                continue
            clean_items = []
            for item in items:
                text = str(item).strip()
                if text and text not in clean_items:
                    clean_items.append(text)
            prompts[group_name] = clean_items
    result["help_prompts"] = prompts if prompts else deepcopy(DEFAULT_HELP_PROMPTS)
    return result


def tai_cai_dat():
    with _LOCK:
        if not SETTINGS_PATH.exists():
            return deepcopy(DEFAULTS)
        try:
            with SETTINGS_PATH.open("r", encoding="utf-8") as f:
                return _sanitize(json.load(f))
        except Exception as e:
            print("[SETTINGS WARN] Không đọc được user_settings.json:", e)
            return deepcopy(DEFAULTS)


def luu_cai_dat(data):
    settings = _sanitize(data)
    with _LOCK:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_PATH.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        tmp.replace(SETTINGS_PATH)
    print("[SETTINGS] Saved", SETTINGS_PATH)
    return settings


def khoi_phuc_mac_dinh():
    return luu_cai_dat(DEFAULTS)


def danh_sach_thiet_bi_am_thanh():
    import sounddevice as sd

    inputs = []
    outputs = []
    try:
        devices = sd.query_devices()
    except Exception as e:
        print("[SETTINGS AUDIO WARN]", e)
        return inputs, outputs

    for index, device in enumerate(devices):
        name = str(device.get("name", f"Device {index}"))
        rate = int(round(float(device.get("default_samplerate", 0) or 0)))
        if int(device.get("max_input_channels", 0) or 0) > 0:
            inputs.append({"index": index, "name": name, "rate": rate})
        if int(device.get("max_output_channels", 0) or 0) > 0:
            outputs.append({"index": index, "name": name, "rate": rate})
    return inputs, outputs


def danh_sach_camera_usb():
    """Liệt kê /dev/video* mà không mở camera, an toàn cho Jetson."""
    cameras = []
    sys_dir = Path("/sys/class/video4linux")
    if sys_dir.exists():
        for item in sorted(sys_dir.glob("video*"), key=lambda p: p.name):
            try:
                idx = int(item.name.replace("video", ""))
            except ValueError:
                continue
            try:
                name = (item / "name").read_text(encoding="utf-8").strip()
            except Exception:
                name = item.name
            cameras.append({"index": idx, "name": name})
    if not cameras:
        # Fallback đơn giản cho máy không expose sysfs như mong đợi.
        cameras = [{"index": i, "name": f"Camera {i}"} for i in range(4)]
    return cameras
