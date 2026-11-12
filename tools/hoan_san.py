#!/usr/bin/env python3
"""YÊU CẦU HOÀN TIỀN / TRẢ HÀNG trên TikTok Shop + Shopee → báo nhóm Đổi trả CS-Kho cho CSKH xử lý.

Bot CHỈ ĐỌC + NHẮC, không bấm duyệt/từ chối (việc của người được giao, xem SOP).
Tác vụ lịch (Claude in Chrome của chủ shop) chạy tools/doc_san.js → __docHoanTikTok / __docHoanShopee → CSV, rồi:
  python3 tools/hoan_san.py --tiktok tt.csv --shopee sp.csv [--tong-tiktok N] [--tong-shopee N] [--send]
CSV mỗi dòng: ma|loai|ly_do|tt|han|kv|tien|nut|mvd   (thiếu file sàn nào = không đọc được sàn đó)
Đối chiếu bảng 09 · HÀNG HOÀN NHẬN: kiện kho đã nhận chưa + tình trạng → CSKH biết đồng ý hoàn hay khiếu nại/kháng nghị.
Tag CSKH: CSKH_TAG trong ~/.config/orbit-kho/lark.env (VD "@mai_cs @lan_cs").
"""
import json, os, re, sys
from datetime import datetime, timedelta

import orbit_tg as TG
import ticket as TK
import nhanh as NH
import kho_flow as KF

esc, tsend = TK.esc, TK.tsend
STATE = os.path.join(KF.ROOT, "logs", "hoan_san.json")
COLS = ("ma", "loai", "ly_do", "tt", "han", "kv", "tien", "nut", "mvd")
CAN_XL = {"phan_hoi", "xac_nhan", "bang_chung"}     # shop phải bấm trên sàn
TEN = {"tiktok": "TikTok", "shopee": "Shopee"}


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
        return "kho chưa nhận"
    if not r.get("Người nhận"):
        return "kho chưa nhận (sàn đã báo hoàn)"
    tt = str(r.get("Tình trạng") or "")
    return ("✅ kho đã nhận, " if "✅" in tt or not tt else "⚠️ kho nhận: ") + esc(tt.replace("✅", "").strip() or "nguyên vẹn")


def loi(r):
    return bool(r and r.get("Người nhận") and r.get("Tình trạng") and "✅" not in str(r.get("Tình trạng")))


def dong(x, r, moi):
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
    tag = str(TK.E.get("CSKH_TAG") or "").strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    moi_st, out, kho, tom = {}, [], [], []
    for k in ("tiktok", "shopee"):
        ds = d.get(k)
        if ds is None:
            out.append(f"❔ <b>{TEN[k]}</b>: không đọc được trang trả hàng/hoàn tiền — CSKH tự vào kiểm tra.")
            continue
        for x in ds:
            x["_r"] = tim_09(x, rows)
            x["_moi"] = x["ma"] not in cu
            moi_st[x["ma"]] = {"kenh": k, "nut": x["nut"], "lan_dau": (cu.get(x["ma"]) or {}).get("lan_dau", now), "lan_cuoi": now}
        can = sap_xep([x for x in ds if x["nut"] in CAN_XL])
        dang = sap_xep([x for x in ds if x["nut"] == "dang_tra"])
        sau = sap_xep([x for x in ds if x["nut"] in ("khang_nghi", "kiem_hang")])
        gap = [x for x in can if (g := gio_con(x)) is not None and g <= 24]
        xong = [m for m, v in cu.items() if v.get("kenh") == k and v.get("nut") in CAN_XL and m not in {x["ma"] for x in ds}]
        L = [f"💸 <b>{TEN[k].upper()} — HOÀN TIỀN / TRẢ HÀNG CẦN CSKH XỬ LÝ</b> {datetime.now():%d/%m} · đọc sàn {esc(d.get('luc', ''))}"]
        if tag:
            L.append(esc(tag))
        if can:
            L.append(f"\n🔴 <b>{len(can)} yêu cầu chờ shop phản hồi</b>" + (f" · ⏰ <b>{len(gap)} hết hạn trong 24h</b>" if gap else "")
                     + (" (Seller Center › Trả hàng và hoàn tiền › Đang chờ bạn)" if k == "tiktok"
                        else " (Kênh người bán › Trả hàng/Hoàn tiền › Kiểm tra hàng hoàn)"))
            L += [dong(x, x["_r"], x["_moi"]) for x in can[:25]]
            if len(can) > 25:
                L.append(f"… +{len(can) - 25} yêu cầu nữa")
            L.append("→ Kiện đã về + kho ghi ✅ nguyên vẹn: đồng ý hoàn. Kho ghi ⚠️ sai/thiếu/lỗi: từ chối/khiếu nại kèm ảnh kho. "
                     "Kiện chưa về: chờ kho quét <code>/hoan</code>, sát hạn thì hỏi kho ngay.")
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
                f"<code>{esc(x['mvd'] or x['ma'])}</code>{han_txt(x)}" for x in sap_xep(ck)[:20]))
        tom.append(f"{TEN[k]}: {len(can)} cần phản hồi ({len(gap)} ≤24h), {len(dang)} đang gửi trả, {len(sau)} đã hoàn")
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(moi_st, open(STATE, "w"), ensure_ascii=False, indent=1)
    kt = ""
    if kho:
        kt = ("↩️ <b>KIỆN HOÀN CSKH ĐANG CHỜ KIỂM</b> — sàn ghi đã giao về shop, kho chưa quét. Tìm kiện, kiểm rồi "
              "<code>/hoan MVĐ</code> (lỗi/thiếu thì chụp ảnh) để CSKH duyệt/khiếu nại kịp hạn:\n" + "\n".join(kho))
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
