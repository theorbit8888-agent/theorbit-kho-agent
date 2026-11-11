#!/usr/bin/env python3
"""DẠY BOT — team dạy bot theo kiểu tư duy bậc 2 (quy tắc chung + vì sao + ngoại lệ + ví dụ), chủ shop duyệt.
Bot KHÔNG tự sửa code: bài đã duyệt do Claude Code trên máy chủ shop xử lý (xem CLAUDE.md "DẠY BOT").

  /day [ý muốn dạy]   (trong nhóm → bot mở chat riêng; hoặc nhắn riêng bot)
    → bot hỏi ngược 6 câu: tình huống · bot nên làm gì · vì sao · quy tắc chung (con số) · ngoại lệ · ví dụ
      câu trả lời mơ hồ ("nhiều", "khi cần", quá ngắn, ví dụ thiếu) → bot bắt nói rõ
    → người dạy xem lại, bấm Gửi → bảng "DB · DẠY BOT" + chủ shop nhận thẻ: 👍 Duyệt làm · ❓ Hỏi lại · ❌ Không làm
  /dangday   xem các bài chưa xong
CLI (Claude Code dùng):
  python3 tools/day_bot.py moi                        bài chờ duyệt chưa báo qua Claude (tác vụ hằng giờ dùng)
  python3 tools/day_bot.py ds [--het]                 bài đang chờ / đã duyệt (--het: cả bài xong)
  python3 tools/day_bot.py xem D001                   đủ nội dung + trao đổi
  python3 tools/day_bot.py hoi D001 "câu hỏi" --send   hỏi lại người dạy (họ trả lời trong chat riêng với bot)
  python3 tools/day_bot.py duyet|khong D001 [--send]  chủ shop duyệt ngay trong Claude
  python3 tools/day_bot.py xong D001 "đã sửa gì" --send
"""
import json, os, re, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orbit_tg as TG  # noqa: E402
import ticket as TK  # noqa: E402

BANG = "DB · DẠY BOT"
CAU = [
    ("Tình huống", "1/6 · <b>TÌNH HUỐNG</b>: chuyện này xảy ra khi nào? (ở bước/lệnh nào, ai đang làm, lúc nào)"),
    ("Bot nên làm gì", "2/6 · <b>BOT NÊN LÀM GÌ</b>: cụ thể bot nói/làm gì, báo cho ai, có nút gì?"),
    ("Vì sao", "3/6 · <b>VÌ SAO</b>: mục đích là gì, không làm thì hậu quả gì? "
               "(bot dựa vào đây để tự áp dụng cho trường hợp giống mà bạn chưa kể)"),
    ("Quy tắc chung", "4/6 · <b>QUY TẮC CHUNG</b>: áp dụng cho MỌI trường hợp nào? Ghi rõ con số/ngưỡng "
                      "(từ 5 cái, quá 2 giờ, mọi sàn hay chỉ TikTok, mọi kho hay chỉ Q2…)"),
    ("Ngoại lệ", "5/6 · <b>NGOẠI LỆ</b>: khi nào KHÔNG làm vậy hoặc làm khác? (combo, hàng tặng, hoả tốc, cuối tuần, "
                 "hàng lỗi…). Không có thì ghi \"không có vì …\""),
    ("Ví dụ", "6/6 · <b>VÍ DỤ THẬT</b>: 1 ví dụ PHẢI áp dụng và 1 ví dụ KHÔNG áp dụng (mỗi ví dụ 1 dòng)"),
]
COLS = ["Mã", "Ngày", "Người dạy", "Telegram ID", "Nhóm"] + [c for c, _ in CAU] + \
       ["Ảnh", "Ảnh (xem)", "Trạng thái", "Chủ shop", "Trao đổi", "Kết quả"]
CHO, HOI, DUYET, XONG, KHONG = "Chờ chủ shop", "Chờ người dạy trả lời", "Đã duyệt — chờ làm", "Đã áp dụng", "Không làm"
MO_HO = ["tuỳ", "tùy", "khi cần", "nhiều", "ít", "lâu", "gấp", "thường", "hay bị", "sớm", "muộn", "đôi khi",
         "một số", "vài", "khoảng", "chắc", "có thể"]
DRAFT_F = os.path.join(TK.ROOT, "logs", "day", "nhap.json")
esc, tsend, tedit, answer, ten = TK.esc, TK.tsend, TK.tedit, TK.answer, TK.ten


# ---------------- lưu nháp (phiếu đang hỏi) ----------------
def nhap():
    try:
        return json.load(open(DRAFT_F))
    except Exception:
        return {}


def luu_nhap(d):
    os.makedirs(os.path.dirname(DRAFT_F), exist_ok=True)
    json.dump(d, open(DRAFT_F, "w"), ensure_ascii=False, indent=1)


# ---------------- Sheet ----------------
def rows():
    return TG.rows(BANG, fresh=True)


def get(ma):
    return next((r for r in rows() if r.get("Mã") == ma), None)


def upd(r, f):
    TG.kho("update", table=TG.sname(BANG), id=r["_id"], fields=f)
    TG._CACHE.pop(TG.sname(BANG), None)
    r.update(f)


def noi_dung(r, ngan=False):
    out = []
    for c, _ in CAU:
        v = str(r.get(c) or "").strip()
        if v:
            out.append(f"<b>{c}:</b> {esc(v[:200] if ngan else v)}")
    return "\n".join(out)


def the(r):
    return (f"📚 <b>BÀI DẠY {esc(r['Mã'])}</b> · {esc(r.get('Người dạy'))} · {esc(str(r.get('Ngày'))[5:16])} · {esc(r.get('Nhóm'))}\n"
            + noi_dung(r) + ("\n📷 có ảnh" if r.get("Ảnh") else "")
            + (f"\n💬 <b>Trao đổi:</b>\n{esc(r.get('Trao đổi'))}" if r.get("Trao đổi") else "")
            + f"\n➡️ <b>{esc(r.get('Trạng thái'))}</b>" + (f" · {esc(r.get('Chủ shop'))}" if r.get("Chủ shop") else "")
            + (f"\n✅ {esc(r.get('Kết quả'))}" if r.get("Kết quả") else ""))


def nut_chu(ma):
    return [[{"text": "👍 Duyệt làm", "callback_data": f"dy:ok:{ma}"}, {"text": "❓ Hỏi lại", "callback_data": f"dy:hoi:{ma}"},
             {"text": "❌ Không làm", "callback_data": f"dy:no:{ma}"}]]


# ---------------- kiểm tra câu trả lời ----------------
def kiem(cot, t):
    """None = được; ngược lại câu nhắc nói rõ hơn."""
    w = len(t.split())
    low = " " + t.lower() + " "
    if cot == "Ngoại lệ":
        if re.fullmatch(r"\s*(không|ko|k|không có|ko có)\s*\.?\s*", t.lower()):
            return "Ghi \"không có vì …\" — nói vì sao không có ngoại lệ (để chắc là đã nghĩ tới combo, hàng tặng, hoả tốc…)."
        return None if w >= 4 else "Ngắn quá — nói rõ trường hợp nào làm khác."
    if w < 4:
        return "Ngắn quá — nói rõ hơn để bot làm đúng mà không phải đoán."
    if cot == "Quy tắc chung":
        mh = [x for x in MO_HO if f" {x} " in low or f" {x}," in low or f" {x}." in low]
        if mh and not re.search(r"\d", t):
            return f"\"{mh[0]}\" là bao nhiêu? Ghi con số cụ thể (vd: từ 5 cái, quá 2 giờ, sau 3 ngày)."
    if cot == "Vì sao" and w < 6:
        return "Nói rõ mục đích/hậu quả — bot dựa vào lý do để xử lý cả trường hợp bạn chưa kể."
    if cot == "Ví dụ":
        dong = [x for x in re.split(r"\n|;", t) if x.strip()]
        if len(dong) < 2 and " không " not in low:
            return "Cần 2 ví dụ: 1 ví dụ PHẢI áp dụng và 1 ví dụ KHÔNG áp dụng (mỗi cái 1 dòng)."
    return None


# ---------------- phiếu hỏi ngược ----------------
def bat_dau(m, seed=""):
    u = m.get("from") or {}
    uid = str(u.get("id"))
    d = nhap()
    nhom = d.get(uid, {}).get("nhom") or ""
    d[uid] = {"buoc": 0, "data": {}, "nhom": nhom or "chat riêng", "ten": ten(u), "anh": d.get(uid, {}).get("anh", "")}
    d[uid]["seed"] = seed
    luu_nhap(d)
    tsend(uid, "📚 <b>Dạy bot</b> — bot hỏi 6 câu để hiểu đúng và áp dụng được cho cả trường hợp tương tự.\n"
               "Trả lời từng tin (bấm trả lời hoặc gõ thẳng). Gõ <code>huỷ</code> để dừng."
               + (f"\nÝ ban đầu: <i>{esc(seed)}</i>" if seed else ""))
    hoi_tiep(uid)


def hoi_tiep(uid):
    d = nhap(); p = d.get(uid)
    if not p:
        return
    while p["buoc"] < len(CAU) and CAU[p["buoc"]][0] in p["data"] and p["data"][CAU[p["buoc"]][0]]:
        p["buoc"] += 1
    luu_nhap(d)
    if p["buoc"] >= len(CAU):
        return xem_lai(uid)
    TK.prompt(int(uid), None, uid, "day_q", {"id": int(uid), "first_name": p["ten"]}, CAU[p["buoc"]][1])


def xem_lai(uid):
    p = nhap()[uid]
    r = dict(p["data"])
    tsend(int(uid), "📋 <b>Xem lại bài dạy</b>\n" + noi_dung(r) + "\n\nĐúng ý chưa?",
          [[{"text": "📤 Gửi chủ shop", "callback_data": f"dy:gui:{uid}"},
            {"text": "✏️ Làm lại", "callback_data": f"dy:lai:{uid}"}]])


def tra_loi(m, p=None):
    """Câu trả lời cho phiếu (reply hoặc gõ thẳng trong chat riêng). True = đã nhận."""
    uid = str((m.get("from") or {}).get("id"))
    d = nhap(); w = d.get(uid)
    if not w:
        return False
    t = (m.get("text") or m.get("caption") or "").strip()
    if m.get("photo"):
        w["anh"] = max(m["photo"], key=lambda x: x.get("file_size", 0))["file_id"]
        luu_nhap(d)
        if not t:
            tsend(int(uid), "📷 Đã nhận ảnh (gắn vào bài dạy).")
            return True
    if t.lower() in ("huỷ", "hủy", "/huy", "huy"):
        d.pop(uid, None); luu_nhap(d)
        tsend(int(uid), "Đã huỷ bài dạy.")
        return True
    if w["buoc"] >= len(CAU):
        tsend(int(uid), "Bấm 📤 Gửi chủ shop hoặc ✏️ Làm lại ở tin xem lại.")
        return True
    cot = CAU[w["buoc"]][0]
    loi = kiem(cot, t)
    if loi:
        TK.prompt(int(uid), m.get("message_id"), uid, "day_q", {"id": int(uid), "first_name": w["ten"]},
                  f"🤔 {loi}\n\n" + CAU[w["buoc"]][1])
        return True
    w["data"][cot] = t
    w["buoc"] += 1
    luu_nhap(d)
    hoi_tiep(uid)
    return True


def gui(uid, u):
    d = nhap(); w = d.pop(uid, None)
    if not w:
        return
    luu_nhap(d)
    TG.kho("setup", tables={TG.sname(BANG): COLS})
    n = len([r for r in rows() if r.get("Mã")]) + 1
    ma = f"D{n:03d}"
    r = {"Mã": ma, "Ngày": datetime.now().strftime("%Y-%m-%d %H:%M"), "Người dạy": w["ten"], "Telegram ID": uid,
         "Nhóm": w["nhom"], **w["data"], "Ảnh": "tg:" + w["anh"] if w.get("anh") else "", "Trạng thái": CHO}
    rid = TG.kho("add", table=TG.sname(BANG), rows=[r])[0]
    TG._CACHE.pop(TG.sname(BANG), None)
    r["_id"] = rid
    if w.get("anh"):
        try:
            TG.xem_anh(BANG, rid, "Ảnh", TG.download(w["anh"]))
        except BaseException as e:
            print("day_bot: ảnh lỗi", e, flush=True)
    tsend(int(uid), f"📤 Đã gửi bài dạy <b>{ma}</b> cho chủ shop. Có câu hỏi thêm bot sẽ nhắn bạn ở đây.")
    bao_chu(r, "\n\nDuyệt xong: nhắn Claude <b>\"xử lý bài dạy\"</b> trên máy Mac.")


def bao_chu(r, them=""):
    for o in TK.duyet_ids():
        tsend(o, the(r) + them, nut_chu(r["Mã"]) if r.get("Trạng thái") in (CHO,) else None)
        if str(r.get("Ảnh", "")).startswith("tg:"):
            try:
                TG.api("sendPhoto", {"chat_id": o, "photo": r["Ảnh"][3:], "caption": f"Ảnh bài dạy {r['Mã']}"})
            except Exception:
                pass


# ---------------- hỏi lại người dạy (chủ shop / Claude) ----------------
def hoi_lai(r, cau, ai="Chủ shop"):
    trao = (str(r.get("Trao đổi") or "") + f"\n[{datetime.now():%d/%m %H:%M}] {ai} hỏi: {cau}").strip()
    upd(r, {"Trao đổi": trao, "Trạng thái": HOI})
    uid = str(r.get("Telegram ID") or "")
    if uid:
        TK.prompt(int(uid), None, r["Mã"], "day_tl", {"id": int(uid), "first_name": r.get("Người dạy") or ""},
                  f"❓ <b>Bài dạy {esc(r['Mã'])}</b> — {esc(ai)} hỏi thêm:\n<b>{esc(cau)}</b>\n\n"
                  f"{esc(r.get('Người dạy'))} trả lời tin này (trả lời theo quy tắc chung + ngoại lệ nếu có).")


def on_tl(m, p):
    r = get(p["id"])
    t = (m.get("text") or m.get("caption") or "").strip()
    if not r or not t:
        return
    if len(t.split()) < 3:
        return TK.prompt(m["chat"]["id"], m["message_id"], r["Mã"], "day_tl", m.get("from") or {},
                         "Ngắn quá — trả lời rõ hơn giúp bot nhé (trả lời tin này).")
    trao = (str(r.get("Trao đổi") or "") + f"\n[{datetime.now():%d/%m %H:%M}] {ten(m.get('from'))} trả lời: {t}").strip()
    upd(r, {"Trao đổi": trao, "Trạng thái": CHO})
    tsend(m["chat"]["id"], f"✅ Đã gửi câu trả lời cho chủ shop (bài {esc(r['Mã'])}).", reply_to=m["message_id"])
    bao_chu(r, "\n\n(người dạy vừa trả lời)")


def on_q(m, p):
    tra_loi(m, p)


# ---------------- lệnh + nút ----------------
def cmd_day(m, arg):
    chat, u = m["chat"]["id"], m.get("from") or {}
    if m["chat"]["type"] == "private":
        return bat_dau(m, arg.strip())
    d = nhap()
    nhom = {str(TK.E.get(k) or ""): v for k, v in TK.TEN_NHOM.items()}.get(str(chat), str(chat))
    d[str(u.get("id"))] = {"buoc": 0, "data": {}, "nhom": nhom, "ten": ten(u), "seed": arg.strip(),
                           "anh": max(m["photo"], key=lambda x: x.get("file_size", 0))["file_id"] if m.get("photo") else ""}
    luu_nhap(d)
    bot = TK.me().get("username", "")
    tsend(chat, f"📚 {esc(ten(u))}: bấm nút để dạy bot trong chat riêng (bot hỏi 6 câu cho rõ, không làm loãng nhóm).",
          [[{"text": "📚 Dạy bot (chat riêng)", "url": f"https://t.me/{bot}?start=day"}]], reply_to=m["message_id"])


def start_day(m, arg):
    uid = str((m.get("from") or {}).get("id"))
    seed = nhap().get(uid, {}).get("seed", "")
    bat_dau(m, seed)


def cmd_dangday(m, arg):
    bs = [r for r in rows() if r.get("Trạng thái") in (CHO, HOI, DUYET)]
    if not bs:
        return tsend(m["chat"]["id"], "Không có bài dạy nào đang chờ.")
    tsend(m["chat"]["id"], "📚 <b>Bài dạy chưa xong</b>\n" + "\n".join(
        f"• {esc(r['Mã'])} · {esc(r.get('Người dạy'))} · {esc(r.get('Trạng thái'))} — {esc(str(r.get('Bot nên làm gì'))[:90])}"
        for r in bs))


def bao_nguoi_day(r, text):
    if r.get("Telegram ID"):
        tsend(int(r["Telegram ID"]), text)


def on_cb(cq, p):
    kind, key = p[1], p[2]
    u = cq["from"]
    c, mid = cq["message"]["chat"]["id"], cq["message"]["message_id"]
    if kind in ("gui", "lai"):
        if str(u["id"]) != key:
            return answer(cq, "Nút của người khác")
        answer(cq)
        TK.TG.api("editMessageReplyMarkup", {"chat_id": c, "message_id": mid})
        if kind == "gui":
            return gui(key, u)
        d = nhap(); w = d.get(key)
        if w:
            w.update(buoc=0, data={}); luu_nhap(d)
        return hoi_tiep(key)
    if str(u["id"]) not in TK.duyet_ids():
        return answer(cq, "Chỉ chủ shop duyệt", alert=True)
    r = get(key)
    if not r:
        return answer(cq, "Không còn bài này")
    if kind == "hoi":
        answer(cq)
        return TK.prompt(c, mid, key, "day_chuhoi", u, f"❓ {esc(ten(u))} trả lời tin này bằng câu muốn hỏi lại người dạy ({esc(key)}).")
    if r.get("Trạng thái") not in (CHO, HOI):
        return answer(cq, f"Bài này đang: {r.get('Trạng thái')}")
    duyet(r, kind == "ok", ten(u))
    answer(cq, r["Trạng thái"])
    tedit(c, mid, the(r) + ("\n\n➡️ Nhắn Claude <b>\"xử lý bài dạy\"</b> trên máy Mac." if kind == "ok" else ""))


def duyet(r, ok, ai, send=True):
    upd(r, {"Trạng thái": DUYET if ok else KHONG, "Chủ shop": f"{ai} {datetime.now():%H:%M %d/%m}"})
    if send:
        bao_nguoi_day(r, f"📚 Bài dạy {esc(r['Mã'])}: chủ shop <b>{'đã duyệt, sắp cập nhật bot' if ok else 'chưa làm lúc này'}</b>.")


def on_chuhoi(m, p):
    r = get(p["id"])
    t = (m.get("text") or "").strip()
    if r and t:
        hoi_lai(r, t)
        tsend(m["chat"]["id"], f"Đã hỏi {esc(r.get('Người dạy'))}.", reply_to=m["message_id"])


def xong(ma, ket_qua, send=False):
    r = get(ma)
    if not r:
        sys.exit(f"không có bài {ma}")
    upd(r, {"Trạng thái": XONG, "Kết quả": ket_qua})
    print(f"{ma}: {XONG} — {ket_qua}")
    if send:
        bao_nguoi_day(r, f"✅ Bài dạy {esc(ma)} đã áp dụng vào bot: {esc(ket_qua)}")


TK.EXT_CMDS.update({"/day": cmd_day, "/dangday": cmd_dangday})
TK.EXT_PRIV.update({"/day": cmd_day, "/dangday": cmd_dangday})
TK.EXT_START["day"] = start_day
TK.EXT_CB["dy"] = on_cb
TK.EXT_REPLY.update({"day_q": on_q, "day_tl": on_tl, "day_chuhoi": on_chuhoi})
TK.EXT_TEXT.append(tra_loi)
TK.EXT_BAN.append(lambda uid: str(uid) in nhap())

if __name__ == "__main__":
    import lark as Lk
    TK.init(Lk.load_env(), start_worker=False)
    TG.kho("setup", tables={TG.sname(BANG): COLS})
    a = sys.argv[1:] or ["help"]
    send = "--send" in a
    a = [x for x in a if x != "--send"]
    plain = lambda s: re.sub(r"<[^>]+>", "", s).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    if a[0] == "ds":
        bs = [r for r in rows() if r.get("Mã") and ("--het" in a or r.get("Trạng thái") in (CHO, HOI, DUYET))]
        for r in bs:
            print(f"{r['Mã']} [{r.get('Trạng thái')}] {r.get('Người dạy')} ({r.get('Nhóm')}): {r.get('Bot nên làm gì')}")
        print(f"{len(bs)} bài" if bs else "không có bài nào")
    elif a[0] == "moi":   # bài chờ chủ shop CHƯA báo qua Claude (in đủ nội dung, rồi đánh dấu đã báo)
        f = os.path.join(TK.ROOT, "logs", "day", "da_bao_claude.json")
        try:
            da = set(json.load(open(f)))
        except Exception:
            da = set()
        moi = [r for r in rows() if r.get("Mã") and r.get("Trạng thái") == CHO and
               f"{r['Mã']}|{len(str(r.get('Trao đổi') or ''))}" not in da]
        for r in moi:
            print(plain(the(r))); print("-" * 30)
            da.add(f"{r['Mã']}|{len(str(r.get('Trao đổi') or ''))}")
        os.makedirs(os.path.dirname(f), exist_ok=True)
        json.dump(sorted(da), open(f, "w"))
        print(f"{len(moi)} bài mới" if moi else "KHONG_CO_BAI_MOI")
    elif a[0] == "xem" and len(a) > 1:
        r = get(a[1]); print(plain(the(r)) if r else "không có")
    elif a[0] == "hoi" and len(a) > 2:
        r = get(a[1])
        if not r:
            sys.exit("không có bài")
        if send:
            hoi_lai(r, a[2], "Claude")
            print("đã hỏi", r.get("Người dạy"))
        else:
            print("(thêm --send để gửi) sẽ hỏi:", a[2])
    elif a[0] in ("duyet", "khong") and len(a) > 1:
        r = get(a[1])
        if not r:
            sys.exit("không có bài")
        duyet(r, a[0] == "duyet", "Chủ shop (qua Claude)", send)
        print(a[1], r["Trạng thái"])
    elif a[0] == "xong" and len(a) >= 3:
        xong(a[1], a[2], send)
    else:
        print(__doc__)
