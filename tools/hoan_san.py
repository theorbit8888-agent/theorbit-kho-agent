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
    """Lúc kho /hoan: bảng 09 chỉ có ngày → ngày cũ hơn hôm nay coi như 22h hôm đó; hôm nay → lúc bot thấy lần đầu."""
    n = str(r.get("Ngày") or "")[:10]
    t = _dt(cu_luc) or datetime.now()
    try:
        d = datetime.strptime(n, "%Y-%m-%d").replace(hour=GIO_LAM[1])
        return min(t, d) if d.date() < datetime.now().date() else t
    except Exception:
        return t


def _tag(ten_id):
    return ", ".join(f'<a href="tg://user?id={i}">{esc(t)}</a>' if i else f"<b>{esc(t)}</b>" for t, i in ten_id)


def tag_quan_ly():
    """Trưởng ca CSKH (ca.json "truong_ca" → {"CSKH": "Tên"} hoặc env TRUONG_CA_CSKH) + chủ shop (OWNER_TELE_ID)."""
    ds = []
    try:
        d = json.load(open(LICH_CA))
        t = (d.get("truong_ca") or {}).get("CSKH")
        if t:
            ds.append((t, d.get("nguoi", {}).get(t)))
    except Exception:
        pass
    if not ds and TK.E.get("TRUONG_CA_CSKH"):
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
    return _dong(x, r, moi) + {1: " · 🔺quá 50% hạn", 2: " · 🚨 <b>QUÁ HẠN</b>"}.get(x.get("_muc", 0), "")


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
    moi_st, out, kho, tom, kho_tre = {}, [], [], [], []
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
            st = {"kenh": k, "nut": x["nut"], "lan_dau": c.get("lan_dau", now), "lan_cuoi": now}
            r = x["_r"]
            nhan = bool(r and r.get("Người nhận"))
            if x.get("kv") == "Đã giao" and not nhan:
                st["lan_ve"] = c.get("lan_ve", now)      # sàn ghi kiện đã về shop, kho chưa /hoan
            if nhan:
                st["lan_kho"] = c.get("lan_kho", now)
            moi_st[x["ma"]] = st
            x["_st"] = st
            x["_muc"] = muc_han(x, st["lan_dau"]) if x["nut"] in CAN_XL else 0
            # kho /hoan ĐÚNG HÀNG mà sàn còn chờ shop → hạn 2h cho CSKH bấm
            x["_dung"] = (gio_lam(luc_kho(r, st["lan_kho"])) if nhan and not loi(r) and x["nut"] in CAN_XL else None)
            if x["_dung"] is not None and x["_dung"] >= SLA_XAC_NHAN:
                x["_muc"] = 2
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
            L.append("→ Kiện đã về + kho ghi ✅ nguyên vẹn: đồng ý hoàn. Kho ghi ⚠️ sai/thiếu/lỗi: từ chối/khiếu nại kèm ảnh kho. "
                     "Kiện chưa về: chờ kho quét <code>/hoan</code>, sát hạn thì hỏi kho ngay.")
        dung = sorted((x for x in can if x["_dung"] is not None and x["_dung"] >= SLA_XAC_NHAN), key=lambda x: -x["_dung"])
        if dung:
            L.append(f"\n⏱ <b>{len(dung)} ca kho đã /hoan ĐÚNG HÀNG quá {SLA_XAC_NHAN}h mà sàn chưa xác nhận</b> — "
                     "vào sàn bấm xác nhận nhận hàng/hoàn tiền ngay" + (f" · {tag}" if tag else "") + ":\n"
                     + "\n".join(f"• <code>{esc(x['ma'])}</code> · {kho_txt(x['_r'])} · đã {int(x['_dung'])}h giờ làm"
                                 for x in dung[:20]))
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
                L.append(f"   ⚠️ <b>Kho kiểm thấy lỗi → {'kháng nghị' if k == 'tiktok' else 'khiếu nại'} ngay</b>:\n"
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
    if kho:
        kt = ("↩️ <b>KIỆN HOÀN CSKH ĐANG CHỜ KIỂM</b> — sàn ghi đã giao về shop, kho chưa quét. Tìm kiện, kiểm rồi "
              "<code>/hoan MVĐ</code> + ảnh, ghi rõ <i>đúng hàng, còn tag</i> hoặc lỗi gì — hạn ≤4h trong giờ làm, không để qua đêm:\n"
              + "\n".join(kho)
              + (f"\n🚨 <b>{sum(kho_tre)} kiện đã quá {SLA_KHO}h</b> chưa /hoan → CSKH đang kẹt bước \"kiểm tra mặt hàng\"." if kho_tre else ""))
    return out, kt, "; ".join(tom)


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
