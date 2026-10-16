import threading

_lock = threading.Lock()
_dich_vu_thi_giac = None


def lay_dich_vu_thi_giac():
    """Dùng chung một dịch vụ thị giác trong mỗi tiến trình để tránh nạp mô hình nhiều lần."""
    global _dich_vu_thi_giac
    if _dich_vu_thi_giac is None:
        with _lock:
            if _dich_vu_thi_giac is None:
                from dich_vu.dich_vu_thi_giac import DichVuThiGiac
                _dich_vu_thi_giac = DichVuThiGiac()
    return _dich_vu_thi_giac
