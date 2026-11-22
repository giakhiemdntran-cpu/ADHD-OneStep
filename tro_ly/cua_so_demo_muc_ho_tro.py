"""Hộp thoại Human-in-the-Loop DEMO, không ghi vào DB hay đổi Level thật."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QWidget,
)

class CuaSoDemoMucHoTro(QDialog):
    def __init__(self, current_level=1, proposed_level=0, parent=None):
        super().__init__(parent)
        self.current_level = int(current_level)
        self.proposed_level = int(proposed_level)
        self.action = None
        self.selected_level = self.current_level
        self.setWindowTitle("PCBM – Gợi ý hỗ trợ và ý kiến của bạn (DEMO)")
        self.setMinimumWidth(600)
        self.resize(660, 440)
        self.setStyleSheet("""
            QDialog { background:#F3F9F7; color:#263C3A; }
            QLabel { background:transparent; }
            QPushButton { min-height:38px; border-radius:7px; border:1px solid #B6D5D0;
                          background:#FFFFFF; color:#193D38; padding:4px 8px; }
            QPushButton:hover { background:#DFF4EF; border-color:#76C5BA; }
            QComboBox { min-height:34px; background:white; color:#193D38;
                        border:1px solid #B6D5D0; border-radius:5px; padding:3px; }
        """)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(20,18,20,18)
        layout.setSpacing(10)
        heading=QLabel("PCBM đề xuất: THỬ ĐIỀU CHỈNH MỨC HỖ TRỢ")
        heading.setStyleSheet("font-size:18px;font-weight:bold;color:#18635A")
        layout.addWidget(heading)
        msg=QLabel(
            f"Buddy nhận thấy trong tình huống mô phỏng, em đã có đủ lịch sử "
            f"để xem xét mức hỗ trợ. Buddy đề xuất thử từ Level "
            f"{self.current_level} xuống Level {self.proposed_level}. Em có muốn thử không?"
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)
        why=QLabel(
            "Giải thích: Đây là hồ sơ DEMO minh họa việc Buddy hỏi ý kiến người dùng. "
            "Kết quả mô phỏng không thay thế kiểm định độ tin cậy trên dữ liệu thật."
        )
        why.setWordWrap(True)
        why.setStyleSheet("font-size:12px;color:#657A78")
        layout.addWidget(why)
        banner=QLabel(f"Mức hiện tại: Level {self.current_level}     →     "
                      f"PCBM đề xuất: Level {self.proposed_level}")
        banner.setStyleSheet("font-weight:600;color:#164D45;padding:8px;background:#DFF0EA;border-radius:7px")
        layout.addWidget(banner)
        row1=QHBoxLayout(); row1.setSpacing(10)
        self._button(row1,"✓ Đồng ý với đề xuất","accept",highlight=True)
        self._button(row1,"= Chưa muốn thay đổi","keep")
        layout.addLayout(row1)
        row2=QHBoxLayout(); row2.setSpacing(10)
        self._button(row2,"+ Muốn hỗ trợ thêm","more")
        self._button(row2,"− Muốn giảm lời nhắc","less")
        layout.addLayout(row2)
        row3=QHBoxLayout()
        self._button(row3,"? Để quyết định sau","later")
        layout.addLayout(row3)
        optional=QHBoxLayout()
        optional.addWidget(QLabel("Hoặc chọn cụ thể:"))
        self.level_selector=QComboBox()
        for level,label in [(0,"Level 0 – Ít nhắc"),(1,"Level 1 – Gợi ý chung"),(2,"Level 2 – Nhắc rõ từng bước")]:
            self.level_selector.addItem(label,level)
        self.level_selector.setCurrentIndex(self.current_level)
        optional.addWidget(self.level_selector,1)
        btn=QPushButton("Thử mức đã chọn")
        btn.clicked.connect(lambda: self._choose("selected"))
        optional.addWidget(btn)
        layout.addLayout(optional)
        note=QLabel("CHỈ MÔ PHỎNG: Lựa chọn không thay đổi Level hoặc dữ liệu của người dùng thật.")
        note.setWordWrap(True)
        note.setStyleSheet("font-size:11px;color:#8B6224;padding-top:5px")
        layout.addWidget(note)

    def _button(self, row, title, action, highlight=False):
        button=QPushButton(title)
        if highlight:
            button.setStyleSheet("background:#E4F5F0;border:1px solid #63B6A9;font-weight:bold")
        button.clicked.connect(lambda _checked=False, a=action:self._choose(a))
        row.addWidget(button,1)

    def _choose(self, action):
        self.action = action
        if action == "selected":
            self.selected_level = int(self.level_selector.currentData())
        elif action == "more":
            self.action = "selected"
            self.selected_level = min(2,self.current_level+1)
        elif action == "less":
            self.action = "selected"
            self.selected_level = max(0,self.current_level-1)
        self.accept()
