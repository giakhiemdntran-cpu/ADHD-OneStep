"""Kiểm thử nhanh vòng huấn luyện ghi nhớ mà không cần Ollama, Qt hoặc camera."""
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cau_hinh
_tmp = tempfile.TemporaryDirectory()
cau_hinh.DB_PATH = Path(_tmp.name) / "onestep-test.db"

# Import sau khi đổi config.DB_PATH để services.db sử dụng đường dẫn tạm.
from dich_vu.co_so_du_lieu import khoi_tao_co_so_du_lieu
from dich_vu.dich_vu_nhiem_vu import DichVuNhiemVu
from dich_vu.dich_vu_huan_luyen import DichVuHuanLuyen


class AIMoPhong:
    def lap_ke_hoach_nhiem_vu(self, title):
        return [title]


khoi_tao_co_so_du_lieu()
tasks = DichVuNhiemVu()
coach = DichVuHuanLuyen(tasks, AIMoPhong())

# Tạo nhiệm vụ hằng tuần để nhiệm vụ vẫn còn trong CSDL sau khi hoàn thành.
t = tasks.them_nhiem_vu("Uống nước", ["Uống nước"], "weekly", scheduled_time="23:59",
                   repeat_days=["MON","TUE","WED","THU","FRI","SAT","SUN"],
                   created_by="test", habit_key="uong_nuoc")
coach.lay_hoac_tao_thoi_quen("uong_nuoc", "Uống nước")

# Tạo 3 lần kiểm tra mô phỏng thành công ở mức 2 để chuyển xuống mức 1.
for i in range(3):
    cur = tasks.lay_nhiem_vu_hien_tai()
    # Tạo lần thực hiện mới khi lần hiện tại đã hoàn thành; tạo lại lịch chờ khi cần.
    if cur.get("done"):
        tasks.dam_bao_lan_thuc_hien(); cur = tasks.lay_nhiem_vu_hien_tai()
    check = coach._cap_nhat_hoac_them_kiem_tra(cur, 2, "awaiting_level2", prompt_sent=True)
    coach._ghi_ghi_nho_ket_qua(check, "remembered", "not_completed", f"test-{i}")

h = coach.lay_tien_do("uong_nuoc")[0]
assert h["prompt_level"] == 1, h
assert h["memory_success_streak"] == 0, h

# Một lần quên ở mức 1 KHÔNG được tăng ngay trở lại mức 2.
cur = tasks.lay_nhiem_vu_hien_tai()
# Thay lần kiểm tra hiện có bằng lần kiểm tra mô phỏng mới sau khi xóa bản ghi cũ của lần thực hiện này.
from dich_vu.co_so_du_lieu import lay_ket_noi_csdl
with lay_ket_noi_csdl() as c:
    c.execute("DELETE FROM memory_checks WHERE occurrence_id=?", (cur["occurrence_id"],))
check = coach._cap_nhat_hoac_them_kiem_tra(cur, 1, "awaiting_level1_decision", prompt_sent=True)
coach._ghi_ghi_nho_ket_qua(check, "forgot", "not_completed", "không nhớ")
h = coach.lay_tien_do("uong_nuoc")[0]
assert h["prompt_level"] == 1, h
assert h["memory_failure_streak"] == 1, h

print("PASS v9 memory coaching smoke test")
print({k: h[k] for k in ["prompt_level","memory_success_streak","memory_failure_streak","last_memory_result"]})
