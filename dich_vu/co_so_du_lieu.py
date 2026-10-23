import sqlite3
from contextlib import contextmanager
from cau_hinh import DB_PATH


def _cot(c, table):
    return {x[1] for x in c.execute(f"PRAGMA table_info({table})").fetchall()}


def _them_cot(c, table, definition):
    name = definition.split()[0]
    if name not in _cot(c, table):
        c.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def khoi_tao_co_so_du_lieu():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            steps TEXT NOT NULL DEFAULT '[]',
            schedule_type TEXT NOT NULL DEFAULT 'once',
            scheduled_at TEXT,
            scheduled_time TEXT,
            repeat_days TEXT NOT NULL DEFAULT '[]',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT 'web',
            created_at TEXT NOT NULL
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS task_occurrences(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            scheduled_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            current_step INTEGER NOT NULL DEFAULT 0,
            snooze_count INTEGER NOT NULL DEFAULT 0,
            reminded_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(task_id, scheduled_at)
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS task_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            scheduled_at TEXT,
            completed_at TEXT NOT NULL,
            snooze_count INTEGER NOT NULL DEFAULT 0,
            final_status TEXT NOT NULL DEFAULT 'completed'
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS band_notifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            occurrence_id INTEGER,
            type TEXT NOT NULL,
            message TEXT NOT NULL,
            dedupe_key TEXT UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            action TEXT,
            action_at TEXT
        )""")

        # Chuyển đổi dữ liệu huấn luyện thời gian từ v8.
        _them_cot(c, "tasks", "estimated_minutes INTEGER")
        _them_cot(c, "tasks", "deadline_at TEXT")
        _them_cot(c, "tasks", "habit_key TEXT")
        _them_cot(c, "task_occurrences", "started_at TEXT")
        _them_cot(c, "task_occurrences", "start_delay_minutes REAL")
        _them_cot(c, "task_occurrences", "actual_minutes REAL")
        _them_cot(c, "task_history", "estimated_minutes INTEGER")
        _them_cot(c, "task_history", "actual_minutes REAL")
        _them_cot(c, "task_history", "start_delay_minutes REAL")
        _them_cot(c, "task_history", "habit_key TEXT")

        # Hồ sơ huấn luyện ghi nhớ v9; success_streak cũ được giữ để tương thích CSDL.
        c.execute("""
        CREATE TABLE IF NOT EXISTS habit_profiles(
            habit_key TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            prompt_level INTEGER NOT NULL DEFAULT 2,
            success_streak INTEGER NOT NULL DEFAULT 0,
            total_completed INTEGER NOT NULL DEFAULT 0,
            total_snoozes INTEGER NOT NULL DEFAULT 0,
            avg_actual_minutes REAL,
            last_completed_at TEXT,
            updated_at TEXT NOT NULL
        )""")
        _them_cot(c, "habit_profiles", "memory_success_streak INTEGER NOT NULL DEFAULT 0")
        _them_cot(c, "habit_profiles", "memory_failure_streak INTEGER NOT NULL DEFAULT 0")
        _them_cot(c, "habit_profiles", "last_memory_result TEXT")
        _them_cot(c, "habit_profiles", "last_execution_result TEXT")
        _them_cot(c, "habit_profiles", "last_response_at TEXT")
        # Chuyển mọi hồ sơ mức 3 của v8 về mức tối đa 2 trong v9.
        c.execute("UPDATE habit_profiles SET prompt_level=2 WHERE prompt_level>2")

        c.execute("""
        CREATE TABLE IF NOT EXISTS coaching_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            occurrence_id INTEGER,
            habit_key TEXT,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS memory_checks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurrence_id INTEGER NOT NULL UNIQUE,
            task_id INTEGER,
            task_title TEXT NOT NULL,
            habit_key TEXT,
            prompt_level INTEGER NOT NULL,
            scheduled_at TEXT,
            check_due_at TEXT,
            status TEXT NOT NULL,
            prompt_sent_at TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            response_text TEXT,
            recall_text TEXT,
            memory_result TEXT,
            execution_result TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")

        # v9.5: lịch sử bộ nhớ vật dụng / thị giác.
        c.execute("""
        CREATE TABLE IF NOT EXISTS object_sightings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_class TEXT NOT NULL,
            object_label TEXT,
            confidence REAL,
            camera_id TEXT,
            position_zone TEXT,
            bbox_json TEXT,
            seen_at TEXT NOT NULL,
            snapshot_path TEXT,
            created_at TEXT NOT NULL
        )""")
        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_object_sightings_class_seen
        ON object_sightings(object_class, seen_at DESC)
        """)


        # v9.9: nhật ký sự kiện PCBM trực tiếp và kết quả dự đoán mô hình.
        c.execute("""
        CREATE TABLE IF NOT EXISTS pcbm_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL DEFAULT 'local_user',
            task_id TEXT,
            occurrence_id TEXT,
            event_type TEXT NOT NULL,
            data_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )""")
        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_pcbm_events_user_time
        ON pcbm_events(user_id, created_at)
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS pcbm_predictions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL DEFAULT 'local_user',
            task_id TEXT,
            occurrence_id TEXT,
            decision_type TEXT NOT NULL,
            features_json TEXT NOT NULL DEFAULT '{}',
            output_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )""")
        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_pcbm_predictions_user_time
        ON pcbm_predictions(user_id, created_at)
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS pcbm_training_runs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            event_count INTEGER NOT NULL DEFAULT 0,
            record_count INTEGER NOT NULL DEFAULT 0,
            user_count INTEGER NOT NULL DEFAULT 0,
            recall_rows INTEGER NOT NULL DEFAULT 0,
            completion_rows INTEGER NOT NULL DEFAULT 0,
            metrics_json TEXT NOT NULL DEFAULT '{}',
            recall_model_path TEXT,
            completion_model_path TEXT,
            created_at TEXT NOT NULL
        )""")
        # PCBM v4: lưu rõ phiên bản pipeline/dataset của từng lần huấn luyện.
        _them_cot(c, "pcbm_training_runs", "training_version TEXT")
        _them_cot(c, "pcbm_training_runs", "dataset_name TEXT")

        c.commit()


@contextmanager
def lay_ket_noi_csdl():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c

        # v9.5: lịch sử bộ nhớ vật dụng / thị giác.
        c.execute("""
        CREATE TABLE IF NOT EXISTS object_sightings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_class TEXT NOT NULL,
            object_label TEXT,
            confidence REAL,
            camera_id TEXT,
            position_zone TEXT,
            bbox_json TEXT,
            seen_at TEXT NOT NULL,
            snapshot_path TEXT,
            created_at TEXT NOT NULL
        )""")
        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_object_sightings_class_seen
        ON object_sightings(object_class, seen_at DESC)
        """)

        c.commit()
    finally:
        c.close()
