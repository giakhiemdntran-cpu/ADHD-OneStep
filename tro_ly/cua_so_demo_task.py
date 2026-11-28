"""Demo interactively showcases create-confirm-correct and fuzzy delete with double confirmation.
All state is in a private SQLite demo DB; does NOT call the real task service or ASR.
"""
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QListWidget, QPlainTextEdit, QMessageBox,
    QTabWidget, QWidget, QComboBox, QFrame, QScrollArea
)
from PySide6.QtCore import Qt
from cau_hinh import BASE_DIR
from dich_vu.demo_task_store import DemoTaskStore, tomorrow_at


class CuaSoDemoTask(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('OneStep • Demo xác nhận, sửa và xóa lịch an toàn')
        self.resize(850, 690)
        self.store=DemoTaskStore(Path(BASE_DIR)/'demo_coaching'/'task_confirmation_demo.sqlite3')
        self.pending_create=None
        self.delete_candidates=[]
        self.pending_delete=None
        self.delete_stage=0
        self._setup_ui()
        self.refresh()

    @staticmethod
    def btn(name, handler):
        b=QPushButton(name);b.setMinimumHeight(35);b.clicked.connect(handler);return b

    def _setup_ui(self):
        self.setStyleSheet('''
            QDialog {background:#F6FAFC;color:#1C3541;} QLabel {font-size:13px;}
            QGroupBox {font-size:14px;font-weight:bold;border:1px solid #CFE0E5;border-radius:9px;margin-top:10px;padding:10px;}
            QGroupBox::title {subcontrol-origin:margin;left:10px;padding:0 6px;}
            QPushButton {background:white;border:1px solid #AACBD1;border-radius:7px;padding:5px 12px;color:#164A51;font-weight:600;}
            QPushButton:hover {background:#DFF4F1;} QLineEdit,QComboBox,QListWidget,QPlainTextEdit {background:white;border:1px solid #C8DDE2;border-radius:6px;padding:5px;}
            QTabBar::tab {padding:9px 18px;} QTabBar::tab:selected {background:#DDF4EF;}
        ''')
        root=QVBoxLayout(self)
        heading=QLabel('🎬 DEMO • Buddy xác nhận trước khi tạo/xóa lịch')
        heading.setStyleSheet('font-weight:800;font-size:20px;color:#15564D;')
        root.addWidget(heading)
        sub=QLabel('DỮ LIỆU GIẢ LẬP • chỉ lưu tại demo_coaching/task_confirmation_demo.sqlite3 • Không tác động lịch thật')
        sub.setWordWrap(True);sub.setStyleSheet('color:#94622B;font-weight:600;');root.addWidget(sub)
        self.tabs=QTabWidget(); root.addWidget(self.tabs,1)
        self._build_create()
        self._build_delete()
        self._build_records()
        controls=QHBoxLayout()
        controls.addWidget(self.btn('↺ Reset lại kịch bản mẫu',self.reset))
        controls.addStretch(1)
        controls.addWidget(self.btn('Đóng',self.close))
        root.addLayout(controls)

    def _build_create(self):
        tab=QWidget();self.tabs.addTab(tab,'1. Tạo và xác nhận')
        lay=QVBoxLayout(tab)
        hint=QLabel('Tình huống: học sinh đặt lịch; Buddy nghe nhầm môn học. Xem kết quả mô phỏng ASR, sửa lại rồi xác nhận lưu.')
        hint.setWordWrap(True);lay.addWidget(hint)
        self.create_speech=QLabel('Học sinh nói: “Nhắc em làm bài tập Toán lúc 19:00 ngày mai.”')
        lay.addWidget(self.create_speech)
        lay.addWidget(self.btn('▶ Mô phỏng ASR nghe nhầm Toán → Văn',self.simulate_wrong_asr))
        note=QLabel('Đây là mô phỏng kết quả ASR để kiểm tra LUỒNG XÁC NHẬN, không phải kết quả microphone thật.')
        note.setStyleSheet('color:#A16620;');note.setWordWrap(True);lay.addWidget(note)
        box=QGroupBox('Thông tin Buddy hiểu được (có thể sửa trước khi lưu)');form=QGridLayout(box)
        form.addWidget(QLabel('Tên nhiệm vụ'),0,0)
        self.create_title=QLineEdit('Làm bài tập Toán');form.addWidget(self.create_title,0,1)
        form.addWidget(QLabel('Ngày và giờ (YYYY-MM-DD HH:MM)'),1,0)
        self.create_time=QLineEdit(tomorrow_at(19,0));form.addWidget(self.create_time,1,1)
        lay.addWidget(box)
        self.create_message=QLabel('Buddy chưa lưu gì. Hãy thử “Đọc lại lời nhắc”.')
        self.create_message.setWordWrap(True);self.create_message.setStyleSheet('background:#E8F6F2;padding:12px;border-radius:8px;');lay.addWidget(self.create_message)
        buttons=QHBoxLayout()
        buttons.addWidget(self.btn('🔊 Đọc lại / yêu cầu xác nhận',self.preview_create))
        buttons.addWidget(self.btn('✓ Đồng ý lưu',self.confirm_create))
        buttons.addWidget(self.btn('✕ Hủy',self.cancel_create))
        lay.addLayout(buttons)
        lay.addWidget(QLabel('Muốn demo sửa: đổi “Văn” thành “Toán” trong ô tên, sau đó bấm Đọc lại.'))
        lay.addStretch(1)

    def _build_delete(self):
        tab=QWidget();self.tabs.addTab(tab,'2. Xóa lịch có sẵn')
        lay=QVBoxLayout(tab)
        intro=QLabel('Trong database demo đã có lịch “Làm bài tập Toán” lúc 19:30 ngày mai. Người dùng nhớ nhầm là “khoảng 7 giờ tối”.')
        intro.setWordWrap(True);lay.addWidget(intro)
        box=QGroupBox('Câu lệnh muốn xóa');grid=QGridLayout(box)
        grid.addWidget(QLabel('Tên mà người dùng nhớ'),0,0)
        self.delete_title=QLineEdit('Làm bài tập Toán');grid.addWidget(self.delete_title,0,1)
        grid.addWidget(QLabel('Thời gian người dùng nhớ'),1,0)
        self.delete_time=QLineEdit(tomorrow_at(19,0));grid.addWidget(self.delete_time,1,1)
        lay.addWidget(box)
        lay.addWidget(self.btn('🔍 Tra cứu SQLite (±60 phút)',self.search_delete))
        self.match_combo=QComboBox();self.match_combo.currentIndexChanged.connect(self.change_candidate);lay.addWidget(self.match_combo)
        self.delete_message=QLabel('Buddy: Mình sẽ kiểm tra danh sách trước khi xóa. Chưa xóa nhiệm vụ nào.')
        self.delete_message.setWordWrap(True);self.delete_message.setStyleSheet('background:#FFF3DF;padding:14px;border-radius:8px;');lay.addWidget(self.delete_message)
        buttons=QHBoxLayout()
        buttons.addWidget(self.btn('✓ Đúng nhiệm vụ này',self.choose_delete))
        buttons.addWidget(self.btn('🗑 Xác nhận xóa',self.confirm_delete))
        buttons.addWidget(self.btn('✕ Không / Hủy',self.cancel_delete))
        lay.addLayout(buttons)
        lay.addWidget(QLabel('Quy tắc: TÌM → CHỌN/ĐÚNG → XÁC NHẬN XÓA. Không có bước nào tự xóa nhiệm vụ.'))
        lay.addStretch(1)

    def _build_records(self):
        tab=QWidget();self.tabs.addTab(tab,'3. SQLite & lịch sử')
        lay=QVBoxLayout(tab)
        lay.addWidget(QLabel('Nhiệm vụ còn hoạt động trong SQLite demo:'))
        self.task_list=QListWidget();lay.addWidget(self.task_list)
        lay.addWidget(QLabel('Nhật ký thao tác thực tế trên database DEMO:'))
        self.history=QPlainTextEdit();self.history.setReadOnly(True);lay.addWidget(self.history)
        lay.addWidget(self.btn('↻ Làm mới dữ liệu',self.refresh))

    def simulate_wrong_asr(self):
        self.create_title.setText('Làm bài tập Văn')
        self.create_time.setText(tomorrow_at(19,0))
        self.pending_create=None
        self.create_message.setText('🎤 ASR mô phỏng nghe nhầm: “Làm bài tập Văn”. Buddy chưa ghi dữ liệu. Hãy kiểm tra và sửa lại “Toán”.')

    def preview_create(self):
        title=self.create_title.text().strip();when=self.create_time.text().strip()
        try:
            from datetime import datetime
            datetime.strptime(when,'%Y-%m-%d %H:%M')
            if not title: raise ValueError('Thiếu tên nhiệm vụ')
        except Exception:
            self.pending_create=None
            self.create_message.setText('Buddy: Nội dung hoặc thời gian chưa hợp lệ. Bạn vui lòng sửa trước khi lưu.')
            return
        self.pending_create=(title,when)
        self.create_message.setText(f'🤖 Buddy: Mình hiểu bạn muốn tạo lịch “{title}” vào {when}. Đây có đúng là ý bạn không? Chọn Đồng ý để lưu, hoặc sửa thông tin trên rồi Đọc lại.')

    def confirm_create(self):
        if self.pending_create is None:
            self.create_message.setText('Buddy: Bạn hãy bấm “Đọc lại” để xác nhận nội dung trước khi lưu.')
            return
        if self.pending_create!=(self.create_title.text().strip(),self.create_time.text().strip()):
            self.pending_create=None
            self.create_message.setText('Buddy: Bạn vừa sửa nội dung. Mình cần đọc lại bản mới trước khi lưu.')
            return
        title,when=self.pending_create
        try: task_id=self.store.create(title,when)
        except Exception as ex:
            self.create_message.setText(f'Không thể lưu: {ex}');return
        self.pending_create=None
        self.create_message.setText(f'✅ Buddy: Đã lưu nhiệm vụ demo #{task_id} – {title} lúc {when}.')
        self.refresh()

    def cancel_create(self):
        self.pending_create=None
        self.create_message.setText('Buddy: Đã hủy yêu cầu. Không có nhiệm vụ mới nào được lưu.')

    def search_delete(self):
        self.pending_delete=None;self.delete_stage=0
        try:matches=self.store.find(self.delete_title.text(),self.delete_time.text(),60)
        except ValueError:
            self.delete_message.setText('Buddy: Thời gian chưa đúng dạng YYYY-MM-DD HH:MM. Mình chưa xóa gì.');return
        self.delete_candidates=matches
        self.match_combo.blockSignals(True);self.match_combo.clear()
        for r in matches:
            self.match_combo.addItem(f'#{r["id"]} • {r["title"]} • {r["scheduled_at"]} (lệch {r["delta_minutes"]} phút)',r['id'])
        self.match_combo.blockSignals(False)
        if not matches:
            self.delete_message.setText('🤖 Buddy: Mình không tìm thấy nhiệm vụ phù hợp trong SQLite. Chưa xóa gì. Bạn có thể nói rõ tên hoặc thời gian không?')
        elif len(matches)==1:
            r=matches[0]
            self.delete_message.setText(f'🤖 Buddy: Bạn nói khoảng 19:00. Mình tìm thấy “{r["title"]}” lúc {r["scheduled_at"]}. Có phải bạn muốn xóa nhiệm vụ này không?')
        else:
            self.delete_message.setText('🤖 Buddy: Mình tìm thấy vài nhiệm vụ gần giống. Bạn chọn đúng nhiệm vụ trong danh sách nhé. Mình chưa xóa gì.')

    def change_candidate(self,*_):
        self.pending_delete=None;self.delete_stage=0

    def choose_delete(self):
        idx=self.match_combo.currentIndex()
        if idx<0 or idx>=len(self.delete_candidates):
            self.delete_message.setText('Buddy: Bạn cần tìm và chọn nhiệm vụ trước.');return
        r=self.delete_candidates[idx]
        self.pending_delete=(r['id'],r['title'],r['scheduled_at'])
        self.delete_stage=1
        self.delete_message.setText(f'🤖 Buddy: Bạn muốn xóa CHÍNH XÁC nhiệm vụ “{r["title"]}” lúc {r["scheduled_at"]}, đúng không? Nếu chắc chắn, hãy bấm “Xác nhận xóa”.')

    def confirm_delete(self):
        if self.delete_stage!=1 or self.pending_delete is None:
            self.delete_message.setText('Buddy: Cần chọn “Đúng nhiệm vụ này” trước khi xác nhận xóa. Chưa có gì bị xóa.');return
        tid,title,when=self.pending_delete
        ok=self.store.delete_exact(tid,title,when)
        self.pending_delete=None;self.delete_stage=0
        self.delete_message.setText(f'✅ Buddy: Đã xóa nhiệm vụ “{title}” lúc {when} trong DEMO.' if ok else 'Buddy: Nhiệm vụ đã thay đổi hoặc không còn. Không xóa gì; vui lòng tìm lại.')
        self.match_combo.clear();self.delete_candidates=[];self.refresh()

    def cancel_delete(self):
        self.pending_delete=None;self.delete_stage=0
        self.delete_message.setText('Buddy: Đã hủy thao tác. Không có nhiệm vụ nào bị xóa.')

    def refresh(self):
        self.task_list.clear()
        for t in self.store.list_tasks():
            self.task_list.addItem(f'#{t["id"]} | {t["scheduled_at"]} | {t["title"]}')
        self.history.setPlainText('\n'.join(f'{x["created_at"]}  [{x["operation"]}] {x["detail"]}' for x in self.store.audit()))

    def reset(self):
        self.store.reset();self.pending_create=None;self.pending_delete=None;self.delete_stage=0
        self.delete_candidates=[];self.match_combo.clear()
        self.create_title.setText('Làm bài tập Toán');self.create_time.setText(tomorrow_at(19))
        self.delete_title.setText('Làm bài tập Toán');self.delete_time.setText(tomorrow_at(19))
        self.create_message.setText('Đã reset. Bắt đầu bằng “Mô phỏng ASR nghe nhầm”.')
        self.delete_message.setText('Đã reset dữ liệu mẫu: Toán 19:30, Ôn tập Toán 20:00, Đọc sách 21:00 ngày mai.')
        self.refresh()
