#!/usr/bin/env python3
"""BÁO CÁO KHO CUỐI NGÀY 21h (CEO giao 14/11 — mục tiêu kho tự vận hành, cắt vị trí quản lý kho).

BẢN NHÁP: chỉ in ra. Chủ shop duyệt mẫu xong mới bật gửi nhóm Kho (thêm --send + lịch launchd 21h).
  python3 tools/bao_cuoi_ngay.py [--ngay YYYY-MM-DD] [--send]
4 mục, mỗi mục 1 dòng số + danh sách việc còn treo (tối đa vài mã):
  1. Hàng hoàn: kiện đã /hoan hôm nay (theo tình trạng) · kiện sàn ghi đã về shop mà kho chưa /hoan (quá 4h).
  2. Yêu cầu trên sàn: kho đã duyệt / đã khiếu nại hôm nay · còn treo chờ shop · quá hạn.
  3. Đơn đi: cần gửi · đã bàn giao · còn chưa đi · huỷ sau in chưa giữ lại.
  4. Lệch tồn Nhanh: hàng về chưa nhập Nhanh · kiểm kho lệch chưa điều chỉnh · đơn sàn mà Nhanh thiếu.
Cuối tin: "Tiêu chí 30/11" (0 kiện quá 4h · 0 yêu cầu quá hạn · lệch tồn 0) → ✅/❌ hôm nay.
"""
import json, os, re, sys
from datetime import datetime

import orbit_tg as TG
import ticket as TK
import kho_flow as KF
import xuat_kho as XK
import hoan_san as HS

esc = TK.esc


def _ds(xs, n=8):
    xs = list(xs)
    return ", ".join(f"<code>{esc(x)}</code>" for x in xs[:n]) + (f" … +{len(xs) - n}" if len(xs) > n else "")


def muc_hoan(ngay):
    rows = TG.rows(TK.HOAN, fresh=True)
    nay = [r for r in rows if str(r.get("Ngày") or "")[:10] == ngay and r.get("Người nhận")]
    dem = {}
    for r in nay:
        k = "✅ nguyên vẹn" if "✅" in str(r.get("Tình trạng") or "✅") else re.sub(r"^\W+\s*", "", str(r.get("Tình trạng")))
        dem[k] = dem.get(k, 0) + 1
    st = HS._doc(HS.STATE)
    ve = [(v.get("mvd") or m, HS.gio_lam(HS._dt(v["lan_ve"]))) for m, v in st.items() if v.get("lan_ve")]
    tre = [m for m, h in ve if h >= HS.SLA_KHO]
    L = [f"📦 <b>Hàng hoàn</b>: đã /hoan hôm nay <b>{len(nay)}</b> kiện"
         + (" (" + ", ".join(f"{k} {v}" for k, v in dem.items()) + ")" if dem else "")
         + f" · sàn ghi đã về mà chưa /hoan <b>{len(ve)}</b>" + (f", quá {HS.SLA_KHO}h: <b>{len(tre)}</b>" if tre else "")]
    if tre:
        L.append("   ↳ tìm kiện sáng mai đầu ca: " + _ds(tre))
    return L, len(tre)


def muc_san(ngay):
    st, xl = HS._doc(HS.STATE), HS.xu_ly()
    duyet = [t for t, v in xl.items() if v.get("luc", "")[:10] == ngay and v.get("xl") == "d"]
    kn = [t for t, v in xl.items() if v.get("luc", "")[:10] == ngay and v.get("xl") == "k"]
    treo, qh = [], []
    now = datetime.now()
    for m, v in st.items():
        if v.get("nut") not in HS.CAN_XL or HS.da_xu_ly(dict(v, ma=m)):
            continue
        treo.append(m)
        if v.get("han_gio") is not None:
            con = v["han_gio"] - (now - (HS._dt(v.get("lan_cuoi")) or now)).total_seconds() / 3600
            if con <= 0:
                qh.append(m)
    luc = HS.luc_doc_san()
    L = [f"💸 <b>Yêu cầu trên sàn</b>: kho đã duyệt <b>{len(duyet)}</b> · đã khiếu nại <b>{len(kn)}</b> · còn chờ shop <b>{len(treo)}</b>"
         + (f" · quá hạn <b>{len(qh)}</b>" if qh else "") + (f" <i>(đọc sàn {esc(luc[11:])})</i>" if luc else " <i>(chưa đọc được sàn)</i>")]
    if qh:
        L.append("   ↳ quá hạn: " + _ds(qh))
    return L, len(qh)


def muc_don(ngay):
    try:
        out, _, _ = XK.tinh(ngay)
    except Exception as e:
        return [f"🚚 <b>Đơn đi</b>: chưa tính được ({esc(str(e)[:60])})"]
    can = sum(len(k["can"]) for k in out.values())
    di = sum(len(k["lay"]) + len(k["quet_chua_lay"]) for k in out.values())
    chua = [XK.ma(o) for k in out.values() for o in k["chua_di"] + k["chua_tem"]]
    huy = [XK.ma(o) for k in out.values() for o in k["huy_sau_in"] + k["huy_da_giao"]]
    L = [f"🚚 <b>Đơn đi</b>: cần gửi <b>{can}</b> · đã bàn giao <b>{di}</b> · chưa đi <b>{len(chua)}</b>"
         + (f" · huỷ sau in chưa giữ lại <b>{len(huy)}</b>" if huy else "")]
    if chua:
        L.append("   ↳ chưa đi: " + _ds(chua))
    if huy:
        L.append("   ↳ huỷ sau in: " + _ds(huy))
    return L


def muc_ton():
    nhap = [r for r in TG.rows(KF.NHAP, fresh=True)
            if not r.get("Đã nhập Nhanh.vn") and str(r.get("Ngày nhận") or "")[:10] < KF.today()
            and str(r.get("Ngày nhận") or "") >= "2026-11-01"]
    kiem = [r for r in TG.rows(KF.KIEM, fresh=True)
            if str(r.get("Lệch") or "0").strip() not in ("", "0") and not r.get("Đã điều chỉnh Nhanh")]
    thieu = XK.thieu_doc()
    n = len(nhap) + len(kiem) + len(thieu)
    L = [f"📊 <b>Lệch tồn Nhanh</b>: hàng về chưa nhập Nhanh <b>{len(nhap)}</b> · kiểm kho lệch chưa điều chỉnh <b>{len(kiem)}</b>"
         f" · đơn sàn Nhanh thiếu <b>{len(thieu)}</b>"]
    if nhap:
        L.append("   ↳ chưa nhập Nhanh: " + _ds(f"{r.get('Tên sản phẩm') or r.get('SKU') or '?'} ({str(r.get('Ngày nhận'))[5:10]})" for r in nhap))
    if kiem:
        L.append("   ↳ lệch kiểm kho: " + _ds(f"{r.get('SKU')} {r.get('Lệch')}" for r in kiem))
    return L, n


def bao(ngay=None):
    ngay = ngay or KF.today()
    h, n_tre = muc_hoan(ngay)
    s, n_qh = muc_san(ngay)
    d = muc_don(ngay)
    t, n_lech = muc_ton()
    dat = lambda ok: "✅" if ok else "❌"
    L = [f"🌙 <b>KHO CUỐI NGÀY {datetime.strptime(ngay, '%Y-%m-%d'):%d/%m}</b>", *h, *s, *d, *t,
         f"\n🎯 Tiêu chí 30/11: {dat(n_tre == 0)} 0 kiện quá 4h chưa /hoan · {dat(n_qh == 0)} 0 yêu cầu sàn quá hạn · "
         f"{dat(n_lech == 0)} lệch tồn 0"]
    return "\n".join(L)


if __name__ == "__main__":
    import lark as Lk
    TK.init(Lk.load_env(), start_worker=False)
    a = sys.argv[1:]
    t = bao(a[a.index("--ngay") + 1] if "--ngay" in a else None)
    print(re.sub(r"<[^>]+>", "", t))
    if "--send" in a and KF.kchat():
        TK.tsend(KF.kchat(), t)
