#!/usr/bin/env python3
"""YÊU CẦU HOÀN TIỀN / TRẢ HÀNG trên TikTok Shop + Shopee → báo nhóm Đổi trả CS-Kho cho CSKH xử lý.

Bot CHỈ ĐỌC + NHẮC, không bấm duyệt/từ chối (việc của người được giao, xem SOP).
Tác vụ lịch (Claude in Chrome của chủ shop) chạy tools/doc_san.js → __docHoanTikTok / __docHoanShopee → CSV, rồi:
  python3 tools/hoan_san.py --tiktok tt.csv --shopee sp.csv [--tong-tiktok N] [--tong-shopee N] [--send]
CSV mỗi dòng: ma|loai|ly_do|tt|han|kv|tien|nut|mvd   (thiếu file sàn nào = không đọc được sàn đó)
Đối chiếu bảng 09 · HÀNG HOÀN NHẬN: kiện kho đã nhận chưa + tình trạng → CSKH biết đồng ý hoàn hay khiếu nại/kháng nghị.
Tag CSKH theo CA LÀM: đọc lịch ca ~/orbit-runtime/lich/ca.json (bot HCNS ghi mỗi tuần: khung giờ + người từng ca + ID
Telegram) → tag người đang trong ca CSKH; ngoài giờ ca thì tag ca kế tiếp. Không có lịch → CSKH_TAG trong lark.env.
"""
import json, os, re, sys
from datetime import datetime, timedelta

import orbit_tg as TG
import ticket as TK
import nhanh as NH
import kho_flow as KF
import ly_do_hoan as LDH

esc, tsend = TK.esc, TK.tsend
STATE = os.path.join(KF.ROOT, "logs", "hoan_san.json")
COLS = ("ma", "loai", "ly_do", "tt", "han", "kv", "tien", "nut", "mvd")
CAN_XL = {"phan_hoi", "xac_nhan", "bang_chung"}     # shop phải bấm trên sàn
TEN = {"tiktok": "TikTok", "shopee": "Shopee"}


LICH_CA = os.path.expanduser(os.environ.get("ORBIT_LICH_CA", "~/orbit-runtime/lich/ca.json"))


def nguoi_ca(luc=None, nhom="CSKH"):
    """[(tên, telegram id)] người đang trong ca `nhom` lúc `luc`; ngoài khung ca → ca kế tiếp trong ngày (sau 22h: ca 1 mai)."""
    luc = luc or datetime.now()
    try:
        d = json.load(open(LICH_CA))
    except Exception:
        return []
    khung = sorted(((int(v.split("-")[0]), int(v.split("-")[1]), k) for k, v in (d.get("khung", {}).get(nhom) or {}).items()))
    if not khung:
        return []
    ngay, ca = luc, None
    for a, b, k in khung:
        if a <= luc.hour < b:
            ca = k; break
    if not ca:
        sau = [k for a, b, k in khung if luc.hour < a]
        ca = sau[0] if sau else khung[0][2]
        if not sau:
            ngay = luc + timedelta(days=1)
    ten_ = (d.get("lich", {}).get(nhom, {}).get(ngay.strftime("%Y-%m-%d")) or {}).get(ca) or []
    ids = d.get("nguoi", {})
    return [(t, ids.get(t)) for t in dict.fromkeys(ten_)]


def tag_ca(luc=None):
    ds = nguoi_ca(luc)
    if not ds:
        return esc(str(TK.E.get("CSKH_TAG") or "").strip())
    return "📣 CSKH trong ca: " + _tag(ds)


# HẠN NỘI BỘ (CEO 14/11, phương án hậu mãi TikTok) — tính theo GIỜ LÀM 8h–22h kể từ lúc bot thấy lần đầu:
SLA_PHAN_HOI = 4     # yêu cầu chờ shop phản hồi → CSKH trong ca
SLA_KHO = 4          # sàn ghi kiện đã giao về shop → kho /hoan + ảnh
SLA_XAC_NHAN = 2     # kho /hoan "đúng hàng" → CSKH bấm xác nhận/hoàn trên sàn
GIO_LAM = (8, 22)
SAN_50, SAN_HET = 12, 4   # hạn sàn còn ≤12h = quá 50%; ≤4h = coi như quá hạn (kịp bấm)


def _dt(s):
    try:
        return datetime.strptime(str(s)[:16], "%Y-%m-%d %H:%M")
    except Exception:
        return None


def gio_lam(tu, den=None):
    """Số giờ làm (8h–22h) giữa 2 mốc."""
    den = den or datetime.now()
    h, d = 0.0, tu
    while d < den:
        a = d.replace(hour=GIO_LAM[0], minute=0, second=0, microsecond=0)
        b = d.replace(hour=GIO_LAM[1], minute=0, second=0, microsecond=0)
        h += max(0, (min(b, den) - max(a, d)).total_seconds()) / 3600
        d = (d + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return h


def muc_han(x, lan_dau):
    """0 trong hạn · 1 quá 50% hạn · 2 quá hạn — hạn = min(4h giờ làm nội bộ, hạn sàn)."""
    di = gio_lam(_dt(lan_dau) or datetime.now())
    g = gio_con(x)
    if di >= SLA_PHAN_HOI or (g is not None and g <= SAN_HET):
        return 2
    if di >= SLA_PHAN_HOI / 2 or (g is not None and g <= SAN_50):
        return 1
    return 0


def luc_kho(r, cu_luc):
    """Lúc kho /hoan: sổ giờ quét (ghi từ 14/11 khi /hoan) → đúng giờ; không có thì bảng 09 chỉ có ngày →
    ngày cũ hơn hôm nay coi như 22h hôm đó; hôm nay → lúc bot thấy lần đầu."""
    q = _dt((_doc(KHO_LUC).get(str(r.get("MVĐ") or "")) or ""))
    if q:
        return q
    n = str(r.get("Ngày") or "")[:10]
    t = _dt(cu_luc) or datetime.now()
    try:
        d = datetime.strptime(n, "%Y-%m-%d").replace(hour=GIO_LAM[1])
        return min(t, d) if d.date() < datetime.now().date() else t
    except Exception:
        return t


def _tag(ten_id):
    return ", ".join(f'<a href="tg://user?id={i}">{esc(t)}</a>' if i else f"<b>{esc(t)}</b>" for t, i in ten_id)


def tag_kho(luc=None):
    """Người KHO đang trong ca (ca.json nhóm "Kho"); không có lịch → env KHO_TAG."""
    ds = nguoi_ca(luc, nhom="Kho")
    return ("📣 Kho trong ca: " + _tag(ds)) if ds else esc(str(TK.E.get("KHO_TAG") or "").strip())


def tag_quan_ly(truong_ca=True):
    """Trưởng ca CSKH (ca.json "truong_ca" → {"CSKH": "Tên"} hoặc env TRUONG_CA_CSKH) + chủ shop (OWNER_TELE_ID)."""
    ds = []
    try:
        if not truong_ca:
            raise StopIteration
        d = json.load(open(LICH_CA))
        t = (d.get("truong_ca") or {}).get("CSKH")
        if t:
            ds.append((t, d.get("nguoi", {}).get(t)))
    except Exception:
        pass
    if truong_ca and not ds and TK.E.get("TRUONG_CA_CSKH"):
        ds.append((str(TK.E["TRUONG_CA_CSKH"]), None))
    if TK.E.get("OWNER_TELE_ID"):
        ds.append(("chủ shop", TK.E["OWNER_TELE_ID"]))
    return _tag(ds)


def doc_csv(f):
    return [dict(zip(COLS, (l.split("|") + [""] * 9)[:9])) for l in open(f, encoding="utf-8").read().splitlines() if l.strip()]


def gio_con(x):
    """Số giờ còn lại tới hạn: TikTok "1ngày6giờ" / Shopee "13-11-2026" (hết ngày đó). Không rõ → None."""
    h = x.get("han", "")
    if not h:
        return None
    m = re.fullmatch(r"(\d\d)-(\d\d)-(\d{4})", h)
    if m:
        het = datetime(int(m[3]), int(m[2]), int(m[1]), 23, 59)
        return (het - datetime.now()).total_seconds() / 3600
    n = lambda k: int((re.search(r"(\d+)\s*" + k, h) or [0, 0])[1])
    if not re.search(r"\d", h):
        return None
    return n("ngày") * 24 + n("giờ") + n("phút") / 60


def han_txt(x):
    g = gio_con(x)
    if g is None:
        return ""
    if g <= 24:
        return f" · ⏰ <b>còn {max(int(g), 0)}h</b>"
    return f" · hạn {esc(x['han'])}" if "-" in x["han"] else f" · còn {esc(x['han'])}"


def kho_09():
    out = []
    for r in TG.rows(TK.HOAN, fresh=True):
        blob = " ".join(str(v) for k, v in r.items() if not k.startswith("_")).lower()
        m = str(r.get("MVĐ") or "")
        o = (NH.don_theo_ma(m) or NH.don_theo_ma(m.split("-")[0])) if m and NH.meta() else None
        if m and NH.goc_hoan(m):   # tem hoàn đã tra ra đơn gốc (sổ ma_hoan)
            blob += " " + NH.goc_hoan(m).lower()
        if o:   # kiện kho quét → đơn Nhanh → mã đơn sàn (TikTok trả hàng dùng MVĐ hoàn khác MVĐ gửi)
            blob += " " + " ".join(str(o.get(k, "")) for k in ("ma_san", "mvd", "id")).lower()
        out.append((blob, r))
    return out


def tim_09(x, rows):
    keys = {x["ma"].lower()} | ({x["mvd"].lower()} if x.get("mvd") else set())
    o = NH.don_theo_ma(x["ma"]) if NH.meta() else None
    if o:
        keys |= {str(o.get("mvd", "")).lower(), str(o.get("id", "")).lower()} - {""}
    for blob, r in rows:
        if any(k and k in blob for k in keys):
            return r
    return None


def kho_txt(r):
    if not r:
        return "kho chưa quét /hoan"
    if not r.get("Người nhận"):
        return "kho chưa nhận (sàn đã báo hoàn)"
    tt = str(r.get("Tình trạng") or "")
    return ("✅ kho đã nhận, " if "✅" in tt or not tt else "⚠️ kho nhận: ") + esc(tt.replace("✅", "").strip() or "nguyên vẹn")


def loi(r):
    return bool(r and r.get("Người nhận") and r.get("Tình trạng") and "✅" not in str(r.get("Tình trạng")))


def dong(x, r, moi):
    return _dong(x, r, moi) + (f" · 📝 kho {esc((x['_xl'].get('xl_ten', '') + ' ').split(' ', 1)[1].strip())}" if x.get("_xl") else "") + {1: " · 🔺quá 50% hạn", 2: " · 🚨 <b>QUÁ HẠN</b>"}.get(x.get("_muc", 0), "")


def _dong(x, r, moi):
    loai = "Chỉ hoàn tiền" if "chỉ hoàn" in x["loai"].lower() else "Hoàn ngay" if "ngay" in x["loai"].lower() else "Trả hàng"
    tien = x["tien"] if x["tien"] not in ("", "0") else ""
    return (f"• <code>{esc(x['ma'])}</code> {loai} · {esc(x['ly_do'][:40])}" + (f" · {esc(tien)}" + ("" if "₫" in tien else "₫") if tien else "")
            + han_txt(x) + (f" · kiện: {esc(x['kv'])}" if x.get("kv") else "") + f" · {kho_txt(r)}" + (" 🆕" if moi else ""))


def sap_xep(xs):
    return sorted(xs, key=lambda x: (gio_con(x) if gio_con(x) is not None else 9999))


def bao(d):
    """d = {"luc", "tiktok": [...], "shopee": [...]} → (texts cho nhóm Đổi trả, text cho nhóm Kho, tóm tắt)."""
    try:
        cu = json.load(open(STATE))
    except Exception:
        cu = {}
    rows = kho_09()
    tag = tag_ca()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    moi_st, out, kho, tom, kho_tre, kho_dung, kho_kn = {}, [], [], [], [], [], []
    for k in ("tiktok", "shopee"):
        ds = d.get(k)
        if ds is None:
            out.append(f"❔ <b>{TEN[k]}</b>: không đọc được trang trả hàng/hoàn tiền — CSKH tự vào kiểm tra.")
            continue
        try:
            LDH.ghi_so(ds, k)      # sổ lý do sàn cho thống kê thứ 2
        except Exception as e:
            print("hoan_san: sổ lý do lỗi", e, file=sys.stderr)
        for x in ds:
            x["_r"] = tim_09(x, rows)
            x["_moi"] = x["ma"] not in cu
            c = cu.get(x["ma"]) or {}
            st = {"kenh": k, "nut": x["nut"], "lan_dau": c.get("lan_dau", now), "lan_cuoi": now,
                  "tt": x.get("tt", ""), "mvd": x.get("mvd", ""), "ly_do": x.get("ly_do", ""), "loai": x.get("loai", "")}
            if gio_con(x) is not None:
                st["han_gio"] = round(gio_con(x), 1)
            r = x["_r"]
            nhan = bool(r and r.get("Người nhận"))
            if x.get("kv") == "Đã giao" and not nhan:
                st["lan_ve"] = c.get("lan_ve", now)      # sàn ghi kiện đã về shop, kho chưa /hoan
            if nhan:
                st["lan_kho"] = c.get("lan_kho", now)
            moi_st[x["ma"]] = st
            x["_st"] = st
            x["_xl"] = da_xu_ly(x)     # kho đã bấm nút "Đã duyệt / Đã khiếu nại trên sàn" → tắt nhắc
            # hạn CSKH chỉ cho bước phản hồi; kiện kho đã nhận → việc của KHO (luồng chủ shop chốt 14/11)
            x["_muc"] = muc_han(x, st["lan_dau"]) if x["nut"] in CAN_XL and not nhan and not x["_xl"] else 0
            # kho /hoan ĐÚNG HÀNG mà sàn còn chờ shop → hạn 2h cho KHO bấm xác nhận trên sàn
            x["_dung"] = (gio_lam(luc_kho(r, st["lan_kho"])) if nhan and not loi(r) and x["nut"] in CAN_XL and not x["_xl"] else None)
            x["_kn"] = bool(loi(r) and not x["_xl"] and x["nut"] in CAN_XL | {"khang_nghi", "kiem_hang"})
            x["_kho_tre"] = gio_lam(_dt(st["lan_ve"])) if st.get("lan_ve") else 0
        can = sap_xep([x for x in ds if x["nut"] in CAN_XL])
        dang = sap_xep([x for x in ds if x["nut"] == "dang_tra"])
        sau = sap_xep([x for x in ds if x["nut"] in ("khang_nghi", "kiem_hang")])
        gap = [x for x in can if (g := gio_con(x)) is not None and g <= 24]
        xong = [m for m, v in cu.items() if v.get("kenh") == k and v.get("nut") in CAN_XL and m not in {x["ma"] for x in ds}]
        L = [f"💸 <b>{TEN[k].upper()} — HOÀN TIỀN / TRẢ HÀNG CẦN CSKH XỬ LÝ</b> {datetime.now():%d/%m} · đọc sàn {esc(d.get('luc', ''))}"]
        if tag:
            L.append(tag)
        if can:
            L.append(f"\n🔴 <b>{len(can)} yêu cầu chờ shop phản hồi</b>" + (f" · ⏰ <b>{len(gap)} hết hạn trong 24h</b>" if gap else "")
                     + (" (Seller Center › Trả hàng và hoàn tiền › Đang chờ bạn)" if k == "tiktok"
                        else " (Kênh người bán › Trả hàng/Hoàn tiền › Kiểm tra hàng hoàn)"))
            L += [dong(x, x["_r"], x["_moi"]) for x in can[:25]]
            if len(can) > 25:
                L.append(f"… +{len(can) - 25} yêu cầu nữa")
            qh = [x for x in can if x["_muc"] == 2]
            nua = [x for x in can if x["_muc"] == 1]
            if qh:
                L.append(f"🚨 <b>{len(qh)} yêu cầu QUÁ HẠN</b> (quá {SLA_PHAN_HOI}h giờ làm hoặc hạn sàn còn ≤{SAN_HET}h)"
                         + (f" → {tag_quan_ly()}" if tag_quan_ly() else ""))
            if nua:
                L.append(f"🔺 {len(nua)} yêu cầu đã quá 50% hạn" + (f" → {tag}" if tag else ""))
            L.append("→ CSKH: phản hồi yêu cầu mới ≤4h. Kiện đã về kho: <b>KHO</b> kiểm và bấm xác nhận / khiếu nại trên sàn "
                     "(bot nhắc nhóm Kho), CSKH không bấm bước này.")
        dung = sorted((x for x in can if x["_dung"] is not None and x["_dung"] >= SLA_XAC_NHAN), key=lambda x: -x["_dung"])
        if dung:
            kho_dung.append(f"• <b>{TEN[k]}</b>: " + ", ".join(
                f"<code>{esc(x['_r'].get('MVĐ') or x['mvd'] or x['ma'])}</code> (đơn {esc(x['ma'])}, đã {int(x['_dung'])}h){han_txt(x)}" for x in dung[:15]))
        kn = [x for x in can + sau if x["_kn"]]
        if kn:
            kho_kn.append(f"• <b>{TEN[k]}</b>: " + ", ".join(
                f"<code>{esc(x['mvd'] or x['ma'])}</code> ({esc(str(x['_r'].get('Tình trạng', ''))[:25])}){han_txt(x)}" for x in kn[:15]))
        if dang:
            L.append(f"\n🚚 {len(dang)} người mua đang gửi trả (kiện chưa về kho): "
                     + ", ".join(f"<code>{esc(x['ma'])}</code>{han_txt(x)}" for x in dang[:12]))
        if sau:
            l_ = [x for x in sau if loi(x["_r"])]
            ve = [x for x in sau if x.get("kv") in ("Đã giao",) and not (x["_r"] and x["_r"].get("Người nhận"))]
            L.append(f"\n🟡 {len(sau)} đơn sàn đã hoàn tiền cho khách"
                     + (" — còn kháng nghị được nếu kiện về sai/thiếu/lỗi" if k == "tiktok" else
                        " (đơn huỷ/giao thất bại/trả hàng quay về) — kiểm hàng, sai thì khiếu nại"))
            if l_:
                L.append(f"   ⚠️ Kho kiểm thấy lỗi → kho {'kháng nghị' if k == 'tiktok' else 'khiếu nại'} trên sàn (CSKH theo dõi):\n"
                         + "\n".join(dong(x, x["_r"], False) for x in l_[:15]))
            if ve:
                L.append(f"   📦 {len(ve)} kiện sàn ghi đã giao về shop mà kho chưa quét <code>/hoan</code>: "
                         + ", ".join(f"<code>{esc(x['mvd'] or x['ma'])}</code>{han_txt(x)}" for x in ve[:12]))
        if xong:
            L.append(f"\n✅ {len(xong)} yêu cầu đã xử lý từ lần đọc trước.")
        if not (can or dang or sau):
            L.append("Không có yêu cầu nào đang chờ shop 🎉")
        out.append("\n".join(L))
        # nhóm Kho: kiện cần kiểm gấp (CSKH đang chờ) mà kho chưa quét
        ck = [x for x in can + sau if x.get("kv") in ("Đã giao",) and not (x["_r"] and x["_r"].get("Người nhận"))]
        if ck:
            kho.append(f"• <b>{TEN[k]}</b> {len(ck)} kiện: " + ", ".join(
                f"<code>{esc(x['mvd'] or x['ma'])}</code>{han_txt(x)}"
                + (f" · 🚨 về {int(x['_kho_tre'])}h chưa /hoan" if x["_kho_tre"] >= SLA_KHO else "")
                for x in sorted(ck, key=lambda x: -x["_kho_tre"])[:20]))
            tre = [x for x in ck if x["_kho_tre"] >= SLA_KHO]
            if tre:
                kho_tre.append(len(tre))
        tom.append(f"{TEN[k]}: {len(can)} cần phản hồi ({len(gap)} ≤24h, {sum(x['_muc'] == 2 for x in can)} quá hạn), "
                   f"{len(dang)} đang gửi trả, {len(sau)} đã hoàn")
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(moi_st, open(STATE, "w"), ensure_ascii=False, indent=1)
    kt = ""
    if kho_dung or kho_kn:
        tk_ = tag_kho()
        kt += ((f"⏱ <b>KHO ĐÃ /hoan ĐÚNG HÀNG quá {SLA_XAC_NHAN}h mà sàn chưa xác nhận</b> — vào sàn bấm xác nhận nhận hàng / đồng ý hoàn, "
                "xong bấm nút ✅ ở tin đối chiếu (hoặc /hoan lại tem để lấy nút)" + (f" · {tk_}" if tk_ else "")
                + (f" · 🚨 quá hạn → {tag_quan_ly(False)}" if tag_quan_ly(False) else "") + ":\n" + "\n".join(kho_dung) + "\n\n")
               if kho_dung else "")
        kt += (("⚠️ <b>Kho ghi lỗi/tráo/thiếu mà chưa bấm Khiếu nại trên sàn</b> — khiếu nại/kháng nghị kèm video mở kiện + video đóng gói"
                + (f" · {tk_}" if tk_ else "") + ":\n" + "\n".join(kho_kn) + "\n\n") if kho_kn else "")
    if kho:
        kt += ("↩️ <b>KIỆN HOÀN CSKH ĐANG CHỜ KIỂM</b> — sàn ghi đã giao về shop, kho chưa quét. Tìm kiện, kiểm rồi "
              "<code>/hoan MVĐ</code> + ảnh, ghi rõ <i>đúng hàng, còn tag</i> hoặc lỗi gì — hạn ≤4h trong giờ làm, không để qua đêm:\n"
              + "\n".join(kho)
              + (f"\n🚨 <b>{sum(kho_tre)} kiện đã quá {SLA_KHO}h</b> chưa /hoan → CSKH đang kẹt bước \"kiểm tra mặt hàng\"." if kho_tre else ""))
    return out, kt, "; ".join(tom)


# ======================= /hoan → đối chiếu sàn (chủ shop chốt 14/11: KHO bấm duyệt/khiếu nại trên sàn) =======================
# Kho quét /hoan <tem> → bot tìm yêu cầu trả hàng trên sàn (sổ đọc sàn gần nhất + API trả hàng Nhanh) → báo KHỚP/LỆCH
# + nút [Đã duyệt trên sàn] [Đã khiếu nại]. Kho bấm TRÊN SÀN trước rồi mới bấm nút để bot ghi 09 + tắt nhắc.
# Bot CHỈ ĐỌC sàn, không tự bấm. Chưa thấy trên sàn → sổ chờ, lượt đọc sàn sau tự báo lại nhóm Kho.
XU_LY = os.path.join(KF.ROOT, "logs", "hoan_xu_ly.json")
KHO_LUC = os.path.join(KF.ROOT, "logs", "hoan_kho_luc.json")   # tem → giờ kho quét /hoan (bảng 09 chỉ có ngày)
CHO = os.path.join(KF.ROOT, "logs", "hoan_cho_san.json")
TEN_XL = {"d": "✅ đã duyệt trên sàn", "k": "⚠️ đã khiếu nại trên sàn"}


def xl_txt(xl):
    return TEN_XL.get(xl, xl).split(" ", 1)[-1]


def _doc(f):
    try:
        return json.load(open(f))
    except Exception:
        return {}


def _ghi(f, obj):
    os.makedirs(os.path.dirname(f), exist_ok=True)
    json.dump(obj, open(f + ".tmp", "w"), ensure_ascii=False, indent=1)
    os.replace(f + ".tmp", f)


def xu_ly():
    return _doc(XU_LY)


def da_xu_ly(x):
    """Yêu cầu sàn x (dict có ma, mvd) đã được kho bấm duyệt/khiếu nại? → bản ghi hoặc None."""
    xl = xu_ly()
    ks = {str(x.get("ma", "")).lower(), str(x.get("mvd", "")).lower()} - {""}
    return next((v for t, v in xl.items() if t.lower() in ks or str(v.get("ma", "")).lower() in ks), None)


def tim_yc(tem):
    """tem kho quét → (mã đơn sàn, bản ghi sổ đọc sàn hoặc None, đơn Nhanh, sp khách trả, tra trả hàng)."""
    o, sp = TK.sp_don(tem)
    tra = (o or {}).get("tra_sau_giao") or {}
    ma = tra.get("ma_san") or NH.goc_hoan(tem) or (o or {}).get("ma_san") or ""
    if ma.endswith("R") and NH.don_theo_ma(ma[:-1]):
        ma = ma[:-1]
    ks = {tem.lower(), NH.chuan_ma(tem)} | ({ma.lower()} if ma else set()) | ({str(o["id"]).lower()} if o else set())
    st = _doc(STATE)
    e = next(((k, v) for k, v in st.items() if k.lower() in ks or str(v.get("mvd", "")).lower() in ks), None)
    if e and not ma:
        ma = e[0]
    return ma, (dict(e[1], ma=e[0]) if e else None), o, sp, tra


def luc_doc_san():
    ls = [v.get("lan_cuoi", "") for v in _doc(STATE).values()]
    return max(ls) if ls else ""


def doi_chieu(tem):
    """→ {"kq": khop|lech|dvvc|chua|xong, "ma", "dong"} — 1 dòng HTML cho nhóm Kho."""
    ma, e, o, sp, tra = tim_yc(tem)
    xl = xu_ly().get(tem) or (da_xu_ly(e) if e else None)
    if xl:
        return {"kq": "xong", "ma": ma, "dong": f"• <code>{esc(tem)}</code>: {esc(xl.get('xl_ten', ''))} ({esc(xl.get('who'))} {esc(xl.get('luc', '')[11:])})"}
    kenh = TEN.get((e or {}).get("kenh") or tra.get("kenh") or "", "")
    if not e and not tra:
        if o and o.get("st") in NH.HOAN_ST:
            return {"kq": "dvvc", "ma": ma, "dong": f"• <code>{esc(tem)}</code> 📦 hoàn ĐVVC/giao thất bại (Nhanh: {esc(o.get('st_ten'))}), "
                                                  f"không có yêu cầu trả hàng trên sàn — kiểm đủ: {esc(sp.split(' ‖ ')[0][:120])}"}
        return {"kq": "chua", "ma": ma, "dong": f"• <code>{esc(tem)}</code> ❔ chưa có trong lần đọc sàn {esc(luc_doc_san()[5:] or '—')}"
                                              + (f" (Nhanh: đơn {esc(ma)})" if ma else "") + " — bot kiểm lại lượt đọc sàn sau"}
    lech = []
    if tra.get("chua_ghep"):
        lech.append("món khách trả trên sàn không khớp đơn gốc: " + ", ".join(tra["chua_ghep"])[:120])
    nut = (e or {}).get("nut", "")
    han = ""
    if e and e.get("han_gio") is not None:
        con = e["han_gio"] - ((datetime.now() - (_dt(e.get("lan_cuoi")) or datetime.now())).total_seconds() / 3600)
        han = f" · ⏰ <b>hạn còn {max(int(con), 0)}h</b>" if con <= 24 else f" · hạn còn {int(con)}h"
    tt = (e or {}).get("tt") or tra.get("tt_san") or ""
    ghi = ""
    if nut in ("khang_nghi", "kiem_hang"):
        ghi = " · sàn ĐÃ hoàn tiền cho khách → đúng hàng thì bấm Đã duyệt (không cần làm gì trên sàn), sai/thiếu thì kháng nghị/khiếu nại"
    elif nut == "dang_tra":
        ghi = " · sàn chưa ghi kiện về shop — nút xác nhận có thể chưa hiện, lượt sau bot báo lại"
    sp_ = sp.split(" ‖ ")[0][:140] if sp else "(chưa đọc được món khách trả)"
    dau = "⚠️ <b>LỆCH</b>: " + "; ".join(lech) + " — gợi ý khiếu nại" if lech else "✅ <b>KHỚP sàn</b>"
    return {"kq": "lech" if lech else "khop", "ma": ma,
            "dong": f"• <code>{esc(tem)}</code> {dau}: đơn {kenh} <code>{esc(ma)}</code> · {esc(sp_)}{han}"
                    + (f" · {esc(tt[:40])}" if tt else "") + (f" · lý do khách: {esc(((e or {}).get('ly_do') or tra.get('ly_do') or '')[:40])}"
                                                            if ((e or {}).get("ly_do") or tra.get("ly_do")) else "") + ghi}


HD_SAN = ("→ <b>Kho làm trên sàn</b>: đúng hàng, còn tag → bấm <b>xác nhận nhận hàng / đồng ý hoàn</b>. Sai/tráo/thiếu/đã dùng/mất tag → "
          "bấm <b>Khiếu nại / Kháng nghị</b> kèm video mở kiện + video đóng gói. Bấm trên sàn XONG rồi mới bấm nút dưới.")


def nut(tems):
    return [[{"text": f"✅ Đã duyệt {t[-6:]}", "callback_data": f"hs:d:{t}"[:64]},
             {"text": f"⚠️ Khiếu nại {t[-6:]}", "callback_data": f"hs:k:{t}"[:64]}] for t in tems[:8]]


def gui_doi_chieu(chat, mas, reply_to=None):
    """Gọi sau /hoan (ticket.cmd_hoan): báo nhóm Kho kết quả đối chiếu sàn từng tem."""
    kq = [(t, doi_chieu(t)) for t in mas]
    if not kq:
        return
    kl, bg = _doc(KHO_LUC), datetime.now().strftime("%Y-%m-%d %H:%M")
    for t in mas:
        kl.setdefault(t, bg)
    _ghi(KHO_LUC, kl)
    cho = _doc(CHO)
    for t, k in kq:
        if k["kq"] == "chua":
            cho.setdefault(t, {"chat": str(chat), "luc": datetime.now().strftime("%Y-%m-%d %H:%M"), "lan": 0})
    _ghi(CHO, cho)
    co_nut = [t for t, k in kq if k["kq"] in ("khop", "lech")]
    text = (f"🔎 <b>ĐỐI CHIẾU SÀN</b> (đọc sàn {esc(luc_doc_san()[5:] or 'chưa có')})\n" + "\n".join(k["dong"] for _, k in kq)
            + ("\n" + HD_SAN if co_nut else ""))
    tsend(chat, text, nut(co_nut) or None, reply_to=reply_to)


def kiem_lai_cho(send=False):
    """Sau mỗi lượt đọc sàn: tem kho đã /hoan mà lần trước chưa thấy trên sàn → đối chiếu lại, thấy thì báo nhóm Kho."""
    cho, con, ra = _doc(CHO), {}, []
    for t, v in cho.items():
        k = doi_chieu(t)
        if k["kq"] == "chua":
            v["lan"] = v.get("lan", 0) + 1
            if v["lan"] < 6:      # ~3 ngày đọc sàn 2 lượt/ngày; quá thì thôi (đối soát hoàn 9h/17h vẫn liệt kê)
                con[t] = v
        else:
            ra.append((t, v, k))
    _ghi(CHO, con)
    if not ra:
        return ""
    co_nut = [t for t, _, k in ra if k["kq"] in ("khop", "lech")]
    text = ("🔎 <b>ĐỐI CHIẾU SÀN — tem kho /hoan lần trước chưa thấy, nay sàn đã có</b>\n" + "\n".join(k["dong"] for _, _, k in ra)
            + ("\n" + HD_SAN if co_nut else ""))
    print(re.sub(r"<[^>]+>", "", text))
    if send and KF.kchat():
        tsend(KF.kchat(), text, nut(co_nut) or None)
    return text


def on_cb(cq, p):
    """hs:d:<tem> / hs:k:<tem> — kho báo đã bấm duyệt / khiếu nại trên sàn."""
    u = cq["from"]
    if not TK.is_member(u["id"]):
        return TK.answer(cq, "Bạn chưa ở nhóm kho / đổi trả", True)
    xl, tem = p[1], ":".join(p[2:])
    who = TK.ten(u)
    ma = tim_yc(tem)[0]
    luc = datetime.now().strftime("%Y-%m-%d %H:%M")
    d = xu_ly()
    d[tem] = {"xl": xl, "xl_ten": TEN_XL.get(xl, xl), "who": who, "luc": luc, "ma": ma}
    _ghi(XU_LY, d)
    try:
        for r in TG.rows(TK.HOAN, fresh=True):
            if str(r.get("MVĐ", "")).lower() == tem.lower():
                g = str(r.get("Ghi chú") or "")
                TG.kho("update", table=TG.sname(TK.HOAN), id=r["_id"],
                       fields={"Ghi chú": (g + " · " if g else "") + f"Sàn: kho {xl_txt(xl)} {luc[5:]} {who}"})
                TG._CACHE.pop(TG.sname(TK.HOAN), None)
                break
    except Exception as e:
        print("hoan_san: ghi 09 lỗi", e, flush=True)
    TK.answer(cq, TEN_XL.get(xl, xl))
    msg = cq["message"]
    kb = [row for row in ((msg.get("reply_markup") or {}).get("inline_keyboard") or [])
          if not any(str(b.get("callback_data", "")).endswith(":" + tem) for b in row)]
    try:
        TG.api("editMessageReplyMarkup", {"chat_id": msg["chat"]["id"], "message_id": msg["message_id"],
                                          "reply_markup": {"inline_keyboard": kb}})
    except Exception:
        pass
    tsend(msg["chat"]["id"], f"📝 <code>{esc(tem)}</code>" + (f" (đơn <code>{esc(ma)}</code>)" if ma else "")
          + f": {esc(who)} {xl_txt(xl)} — đã ghi bảng 09, bot tắt nhắc." + (
              "\nNhớ đính kèm video mở kiện + video đóng gói trên sàn." if xl == "k" else ""), reply_to=msg["message_id"])


TK.EXT_CB["hs"] = on_cb


def chay(d, send=False):
    out, kt, tom = bao(d)
    for t in out:
        print(re.sub(r"<[^>]+>", "", t), "\n")
    if kt:
        print(re.sub(r"<[^>]+>", "", kt))
    if send:
        if TK.tchat():
            for t in out:
                tsend(TK.tchat(), t)
        if kt and KF.kchat():
            tsend(KF.kchat(), kt)
    try:
        kiem_lai_cho(send)      # tem kho /hoan lần trước chưa thấy trên sàn → đối chiếu lại
    except Exception as e:
        print("hoan_san: kiểm lại tem chờ lỗi", e, file=sys.stderr)
    return tom


def cli(a):
    opt = {a[i]: a[i + 1] for i in range(len(a) - 1) if a[i].startswith("--") and not a[i + 1].startswith("--")}
    d = {"luc": datetime.now().strftime("%H:%M")}
    for k in ("tiktok", "shopee"):
        f = opt.get("--" + k)
        if f and os.path.exists(f):
            d[k] = doc_csv(f)
    print("TÓM TẮT:", chay(d, "--send" in a))


if __name__ == "__main__":
    import lark as Lk
    TK.init(Lk.load_env(), start_worker=False)
    if len(sys.argv) < 2:
        print(__doc__)
    else:
        cli(sys.argv[1:])
