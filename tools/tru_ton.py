#!/usr/bin/env python3
"""TRỪ TỒN NHANH cho hàng không bán được (chủ shop chốt 21/11/2026) — nằm trong luồng có sẵn, không lệnh mới.

⚠️ 28/11/2026 chủ shop chốt: kiện tráo / lỗi KHÔNG nhập hoàn kho trên Nhanh (knowledge/SOP_NHANH_HOAN_DOI.md) → bình thường
   Nhanh không cộng → bot không trừ. TH1 dưới đây chỉ còn để sửa khi kho LỠ nhập hoàn kiện xấu.
TH1 · Hàng hoàn xấu (/hoan → kho chọn Không nguyên vẹn / Bị tráo / Thiếu, bảng 09):
  kho vẫn nhập trả trên Nhanh như thường (đóng đơn hoàn) → Nhanh cộng món đó lại vào tồn bán → sau mỗi lần đồng bộ
  bot thấy phiếu nhập trả của đơn đó → tạo PHIẾU XUẤT KHÁC trừ lại đúng món, đúng kho (Open API inventory/exportother).
    • 1 món + lỗi/tráo      → bot tự trừ, báo 1 dòng ở nhóm Kho
    • nhiều món / thiếu     → thẻ ở nhóm Kho: bấm món hỏng/thiếu → ✅ Trừ (hoặc Không trừ)
  Hoàn ĐVVC Nhanh tự cộng tồn khi "Đã chuyển hoàn" (không có phiếu) → trừ theo món ghi ở 09.
  Kho KHÔNG nhập trả (VD hàng tráo giữ lại khiếu nại) → Nhanh không cộng → bot không trừ.
TH2 · Hàng nhập lỗi/thiếu (/hangve): KHÔNG nhập phần đó vào Nhanh → thẻ "Gửi về xưởng" (kho_flow.py), ghi sổ 11.
Sổ chung: 11 · HÀNG KHÔNG BÁN (Nguồn, SKU, SL, kho, phiếu Nhanh) → /tonghoploi tổng hợp món nào lỗi/thiếu/tráo.
Công tắc: chỉ ghi Nhanh khi có file logs/tru_ton_bat (chủ shop duyệt). Chưa có → chỉ in bản xem trước.
  python3 tools/tru_ton.py xem          # in những gì bot SẼ trừ (không ghi gì)
  python3 tools/tru_ton.py chay --send  # sau mỗi lần đồng bộ Nhanh 30 phút (nhanh.py sau_sync)
"""
import json, os, re, sys, time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orbit_tg as TG  # noqa: E402
import ticket as TK  # noqa: E402
import nhanh as NH  # noqa: E402

esc, tsend, tedit, answer, ten = TK.esc, TK.tsend, TK.tedit, TK.answer, TK.ten
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
STATE_F = os.path.join(ROOT, "logs", "tru_ton.json")
BAT_F = os.path.join(ROOT, "logs", "tru_ton_bat")
BANG = "11 · HÀNG KHÔNG BÁN"
COLS = ["Ngày", "Giờ", "Nguồn", "SKU", "Tên", "SL", "Kho", "Mã kiện / đợt", "Phiếu Nhanh", "Người", "Ghi chú"]
KHO = {"205577": "KHO TỔNG Q2", "206425": "KHO CỬA HÀNG PN"}
TU_NGAY = "2026-11-17"   # kiện hoàn xấu từ ngày này (luồng HHV mới)
NGUON = {"⚠️": "Hoàn lỗi", "🔀": "Hoàn bị tráo", "➖": "Hoàn thiếu"}


def now():
    return datetime.now()


def bat():
    return os.path.exists(BAT_F)


def st_doc():
    try:
        return json.load(open(STATE_F))
    except Exception:
        return {}


def st_ghi(st):
    os.makedirs(os.path.dirname(STATE_F), exist_ok=True)
    json.dump(st, open(STATE_F, "w"), ensure_ascii=False, indent=1)


def nguon(r):
    return next((v for k, v in NGUON.items() if str(r.get("Tình trạng") or "").startswith(k)), "")


def sp_09(r):
    return [(a.upper(), int(b)) for a, b in re.findall(r"\(([A-Za-z0-9-]+)\)\s*x(\d+)", str(r.get("Sản phẩm") or "").split("‖")[0])]


def tim(r, nt=None, dons=None):
    """Kiện 09 → (kho, [[SKU, SL]], phiếu nhập trả | 'ĐVVC') nếu Nhanh ĐÃ cộng lại tồn, ngược lại None."""
    nt = NH.nhap_tra() if nt is None else nt
    dons = NH.orders() if dons is None else dons
    ma = str(r.get("Đơn Nhanh") or "").strip()
    o = NH.don_theo_ma(r.get("MVĐ"))
    ids = ([o["id"]] if o else []) + [k for k, v in dons.items() if ma and v.get("ma_san") in (ma, ma + "R")]
    for i in dict.fromkeys(ids):
        b = nt.get(i)
        if b and b.get("sp"):
            ten09 = {s for s, _ in sp_09(r)}
            sp = [[s, n] for s, n, *_ in b["sp"] if not ten09 or s.upper() in ten09] or [[s, n] for s, n, *_ in b["sp"]]
            return b.get("kho") or "205577", sp, b["bill"]
    o = o or next((dons[i] for i in ids if i in dons), None)
    if o and o.get("st") == 72 and sp_09(r):   # hoàn ĐVVC: Nhanh tự cộng tồn khi Đã chuyển hoàn
        return o.get("kho") or "205577", [[s, n] for s, n in sp_09(r)], "ĐVVC"
    return None


def can_tru():
    """[(row 09, nguồn, kho, sp, phiếu)] kiện xấu Nhanh đã cộng lại mà bot chưa xử lý."""
    st, nt, dons, out = st_doc(), NH.nhap_tra(), NH.orders(), []
    for r in TG.rows(TK.HOAN, fresh=True):
        n = nguon(r)
        if not n or str(r.get("Ngày") or "")[:10] < TU_NGAY or r["_id"] in st:
            continue
        x = tim(r, nt, dons)
        if x:
            out.append((r, n) + x)
    return out


def xuat_nhanh(kho, sp, ghi_chu):
    """Phiếu xuất kho khác trên Nhanh → id phiếu. sp = [[SKU, SL]]."""
    import nhanh_api as NA
    prods = []
    for s, n in sp:
        j = NA.goi("product/list", {"filters": {"name": s, "gpid": 3}, "paginator": {"size": 20}})
        pid = next((p.get("id") for p in j.get("data") or [] if str(p.get("code", "")).upper() == s.upper()), None)
        if not pid:
            raise RuntimeError(f"không thấy {s} trên Nhanh")
        prods.append({"id": int(pid), "quantity": n})
    j = NA.goi("inventory/exportother", {"depotId": int(kho), "products": prods, "description": ghi_chu[:250]})
    return str((j.get("data") or {}).get("id") or "?")


def dieu_chinh(kho, lech, ghi_chu):
    """Kiểm kho lệch chưa rõ → sửa Nhanh theo số đếm: lech = [(SKU, đếm − Nhanh)]. Âm → phiếu xuất khác, dương → nhập khác.
    → 'X…/N…' id phiếu."""
    import nhanh_api as NA
    out = []
    for loai, ds in (("exportother", [(s, -d) for s, d in lech if d < 0]), ("importother", [(s, d) for s, d in lech if d > 0])):
        if not ds:
            continue
        prods = []
        for s, n in ds:
            j = NA.goi("product/list", {"filters": {"name": s, "gpid": 3}, "paginator": {"size": 20}})
            pid = next((p.get("id") for p in j.get("data") or [] if str(p.get("code", "")).upper() == s.upper()), None)
            if not pid:
                raise RuntimeError(f"không thấy {s} trên Nhanh")
            prods.append({"id": int(pid), "quantity": int(n)})
        j = NA.goi(f"inventory/{loai}", {"depotId": int(kho), "products": prods, "description": ghi_chu[:250]})
        out.append(("xuất " if loai == "exportother" else "nhập ") + str((j.get("data") or {}).get("id") or "?"))
    return " / ".join(out)


def ghi_so(rows):
    try:
        TG.kho("setup", tables={TG.sname(BANG): COLS})
        TG.kho("add", table=TG.sname(BANG), rows=rows)
        TG._CACHE.pop(TG.sname(BANG), None)
    except BaseException as e:
        print("tru_ton: ghi sổ lỗi", e, flush=True)


def dong_so(nguon_, sku, sl, kho, ma, phieu, nguoi, gc=""):
    return {"Ngày": now().strftime("%Y-%m-%d"), "Giờ": now().strftime("%H:%M"), "Nguồn": nguon_, "SKU": sku,
            "Tên": (NH.ton_sku(sku) or {}).get("ten", ""), "SL": sl, "Kho": KHO.get(str(kho), str(kho)),
            "Mã kiện / đợt": ma, "Phiếu Nhanh": phieu, "Người": nguoi, "Ghi chú": gc}


def tru(r, n, kho, sp, phieu_tra, nguoi="Bot kho (tự trừ)"):
    """Trừ thật + ghi sổ 11 + ghi chú 09. → id phiếu xuất."""
    bill = xuat_nhanh(kho, sp, f"Bot kho · {n} · kiện {r.get('MVĐ')} · đơn {r.get('Đơn Nhanh') or ''}"
                                f" · nhập trả {phieu_tra}" + (f" · {r.get('Ticket')}" if r.get("Ticket") else ""))
    ghi_so([dong_so(n, s, q, kho, r.get("MVĐ"), bill, nguoi, f"nhập trả {phieu_tra}") for s, q in sp])
    try:
        gc = str(r.get("Ghi chú") or "")
        TG.kho("update", table=TG.sname(TK.HOAN), id=r["_id"],
               fields={"Ghi chú": (gc + " · " if gc else "") + f"Đã trừ tồn Nhanh (phiếu xuất {bill}): "
                                  + ", ".join(f"{s}×{q}" for s, q in sp)})
        TG._CACHE.pop(TG.sname(TK.HOAN), None)
    except BaseException as e:
        print("tru_ton: ghi 09 lỗi", e, flush=True)
    return bill


def the_text(x):
    L = [f"➖ <b>TRỪ TỒN HÀNG HOÀN</b> · {esc(x['nguon'])} · kiện <code>{esc(x['mvd'])}</code> · {esc(KHO.get(x['kho'], x['kho']))}",
         f"Nhanh đã cộng lại khi nhập trả ({esc(x['phieu'])}). Món nào <b>hỏng/thiếu/không phải hàng mình</b> → bấm chọn rồi ✅ Trừ."]
    for i, (s, n) in enumerate(x["sp"]):
        L.append(f"{'☑️' if i in x['chon'] else '⬜'} {esc(s)} ×{n}")
    return "\n".join(L)


def the_btn(x, key):
    b = [[{"text": f"{'☑️' if i in x['chon'] else '⬜'} {s} ×{n}", "callback_data": f"tt:c:{key}:{i}"}] for i, (s, n) in enumerate(x["sp"])]
    return b + [[{"text": "✅ Trừ món đã chọn", "callback_data": f"tt:ok:{key}:0"},
                 {"text": "Không trừ (bán lại được)", "callback_data": f"tt:ko:{key}:0"}]]


def chay(send=False):
    ds = can_tru()
    if not ds:
        return "không có kiện hoàn xấu nào cần trừ"
    st, L = st_doc(), []
    kc = TK.E.get("CHAT_ID")
    for r, n, kho, sp, phieu in ds:
        mo_ta = f"{n} · {r.get('MVĐ')} · {', '.join(f'{s}×{q}' for s, q in sp)} · {KHO.get(kho, kho)} · nhập trả {phieu}"
        tu_dong = len(sp) == 1 and n != "Hoàn thiếu"
        if not send or not bat():
            L.append(("TỰ TRỪ " if tu_dong else "HỎI KHO ") + mo_ta)
            continue
        if tu_dong:
            try:
                bill = tru(r, n, kho, sp, phieu)
            except BaseException as e:
                L.append(f"LỖI {mo_ta}: {e}")
                continue
            st[r["_id"]] = {"kq": "da_tru", "bill": bill, "luc": now().strftime("%Y-%m-%d %H:%M")}
            st_ghi(st)
            if kc:
                tsend(kc, f"➖ <b>Đã trừ tồn Nhanh</b> {esc(sp[0][0])} ×{sp[0][1]} — {esc(n.lower())}, kiện <code>{esc(r.get('MVĐ'))}</code> "
                          f"({esc(KHO.get(kho, kho))}, phiếu xuất {esc(bill)}). Món này không còn trong tồn bán.")
            L.append("ĐÃ TRỪ " + mo_ta)
        else:
            key = re.sub(r"\W", "", r["_id"])[-20:]
            x = {"rid": r["_id"], "nguon": n, "mvd": r.get("MVĐ"), "kho": kho, "sp": sp, "phieu": phieu, "chon": []}
            mid = tsend(kc, the_text(x), the_btn(x, key)) if kc else None
            st[r["_id"]] = {"kq": "cho_kho", "key": key, "x": x, "mid": mid, "luc": now().strftime("%Y-%m-%d %H:%M")}
            st_ghi(st)
            L.append("ĐÃ HỎI KHO " + mo_ta)
    return "\n".join(L)


def on_cb(cq, p):
    a, key, i = p[1], p[2], int(p[3] or 0)
    st = st_doc()
    rid = next((k for k, v in st.items() if v.get("key") == key), None)
    v = st.get(rid) if rid else None
    c, mid, who = cq["message"]["chat"]["id"], cq["message"]["message_id"], ten(cq.get("from"))
    if not v or v.get("kq") != "cho_kho":
        return answer(cq, "Thẻ này đã xử lý.", True)
    x = v["x"]
    if a == "c":
        x["chon"] = [j for j in x["chon"] if j != i] if i in x["chon"] else x["chon"] + [i]
        st_ghi(st); answer(cq)
        return tedit(c, mid, the_text(x), the_btn(x, key))
    if a == "ko":
        v["kq"] = "khong_tru"; v["ai"] = who; st_ghi(st); answer(cq, "Không trừ")
        return tedit(c, mid, the_text(x) + f"\n\n✔️ {esc(who)}: hàng bán lại được — không trừ tồn.")
    if not x["chon"]:
        return answer(cq, "Chọn món hỏng/thiếu trước (bấm vào tên món).", True)
    answer(cq, "Đang trừ tồn Nhanh…")
    sp = [x["sp"][j] for j in sorted(x["chon"])]
    r = next((r for r in TG.rows(TK.HOAN, fresh=True) if r["_id"] == x["rid"]), {"_id": x["rid"], "MVĐ": x["mvd"]})
    try:
        bill = tru(r, x["nguon"], x["kho"], sp, x["phieu"], who)
    except BaseException as e:
        return tedit(c, mid, the_text(x) + f"\n\n⚠️ Nhanh báo lỗi, <b>chưa trừ</b>: {esc(str(e)[:200])}", the_btn(x, key))
    v.update(kq="da_tru", bill=bill, ai=who); st_ghi(st)
    tedit(c, mid, the_text(x) + f"\n\n➖ <b>Đã trừ tồn Nhanh</b> {', '.join(f'{esc(s)}×{q}' for s, q in sp)} — {esc(who)}, phiếu xuất {esc(bill)}")


def tong_hop(ngay=7):
    t0 = (now() - timedelta(days=ngay)).strftime("%Y-%m-%d")
    try:
        rs = [r for r in TG.rows(BANG, fresh=True) if str(r.get("Ngày", "")) >= t0]
    except BaseException:
        rs = []
    if not rs:
        return f"📋 {ngay} ngày qua chưa có hàng hoàn xấu / hàng nhập lỗi-thiếu nào."
    L = [f"📋 <b>Hàng không bán được · {ngay} ngày</b>"]
    for ng in ("Hoàn lỗi", "Hoàn bị tráo", "Hoàn thiếu", "Nhập lỗi", "Nhập thiếu"):
        g = [r for r in rs if r.get("Nguồn") == ng]
        if not g:
            continue
        sku = {}
        for r in g:
            sku[r.get("SKU")] = sku.get(r.get("SKU"), 0) + TK.tien(r.get("SL"))
        L.append(f"• <b>{ng}</b> {int(sum(sku.values()))} cái: " + ", ".join(
            f"{esc(k)}×{int(v)}" for k, v in sorted(sku.items(), key=lambda kv: -kv[1])[:12]))
    return "\n".join(L)


def cmd_tonghop(m, arg):
    n = int(arg) if arg.strip().isdigit() else 7
    tsend(m["chat"]["id"], tong_hop(n), reply_to=m["message_id"])


TK.EXT_CB["tt"] = on_cb
TK.EXT_CMDS["/tonghoploi"] = cmd_tonghop
TK.EXT_NHOM["/tonghoploi"] = ("CHAT_ID",)

if __name__ == "__main__":
    import lark as Lk
    TK.init(Lk.load_env(), start_worker=False)
    a = sys.argv[1:] or ["help"]
    if a[0] == "xem":
        print(chay(False))
    elif a[0] == "chay":
        print(chay("--send" in a))
    elif a[0] == "tonghop":
        print(re.sub(r"<[^>]+>", "", tong_hop(int(a[1]) if len(a) > 1 else 7)))
    else:
        print(__doc__)
