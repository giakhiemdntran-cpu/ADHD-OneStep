#!/usr/bin/env python3
"""Kiểm tra các lệnh Qt signal.connect(...) trỏ tới hàm xử lý có tồn tại.

Công cụ chỉ phân tích mã nguồn (AST), không cần khởi động giao diện PySide6.
Mục tiêu là phát hiện lỗi refactor kiểu:
    signal.connect(self.ten_ham_cu)
trong khi class chỉ còn hàm mới với tên tiếng Việt.
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys

GOC_DU_AN = Path(__file__).resolve().parents[1]


def lay_ten_thanh_vien_self(bieu_thuc: ast.AST) -> str | None:
    if (
        isinstance(bieu_thuc, ast.Attribute)
        and isinstance(bieu_thuc.value, ast.Name)
        and bieu_thuc.value.id == "self"
    ):
        return bieu_thuc.attr
    return None


def kiem_tra_tap_tin(duong_dan: Path) -> list[dict]:
    cay = ast.parse(duong_dan.read_text(encoding="utf-8"), filename=str(duong_dan))
    ket_qua: list[dict] = []

    for lop in [n for n in ast.walk(cay) if isinstance(n, ast.ClassDef)]:
        ten_ham = {
            n.name
            for n in lop.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        ten_thanh_vien = set()
        for n in lop.body:
            if isinstance(n, ast.Assign):
                for dich in n.targets:
                    if isinstance(dich, ast.Name):
                        ten_thanh_vien.add(dich.id)
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                ten_thanh_vien.add(n.target.id)

        for nut in ast.walk(lop):
            if not (
                isinstance(nut, ast.Call)
                and isinstance(nut.func, ast.Attribute)
                and nut.func.attr == "connect"
            ):
                continue

            doi_so = nut.args[0] if nut.args else None
            ten_xu_ly = lay_ten_thanh_vien_self(doi_so) if doi_so else None
            hop_le = True
            ly_do = ""

            if ten_xu_ly:
                hop_le = ten_xu_ly in ten_ham or ten_xu_ly in ten_thanh_vien
                if not hop_le:
                    ly_do = f"Không tìm thấy self.{ten_xu_ly} trong class {lop.name}"

            ket_qua.append(
                {
                    "tep": str(duong_dan.relative_to(GOC_DU_AN)),
                    "lop": lop.name,
                    "dong": nut.lineno,
                    "signal": ast.unparse(nut.func.value),
                    "ham_xu_ly": ast.unparse(doi_so) if doi_so else "<không có>",
                    "hop_le": hop_le,
                    "ly_do": ly_do,
                }
            )

    return ket_qua


def main() -> int:
    tat_ca = []
    loi_phan_tich = []

    for tep in sorted(GOC_DU_AN.rglob("*.py")):
        if "__pycache__" in tep.parts:
            continue
        try:
            tat_ca.extend(kiem_tra_tap_tin(tep))
        except SyntaxError as exc:
            loi_phan_tich.append((tep, exc))

    print("=== KIỂM TRA SIGNAL.CONNECT ===")
    for muc in tat_ca:
        trang_thai = "OK" if muc["hop_le"] else "LỖI"
        print(
            f'[{trang_thai}] {muc["tep"]}:{muc["dong"]} | '
            f'{muc["signal"]}.connect({muc["ham_xu_ly"]})'
        )
        if muc["ly_do"]:
            print("      ", muc["ly_do"])

    if loi_phan_tich:
        print("\nLỗi cú pháp khi phân tích:")
        for tep, exc in loi_phan_tich:
            print(f"- {tep}: {exc}")

    so_loi = sum(not m["hop_le"] for m in tat_ca) + len(loi_phan_tich)
    print(f"\nTổng số connect: {len(tat_ca)}")
    print(f"Số lỗi: {so_loi}")

    return 1 if so_loi else 0


if __name__ == "__main__":
    raise SystemExit(main())
