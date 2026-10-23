from flask import Flask, jsonify, render_template, request, send_file, abort
from dich_vu.co_so_du_lieu import khoi_tao_co_so_du_lieu
from dich_vu.dich_vu_nhiem_vu import DichVuNhiemVu
from dich_vu.dich_vu_ai import DichVuAI
from dich_vu.dich_vu_huan_luyen import DichVuHuanLuyen
from dich_vu.thoi_gian_chay import lay_dich_vu_thi_giac
from dich_vu.dich_vu_vong_deo import DichVuVongDeo
from dich_vu.dich_vu_pcbm import DichVuPCBM
from cau_hinh import ADHD_MODE_ENABLED, COACHING_DEVICE_MODE


def tao_ung_dung_web():
    khoi_tao_co_so_du_lieu()
    app = Flask(__name__, template_folder="templates")
    dich_vu_nhiem_vu = DichVuNhiemVu()
    dich_vu_ai = DichVuAI()
    dich_vu_huan_luyen = DichVuHuanLuyen(dich_vu_nhiem_vu, dich_vu_ai)
    dich_vu_thi_giac = lay_dich_vu_thi_giac()
    dich_vu_vong_deo = DichVuVongDeo(dich_vu_nhiem_vu, dich_vu_huan_luyen)
    dich_vu_pcbm = DichVuPCBM()
    dich_vu_vong_deo.dam_bao_luoc_do()

    @app.get("/")
    @app.get("/tasks")
    def trang_chu():
        return render_template("admin.html")


    @app.get("/api/health")
    def kiem_tra_he_thong():
        from cau_hinh import OLLAMA_MODEL, APP_TIMEZONE, DB_PATH
        return jsonify({
            "success": True,
            "service": "ADHD OneStep",
            "version": "9.9-pcbm-integrated",
            "ollama_model": OLLAMA_MODEL,
            "timezone": APP_TIMEZONE,
            "db_path": str(DB_PATH),
            "adhd_mode_enabled": ADHD_MODE_ENABLED,
            "coaching_device_mode": COACHING_DEVICE_MODE,
        })

    @app.post("/api/ai/parse")
    def ai_phan_tich():
        d = request.get_json(silent=True) or {}
        text = (d.get("text") or "").strip()
        if not text:
            return jsonify({"success": False, "message": "Thiếu text."}), 400
        try:
            return jsonify({"success": True, "command": dich_vu_ai.phan_tich_lenh(text)})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.post("/api/ai/plan")
    def ai_lap_ke_hoach():
        d = request.get_json(silent=True) or {}
        title = (d.get("title") or "").strip()
        if not title:
            return jsonify({"success": False, "message": "Thiếu title."}), 400
        try:
            return jsonify({"success": True, "steps": dich_vu_ai.lap_ke_hoach_nhiem_vu(title)})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.post("/api/tasks/current/complete")
    def hoan_thanh_nhiem_vu_hien_tai():
        try:
            result = dich_vu_nhiem_vu.hoan_thanh_hien_tai_buoc()
            if result.get("done"):
                dich_vu_huan_luyen.khi_da_hoan_thanh(result)
                dich_vu_pcbm.ghi_su_kien("TASK_COMPLETED", result.get("task_id"), result.get("occurrence_id"), result)
            return jsonify(result)
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 400

    @app.post("/api/tasks/current/snooze")
    def hoan_nhiem_vu_hien_tai():
        d = request.get_json(silent=True) or {}
        try:
            minutes = max(1, min(int(d.get("minutes", 5)), 120))
            cur = dich_vu_nhiem_vu.lay_nhiem_vu_hien_tai()
            result = dich_vu_nhiem_vu.hoan_nhiem_vu_hien_tai(minutes)
            if not cur.get("done"):
                dich_vu_huan_luyen.khi_hoan(cur)
                dich_vu_pcbm.ghi_su_kien("SNOOZE", cur.get("task_id"), cur.get("occurrence_id"), {"minutes": minutes})
            return jsonify(result)
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 400

    @app.post("/api/tasks/current/cancel")
    def huy_nhiem_vu_hien_tai():
        try:
            return jsonify(dich_vu_nhiem_vu.huy_hien_tai_nhiem_vu())
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 400

    @app.get("/api/state")
    def lay_trang_thai_vong_deo_api():
        return jsonify({
            "tasks": dich_vu_nhiem_vu.liet_ke_nhiem_vu(),
            "history": dich_vu_nhiem_vu.lay_lich_su(),
            "current": dich_vu_nhiem_vu.lay_nhiem_vu_hien_tai(),
            "coaching": dich_vu_huan_luyen.lay_tien_do(),
            "memory_checks": dich_vu_huan_luyen.lay_kiem_tra_ghi_nho(20),
            "vision": dich_vu_thi_giac.lay_trang_thai_dich_vu(),
            "adhd_mode_enabled": ADHD_MODE_ENABLED,
            "coaching_device_mode": COACHING_DEVICE_MODE,
        })

    @app.post("/api/tasks")
    def tao_nhiem_vu_api():
        d = request.get_json(silent=True) or {}
        try:
            t = dich_vu_nhiem_vu.them_nhiem_vu(
                d.get("title"), d.get("steps", []), d.get("schedule_type", "once"),
                d.get("scheduled_at"), d.get("scheduled_time"), d.get("repeat_days", []),
                "web", d.get("estimated_minutes"), d.get("deadline_at"), d.get("habit_key")
            )
            if t.get("habit_key"):
                dich_vu_huan_luyen.lay_hoac_tao_thoi_quen(t["habit_key"], t["title"])
            dich_vu_pcbm.ghi_su_kien(
                "TASK_CREATED", t.get("id"), None,
                {
                    "title": t.get("title"),
                    "task_type": dich_vu_pcbm._suy_ra_nhiem_vu_loai(t.get("title")),
                    "priority": 1,
                    "estimated_minutes": t.get("estimated_minutes"),
                    "deadline_at": t.get("deadline_at"),
                    "schedule_type": t.get("schedule_type"),
                }
            )
            return jsonify({"success": True, "task": t})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 400

    @app.put("/api/tasks/<int:tid>")
    def cap_nhat(tid):
        try:
            return jsonify({"success": True, "task": dich_vu_nhiem_vu.cap_nhat_nhiem_vu(tid, request.get_json(silent=True) or {})})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 400

    @app.delete("/api/tasks/<int:tid>")
    def xoa_nhiem_vu_api(tid):
        dich_vu_nhiem_vu.xoa_nhiem_vu(tid)
        return jsonify({"success": True})

    @app.post("/api/tasks/<int:tid>/cancel")
    def huy(tid):
        return jsonify(dich_vu_nhiem_vu.huy_nhiem_vu(tid))

    @app.post("/api/tasks/current/start")
    def bat_dau_hien_tai():
        cur = dich_vu_nhiem_vu.lay_nhiem_vu_hien_tai()
        result = dich_vu_nhiem_vu.bat_dau_hien_tai_nhiem_vu()
        if not cur.get("done") and result.get("success"):
            dich_vu_pcbm.ghi_su_kien("TASK_STARTED", cur.get("task_id"), cur.get("occurrence_id"), result)
        return jsonify(result)

    @app.get("/api/coaching/progress")
    def lay_tien_do_huan_luyen():
        return jsonify({"success": True, "habits": dich_vu_huan_luyen.lay_tien_do(request.args.get("habit_key"))})

    @app.get("/api/coaching/memory-checks")
    def lay_kiem_tra_ghi_nho_huan_luyen():
        return jsonify({"success": True, "checks": dich_vu_huan_luyen.lay_kiem_tra_ghi_nho(int(request.args.get("limit", 100)))})

    @app.get("/api/coaching/events")
    def lay_su_kien_huan_luyen():
        return jsonify({
            "success": True,
            "events": dich_vu_huan_luyen.lay_su_kien_huan_luyen(int(request.args.get("limit", 100))),
        })

    @app.get("/api/coaching/config")
    def lay_cau_hinh_huan_luyen():
        return jsonify({"adhd_mode_enabled": ADHD_MODE_ENABLED, "device_mode": COACHING_DEVICE_MODE,
                        "levels": [2, 1, 0]})


    @app.get("/api/pcbm/status")
    def lay_trang_thai_pcbm():
        return jsonify({"success": True, **dich_vu_pcbm.lay_trang_thai_dich_vu()})

    @app.post("/api/pcbm/train-sample")
    def huan_luyen_pcbm_tu_du_lieu_mau():
        try:
            return jsonify(dich_vu_pcbm.huan_luyen_mau_mo_hinh())
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.post("/api/pcbm/train-db")
    def huan_luyen_pcbm_tu_csdl():
        try:
            return jsonify(dich_vu_pcbm.huan_luyen_tu_sqlite())
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.get("/api/pcbm/recommend/current")
    def de_xuat_pcbm_hien_tai():
        cur = dich_vu_nhiem_vu.lay_nhiem_vu_hien_tai()
        if cur.get("done"):
            return jsonify({"success": False, "message": cur.get("message", "Không có task hiện tại.")}), 404
        base_level = dich_vu_huan_luyen.lay_muc_nhac(cur)
        return jsonify({"success": True, "recommendation": dich_vu_pcbm.de_xuat_muc_ho_tro(cur, base_level)})

    @app.get("/api/pcbm/events")
    def lay_su_kien_pcbm():
        return jsonify({"success": True, "events": dich_vu_pcbm.lay_su_kien_gan_day(int(request.args.get("limit", 200)))})

    @app.get("/api/pcbm/predictions")
    def lay_du_doan_pcbm():
        return jsonify({"success": True, "predictions": dich_vu_pcbm.lay_du_doan_gan_day(int(request.args.get("limit", 100)))})

    @app.get("/api/vision/status")
    def thi_giac_trang_thai():
        return jsonify(dich_vu_thi_giac.lay_trang_thai_dich_vu())

    @app.post("/api/vision/check")
    def thi_giac_kiem_tra():
        d = request.get_json(silent=True) or {}
        try:
            return jsonify(dich_vu_thi_giac.kiem_tra_vat_dung(d.get("required_items") or ["backpack", "book", "bottle"], d.get("frames")))
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.post("/api/vision/find")
    def thi_giac_tim():
        d = request.get_json(silent=True) or {}
        item = d.get("object") or d.get("item")
        if not item:
            return jsonify({"success": False, "message": "Thiếu object."}), 400
        try:
            r = dich_vu_thi_giac.tim_vat_dung(item, try_live=bool(d.get("try_live", True)))
            if r.get("success") and r.get("snapshot_id"):
                r["snapshot_url"] = f"/vision/snapshot/{r['snapshot_id']}"
            return jsonify(r)
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.get("/api/vision/sightings")
    def thi_giac_lan_nhin_thay():
        return jsonify({
            "success": True,
            "sightings": dich_vu_thi_giac.lay_cac_lan_nhin_thay_gan_day(int(request.args.get("limit", 100)))
        })

    @app.post("/api/vision/cleanup")
    def thi_giac_don_dep():
        try:
            return jsonify({"success": True, **dich_vu_thi_giac.don_dep()})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.get("/vision/snapshot/<int:sighting_id>")
    def thi_giac_anh_chup(sighting_id):
        row = dich_vu_thi_giac.lay_lan_nhin_thay(sighting_id)
        if not row or not row.get("snapshot_path"):
            abort(404)
        from pathlib import Path
        p = Path(row["snapshot_path"])
        if not p.exists():
            abort(404)
        return send_file(str(p), mimetype="image/jpeg", conditional=True)

    @app.get("/api/band/state")
    def vong_deo_trang_thai():
        return jsonify(dich_vu_vong_deo.lay_trang_thai_band())

    @app.get("/api/band/next")
    def vong_deo_tiep_theo():
        return jsonify(dich_vu_vong_deo.lay_tiep_theo())

    @app.post("/api/band/action")
    def vong_deo_hanh_dong():
        d = request.get_json(silent=True) or {}
        nid = d.get("notification_id")
        if not nid:
            return jsonify({"success": False, "message": "Thiếu notification_id."}), 400
        return jsonify(dich_vu_vong_deo.xu_ly_hanh_dong(int(nid), d.get("action")))

    @app.post("/api/band/test")
    def vong_deo_kiem_thu():
        d = request.get_json(silent=True) or {}
        n = dich_vu_vong_deo.gui(d.get("type", "TEST"), d.get("message", "Test OneBand|Nhớ / Không nhớ"))
        return jsonify({"success": True, "notification": n})

    return app
