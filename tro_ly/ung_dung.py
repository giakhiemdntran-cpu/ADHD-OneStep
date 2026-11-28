import sys
import threading
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QEvent
from PySide6.QtGui import QPixmap, QPainter, QColor, QKeySequence, QShortcut, QFontMetrics
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QSizePolicy,
    QPushButton, QStackedWidget, QLineEdit, QScrollArea, QFrame, QComboBox,
    QTextEdit, QPlainTextEdit
)

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
from dich_vu.cai_dat_nguoi_dung import tai_cai_dat, luu_cai_dat
from tro_ly.bo_dinh_tuyen_y_dinh import BoDinhTuyenYDinh
from tro_ly.cua_so_cai_dat import CuaSoCaiDat
from tro_ly.cua_so_tro_giup import CuaSoTroGiup
from tro_ly.cua_so_demo_coaching import CuaSoDemoCoaching
from dich_vu.demo_coaching import DemoCoachingManager
from dich_vu.coaching_actions import CoachingActionStore
from tro_ly.daily_coaching_widget import DailyCoachingWidget
from pathlib import Path
from cau_hinh import BASE_DIR


class KenhTinHieu(QObject):
    da_nghe = Signal(str)
    loi = Signal(str)
    doc_giong_noi_xong = Signal()
    ket_qua = Signal(object)
    muc_am_thanh = Signal(float, float)


class BoTatBanPhimAo(QObject):
    """Không cho Qt/Ubuntu tự bật bàn phím ảo khi chạm ô nhập.

    WA_InputMethodEnabled chỉ tắt input method/virtual keyboard; các sự kiện
    bàn phím vật lý (USB/Bluetooth) vẫn được QLineEdit/QTextEdit nhận bình thường.
    """

    def eventFilter(self, obj, event):
        if isinstance(obj, (QLineEdit, QTextEdit, QPlainTextEdit)):
            if event.type() in (QEvent.FocusIn, QEvent.MouseButtonPress, QEvent.TouchBegin):
                obj.setAttribute(Qt.WA_InputMethodEnabled, False)
                im = QApplication.inputMethod()
                if im is not None and im.isVisible():
                    im.hide()
        return super().eventFilter(obj, event)


class ThanhMucAmThanh(QWidget):
    """Equalizer nhỏ màu đỏ hiển thị mức microphone theo RMS/Peak."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rms = 0.0
        self._peak = 0.0
        self.setFixedHeight(34)
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.hide()

    def dat_muc(self, rms: float, peak: float):
        self._rms = max(0.0, float(rms))
        self._peak = max(0.0, float(peak))
        self.update()

    def reset(self):
        self._rms = 0.0
        self._peak = 0.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # Chuẩn hoá cho tín hiệu speech thông thường. Peak làm meter phản ứng nhanh hơn.
        muc_rms = min(1.0, self._rms / 0.055)
        muc_peak = min(1.0, self._peak / 0.22)
        level = max(muc_rms, muc_peak * 0.85)

        bar_count = 13
        bar_w = 6
        gap = 6
        total_w = bar_count * bar_w + (bar_count - 1) * gap
        x0 = (self.width() - total_w) / 2
        cy = self.height() / 2

        # Dạng sóng đối xứng: thấp ở hai biên, cao ở giữa.
        shape = [0.28, 0.38, 0.52, 0.70, 0.86, 1.00, 0.82,
                 1.00, 0.86, 0.70, 0.52, 0.38, 0.28]

        active = level > 0.025
        painter.setBrush(QColor('#E43D30' if active else '#E9A29C'))
        painter.setPen(Qt.NoPen)

        for i, factor in enumerate(shape):
            # Khi im lặng vẫn giữ một dải gạch nhỏ để người dùng biết app đang nghe.
            base_h = 4.0
            h = base_h + (self.height() - 8.0) * level * factor
            x = x0 + i * (bar_w + gap)
            y = cy - h / 2
            painter.drawRoundedRect(int(x), int(y), bar_w, max(4, int(h)), 3, 3)

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
        self.active_user_id = str(tai_cai_dat().get("active_user_id") or "test_U036").strip() or "test_U036"
        self.dich_vu_pcbm.dat_nguoi_dung_hien_tai(self.active_user_id)
        self.demo_coaching = DemoCoachingManager(self.dich_vu_pcbm)
        # Riêng demo: không dùng database nhiệm vụ thật.
        self.demo_daily_store = CoachingActionStore(Path(BASE_DIR) / "demo_coaching" / "daily_actions.sqlite3")
        self._demo_reminder_seen = set()
        self._support_text_full = "Đang tải trạng thái PCBM..."
        self._daily_text_full = ""
        self.dich_vu_vong_deo.dam_bao_luoc_do()
        self.bo_dinh_tuyen = BoDinhTuyenYDinh(self.dich_vu_nhiem_vu, self.dich_vu_ai, self.dich_vu_huan_luyen, self.dich_vu_thi_giac, self.dich_vu_pcbm)

        self.kenh_tin_hieu = KenhTinHieu()
        self.kenh_tin_hieu.da_nghe.connect(self.khi_da_nghe)
        self.kenh_tin_hieu.loi.connect(self.khi_loi)
        self.kenh_tin_hieu.doc_giong_noi_xong.connect(self.khi_doc_giong_noi_xong)
        self.kenh_tin_hieu.ket_qua.connect(self.khi_ket_qua)
        self.kenh_tin_hieu.muc_am_thanh.connect(self.khi_co_muc_am_thanh)
        self.dich_vu_nhan_dang_giong_noi.on_audio_level = (
            lambda rms, peak: self.kenh_tin_hieu.muc_am_thanh.emit(rms, peak)
        )

        self.trang_thai = "idle"
        self.chi_so_khung_hinh = 0
        self.dang_nghe = False
        self.dang_noi = False
        self.dang_xu_ly = False
        self._bo_qua_luot_nghe_tiep_theo = False
        self.bo_nho_dem_khung_hinh = {}
        self._after = "idle"
        self.dang_hien_thi_anh_chup = False
        self._anh_chup_dang_cho = None
        self._phan_hoi_sau_anh_chup = ""
        self._trang_thai_sau_anh_chup = "idle"

        self.setWindowTitle("OneStep Buddy v10.9.2 PCBM")
        # Kiosk: tránh Terminal/desktop che mất nửa dưới màn hình robot.
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setCursor(Qt.BlankCursor)
        self.setStyleSheet("background:#F2F9F7;color:#20303A;")

        # Khung chính: nút chuyển giao diện luôn nằm ở góc phải trên.
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(3)

        top_bar = QHBoxLayout()
        # Chừa khoảng an toàn cho viền màn hình robot:
        # - lùi cụm Người dùng bên trái vào trong
        # - lùi nút Thoát bên phải vào trong
        # - hạ toàn bộ thanh nút xuống một chút để tránh bị cắt mép trên
        top_bar.setContentsMargins(4, 2, 4, 1)
        top_bar.setSpacing(4)

        nhan_user = QLabel("👤  Người dùng:")
        nhan_user.setStyleSheet("font:600 14px Arial;color:#365A52;padding-left:2px;")
        top_bar.addWidget(nhan_user)

        self.chon_nguoi_dung = QComboBox()
        self.chon_nguoi_dung.setFixedHeight(36)
        self.chon_nguoi_dung.setMinimumWidth(150)
        self.chon_nguoi_dung.setToolTip("Chọn người dùng hiện tại cho Robot Buddy")
        self.chon_nguoi_dung.setStyleSheet(
            "QComboBox{background:#FFFFFF;border:1px solid #AFCFC7;border-radius:14px;"
            "padding:5px 10px;font:700 14px Arial;color:#23463E;}"
            "QComboBox:hover{border-color:#2F7D6D;}"
            "QComboBox::drop-down{border:none;width:28px;}"
        )
        user_ids = [str(x.get("user_id")) for x in self.dich_vu_pcbm.liet_ke_nguoi_dung() if x.get("user_id")]
        for uid in [self.active_user_id, "test_U036"] + user_ids:
            if uid and self.chon_nguoi_dung.findText(uid) < 0:
                self.chon_nguoi_dung.addItem(uid)
        idx_user = self.chon_nguoi_dung.findText(self.active_user_id)
        self.chon_nguoi_dung.setCurrentIndex(idx_user if idx_user >= 0 else 0)
        self.chon_nguoi_dung.currentTextChanged.connect(self.doi_nguoi_dung_hien_tai)
        top_bar.addWidget(self.chon_nguoi_dung)

        top_bar.addStretch(1)
        self.nut_chuyen_giao_dien = QPushButton("💬  Chat")
        self.nut_chuyen_giao_dien.setCursor(Qt.PointingHandCursor)
        self.nut_chuyen_giao_dien.setFixedHeight(36)
        self.nut_chuyen_giao_dien.setMinimumWidth(98)
        self.nut_chuyen_giao_dien.setStyleSheet(
            "QPushButton{background:#FFFFFF;border:1px solid #CFE1DD;border-radius:20px;"
            "padding:5px 12px;font:600 14px Arial;color:#20303A;}"
            "QPushButton:hover{background:#E6F3F0;}"
            "QPushButton:pressed{background:#D8ECE7;}"
        )
        self.nut_chuyen_giao_dien.setToolTip("Chuyển Khuôn mặt / Chat (F1)")
        self.nut_chuyen_giao_dien.clicked.connect(self.chuyen_giao_dien)
        top_bar.addWidget(self.nut_chuyen_giao_dien)

        self.nut_demo_coaching = QPushButton("Demo")
        self.nut_demo_coaching.setCursor(Qt.PointingHandCursor)
        self.nut_demo_coaching.setFixedHeight(36)
        self.nut_demo_coaching.setMinimumWidth(54)
        self.nut_demo_coaching.setToolTip("Demo Coaching Mode - dữ liệu tách riêng")
        self.nut_demo_coaching.setStyleSheet(
            "QPushButton{background:#FFF8E8;border:1px solid #E8C56A;border-radius:20px;"
            "padding:4px 8px;font:600 12px Arial;color:#70520F;}"
            "QPushButton:hover{background:#FFF0C7;}"
        )
        self.nut_demo_coaching.clicked.connect(self.mo_demo_coaching)
        top_bar.addWidget(self.nut_demo_coaching)

        # Always accessible, not a hidden Train/demo page.
        self.nut_pcbm_review = QPushButton('🧠 Mức hỗ trợ')
        self.nut_pcbm_review.setCursor(Qt.PointingHandCursor)
        self.nut_pcbm_review.setFixedHeight(36)
        self.nut_pcbm_review.setToolTip('Xem đề xuất AI; em có quyền giữ mức hiện tại')
        self.nut_pcbm_review.clicked.connect(self.mo_hoi_y_kien_muc_ho_tro)
        top_bar.addWidget(self.nut_pcbm_review)

        # Nút Settings: thiết bị audio/camera + buffer VieNeu.
        self.nut_cai_dat = QPushButton("⚙  Cài đặt")
        self.nut_cai_dat.setCursor(Qt.PointingHandCursor)
        self.nut_cai_dat.setFixedHeight(36)
        self.nut_cai_dat.setMinimumWidth(102)
        self.nut_cai_dat.setToolTip("Cài đặt thiết bị & TTS (F2)")
        self.nut_cai_dat.setStyleSheet(
            "QPushButton{background:#FFFFFF;border:1px solid #CFE1DD;border-radius:20px;"
            "padding:5px 12px;font:600 14px Arial;color:#20303A;}"
            "QPushButton:hover{background:#E6F3F0;}"
            "QPushButton:pressed{background:#D8ECE7;}"
        )
        self.nut_cai_dat.clicked.connect(self.mo_cai_dat)
        top_bar.addWidget(self.nut_cai_dat)

        # Nút Trợ giúp: danh mục prompt mẫu theo từng tình huống.
        self.nut_tro_giup = QPushButton("❓  Trợ giúp")
        self.nut_tro_giup.setCursor(Qt.PointingHandCursor)
        self.nut_tro_giup.setFixedHeight(36)
        self.nut_tro_giup.setMinimumWidth(102)
        self.nut_tro_giup.setToolTip("Xem câu nói mẫu với Buddy (F3)")
        self.nut_tro_giup.setStyleSheet(
            "QPushButton{background:#FFFFFF;border:1px solid #CFE1DD;border-radius:20px;"
            "padding:5px 12px;font:600 14px Arial;color:#20303A;}"
            "QPushButton:hover{background:#E6F3F0;}"
            "QPushButton:pressed{background:#D8ECE7;}"
        )
        self.nut_tro_giup.clicked.connect(self.mo_tro_giup)
        top_bar.addWidget(self.nut_tro_giup)

        # Nút thoát luôn hiển thị ở góc phải, cạnh nút đổi giao diện.
        self.nut_thoat = QPushButton("⏻  Thoát")
        self.nut_thoat.setCursor(Qt.PointingHandCursor)
        self.nut_thoat.setFixedHeight(36)
        self.nut_thoat.setMinimumWidth(88)
        self.nut_thoat.setToolTip("Tắt OneStep Buddy (Ctrl+Q)")
        self.nut_thoat.setStyleSheet(
            "QPushButton{background:#FFF4F2;border:1px solid #E9BBB3;border-radius:20px;"
            "padding:5px 12px;font:600 14px Arial;color:#B33A2E;}"
            "QPushButton:hover{background:#FDE3DE;border-color:#DE8D82;}"
            "QPushButton:pressed{background:#F8D2CB;}"
        )
        self.nut_thoat.clicked.connect(self.thoat_ung_dung)
        top_bar.addWidget(self.nut_thoat)

        # Phím tắt toàn cục của giao diện kiosk.
        self.phim_tat_chuyen_giao_dien = QShortcut(QKeySequence("F1"), self)
        self.phim_tat_chuyen_giao_dien.setContext(Qt.ApplicationShortcut)
        self.phim_tat_chuyen_giao_dien.activated.connect(self.chuyen_giao_dien)

        self.phim_tat_cai_dat = QShortcut(QKeySequence("F2"), self)
        self.phim_tat_cai_dat.setContext(Qt.ApplicationShortcut)
        self.phim_tat_cai_dat.activated.connect(self.mo_cai_dat)

        self.phim_tat_tro_giup = QShortcut(QKeySequence("F3"), self)
        self.phim_tat_tro_giup.setContext(Qt.ApplicationShortcut)
        self.phim_tat_tro_giup.activated.connect(self.mo_tro_giup)

        self.phim_tat_thoat = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.phim_tat_thoat.setContext(Qt.ApplicationShortcut)
        self.phim_tat_thoat.activated.connect(self.thoat_ung_dung)

        # Header có thể cuộn ngang ở màn hình 800px; không cắt nút Thoát/Cài đặt.
        top_widget = QWidget()
        top_widget.setLayout(top_bar)
        top_widget.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        top_scroll = QScrollArea()
        top_scroll.setWidget(top_widget)
        top_scroll.setWidgetResizable(False)
        top_scroll.setFrameShape(QFrame.NoFrame)
        top_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        top_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        top_scroll.setFixedHeight(53)
        top_scroll.setStyleSheet("QScrollArea{background:transparent;border:0;}"
                                 "QScrollBar:horizontal{height:5px;background:transparent;}"
                                 "QScrollBar::handle:horizontal{background:#AFCFC7;border-radius:2px;}")
        root.addWidget(top_scroll)

        self.ngan_xep_giao_dien = QStackedWidget()
        root.addWidget(self.ngan_xep_giao_dien, 1)

        # -------- Trang khuôn mặt --------
        self.trang_khuon_mat = QWidget()
        self.trang_khuon_mat.setStyleSheet("background:#F2F9F7;")
        lay = QVBoxLayout(self.trang_khuon_mat)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Thanh trạng thái PCBM đặt ở phía trên khuôn mặt để tránh bị che bởi viền dưới màn hình robot.
        self.nhan_muc_ho_tro = QLabel("Đang tải trạng thái PCBM...")
        self.nhan_muc_ho_tro.setAlignment(Qt.AlignCenter)
        self.nhan_muc_ho_tro.setWordWrap(False)
        self.nhan_muc_ho_tro.setTextFormat(Qt.PlainText)
        self.nhan_muc_ho_tro.setMinimumHeight(40)
        self.nhan_muc_ho_tro.setMaximumHeight(40)
        self.nhan_muc_ho_tro.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._set_support_label_style("#FFFFFF", "#CFE1DD", "#315C52")
        lay.addWidget(self.nhan_muc_ho_tro)

        # Chỉ hiện khi Demo Coaching đang chạy: lịch gợi ý trong ngày dựa trên thói quen của hồ sơ demo.
        self.nhan_goi_y_trong_ngay = QPushButton("🗓 Gợi ý hôm nay • Chạm để xem")
        self.nhan_goi_y_trong_ngay.setStyleSheet(
            "QPushButton{background:#FFF9EA;border:1px solid #E8D59A;border-radius:11px;"
            "font:600 11px Arial;padding:4px 8px;margin:0 54px 4px;color:#6B5520;text-align:left;}"
        )
        self.nhan_goi_y_trong_ngay.setFixedHeight(32)
        self.nhan_goi_y_trong_ngay.clicked.connect(self.mo_daily_coaching_plan)
        self.nhan_goi_y_trong_ngay.hide()
        lay.addWidget(self.nhan_goi_y_trong_ngay)

        self.nhan_khuon_mat = QLabel()
        self.nhan_khuon_mat.setAlignment(Qt.AlignCenter)
        # Quan trọng: không để kích thước pixmap làm QLabel/window tự nở dần.
        self.nhan_khuon_mat.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.nhan_khuon_mat.setMinimumSize(1, 1)
        lay.addWidget(self.nhan_khuon_mat, 1)

        # Meter microphone: thay dòng "Mình đang nghe..." bằng equalizer màu đỏ.
        self.thanh_muc_am_thanh = ThanhMucAmThanh(self.trang_khuon_mat)
        self.thanh_muc_am_thanh.setFixedHeight(24)
        lay.addWidget(self.thanh_muc_am_thanh)

        self.lay_trang_thai_dich_vu = QLabel("Xin chào, mình là OneStep Buddy.")
        self.lay_trang_thai_dich_vu.setAlignment(Qt.AlignCenter)
        self.lay_trang_thai_dich_vu.setWordWrap(True)
        self.lay_trang_thai_dich_vu.setStyleSheet("font:600 18px Arial;padding:3px 12px;color:#20303A;")
        self.lay_trang_thai_dich_vu.setMaximumHeight(54)
        lay.addWidget(self.lay_trang_thai_dich_vu)
        self.nhan_nhiem_vu = QLabel("")
        self.nhan_nhiem_vu.setAlignment(Qt.AlignCenter)
        self.nhan_nhiem_vu.setWordWrap(True)
        self.nhan_nhiem_vu.setStyleSheet("font:14px Arial;padding:0 12px 3px;color:#567078;")
        self.nhan_nhiem_vu.setMaximumHeight(40)
        lay.addWidget(self.nhan_nhiem_vu)

        self.ngan_xep_giao_dien.addWidget(self.trang_khuon_mat)

        # -------- Trang lịch sử chat --------
        self.trang_chat = QWidget()
        self.trang_chat.setStyleSheet("background:#EEF6F3;")
        chat_lay = QVBoxLayout(self.trang_chat)
        chat_lay.setContentsMargins(34, 14, 34, 28)
        chat_lay.setSpacing(14)

        # Header gọn như một ứng dụng chat hiện đại.
        khung_dau_chat = QFrame()
        khung_dau_chat.setObjectName("chatHeader")
        khung_dau_chat.setStyleSheet(
            "QFrame#chatHeader{background:#FFFFFF;border:1px solid #D8E7E3;"
            "border-radius:20px;}"
        )
        dau_lay = QHBoxLayout(khung_dau_chat)
        dau_lay.setContentsMargins(18, 12, 18, 12)
        dau_lay.setSpacing(12)

        avatar = QLabel("OB")
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setFixedSize(46, 46)
        avatar.setStyleSheet(
            "background:#2F7D6D;color:white;border-radius:23px;"
            "font:700 16px Arial;"
        )
        dau_lay.addWidget(avatar)

        khoi_tieu_de = QVBoxLayout()
        khoi_tieu_de.setSpacing(1)
        tieu_de_chat = QLabel("OneStep Buddy")
        tieu_de_chat.setStyleSheet("font:700 22px Arial;color:#20303A;")
        phu_de_chat = QLabel("●  Đang hoạt động  •  Có thể nói hoặc gõ tin nhắn")
        phu_de_chat.setStyleSheet("font:14px Arial;color:#6F8780;")
        khoi_tieu_de.addWidget(tieu_de_chat)
        khoi_tieu_de.addWidget(phu_de_chat)
        dau_lay.addLayout(khoi_tieu_de)
        dau_lay.addStretch(1)
        self.nhan_chat_muc_ho_tro = QLabel("PCBM")
        self.nhan_chat_muc_ho_tro.setAlignment(Qt.AlignCenter)
        self.nhan_chat_muc_ho_tro.setStyleSheet(
            "QLabel{background:#EAF5F2;border:1px solid #BCDAD2;border-radius:12px;"
            "padding:7px 12px;font:600 14px Arial;color:#2F6F61;}"
        )
        dau_lay.addWidget(self.nhan_chat_muc_ho_tro)
        chat_lay.addWidget(khung_dau_chat)

        # Vùng hội thoại dùng widget thật thay vì HTML để bubble đẹp và ổn định trên Qt.
        self.lich_su_chat = QScrollArea()
        self.lich_su_chat.setWidgetResizable(True)
        self.lich_su_chat.setFrameShape(QFrame.NoFrame)
        self.lich_su_chat.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lich_su_chat.setStyleSheet(
            "QScrollArea{background:#FFFFFF;border:1px solid #D8E7E3;border-radius:20px;}"
            "QScrollBar:vertical{background:transparent;width:10px;margin:10px 3px 10px 0;}"
            "QScrollBar::handle:vertical{background:#C9DCD7;border-radius:5px;min-height:36px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )

        self.noi_dung_chat = QWidget()
        self.noi_dung_chat.setStyleSheet("background:#FFFFFF;")
        self.bo_cuc_tin_nhan = QVBoxLayout(self.noi_dung_chat)
        self.bo_cuc_tin_nhan.setContentsMargins(24, 24, 24, 24)
        self.bo_cuc_tin_nhan.setSpacing(12)

        self.nhan_chat_trong = QLabel(
            "Bắt đầu trò chuyện với OneStep Buddy\nBạn có thể nói hoặc nhập tin nhắn ở bên dưới."
        )
        self.nhan_chat_trong.setAlignment(Qt.AlignCenter)
        self.nhan_chat_trong.setStyleSheet(
            "font:16px Arial;color:#8AA09A;padding:36px 12px;"
        )
        self.bo_cuc_tin_nhan.addWidget(self.nhan_chat_trong)
        self.bo_cuc_tin_nhan.addStretch(1)

        self.lich_su_chat.setWidget(self.noi_dung_chat)
        chat_lay.addWidget(self.lich_su_chat, 1)

        # Composer: thanh nhập dạng pill + nút gửi nổi bật.
        khung_nhap = QFrame()
        khung_nhap.setObjectName("chatComposer")
        khung_nhap.setStyleSheet(
            "QFrame#chatComposer{background:#FFFFFF;border:1px solid #CFE1DD;"
            "border-radius:22px;}"
        )
        hang_nhap = QHBoxLayout(khung_nhap)
        hang_nhap.setContentsMargins(14, 8, 8, 8)
        hang_nhap.setSpacing(8)

        self.o_nhap_chat = QLineEdit()
        self.o_nhap_chat.setAttribute(Qt.WA_InputMethodEnabled, False)
        self.o_nhap_chat.setPlaceholderText("Nhắn cho OneStep Buddy...")
        self.o_nhap_chat.setClearButtonEnabled(True)
        self.o_nhap_chat.setMinimumHeight(46)
        self.o_nhap_chat.setStyleSheet(
            "QLineEdit{background:transparent;border:none;padding:6px 8px;"
            "font:18px Arial;color:#20303A;}"
            "QLineEdit::placeholder{color:#91A39F;}"
        )
        self.o_nhap_chat.returnPressed.connect(self.gui_tin_nhan_ban_phim)
        hang_nhap.addWidget(self.o_nhap_chat, 1)

        self.nut_gui_chat = QPushButton("Gửi")
        self.nut_gui_chat.setCursor(Qt.PointingHandCursor)
        self.nut_gui_chat.setFixedHeight(46)
        self.nut_gui_chat.setMinimumWidth(92)
        self.nut_gui_chat.setStyleSheet(
            "QPushButton{background:#2F7D6D;border:none;border-radius:18px;"
            "padding:8px 20px;font:700 17px Arial;color:#FFFFFF;}"
            "QPushButton:hover{background:#286E61;}"
            "QPushButton:pressed{background:#205B50;}"
            "QPushButton:disabled{background:#B7CBC6;color:#EEF5F3;}"
        )
        self.nut_gui_chat.clicked.connect(self.gui_tin_nhan_ban_phim)
        hang_nhap.addWidget(self.nut_gui_chat)
        chat_lay.addWidget(khung_nhap)

        self.ngan_xep_giao_dien.addWidget(self.trang_chat)
        self.ngan_xep_giao_dien.setCurrentWidget(self.trang_khuon_mat)

        self._chat_message_widgets = []

        self.bo_hen_gio_hoat_anh = QTimer(self)
        self.bo_hen_gio_hoat_anh.timeout.connect(self.tiep_theo_khung_hinh)
        self.bo_hen_gio_hoat_anh.start(320)
        self.bo_hen_gio_lam_moi = QTimer(self)
        self.bo_hen_gio_lam_moi.timeout.connect(self.lam_moi_nhiem_vu)
        self.bo_hen_gio_lam_moi.start(2000)
        self.bo_hen_gio_nhac_nho = QTimer(self)
        self.bo_hen_gio_nhac_nho.timeout.connect(self.kiem_tra_nhac_nho)
        self.bo_hen_gio_nhac_nho.start(REMINDER_CHECK_MS)
        self.bo_hen_gio_demo_daily = QTimer(self)
        self.bo_hen_gio_demo_daily.timeout.connect(self.cap_nhat_daily_coaching_plan)
        self.bo_hen_gio_demo_daily.start(30000)

        # Once after startup; on further long sessions once per 30 minutes.
        self._last_review_auto_uid = None
        self.bo_hen_gio_hoi_y_kien = QTimer(self)
        self.bo_hen_gio_hoi_y_kien.timeout.connect(self.tu_dong_hoi_y_kien_muc_ho_tro)
        self.bo_hen_gio_hoi_y_kien.start(30 * 60 * 1000)
        QTimer.singleShot(12000, self.tu_dong_hoi_y_kien_muc_ho_tro)

        self.lam_moi_nhiem_vu()
        self.tiep_theo_khung_hinh()
        if AUTO_LISTEN:
            QTimer.singleShot(900, self.lang_nghe)

    def _set_support_label_style(self, bg, border, fg):
        self.nhan_muc_ho_tro.setStyleSheet(
            f"QLabel{{background:{bg};border:1px solid {border};border-radius:12px;"
            f"font:600 12px Arial;padding:4px 10px;margin:3px 24px 4px;color:{fg};}}"
        )

    def _set_support_text(self, text, tooltip=""):
        self._support_text_full = str(text or "")
        self.nhan_muc_ho_tro.setToolTip(tooltip or self._support_text_full)
        self._refresh_support_text()

    def _refresh_support_text(self):
        full = getattr(self, "_support_text_full", "") or ""
        metrics = QFontMetrics(self.nhan_muc_ho_tro.font())
        avail = max(120, self.nhan_muc_ho_tro.width() - 24)
        self.nhan_muc_ho_tro.setText(metrics.elidedText(full, Qt.ElideRight, avail))

    def _set_daily_plan_text(self, text):
        self._daily_text_full = str(text or "")
        metrics = QFontMetrics(self.nhan_goi_y_trong_ngay.font())
        avail = max(120, self.nhan_goi_y_trong_ngay.width() - 28)
        self.nhan_goi_y_trong_ngay.setText(metrics.elidedText(self._daily_text_full, Qt.ElideRight, avail))
        self.nhan_goi_y_trong_ngay.setToolTip(self._daily_text_full)

    def _refresh_compact_headers(self):
        if hasattr(self, "nhan_muc_ho_tro"):
            self._refresh_support_text()
        if hasattr(self, "nhan_goi_y_trong_ngay") and self.nhan_goi_y_trong_ngay.isVisible():
            self._set_daily_plan_text(getattr(self, "_daily_text_full", self.nhan_goi_y_trong_ngay.text()))

    def _refresh_layout_after_mode_change(self):
        self.bo_nho_dem_khung_hinh.clear()
        for w in (self.trang_khuon_mat, self.ngan_xep_giao_dien, self):
            try:
                if w.layout() is not None:
                    w.layout().activate()
                w.updateGeometry()
                w.update()
            except Exception:
                pass
        QTimer.singleShot(0, self._refresh_compact_headers)
        QTimer.singleShot(0, self.tiep_theo_khung_hinh)
        QTimer.singleShot(120, self.tiep_theo_khung_hinh)

    def mo_demo_coaching(self):
        dlg = CuaSoDemoCoaching(
            self.demo_coaching.danh_sach_profile(),
            self.bat_dau_demo_coaching,
            self.reset_demo_coaching,
            self,
        )
        dlg.exec()

    def _demo_daily_items(self, profile_id):
        # ID ổn định theo ngày, hồ sơ và vị trí gợi ý. Không lẫn sang task thật.
        today = datetime.now().date().isoformat()
        return [
            {"id": f"{today}:{i}", "time": item.get("time", "--:--"),
             "title": item.get("title", "Gợi ý"), "detail": item.get("coach", "")}
            for i, item in enumerate(self.demo_coaching.lich_goi_y_trong_ngay(profile_id))
        ]

    def cap_nhat_daily_coaching_plan(self):
        profile_id = self.demo_coaching.profile_id
        if not profile_id or not self.nhan_goi_y_trong_ngay.isVisible():
            return
        lines = []
        due = []
        for item in self._demo_daily_items(profile_id):
            state = self.demo_daily_store.state(profile_id, item["id"])
            marker = {"pending": "○", "in_progress": "▶", "snoozed": "⏰",
                      "done": "✓", "skipped": "↷"}.get(state["status"], "○")
            if state.get("reminder_due"):
                marker = "🔔"
                key = (profile_id, item["id"], state.get("updated_at"))
                if key not in self._demo_reminder_seen:
                    self._demo_reminder_seen.add(key)
                    due.append(item["title"])
            lines.append(f"{marker} {item['time']} {item['title']}")
        self._set_daily_plan_text("🗓 Gợi ý hôm nay (chạm để thao tác):  " + "   •   ".join(lines))
        if due:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "⏰ Demo Coaching - Đến giờ nhắc lại",
                                    "Đã đến giờ xem lại gợi ý:\n" + "\n".join(due))

    def mo_daily_coaching_plan(self):
        profile_id = self.demo_coaching.profile_id
        if not profile_id:
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QDialogButtonBox
        dialog = QDialog(self)
        dialog.setWindowTitle("Daily Coaching Plan • " + profile_id)
        dialog.resize(650, 510)
        layout = QVBoxLayout(dialog)
        widget = DailyCoachingWidget(
            store=self.demo_daily_store, user_id=profile_id,
            on_action=lambda result: self.cap_nhat_daily_coaching_plan(), parent=dialog)
        widget.set_suggestions(self._demo_daily_items(profile_id))
        layout.addWidget(widget)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()
        self.cap_nhat_daily_coaching_plan()
        self._refresh_layout_after_mode_change()

    def _one_step_delete_demo(self):
        from dich_vu.demo_delete_voice_flow import DemoDeleteVoiceFlow
        if not hasattr(self, '_delete_voice_demo'):
            self._delete_voice_demo = DemoDeleteVoiceFlow()
        return self._delete_voice_demo

    def reset_demo_coaching(self, profile_id):
        if profile_id == "DEMO_DELETE_VOICE_WAIT":
            self._one_step_delete_demo().reset()
            self.dat_trang_thai("idle", "Đã nạp lịch Toán 19:00 ngày mai trong dữ liệu DEMO.")
            return
        r = self.demo_coaching.reset(profile_id)
        self.demo_daily_store.reset_user(profile_id)
        self._demo_reminder_seen = {k for k in self._demo_reminder_seen if k[0] != profile_id}
        self._set_support_text(self.demo_coaching.status_text(r))
        self.nhan_chat_muc_ho_tro.setText(self.demo_coaching.status_text(r))
        self.nhan_goi_y_trong_ngay.show()
        self.cap_nhat_daily_coaching_plan()
        self._refresh_layout_after_mode_change()

    def bat_dau_demo_coaching(self, profile_id):
        if profile_id == "DEMO_DELETE_VOICE_WAIT":
            # Prepare only. No speech, no search, no delete until user actually speaks.
            self._one_step_delete_demo().start()
            self.dat_trang_thai("idle", "Đã chuẩn bị lịch Toán 19:00 ngày mai. Bạn có thể nói yêu cầu xóa.")
            return
        if hasattr(self, '_delete_voice_demo'):
            self._delete_voice_demo.stop()
        r = self.demo_coaching.start(profile_id)
        status = r.get("demo_status") or self.demo_coaching.status_text()
        self._set_support_text(status)
        self.nhan_chat_muc_ho_tro.setText(status)
        self.nhan_goi_y_trong_ngay.show()
        self.cap_nhat_daily_coaching_plan()
        self.dat_trang_thai("idle", r.get("reply", ""))
        self._refresh_layout_after_mode_change()
        self.noi(r.get("reply", ""), "idle")

    def _xu_ly_demo_neu_can(self, text):
        if hasattr(self, '_delete_voice_demo') and self._delete_voice_demo.stage != 'off':
            r = self._delete_voice_demo.handle(text)
            if r:
                self.kenh_tin_hieu.ket_qua.emit(r)
                return True
        if not getattr(self, "demo_coaching", None) or not self.demo_coaching.active:
            return False
        r = self.demo_coaching.handle(text)
        if not r:
            return False
        if r.get("demo_status"):
            self._set_support_text(r["demo_status"])
            self.nhan_chat_muc_ho_tro.setText(r["demo_status"])
        self.kenh_tin_hieu.ket_qua.emit(r)
        return True

    def doi_nguoi_dung_hien_tai(self, user_id):
        user_id = str(user_id or "").strip()
        if not user_id:
            return
        self.active_user_id = user_id
        self.dich_vu_pcbm.dat_nguoi_dung_hien_tai(user_id)
        settings = tai_cai_dat()
        settings["active_user_id"] = user_id
        luu_cai_dat(settings)
        print("[ACTIVE USER]", user_id)
        self.lam_moi_trang_thai_nguoi_dung()
        self._refresh_layout_after_mode_change()

    @staticmethod
    def _fmt_pct(value):
        if value is None:
            return "—"
        try:
            return f"{float(value):.1f}%"
        except Exception:
            return "—"

    def lam_moi_trang_thai_nguoi_dung(self):
        """Hiển thị user hiện tại + mức hỗ trợ PCBM mà không ghi dữ liệu test vào DB."""
        if not hasattr(self, "nhan_muc_ho_tro"):
            return
        uid = getattr(self, "active_user_id", "test_U036")
        try:
            t = self.dich_vu_nhiem_vu.lay_nhiem_vu_hien_tai()
            if not t.get("done"):
                title = t.get("task_name") or "Nhiệm vụ hiện tại"
                try:
                    base_level = int(self.bo_dinh_tuyen.dieu_phoi_pcbm.lay_muc_ho_tro(self.active_user_id))
                except Exception:
                    base_level = 1
                estimated = int(t.get("estimated_minutes") or 30)
            else:
                title = "Nhiệm vụ học tập"
                try:
                    base_level = int(self.bo_dinh_tuyen.dieu_phoi_pcbm.lay_muc_ho_tro(self.active_user_id))
                except Exception:
                    base_level = 1
                estimated = 30

            # User mô phỏng được neo theo lịch sử gần nhất để số liệu demo vẫn có ý nghĩa.
            decision_time = None
            if uid.startswith("test_") or uid.startswith("U"):
                decision_time = self.dich_vu_pcbm.thoi_diem_demo_theo_lich_su([uid])

            result = self.dich_vu_pcbm.thu_nghiem_kich_ban(
                uid, title, base_level, estimated, 1, "buddy", decision_time
            )
            pred = result.get("prediction") or {}
            profile = result.get("profile") or {}
            rec = int(pred.get("recommended_prompt_level", base_level))
            recall = self._fmt_pct(pred.get("recall_percent"))
            completion = self._fmt_pct(pred.get("completion_30m_percent"))
            cold = " • Cold-start" if profile.get("cold_start") else ""

            if rec < base_level:
                huong = "↓ giảm hỗ trợ"
                bg, border, fg = "#EAF7EF", "#A9D8B8", "#28623A"
            elif rec > base_level:
                huong = "↑ tăng hỗ trợ"
                bg, border, fg = "#FFF3E8", "#E9C39C", "#8B5520"
            else:
                huong = "= giữ mức"
                bg, border, fg = "#EEF5FB", "#BDD4E8", "#315E7D"

            text = (f"👤 {uid}   •   Hỗ trợ hiện tại: Level {base_level}   →   "
                    f"PCBM đề xuất: Level {rec} ({huong})   •   "
                    f"Recall {recall}   •   Completion≤30m {completion}{cold}")
            self._set_support_text(text, pred.get("reason_vi") or "")
            self._set_support_label_style(bg, border, fg)
            if hasattr(self, "nhan_chat_muc_ho_tro"):
                self.nhan_chat_muc_ho_tro.setText(
                    f"👤 {uid}  •  L{base_level}→L{rec}  •  Recall {recall}"
                )
                self.nhan_chat_muc_ho_tro.setToolTip(pred.get("reason_vi") or "")
        except Exception as e:
            print("[PCBM USER STATUS ERROR]", e)
            self._set_support_text(f"👤 {uid}  •  Chưa đủ dữ liệu để hiển thị mức hỗ trợ")
            if hasattr(self, "nhan_chat_muc_ho_tro"):
                self.nhan_chat_muc_ho_tro.setText(f"👤 {uid}  •  PCBM chưa sẵn sàng")

    def tu_dong_hoi_y_kien_muc_ho_tro(self):
        # No pop-up during test/demo data or when a dialog has already been shown for this user.
        uid=str(getattr(self,'active_user_id',''))
        if uid.startswith('test_') or uid.startswith('U'):
            return
        if self._last_review_auto_uid==uid:
            return
        self.mo_hoi_y_kien_muc_ho_tro(tu_dong=True)

    def mo_hoi_y_kien_muc_ho_tro(self, tu_dong=False):
        from PySide6.QtWidgets import QMessageBox
        coordinator=self.bo_dinh_tuyen.dieu_phoi_pcbm
        try:
            review=coordinator.xem_xet_thay_doi_muc(auto=tu_dong)
        except Exception as exc:
            if not tu_dong:
                QMessageBox.warning(self,'Mức hỗ trợ','Chưa thể đánh giá: '+str(exc))
            return
        if not review.get('eligible'):
            if not tu_dong:
                QMessageBox.information(self,'Mức hỗ trợ',
                    'Buddy đang giữ nguyên Level {}.\n{}'.format(review.get('current'),review.get('reason')))
            return
        old,new=review['current'],review['proposed']
        box=QMessageBox(self)
        box.setWindowTitle('Buddy hỏi ý kiến về mức hỗ trợ')
        box.setIcon(QMessageBox.Question)
        box.setText(f'Buddy đề xuất thay đổi Level {old} → Level {new}.')
        box.setInformativeText('Em muốn giữ nguyên mức hỗ trợ hiện tại, hay đồng ý thử theo đề xuất của AI?\n'
            'Chỉ số dự đoán là hỗ trợ tham khảo, không phải đánh giá y khoa.\n'
            'Buddy sẽ không tự giảm hỗ trợ.')
        btn_keep=box.addButton('Giữ nguyên', QMessageBox.AcceptRole)
        btn_accept=box.addButton('Đồng ý theo AI', QMessageBox.ActionRole)
        btn_later=box.addButton('Để sau', QMessageBox.RejectRole)
        coordinator.ghi_da_hoi(review)
        if tu_dong:
            self._last_review_auto_uid=str(self.active_user_id)
        box.exec()
        clicked=box.clickedButton()
        action=('keep' if clicked is btn_keep else 'accept' if clicked is btn_accept else 'later')
        result=coordinator.luu_quyet_dinh_muc(action,review)
        QMessageBox.information(self,'Buddy',result['message'])
        self.lam_moi_trang_thai_nguoi_dung()

    def mo_cai_dat(self):
        """Mở Settings. Thiết bị/buffer áp dụng từ lượt tiếp theo."""
        dlg = CuaSoCaiDat(self)
        if dlg.exec():
            print("[SETTINGS] Cài đặt mới sẽ áp dụng từ lượt tiếp theo")
            # Đưa focus về app; nếu đang ở chat thì trả focus cho ô nhập.
            if self.ngan_xep_giao_dien.currentWidget() is self.trang_chat:
                self.o_nhap_chat.setFocus()

    def mo_tro_giup(self):
        """Mở danh mục prompt mẫu và có thể đưa câu được chọn vào ô Chat."""
        dlg = CuaSoTroGiup(self)
        if dlg.exec() and dlg.prompt_da_chon:
            self.ngan_xep_giao_dien.setCurrentWidget(self.trang_chat)
            self.nut_chuyen_giao_dien.setText("🤖  Khuôn mặt")
            self.o_nhap_chat.setText(dlg.prompt_da_chon)
            self.o_nhap_chat.setFocus()
            self.o_nhap_chat.setCursorPosition(len(dlg.prompt_da_chon))
            sb = self.lich_su_chat.verticalScrollBar()
            sb.setValue(sb.maximum())
        elif self.ngan_xep_giao_dien.currentWidget() is self.trang_chat:
            self.o_nhap_chat.setFocus()

    def thoat_ung_dung(self):
        """Dừng audio/timer rồi thoát OneStep Buddy một cách gọn gàng."""
        try:
            self.dich_vu_doc_giong_noi.dung()
        except Exception:
            pass

        for ten_bo_hen_gio in (
            "bo_hen_gio_hoat_anh",
            "bo_hen_gio_lam_moi",
            "bo_hen_gio_nhac_nho",
            "bo_hen_gio_demo_daily",
        ):
            bo_hen_gio = getattr(self, ten_bo_hen_gio, None)
            if bo_hen_gio is not None:
                bo_hen_gio.stop()

        QApplication.instance().quit()

    def closeEvent(self, event):
        """Áp dụng cùng cơ chế dọn dẹp nếu cửa sổ bị đóng từ hệ điều hành."""
        try:
            self.dich_vu_doc_giong_noi.dung()
        except Exception:
            pass
        event.accept()

    def chuyen_giao_dien(self):
        """Chuyển qua lại giữa khuôn mặt Buddy và lịch sử hội thoại."""
        if self.ngan_xep_giao_dien.currentWidget() is self.trang_khuon_mat:
            self.ngan_xep_giao_dien.setCurrentWidget(self.trang_chat)
            self.nut_chuyen_giao_dien.setText("🤖  Khuôn mặt")
            # Luôn cuộn xuống tin nhắn mới nhất khi mở trang chat.
            sb = self.lich_su_chat.verticalScrollBar()
            sb.setValue(sb.maximum())
        else:
            self.ngan_xep_giao_dien.setCurrentWidget(self.trang_khuon_mat)
            self.nut_chuyen_giao_dien.setText("💬  Chat")
            self.tiep_theo_khung_hinh()

    def them_vao_lich_su_chat(self, vai_tro, noi_dung):
        """Thêm bubble chat bằng QWidget để căn lề, bo góc và wrap ổn định."""
        if not noi_dung:
            return

        # Xoá placeholder ở tin nhắn đầu tiên.
        if self.nhan_chat_trong is not None:
            self.nhan_chat_trong.hide()

        la_nguoi_dung = (vai_tro == "user")
        gio = datetime.now().strftime("%H:%M")

        dong = QWidget()
        dong.setStyleSheet("background:transparent;")
        # Không cho từng dòng tin nhắn ăn hết chiều cao còn trống của QScrollArea.
        # Đây là nguyên nhân làm bubble bị "kéo giãn" theo chiều dọc.
        dong.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        dong_lay = QHBoxLayout(dong)
        dong_lay.setContentsMargins(2, 2, 2, 2)
        dong_lay.setSpacing(10)

        cum = QWidget()
        cum.setStyleSheet("background:transparent;")
        cum.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        cum_lay = QVBoxLayout(cum)
        cum_lay.setContentsMargins(0, 0, 0, 0)
        cum_lay.setSpacing(4)

        meta = QLabel(("Bạn" if la_nguoi_dung else "OneStep Buddy") + f"  ·  {gio}")
        meta.setStyleSheet("font:13px Arial;color:#7A908A;")
        meta.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        meta.setAlignment(Qt.AlignRight if la_nguoi_dung else Qt.AlignLeft)
        cum_lay.addWidget(meta)

        bubble = QLabel(str(noi_dung))
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bubble.setMinimumWidth(90)
        # Giới hạn để hội thoại không kéo thành một dòng dài trên màn hình lớn.
        # Khoảng 45% màn hình giúp bubble gọn hơn và dễ đọc trên màn hình lớn.
        # Chặn tối đa 720 px để câu trả lời không trải quá ngang.
        viewport_w = max(900, self.lich_su_chat.viewport().width())
        bubble.setMaximumWidth(min(720, int(viewport_w * 0.46)))
        bubble.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        if la_nguoi_dung:
            bubble.setStyleSheet(
                "QLabel{background:#DDF2EC;border:1px solid #BEDDD4;border-radius:16px;"
                "padding:11px 15px;font:18px Arial;color:#173A33;}"
            )
        else:
            bubble.setStyleSheet(
                "QLabel{background:#F7FAF9;border:1px solid #DCE8E5;border-radius:16px;"
                "padding:11px 15px;font:18px Arial;color:#20303A;}"
            )

        # Chọn chiều rộng theo nội dung thay vì để QLabel co thành một cột hẹp.
        # Câu ngắn có bubble gọn, câu dài mới mở rộng tới giới hạn đã đặt.
        max_bubble_w = bubble.maximumWidth()
        text_w = bubble.fontMetrics().horizontalAdvance(str(noi_dung)) + 44
        desired_w = max(120, min(max_bubble_w, text_w))
        bubble.setFixedWidth(desired_w)
        cum_lay.addWidget(bubble)

        if la_nguoi_dung:
            dong_lay.addStretch(1)
            dong_lay.addWidget(cum, 0, Qt.AlignRight)
        else:
            # Avatar nhỏ cho Buddy giúp phân biệt hội thoại nhanh hơn.
            avatar = QLabel("OB")
            avatar.setAlignment(Qt.AlignCenter)
            avatar.setFixedSize(34, 34)
            avatar.setStyleSheet(
                "background:#E2F1ED;color:#2F7D6D;border-radius:17px;font:700 11px Arial;"
            )
            dong_lay.addWidget(avatar, 0, Qt.AlignTop)
            dong_lay.addWidget(cum, 0, Qt.AlignLeft)
            dong_lay.addStretch(1)

        # Chèn trước stretch cuối cùng để tin nhắn dồn từ trên xuống.
        idx = max(0, self.bo_cuc_tin_nhan.count() - 1)
        self.bo_cuc_tin_nhan.insertWidget(idx, dong)
        self._chat_message_widgets.append(dong)

        def _chot_chieu_cao_dong():
            # Sau khi Qt tính word-wrap, khóa chiều cao của dòng đúng theo nội dung.
            # Nhờ vậy nhiều message không bị chia đều toàn bộ chiều cao cửa sổ.
            dong.adjustSize()
            h = max(54, dong.sizeHint().height())
            dong.setMinimumHeight(h)
            dong.setMaximumHeight(h)
            self.noi_dung_chat.adjustSize()
            sb = self.lich_su_chat.verticalScrollBar()
            sb.setValue(sb.maximum())

        QTimer.singleShot(0, _chot_chieu_cao_dong)

    def gui_tin_nhan_ban_phim(self):
        """Gửi tin nhắn gõ từ bàn phím qua cùng pipeline intent/AI như STT."""
        text = self.o_nhap_chat.text().strip()
        if not text:
            return

        # Không chồng một yêu cầu mới lên lúc Buddy đang trả lời/xử lý.
        if self.dang_noi or self.dang_xu_ly:
            self.o_nhap_chat.setFocus()
            return

        self.o_nhap_chat.clear()
        self.them_vao_lich_su_chat("user", text)

        # Nếu microphone đang chờ, không thể ngắt InputStream an toàn từ UI;
        # đánh dấu để bỏ kết quả STT của lượt đó khi thread trả về.
        if self.dang_nghe:
            self._bo_qua_luot_nghe_tiep_theo = True
            self.dang_nghe = False

        self.dang_xu_ly = True
        self.dat_trang_thai("thinking", f"Bạn: {text}")

        if self._xu_ly_demo_neu_can(text):
            return

        def tien_trinh():
            try:
                self.kenh_tin_hieu.ket_qua.emit(self.bo_dinh_tuyen.xu_ly(text))
            except Exception as e:
                self.kenh_tin_hieu.loi.emit(str(e))

        threading.Thread(target=tien_trinh, daemon=True).start()

    @property
    def vong_deo_duoc_bat(self):
        return COACHING_DEVICE_MODE in {"band", "both"}

    @property
    def tro_ly_nhac_duoc_bat(self):
        return COACHING_DEVICE_MODE in {"home", "both"}

    def dat_trang_thai(self, s, text=None):
        self.trang_thai = s if (FACE_DIR / s).exists() else "idle"
        self.chi_so_khung_hinh = 0

        if s == "listening":
            self.lay_trang_thai_dich_vu.hide()
            self.thanh_muc_am_thanh.reset()
            self.thanh_muc_am_thanh.show()
        else:
            self.thanh_muc_am_thanh.hide()
            self.lay_trang_thai_dich_vu.show()
            if text:
                self.lay_trang_thai_dich_vu.setText(text)

        self.tiep_theo_khung_hinh()

    def khi_co_muc_am_thanh(self, rms, peak):
        """Cập nhật equalizer microphone trong lúc đang nghe."""
        if not self.dang_nghe:
            return
        self.thanh_muc_am_thanh.dat_muc(rms, peak)


    def tiep_theo_khung_hinh(self):
        if self.dang_hien_thi_anh_chup:
            return
        fs = sorted((FACE_DIR / self.trang_thai).glob("*.png"))
        if not fs:
            return
        p = fs[self.chi_so_khung_hinh % len(fs)]
        self.chi_so_khung_hinh += 1
        # Scale theo vùng hiển thị thực của QLabel, KHÔNG scale theo toàn cửa sổ.
        # Trước đây pixmap lớn làm sizeHint của QLabel tăng -> layout nở -> lần sau
        # scale lớn hơn nữa, tạo hiệu ứng khuôn mặt zoom to dần.
        target_w = max(1, self.nhan_khuon_mat.width())
        target_h = max(1, self.nhan_khuon_mat.height())
        key = (str(p), target_w, target_h)
        if key not in self.bo_nho_dem_khung_hinh:
            pix = QPixmap(str(p))
            pix = pix.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.bo_nho_dem_khung_hinh[key] = pix
        self.nhan_khuon_mat.setPixmap(self.bo_nho_dem_khung_hinh[key])

    def thay_doi_kich_thuoc(self, e):
        self.bo_nho_dem_khung_hinh.clear()
        super().resizeEvent(e)
        self._refresh_compact_headers()
        self.tiep_theo_khung_hinh()
    resizeEvent = thay_doi_kich_thuoc

    def lam_moi_nhiem_vu(self):
        self.lam_moi_trang_thai_nguoi_dung()
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

        # Mức hỗ trợ hiện tại được lưu riêng theo user bởi lớp điều phối PCBM.
        # PCBM chỉ đề xuất; level này chỉ đổi khi người dùng chấp nhận.
        try:
            base_level = int(self.bo_dinh_tuyen.dieu_phoi_pcbm.lay_muc_ho_tro(self.active_user_id))
        except Exception:
            base_level = self.dich_vu_huan_luyen.lay_muc_nhac(t)

        # PCBM dự đoán xác suất tự nhớ / hoàn thành từ lịch sử sự kiện cá nhân.
        # Mặc định PCBM chỉ đưa khuyến nghị. Đặt PCBM_APPLY_PROMPT_LEVEL=1 để cho phép
        # mô hình thay đổi một mức nhắc nhưng vẫn tuân thủ giới hạn huấn luyện ghi nhớ 0..2.
        rec = self.dich_vu_pcbm.de_xuat_muc_ho_tro(t, base_level, self.active_user_id)
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
        self.dat_trang_thai("listening")

        def tien_trinh():
            try:
                self.kenh_tin_hieu.da_nghe.emit(self.dich_vu_nhan_dang_giong_noi.lang_nghe_mot_lan())
            except Exception as e:
                self.kenh_tin_hieu.loi.emit(str(e))
        threading.Thread(target=tien_trinh, daemon=True).start()

    def khi_da_nghe(self, text):
        # Một tin nhắn bàn phím có thể đã được gửi trong khi thread STT còn chạy.
        # Bỏ kết quả cũ để tránh xử lý hai câu cùng lúc.
        if self._bo_qua_luot_nghe_tiep_theo:
            self._bo_qua_luot_nghe_tiep_theo = False
            self.dang_nghe = False
            return

        self.dang_nghe = False
        if not text:
            self.dat_trang_thai("error", "Mình chưa nghe rõ. Bạn nói lại nhé.")
            QTimer.singleShot(900, self.lang_nghe)
            return
        print("[HEARD]", text)
        self.them_vao_lich_su_chat("user", text)
        self.dang_xu_ly = True
        self.dat_trang_thai("thinking", f"Bạn: {text}")

        if self._xu_ly_demo_neu_can(text):
            return

        def tien_trinh():
            try:
                self.kenh_tin_hieu.ket_qua.emit(self.bo_dinh_tuyen.xu_ly(text))
            except Exception as e:
                self.kenh_tin_hieu.loi.emit(str(e))
        threading.Thread(target=tien_trinh, daemon=True).start()

    def khi_ket_qua(self, r):
        self.dang_xu_ly = False
        if r.get("refresh") and not r.get("demo"):
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
                QTimer.singleShot(650, self.lang_nghe)
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
        self.them_vao_lich_su_chat("assistant", text)
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
            QTimer.singleShot(650, self.lang_nghe)

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

    # Robot dùng màn hình cảm ứng nhưng không cần bàn phím ảo tự bật.
    # Giữ object này sống suốt vòng đời QApplication.
    app.bo_tat_ban_phim_ao = BoTatBanPhimAo(app)
    app.installEventFilter(app.bo_tat_ban_phim_ao)

    w = CuaSoTroLy()

    # Robot mode: dùng fullscreen thật để window manager không co cửa sổ
    # và không làm lộ desktop/dock ở các cạnh. Các control phía trên đã
    # được thu nhỏ và lùi vào trong nên vẫn nằm trong vùng an toàn.
    w.showFullScreen()
    w.raise_()
    w.activateWindow()
    # Window manager (X11) có thể đổi thứ tự xếp cửa sổ ngay sau showFullScreen.
    QTimer.singleShot(300, lambda: (w.raise_(), w.activateWindow()))
    sys.exit(app.exec())
