#!/usr/bin/env python3
"""
OneStep v9.9 - Test DB Importer

Mục đích:
1) Import sample PCBM event log từ data/sample_events.jsonl vào SQLite.
2) Tạo dữ liệu vận hành giả lập cho Dashboard/Streamlit:
   tasks, task_occurrences, task_history, habit_profiles,
   coaching_events, memory_checks, object_sightings.
3) Có thể xóa CHỈ dữ liệu test do tool này tạo.

Ví dụ:
    python cong_cu/nhap_du_lieu_kiem_thu.py --all
    python cong_cu/nhap_du_lieu_kiem_thu.py --pcbm-only
    python cong_cu/nhap_du_lieu_kiem_thu.py --app-only
    python cong_cu/nhap_du_lieu_kiem_thu.py --reset
    python cong_cu/nhap_du_lieu_kiem_thu.py --reset --all

Dữ liệu test được đánh dấu bằng:
- tasks.created_by = "test_import"
- habit_key bắt đầu bằng "test_"
- pcbm_events.user_id bắt đầu bằng "test_"
- object_sightings.camera_id = "test_camera"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cau_hinh import DB_PATH
from dich_vu.co_so_du_lieu import khoi_tao_co_so_du_lieu, lay_ket_noi_csdl

TEST_CREATED_BY = "test_import"
TEST_USER_PREFIX = "test_"
TEST_CAMERA_ID = "test_camera"


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def phan_tich_tham_so():
    p = argparse.ArgumentParser(description="Import dữ liệu test cho OneStep v9.9 SQLite DB")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--pcbm-only", action="store_true", help="Chỉ import sample PCBM events")
    group.add_argument("--app-only", action="store_true", help="Chỉ tạo dữ liệu app/dashboard")
    group.add_argument("--all", action="store_true", help="Import cả PCBM + dữ liệu app (mặc định)")
    p.add_argument("--reset", action="store_true", help="Xóa dữ liệu test do tool này tạo trước khi import")
    p.add_argument("--reset-only", action="store_true", help="Chỉ xóa dữ liệu test rồi thoát")
    p.add_argument("--dry-run", action="store_true", help="Chỉ hiển thị kế hoạch, không ghi DB")
    p.add_argument(
        "--sample",
        default=str(ROOT / "data" / "sample_events.jsonl"),
        help="Đường dẫn sample_events.jsonl",
    )
    p.add_argument(
        "--shift-to-now",
        action="store_true",
        help="Dịch timeline sample PCBM để event mới nhất gần thời điểm hiện tại",
    )
    return p.phan_tich_tham_so()


def lay_kiem_thu_nhiem_vu_ma(c):
    return [
        r[0]
        for r in c.execute(
            "SELECT id FROM tasks WHERE created_by=? OR habit_key LIKE 'test_%'",
            (TEST_CREATED_BY,),
        ).fetchall()
    ]


def dat_lai_kiem_thu_du_lieu(dry_run=False):
    if dry_run:
        print("[DRY-RUN] Sẽ xóa dữ liệu test_import/test_* khỏi DB")
        return

    with lay_ket_noi_csdl() as c:
        task_ids = lay_kiem_thu_nhiem_vu_ma(c)
        if task_ids:
            qs = ",".join("?" * len(task_ids))
            # Xử lý các bảng con trước.
            c.execute(f"DELETE FROM band_notifications WHERE task_id IN ({qs})", task_ids)
            c.execute(f"DELETE FROM memory_checks WHERE task_id IN ({qs})", task_ids)
            c.execute(f"DELETE FROM coaching_events WHERE task_id IN ({qs})", task_ids)
            c.execute(f"DELETE FROM task_history WHERE task_id IN ({qs})", task_ids)
            c.execute(f"DELETE FROM task_occurrences WHERE task_id IN ({qs})", task_ids)
            c.execute(f"DELETE FROM tasks WHERE id IN ({qs})", task_ids)

        c.execute("DELETE FROM habit_profiles WHERE habit_key LIKE 'test_%'")
        c.execute("DELETE FROM object_sightings WHERE camera_id=?", (TEST_CAMERA_ID,))
        c.execute("DELETE FROM pcbm_predictions WHERE user_id LIKE 'test_%'")
        c.execute("DELETE FROM pcbm_events WHERE user_id LIKE 'test_%'")

    print("[RESET] Đã xóa dữ liệu test do tool tạo.")


def tai_mau_su_kien(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rows.append(json.loads(line))
    return rows


def nhap_pcbm_su_kien(sample_path: Path, shift_to_now=False, dry_run=False):
    events = tai_mau_su_kien(sample_path)
    if not events:
        print("[PCBM] Không có sample event.")
        return 0

    shift = timedelta(0)
    if shift_to_now:
        parsed = [datetime.fromisoformat(e["timestamp"]) for e in events]
        latest = max(parsed)
        now = datetime.now(latest.tzinfo) if latest.tzinfo else datetime.now()
        # Giữ sự kiện mới nhất ở khoảng 15 phút trước thời điểm hiện tại.
        shift = (now - timedelta(minutes=15)) - latest

    prepared = []
    for e in events:
        ts = datetime.fromisoformat(e["timestamp"]) + shift
        prepared.append(
            (
                TEST_USER_PREFIX + str(e["user_id"]),
                "sample_" + str(e.get("task_id") or ""),
                "sample_" + str(e.get("occurrence_id") or ""),
                str(e["event_type"]).upper(),
                json.dumps(e.get("data") or {}, ensure_ascii=False),
                iso(ts),
            )
        )

    if dry_run:
        print(f"[DRY-RUN][PCBM] Sẽ import {len(prepared)} events từ {sample_path}")
        return len(prepared)

    with lay_ket_noi_csdl() as c:
        # Xóa dữ liệu người dùng mẫu đã nhập trước để hạn chế trùng lặp khi chạy lại.
        c.execute("DELETE FROM pcbm_events WHERE user_id LIKE 'test_U%'")
        c.executemany(
            """INSERT INTO pcbm_events(
                user_id, task_id, occurrence_id, event_type, data_json, created_at
            ) VALUES(?,?,?,?,?,?)""",
            prepared,
        )

    print(f"[PCBM] Đã import {len(prepared)} sample events.")
    return len(prepared)


def them_nhiem_vu(c, *, title, scheduled_at, status="pending", habit_key=None,
             prompt_level=2, estimated=20, snoozes=0, started_at=None,
             completed_at=None, actual_minutes=None, deadline_at=None,
             steps=None):
    now = datetime.now()
    steps = steps or []
    cur = c.execute(
        """INSERT INTO tasks(
            title, steps, schedule_type, scheduled_at, scheduled_time,
            repeat_days, enabled, created_by, created_at,
            estimated_minutes, deadline_at, habit_key
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            title,
            json.dumps(steps, ensure_ascii=False),
            "once",
            iso(scheduled_at),
            scheduled_at.strftime("%H:%M"),
            "[]",
            1,
            TEST_CREATED_BY,
            iso(now - timedelta(days=7)),
            estimated,
            iso(deadline_at) if deadline_at else None,
            habit_key,
        ),
    )
    task_id = cur.lastrowid

    occ = c.execute(
        """INSERT INTO task_occurrences(
            task_id, scheduled_at, status, current_step, snooze_count,
            reminded_at, completed_at, created_at, started_at,
            start_delay_minutes, actual_minutes
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            task_id,
            iso(scheduled_at),
            status,
            len(steps) if status == "completed" and steps else 0,
            snoozes,
            iso(scheduled_at - timedelta(minutes=5)) if status != "pending" or scheduled_at <= now else None,
            iso(completed_at) if completed_at else None,
            iso(now - timedelta(days=7)),
            iso(started_at) if started_at else None,
            ((started_at - scheduled_at).total_seconds() / 60.0) if started_at else None,
            actual_minutes,
        ),
    )
    occurrence_id = occ.lastrowid

    if habit_key:
        c.execute(
            """INSERT OR REPLACE INTO habit_profiles(
                habit_key,label,prompt_level,success_streak,total_completed,total_snoozes,
                avg_actual_minutes,last_completed_at,updated_at,
                memory_success_streak,memory_failure_streak,last_memory_result,
                last_execution_result,last_response_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                habit_key,
                title,
                prompt_level,
                2 if prompt_level <= 1 else 0,
                6 if status == "completed" else 4,
                snoozes + 1,
                float(actual_minutes or estimated),
                iso(completed_at) if completed_at else None,
                iso(now),
                3 if prompt_level <= 1 else 0,
                0,
                "remembered" if prompt_level <= 1 else "unknown",
                "completed" if status == "completed" else "pending",
                iso(now - timedelta(hours=1)),
            ),
        )

    if completed_at:
        c.execute(
            """INSERT INTO task_history(
                task_id,title,scheduled_at,completed_at,snooze_count,final_status,
                estimated_minutes,actual_minutes,start_delay_minutes,habit_key
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id,
                title,
                iso(scheduled_at),
                iso(completed_at),
                snoozes,
                "completed",
                estimated,
                actual_minutes,
                ((started_at - scheduled_at).total_seconds() / 60.0) if started_at else None,
                habit_key,
            ),
        )

    return task_id, occurrence_id


def chen_huan_luyen_su_kien(c, task_id, occ_id, habit_key, event_type, payload, at):
    c.execute(
        """INSERT INTO coaching_events(
            task_id,occurrence_id,habit_key,event_type,payload,created_at
        ) VALUES(?,?,?,?,?,?)""",
        (
            task_id,
            occ_id,
            habit_key,
            event_type,
            json.dumps(payload, ensure_ascii=False),
            iso(at),
        ),
    )


def nhap_ung_dung_du_lieu(dry_run=False):
    now = datetime.now()

    if dry_run:
        print("[DRY-RUN][APP] Sẽ tạo 8 task + occurrence/history/coaching/memory/vision test.")
        return

    with lay_ket_noi_csdl() as c:
        # Tránh dữ liệu trùng khi chạy lặp lại.
        task_ids = lay_kiem_thu_nhiem_vu_ma(c)
        if task_ids:
            print("[APP] Đã có dữ liệu test. Dùng --reset --all để tạo lại.")
            return

        # 1. Nhiệm vụ học tập đã hoàn thành
        sched = now - timedelta(days=2, hours=1)
        started = sched + timedelta(minutes=6)
        completed = started + timedelta(minutes=34)
        t1, o1 = them_nhiem_vu(
            c,
            title="[TEST] Làm bài Toán",
            scheduled_at=sched,
            status="completed",
            habit_key="test_math_homework",
            prompt_level=1,
            estimated=30,
            snoozes=0,
            started_at=started,
            completed_at=completed,
            actual_minutes=34,
            deadline_at=sched + timedelta(hours=2),
            steps=["Mở bài tập", "Làm câu 1-5", "Kiểm tra đáp án"],
        )
        chen_huan_luyen_su_kien(c, t1, o1, "test_math_homework", "RECALL_SUCCESS",
                              {"prompt_level": 1}, sched + timedelta(minutes=1))
        chen_huan_luyen_su_kien(c, t1, o1, "test_math_homework", "TASK_COMPLETED",
                              {"actual_minutes": 34}, completed)

        # 2. Nhiệm vụ chuẩn bị đã hoàn thành, thành công ở mức 0
        sched2 = now - timedelta(days=1, hours=2)
        started2 = sched2 + timedelta(minutes=2)
        completed2 = started2 + timedelta(minutes=7)
        t2, o2 = them_nhiem_vu(
            c,
            title="[TEST] Chuẩn bị cặp đi học",
            scheduled_at=sched2,
            status="completed",
            habit_key="test_prepare_bag",
            prompt_level=0,
            estimated=10,
            started_at=started2,
            completed_at=completed2,
            actual_minutes=7,
        )
        chen_huan_luyen_su_kien(c, t2, o2, "test_prepare_bag", "MEMORY_LEVEL0_SUCCESS",
                              {"memory_result": "remembered"}, completed2)

        # 3. Nhiệm vụ đã hoãn / đang chờ
        sched3 = now - timedelta(minutes=25)
        t3, o3 = them_nhiem_vu(
            c,
            title="[TEST] Đọc sách 20 phút",
            scheduled_at=sched3,
            status="pending",
            habit_key="test_reading",
            prompt_level=2,
            estimated=20,
            snoozes=2,
        )
        chen_huan_luyen_su_kien(c, t3, o3, "test_reading", "SNOOZE",
                              {"minutes": 5, "count": 2}, sched3 + timedelta(minutes=3))

        # 4. Nhiệm vụ hiện tại đã đến hạn
        sched4 = now - timedelta(minutes=2)
        t4, o4 = them_nhiem_vu(
            c,
            title="[TEST] Uống nước",
            scheduled_at=sched4,
            status="pending",
            habit_key="test_drink_water",
            prompt_level=1,
            estimated=5,
        )

        # 5-6. Các nhiệm vụ trong tương lai
        them_nhiem_vu(
            c,
            title="[TEST] Ôn tiếng Anh",
            scheduled_at=now + timedelta(hours=1),
            status="pending",
            habit_key="test_english",
            prompt_level=1,
            estimated=25,
            deadline_at=now + timedelta(hours=3),
        )
        them_nhiem_vu(
            c,
            title="[TEST] Chuẩn bị đồ thể thao",
            scheduled_at=now + timedelta(hours=2),
            status="pending",
            habit_key="test_sport_bag",
            prompt_level=2,
            estimated=10,
        )

        # 7. Một nhiệm vụ lịch sử bị bỏ lỡ / còn chờ
        them_nhiem_vu(
            c,
            title="[TEST] Sắp xếp bàn học",
            scheduled_at=now - timedelta(days=1, hours=4),
            status="pending",
            habit_key="test_desk",
            prompt_level=2,
            estimated=15,
            snoozes=1,
        )

        # 8. Nhiệm vụ nhiều bước trong tương lai
        them_nhiem_vu(
            c,
            title="[TEST] Hoàn thành bài thuyết trình",
            scheduled_at=now + timedelta(hours=4),
            status="pending",
            habit_key="test_presentation",
            prompt_level=2,
            estimated=45,
            deadline_at=now + timedelta(hours=7),
            steps=["Mở slide", "Viết nội dung", "Kiểm tra", "Luyện nói"],
        )

        # Các lần kiểm tra ghi nhớ (một đã hoàn thành, một đang chờ)
        c.execute(
            """INSERT OR REPLACE INTO memory_checks(
                occurrence_id,task_id,task_title,habit_key,prompt_level,
                scheduled_at,check_due_at,status,prompt_sent_at,attempts,
                response_text,recall_text,memory_result,execution_result,
                created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                o2, t2, "[TEST] Chuẩn bị cặp đi học", "test_prepare_bag", 0,
                iso(sched2), iso(sched2 + timedelta(minutes=10)), "completed",
                iso(sched2 + timedelta(minutes=10)), 1,
                "Mình đã nhớ", "Chuẩn bị cặp đi học", "remembered", "completed",
                iso(sched2), iso(completed2),
            ),
        )
        c.execute(
            """INSERT OR REPLACE INTO memory_checks(
                occurrence_id,task_id,task_title,habit_key,prompt_level,
                scheduled_at,check_due_at,status,prompt_sent_at,attempts,
                response_text,recall_text,memory_result,execution_result,
                created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                o3, t3, "[TEST] Đọc sách 20 phút", "test_reading", 2,
                iso(sched3), iso(sched3 + timedelta(minutes=10)), "pending",
                None, 0, None, None, None, None,
                iso(sched3), iso(now),
            ),
        )

        # Thị giác / bộ nhớ vật dụng
        sightings = [
            ("backpack", "Cặp", 0.91, "center", now - timedelta(minutes=35)),
            ("bottle", "Chai nước", 0.88, "left", now - timedelta(minutes=18)),
            ("book", "Sách", 0.84, "right", now - timedelta(hours=3)),
            ("cell phone", "Điện thoại", 0.79, "center", now - timedelta(days=1)),
        ]
        for cls, label, conf, zone, seen in sightings:
            c.execute(
                """INSERT INTO object_sightings(
                    object_class,object_label,confidence,camera_id,position_zone,
                    bbox_json,seen_at,snapshot_path,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    cls, label, conf, TEST_CAMERA_ID, zone,
                    json.dumps([100, 80, 220, 210]),
                    iso(seen), None, iso(seen),
                ),
            )

    print("[APP] Đã tạo dữ liệu task/history/coaching/memory/vision test.")


def in_tom_tat():
    with lay_ket_noi_csdl() as c:
        tables = [
            "tasks",
            "task_occurrences",
            "task_history",
            "habit_profiles",
            "coaching_events",
            "memory_checks",
            "object_sightings",
            "pcbm_events",
            "pcbm_predictions",
        ]
        print("\n===== DB SUMMARY =====")
        print("DB:", DB_PATH)
        for table in tables:
            try:
                n = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                print(f"{table:22s}: {n}")
            except Exception as e:
                print(f"{table:22s}: ERROR {e}")


def chay_chuong_trinh():
    args = phan_tich_tham_so()
    khoi_tao_co_so_du_lieu()

    if args.reset or args.reset_only:
        dat_lai_kiem_thu_du_lieu(args.dry_run)

    if args.reset_only:
        in_tom_tat()
        return

    do_pcbm = not args.app_only
    do_app = not args.pcbm_only

    if do_pcbm:
        sample = Path(args.sample)
        if not sample.exists():
            raise SystemExit(f"Không tìm thấy sample file: {sample}")
        nhap_pcbm_su_kien(
            sample,
            shift_to_now=args.shift_to_now,
            dry_run=args.dry_run,
        )

    if do_app:
        nhap_ung_dung_du_lieu(dry_run=args.dry_run)

    if not args.dry_run:
        in_tom_tat()

    print("\nHoàn tất.")
    if not args.dry_run:
        print("Mở Streamlit -> Dashboard / PCBM AI / Data Browser để kiểm tra.")


if __name__ == "__main__":
    chay_chuong_trinh()
