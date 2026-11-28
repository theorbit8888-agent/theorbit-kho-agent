#!/usr/bin/env python3
"""KHUNG TIN CHUNG — mọi tin bot cần NGƯỜI xử lý viết cùng 1 kiểu cho dễ đọc (chủ shop chốt 28/11/2026):

    🔥 TIÊU ĐỀ NGẮN
    🧾 Mã đơn: …
    ❗ Vấn đề: … (1 câu lời thường)
    👉 Việc cần làm: 1. … 2. …
    👤 Ai làm: …   ⏰ Hạn: …

the(...) trả chuỗi HTML Telegram. ten_sku("SO-A4-RIVET-L") → "Rivet Washed Shorts size L" (bảng knowledge/SKU_NHANH.md).
Viết tin mới thì dùng the() thay vì tự nối chuỗi, để kho/CS đọc tin nào cũng thấy cùng chỗ: đơn nào, bị gì, làm gì, ai làm.
"""
import html, os, re

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SIZES = ("XXL", "2XL", "3XL", "XS", "XL", "S", "M", "L", "FREE", "F")
_TEN = {}


def esc(x):
    return html.escape(str(x if x is not None else ""), quote=False)


def _bang():
    if not _TEN:
        try:
            for line in open(os.path.join(ROOT, "knowledge", "SKU_NHANH.md"), encoding="utf-8"):
                m = re.match(r"\|\s*`([^`]+)`\s*\|\s*([^|]+)\|", line)
                if m:
                    _TEN[m[1].upper()] = m[2].strip()
        except FileNotFoundError:
            pass
    return _TEN


def _dep(ten):
    """'ORBIT RIVET WASHED SHORTS' → 'Rivet Washed Shorts' (bỏ chữ ORBIT, viết hoa chữ đầu). Tên có dấu giữ nguyên."""
    if ten.isupper():
        ten = " ".join(w.capitalize() for w in ten.split() if w not in ("ORBIT", "THE"))
    return ten


def ten_sku(sku):
    """Mã SKU → tên dễ đọc kèm size; không có trong bảng → trả nguyên mã."""
    s = re.sub(r"\s+", "", str(sku or "")).upper()
    if not s:
        return ""
    mau, _, size = s.rpartition("-")
    if mau and size in SIZES and mau in _bang():
        return f"{_dep(_bang()[mau])} size {size}"
    if s in _bang():
        return _dep(_bang()[s])
    return s


def doi(cu, moi):
    """('SO-A4-RIVET-L', 'SO-A4-RIVET-M') → 'Rivet Washed Shorts size L → M'."""
    a, b = ten_sku(cu), ten_sku(moi)
    if not cu:
        return b
    pa, pb = a.rpartition(" size "), b.rpartition(" size ")
    if pa[1] and pb[1] and pa[0] == pb[0]:
        return f"{pa[0]} size {pa[2]} → {pb[2]}"
    return f"{a} → {b}"


def the(tieu_de, ma=None, van_de=None, viec=None, ai=None, han=None, icon="📌", them=None):
    """Tin theo khung chung. viec: chuỗi hoặc list các bước (tự đánh số). them: dòng phụ (list/chuỗi) thêm cuối.
    Mọi giá trị là CHỮ THƯỜNG (chưa escape); chỉ `them` được phép chứa HTML có sẵn."""
    L = [f"{icon} <b>{esc(tieu_de).upper()}</b>"]
    if ma:
        L.append(f"🧾 <b>Mã đơn:</b> {esc(ma)}")
    if van_de:
        L.append(f"❗ <b>Vấn đề:</b> {esc(van_de)}")
    if viec:
        if isinstance(viec, (list, tuple)) and len(viec) > 1:
            L.append("👉 <b>Việc cần làm:</b>")
            L.extend(f"   {i}. {esc(v)}" for i, v in enumerate(viec, 1))
        else:
            L.append(f"👉 <b>Việc cần làm:</b> {esc(viec[0] if isinstance(viec, (list, tuple)) else viec)}")
    cuoi = []
    if ai:
        cuoi.append(f"👤 <b>Ai làm:</b> {esc(ai)}")
    if han:
        cuoi.append(f"⏰ <b>Hạn:</b> {esc(han)}")
    if cuoi:
        L.append("   ".join(cuoi))
    if them:
        L.extend(them if isinstance(them, (list, tuple)) else [them])
    return "\n".join(L)


def gio_txt(phut):
    phut = int(phut)
    if phut < 60:
        return f"{phut} phút"
    if phut < 48 * 60:
        return f"{phut // 60} giờ" + (f" {phut % 60} phút" if phut % 60 and phut < 600 else "")
    return f"{phut // 1440} ngày"
