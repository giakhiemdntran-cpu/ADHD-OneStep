from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QVBoxLayout,
)

from dich_vu.cai_dat_nguoi_dung import (
    DEFAULTS,
    danh_sach_camera_usb,
    danh_sach_thiet_bi_am_thanh,
    khoi_phuc_mac_dinh,
    luu_cai_dat,
    tai_cai_dat,
)


class CuaSoCaiDat(QDialog):
    """Cài đặt phần cứng/TTS cho OneStep. Thay đổi áp dụng từ lượt tiếp theo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cài đặt OneStep Buddy")
        self.setMinimumWidth(650)
        self.setModal(True)
        self.setStyleSheet(
            "QDialog{background:#F3F8F6;color:#20303A;}"
            "QLabel{font:15px Arial;}"
            "QComboBox,QSpinBox,QDoubleSpinBox{background:white;border:1px solid #C9DCD7;"
            "border-radius:8px;padding:7px 10px;min-height:28px;font:15px Arial;}"
            "QPushButton{background:white;border:1px solid #C9DCD7;border-radius:9px;"
            "padding:8px 14px;font:600 14px Arial;}"
            "QPushButton:hover{background:#E7F2EF;}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        title = QLabel("⚙  Cài đặt thiết bị & giọng nói")
        title.setStyleSheet("font:700 22px Arial;color:#23463E;")
        root.addWidget(title)

        note = QLabel(
            "Mic, loa, camera và buffer VieNeu được áp dụng từ lượt nghe/nói/chụp kế tiếp. "
            "Không cần khởi động lại ứng dụng."
        )
        note.setWordWrap(True)
        note.setStyleSheet("font:14px Arial;color:#617872;")
        root.addWidget(note)

        panel = QFrame()
        panel.setStyleSheet("QFrame{background:#FFFFFF;border:1px solid #D8E6E2;border-radius:14px;}")
        form = QFormLayout(panel)
        form.setContentsMargins(18, 18, 18, 18)
        form.setHorizontalSpacing(20)
        form.setVerticalSpacing(13)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.cbo_mic = QComboBox()
        self.cbo_loa = QComboBox()
        inputs, outputs = danh_sach_thiet_bi_am_thanh()
        self.cbo_mic.addItem("Mặc định của Ubuntu", None)
        self.cbo_loa.addItem("Mặc định của Ubuntu", None)
        for d in inputs:
            rate = f" · {d['rate']} Hz" if d['rate'] else ""
            self.cbo_mic.addItem(f"[{d['index']}] {d['name']}{rate}", d["index"])
        for d in outputs:
            rate = f" · {d['rate']} Hz" if d['rate'] else ""
            self.cbo_loa.addItem(f"[{d['index']}] {d['name']}{rate}", d["index"])
        form.addRow("Microphone:", self.cbo_mic)
        form.addRow("Loa / Audio output:", self.cbo_loa)

        self.cbo_camera_source = QComboBox()
        self.cbo_camera_source.addItem("USB / V4L2", "usb")
        self.cbo_camera_source.addItem("CSI / nvarguscamerasrc", "csi")
        form.addRow("Loại camera:", self.cbo_camera_source)

        self.cbo_camera = QComboBox()
        for c in danh_sach_camera_usb():
            self.cbo_camera.addItem(f"/dev/video{c['index']} · {c['name']}", c["index"])
        form.addRow("Camera USB:", self.cbo_camera)

        self.spin_csi = QSpinBox()
        self.spin_csi.setRange(0, 9)
        form.addRow("CSI sensor-id:", self.spin_csi)

        self.cbo_voice = QComboBox()
        # Có thể nhập tên preset khác nếu package VieNeu có thêm voice.
        self.cbo_voice.setEditable(True)
        self.cbo_voice.addItems(["Mai Anh", "Ngọc Lam", "Hoàng Nam", "Minh Quang"])
        form.addRow("Giọng VieNeu:", self.cbo_voice)

        self.spin_buffer = QSpinBox()
        self.spin_buffer.setRange(50, 2000)
        self.spin_buffer.setSingleStep(50)
        self.spin_buffer.setSuffix(" ms")
        self.spin_buffer.setToolTip("Jetson: nên thử 350 ms, nếu còn giật tăng 450–500 ms")
        form.addRow("Startup buffer:", self.spin_buffer)

        self.cbo_blocksize = QComboBox()
        for value, label in ((0, "Auto"), (1024, "1024"), (2048, "2048 (khuyên dùng Jetson)"), (4096, "4096")):
            self.cbo_blocksize.addItem(label, value)
        form.addRow("Audio blocksize:", self.cbo_blocksize)

        self.spin_first_timeout = QDoubleSpinBox()
        self.spin_first_timeout.setRange(0.5, 15.0)
        self.spin_first_timeout.setSingleStep(0.5)
        self.spin_first_timeout.setSuffix(" s")
        form.addRow("First-audio timeout:", self.spin_first_timeout)

        self.spin_stall_timeout = QDoubleSpinBox()
        self.spin_stall_timeout.setRange(0.5, 15.0)
        self.spin_stall_timeout.setSingleStep(0.5)
        self.spin_stall_timeout.setSuffix(" s")
        form.addRow("Stream-stall timeout:", self.spin_stall_timeout)

        root.addWidget(panel)

        quick = QHBoxLayout()
        quick.addWidget(QLabel("Buffer nhanh:"))
        for value in (250, 350, 450, 500):
            button = QPushButton(f"{value} ms")
            button.clicked.connect(lambda checked=False, v=value: self.spin_buffer.setValue(v))
            quick.addWidget(button)
        quick.addStretch(1)
        root.addLayout(quick)

        bottom = QHBoxLayout()
        self.btn_default = QPushButton("Khôi phục mặc định")
        self.btn_default.clicked.connect(self._dat_mac_dinh_tren_form)
        bottom.addWidget(self.btn_default)
        bottom.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Lưu cài đặt")
        buttons.button(QDialogButtonBox.Cancel).setText("Hủy")
        buttons.accepted.connect(self._luu)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons)
        root.addLayout(bottom)

        self.cbo_camera_source.currentIndexChanged.connect(self._cap_nhat_camera_controls)
        self._nap(tai_cai_dat())

    @staticmethod
    def _set_combo_data(combo, value):
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _nap(self, s):
        self._set_combo_data(self.cbo_mic, s.get("audio_input_device"))
        self._set_combo_data(self.cbo_loa, s.get("audio_output_device"))
        self._set_combo_data(self.cbo_camera_source, s.get("camera_source", "usb"))
        self._set_combo_data(self.cbo_camera, int(s.get("camera_id", 0)))
        self.spin_csi.setValue(int(s.get("csi_sensor_id", 0)))
        self.cbo_voice.setCurrentText(str(s.get("vieneu_voice", "Mai Anh")))
        self.spin_buffer.setValue(int(s.get("vieneu_start_buffer_ms", 350)))
        self._set_combo_data(self.cbo_blocksize, int(s.get("vieneu_output_blocksize", 2048)))
        self.spin_first_timeout.setValue(float(s.get("vieneu_first_audio_timeout", 2.0)))
        self.spin_stall_timeout.setValue(float(s.get("vieneu_stream_stall_timeout", 1.5)))
        self._cap_nhat_camera_controls()

    def _cap_nhat_camera_controls(self):
        is_usb = self.cbo_camera_source.currentData() == "usb"
        self.cbo_camera.setEnabled(is_usb)
        self.spin_csi.setEnabled(not is_usb)

    def _collect(self):
        return {
            "audio_input_device": self.cbo_mic.currentData(),
            "audio_output_device": self.cbo_loa.currentData(),
            "camera_source": self.cbo_camera_source.currentData(),
            "camera_id": self.cbo_camera.currentData() if self.cbo_camera.currentData() is not None else 0,
            "csi_sensor_id": self.spin_csi.value(),
            "vieneu_voice": self.cbo_voice.currentText().strip() or "Mai Anh",
            "vieneu_start_buffer_ms": self.spin_buffer.value(),
            "vieneu_output_blocksize": int(self.cbo_blocksize.currentData() or 0),
            "vieneu_first_audio_timeout": self.spin_first_timeout.value(),
            "vieneu_stream_stall_timeout": self.spin_stall_timeout.value(),
        }

    def _luu(self):
        # Giữ nguyên các khóa khác trong user_settings.json (ví dụ help_prompts).
        settings = tai_cai_dat()
        settings.update(self._collect())
        luu_cai_dat(settings)
        self.accept()

    def _dat_mac_dinh_tren_form(self):
        self._nap(DEFAULTS)
