import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from cau_hinh import (
    VISION_ENABLED, VISION_MODEL, VISION_CAMERA_ID, VISION_CONFIDENCE,
    VISION_VERIFY_FRAMES, VISION_FRAME_INTERVAL, VISION_IMGSZ,
    VISION_CAMERA_SOURCE, VISION_DEVICE, VISION_HALF,
    VISION_CSI_SENSOR_ID, VISION_CSI_WIDTH, VISION_CSI_HEIGHT, VISION_CSI_FPS,
    VISION_SNAPSHOT_DIR, VISION_SAVE_SNAPSHOTS,
    VISION_RETENTION_HOURS,
)
from dich_vu.dich_vu_bo_nho_vat_dung import DichVuBoNhoVatDung


ALIASES = {
    "cặp": "backpack", "cap": "backpack", "ba lô": "backpack", "balo": "backpack",
    "ba lo": "backpack", "backpack": "backpack",
    "sách": "book", "sach": "book", "book": "book",
    "bình nước": "bottle", "binh nuoc": "bottle",
    "chai nước": "bottle", "chai nuoc": "bottle", "bottle": "bottle",
    "điện thoại": "cell phone", "dien thoai": "cell phone", "cell phone": "cell phone",
    "laptop": "laptop", "máy tính xách tay": "laptop",
    "cốc": "cup", "ly": "cup", "cup": "cup",
}

DISPLAY_NAMES = {
    "backpack": "cặp",
    "book": "sách",
    "bottle": "bình nước",
    "cell phone": "điện thoại",
    "laptop": "laptop",
    "cup": "cốc",
}


class DichVuThiGiac:
    """Dịch vụ thị giác hướng sự kiện, tối ưu để chạy trên Jetson và dùng chung mô hình trong tiến trình."""

    def __init__(self):
        self.duoc_bat = VISION_ENABLED
        self._mo_hinh = None
        self._khoa = threading.Lock()
        self.bo_nho_vat_dung = DichVuBoNhoVatDung()
        self.ma_anh_chup_da_hien_thi_cuoi = None
        self._lan_don_dep_cuoi = 0.0
        self._don_dep_neu_den_han(force=True)

    def _don_dep_neu_den_han(self, force=False):
        if force or (time.time() - self._lan_don_dep_cuoi > 6 * 3600):
            try:
                result = self.bo_nho_vat_dung.don_dep_ban_ghi_cu(VISION_RETENTION_HOURS)
                if result.get("removed_records"):
                    print("[VISION CLEANUP]", result)
            except Exception as e:
                print("[VISION CLEANUP ERROR]", e)
            self._lan_don_dep_cuoi = time.time()

    def _tai_mo_hinh(self):
        if self._mo_hinh is not None:
            return self._mo_hinh
        if not self.duoc_bat:
            raise RuntimeError("Vision đang tắt trong config.")
        from ultralytics import YOLO
        self._mo_hinh = YOLO(VISION_MODEL)
        print("[VISION] Loaded", VISION_MODEL, "device=", VISION_DEVICE)
        return self._mo_hinh

    def lay_trang_thai_dich_vu(self):
        return {
            "enabled": self.duoc_bat,
            "model": str(VISION_MODEL),
            "loaded": self._mo_hinh is not None,
            "camera_source": VISION_CAMERA_SOURCE,
            "camera_id": VISION_CAMERA_ID,
            "device": VISION_DEVICE,
            "half": VISION_HALF,
            "retention_hours": VISION_RETENTION_HOURS,
        }

    def chuan_hoa_vat_dung(self, item):
        s = (item or "").strip().lower()
        return ALIASES.get(s, s)

    def hien_thi_ten(self, item):
        return DISPLAY_NAMES.get(self.chuan_hoa_vat_dung(item), item)

    def trich_xuat_doi_tuong_tu_van_ban(self, text):
        low = (text or "").lower()
        # Ưu tiên bí danh dài hơn để tránh nhầm "cặp" với các mảnh từ ngắn khác.
        for alias in sorted(ALIASES.keys(), key=len, reverse=True):
            if alias in low:
                return ALIASES[alias]
        return None

    def _csi_quy_trinh(self):
        return (
            f"nvarguscamerasrc sensor-id={VISION_CSI_SENSOR_ID} ! "
            f"video/x-raw(memory:NVMM),width={VISION_CSI_WIDTH},height={VISION_CSI_HEIGHT},"
            f"framerate={VISION_CSI_FPS}/1 ! "
            "nvvidconv ! video/x-raw,format=BGRx ! "
            "videoconvert ! video/x-raw,format=BGR ! "
            "appsink drop=true max-buffers=1 sync=false"
        )

    def _mo_camera(self, cv2):
        if VISION_CAMERA_SOURCE == "csi":
            pipeline = self._csi_quy_trinh()
            print("[VISION CAMERA] CSI:", pipeline)
            return cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        print("[VISION CAMERA] USB/V4L2:", VISION_CAMERA_ID)
        return cv2.VideoCapture(VISION_CAMERA_ID)

    @staticmethod
    def _vung_tu_khung(x1, y1, x2, y2, frame_w):
        cx = (float(x1) + float(x2)) / 2.0
        if frame_w <= 0:
            return "unknown"
        ratio = cx / float(frame_w)
        if ratio < 0.34:
            return "left"
        if ratio > 0.66:
            return "right"
        return "center"

    def _du_doan(self, model, frame):
        kwargs = {
            "conf": VISION_CONFIDENCE,
            "imgsz": VISION_IMGSZ,
            "verbose": False,
        }
        # TensorRT .engine tự quản lý độ chính xác và thiết bị; với .pt dùng CUDA/half khi được cấu hình.
        if not str(VISION_MODEL).lower().endswith(".engine"):
            kwargs["device"] = VISION_DEVICE
            kwargs["half"] = bool(VISION_HALF)
        return model.predict(frame, **kwargs)

    def _luu_da_chu_thich_anh_chup(self, frame, detections):
        if not VISION_SAVE_SNAPSHOTS or frame is None:
            return None
        import cv2
        VISION_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        image = frame.copy()

        for d in detections:
            x1, y1, x2, y2 = [int(v) for v in d["bbox"]]
            label = f"{DISPLAY_NAMES.get(d['class'], d['class'])} {d['confidence']:.2f}"
            cv2.rectangle(image, (x1, y1), (x2, y2), (40, 220, 80), 2)
            cv2.putText(image, label, (x1, max(22, y1 - 7)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (40, 220, 80), 2, cv2.LINE_AA)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = VISION_SNAPSHOT_DIR / f"vision_{stamp}.jpg"
        if not cv2.imwrite(str(path), image):
            return None
        return str(path)

    def _chup_va_phat_hien(self, frames=None):
        frames = max(1, int(frames or VISION_VERIFY_FRAMES))
        with self._khoa:
            import cv2
            model = self._tai_mo_hinh()
            cap = self._mo_camera(cv2)

            if not cap.isOpened():
                cap.release()
                return {
                    "success": False,
                    "message": "Không mở được camera.",
                    "detections": [],
                }

            counts = Counter()
            best = {}
            latest_frame = None
            valid_frames = 0

            try:
                for _ in range(3):
                    cap.read()
                    time.sleep(0.03)

                for _ in range(frames):
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        continue
                    valid_frames += 1
                    latest_frame = frame

                    results = self._du_doan(model, frame)
                    seen_this_frame = set()

                    for r in results:
                        if r.boxes is None:
                            continue
                        for box in r.boxes:
                            cls_id = int(box.cls[0])
                            conf = float(box.conf[0])
                            name = str(model.names[cls_id]).lower()
                            xyxy = box.xyxy[0].tolist()
                            zone = self._vung_tu_khung(*xyxy, frame.shape[1])

                            seen_this_frame.add(name)
                            prev = best.get(name)
                            if prev is None or conf > prev["confidence"]:
                                best[name] = {
                                    "class": name,
                                    "confidence": conf,
                                    "bbox": [float(x) for x in xyxy],
                                    "zone": zone,
                                }

                    for name in seen_this_frame:
                        counts[name] += 1

                    time.sleep(VISION_FRAME_INTERVAL)
            finally:
                cap.release()

        needed = max(1, (max(1, valid_frames) + 1) // 2)
        voted = []
        for name, d in best.items():
            if counts.get(name, 0) >= needed:
                voted.append(d)

        return {
            "success": True,
            "detections": voted,
            "counts": dict(counts),
            "frames_requested": frames,
            "frames_valid": valid_frames,
            "frame": latest_frame,
        }

    def _nho_ket_qua_phat_hien(self, result, force_snapshot=False, force_rows=False):
        if not result.get("success"):
            return []

        detections = result.get("detections") or []
        if not detections:
            return []

        snapshot_path = self._luu_da_chu_thich_anh_chup(result.get("frame"), detections)
        rows = []
        camera_id = (
            f"csi:{VISION_CSI_SENSOR_ID}"
            if VISION_CAMERA_SOURCE == "csi"
            else f"usb:{VISION_CAMERA_ID}"
        )

        for d in detections:
            row = self.bo_nho_vat_dung.luu_lan_nhin_thay(
                d["class"],
                d["confidence"],
                camera_id,
                d.get("zone"),
                d.get("bbox"),
                snapshot_path=snapshot_path,
                force=force_rows,
            )
            rows.append(row)

        self._don_dep_neu_den_han()
        return rows

    def kiem_tra_vat_dung(self, required_items, frames=None):
        required = [self.chuan_hoa_vat_dung(x) for x in (required_items or []) if str(x).strip()]
        if not required:
            return {"success": False, "message": "Chưa có danh sách đồ cần kiểm tra.", "missing": []}

        result = self._chup_va_phat_hien(frames)
        if not result.get("success"):
            return {
                "success": False,
                "message": result.get("message", "Không kiểm tra được camera."),
                "missing": required,
                "detected": [],
            }

        rows = self._nho_ket_qua_phat_hien(result)
        detected = sorted({d["class"] for d in result.get("detections", [])})
        missing = [x for x in required if x not in detected]

        return {
            "success": True,
            "required": required,
            "detected": detected,
            "detected_vi": [self.hien_thi_ten(x) for x in detected],
            "missing": missing,
            "missing_vi": [self.hien_thi_ten(x) for x in missing],
            "counts": result.get("counts", {}),
            "frames": result.get("frames_valid", 0),
            "sightings": rows,
        }

    def tim_vat_dung(self, item, try_live=True):
        obj = self.chuan_hoa_vat_dung(item)
        if not obj:
            return {"success": False, "message": "Bạn muốn tìm đồ vật nào?"}

        live_error = None

        # Ưu tiên bằng chứng mới nếu camera hiện đang nhìn thấy vật thể.
        if try_live:
            live = self._chup_va_phat_hien()
            if live.get("success"):
                rows = self._nho_ket_qua_phat_hien(live, force_snapshot=True, force_rows=True)
                match = next((r for r in rows if r.get("object_class") == obj), None)
                if match:
                    self.ma_anh_chup_da_hien_thi_cuoi = match["id"]
                    return {
                        "success": True,
                        "source": "live",
                        "object_class": obj,
                        "object_label": self.hien_thi_ten(obj),
                        "sighting": match,
                        "snapshot_id": match["id"],
                        "snapshot_path": match.get("snapshot_path"),
                    }
            else:
                live_error = live.get("message")

        last = self.bo_nho_vat_dung.lay_cuoi_da_thay(obj)
        if last:
            self.ma_anh_chup_da_hien_thi_cuoi = last["id"]
            return {
                "success": True,
                "source": "history",
                "object_class": obj,
                "object_label": self.hien_thi_ten(obj),
                "sighting": last,
                "snapshot_id": last["id"],
                "snapshot_path": last.get("snapshot_path"),
                "live_error": live_error,
            }

        return {
            "success": False,
            "object_class": obj,
            "object_label": self.hien_thi_ten(obj),
            "message": (
                f"Mình chưa có thông tin lần cuối bạn để {self.hien_thi_ten(obj)} ở đâu."
                if not live_error else
                f"Mình chưa mở được camera và cũng chưa có lịch sử của {self.hien_thi_ten(obj)}."
            ),
        }

    def lay_cuoi_da_trinh_bay_anh_chup(self):
        if not self.ma_anh_chup_da_hien_thi_cuoi:
            return None
        return self.bo_nho_vat_dung.lay_lan_nhin_thay(self.ma_anh_chup_da_hien_thi_cuoi)

    def lay_cac_lan_nhin_thay_gan_day(self, limit=100):
        return self.bo_nho_vat_dung.lay_du_lieu_gan_day(limit)

    def lay_lan_nhin_thay(self, sighting_id):
        return self.bo_nho_vat_dung.lay_lan_nhin_thay(sighting_id)

    def don_dep(self):
        return self.bo_nho_vat_dung.don_dep_ban_ghi_cu(VISION_RETENTION_HOURS)
