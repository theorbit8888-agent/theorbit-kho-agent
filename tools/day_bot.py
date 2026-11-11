#!/usr/bin/env python3
"""DẠY BOT — team ghi lại điều muốn bot làm khác đi, chủ shop duyệt; bot KHÔNG tự sửa gì.

  /day <điều muốn bot làm khác / quy tắc mới>   (nhóm Kho, Đổi trả, CS & Cửa hàng; kèm ảnh được)
    → ghi bảng "DB · DẠY BOT" + nhắn riêng chủ shop thẻ có nút 👍 Duyệt làm / ❌ Không làm
    → chủ shop duyệt rồi nhắn Claude Code trên máy Mac "xử lý bài dạy" → Claude sửa, chạy sân thử, cập nhật bot,
      đánh dấu "Đã áp dụng" (python3 tools/day_bot.py xong <Mã> "ghi chú") → người dạy được báo.
  /dangday   xem các bài dạy chưa xong
CLI: python3 tools/day_bot.py ds            # liệt kê bài đã duyệt chờ làm (cho Claude Code đọc)
     python3 tools/day_bot.py xong D001 "đã sửa ..." [--send]
"""
import os, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orbit_tg as TG  # noqa: E402
import ticket as TK  # noqa: E402

BANG = "DB · DẠY BOT"
COLS = ["Mã", "Ngày", "Người dạy", "Telegram ID", "Nhóm", "Nội dung", "Ảnh", "Ảnh (xem)", "Trạng thái",
        "Chủ shop", "Kết quả", "Thẻ tin"]
CHO, DUYET, XONG, KHONG = "Chờ chủ shop", "Đã duyệt — chờ làm", "Đã áp dụng", "Không làm"
esc, tsend, tedit, answer, ten = TK.esc, TK.tsend, TK.tedit, TK.answer, TK.ten


def rows():
    return TG.rows(BANG, fresh=True)


def get(ma):
    return next((r for r in rows() if r.get("Mã") == ma), None)


def upd(r, f):
    TG.kho("update", table=TG.sname(BANG), id=r["_id"], fields=f)
    TG._CACHE.pop(TG.sname(BANG), None)


def the(r):
    return (f"📚 <b>BÀI DẠY {esc(r['Mã'])}</b> · {esc(r.get('Người dạy'))} · {esc(str(r.get('Ngày'))[5:16])}\n"
            f"Nhóm: {esc(r.get('Nhóm'))}\n<i>{esc(r.get('Nội dung'))}</i>"
            + ("\n📷 có ảnh" if r.get("Ảnh") else "")
            + f"\n➡️ <b>{esc(r.get('Trạng thái'))}</b>"
            + (f" · {esc(r.get('Chủ shop'))}" if r.get("Chủ shop") else "")
            + (f"\n✅ {esc(r.get('Kết quả'))}" if r.get("Kết quả") else ""))


def cmd_day(m, arg):
    chat, u = m["chat"]["id"], m.get("from") or {}
    if not arg.strip():
        return tsend(chat, "📚 <b>Dạy bot</b>: gõ <code>/day</code> + điều muốn bot làm khác đi. Ví dụ:\n"
                           "• <code>/day hàng về thiếu từ 5 cái trở lên thì báo Huyền</code>\n"
                           "• <code>/day mẫu /kiemkho thêm cột vị trí kệ</code>\n"
                           "• <code>/day kiện hoàn quá 7 ngày chưa về thì nhắc mỗi sáng</code>\n"
                           "Chủ shop duyệt xong bot sẽ được sửa, bạn được báo. Xem bài đang chờ: /dangday",
                     reply_to=m["message_id"])
    TG.kho("setup", tables={TG.sname(BANG): COLS})
    n = len([r for r in rows() if r.get("Mã")]) + 1
    ma = f"D{n:03d}"
    fid = max(m["photo"], key=lambda x: x.get("file_size", 0))["file_id"] if m.get("photo") else ""
    nhom = {str(TK.E.get(k) or ""): v for k, v in TK.TEN_NHOM.items()}.get(str(chat), str(chat))
    r = {"Mã": ma, "Ngày": datetime.now().strftime("%Y-%m-%d %H:%M"), "Người dạy": ten(u), "Telegram ID": str(u.get("id", "")),
         "Nhóm": nhom, "Nội dung": arg.strip(), "Ảnh": "tg:" + fid if fid else "", "Trạng thái": CHO,
         "Thẻ tin": f"{chat}:{m['message_id']}"}
    rid = TG.kho("add", table=TG.sname(BANG), rows=[r])[0]
    TG._CACHE.pop(TG.sname(BANG), None)
    if fid:
        try:
            TG.xem_anh(BANG, rid, "Ảnh", TG.download(fid))
        except BaseException as e:
            print("day_bot: ảnh lỗi", e, flush=True)
    r["_id"] = rid
    tsend(chat, f"📚 Đã ghi bài dạy <b>{ma}</b>, đã báo chủ shop duyệt. Xong bot sẽ báo lại bạn.", reply_to=m["message_id"])
    nut = [[{"text": "👍 Duyệt làm", "callback_data": f"dy:ok:{ma}"}, {"text": "❌ Không làm", "callback_data": f"dy:no:{ma}"}]]
    for o in TK.duyet_ids():
        tsend(o, the(r) + "\n\nDuyệt xong: mở Claude Code trên máy Mac, nhắn <b>\"xử lý bài dạy\"</b>.", nut)
        if fid:
            try:
                TG.api("sendPhoto", {"chat_id": o, "photo": fid, "caption": f"Ảnh bài dạy {ma}"})
            except Exception:
                pass


def cmd_dangday(m, arg):
    bs = [r for r in rows() if r.get("Trạng thái") in (CHO, DUYET)]
    if not bs:
        return tsend(m["chat"]["id"], "Không có bài dạy nào đang chờ.")
    tsend(m["chat"]["id"], "📚 <b>Bài dạy chưa xong</b>\n" + "\n".join(
        f"• {esc(r['Mã'])} · {esc(r.get('Người dạy'))} · {esc(r.get('Trạng thái'))} — {esc(str(r.get('Nội dung'))[:90])}"
        for r in bs))


def bao_nguoi_day(r, text):
    chat = str(r.get("Thẻ tin", "")).split(":")[0]
    if chat:
        tsend(chat, text)


def on_cb(cq, p):
    kind, ma = p[1], p[2]
    u = cq["from"]
    if str(u["id"]) not in TK.duyet_ids():
        return answer(cq, "Chỉ chủ shop duyệt", alert=True)
    r = get(ma)
    if not r:
        return answer(cq, "Không còn bài này")
    if r.get("Trạng thái") != CHO:
        return answer(cq, f"Bài này đang: {r.get('Trạng thái')}")
    tt = DUYET if kind == "ok" else KHONG
    upd(r, {"Trạng thái": tt, "Chủ shop": f"{ten(u)} {datetime.now():%H:%M %d/%m}"})
    r.update({"Trạng thái": tt, "Chủ shop": f"{ten(u)} {datetime.now():%H:%M %d/%m}"})
    answer(cq, tt)
    tedit(cq["message"]["chat"]["id"], cq["message"]["message_id"], the(r)
          + ("\n\n➡️ Mở Claude Code trên máy Mac, nhắn <b>\"xử lý bài dạy\"</b>." if kind == "ok" else ""))
    bao_nguoi_day(r, f"📚 Bài dạy {esc(ma)}: chủ shop <b>{'đã duyệt, đang sửa bot' if kind == 'ok' else 'chưa làm lúc này'}</b>.")


def xong(ma, ket_qua, send=False):
    r = get(ma)
    if not r:
        sys.exit(f"không có bài {ma}")
    upd(r, {"Trạng thái": XONG, "Kết quả": ket_qua})
    print(f"{ma}: {XONG} — {ket_qua}")
    if send:
        bao_nguoi_day(r, f"✅ Bài dạy {esc(ma)} đã áp dụng: {esc(ket_qua)}\n({esc(str(r.get('Nội dung'))[:120])})")


TK.EXT_CMDS.update({"/day": cmd_day, "/dangday": cmd_dangday})
TK.EXT_CB["dy"] = on_cb

if __name__ == "__main__":
    import lark as Lk
    TK.init(Lk.load_env(), start_worker=False)
    a = sys.argv[1:] or ["help"]
    if a[0] == "ds":
        bs = [r for r in rows() if r.get("Trạng thái") in (DUYET, CHO)]
        for r in bs:
            print(f"{r['Mã']} [{r.get('Trạng thái')}] {r.get('Người dạy')} ({r.get('Nhóm')}): {r.get('Nội dung')}"
                  + (" [có ảnh]" if r.get("Ảnh") else ""))
        print(f"{len(bs)} bài") if bs else print("không có bài nào")
    elif a[0] == "xong" and len(a) >= 3:
        xong(a[1], a[2], "--send" in a)
    else:
        print(__doc__)
