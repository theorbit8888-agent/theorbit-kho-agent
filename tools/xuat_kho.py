#!/usr/bin/env python3
"""Đối soát IN ĐƠN → BÀN GIAO theo TỪNG MÃ VẬN ĐƠN (nhóm Kho, không qua Claude).

Nguồn: đơn Nhanh.vn (cache logs/nhanh/, đồng bộ 30 phút/lần) + kiện kho quét lúc bàn giao shipper.
  /indon            chốt danh sách cần gửi hôm nay (đơn chờ gửi trên Nhanh) → số tem phải in, đơn chưa có MVĐ, đơn tồn >24h
  /giao + ảnh tem   lúc giao shipper: chụp tem (nhiều tem 1 ảnh / album), hoặc gõ /giao MVĐ MVĐ… → ghi đã giao,
                    đơn đã HUỶ thì báo giữ kiện lại ngay
  /giulai + ảnh tem  đơn HUỶ SAU KHI IN (đã có MVĐ rồi mới huỷ): kho rút kiện ra, chụp/quét tem xác nhận đã giữ.
                    Bot báo ngay khi Nhanh thấy đơn huỷ (sau mỗi lần đồng bộ) + 9h/17h nhắc kiện chưa xác nhận;
                    quá 1 ngày chưa thấy kiện = nghi shipper đã lấy → xem camera / đòi shipper.
  /doisoat [qua]    đối soát ngay: cần gửi ↔ kho quét giao ↔ Nhanh/sàn ghi nhận ĐVVC lấy; tự chạy 17h, 18h, 9h hôm sau
Kết quả ghi bảng 07 · ĐỐI SOÁT NGÀY (mỗi sàn 1 dòng), danh sách lệch kèm MVĐ.
"""
import json, os, re, sys, time
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


def nh_idx():
    idx = {}
    for o in NH.orders().values():
        for k in (o.get("ma_san"), o.get("mvd")):
            if k:
                idx[str(k).lower()] = o
    return idx


def don_all(d):
    """Đơn Nhanh + đơn CHỈ CÓ TRÊN SÀN (danh sách 7h30 đọc từ Seller Center mà Nhanh chưa đồng bộ)."""
    od = dict(NH.orders())
    idx = nh_idx()
    for x in d.get("san", []):
        if str(x["ma"]).lower() in idx or (x.get("mvd") and x["mvd"].lower() in idx):
            continue
        od["san:" + x["ma"]] = {"id": "san:" + x["ma"], "kenh": x["kenh"], "ma_san": x["ma"], "mvd": x.get("mvd", ""),
                                "st": 42, "st_ten": "Chỉ có trên sàn", "tao": "", "cap_nhat": "", "gui_dvvc": "",
                                "chi_san": True}
    return od


def tim(ma_, d):
    o = NH.don_theo_ma(ma_) if NH.meta() else None
    if o:
        return o
    k = ma_.lower()
    return next((o for o in don_all(d).values() if o.get("chi_san") and k in (o["ma_san"].lower(), o["mvd"].lower())), None)


def tinh(ngay):
    """Đối soát 1 ngày → {kenh: {...danh sách đơn...}}."""
    s = st()
    d = ngay_st(s, ngay)
    huy_doc()
    od = don_all(d)
    giao = d["giao"]
    for g in giao.values():   # mã quét lúc Nhanh chưa đồng bộ đơn → tìm lại
        if (not g.get("id") or g["id"].startswith("san:")) and (o := tim(g["ma"], d)):
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
                                       "quet_chua_lay": [], "huy_sau_in": [], "huy_da_giao": [], "lay_khong_quet": [],
                                       "chi_san": []})
        if o.get("chi_san"):
            k["chi_san"].append(o)
        huy = la_huy(o)
        if huy:
            if oid in {r.get("id") for r in d["rut"].values()} or (HUY.get(oid) or {}).get("giu"):
                pass   # kho đã bấm "Đã rút lại" / /giulai
            elif quet:
                k["huy_da_giao"].append(o)
            elif trong_ds and not quet:
                k["huy_sau_in"].append(o)
            continue
        k["can"].append(o)
        if quet:
            k["quet"].append(o)
        if o.get("chi_san") and quet:   # Nhanh chưa có đơn → không biết sàn đã lấy chưa, tin kho
            k["lay"].append(o)
        elif lay or not la_cho(o):
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
    huy_cap_nhat()
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
        n_huy = len([1 for h in HUY.values() if h.get("kenh") == k and h.get("huy") == ngay])   # cùng nguồn với mục tổng kết
        if n_huy:
            L.append(f"   ⛔ {n_huy} đơn huỷ sau khi in (chi tiết ở mục ĐƠN HUỶ SAU IN)")
        if x["quet_chua_lay"]:
            L.append(f"   📣 {len(x['quet_chua_lay'])} kiện kho đã giao mà sàn chưa ghi nhận lấy → shipper chưa quét, "
                     f"đối chiếu biên bản: {ds_ma(x['quet_chua_lay'])}")
        if x["chua_di"]:
            L.append(f"   📦 <b>{len(x['chua_di'])} đơn chưa đi</b> (còn ở kho?): {ds_ma(x['chua_di'])}")
        if x["chua_tem"]:
            L.append(f"   🏷 {len(x['chua_tem'])} đơn chưa có MVĐ (chưa in được tem): {ds_ma(x['chua_tem'])}")
        if x["chi_san"]:
            L.append(f"   🔗 {len(x['chi_san'])} đơn CHỈ CÓ TRÊN SÀN, Nhanh chưa có → tồn Nhanh chưa trừ, kéo đơn về Nhanh: "
                     f"{ds_ma(x['chi_san'])}")
        if co_quet and x["lay_khong_quet"]:
            L.append(f"   ℹ️ {len(x['lay_khong_quet'])} kiện sàn ghi đã lấy mà kho không quét (quét sót?)")
        if ghi:
            ghi_07(ngay, san, x, co_quet)
    ht, _ = huy_tong_ket(ngay) if (ngay != KF.today() or datetime.now().hour >= 16) else huy_bao()
    if ht:
        L.append("\n" + ht)
    if ngay == KF.today() and (tt := thieu_bao()):
        L.append("\n" + tt)
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


def noi_dung_in(ds):
    """Các dòng báo in đơn cho danh sách đơn chờ gửi `ds` (dùng chung cho /indon và báo tự động theo giờ)."""
    L = []
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
    giu = []
    try:   # đơn đang có ticket đổi trước giao / /note / hoả tốc đổi size chưa xong → xử lý TRƯỚC khi gói
        import giu_don as GD
        cho = GD.dang_cho()
        giu = [(o, GD.ly_do_giu(o, cho)) for o in ds]
        giu = [(o, ly) for o, ly in giu if ly]
    except Exception as e:
        print("indon: không đọc được đơn chờ đổi", e, flush=True)
    if giu:
        import khung as KH
        L.append("\n" + KH.the(f"{len(giu)} đơn phải xử lý TRƯỚC khi gói", None, "Các đơn dưới có yêu cầu đổi size / ghi chú chưa xong",
                               ["Làm đúng yêu cầu (sửa đơn trên Nhanh nếu đổi size)", "Bấm nút trên thẻ ticket / thẻ việc", "Rồi mới gói + in tem"],
                               "Kho", icon="⚠️",
                               them=[f"• <code>{esc(ma(o))}</code> — " + "; ".join(esc(x) for x in ly) for o, ly in giu[:20]]))
    return L


def indon(m, arg):
    if not can_nhanh(m):
        return
    s = chup()
    luu(s)
    hn = KF.today()
    ds = [o for o in NH.orders().values() if la_cho(o)]
    L = [f"🖨 <b>IN ĐƠN</b> {datetime.now():%H:%M %d/%m} — đơn chờ gửi trên Nhanh:"] + noi_dung_in(ds)
    if len(L) == 1:
        L.append("Không có đơn chờ gửi 🎉")
    L.append(f"\nTổng cần gửi hôm nay: <b>{sum(1 for o in NH.orders().values() if o['id'] in s[hn]['ds'] and not la_huy(o))}</b>. "
             "Giao shipper xong: <b>chụp tem</b> (nhiều tem 1 ảnh được), chú thích <code>/giao</code>.")
    tsend(m["chat"]["id"], "\n".join(L) + cu_qua(), reply_to=m["message_id"])


BAO_IN_F = os.path.join(KF.ROOT, "logs", "bao_in.json")


def bao_in(send=False, luc=None):
    """BÁO IN ĐƠN TỰ ĐỘNG theo giờ (canh_bao.json bao_in_don_gio, mặc định 8h, 11h, 14h; chủ shop 28/11/2026).
    Mỗi khung giờ báo 1 lần trong 30 phút đầu; chỉ gửi khi có ĐƠN MỚI chờ gửi so với lần báo trước (không thì im).
    Gọi từ lượt đồng bộ Nhanh 3 phút / 30 phút. Trả text đã gửi (hoặc "")."""
    import khung as KH
    now = luc or datetime.now()
    try:
        gio = json.load(open(os.path.join(KF.ROOT, "knowledge", "canh_bao.json"), encoding="utf-8")).get("bao_in_don_gio") or [8, 11, 14]
    except Exception:
        gio = [8, 11, 14]
    if now.hour not in gio or now.minute >= 30 or not NH.meta():
        return ""
    try:
        st = json.load(open(BAO_IN_F))
    except Exception:
        st = {}
    hn, khung_ = now.strftime("%Y-%m-%d"), f"{now:%Y-%m-%d} {now.hour:02d}"
    if st.get("ngay") != hn:
        st = {"ngay": hn, "da_bao": [], "khung": []}
    if khung_ in st["khung"]:
        return ""
    ds = [o for o in NH.orders().values() if la_cho(o)]
    moi = [o for o in ds if o["id"] not in set(st["da_bao"])]
    st["khung"].append(khung_)
    t = ""
    if moi:
        tem = sum(1 for o in ds if o.get("mvd"))
        t = KH.the(f"In đơn – {now:%H:%M}", None,
                   f"Có {len(moi)} đơn mới từ lần báo trước · đang chờ gửi {len(ds)} đơn, cần in {tem} tem",
                   ["In tem trên sàn (TikTok / Shopee Seller Center) theo số dưới",
                    "Đơn trong mục ⚠️ phải xử lý xong rồi mới gói", "Giao shipper xong: chụp tem, chú thích /giao"],
                   "Kho", icon="🖨", them=[""] + noi_dung_in(ds))
        st["da_bao"] = sorted(set(st["da_bao"]) | {o["id"] for o in ds})
        print(re.sub(r"<[^>]+>", "", t))
        if send and KF.kchat():
            tsend(KF.kchat(), t)
    else:
        print(f"bao_in {khung_}: không có đơn mới")
    if send:
        try:
            os.makedirs(os.path.dirname(BAO_IN_F), exist_ok=True)
            json.dump(st, open(BAO_IN_F, "w"))
        except Exception as e:
            print("bao_in: không ghi được sổ", e)
    return t


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
    moi, trung, huy, la, cu, ngoai = [], [], [], [], [], []
    quet = []   # (mã quét, đơn Nhanh | None) — để kiểm đơn đang chờ đổi
    for x in mas:
        if x.lower() in d["giao"]:
            trung.append(x); continue
        o = tim(x, d)
        quet.append((x, o))
        d["giao"][x.lower()] = {"ma": x, "id": o["id"] if o else "", "kenh": o["kenh"] if o else "", "who": who,
                                "luc": datetime.now().strftime("%H:%M")}
        if not o:
            la.append(x)
        elif o.get("chi_san"):
            moi.append(o); ngoai.append(x)
        elif la_huy(o):
            huy.append((x, o))
        else:
            moi.append(o)
            if not la_cho(o) and _d(o.get("gui_dvvc") or o.get("cap_nhat")) < KF.today():
                cu.append(o)
    giu = []
    try:   # đơn còn ticket đổi trước giao / /note / hoả tốc đổi size chưa xong → GIỮ LẠI, không ghi đã giao
        import giu_don as GD
        cho = GD.dang_cho()
        for x, o in quet:
            if o and la_huy(o):
                continue
            ly = GD.ly_do_giu(o, cho) if o else GD.ly_do_giu_ma(x, cho)
            if ly:
                giu.append((x, ly))
                d["giao"].pop(x.lower(), None)
                moi[:] = [y for y in moi if y is not o]
                la[:] = [y for y in la if y != x]
                ngoai[:] = [y for y in ngoai if y != x]
                cu[:] = [y for y in cu if y is not o]
    except Exception as e:
        print("giao: không đọc được đơn chờ đổi", e, flush=True)
    luu(s)
    so = [x for x in la if ma_that(x)] + ngoai   # mã gõ sai/ngắn (VD XYZ123) không ghi sổ, chỉ báo ❓
    if so:
        thieu_ghi([{"ma": x, "kenh": kenh_theo_ma(x)} for x in so], "kho /giao")
    dem = {}
    for o in moi:
        dem[SAN_KENH.get(o["kenh"], o["kenh"])] = dem.get(SAN_KENH.get(o["kenh"], o["kenh"]), 0) + 1
    L = [f"🚚 {esc(who)} giao <b>{len(moi) + len(la)}</b> kiện" + (" (" + " · ".join(f"{k} {v}" for k, v in dem.items()) + ")" if dem else "")]
    btn = None
    if huy:
        L.append("🚨 <b>ĐƠN ĐÃ HUỶ — GIỮ LẠI, KHÔNG GIAO:</b> " + ", ".join(
            f"<code>{esc(x)}</code> ({esc(o['st_ten'])})" for x, o in huy))
        btn = [[{"text": f"↩️ Đã rút lại {x[-8:]}", "callback_data": f"xk:rut:{x[:40]}"}] for x, _ in huy[:5]]
    if giu:
        import khung as KH
        for x, ly in giu:
            L.append("\n" + KH.the("Giữ lại kiện này – không giao", x, "; ".join(ly) + " – chưa làm xong",
                                   ["Rút kiện ra, KHÔNG đưa shipper", "Làm xong yêu cầu, bấm nút trên thẻ",
                                    "In lại tem nếu cần, rồi quét /giao lại"], "Kho", icon="⛔",
                                   them=["<i>(kiện này chưa được ghi là đã giao)</i>"]))
    if trung:
        L.append("♻️ Quét rồi, bỏ qua: " + ", ".join(f"<code>{esc(x)}</code>" for x in trung))
    if la:
        L.append("❓ Không thấy trên Nhanh (đơn mới chưa đồng bộ / gõ sai?): " + ", ".join(f"<code>{esc(x)}</code>" for x in la))
    if ngoai:
        L.append("🔗 Có trên sàn nhưng Nhanh chưa có (tồn Nhanh chưa trừ): " + ", ".join(f"<code>{esc(x)}</code>" for x in ngoai))
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
        huy_giu(x, ten(u))
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


def doi_soat_shipper():
    """12h / 18h (bài dạy D004): đơn ĐÃ IN TEM mà sàn vẫn chưa ghi nhận shipper lấy → đối chiếu với shipper
    (shipper báo "quét hết" nhưng sàn còn sót đơn chưa quét → đơn trễ/fail). Trả list tin (mỗi sàn 1 tin, tránh quá dài)."""
    try:   # đọc Nhanh mới nhất ngay lúc báo (lịch 30 phút có thể trễ)
        import nhanh_api as NA
        if NA.co_api():
            NA.sync()
    except Exception as e:
        print("doi_soat_shipper: đọc Nhanh lỗi", repr(e)[:200], flush=True)
    if not NH.con_moi(90):
        return []
    out, _, _ = tinh(KF.today())
    gio = datetime.now().strftime("%Hh%M")
    tin, tong = [], 0
    for k, x in out.items():
        xs = x["quet_chua_lay"] + x["chua_di"]
        if not xs:
            continue
        tong += len(xs)
        dong = [f"• <b>{SAN_KENH.get(k, k)}: {len(xs)} đơn</b>"
                + (f" (🚨 {len(x['quet_chua_lay'])} kho đã giao shipper)" if x["quet_chua_lay"] else "")]
        for o in xs[:60]:
            dong.append(("🚨 " if o in x["quet_chua_lay"] else "") + f"<code>{esc(o.get('mvd'))}</code> · đơn "
                        f"<code>{esc(o.get('ma_san') or o.get('id'))}</code>")
        if len(xs) > 60:
            dong.append(f"… (+{len(xs) - 60}) — gõ /doisoat xem đủ")
        tin.append("\n".join(dong))
    if not tong:
        return [f"✅ <b>ĐỐI SOÁT SHIPPER {gio}</b>: mọi đơn đã in tem hôm nay sàn đều ghi nhận shipper đã lấy."]
    dau = (f"🚚 <b>ĐỐI SOÁT SHIPPER {gio}</b> — <b>{tong} đơn đã in tem mà sàn chưa ghi nhận shipper quét</b> "
           "(MVĐ · mã đơn sàn):\n"
           "→ Còn trong kho: đưa shipper quét ngay. 🚨 Đã đưa shipper mà sàn chưa ghi lấy: hỏi shipper, đối chiếu biên bản.")
    return [dau] + tin


def bao_sang():
    """9h: chốt danh sách hôm nay + việc còn treo của hôm qua."""
    if not NH.con_moi(180):
        return ""
    luu(chup())
    qua = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    huy_cap_nhat()
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
    ht, _ = huy_bao()
    if ht:
        L.append(ht)
    if tt := thieu_bao():
        L.append(tt)
    ghi_qua = bool(L)
    if ghi_qua:
        bao_cao(qua)  # cập nhật dòng 07 hôm qua với trạng thái mới nhất
    n = len([1 for o in NH.orders().values() if la_cho(o)])
    t = f"🖨 <b>Hôm nay cần gửi {n} đơn</b> — gõ /indon xem chi tiết (tem cần in, đơn sắp quá hạn)."
    if L:
        t = "🚚 <b>Còn treo từ hôm qua</b>:\n" + "\n".join(L) + "\n\n" + t
    return t


# ======================= 7h30: Seller Center ↔ Nhanh → in ở đâu =======================

SAN_DIR = os.path.join(KF.ROOT, "logs", "san")


def lech_san(d):
    """So danh sách sàn cần gửi với cache Nhanh → {kenh: {ds, thieu, huy_nh, du, nh_cho, gap}} (kenh không đọc được: None)."""
    idx = nh_idx()
    out = {}
    for k in ("tiktok", "shopee"):
        ds = d.get(k)
        if ds is None:
            out[k] = None; continue
        san_ma = {str(x["ma"]).lower() for x in ds} | {str(x.get("mvd", "")).lower() for x in ds if x.get("mvd")}
        tim = lambda x: idx.get(str(x["ma"]).lower()) or idx.get(str(x.get("mvd", "")).lower())
        nh_cho = [o for o in NH.orders().values() if o["kenh"] == k and la_cho(o)]
        doc = f"{KF.today()} {d.get('luc') or '23:59'}"   # đơn Nhanh tạo sau lúc đọc sàn: sàn lúc đó chưa có, không phải thừa
        out[k] = {"ds": ds,
                  "gap": [x for x in ds if x.get("hoa_toc") or "tốc" in str(x.get("giao", "")).lower()],
                  "thieu": [x for x in ds if not tim(x)],
                  # huỷ SAU lúc đọc sàn = khách huỷ sau đó (sổ "huỷ sau in" lo), không phải Nhanh ghi sai
                  "huy_nh": [x for x in ds if (o := tim(x)) and la_huy(o) and (o.get("cap_nhat") or "") <= doc + ":59"],
                  "nh_cho": nh_cho,
                  # Mới/Chờ xác nhận: sàn còn để ở tab chờ xác nhận, không phải lệch
                  "du": [o for o in nh_cho if o["ma_san"].lower() not in san_ma and o["mvd"].lower() not in san_ma
                         and o.get("st") not in (54, 55, 57) and (o.get("tao") or "") < doc]}
    return out


def co_lech(d):
    return any(v and (v["thieu"] or v["huy_nh"] or v["du"]) for v in lech_san(d).values())


def dong_bo_lai():
    """Đọc lại Nhanh qua Open API (chỉ đọc). False = không có API (tác vụ lịch tự đồng bộ qua Chrome)."""
    import subprocess
    import nhanh_api as NA
    if not NA.co_api():
        return False
    try:
        subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "nhanh.py"), "sync"],
                       timeout=900, capture_output=True)
    except Exception as e:
        print("dong bo lai loi:", e)
    return True


LAY_F = os.path.join(KF.ROOT, "logs", "san", "lay_nhanh.json")


def doc_csv_san(opt):
    d = {"luc": datetime.now().strftime("%H:%M")}
    for k in ("tiktok", "shopee"):
        f = opt.get("--" + k)
        if f and os.path.exists(f):
            d[k] = [dict(zip(("ma", "mvd", "tt", "giao"), (l.split("|") + ["", "", ""])[:4]))
                    for l in open(f, encoding="utf-8").read().splitlines() if l.strip()]
            for x in d[k]:
                x["hoa_toc"] = "tốc" in x["giao"].lower()
            if opt.get("--tong-" + k):
                d["tong_" + k] = int(opt["--tong-" + k])
    return d


def ma_that(m):
    """Mã trông như mã đơn sàn / mã vận đơn thật (đủ dài, nhiều số) — để mã gõ sai không vào sổ theo dõi."""
    m = str(m).strip().upper()
    return bool(kenh_theo_ma(m)) or bool(re.fullmatch(r"[A-Z]{0,6}\d{9,}[A-Z0-9]*", m))


def kenh_theo_ma(m):
    m = str(m).strip().upper()
    return "tiktok" if re.fullmatch(r"5[78]\d{16}", m) else "shopee" if re.fullmatch(r"\d{6}[0-9A-Z]{8}", m) else ""


def can_lay(d):
    """Mã đơn sàn cần bấm "Tải đơn" trên Nhanh (đơn Nhanh thiếu / ghi huỷ sai / còn chờ mà sàn đã xong + sổ Nhanh thiếu)."""
    out = {"tiktok": [], "shopee": []}
    if NH.meta():
        for k, x in lech_san(d).items():
            if x:
                out[k] += [o["ma"] for o in x["thieu"] + x["huy_nh"]] + [o["ma_san"] for o in x["du"] if o.get("ma_san")]
    for v in thieu_cap_nhat():
        k = v.get("kenh") or kenh_theo_ma(v["ma"])
        if k in out and kenh_theo_ma(v["ma"]):
            out[k].append(v["ma"])
    return {k: list(dict.fromkeys(m for m in v if m))[:150] for k, v in out.items()}


def canlay_cli(a):
    """7h30, TRƯỚC khi so: python3 tools/xuat_kho.py canlay --tiktok tt.csv --shopee sp.csv → đọc lại Nhanh (API) rồi in JSON
    {"tiktok": [mã], "shopee": [mã]} = đơn tác vụ lịch phải bấm Tải đơn trên Nhanh (doc_san.js __layDonNhanh)."""
    opt = {a[i]: a[i + 1] for i in range(1, len(a) - 1) if a[i].startswith("--") and not a[i + 1].startswith("--")}
    d = doc_csv_san(opt)
    if NH.meta() and co_lech(d):
        dong_bo_lai()
    out = can_lay(d)
    os.makedirs(os.path.dirname(LAY_F), exist_ok=True)
    json.dump(dict(out, ngay=KF.today(), luc=datetime.now().strftime("%H:%M")), open(LAY_F, "w"), ensure_ascii=False)
    print(json.dumps(out, ensure_ascii=False))


def so_san(d, lan_dong_bo=0):
    """d = {"luc": "07:31", "tiktok": [{"ma", "tt", "giao"}], "shopee": [{"ma", "mvd", "tt", "hoa_toc"}]} — danh sách đơn
    CẦN GỬI đọc từ Seller Center (tác vụ lịch 7h30, Chrome chủ shop). Kho IN ĐƠN Ở SÀN (từ 12/11/2026); bot so với Nhanh
    để bắt tồn Nhanh lệch: đơn sàn có mà Nhanh thiếu (tồn chưa trừ) → ghi sổ theo dõi tới khi Nhanh có."""
    s = st()
    dd = ngay_st(s, KF.today())
    co_nh = bool(NH.meta())
    dd["san"] = [dict(x, kenh=k) for k in ("tiktok", "shopee") for x in d.get(k) or [] if x.get("ma")]
    cu = NH.meta().get("dong_bo", "") if co_nh else ""
    L = [f"🖨 <b>IN ĐƠN Ở SÀN {datetime.now():%d/%m}</b> · sàn đọc lúc {esc(d.get('luc', ''))}"
         + (f" · Nhanh cập nhật {esc(cu[11:] or cu)}" if co_nh else "")]
    ket, lech_ton = {}, []
    lech = lech_san(d) if co_nh else {}
    try:
        lay = json.load(open(LAY_F))
        lay = sum(len(lay.get(k) or []) for k in ("tiktok", "shopee")) if lay.get("ngay") == KF.today() else 0
    except Exception:
        lay = 0
    if lay:
        L.append(f"🔄 Bot đã bấm <b>Tải đơn</b> trên Nhanh cho {lay} đơn lệch rồi đọc lại Nhanh — dưới đây là phần Nhanh VẪN chưa khớp.")
    for k in ("tiktok", "shopee"):
        ds = d.get(k)
        if ds is None:
            L.append(f"\n❔ <b>{SAN_KENH[k]}</b>: bot không đọc được Seller Center — kho vẫn in ở sàn như thường"); continue
        tong = d.get("tong_" + k) or 0
        gap = [x for x in ds if x.get("hoa_toc") or "tốc" in str(x.get("giao", "")).lower()]
        L.append(f"\n📦 <b>{SAN_KENH[k]}</b>: cần gửi <b>{len(ds)}</b> đơn" + (f" · 🔥 hoả tốc {len(gap)} (in + gói trước)" if gap else "")
                 + (f"\n   ⚠️ bot chỉ đọc được {len(ds)}/{tong} đơn — đối soát dưới có thể thiếu" if tong > len(ds) + 2 else ""))
        ket[k] = "san"
        if not co_nh:
            continue
        x = lech[k]
        thieu = x["thieu"]
        dl = f" (đã đồng bộ lại Nhanh {lan_dong_bo} lần)" if lan_dong_bo else ""
        if thieu:
            thieu_ghi([dict(o, kenh=k) for o in thieu], "sàn cần gửi 7h30")
            lech_ton.append(f"   🔗 {SAN_KENH[k]}: <b>{len(thieu)} đơn Nhanh chưa có</b>{dl}{' (bấm Tải đơn rồi vẫn không về)' if lay else ''} → tồn Nhanh CHƯA TRỪ, dễ bán vượt: "
                            + ", ".join(f"<code>{esc(o['ma'])}</code>" for o in thieu[:30]) + (" …" if len(thieu) > 30 else ""))
        het = [o for o in x["huy_nh"] if (nh := nh_idx().get(str(o["ma"]).lower()) or nh_idx().get(str(o.get("mvd", "")).lower()))
               and (nh.get("st") == 68 or "hết hàng" in str(nh.get("st_ten", "")).lower())]
        if het:
            lech_ton.append(f"   🚫 {SAN_KENH[k]}: <b>{len(het)} đơn sàn cần gửi mà Nhanh báo HẾT HÀNG</b> → kho kiểm kệ: còn hàng thì gói gửi"
                            " + báo người nhập Nhanh chỉnh tồn; hết thật thì báo chủ shop/CSKH xử lý đơn trên sàn (bot không huỷ): "
                            + ", ".join(f"<code>{esc(o['ma'])}</code>" for o in het[:30]))
            x["huy_nh"] = [o for o in x["huy_nh"] if o not in het]
        if x["huy_nh"]:
            lech_ton.append(f"   ⚠️ {SAN_KENH[k]}: <b>{len(x['huy_nh'])} đơn sàn vẫn cần gửi mà Nhanh ghi huỷ</b>{dl} → Nhanh đã nhả hàng,"
                            " tồn Nhanh CAO hơn thật (kiểm lại đơn trên sàn, đúng là cần gửi thì sửa trên Nhanh): "
                            + ", ".join(f"<code>{esc(o['ma'])}</code>" for o in x["huy_nh"][:30]))
        if x["du"]:
            lech_ton.append(f"   ⛔ {SAN_KENH[k]}: <b>{len(x['du'])} đơn Nhanh còn chờ gửi mà sàn đã huỷ/đã giao</b>"
                            " → Nhanh đang giữ hàng, tồn Nhanh THẤP hơn thật: " + ds_ma(x["du"], 30))
    luu(s)
    if co_nh:
        L.append("\n🧮 <b>ĐỐI SOÁT TỒN NHANH</b>")
        chua = [SAN_KENH[k] for k in ("tiktok", "shopee") if d.get(k) is None]
        if len(chua) == 2:
            L.append("   ❔ Không đọc được sàn nào → hôm nay CHƯA đối soát tồn được (kiện /giao vẫn được so với Nhanh).")
        else:
            L.extend(lech_ton or [f"   🟢 {' + '.join(SAN_KENH[k] for k in ('tiktok', 'shopee') if d.get(k) is not None)}: đơn sàn và Nhanh"
                                  " khớp — tồn Nhanh đã trừ đủ."])
            if chua:
                L.append(f"   ❔ {', '.join(chua)}: chưa đối soát (không đọc được sàn).")
        if lech_ton:
            L.append("   → Đơn 🔗: vào Nhanh › Đơn sàn › Lấy đơn kéo về (bot nhắc 9h + 17h mỗi ngày tới khi Nhanh có). Đơn ⛔: mai vẫn còn thì sửa trạng thái trên Nhanh.")
    else:
        L.append("\n❔ Chưa đọc được Nhanh → chưa đối soát tồn được.")
    L.append("Giao shipper: chụp tem chú thích <code>/giao</code> — bot so từng kiện với Nhanh, kiện Nhanh không có sẽ vào sổ theo dõi tồn.")
    return "\n".join(L), ket


# ======================= SỔ "NHANH THIẾU ĐƠN" (đơn in/giao ở sàn mà Nhanh chưa có → tồn Nhanh chưa trừ) =======================

THIEU_F = os.path.join(KF.ROOT, "logs", "nhanh_thieu.json")


def thieu_doc():
    try:
        return json.load(open(THIEU_F))
    except Exception:
        return {}


def thieu_luu(t):
    han = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    t = {k: v for k, v in t.items() if (v.get("co") or v["tu"]) >= han}
    os.makedirs(os.path.dirname(THIEU_F), exist_ok=True)
    json.dump(t, open(THIEU_F, "w"), ensure_ascii=False, indent=1)


def thieu_ghi(xs, nguon):
    """xs: [{ma, mvd?, kenh?}] — đơn sàn có mà Nhanh chưa có."""
    t = thieu_doc()
    for x in xs:
        k = str(x.get("ma") or "").lower()
        da = set(t) | {str(v.get("mvd", "")).lower() for v in t.values() if v.get("mvd")}   # đã có theo mã đơn HOẶC MVĐ
        if k and k not in da and not (x.get("mvd") and str(x["mvd"]).lower() in da):
            t[k] = {"ma": x["ma"], "mvd": x.get("mvd", ""), "kenh": x.get("kenh", ""), "tu": KF.today(), "nguon": nguon, "co": ""}
    thieu_luu(t)


def thieu_cap_nhat():
    """Đơn trong sổ mà Nhanh đã có → đánh dấu xong. Trả danh sách còn thiếu (cũ nhất trước)."""
    t = thieu_doc()
    if not t or not NH.meta():
        return []
    idx = nh_idx()
    for v in t.values():
        if not v.get("co") and (idx.get(str(v["ma"]).lower()) or (v.get("mvd") and idx.get(str(v["mvd"]).lower()))):
            v["co"] = KF.today()
    thieu_luu(t)
    return sorted((v for v in t.values() if not v.get("co")), key=lambda v: v["tu"])


def thieu_bao():
    con = thieu_cap_nhat()
    if not con:
        return ""
    cu = [v for v in con if v["tu"] < KF.today()]
    return (f"🔗 <b>{len(con)} đơn đã in/giao ở sàn mà Nhanh vẫn chưa có</b> → tồn Nhanh chưa trừ hàng các đơn này"
            + (f" (⏳ {len(cu)} đơn từ hôm trước)" if cu else "") + ":\n"
            + "\n".join(f"• <code>{esc(v['ma'])}</code> {SAN_KENH.get(v.get('kenh'), '')} · từ {v['tu'][8:]}/{v['tu'][5:7]} ({esc(v['nguon'])})"
                        for v in con[:25]) + (f"\n… (+{len(con) - 25})" if len(con) > 25 else "")
            + "\n→ Nhanh › Đơn sàn › Lấy đơn kéo về; mã kho quét sai thì bỏ qua.")


def so_san_file(path, send=False, doi=True):
    d = json.load(open(path))
    os.makedirs(SAN_DIR, exist_ok=True)
    out = os.path.join(SAN_DIR, KF.today() + ".json")
    if os.path.abspath(path) != os.path.abspath(out):
        json.dump(d, open(out, "w"), ensure_ascii=False)
    lan = 0
    # luôn đọc lại Nhanh trước khi so; còn lệch → đợi 3 phút đọc lại lần nữa (Nhanh bắt đơn sàn chậm vài phút),
    # rồi mới chốt đơn phải in ở sàn
    while doi and NH.meta() and lan < 2 and (lan == 0 or co_lech(d)):
        if lan:
            time.sleep(180)
        if not dong_bo_lai():
            break
        lan += 1
    t, ket = so_san(d, lan)
    print(re.sub(r"<[^>]+>", "", t))
    if send and KF.kchat():
        tsend(KF.kchat(), t)
    return ket


def sosan_cli(a):
    # tác vụ 7h30:  python3 tools/xuat_kho.py sosan --tiktok tt.csv --shopee sp.csv [--tong-tiktok N] [--tong-shopee N] [--send]
    # (csv = window.__out của tools/doc_san.js: "ma|mvd|tt|giao"; thiếu file sàn nào = không đọc được sàn đó)
    #  hoặc: sosan file.json [--send]
    if a[1].startswith("--"):
        opt = {a[i]: a[i + 1] for i in range(1, len(a) - 1) if a[i].startswith("--") and not a[i + 1].startswith("--")}
        d = doc_csv_san(opt)
        os.makedirs(SAN_DIR, exist_ok=True)
        f = os.path.join(SAN_DIR, KF.today() + ".json")
        json.dump(d, open(f, "w"), ensure_ascii=False)
        so_san_file(f, "--send" in a, "--khong-doi" not in a)
    else:
        so_san_file(a[1], "--send" in a, "--khong-doi" not in a)


# ======================= ĐƠN HUỶ SAU KHI IN (đã bấm Chuẩn bị hàng / có MVĐ rồi mới huỷ) =======================

HUY_F = os.path.join(KF.ROOT, "logs", "huy_sau_in.json")
HUY_TU = "2026-11-12"     # ngày bắt đầu theo dõi — không lôi đơn huỷ cũ ra
HUY = {}                  # oid -> {ma, ma_san, kenh, huy (ngày), st_ten, quet, giu{who,luc}, bao}


def huy_doc():
    HUY.clear()
    try:
        HUY.update(json.load(open(HUY_F)))
    except Exception:
        pass
    return HUY


def huy_luu():
    han = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    for k in [k for k, x in HUY.items() if x.get("huy", "") < han]:
        HUY.pop(k)
    os.makedirs(os.path.dirname(HUY_F), exist_ok=True)
    json.dump(HUY, open(HUY_F, "w"), ensure_ascii=False, indent=1)


def huy_cap_nhat():
    """Quét Nhanh: đơn đã HUỶ mà có MVĐ (= đã sắp xếp vận chuyển / in tem) → vào sổ. Ghi kèm kho đã quét giao chưa."""
    huy_doc()
    if not NH.meta():
        return HUY
    s = st()
    giao_ids = {g.get("id") for d in s.values() for g in d.get("giao", {}).values() if g.get("id")}
    rut = {r.get("id"): r for d in s.values() for r in d.get("rut", {}).values() if r.get("id")}
    moc = max(HUY_TU, (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"))
    for o in NH.orders().values():
        if not (la_huy(o) and o.get("mvd")):
            continue
        ngay = _d(o.get("cap_nhat")) or _d(o.get("tao"))
        if o["id"] not in HUY and ngay < moc:
            continue
        x = HUY.setdefault(o["id"], {"ma": o["mvd"], "ma_san": o.get("ma_san", ""), "kenh": o["kenh"], "huy": ngay,
                                     "thay": datetime.now().strftime("%Y-%m-%d %H:%M")})
        x["st_ten"] = o.get("st_ten", "")
        x["quet"] = o["id"] in giao_ids
        if o["id"] in rut and not x.get("giu"):
            x["giu"] = {"who": rut[o["id"]].get("rut", ""), "luc": datetime.now().strftime("%d/%m %H:%M")}
    huy_luu()
    return HUY


def huy_giu(ma_, who):
    """Kho xác nhận đã giữ kiện/tem của đơn huỷ. Trả 'ok' | 'da' | 'khong_huy' | 'la'."""
    huy_doc()
    k = ma_.lower()
    oid = next((i for i, x in HUY.items() if k in (str(x["ma"]).lower(), str(x.get("ma_san", "")).lower())), None)
    if not oid:
        o = NH.don_theo_ma(ma_) if NH.meta() else None
        if not o:
            return "la"
        if not la_huy(o):
            return "khong_huy"
        oid = o["id"]
        HUY[oid] = {"ma": o.get("mvd") or ma_, "ma_san": o.get("ma_san", ""), "kenh": o["kenh"],
                    "huy": _d(o.get("cap_nhat")) or KF.today(), "st_ten": o.get("st_ten", ""), "bao": True}
    if HUY[oid].get("giu"):
        return "da"
    HUY[oid]["giu"] = {"who": who, "luc": datetime.now().strftime("%d/%m %H:%M")}
    huy_luu()
    return "ok"


def don_san(x):
    """' · đơn <mã đơn sàn>' (bài dạy D003: báo đơn huỷ sau in kèm mã đơn hàng + mã vận đơn)."""
    return f" · đơn <code>{esc(x['ma_san'])}</code>" if x.get("ma_san") else ""


def huy_bao():
    """Text các đơn huỷ sau in mà kho CHƯA xác nhận giữ kiện. Trả (text, số đơn)."""
    cho = [x for x in HUY.values() if not x.get("giu")]
    if not cho:
        return "", 0
    hn = KF.today()
    da_giao = [x for x in cho if x.get("quet")]
    lau = [x for x in cho if not x.get("quet") and x.get("huy", hn) < hn]
    moi = [x for x in cho if not x.get("quet") and x.get("huy", hn) >= hn]
    f = lambda xs: ", ".join(f"<code>{esc(x['ma'])}</code> ({SAN_KENH.get(x['kenh'], x['kenh'])}{don_san(x)})" for x in xs[:15]) \
        + (f" … (+{len(xs) - 15})" if len(xs) > 15 else "")
    L = [f"⛔ <b>ĐƠN HUỶ SAU KHI IN — {len(cho)} kiện kho chưa xác nhận giữ lại</b>"]
    if da_giao:
        L.append(f"🚨 <b>{len(da_giao)} đơn đã huỷ mà kho ĐÃ QUÉT GIAO shipper</b> → gọi shipper trả lại kiện, "
                 f"không trả thì khiếu nại ĐVVC: {f(da_giao)}")
    if lau:
        L.append(f"🚨 <b>{len(lau)} đơn huỷ từ hôm trước vẫn chưa thấy kiện</b> → tìm ở khay/kệ; không thấy = nghi shipper "
                 f"đã lấy (xem camera bàn giao, đối chiếu biên bản, đòi shipper): {f(lau)}")
    if moi:
        L.append(f"📦 {len(moi)} đơn huỷ hôm nay → rút kiện/tem khỏi khay giao, KHÔNG đưa shipper: {f(moi)}")
    L.append("Rút được kiện nào: chụp tem chú thích <code>/giulai</code> (hoặc gõ <code>/giulai MVĐ …</code>) → bot gạch. "
             "Sau đó bóc kiện, trả hàng lên kệ.")
    return "\n".join(L), len(cho)


def huy_tong_ket(ngay=None):
    """Cuối ngày: TẤT CẢ đơn huỷ sau khi in/gói của ngày (cả kiện đã giữ) + kiện ngày trước còn treo → kho đếm khay đơn huỷ."""
    ngay = ngay or KF.today()
    xs = [x for x in HUY.values() if x.get("huy") == ngay or not x.get("giu")]
    if not xs:
        return "", 0
    f = lambda ys: ", ".join(f"<code>{esc(x['ma'])}</code>{(' (' + don_san(x)[3:] + ')') if x.get('ma_san') else ''}" for x in ys[:25]) \
        + (f" … (+{len(ys) - 25})" if len(ys) > 25 else "")
    giu = [x for x in xs if x.get("giu")]
    da_giao = [x for x in xs if not x.get("giu") and x.get("quet")]
    chua = [x for x in xs if not x.get("giu") and not x.get("quet")]
    dem = {}
    for x in xs:
        dem[SAN_KENH.get(x["kenh"], x["kenh"])] = dem.get(SAN_KENH.get(x["kenh"], x["kenh"]), 0) + 1
    L = [f"⛔ <b>TỔNG KẾT ĐƠN HUỶ SAU KHI IN/GÓI</b> {ngay[8:10]}/{ngay[5:7]}: <b>{len(xs)}</b> đơn ("
         + " · ".join(f"{k} {v}" for k, v in dem.items()) + ")"]
    if giu:
        L.append(f"✅ Kho đã giữ <b>{len(giu)}</b> kiện → <b>đếm khay đơn huỷ phải đủ {len(giu)} kiện</b>, bóc ra trả hàng lên kệ: {f(giu)}")
    if chua:
        L.append(f"❓ <b>{len(chua)} kiện chưa thấy</b> → tìm ở khay giao/kệ trước khi về; không thấy = nghi shipper đã lấy, "
                 f"báo trưởng kho xem camera: {f(chua)}")
    if da_giao:
        L.append(f"🚨 <b>{len(da_giao)} kiện đã huỷ mà kho đã giao shipper</b> → đòi shipper trả lại: {f(da_giao)}")
    L.append("Tìm được kiện nào: chụp tem chú thích <code>/giulai</code>.")
    return "\n".join(L), len(chua) + len(da_giao)


def canh_huy(send=False):
    """Sau mỗi lần đồng bộ Nhanh: đơn vừa huỷ sau khi in → báo nhóm Kho NGAY để rút kiện trước khi shipper tới."""
    if not NH.meta():
        return ""
    huy_cap_nhat()
    moi = [x for x in HUY.values() if not x.get("bao") and not x.get("giu")]
    if not moi or not (7 <= datetime.now().hour < 22):
        return ""
    t = ("⛔ <b>VỪA HUỶ SAU KHI IN — RÚT KIỆN RA, ĐỪNG GIAO SHIPPER</b>\n"
         + "\n".join(f"• <code>{esc(x['ma'])}</code> {SAN_KENH.get(x['kenh'], x['kenh'])}{don_san(x)} · {esc(x.get('st_ten', ''))}"
                     + (" · 🚨 kho đã quét giao → gọi shipper trả lại" if x.get("quet") else "") for x in moi[:30])
         + "\nRút xong chụp tem chú thích <code>/giulai</code>.")
    if send:
        if not KF.kchat() or not tsend(KF.kchat(), t):
            return t
    for x in moi:
        x["bao"] = True
    huy_luu()
    return t


def giulai(m, arg):
    chat, who = m["chat"]["id"], ten(m.get("from"))
    mas = list(dict.fromkeys(TK.ma_list(arg)))
    if not mas:
        huy_cap_nhat()
        t, n = huy_bao()
        return tsend(chat, (t or "✅ Không còn đơn huỷ sau in nào chờ giữ kiện.")
                     + "\n\n📷 Rút được kiện đơn huỷ: chụp tem chú thích <code>/giulai</code>.",
                     reply_to=m["message_id"])
    kq = {"ok": [], "da": [], "khong_huy": [], "la": []}
    huy_cap_nhat()
    for x in mas:
        kq[huy_giu(x, who)].append(x)
    for x in kq["ok"] + kq["da"]:   # bỏ khỏi "đã giao" nếu lỡ quét
        s = st()
        for dd in s.values():
            g = dd.get("giao", {}).pop(x.lower(), None)
            if g:
                dd.setdefault("rut", {})[x.lower()] = dict(g, rut=who)
        luu(s)
    c = lambda xs: ", ".join(f"<code>{esc(x)}</code>" for x in xs)
    L = [f"↩️ {esc(who)} giữ lại <b>{len(kq['ok'])}</b> kiện đơn huỷ" + (f": {c(kq['ok'])}" if kq["ok"] else "")]
    if kq["da"]:
        L.append("♻️ Đã xác nhận trước rồi: " + c(kq["da"]))
    if kq["khong_huy"]:
        L.append("⚠️ <b>Đơn KHÔNG huỷ</b> → vẫn giao bình thường, đừng giữ: " + c(kq["khong_huy"]))
    if kq["la"]:
        L.append("❓ Không thấy trên Nhanh (gõ sai / Nhanh chưa đồng bộ?): " + c(kq["la"]))
    _, n = huy_bao()
    L.append(f"Còn <b>{n}</b> đơn huỷ sau in chưa thấy kiện — gõ /giulai xem." if n else "✅ Hết đơn huỷ sau in chờ giữ kiện.")
    tsend(chat, "\n".join(L), reply_to=m["message_id"])


TK.EXT_CMDS.update({"/indon": indon, "/giao": giao, "/doisoat": doisoat, "/giulai": giulai})
TK.EXT_NHOM.update({k: ("CHAT_ID",) for k in ("/indon", "/giao", "/doisoat", "/giulai")})
TK.EXT_CB["xk"] = on_cb

if __name__ == "__main__":
    import lark as Lk
    TK.init(Lk.load_env(), start_worker=False)
    import sys
    a = sys.argv[1:]
    if a and a[0] == "sosan":
        sosan_cli(a)
    elif a and a[0] == "canlay":
        canlay_cli(a)
    elif a and a[0] == "canhhuy":   # sau mỗi lần đồng bộ Nhanh (nhanh.py sync gọi): báo đơn vừa huỷ sau in
        print(re.sub(r"<[^>]+>", "", canh_huy("--send" in a)) or "không có đơn huỷ sau in mới")
    elif a and a[0] == "baoin":   # báo in đơn tự động theo giờ (gọi mỗi lượt đồng bộ Nhanh; tự lọc khung giờ)
        bao_in("--send" in a)
    elif a and a[0] == "doisoat":   # python3 tools/xuat_kho.py doisoat [YYYY-MM-DD]
        print(re.sub(r"<[^>]+>", "", bao_cao(a[1] if len(a) > 1 else None, ghi=False)[0]))
    else:
        print(__doc__)
