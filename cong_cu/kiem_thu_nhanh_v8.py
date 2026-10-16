from dich_vu.co_so_du_lieu import khoi_tao_co_so_du_lieu
from dich_vu.dich_vu_nhiem_vu import DichVuNhiemVu
from dich_vu.dich_vu_ai import DichVuAI
from dich_vu.dich_vu_huan_luyen import DichVuHuanLuyen,thoi_quen_khoa_tu_tieu_de

khoi_tao_co_so_du_lieu(); t=DichVuNhiemVu(); ai=DichVuAI(); c=DichVuHuanLuyen(t,ai)
print("DB OK")
print("Current:",t.lay_nhiem_vu_hien_tai())
print("Habits:",c.lay_tien_do())
print("habit_key:",thoi_quen_khoa_tu_tieu_de("Chuẩn bị đi học"))
