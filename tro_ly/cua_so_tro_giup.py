from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QListWidget,
    QListWidgetItem, QPushButton, QInputDialog, QMessageBox
)

from dich_vu.cai_dat_nguoi_dung import (
    DEFAULT_HELP_PROMPTS,
    luu_cai_dat,
    tai_cai_dat,
)


class CuaSoTroGiup(QDialog):
    """Xem và quản lý các prompt mẫu giao tiếp với OneStep Buddy."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.prompt_da_chon = ""
        self.cai_dat = tai_cai_dat()
        self.nhom_prompt = deepcopy(
            self.cai_dat.get("help_prompts") or DEFAULT_HELP_PROMPTS
        )

        self.setWindowTitle("Trợ giúp - Cách nói với OneStep Buddy")
        self.setMinimumSize(760, 600)
        self.resize(860, 660)
        self.setStyleSheet("""
            QDialog { background:#F2F9F7; color:#20303A; }
            QLabel#title { font:700 26px Arial; color:#20303A; }
            QLabel#hint { font:15px Arial; color:#6F8780; }
            QComboBox, QListWidget {
                background:#FFFFFF; border:1px solid #CFE1DD; border-radius:12px;
                padding:8px; font:16px Arial; color:#20303A;
            }
            QListWidget::item { padding:10px 8px; border-bottom:1px solid #EEF4F2; }
            QListWidget::item:selected { background:#DDF2EC; color:#173A33; }
            QPushButton {
                background:#FFFFFF; border:1px solid #CFE1DD; border-radius:16px;
                padding:9px 16px; font:600 15px Arial; color:#20303A;
            }
            QPushButton:hover { background:#E6F3F0; }
            QPushButton#usePrompt { background:#2F7D6D; color:#FFFFFF; border:none; }
            QPushButton#usePrompt:hover { background:#286E61; }
            QPushButton#deletePrompt { color:#A33A3A; }
            QPushButton#deletePrompt:hover { background:#F9EAEA; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)

        title = QLabel("Các câu nói mẫu với OneStep Buddy")
        title.setObjectName("title")
        root.addWidget(title)

        hint = QLabel(
            "Chọn tình huống để xem câu mẫu. Bạn có thể thêm, chỉnh sửa hoặc xóa prompt; "
            "mọi thay đổi được lưu tự động vào storage/user_settings.json."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.combo_nhom = QComboBox()
        self.combo_nhom.addItems(self.nhom_prompt.keys())
        self.combo_nhom.currentTextChanged.connect(self._tai_prompt)
        root.addWidget(self.combo_nhom)

        self.danh_sach = QListWidget()
        self.danh_sach.itemDoubleClicked.connect(lambda _: self._dung_prompt())
        root.addWidget(self.danh_sach, 1)

        edit_row = QHBoxLayout()
        self.btn_them = QPushButton("＋ Thêm prompt")
        self.btn_them.clicked.connect(self._them_prompt)
        edit_row.addWidget(self.btn_them)

        self.btn_sua = QPushButton("✎ Chỉnh sửa")
        self.btn_sua.clicked.connect(self._sua_prompt)
        edit_row.addWidget(self.btn_sua)

        self.btn_xoa = QPushButton("🗑 Xóa")
        self.btn_xoa.setObjectName("deletePrompt")
        self.btn_xoa.clicked.connect(self._xoa_prompt)
        edit_row.addWidget(self.btn_xoa)
        edit_row.addStretch(1)
        root.addLayout(edit_row)

        note = QLabel(
            "Mẹo: Bạn không cần nói đúng y nguyên câu mẫu. Hãy nói tự nhiên, nhưng nên nêu rõ "
            "việc cần làm, thời điểm hoặc đồ vật cần tìm khi có liên quan."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            "background:#FFFFFF;border:1px solid #D8E7E3;border-radius:12px;"
            "padding:12px;font:14px Arial;color:#567078;"
        )
        root.addWidget(note)

        actions = QHBoxLayout()
        actions.addStretch(1)
        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.reject)
        actions.addWidget(btn_close)

        btn_use = QPushButton("Đưa vào Chat")
        btn_use.setObjectName("usePrompt")
        btn_use.clicked.connect(self._dung_prompt)
        actions.addWidget(btn_use)
        root.addLayout(actions)

        self._tai_prompt(self.combo_nhom.currentText())

    def _tai_prompt(self, nhom, select_text=None):
        self.danh_sach.clear()
        for prompt in self.nhom_prompt.get(nhom, []):
            item = QListWidgetItem(prompt)
            item.setToolTip(prompt)
            self.danh_sach.addItem(item)

        if not self.danh_sach.count():
            return

        row = 0
        if select_text:
            for i in range(self.danh_sach.count()):
                if self.danh_sach.item(i).text() == select_text:
                    row = i
                    break
        self.danh_sach.setCurrentRow(row)

    def _luu_prompts(self):
        # Gộp với toàn bộ settings hiện có để không làm mất cấu hình mic/camera/TTS.
        self.cai_dat = tai_cai_dat()
        self.cai_dat["help_prompts"] = deepcopy(self.nhom_prompt)
        luu_cai_dat(self.cai_dat)

    def _them_prompt(self):
        nhom = self.combo_nhom.currentText().strip()
        if not nhom:
            return

        text, ok = QInputDialog.getMultiLineText(
            self,
            "Thêm prompt",
            f"Nhập prompt mới cho nhóm:\n{nhom}",
            "",
        )
        text = text.strip()
        if not ok or not text:
            return

        prompts = self.nhom_prompt.setdefault(nhom, [])
        if text in prompts:
            QMessageBox.information(self, "Prompt đã tồn tại", "Câu prompt này đã có trong nhóm hiện tại.")
            return

        prompts.append(text)
        self._luu_prompts()
        self._tai_prompt(nhom, text)

    def _sua_prompt(self):
        item = self.danh_sach.currentItem()
        nhom = self.combo_nhom.currentText().strip()
        if item is None or not nhom:
            return

        old_text = item.text().strip()
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Chỉnh sửa prompt",
            "Nội dung prompt:",
            old_text,
        )
        text = text.strip()
        if not ok or not text or text == old_text:
            return

        prompts = self.nhom_prompt.get(nhom, [])
        if text in prompts and text != old_text:
            QMessageBox.information(self, "Prompt đã tồn tại", "Câu prompt này đã có trong nhóm hiện tại.")
            return

        try:
            idx = prompts.index(old_text)
        except ValueError:
            return
        prompts[idx] = text
        self._luu_prompts()
        self._tai_prompt(nhom, text)

    def _xoa_prompt(self):
        item = self.danh_sach.currentItem()
        nhom = self.combo_nhom.currentText().strip()
        if item is None or not nhom:
            return

        text = item.text().strip()
        answer = QMessageBox.question(
            self,
            "Xóa prompt",
            f"Bạn có chắc muốn xóa prompt này?\n\n{text}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        prompts = self.nhom_prompt.get(nhom, [])
        if text in prompts:
            prompts.remove(text)
            self._luu_prompts()
            self._tai_prompt(nhom)

    def _dung_prompt(self):
        item = self.danh_sach.currentItem()
        if item is None:
            return
        self.prompt_da_chon = item.text().strip()
        if self.prompt_da_chon:
            self.accept()
