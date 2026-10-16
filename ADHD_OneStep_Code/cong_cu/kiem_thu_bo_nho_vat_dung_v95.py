from dich_vu.co_so_du_lieu import khoi_tao_co_so_du_lieu
from dich_vu.dich_vu_bo_nho_vat_dung import DichVuBoNhoVatDung

khoi_tao_co_so_du_lieu()
m = DichVuBoNhoVatDung()
r = m.luu_lan_nhin_thay(
    "backpack", 0.91, "test:0", "left", [1,2,100,120],
    snapshot_path=None, force=True
)
assert r["object_class"] == "backpack"
last = m.lay_cuoi_da_thay("backpack")
assert last and last["id"] == r["id"]
print("OK object memory:", last["id"], last["seen_at"])
