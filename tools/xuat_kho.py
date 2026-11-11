#!/usr/bin/env python3
"""Đối soát IN ĐƠN → BÀN GIAO theo TỪNG MÃ VẬN ĐƠN (nhóm Kho, không qua Claude).

Nguồn: đơn Nhanh.vn (cache logs/nhanh/, đồng bộ 30 phút/lần) + kiện kho quét lúc bàn giao shipper.
  /indon            chốt danh sách cần gửi hôm nay (đơn chờ gửi trên Nhanh) → số tem phải in, đơn chưa có MVĐ, đơn tồn >24h
  /giao + ảnh tem   lúc giao shipper: chụp tem (nhiều tem 1 ảnh / album), hoặc gõ /giao MVĐ MVĐ… → ghi đã giao,
                    đơn đã HUỶ thì báo giữ kiện lại ngay
  /doisoat [qua]    đối soát ngay: cần gửi ↔ kho quét giao ↔ Nhanh/sàn ghi nhận ĐVVC lấy; tự chạy 17h, 18h, 9h hôm sau
Kết quả ghi bảng 07 · ĐỐI SOÁT NGÀY (mỗi sàn 1 dòng), danh sách lệch kèm MVĐ.
"""
import json, os, re
from datetime import datetime, timedelta

import orbit_tg as TG
import ticket as TK
import nhanh as NH
import kho_flow as KF

esc, tsend, tedit, answer, ten = TK.esc, TK.tsend, TK.tedit, TK.answer, TK.ten
STATE = os.path.join(KF.ROOT, "logs", "xuat_kho.json")
HUY_ST = {58, 63, 64, 68}                 # Hãng VC huỷ, Khách huỷ, Hệ thống huỷ, Hết hàng
CHO_ST = set(NH.CHUA_GUI_ST) | {43, 55}   # + Đã đóng gói, Đang xác nhận: vẫn nằm ở kho
SAN_KENH = {"tiktok": "TikTok", "shopee": "Shopee", "ngoai": "Web/Meta"}
BOT = "Bot đối soát"


def st():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def luu(s):
    giu = sorted(s)[-10:]
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({k: s[k] for k in giu}, open(STATE, "w"), ensure_ascii=False, indent=1)


def ngay_st(s, ngay):
    return s.setdefault(ngay, {"ds": {}, "giao": {}, "rut": {}})


def la_huy(o):
    t = str(o.get("st_ten", "")).lower()
    return o.get("st") in HUY_ST or "hủy" in t or "huỷ" in t


def la_cho(o):
    return o.get("st") in CHO_ST and not la_huy(o)


def _d(s):
    return str(s or "")[:10]


def da_lay_ngay(o, ngay):
    """Nhanh/sàn ghi nhận ĐVVC đã lấy kiện vào ngày `ngay` (như NH.chot_ca)."""
    return _d(o.get("gui_dvvc")) == ngay or (o.get("st") == 59 and _d(o.get("cap_nhat")) == ngay)


def ma(o):
    return o.get("mvd") or o.get("ma_san") or o.get("id")


def chup(s=None, ngay=None):
    """Thêm các đơn đang chờ gửi trên Nhanh vào danh sách cần gửi của ngày (gọi nhiều lần trong ngày được)."""
    s = s if s is not None else st()
    d = ngay_st(s, ngay or KF.today())
    for o in NH.orders().values():
        if la_cho(o) and o["id"] not in d["ds"]:
            d["ds"][o["id"]] = {"luc": datetime.now().strftime("%H:%M")}
    return s


def tinh(ngay):
    """Đối soát 1 ngày → {kenh: {...danh sách đơn...}}."""
    s = st()
    d = ngay_st(s, ngay)
    od = NH.orders()
    giao = d["giao"]
    for g in giao.values():   # mã quét lúc Nhanh chưa đồng bộ đơn → tìm lại
        if not g.get("id") and (o := NH.don_theo_ma(g["ma"])):
            g["id"], g["kenh"] = o["id"], o["kenh"]
    giao_id = {g.get("id") for g in giao.values() if g.get("id")}
    out = {}
    for oid, o in od.items():
        trong_ds = oid in d["ds"]
        quet = oid in giao_id
        lay = da_lay_ngay(o, ngay)
        cho = la_cho(o) and (trong_ds or ngay == KF.today())
        if not (trong_ds or quet or lay or cho):
            continue
        k = out.setdefault(o["kenh"], {"can": [], "quet": [], "lay": [], "chua_di": [], "chua_tem": [],
                                       "quet_chua_lay": [], "huy_sau_in": [], "huy_da_giao": [], "lay_khong_quet": []})
        huy = la_huy(o)
        if huy:
            if oid in {r.get("id") for r in d["rut"].values()}:
                pass   # kho đã bấm "Đã rút lại"
            elif quet:
                k["huy_da_giao"].append(o)
            elif trong_ds and not quet:
                k["huy_sau_in"].append(o)
            continue
        k["can"].append(o)
        if quet:
            k["quet"].append(o)
        if lay or not la_cho(o):
            k["lay"].append(o)
            if giao and not quet:
                k["lay_khong_quet"].append(o)
        elif quet:
            k["quet_chua_lay"].append(o)
        elif not o.get("mvd"):
            k["chua_tem"].append(o)
        else:
            k["chua_di"].append(o)
    la = [g for g in giao.values() if not g.get("id")]
    return out, la, d


def ds_ma(xs, n=15):
    return ", ".join(f"<code>{esc(ma(o))}</code>" for o in xs[:n]) + (f" … (+{len(xs) - n})" if len(xs) > n else "")


def bao_cao(ngay=None, ghi=True):
    """Text đối soát + số việc lệch; ghi bảng 07."""
    ngay = ngay or KF.today()
    if not NH.meta():
        return "", 0
    if ngay == KF.today():
        luu(chup())
    out, la, d = tinh(ngay)
    cu = NH.meta().get("dong_bo", "")
    L = [f"🚚 <b>ĐỐI SOÁT IN ĐƠN → BÀN GIAO</b> {ngay[8:10]}/{ngay[5:7]} (Nhanh cập nhật {esc(cu[11:] or cu)})"]
    lech = 0
    co_quet = bool(d["giao"])
    for k in ("tiktok", "shopee", "ngoai"):
        x = out.get(k)
        if not x or not (x["can"] or x["huy_da_giao"] or x["huy_sau_in"]):
            continue
        san = SAN_KENH[k]
        bad = len(x["chua_di"]) + len(x["chua_tem"]) + len(x["quet_chua_lay"]) + len(x["huy_da_giao"]) + len(x["huy_sau_in"])
        lech += bad
        L.append(f"\n{'✅' if not bad else '⚠️'} <b>{san}</b>: cần gửi <b>{len(x['can'])}</b>"
                 + (f" · kho quét giao <b>{len(x['quet'])}</b>" if co_quet else "")
                 + f" · sàn ghi nhận ĐVVC lấy <b>{len(x['lay'])}</b>")
        if x["huy_da_giao"]:
            L.append(f"   🚨 <b>{len(x['huy_da_giao'])} đơn ĐÃ HUỶ mà kho đã giao</b> → gọi shipper lấy lại: {ds_ma(x['huy_da_giao'])}")
        if x["huy_sau_in"]:
            L.append(f"   ⛔ {len(x['huy_sau_in'])} đơn huỷ sau khi in → rút kiện/tem khỏi khay, trả hàng lên kệ: "
                     f"{ds_ma(x['huy_sau_in'])}")
        if x["quet_chua_lay"]:
            L.append(f"   📣 {len(x['quet_chua_lay'])} kiện kho đã giao mà sàn chưa ghi nhận lấy → shipper chưa quét, "
                     f"đối chiếu biên bản: {ds_ma(x['quet_chua_lay'])}")
        if x["chua_di"]:
            L.append(f"   📦 <b>{len(x['chua_di'])} đơn chưa đi</b> (còn ở kho?): {ds_ma(x['chua_di'])}")
        if x["chua_tem"]:
            L.append(f"   🏷 {len(x['chua_tem'])} đơn chưa có MVĐ (chưa in được tem): {ds_ma(x['chua_tem'])}")
        if co_quet and x["lay_khong_quet"]:
            L.append(f"   ℹ️ {len(x['lay_khong_quet'])} kiện sàn ghi đã lấy mà kho không quét (quét sót?)")
        if ghi:
            ghi_07(ngay, san, x, co_quet)
    if la:
        L.append(f"\n❓ {len(la)} mã kho quét không thấy trên Nhanh: "
                 + ", ".join(f"<code>{esc(g['ma'])}</code>" for g in la[:10]))
    if len(L) == 1:
        L.append("Không có đơn cần gửi.")
    elif not lech:
        L.append("\n🟢 Khớp hết.")
    elif not co_quet:
        L.append("\n💡 Lúc giao shipper chụp tem với chú thích <code>/giao</code> → bot so được từng kiện.")
    TG._CACHE.pop(TG.sname(KF.DS), None)
    return "\n".join(L), lech


def ghi_07(ngay, san, x, co_quet):
    key = f"{ngay} - {san}"
    note = []
    for nhan, kk in (("chưa đi", "chua_di"), ("chưa có tem", "chua_tem"), ("giao mà sàn chưa ghi lấy", "quet_chua_lay"),
                     ("huỷ sau in", "huy_sau_in"), ("HUỶ đã giao", "huy_da_giao")):
        if x[kk]:
            note.append(f"{len(x[kk])} {nhan}: " + " ".join(ma(o) for o in x[kk][:20]))
    ghi = "; ".join(note) or "khớp"
    giao = len(x["quet"]) if co_quet else len(x["lay"])
    old = [r for r in TG.rows(KF.DS, fresh=True) if r.get("Ngày - Sàn") == key]
    if old and old[0].get("Người làm") not in ("", None, BOT):   # kho đã /chotdi: giữ số kho, thêm phần bot
        cu = str(old[0].get("Lệch/ghi chú", "")).split(" | bot:")[0]
        return TG.kho("update", table=TG.sname(KF.DS), id=old[0]["_id"], fields={"Lệch/ghi chú": f"{cu} | bot: {ghi}"})
    f = {"Ngày - Sàn": key, "Ngày": ngay, "Sàn": san, "Đơn cần gửi": len(x["can"]), "Đã bàn giao ĐVVC": giao,
         "Lệch/ghi chú": ghi, "Người làm": BOT}
    if old:
        TG.kho("update", table=TG.sname(KF.DS), id=old[0]["_id"], fields=f)
    else:
        TG.kho("add", table=TG.sname(KF.DS), rows=[f])


def nut(lech):
    return [[{"text": "🔍 Đã xử lý đơn lệch (gõ ghi chú)", "callback_data": f"kf:lechdi:{KF.today()}"}]] if lech else None


# ======================= lệnh =======================

def can_nhanh(m):
    if not NH.meta():
        tsend(m["chat"]["id"], "Chưa đọc Nhanh lần nào → chủ shop nhắn <b>/dangnhapnhanh</b> cho bot (ngồi máy Mac). "
                               "Trong lúc chờ, chốt tay bằng /chotdi.", reply_to=m["message_id"])
        return False
    return True


def cu_qua():
    return "" if NH.con_moi(90) else f"\n⚠️ Dữ liệu Nhanh cũ (cập nhật {esc(NH.meta().get('dong_bo', '?'))}) — số có thể trễ."


def indon(m, arg):
    if not can_nhanh(m):
        return
    s = chup()
    luu(s)
    hn = KF.today()
    ds = [o for o in NH.orders().values() if la_cho(o)]
    L = [f"🖨 <b>IN ĐƠN</b> {datetime.now():%H:%M %d/%m} — đơn chờ gửi trên Nhanh:"]
    moc = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
    for k in ("tiktok", "shopee", "ngoai"):
        xs = [o for o in ds if o["kenh"] == k]
        if not xs:
            continue
        tem = [o for o in xs if o.get("mvd")]
        cu = [o for o in xs if o.get("tao") and str(o["tao"])[:16] < moc]
        L.append(f"• <b>{SAN_KENH[k]}</b>: {len(xs)} đơn → in <b>{len(tem)}</b> tem"
                 + (f" · 🏷 {len(xs) - len(tem)} chưa có MVĐ (chưa sắp xếp vận chuyển trên sàn)" if len(tem) < len(xs) else "")
                 + (f"\n   ⏰ <b>{len(cu)} đơn tạo quá 24h</b> — giao trước kẻo quá hạn: {ds_ma(cu, 10)}" if cu else ""))
    if len(L) == 1:
        L.append("Không có đơn chờ gửi 🎉")
    L.append(f"\nTổng cần gửi hôm nay: <b>{sum(1 for o in NH.orders().values() if o['id'] in s[hn]['ds'] and not la_huy(o))}</b>. "
             "Giao shipper xong: <b>chụp tem</b> (nhiều tem 1 ảnh được), chú thích <code>/giao</code>.")
    tsend(m["chat"]["id"], "\n".join(L) + cu_qua(), reply_to=m["message_id"])


def giao(m, arg):
    chat, who = m["chat"]["id"], ten(m.get("from"))
    mas = []
    for x in TK.ma_list(arg):
        if x.lower() not in {y.lower() for y in mas}:
            mas.append(x)
    if not mas:
        return tsend(chat, "📷 Lúc bàn giao shipper: <b>chụp tem vận đơn</b> (xếp 10–15 kiện chụp 1 ảnh, hoặc gửi album), "
                           "chú thích <code>/giao</code>. Hoặc gõ <code>/giao MVĐ MVĐ …</code>.\n"
                           "Máy bắn mã vạch: đặt hậu tố là dấu cách (không Enter), gõ <code>/giao </code> rồi bắn liên tục, "
                           "xong mới Enter.", reply_to=m["message_id"])
    s = chup() if NH.meta() else st()
    d = ngay_st(s, KF.today())
    moi, trung, huy, la, cu = [], [], [], [], []
    for x in mas:
        if x.lower() in d["giao"]:
            trung.append(x); continue
        o = NH.don_theo_ma(x) if NH.meta() else None
        d["giao"][x.lower()] = {"ma": x, "id": o["id"] if o else "", "kenh": o["kenh"] if o else "", "who": who,
                                "luc": datetime.now().strftime("%H:%M")}
        if not o:
            la.append(x)
        elif la_huy(o):
            huy.append((x, o))
        else:
            moi.append(o)
            if not la_cho(o) and _d(o.get("gui_dvvc") or o.get("cap_nhat")) < KF.today():
                cu.append(o)
    luu(s)
    dem = {}
    for o in moi:
        dem[SAN_KENH.get(o["kenh"], o["kenh"])] = dem.get(SAN_KENH.get(o["kenh"], o["kenh"]), 0) + 1
    L = [f"🚚 {esc(who)} giao <b>{len(moi) + len(la)}</b> kiện" + (" (" + " · ".join(f"{k} {v}" for k, v in dem.items()) + ")" if dem else "")]
    btn = None
    if huy:
        L.append("🚨 <b>ĐƠN ĐÃ HUỶ — GIỮ LẠI, KHÔNG GIAO:</b> " + ", ".join(
            f"<code>{esc(x)}</code> ({esc(o['st_ten'])})" for x, o in huy))
        btn = [[{"text": f"↩️ Đã rút lại {x[-8:]}", "callback_data": f"xk:rut:{x[:40]}"}] for x, _ in huy[:5]]
    if trung:
        L.append("♻️ Quét rồi, bỏ qua: " + ", ".join(f"<code>{esc(x)}</code>" for x in trung))
    if la:
        L.append("❓ Không thấy trên Nhanh (đơn mới chưa đồng bộ / gõ sai?): " + ", ".join(f"<code>{esc(x)}</code>" for x in la))
    if cu:
        L.append("ℹ️ Nhanh ghi đã đi từ trước: " + ds_ma(cu, 8) + " — kiện giao 2 lần?")
    if NH.meta():
        out, _, _ = tinh(KF.today())
        con = sum(len(x["chua_di"]) + len(x["chua_tem"]) for x in out.values())
        tong = sum(len(x["can"]) for x in out.values())
        da = sum(len(x["quet"]) for x in out.values())
        L.append(f"Hôm nay: đã quét giao <b>{da}/{tong}</b>" + (f" · còn <b>{con}</b> đơn chưa đi" if con else " ✅ đủ"))
    tsend(chat, "\n".join(L), btn, reply_to=m["message_id"])


def doisoat(m, arg):
    if not can_nhanh(m):
        return
    a = arg.strip().lower()
    ngay = KF.today()
    if a in ("qua", "hôm qua", "hom qua"):
        ngay = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    elif re.fullmatch(r"\d{1,2}/\d{1,2}", a):
        dd, mm = a.split("/")
        ngay = f"{datetime.now().year}-{int(mm):02d}-{int(dd):02d}"
    t, lech = bao_cao(ngay)
    tsend(m["chat"]["id"], t + cu_qua(), nut(lech), reply_to=m["message_id"])


def on_cb(cq, p):
    u = cq["from"]
    if not TK.is_member(u["id"]):
        return answer(cq, "Bạn chưa ở nhóm kho", True)
    answer(cq)
    if p[1] == "rut":
        x = ":".join(p[2:])
        s = st()
        for dd in s.values():
            g = dd.get("giao", {}).pop(x.lower(), None)
            if g:
                dd.setdefault("rut", {})[x.lower()] = dict(g, rut=ten(u))
        luu(s)
        c = cq["message"]
        btn = [r for r in (c.get("reply_markup") or {}).get("inline_keyboard", []) if r[0].get("callback_data") != ":".join(p)]
        return tedit(c["chat"]["id"], c["message_id"], esc(c.get("text", "")) + f"\n↩️ {esc(ten(u))} đã rút lại {esc(x)}",
                     btn or None)


# ======================= lịch (gọi từ kho_flow.hen) =======================

def bao_chieu():
    """17h/18h: đối soát hôm nay."""
    if not NH.con_moi(180):
        return "", 0
    return bao_cao()


def bao_sang():
    """9h: chốt danh sách hôm nay + việc còn treo của hôm qua."""
    if not NH.con_moi(180):
        return ""
    luu(chup())
    qua = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    out, la, d = tinh(qua)
    L = []
    for k, x in out.items():
        bad = x["quet_chua_lay"] + x["huy_da_giao"]
        if bad or x["chua_di"]:
            L.append(f"• <b>{SAN_KENH.get(k, k)}</b>"
                     + (f": 🚨 {len(x['quet_chua_lay'])} kiện giao hôm qua mà sàn vẫn chưa ghi lấy → khiếu nại ĐVVC/"
                        f"đòi shipper: {ds_ma(x['quet_chua_lay'])}" if x["quet_chua_lay"] else "")
                     + (f"\n   🚨 {len(x['huy_da_giao'])} đơn huỷ đã giao: {ds_ma(x['huy_da_giao'])}" if x["huy_da_giao"] else "")
                     + (f"\n   📦 {len(x['chua_di'])} đơn hôm qua chưa đi → ưu tiên giao sáng nay: {ds_ma(x['chua_di'])}"
                        if x["chua_di"] else ""))
    ghi_qua = bool(L)
    if ghi_qua:
        bao_cao(qua)  # cập nhật dòng 07 hôm qua với trạng thái mới nhất
    n = len([1 for o in NH.orders().values() if la_cho(o)])
    t = f"🖨 <b>Hôm nay cần gửi {n} đơn</b> — gõ /indon xem chi tiết (tem cần in, đơn sắp quá hạn)."
    if L:
        t = "🚚 <b>Còn treo từ hôm qua</b>:\n" + "\n".join(L) + "\n\n" + t
    return t


TK.EXT_CMDS.update({"/indon": indon, "/giao": giao, "/doisoat": doisoat})
TK.EXT_NHOM.update({k: ("CHAT_ID",) for k in ("/indon", "/giao", "/doisoat")})
TK.EXT_CB["xk"] = on_cb

if __name__ == "__main__":
    import lark as Lk
    TK.init(Lk.load_env(), start_worker=False)
    import sys
    a = sys.argv[1:]
    if a and a[0] == "doisoat":   # python3 tools/xuat_kho.py doisoat [YYYY-MM-DD]
        print(re.sub(r"<[^>]+>", "", bao_cao(a[1] if len(a) > 1 else None, ghi=False)[0]))
    else:
        print(__doc__)
