from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton


class CuaSoDemoCoaching(QDialog):
    def __init__(self, profiles, on_start, on_reset, parent=None):
        super().__init__(parent)
        self.profiles = profiles
        self.on_start = on_start
        self.on_reset = on_reset
        self.setWindowTitle("Demo Coaching Mode")
        self.setModal(True)
        self.resize(560, 300)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        title = QLabel("🎬 Demo Coaching Mode")
        title.setStyleSheet("font:700 20px Arial;color:#204F45;")
        root.addWidget(title)
        note = QLabel("Dữ liệu demo tách riêng, không ghi vào lịch sử người dùng thật. Chọn 1 hồ sơ để thấy PCBM coaching khác nhau.")
        note.setWordWrap(True)
        note.setStyleSheet("font:13px Arial;color:#48635D;")
        root.addWidget(note)
        self.combo = QComboBox()
        for p in profiles:
            self.combo.addItem(p["label"], p["user_id"])
        self.combo.insertSeparator(self.combo.count())
        self.combo.addItem("🗑 Demo xóa lịch — chờ người dùng ra lệnh", "DEMO_DELETE_VOICE_WAIT")
        self.combo.addItem("🗓 Tạo lịch / sửa khi nghe nhầm / xóa lịch (demo)", "DEMO_TASK_CONFIRM_DELETE")
        self.combo.currentIndexChanged.connect(self._update_desc)
        root.addWidget(self.combo)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("background:#EEF7F4;border-radius:10px;padding:10px;font:13px Arial;color:#2D544B;")
        root.addWidget(self.desc)
        self.plan = QLabel()
        self.plan.setWordWrap(True)
        self.plan.setStyleSheet("background:#FFF8E8;border:1px solid #E8D59A;border-radius:10px;padding:9px;font:12px Arial;color:#5A4A22;")
        root.addWidget(self.plan)
        row = QHBoxLayout()
        reset = QPushButton("Reset dữ liệu demo")
        start = QPushButton("▶ Bắt đầu Demo")
        close = QPushButton("Đóng")
        reset.clicked.connect(self._reset)
        start.clicked.connect(self._start)
        close.clicked.connect(self.reject)
        for b in (reset,start,close):
            b.setMinimumHeight(34)
        row.addWidget(reset); row.addStretch(1); row.addWidget(close); row.addWidget(start)
        root.addLayout(row)
        self._update_desc()

    def _selected(self):
        return self.combo.currentData()

    def _update_desc(self, *_):
        uid=self._selected()
        if uid == "DEMO_DELETE_VOICE_WAIT":
            self.desc.setText("Chỉ nạp sẵn trong SQLite demo: Làm bài tập Toán lúc 19:00 ngày mai. Buddy không nói hoặc xóa gì khi bắt đầu. Sau đó hãy NÓI hoặc GÕ yêu cầu xóa trên màn hình Buddy.")
            self.plan.setText("Bước 1: Bắt đầu Demo → chờ. Bước 2: Nói: Xóa lịch làm bài tập Toán khoảng 7 giờ tối ngày mai. Bước 3: Xác nhận đúng nhiệm vụ. Bước 4: Xác nhận xóa.")
            return
        if uid == "DEMO_TASK_CONFIRM_DELETE":
            self.desc.setText("Tình huống giao tiếp an toàn: Buddy nghe nhầm khi tạo lịch, người dùng sửa và xác nhận; khi xóa, Buddy tìm nhiệm vụ có sẵn trong SQLite demo và hỏi lại trước khi xóa.")
            self.plan.setText("🗓 Dữ liệu có sẵn: Làm bài tập Toán lúc 19:30 ngày mai; Ôn tập Toán lúc 20:00; Đọc sách lúc 21:00. Chọn Bắt đầu Demo để mở kịch bản.")
            return
        p=next((x for x in self.profiles if x["user_id"]==uid), {})
        habit = p.get("habit_summary", "")
        self.desc.setText(p.get("description", "") + ("\nThói quen: " + habit if habit else ""))
        lines = [f"{x.get('time','--:--')}  {x.get('title','')}" for x in (p.get('daily_plan') or [])]
        self.plan.setText("🗓 Gợi ý trong ngày\n" + "   •   ".join(lines))

    def _reset(self):
        if self._selected() == "DEMO_DELETE_VOICE_WAIT":
            self.on_reset("DEMO_DELETE_VOICE_WAIT")
            self.desc.setText("Đã khôi phục lịch mẫu 19:00 ngày mai; Buddy đang chờ yêu cầu.")
            return
        if self._selected() == "DEMO_TASK_CONFIRM_DELETE":
            from pathlib import Path
            from cau_hinh import BASE_DIR
            from dich_vu.demo_task_store import DemoTaskStore
            DemoTaskStore(Path(BASE_DIR)/"demo_coaching"/"task_confirmation_demo.sqlite3").reset()
            self.desc.setText("✓ Đã khôi phục lịch mẫu trong SQLite demo. Không đụng đến lịch thật.")
            return
        self.on_reset(self._selected())
        self.desc.setText(self.desc.text()+"\n✓ Dữ liệu demo đã được reset về seed ban đầu.")

    def _start(self):
        if self._selected() == "DEMO_DELETE_VOICE_WAIT":
            self.on_start("DEMO_DELETE_VOICE_WAIT")
            self.accept()
            return
        if self._selected() == "DEMO_TASK_CONFIRM_DELETE":
            from tro_ly.cua_so_demo_task import CuaSoDemoTask
            dlg = CuaSoDemoTask(self)
            dlg.exec()
            return
        self.on_start(self._selected())
        self.accept()
