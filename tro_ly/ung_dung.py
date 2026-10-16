import sys
import threading
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout

from cau_hinh import (
    FACE_DIR, AUTO_LISTEN, REMINDER_CHECK_MS,
    ADHD_MODE_ENABLED, COACHING_DEVICE_MODE,
)
from dich_vu.co_so_du_lieu import khoi_tao_co_so_du_lieu
from dich_vu.dich_vu_nhiem_vu import DichVuNhiemVu
from dich_vu.dich_vu_ai import DichVuAI
from dich_vu.dich_vu_nhan_dang_giong_noi import DichVuNhanDangGiongNoi
from dich_vu.dich_vu_doc_giong_noi import DichVuDocGiongNoi
from dich_vu.dich_vu_huan_luyen import DichVuHuanLuyen
from dich_vu.thoi_gian_chay import lay_dich_vu_thi_giac
from dich_vu.dich_vu_vong_deo import DichVuVongDeo
from dich_vu.dich_vu_pcbm import DichVuPCBM
from tro_ly.bo_dinh_tuyen_y_dinh import BoDinhTuyenYDinh


class KenhTinHieu(QObject):
    da_nghe = Signal(str)
    loi = Signal(str)
    doc_giong_noi_xong = Signal()
    ket_qua = Signal(object)


class CuaSoTroLy(QWidget):
    def __init__(self):
        super().__init__()
        khoi_tao_co_so_du_lieu()
        self.dich_vu_nhiem_vu = DichVuNhiemVu()
        self.dich_vu_ai = DichVuAI()
        self.dich_vu_huan_luyen = DichVuHuanLuyen(self.dich_vu_nhiem_vu, self.dich_vu_ai)
        self.dich_vu_thi_giac = lay_dich_vu_thi_giac()
        self.dich_vu_nhan_dang_giong_noi = DichVuNhanDangGiongNoi()
        self.dich_vu_doc_giong_noi = DichVuDocGiongNoi()
        self.dich_vu_vong_deo = DichVuVongDeo(self.dich_vu_nhiem_vu, self.dich_vu_huan_luyen)
        self.dich_vu_pcbm = DichVuPCBM()
        self.dich_vu_vong_deo.dam_bao_luoc_do()
        self.bo_dinh_tuyen = BoDinhTuyenYDinh(self.dich_vu_nhiem_vu, self.dich_vu_ai, self.dich_vu_huan_luyen, self.dich_vu_thi_giac, self.dich_vu_pcbm)

        self.kenh_tin_hieu = KenhTinHieu()
        self.kenh_tin_hieu.da_nghe.connect(self.khi_da_nghe)
        self.kenh_tin_hieu.loi.connect(self.khi_loi)
        self.kenh_tin_hieu.doc_giong_noi_xong.connect(self.khi_doc_giong_noi_xong)
        self.kenh_tin_hieu.ket_qua.connect(self.khi_ket_qua)

        self.trang_thai = "idle"
        self.chi_so_khung_hinh = 0
        self.dang_nghe = False
        self.dang_noi = False
        self.dang_xu_ly = False
        self.bo_nho_dem_khung_hinh = {}
        self._after = "idle"
        self.dang_hien_thi_anh_chup = False
        self._anh_chup_dang_cho = None
        self._phan_hoi_sau_anh_chup = ""
        self._trang_thai_sau_anh_chup = "idle"

        self.setWindowTitle("OneStep Buddy v9.9 PCBM")
        self.setCursor(Qt.BlankCursor)
        self.setStyleSheet("background:#F2F9F7;color:#20303A;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.nhan_khuon_mat = QLabel()
        self.nhan_khuon_mat.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.nhan_khuon_mat, 1)
        self.lay_trang_thai_dich_vu = QLabel("Xin chào, mình là OneStep Buddy.")
        self.lay_trang_thai_dich_vu.setAlignment(Qt.AlignCenter)
        self.lay_trang_thai_dich_vu.setWordWrap(True)
        self.lay_trang_thai_dich_vu.setStyleSheet("font:600 26px Arial;padding:12px 40px;color:#20303A;")
        lay.addWidget(self.lay_trang_thai_dich_vu)
        self.nhan_nhiem_vu = QLabel("")
        self.nhan_nhiem_vu.setAlignment(Qt.AlignCenter)
        self.nhan_nhiem_vu.setWordWrap(True)
        self.nhan_nhiem_vu.setStyleSheet("font:18px Arial;padding:0 40px 24px;color:#567078;")
        lay.addWidget(self.nhan_nhiem_vu)

        self.bo_hen_gio_hoat_anh = QTimer(self)
        self.bo_hen_gio_hoat_anh.timeout.connect(self.tiep_theo_khung_hinh)
        self.bo_hen_gio_hoat_anh.start(320)
        self.bo_hen_gio_lam_moi = QTimer(self)
        self.bo_hen_gio_lam_moi.timeout.connect(self.lam_moi_nhiem_vu)
        self.bo_hen_gio_lam_moi.start(2000)
        self.bo_hen_gio_nhac_nho = QTimer(self)
        self.bo_hen_gio_nhac_nho.timeout.connect(self.kiem_tra_nhac_nho)
        self.bo_hen_gio_nhac_nho.start(REMINDER_CHECK_MS)

        self.lam_moi_nhiem_vu()
        self.tiep_theo_khung_hinh()
        if AUTO_LISTEN:
            QTimer.singleShot(900, self.lang_nghe)

    @property
    def vong_deo_duoc_bat(self):
        return COACHING_DEVICE_MODE in {"band", "both"}

    @property
    def tro_ly_nhac_duoc_bat(self):
        return COACHING_DEVICE_MODE in {"home", "both"}

    def dat_trang_thai(self, s, text=None):
        self.trang_thai = s if (FACE_DIR / s).exists() else "idle"
        self.chi_so_khung_hinh = 0
        if text:
            self.lay_trang_thai_dich_vu.setText(text)
        self.tiep_theo_khung_hinh()

    def tiep_theo_khung_hinh(self):
        if self.dang_hien_thi_anh_chup:
            return
        fs = sorted((FACE_DIR / self.trang_thai).glob("*.png"))
        if not fs:
            return
        p = fs[self.chi_so_khung_hinh % len(fs)]
        self.chi_so_khung_hinh += 1
        key = (str(p), self.width(), self.height())
        if key not in self.bo_nho_dem_khung_hinh:
            pix = QPixmap(str(p))
            pix = pix.scaled(self.width(), max(260, self.height() - 130), Qt.KeepAspectRatio, Qt.FastTransformation)
            self.bo_nho_dem_khung_hinh[key] = pix
        self.nhan_khuon_mat.setPixmap(self.bo_nho_dem_khung_hinh[key])

    def thay_doi_kich_thuoc(self, e):
        self.bo_nho_dem_khung_hinh.clear()
        super().resizeEvent(e)
        self.tiep_theo_khung_hinh()
    resizeEvent = thay_doi_kich_thuoc

    def lam_moi_nhiem_vu(self):
        t = self.dich_vu_nhiem_vu.lay_nhiem_vu_hien_tai()
        if t.get("done"):
            self.nhan_nhiem_vu.setText("")
            return
        when = (t.get("scheduled_at") or "").replace("T", " ")
        if int(t.get("total_steps") or 1) > 1:
            txt = f"{t['task_name']}  •  {t['step_index']}/{t['total_steps']}: {t['current_step']}  •  {when}"
        else:
            txt = f"{t['task_name']}  •  {when}"
        self.nhan_nhiem_vu.setText(txt)

    def kiem_tra_nhac_nho(self):
        if self.dang_nghe or self.dang_noi or self.dang_xu_ly:
            return

        # Mức 0: không nhắc tại thời điểm đến hạn. Kiểm tra trễ có thể được
        # gửi qua Buddy, OneBand hoặc cả hai tùy COACHING_DEVICE_MODE.
        if ADHD_MODE_ENABLED:
            due_check = self.dich_vu_huan_luyen.lay_kiem_tra_muc0_den_han()
            if due_check:
                print("[MEMORY LEVEL0 CHECK]", due_check.get("task_title"))
                if self.vong_deo_duoc_bat:
                    try:
                        self.dich_vu_vong_deo.gui_kiem_tra_ghi_nho_muc0(due_check)
                        print("[BAND MEMORY0 PUSH]", due_check.get("task_title"))
                    except Exception as e:
                        print("[BAND MEMORY0 PUSH ERROR]", e)

                if self.tro_ly_nhac_duoc_bat:
                    msg = ("Lúc nãy bạn có một việc cần làm. Bạn đã nhớ và làm chưa? "
                           "Bạn có thể trả lời: đã làm rồi, nhớ nhưng chưa làm, hoặc không nhớ.")
                    self.noi(msg, "idle")
                return

        t = self.dich_vu_nhiem_vu.lay_nhiem_vu_hien_tai()
        if t.get("done") or not t.get("scheduled_at") or t.get("reminded_at"):
            return
        try:
            when = datetime.fromisoformat(t["scheduled_at"])
        except Exception:
            return
        if datetime.now() < when:
            return

        if not ADHD_MODE_ENABLED:
            self.dich_vu_nhiem_vu.danh_dau_da_nhac(t["occurrence_id"])
            if self.vong_deo_duoc_bat:
                try:
                    self.dich_vu_vong_deo.gui_nhac_nhiem_vu(t)
                except Exception as e:
                    print("[BAND PUSH ERROR]", e)
            if self.tro_ly_nhac_duoc_bat:
                self.noi(f"Đến giờ {t['task_name']} rồi.", "idle")
            return

        base_level = self.dich_vu_huan_luyen.lay_muc_nhac(t)

        # PCBM dự đoán xác suất tự nhớ / hoàn thành từ lịch sử sự kiện cá nhân.
        # Mặc định PCBM chỉ đưa khuyến nghị. Đặt PCBM_APPLY_PROMPT_LEVEL=1 để cho phép
        # mô hình thay đổi một mức nhắc nhưng vẫn tuân thủ giới hạn huấn luyện ghi nhớ 0..2.
        rec = self.dich_vu_pcbm.de_xuat_muc_ho_tro(t, base_level)
        level = rec.get("recommended_prompt_level", base_level) if rec.get("applied") else base_level
        print("[PCBM]", rec)

        self.dich_vu_nhiem_vu.danh_dau_da_nhac(t["occurrence_id"])
        self.dich_vu_pcbm.ghi_su_kien(
            "REMINDER_SENT",
            t.get("task_id"),
            t.get("occurrence_id"),
            {
                "prompt_level": level,
                "base_prompt_level": base_level,
                "pcbm_recommended_prompt_level": rec.get("recommended_prompt_level"),
                "recall_probability": rec.get("recall_probability"),
                "completion_30m_probability": rec.get("completion_30m_probability"),
                "reminder_type": "generic" if level <= 1 else "explicit",
                "channel": "buddy",
            },
        )

        if level == 0:
            # Quan trọng: ở mức 0, Buddy không nói và Band không gửi thông báo tại thời điểm đến hạn.
            self.dich_vu_huan_luyen.lap_lich_kiem_tra_muc0(t)
            print("[PROMPT LEVEL 0] no due-time reminder:", t["task_name"])
            return

        prompt = self.dich_vu_huan_luyen.bat_dau_nhac_khi_den_han(t, level)
        if self.vong_deo_duoc_bat:
            try:
                self.dich_vu_vong_deo.gui_nhac_ghi_nho(t, level)
                print("[BAND MEMORY PUSH]", level, t["task_name"])
            except Exception as e:
                print("[BAND PUSH ERROR]", e)

        if self.tro_ly_nhac_duoc_bat:
            print(f"[PROMPT LEVEL {level}]", prompt["text"])
            self.noi(prompt["text"], "idle")

    def lang_nghe(self):
        if self.dang_nghe or self.dang_noi or self.dang_xu_ly:
            return
        self.dang_nghe = True
        self.dat_trang_thai("listening", "Mình đang nghe...")

        def tien_trinh():
            try:
                self.kenh_tin_hieu.da_nghe.emit(self.dich_vu_nhan_dang_giong_noi.lang_nghe_mot_lan())
            except Exception as e:
                self.kenh_tin_hieu.loi.emit(str(e))
        threading.Thread(target=tien_trinh, daemon=True).start()

    def khi_da_nghe(self, text):
        self.dang_nghe = False
        if not text:
            self.dat_trang_thai("error", "Mình chưa nghe rõ. Bạn nói lại nhé.")
            QTimer.singleShot(900, self.lang_nghe)
            return
        print("[HEARD]", text)
        self.dang_xu_ly = True
        self.dat_trang_thai("thinking", f"Bạn: {text}")

        def tien_trinh():
            try:
                self.kenh_tin_hieu.ket_qua.emit(self.bo_dinh_tuyen.xu_ly(text))
            except Exception as e:
                self.kenh_tin_hieu.loi.emit(str(e))
        threading.Thread(target=tien_trinh, daemon=True).start()

    def khi_ket_qua(self, r):
        self.dang_xu_ly = False
        if r.get("refresh"):
            self.lam_moi_nhiem_vu()

        snapshot_path = r.get("snapshot_path")
        if snapshot_path:
            self._anh_chup_dang_cho = {
                "path": snapshot_path,
                "seconds": int(r.get("snapshot_seconds") or 10),
                "caption": r.get("snapshot_caption") or "",
            }
            self._phan_hoi_sau_anh_chup = r.get("after_snapshot_reply") or ""
            self._trang_thai_sau_anh_chup = r.get("state", "idle")

        # Phát lời nói TRƯỚC khi chuyển màn hình sang ảnh chụp.
        self.noi(r.get("reply", ""), r.get("state", "idle"))

    def hien_thi_anh_chup(self, path, seconds=10, caption=""):
        pix = QPixmap(str(path))
        if pix.isNull():
            self.dang_hien_thi_anh_chup = False
            self.dat_trang_thai("error", "Mình chưa mở được hình ảnh.")
            if AUTO_LISTEN:
                QTimer.singleShot(1100, self.lang_nghe)
            return

        self.dang_hien_thi_anh_chup = True
        scaled = pix.scaled(
            self.width(),
            max(260, self.height() - 150),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.nhan_khuon_mat.setPixmap(scaled)
        self.lay_trang_thai_dich_vu.setText(caption or "Hình ảnh Vision")
        self.nhan_nhiem_vu.setText(f"Tự đóng sau {seconds} giây")
        QTimer.singleShot(max(1, int(seconds)) * 1000, self.an_anh_chup)

    def an_anh_chup(self):
        self.dang_hien_thi_anh_chup = False
        self._anh_chup_dang_cho = None
        self.bo_nho_dem_khung_hinh.clear()
        self.lam_moi_nhiem_vu()

        if self._phan_hoi_sau_anh_chup:
            msg = self._phan_hoi_sau_anh_chup
            self._phan_hoi_sau_anh_chup = ""
            self.noi(msg, self._trang_thai_sau_anh_chup)
            return

        self.dat_trang_thai(self._trang_thai_sau_anh_chup, "Mình đang sẵn sàng.")
        if AUTO_LISTEN:
            QTimer.singleShot(500, self.lang_nghe)

    def noi(self, text, after_state="idle"):
        if not text:
            if AUTO_LISTEN:
                QTimer.singleShot(300, self.lang_nghe)
            return

        # Không phát âm thanh đầu ra khi microphone vẫn đang được đánh dấu là hoạt động.
        # Bình thường điều kiện này là false; nó giúp tránh xung đột thời điểm giữa nhắc việc và âm thanh.
        if self.dang_nghe:
            print("[AUDIO] TTS delayed because STT is active")
            QTimer.singleShot(350, lambda: self.noi(text, after_state))
            return

        self.dang_noi = True
        self._after = after_state
        self.dat_trang_thai("speaking", text)
        self.dich_vu_doc_giong_noi.noi(text, lambda: self.kenh_tin_hieu.doc_giong_noi_xong.emit())

    def khi_doc_giong_noi_xong(self):
        self.dang_noi = False

        # Trải nghiệm thị giác: Buddy nói trước, sau đó ảnh xuất hiện trong N giây.
        if self._anh_chup_dang_cho and not self.dang_hien_thi_anh_chup:
            item = self._anh_chup_dang_cho
            self.hien_thi_anh_chup(item["path"], item["seconds"], item["caption"])
            return

        self.dat_trang_thai(self._after, "Mình đang sẵn sàng.")
        if AUTO_LISTEN:
            # DichVuDocGiongNoi đã nhả ALSA; chờ thêm một khoảng ngắn
            # trước khi PortAudio mở lại microphone.
            QTimer.singleShot(1100, self.lang_nghe)

    def khi_loi(self, e):
        self.dang_nghe = False
        self.dang_noi = False
        self.dang_xu_ly = False
        print("[BUDDY ERROR]", e)
        self.dat_trang_thai("error", "Có lỗi nhỏ. Mình sẽ thử lại.")
        if AUTO_LISTEN:
            QTimer.singleShot(1400, self.lang_nghe)


def chay_tro_ly():
    app = QApplication(sys.argv)
    w = CuaSoTroLy()
    w.showFullScreen()
    sys.exit(app.exec())
