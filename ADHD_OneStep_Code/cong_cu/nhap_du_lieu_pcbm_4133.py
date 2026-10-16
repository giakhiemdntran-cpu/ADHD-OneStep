#!/usr/bin/env python3
"""
Import bộ 4.133 sự kiện PCBM vào OneStep v9.9.

Mặc định:
- Đọc file: data/sample_events.jsonl
- Ghi vào bảng: pcbm_events
- user_id được thêm tiền tố "test_" để không lẫn dữ liệu thật
- Có thể reset riêng dữ liệu test trước khi import
- Có thể dịch toàn bộ timeline tới gần thời điểm hiện tại

Ví dụ:
    python cong_cu/nhap_du_lieu_pcbm_4133.py
    python cong_cu/nhap_du_lieu_pcbm_4133.py --reset
    python cong_cu/nhap_du_lieu_pcbm_4133.py --shift-to-now
    python cong_cu/nhap_du_lieu_pcbm_4133.py --reset --shift-to-now
    python cong_cu/nhap_du_lieu_pcbm_4133.py --file /path/to/OneStep_PCBM_sample_events_1500plus.jsonl
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

from dich_vu.co_so_du_lieu import khoi_tao_co_so_du_lieu, lay_ket_noi_csdl
from cau_hinh import DB_PATH

TEST_PREFIX = "test_"


def phan_tich_tham_so():
    p = argparse.ArgumentParser(
        description="Import 4.133 PCBM sample events vào OneStep v9.9"
    )
    p.add_argument(
        "--file",
        default=str(ROOT / "data" / "sample_events.jsonl"),
        help="Đường dẫn JSONL cần import",
    )
    p.add_argument(
        "--reset",
        action="store_true",
        help="Xóa pcbm_events test_* cũ trước khi import",
    )
    p.add_argument(
        "--shift-to-now",
        action="store_true",
        help="Dịch event mới nhất về khoảng 15 phút trước hiện tại",
    )
    p.add_argument(
        "--keep-user-id",
        action="store_true",
        help="Giữ nguyên U001... thay vì đổi thành test_U001...",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Số event insert mỗi batch",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ kiểm tra file, không ghi DB",
    )
    return p.phan_tich_tham_so()


def tai_su_kien(path: Path):
    events = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception as exc:
                raise RuntimeError(f"Lỗi JSON ở dòng {lineno}: {exc}") from exc

            required = {
                "event_id", "user_id", "task_id",
                "occurrence_id", "timestamp", "event_type"
            }
            missing = required - set(e)
            if missing:
                raise RuntimeError(
                    f"Dòng {lineno} thiếu field: {sorted(missing)}"
                )
            events.append(e)

    if not events:
        raise RuntimeError("File không có event nào.")

    return events


def dat_lai_kiem_thu_su_kien():
    with lay_ket_noi_csdl() as c:
        cur = c.execute(
            "DELETE FROM pcbm_events WHERE user_id LIKE ?",
            (TEST_PREFIX + "%",)
        )
        deleted = cur.rowcount
    print(f"[RESET] Đã xóa {deleted} event test cũ.")


def tinh_dich(events):
    parsed = [datetime.fromisoformat(e["timestamp"]) for e in events]
    latest = max(parsed)
    now = datetime.now(latest.tzinfo) if latest.tzinfo else datetime.now()
    return (now - timedelta(minutes=15)) - latest


def chuan_bi_dong(events, shift, keep_user_id):
    rows = []
    for e in events:
        ts = datetime.fromisoformat(e["timestamp"]) + shift

        user_id = str(e["user_id"])
        if not keep_user_id:
            user_id = TEST_PREFIX + user_id

        rows.append(
            (
                user_id,
                str(e.get("task_id") or ""),
                str(e.get("occurrence_id") or ""),
                str(e["event_type"]).upper().strip(),
                json.dumps(e.get("data") or {}, ensure_ascii=False),
                ts.replace(microsecond=0).isoformat(),
            )
        )
    return rows


def chen_lo(rows, batch_size=500):
    inserted = 0
    with lay_ket_noi_csdl() as c:
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            c.executemany(
                """
                INSERT INTO pcbm_events(
                    user_id,
                    task_id,
                    occurrence_id,
                    event_type,
                    data_json,
                    created_at
                )
                VALUES(?,?,?,?,?,?)
                """,
                batch,
            )
            inserted += len(batch)
            print(f"[IMPORT] {inserted}/{len(rows)} events")
    return inserted


def in_tom_tat():
    with lay_ket_noi_csdl() as c:
        total = c.execute(
            "SELECT COUNT(*) FROM pcbm_events"
        ).fetchone()[0]

        test_total = c.execute(
            "SELECT COUNT(*) FROM pcbm_events WHERE user_id LIKE ?",
            (TEST_PREFIX + "%",)
        ).fetchone()[0]

        users = c.execute(
            """
            SELECT user_id, COUNT(*) AS n
            FROM pcbm_events
            GROUP BY user_id
            ORDER BY n DESC
            """
        ).fetchall()

        types = c.execute(
            """
            SELECT event_type, COUNT(*) AS n
            FROM pcbm_events
            GROUP BY event_type
            ORDER BY n DESC
            """
        ).fetchall()

    print("\n===== PCBM DB SUMMARY =====")
    print("DB:", DB_PATH)
    print("Tổng pcbm_events:", total)
    print("Tổng test_* events:", test_total)

    print("\nTheo user:")
    for r in users[:20]:
        print(f"  {r['user_id']:<16} {r['n']}")

    print("\nTheo event_type:")
    for r in types:
        print(f"  {r['event_type']:<22} {r['n']}")


def chay_chuong_trinh():
    args = phan_tich_tham_so()

    khoi_tao_co_so_du_lieu()

    path = Path(args.file).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"Không tìm thấy file: {path}")

    events = tai_su_kien(path)

    users = sorted({e["user_id"] for e in events})
    event_types = sorted({e["event_type"] for e in events})

    print("File:", path)
    print("Số events:", len(events))
    print("Số users:", len(users))
    print("Users:", ", ".join(users))
    print("Event types:", ", ".join(event_types))

    if args.dry_run:
        print("[DRY-RUN] Không ghi dữ liệu vào DB.")
        return

    if args.reset:
        dat_lai_kiem_thu_su_kien()

    shift = timedelta(0)
    if args.shift_to_now:
        shift = tinh_dich(events)
        print("[SHIFT] Timeline được dịch:", shift)

    rows = chuan_bi_dong(
        events,
        shift=shift,
        keep_user_id=args.keep_user_id,
    )

    inserted = chen_lo(
        rows,
        batch_size=max(1, args.batch_size),
    )

    print(f"\n[DONE] Đã import {inserted} events.")
    in_tom_tat()


if __name__ == "__main__":
    chay_chuong_trinh()
