"""PySide6 widget for OneStep Daily Coaching Plan.

Usage:
    widget = DailyCoachingWidget(store=CoachingActionStore(), user_id="user01")
    widget.set_suggestions([{"id":"morning_bag_2026-11-12", "title":"Chuẩn bị cặp"}])

Pass on_action(result) to integrate with the existing TaskService. The default
widget only logs the action; it does NOT mutate the existing task database.
"""
from __future__ import annotations

from typing import Callable, Optional
from PySide6.QtCore import QTimer, Qt
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QDialog, QHBoxLayout,
    QScrollArea, QMessageBox, QInputDialog
)
from dich_vu.coaching_actions import ActionResult, CoachingActionStore

STATUS_TEXT = {
    "pending": "Chưa bắt đầu", "in_progress": "Đang thực hiện",
    "snoozed": "Đã hẹn nhắc lại", "done": "Đã hoàn thành", "skipped": "Đã bỏ qua"
}


class DailyCoachingWidget(QWidget):
    def __init__(self, store: CoachingActionStore, user_id: str = "user01",
                 on_action: Optional[Callable[[ActionResult], None]] = None, parent=None):
        super().__init__(parent)
        self.store = store
        self.user_id = user_id
        self.on_action = on_action
        self.suggestions: list[dict] = []
        self.setWindowTitle("Daily Coaching Plan")
        root = QVBoxLayout(self)
        self.heading = QLabel("📅 Daily Coaching Plan • DEMO")
        self.heading.setStyleSheet("font-size: 22px; font-weight: bold")
        root.addWidget(self.heading)
        self.subtitle = QLabel("")
        root.addWidget(self.subtitle)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body = QWidget()
        self.items_layout = QVBoxLayout(self.body)
        self.items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.body)
        root.addWidget(self.scroll)
        self.timer = QTimer(self)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def set_user(self, user_id: str):
        if not str(user_id).strip():
            raise ValueError("user_id cannot be empty")
        self.user_id = str(user_id)
        self.refresh()

    def set_suggestions(self, suggestions: list[dict]):
        """Each item needs a stable 'id' and display 'title'. Optional 'detail'.

        Use a stable per-day ID (for example task-id + date) so action state
        persists when suggestions are refreshed.
        """
        for item in suggestions:
            if not item.get("id") or not item.get("title"):
                raise ValueError("Each suggestion must have id and title")
        ids = [str(x["id"]) for x in suggestions]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate suggestion IDs")
        self.suggestions = list(suggestions)
        self.refresh()

    def refresh(self):
        self.subtitle.setText(f"Hồ sơ demo: {self.user_id} • Nhấn vào từng gợi ý để chọn hành động")
        while self.items_layout.count():
            item = self.items_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if not self.suggestions:
            self.items_layout.addWidget(QLabel("Chưa có gợi ý hôm nay."))
            return
        for suggestion in self.suggestions:
            state = self.store.state(self.user_id, str(suggestion["id"]))
            label = STATUS_TEXT.get(state["status"], state["status"])
            if state.get("reminder_due"):
                label = "⏰ Đến giờ nhắc lại"
            if state["status"] == "snoozed" and state.get("snooze_until"):
                label += " (đến " + datetime.fromisoformat(state["snooze_until"]).astimezone().strftime("%H:%M") + ")"
            button = QPushButton(f"{suggestion.get('time', '--:--')} • {suggestion['title']}\n{suggestion.get('detail', '')}\nTrạng thái: {label}")
            button.setMinimumHeight(80)
            button.setStyleSheet("text-align:left; padding:12px; font-size:16px; border:1px solid #999; border-radius:9px")
            button.clicked.connect(lambda checked=False, s=suggestion: self.open_actions(s))
            self.items_layout.addWidget(button)

    def open_actions(self, suggestion: dict):
        dlg = QDialog(self)
        dlg.setWindowTitle(str(suggestion["title"]))
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(f"Bạn muốn làm gì với: {suggestion['title']}?"))
        buttons = [
            ("▶ Bắt đầu ngay", "start"),
            ("⏰ Nhắc lại sau", "snooze"),
            ("✅ Đã hoàn thành", "done"),
            ("⏭ Bỏ qua", "skip"),
        ]
        for title, action in buttons:
            btn = QPushButton(title)
            btn.setMinimumHeight(44)
            btn.clicked.connect(lambda checked=False, a=action: self._selected(dlg, suggestion, a))
            layout.addWidget(btn)
        dlg.exec()

    def _selected(self, dialog: QDialog, suggestion: dict, action: str):
        minutes = 10
        if action == "snooze":
            minutes, ok = QInputDialog.getInt(self, "Nhắc lại sau", "Số phút:", 10, 1, 1440)
            if not ok:
                return
        if action == "done":
            reply = QMessageBox.question(self, "Xác nhận hoàn thành",
                                         "Bạn xác nhận đã hoàn thành gợi ý này?")
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            result = self.store.perform(self.user_id, str(suggestion["id"]), action,
                                        snooze_minutes=minutes)
            if self.on_action:
                self.on_action(result)
        except Exception as exc:
            QMessageBox.warning(self, "Không thể thực hiện", str(exc))
            self.refresh()
            return
        dialog.accept()
        self.refresh()
