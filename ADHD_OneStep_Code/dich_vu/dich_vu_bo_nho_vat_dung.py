import json
from datetime import datetime, timedelta
from pathlib import Path

from cau_hinh import (
    VISION_RETENTION_HOURS,
    VISION_SIGHTING_DEDUPE_SECONDS,
    VISION_SNAPSHOT_DIR,
)
from dich_vu.co_so_du_lieu import lay_ket_noi_csdl


DISPLAY_NAMES = {
    "backpack": "cặp",
    "book": "sách",
    "bottle": "bình nước",
    "cell phone": "điện thoại",
    "laptop": "laptop",
    "cup": "cốc",
}

ZONE_VI = {
    "left": "bên trái khung hình",
    "center": "ở giữa khung hình",
    "right": "bên phải khung hình",
    "unknown": "trong vùng camera",
}


def lay_thoi_gian_hien_tai_iso():
    return datetime.now().isoformat(timespec="seconds")


class DichVuBoNhoVatDung:
    """Lưu siêu dữ liệu cục bộ và ảnh chụp trong thời gian ngắn; không ghi video."""

    def __init__(self):
        VISION_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    def hien_thi_ten(self, object_class):
        return DISPLAY_NAMES.get(object_class, object_class)

    def vung_van_ban(self, zone):
        return ZONE_VI.get(zone or "unknown", "trong vùng camera")

    def luu_lan_nhin_thay(self, object_class, confidence, camera_id, position_zone,
                      bbox, snapshot_path=None, force=False):
        seen_at = lay_thoi_gian_hien_tai_iso()
        label = self.hien_thi_ten(object_class)

        # Tránh tăng dữ liệu CSDL không cần thiết khi cùng vật thể vẫn ở cùng một vùng.
        if not force:
            last = self.lay_cuoi_da_thay(object_class)
            if last:
                try:
                    dt = datetime.fromisoformat(last["seen_at"])
                    age = (datetime.now() - dt).total_seconds()
                except Exception:
                    age = VISION_SIGHTING_DEDUPE_SECONDS + 1
                if (age < VISION_SIGHTING_DEDUPE_SECONDS and
                        (last.get("position_zone") or "") == (position_zone or "")):
                    return last

        with lay_ket_noi_csdl() as c:
            cur = c.execute("""
                INSERT INTO object_sightings(
                    object_class, object_label, confidence, camera_id,
                    position_zone, bbox_json, seen_at, snapshot_path, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
            """, (
                object_class,
                label,
                float(confidence or 0.0),
                str(camera_id),
                position_zone,
                json.dumps(bbox or [], ensure_ascii=False),
                seen_at,
                str(snapshot_path) if snapshot_path else None,
                seen_at,
            ))
            sid = cur.lastrowid
            row = c.execute("SELECT * FROM object_sightings WHERE id=?", (sid,)).fetchone()
        return dict(row)

    def lay_cuoi_da_thay(self, object_class):
        with lay_ket_noi_csdl() as c:
            row = c.execute("""
                SELECT * FROM object_sightings
                WHERE object_class=?
                ORDER BY seen_at DESC, id DESC
                LIMIT 1
            """, (object_class,)).fetchone()
        return dict(row) if row else None

    def lay_lan_nhin_thay(self, sighting_id):
        with lay_ket_noi_csdl() as c:
            row = c.execute(
                "SELECT * FROM object_sightings WHERE id=?",
                (int(sighting_id),)
            ).fetchone()
        return dict(row) if row else None

    def lay_du_lieu_gan_day(self, limit=100):
        limit = max(1, min(int(limit), 500))
        with lay_ket_noi_csdl() as c:
            rows = c.execute("""
                SELECT * FROM object_sightings
                ORDER BY seen_at DESC, id DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return [dict(x) for x in rows]

    def don_dep_ban_ghi_cu(self, hours=None):
        hours = int(hours or VISION_RETENTION_HOURS)
        cutoff = datetime.now() - timedelta(hours=hours)

        with lay_ket_noi_csdl() as c:
            rows = c.execute("""
                SELECT id, snapshot_path FROM object_sightings
                WHERE seen_at < ?
            """, (cutoff.isoformat(timespec="seconds"),)).fetchall()

            ids = [int(x["id"]) for x in rows]
            paths = [x["snapshot_path"] for x in rows if x["snapshot_path"]]

            if ids:
                marks = ",".join("?" for _ in ids)
                c.execute(f"DELETE FROM object_sightings WHERE id IN ({marks})", ids)

        # Chỉ xóa ảnh chụp khi không còn bản ghi CSDL nào tham chiếu đến ảnh đó.
        removed_files = 0
        for raw in set(paths):
            try:
                with lay_ket_noi_csdl() as c:
                    ref = c.execute(
                        "SELECT COUNT(*) AS n FROM object_sightings WHERE snapshot_path=?",
                        (raw,)
                    ).fetchone()["n"]
                if int(ref) == 0:
                    p = Path(raw)
                    if p.exists() and VISION_SNAPSHOT_DIR in p.parents:
                        p.unlink()
                        removed_files += 1
            except Exception as e:
                print("[VISION CLEANUP FILE ERROR]", raw, e)

        return {
            "removed_records": len(ids),
            "removed_files": removed_files,
            "retention_hours": hours,
        }

    def mo_ta(self, sighting):
        if not sighting:
            return None
        name = sighting.get("object_label") or self.hien_thi_ten(sighting.get("object_class"))
        zone = self.vung_van_ban(sighting.get("position_zone"))
        seen = (sighting.get("seen_at") or "").replace("T", " ")
        return f"{name} - {zone} - {seen}"
