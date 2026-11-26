#!/usr/bin/env python3
"""NHẬN HÀNG CHUYỂN KHO (chủ yếu Q2 → cửa hàng PN) — nối Telegram với phiếu chuyển kho trên Nhanh.

Trên Nhanh 1 phiếu chuyển kho (yêu cầu #N) = phiếu XUẤT ở kho gửi (type 2, mode 3) → hàng đang đi →
phiếu NHẬP ở kho nhận (type 1, mode 3, cùng requirementBillId) khi người nhận bấm nhận trên Nhanh.
Open API chỉ ĐỌC được 2 phiếu này (không có lệnh "nhận hàng chuyển kho") → bot làm cầu nối:
  1. Kho gửi xuất trên Nhanh → ≤3 phút bot gửi thẻ vào nhóm kho NHẬN (PN = CS & Cửa hàng, Q2 = Kho), tag NVBH ca
  2. Hàng tới, đếm: ✅ Nhận đủ  |  ❌ Thiếu / lỗi → trả lời "số thứ tự  số thật" (hoặc "SKU số thật")
  3. Bot nhắc bấm nhận trên Nhanh → thấy phiếu nhập → sửa thẻ "Nhanh đã nhận", so số Nhanh nhập với số đếm trên Tele;
     lệch → báo nhóm + tag quản lý. Nhận Tele mà 30 phút Nhanh chưa nhận → nhắc 1 lần; thẻ treo 3 tiếng → nhắc.
  python3 tools/chuyen_kho.py xem           # in phiếu chuyển đang đi / mới nhận (không gửi)
  python3 tools/chuyen_kho.py quet --send   # lượt 3 phút (nhanh.py sync --nhanh)
"""
import fcntl, json, os, re, sys, time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticket as TK  # noqa: E402

esc, tsend, tedit, answer, ten = TK.esc, TK.tsend, TK.tedit, TK.answer, TK.ten
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
STATE_F = os.path.join(ROOT, "logs", "chuyen_kho.json")
TEN = {"205577": "Q2", "206425": "PN"}
NHOM = {"206425": "CH_CHAT_ID", "205577": "CHAT_ID"}   # kho nhận → nhóm Telegram
TU_NGAY = "2026-11-21"   # phiếu xuất chuyển kho từ ngày này (không gửi lại phiếu cũ đã nhận xong)


def now():
    return datetime.now()


class _Khoa:
    def __enter__(self):
        os.makedirs(os.path.dirname(STATE_F), exist_ok=True)
        self.f = open(STATE_F + ".khoa", "w"); fcntl.flock(self.f, fcntl.LOCK_EX); return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN); self.f.close()


def st_doc():
    try:
        return json.load(open(STATE_F))
    except Exception:
        return {}


def st_ghi(st):
    tmp = STATE_F + ".tmp"
    json.dump(st, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_F)


def _sp(b):
    d = {}
    for p in b.get("products") or []:
        d[p["code"]] = d.get(p["code"], 0) + int(p.get("quantity") or 0)
    return d


def doc_nhanh(ngay=7):
    """(xuất, nhập) phiếu chuyển kho mode 3 trong `ngay` ngày → {req: bill}."""
    import nhanh_api as NA
    tu, den = (now() - timedelta(days=ngay)).strftime("%Y-%m-%d"), now().strftime("%Y-%m-%d")
    out = []
    for typ in (2, 1):
        d = {}
        for b in NA.tat_ca("bill/list", {"fromDate": tu, "toDate": den, "type": typ, "modes": [3]}, toi_da=10, sort=False):
            if b.get("requirementBillId"):
                d[str(b["requirementBillId"])] = b
        out.append(d)
    return out


def ql_tag():
    try:
        import kho_flow as KF
        return KF.ql_tag()
    except Exception:
        return "quản lý"


def tag_ca(den):
    if den != "206425":
        return ""
    try:
        import cua_hang as CH
        return CH.tag(CH.nvbh_ca())
    except Exception:
        return ""


def the_text(x):
    tong = sum(x["sp"].values())
    L = [f"🚚 <b>HÀNG {TEN.get(x['tu'], x['tu'])} CHUYỂN QUA {TEN.get(x['den'], x['den'])}</b> — phiếu chuyển #{esc(x['req'])}",
         f"{esc(x['nguoi'])} xuất trên Nhanh {esc(x['luc'])} · <b>{tong} cái / {len(x['sp'])} mã</b>"]
    thieu = (x.get("nhan") or {}).get("thieu") or {}
    for i, (s, n) in enumerate(x["sp"].items(), 1):
        k = thieu.get(s)
        L.append(f"{i}. {esc(s)} × {n}" + (f" → <b>thật {k}</b> ({k - n:+d})" if k is not None and k != n else ""))
    nh = x.get("nhan")
    if nh:
        L.append(("\n✅ <b>Đã nhận đủ</b>" if not thieu else f"\n⚠️ <b>Nhận thiếu/lỗi {len(thieu)} mã</b>")
                 + f" — {esc(nh['who'])} {esc(nh['luc'])}")
    nb = x.get("nhap")
    if nb:
        L.append(f"🟢 <b>Nhanh đã nhận</b> (phiếu nhập #{esc(nb['bill'])}, {esc(nb['who'])} {esc(nb['luc'])})"
                 + (" — khớp số đếm" if not nb.get("lech") else f" — <b>lệch {len(nb['lech'])} mã so với đếm</b>"))
    elif nh:
        L.append("👉 Vào Nhanh <b>bấm nhận phiếu chuyển kho #" + esc(x["req"]) + "</b>"
                 + (" (sửa số theo thực tế)" if thieu else "") + " — bot tự kiểm lại.")
    else:
        L.append("\nHàng tới: đếm từng mã → đủ bấm ✅, thiếu/lỗi bấm ❌ rồi trả lời số thật.")
    return "\n".join(L)


def the_btn(x):
    if x.get("nhan") or x.get("nhap"):
        return None
    r = x["req"]
    return [[{"text": "✅ Nhận đủ", "callback_data": f"kc:ok:{r}"}, {"text": "❌ Thiếu / lỗi", "callback_data": f"kc:x:{r}"}]]


def _lech(x, nhap_sp):
    """So Nhanh nhập với số đếm Tele (chưa đếm → so với số xuất)."""
    dem = dict(x["sp"]); dem.update((x.get("nhan") or {}).get("thieu") or {})
    return {s: [dem.get(s, 0), nhap_sp.get(s, 0)] for s in set(dem) | set(nhap_sp) if dem.get(s, 0) != nhap_sp.get(s, 0)}


def quet(send=False):
    xuat, nhap = doc_nhanh()
    out = []
    with _Khoa():
        st = st_doc()
        for req, b in xuat.items():
            den = str((b.get("related") or {}).get("depotId") or "")
            if req in st or b.get("date", "") < TU_NGAY or den not in NHOM:
                continue
            x = {"req": req, "tu": str(b["depotId"]), "den": den, "xuat": b["id"], "sp": _sp(b),
                 "nguoi": (b.get("created") or {}).get("name", ""),
                 "luc": datetime.fromtimestamp((b.get("created") or {}).get("createdAt") or time.time()).strftime("%d/%m %H:%M"),
                 "tao": time.time()}
            if req in nhap:   # đã nhận trên Nhanh trước khi bot thấy → chỉ ghi, không gửi thẻ
                x["nhap"] = {"bill": nhap[req]["id"], "who": "", "luc": "", "lech": {}}
            out.append(f"MỚI #{req} {TEN.get(x['tu'])}→{TEN.get(den)} {sum(x['sp'].values())} cái" + (" (đã nhận)" if x.get("nhap") else ""))
            chat = TK.E.get(NHOM[den])
            if send and chat and not x.get("nhap"):
                tg = tag_ca(den)
                x["chat"], x["mid"] = chat, tsend(chat, the_text(x) + (f"\n👉 {tg}" if tg else ""), the_btn(x))
            st[req] = x
        for req, x in st.items():
            if x.get("nhap") or not x.get("mid"):
                continue
            b = nhap.get(req)
            if b:
                cr = b.get("created") or {}
                x["nhap"] = {"bill": b["id"], "who": cr.get("name", ""), "lech": _lech(x, _sp(b)),
                             "luc": datetime.fromtimestamp(cr.get("createdAt") or time.time()).strftime("%d/%m %H:%M")}
                out.append(f"NHANH ĐÃ NHẬN #{req} lệch {len(x['nhap']['lech'])}")
                if send:
                    tedit(x["chat"], x["mid"], the_text(x), None)
                    if x["nhap"]["lech"]:
                        tsend(x["chat"], f"⚠️ <b>Phiếu chuyển #{esc(req)}: Nhanh nhập khác số đếm</b>\n"
                              + "\n".join(f"• {esc(s)}: đếm {a} · Nhanh nhập {n}" for s, (a, n) in x["nhap"]["lech"].items())
                              + "\n👉 " + ql_tag() + " xử lý giúp", reply_to=x["mid"])
                continue
            gio = now().hour
            nh = x.get("nhan")
            if nh and not x.get("nhac_nhanh") and time.time() - nh["ts"] > 1800 and 8 <= gio < 23:
                x["nhac_nhanh"] = time.time()
                out.append(f"NHẮC NHANH #{req}")
                if send:
                    tsend(x["chat"], f"⏰ <a href=\"tg://user?id={nh['uid']}\">{esc(nh['who'])}</a>: đã nhận trên Tele 30 phút "
                          f"mà Nhanh chưa nhận phiếu chuyển #{esc(req)} → vào Nhanh bấm nhận giúp.", reply_to=x["mid"])
            if not nh and time.time() - x.get("nhac_the", x["tao"]) > 3 * 3600 and 9 <= gio < 22:
                x["nhac_the"] = time.time()
                out.append(f"NHẮC THẺ #{req}")
                if send:
                    tg = tag_ca(x["den"])
                    tsend(x["chat"], f"⏰ Phiếu chuyển #{esc(req)} chưa ai bấm nhận. Hàng tới chưa? Đếm xong bấm ✅/❌ trên thẻ."
                          + (f"\n👉 {tg}" if tg else ""), reply_to=x["mid"])
        st_ghi(st)
    return "\n".join(out) or "không có gì mới"


def on_cb(cq, p):
    u, who = cq["from"], ten(cq["from"])
    chat, mid = cq["message"]["chat"]["id"], cq["message"]["message_id"]
    kind, req = p[1], p[2]
    with _Khoa():
        st = st_doc(); x = st.get(req)
        if not x or x.get("mid") != mid:
            return answer(cq, "Thẻ cũ.", True)
        if x.get("nhan") or x.get("nhap"):
            return answer(cq, "Đã nhận rồi.", True)
        if kind == "ok":
            x["nhan"] = {"who": who, "uid": u["id"], "luc": now().strftime("%d/%m %H:%M"), "ts": time.time(), "thieu": {}}
            st_ghi(st)
    if kind == "ok":
        answer(cq, "✅ Đã ghi nhận đủ")
        return tedit(chat, mid, the_text(x), None)
    if kind == "x":
        answer(cq)
        return TK.prompt(chat, mid, req, "kc_so", u,
                         f"✏️ {esc(who)} trả lời tin này, mỗi dòng 1 mã sai: <b>số thứ tự  số thật</b> "
                         f"(VD <code>2 1</code> = mã thứ 2 chỉ có 1 cái; lỗi thì không tính). Gõ mã SKU thay số thứ tự cũng được.")


def on_reply(m, p):
    chat, who, u = m["chat"]["id"], ten(m.get("from")), m.get("from") or {}
    req, t = p["id"], (m.get("text") or "").strip()
    with _Khoa():
        st = st_doc(); x = st.get(req)
        if not x or x.get("nhan") or x.get("nhap"):
            return
        ds, thieu, sai = list(x["sp"]), {}, []
        for dong in re.split(r"[\n,;]+", t):
            w = dong.split()
            if len(w) != 2 or not re.fullmatch(r"\d+", w[1]):
                if dong.strip():
                    sai.append(dong.strip())
                continue
            k = w[0].upper()
            s = ds[int(k) - 1] if re.fullmatch(r"\d+", k) and 0 < int(k) <= len(ds) else (k if k in x["sp"] else None)
            if not s:
                sai.append(dong.strip()); continue
            thieu[s] = int(w[1])
        if not thieu or sai:
            return TK.prompt(chat, m["message_id"], req, "kc_so", u,
                             (f"Chưa hiểu: {esc('; '.join(sai))}\n" if sai else "")
                             + "Gõ lại mỗi dòng: <b>số thứ tự  số thật</b>, VD <code>2 1</code>")
        x["nhan"] = {"who": who, "uid": u.get("id"), "luc": now().strftime("%d/%m %H:%M"), "ts": time.time(), "thieu": thieu}
        st_ghi(st)
    tedit(x["chat"], x["mid"], the_text(x), None)
    tsend(chat, f"⚠️ <b>Phiếu chuyển #{esc(req)} nhận thiếu/lỗi</b> ({esc(who)}):\n"
          + "\n".join(f"• {esc(s)}: xuất {x['sp'][s]} · thật {k} ({k - x['sp'][s]:+d})" for s, k in thieu.items())
          + "\n👉 " + ql_tag() + " xử lý giúp. Bên nhận vào Nhanh nhận phiếu theo <b>số thật</b>.", reply_to=m["message_id"])
    for o in TK.duyet_ids():
        tsend(o, f"⚠️ Phiếu chuyển #{esc(req)} {TEN.get(x['tu'])}→{TEN.get(x['den'])} nhận thiếu/lỗi {len(thieu)} mã ({esc(who)})")


TK.EXT_CB["kc"] = on_cb
TK.EXT_REPLY["kc_so"] = on_reply

if __name__ == "__main__":
    import lark as Lk
    TK.init(Lk.load_env(), start_worker=False)
    a = sys.argv[1:] or ["help"]
    if a[0] == "xem":
        xuat, nhap = doc_nhanh()
        for r, b in sorted(xuat.items()):
            print(r, b["date"], TEN.get(str(b["depotId"])), "→", TEN.get(str((b.get("related") or {}).get("depotId"))),
                  sum(_sp(b).values()), "cái ·", "ĐÃ NHẬN #" + str(nhap[r]["id"]) if r in nhap else "ĐANG ĐI")
    elif a[0] == "quet":
        print(quet("--send" in a))
    else:
        print(__doc__)
