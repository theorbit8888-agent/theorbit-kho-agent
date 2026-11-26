#!/usr/bin/env python3
"""ĐƠN ĐANG CHỜ ĐỔI / GHI CHÚ → chưa được gói, chưa được giao (chống gửi nhầm size → lệch kho + ticket kẹt).

Gom 3 nguồn "đơn này kho phải làm gì đó TRƯỚC khi gói":
  • ticket DHT "Đổi trước khi giao" đang "Chờ kho đổi trong đơn"            (ticket.py)
  • thẻ việc /note đang "Chờ làm"                                           (cua_hang.py, bảng CH · VIỆC)
  • thẻ /hoatoc có đổi size đang "Chờ đổi size"                             (cua_hang.py)
Dùng ở: /indon (liệt kê riêng, xử lý trước khi gói), /giao (quét trúng → GIỮ LẠI như đơn huỷ).

Đối chiếu Nhanh (CHỈ ĐỌC cache logs/nhanh/orders.json, không sửa đơn):
  kiem_doi(ma, sku_cu, sku_moi) → ("ok" | "sai" | "chua_ro", câu giải thích)
  Dùng khi kho bấm "Đã đổi trong đơn" (ticket DHT / hoả tốc đổi size): Nhanh vẫn còn SKU cũ, chưa có SKU mới → "sai".
  Thao tác sửa đơn trên Nhanh.vn do kho làm tay (chưa có SOP từng bước — chủ shop sẽ hướng dẫn sau).
"""
import os, re, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticket as TK  # noqa: E402
import nhanh as NH  # noqa: E402

DHT_CHO = "Chờ kho đổi trong đơn"
HT_DOI = "Hoả tốc · đổi size"   # cua_hang.py: /hoatoc có chữ "đổi" → thẻ khoá bước, trạng thái đầu "Chờ đổi size"


def viec_giu(r):
    """Thẻ việc nào chặn gói/giao: /note chưa làm, hoả tốc đổi size chưa đổi (hoả tốc thường thì không chặn)."""
    st, loai = r.get("Trạng thái"), r.get("Loại")
    return (loai == "Note kho" and st == "Chờ làm") or st == "Chờ đổi size"


def _khoa(ma):
    """Mọi mã nhận ra cùng 1 đơn: mã gõ vào + (nếu Nhanh có) ID Nhanh, mã sàn, MVĐ."""
    k = {NH.chuan_ma(ma)} if ma else set()
    o = NH.don_theo_ma(ma) if ma else None
    if o:
        k |= {str(o.get(c) or "").lower() for c in ("id", "ma_san", "mvd")}
    return {x for x in k if x}


def _viec_rows():
    try:
        import cua_hang as CH
        return CH.rows(CH.VIEC)
    except Exception as e:
        print("giu_don: không đọc được CH · VIỆC", e, flush=True)
        return []


def dang_cho():
    """{mã (chữ thường): [lý do, …]} cho mọi đơn kho còn phải xử lý trước khi gói/giao."""
    out = {}

    def them(ma, ly_do):
        for k in _khoa(ma):
            out.setdefault(k, [])
            if ly_do not in out[k]:
                out[k].append(ly_do)

    for r in TK.all_rows():
        if r.get("Trạng thái") == DHT_CHO and r.get("Mã đơn"):
            sku = str(r.get("SKU khách đang cầm") or "")
            if r.get("SKU đổi sang"):
                sku += f" → {r.get('SKU đổi sang')}"
            them(r["Mã đơn"], f"{r.get('ID')} đổi trước giao {sku}".strip())
    for r in _viec_rows():
        if viec_giu(r) and r.get("Mã đơn"):
            them(r["Mã đơn"], f"{r.get('ID')} {r.get('Loại')}: {str(r.get('Nội dung') or '')[:60]}".strip())
    return out


def ly_do_giu(o, cho=None):
    """Lý do phải giữ đơn Nhanh `o` lại (rỗng = không có gì chờ)."""
    cho = dang_cho() if cho is None else cho
    ly = []
    for c in ("id", "ma_san", "mvd"):
        for x in cho.get(str(o.get(c) or "").lower(), []):
            if x not in ly:
                ly.append(x)
    return ly


def ly_do_giu_ma(ma, cho=None):
    """Như ly_do_giu nhưng theo mã gõ/quét (đơn chưa có trong cache Nhanh vẫn bắt được)."""
    cho = dang_cho() if cho is None else cho
    ly = []
    for k in _khoa(ma):
        for x in cho.get(k, []):
            if x not in ly:
                ly.append(x)
    return ly


def _sku(x):
    return re.sub(r"\s+", "", str(x or "")).upper()


def kiem_doi(ma, sku_cu, sku_moi, moi_phut=240):
    """Đơn `ma` trên Nhanh đã đổi từ sku_cu sang sku_moi chưa (đọc cache). Không đủ dữ liệu → "chua_ro"."""
    cu, moi = _sku(sku_cu), _sku(sku_moi)
    if not ma or not moi:
        return "chua_ro", "ticket thiếu mã đơn / SKU đổi sang"
    if not NH.con_moi(moi_phut):
        return "chua_ro", "dữ liệu Nhanh cũ (chưa đồng bộ gần đây)"
    o = NH.don_theo_ma(ma)
    if not o:
        return "chua_ro", "Nhanh chưa thấy đơn này"
    co = {_sku(p.get("ma")) for p in o.get("sp") or []}
    ds = ", ".join(sorted(co)) or "(trống)"
    if moi in co and (not cu or cu not in co or cu == moi):
        return "ok", f"Nhanh đã đúng: {ds}"
    lenh = (datetime.now() - datetime.strptime(NH.meta()["dong_bo"], "%Y-%m-%d %H:%M")).total_seconds() // 60 \
        if NH.meta().get("dong_bo") else None
    luc = f" (Nhanh đồng bộ {int(lenh)} phút trước)" if lenh is not None else ""
    if moi not in co:
        return "sai", f"Nhanh vẫn ghi {ds}, chưa có {moi}{luc}"
    return "sai", f"Nhanh có {moi} nhưng vẫn còn {cu}: {ds}{luc}"
