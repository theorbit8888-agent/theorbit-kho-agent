#!/usr/bin/env python3
"""Việc CS + cửa hàng trên Telegram (thay các nhóm Lark BÁO CÁO STORE, BILL CHUYỂN KHOẢN, CS - CỬA HÀNG,
NOTE ĐƠN HÀNG, BÁO CÁO CS). Luồng cố định có nút, không gọi Claude. Chạy chung listener bot kho (đăng ký vào ticket.py).

Nhóm "The Orbit - CS & Cửa hàng" (env CH_CHAT_ID):
  /moca <két đếm>            mở ca: bot so với két cuối ca trước
  /chi <số tiền> <nội dung>  chi tiền mặt từ két (ship, grab, nước, mực in…) — tự xếp loại
  /thu <số tiền> <nội dung>  thu tiền mặt ngoài đơn (khách trả ship…)
  /ketca (dán mẫu)           kết ca: két đếm + thu TM/CK/thẻ → bot tự tính két phải có, báo lệch
  /ket                       két hiện tại phải có + chi trong ca
  /bill <mã đơn> <số tiền> <lý do>   (ảnh bill ở chú thích) sổ chuyển khoản; 21:30 chủ shop nhận 1 danh sách để xác nhận
  /goi <mã đơn> <ghi chú>    CS nhờ store gói / book ship / chừa hàng → thẻ việc có nút
  /chotca                    NVBH chốt mỗi ca (16h, 22h): tin tồn + ẢNH STORE (bắt buộc, reply phiếu hoặc kèm ảnh) + checklist;
                             bot liệt kê việc còn mở: tin khách (ca/xác nhận đơn/note) chưa bấm xong, ticket đổi trả chờ CS,
                             việc store chưa xong; báo hết mà còn sót → ping nhóm + quản lý (không còn CSKH riêng từ 19/11)
Nhóm "Đổi trả CS-Kho" / nhóm kho:
  /note <mã đơn> <ghi chú>   CS ghi chú đơn cho kho (đổi size trước gói, thêm túi, đi hoả tốc…) — bot tra Nhanh: đơn đã đi chưa
  /hoatoc <mã đơn>           đơn hoả tốc cần book ship ngay → kho bấm Đã book
Lịch (`cua_hang.py hen`, launchd vn.theorbit.kho-agent.cuahang): 10:00/14:00/18:00 nhắc việc treo, 21:30 sổ CK cho
chủ shop, 15:50/21:50 nhắc NVBH chốt ca (tag người trong ca), 16:20/22:20 chưa chốt → báo quản lý, Chủ nhật 22:30 báo cáo tuần két + CK + chốt ca.
"""
import os, re, sys, time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orbit_tg as TG  # noqa: E402
import ticket as TK  # noqa: E402
import nhanh as NH  # noqa: E402

KET = "CH · SỔ KÉT"
KET_COLS = ["Ngày", "Giờ", "Loại", "Người", "Số tiền", "Nội dung", "Loại chi", "Két đếm", "Két phải có", "Lệch",
            "Thu TM", "Thu CK", "Thu thẻ", "Ca", "Ảnh", "Ảnh (xem)"]
CK = "CH · CHUYỂN KHOẢN"
CK_COLS = ["Ngày", "Giờ", "Mã đơn", "Số tiền", "Lý do", "Người gửi", "Ảnh", "Ảnh (xem)", "Chủ shop xác nhận"]
VIEC = "CH · VIỆC"
VIEC_COLS = ["ID", "Loại", "Mã đơn", "Nội dung", "Người giao", "Lúc giao", "Trạng thái", "Người làm", "Lúc xong",
             "Nhanh", "Thẻ tin"]
CS = "CS · CHỐT CA"
CS_COLS = ["Ngày", "Giờ", "Người", "Tồn Meta", "Tồn TikTok", "Tồn Shopee", "Tồn Zalo OA", "Tồn Zalo", "Checklist",
           "Còn tồn việc", "Ảnh", "Ca", "Báo hết ticket", "Ticket CSKH còn", "Ticket đổi trả còn", "Bot kiểm",
           "Việc store còn", "Số ảnh store", "Ảnh (xem)"]
CHECK = ["Phản hồi 100% đánh giá sàn", "Kiểm tin ẩn/spam Meta", "Đơn CNV Loyalty", "Đơn Web", "Tin TikTok TO",
         "Đã xử lý HẾT việc (ca khách, xác nhận đơn, note, đổi trả, việc store)"]
TICKET_I = len(CHECK) - 1
LICH_F = os.path.expanduser("~/orbit-runtime/lich/ca.json")
CA_LOG = os.path.expanduser("~/orbit-runtime/cskh/tele_ca.jsonl")
CA_NUT = os.path.expanduser("~/orbit-runtime/cskh/inbox.jsonl")
CS_ST = ("Chờ gọi KH", "Chờ tạo đơn đi", "Chờ CS gắn đơn")   # ticket đổi trả đang chờ CS/NVBH làm
LOAI_CHI = [("Ship/Grab", ("ship", "grab", "xe", "book", "j&t", "jt", "ghtk", "viettel", "ahamove")),
            ("Ăn uống/nước", ("nước", "bánh", "ăn", "cafe", "cà phê", "trà")),
            ("Cúng/ông địa", ("cúng", "ông địa", "hoa", "nhang")),
            ("Văn phòng phẩm/in", ("mực", "giấy", "in ", "a4", "băng keo", "túi")),
            ("Trả khách/thối", ("thối", "trả khách", "khách ck dư", "dư")),
            ("Điện nước/rác/nhà", ("điện", "rác", "nhà", "bàn", "thuê")),
            ("Custom/sản phẩm", ("custom", "cus ", "may", "sửa"))]
esc, tsend, tedit, answer, ten = TK.esc, TK.tsend, TK.tedit, TK.answer, TK.ten


def chat():
    return str(TK.E.get("CH_CHAT_ID") or "")


def now():
    return datetime.now()


def ngay():
    return now().strftime("%Y-%m-%d")


def so(s):
    """'4.300.000' / '1,833,300' / '4tr072k' / '4tr1' / '300k' / '35000' → số đồng."""
    s = str(s).strip().lower().replace(" ", "").replace("đ", "").replace("vnd", "")
    m = re.fullmatch(r"(\d+)tr(\d{1,3})?k?", s)
    if m:
        return int(m[1]) * 1_000_000 + (int(m[2].ljust(3, "0")) * 1000 if m[2] else 0)
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        return int(re.sub(r"[.,]", "", s))
    return TK.parse_num(s)


def tien(n):
    return TK.vnd(n)


def add(table, row):
    rid = TG.kho("add", table=TG.sname(table), rows=[row])[0]
    TG._CACHE.pop(TG.sname(table), None)
    return rid


def rows(table):
    return TG.rows(table, fresh=True)


# ======================= két =======================

def ket_phai_co():
    """Két phải có hiện tại = két đếm lần mở ca/kết ca gần nhất + thu TM − chi sau đó. Trả (số, mốc, list chi)."""
    rs = rows(KET)
    moc, i0 = 0, -1
    for i, r in enumerate(rs):
        if r.get("Loại") in ("Mở ca", "Kết ca") and str(r.get("Két đếm", "")) != "":
            moc, i0 = TK.tien(r.get("Két đếm")), i
    chi, thu = [], 0
    for r in rs[i0 + 1:]:
        if r.get("Loại") == "Chi":
            chi.append(r)
        elif r.get("Loại") == "Thu":
            thu += TK.tien(r.get("Số tiền"))
    return moc + thu - sum(TK.tien(r.get("Số tiền")) for r in chi), moc, chi, thu


def moca(m, arg):
    c, who = m["chat"]["id"], ten(m.get("from"))
    n = so(arg.split()[0]) if arg.strip() else None
    if n is None:
        return tsend(c, "Gõ <code>/moca 4072000</code> (số tiền két đếm lúc mở ca; 4tr072k cũng được).", reply_to=m["message_id"])
    phai, _, _, _ = ket_phai_co()
    co_truoc = any(r.get("Loại") in ("Mở ca", "Kết ca") for r in rows(KET))
    lech = n - phai if co_truoc else 0
    add(KET, {"Ngày": ngay(), "Giờ": now().strftime("%H:%M"), "Loại": "Mở ca", "Người": who, "Két đếm": n,
              "Két phải có": phai, "Lệch": lech, "Ca": "sáng" if now().hour < 13 else "chiều"})
    t = f"🟢 <b>Mở ca</b> {now():%H:%M} · {esc(who)} · két <b>{tien(n)}</b>"
    if lech:
        t += f"\n⚠️ Lệch so với két cuối ca trước ({tien(phai)}): <b>{'+' if lech > 0 else ''}{tien(lech)}</b>"
        for o in TK.duyet_ids():
            tsend(o, f"⚠️ Két mở ca lệch {tien(lech)} ({esc(who)}, {now():%d/%m %H:%M})")
    tsend(c, t, reply_to=m["message_id"])


def loai_chi(nd):
    low = " " + nd.lower() + " "
    for ten_loai, kws in LOAI_CHI:
        if any(k in low for k in kws):
            return ten_loai
    return "Khác"


def chi(m, arg, loai="Chi"):
    c, who = m["chat"]["id"], ten(m.get("from"))
    p = arg.split(maxsplit=1)
    n = so(p[0]) if p else None
    if n is None or len(p) < 2:
        return tsend(c, f"Gõ <code>/chi 35k ship grab đơn 876897256</code>" if loai == "Chi" else
                     "Gõ <code>/thu 25k khách trả tiền ship</code> — chỉ tiền mặt <b>ngoài bán hàng</b> "
                     "(tiền bán hàng ghi 1 lần ở /ketca).",
                     reply_to=m["message_id"])
    fid = max(m["photo"], key=lambda x: x.get("file_size", 0))["file_id"] if m.get("photo") else ""
    rid = add(KET, {"Ngày": ngay(), "Giờ": now().strftime("%H:%M"), "Loại": loai, "Người": who, "Số tiền": n,
                    "Nội dung": p[1], "Loại chi": loai_chi(p[1]) if loai == "Chi" else "", "Ảnh": "tg:" + fid if fid else ""})
    if fid:
        luu_anh(rid, fid)
    phai, _, _, _ = ket_phai_co()
    tsend(c, f"{'🔻 Chi' if loai == 'Chi' else '🔺 Thu ngoài bán hàng'} {tien(n)} — {esc(p[1])}"
             + (f" <i>({loai_chi(p[1])})</i>" if loai == "Chi" else "") + (" 📷" if fid else "")
             + f"\nKét phải có: <b>{tien(phai)}</b>", reply_to=m["message_id"])
    if not fid:
        TK.prompt(c, m["message_id"], rid, "ch_anh", m.get("from") or {},
                  f"📷 {esc(who)} trả lời tin này bằng <b>ảnh hoá đơn / chứng từ</b> cho khoản {tien(n)} "
                  "(lần sau gửi ảnh kèm chú thích /chi ... là xong 1 bước).")


def luu_anh(rid, fid):
    try:
        TG.xem_anh(KET, rid, "Ảnh", TG.download(fid))
    except BaseException as e:
        print("cua_hang: ảnh két lỗi", e, flush=True)


def on_reply(m, p):
    c = m["chat"]["id"]
    if p["f"] == "ch_anh":
        if not m.get("photo"):
            return TK.prompt(c, m["message_id"], p["id"], "ch_anh", m.get("from") or {},
                             f"Cần <b>ảnh</b>: {esc(ten(m.get('from')))} trả lời tin này bằng ảnh hoá đơn.")
        fid = max(m["photo"], key=lambda x: x.get("file_size", 0))["file_id"]
        TG.kho("update", table=TG.sname(KET), id=p["id"], fields={"Ảnh": "tg:" + fid})
        TG._CACHE.pop(TG.sname(KET), None)
        luu_anh(p["id"], fid)
        tsend(c, "✅ Đã gắn ảnh vào khoản thu/chi.", reply_to=m["message_id"])


def thu(m, arg):
    chi(m, arg, "Thu")


MAU_KET = "/ketca\nKét đếm: \nThu tiền mặt: \nThu CK: \nThu thẻ: "


def ketca(m, arg):
    c, who = m["chat"]["id"], ten(m.get("from"))
    v = {}
    for line in arg.splitlines():
        lab, _, val = line.partition(":")
        k = lab.strip().lower()
        n = so(val.strip().split()[0]) if val.strip() else None
        if n is None:
            continue
        if "két" in k or "ket" in k:
            v["dem"] = n
        elif "mặt" in k or "tm" in k:
            v["tm"] = n
        elif "ck" in k or "chuyển" in k:
            v["ck"] = n
        elif "thẻ" in k or "the" in k or "cà" in k or "quẹt" in k:
            v["the"] = n
    if "dem" not in v:
        return tsend(c, f"Chép mẫu, điền rồi gửi:\n<code>{esc(MAU_KET)}</code>", reply_to=m["message_id"])
    phai0, moc, chis, thu_khac = ket_phai_co()
    phai = phai0 + v.get("tm", 0)
    lech = v["dem"] - phai
    add(KET, {"Ngày": ngay(), "Giờ": now().strftime("%H:%M"), "Loại": "Kết ca", "Người": who, "Két đếm": v["dem"],
              "Két phải có": phai, "Lệch": lech, "Thu TM": v.get("tm", 0), "Thu CK": v.get("ck", 0),
              "Thu thẻ": v.get("the", 0), "Ca": "sáng" if now().hour < 15 else "tối"})
    tong_chi = sum(TK.tien(r.get("Số tiền")) for r in chis)
    t = (f"🔵 <b>Kết ca</b> {now():%d/%m %H:%M} · {esc(who)}\n"
         f"Két đầu {tien(moc)} + thu TM {tien(v.get('tm', 0))}" + (f" + thu khác {tien(thu_khac)}" if thu_khac else "")
         + f" − chi {tien(tong_chi)} = <b>phải có {tien(phai)}</b>\nĐếm thực: <b>{tien(v['dem'])}</b> "
         + ("✅ khớp" if not lech else f"⚠️ <b>lệch {'+' if lech > 0 else ''}{tien(lech)}</b>")
         + f"\nThu CK {tien(v.get('ck', 0))} · thẻ {tien(v.get('the', 0))} · "
           f"<b>tổng thu {tien(v.get('tm', 0) + v.get('ck', 0) + v.get('the', 0))}</b>")
    if chis:
        t += "\nChi trong ca: " + "; ".join(f"{tien(r.get('Số tiền'))} {esc(r.get('Nội dung'))}" for r in chis[:12])
        thieu = [r for r in chis if not r.get("Ảnh")]
        if thieu:
            t += (f"\n📷 <b>{len(thieu)} khoản chi chưa có ảnh</b>: " + "; ".join(
                f"{tien(r.get('Số tiền'))} {esc(r.get('Nội dung'))}" for r in thieu[:8]) + " — gửi bổ sung ảnh ngay.")
    tsend(c, t, reply_to=m["message_id"])
    if lech:
        for o in TK.duyet_ids():
            tsend(o, "⚠️ <b>Két lệch khi kết ca</b>\n" + t)


def ket(m, arg):
    phai, moc, chis, thu_khac = ket_phai_co()
    tsend(m["chat"]["id"], f"💰 Két phải có: <b>{tien(phai)}</b> (mốc {tien(moc)}"
          + (f", thu {tien(thu_khac)}" if thu_khac else "") + (f", chi {len(chis)} khoản" if chis else "") + ")"
          + ("\n" + "\n".join(f"• {esc(r.get('Giờ'))} {tien(r.get('Số tiền'))} {esc(r.get('Nội dung'))}" for r in chis)
             if chis else ""), reply_to=m["message_id"])


# ======================= sổ chuyển khoản =======================

def bill(m, arg):
    c, who = m["chat"]["id"], ten(m.get("from"))
    p = arg.split()
    ma = next((x for x in p if re.fullmatch(r"#?[A-Za-z0-9]{5,}", x) and not so(x)), p[0] if p else "")
    tien_ = next((so(x) for x in p if so(x) and x != ma), None)
    ly = " ".join(x for x in p if x != ma and so(x) != tien_) if p else ""
    if not ma or not tien_:
        return tsend(c, "Chụp bill, chú thích: <code>/bill 879123456 368k bù đổi size</code> (mã đơn Nhanh, số tiền, lý do).",
                     reply_to=m["message_id"])
    fid = max(m["photo"], key=lambda x: x.get("file_size", 0))["file_id"] if m.get("photo") else ""
    rid = add(CK, {"Ngày": ngay(), "Giờ": now().strftime("%H:%M"), "Mã đơn": ma, "Số tiền": tien_, "Lý do": ly,
                   "Người gửi": who, "Ảnh": "tg:" + fid if fid else ""})
    if fid:
        try:
            TG.xem_anh(CK, rid, "Ảnh", TG.download(fid))
        except BaseException as e:
            print("cua_hang: ảnh bill lỗi", e, flush=True)
    hn = [r for r in rows(CK) if r.get("Ngày") == ngay()]
    tsend(c, f"🧾 Ghi CK đơn <code>{esc(ma)}</code> {tien(tien_)}" + (f" — {esc(ly)}" if ly else "")
             + ("" if fid else " (chưa có ảnh bill)") + f"\nHôm nay: {len(hn)} bill, {tien(sum(TK.tien(r.get('Số tiền')) for r in hn))}",
          reply_to=m["message_id"])


def gui_so_ck(send=True):
    rs = [r for r in rows(CK) if not r.get("Chủ shop xác nhận")]
    if not rs:
        return print("không có bill chờ xác nhận")
    t = (f"🧾 <b>Sổ chuyển khoản chờ xác nhận</b> ({len(rs)} bill, {tien(sum(TK.tien(r.get('Số tiền')) for r in rs))})\n"
         + "\n".join(f"• {esc(r.get('Ngày'))[5:]} {esc(r.get('Giờ'))} đơn {esc(r.get('Mã đơn'))} <b>{tien(r.get('Số tiền'))}</b>"
                     f" {esc(r.get('Lý do'))} ({esc(r.get('Người gửi'))})" for r in rs[:60])
         + "\nĐối chiếu sao kê, đủ thì bấm nút. Thiếu bill nào: <code>/billthieu mã đơn</code>")
    print(re.sub(r"<[^>]+>", "", t))
    if send:
        for o in TK.duyet_ids():
            tsend(o, t, [[{"text": "✅ Đã nhận đủ tất cả", "callback_data": f"ch:ckdu:{ngay()}"}]])


def billthieu(m, arg):
    if str((m.get("from") or {}).get("id")) not in TK.duyet_ids():
        return tsend(m["chat"]["id"], "Lệnh này của chủ shop (đánh dấu CK chưa nhận được).", reply_to=m["message_id"])
    if not arg.strip():
        return tsend(m["chat"]["id"], "Gõ <code>/billthieu mã đơn</code> để đánh dấu chuyển khoản chưa nhận.",
                     reply_to=m["message_id"])
    for r in rows(CK):
        if str(r.get("Mã đơn", "")).lower() == arg.strip().lower() and not r.get("Chủ shop xác nhận"):
            TG.kho("update", table=TG.sname(CK), id=r["_id"], fields={"Chủ shop xác nhận": "❌ Chưa nhận"})
            if chat():
                tsend(chat(), f"⚠️ Chủ shop chưa nhận được CK đơn <code>{esc(arg)}</code> ({tien(r.get('Số tiền'))}, "
                              f"{esc(r.get('Người gửi'))}) — kiểm lại với khách.")
            return tsend(m["chat"]["id"], "Đã đánh dấu chưa nhận.", reply_to=m["message_id"])
    tsend(m["chat"]["id"], "Không thấy bill chờ xác nhận với mã này.", reply_to=m["message_id"])


# ======================= thẻ việc: gói đơn / note kho / hoả tốc =======================

LOAI_VIEC = {"/goi": ("Store gói/book", [("📦 Đã gói", "goi"), ("🛵 Đã book ship", "book"), ("✅ Xong", "xong")]),
             "/note": ("Note kho", [("✅ Kho đã làm", "xong"), ("🚚 Đơn đã đi rồi", "dadi")]),
             "/hoatoc": ("Hoả tốc", [("🛵 Đã book ship", "book"), ("✅ Shipper đã lấy", "xong")])}


def nhanh_dong(ma):
    o = NH.don_theo_ma(ma) if NH.con_moi(240) else None
    if not o:
        return "", None
    sp = ", ".join(f"{x['ma']} x{x['sl']}" for x in o["sp"])
    return f"📦 Nhanh: {NH.TEN_KENH.get(o['kenh'], o['kenh'])} · <b>{esc(o['st_ten'])}</b> · {esc(sp)}", o


def the_viec(r):
    L = [f"🧷 <b>{esc(r['ID'])}</b> · {esc(r.get('Loại'))} · đơn <code>{esc(r.get('Mã đơn'))}</code>"]
    if r.get("Nội dung"):
        L.append(f"📝 {esc(r.get('Nội dung'))}")
    if r.get("Nhanh"):
        L.append(r["Nhanh"])
    L.append(f"➡️ <b>{esc(r.get('Trạng thái'))}</b> · giao: {esc(r.get('Người giao'))} {esc(str(r.get('Lúc giao'))[11:16])}"
             + (f" · làm: {esc(r.get('Người làm'))} {esc(str(r.get('Lúc xong'))[11:16])}" if r.get("Người làm") else ""))
    return "\n".join(L)


HT_DOI = "Hoả tốc · đổi size"   # /hoatoc có chữ "đổi": khoá bước — đổi size xong mới book ship (giu_don.py chặn /giao)
NUT_DOI = [("✅ Đã đổi size trong đơn", "doisize"), ("🚚 Đơn đã đi rồi", "dadi")]


def la_doi(nd):
    return re.search(r"(?<!\w)(đổi|doi)(?!\w)", nd or "", re.I) is not None


def sku_doi(nd):
    """'đổi SO-A4-RIVET-M → L' / 'doi SO-A4-RIVET-M sang SO-A4-RIVET-L' → (cũ, mới); không rõ → ('', '')."""
    m = re.search(r"([A-Z0-9][A-Z0-9-]*-[A-Z0-9]+)\s*(?:→|->|=>|>|sang)\s*([A-Z0-9-]+)", nd or "", re.I)
    if not m:
        return "", ""
    cu, moi = m.group(1).upper(), m.group(2).upper()
    if "-" not in moi and len(moi) <= 4:
        moi = cu.rsplit("-", 1)[0] + "-" + moi
    return cu, moi


def nut_viec(r, lenh):
    if r.get("Trạng thái") in ("Xong", "Huỷ"):
        return []
    if r.get("Trạng thái") == "Chờ đổi size":
        return [[{"text": t, "callback_data": f"ch:v:{r['ID']}:{a}"} for t, a in NUT_DOI]]
    return [[{"text": t, "callback_data": f"ch:v:{r['ID']}:{a}"} for t, a in LOAI_VIEC[lenh][1]]]


def giao_viec(m, arg, lenh):
    c, who = m["chat"]["id"], ten(m.get("from"))
    p = arg.split(maxsplit=1)
    if not p:
        return tsend(c, f"Gõ <code>{lenh} &lt;mã đơn&gt; &lt;ghi chú&gt;</code>"
                     + ("\nHoả tốc cần đổi size: <code>/hoatoc &lt;mã đơn&gt; đổi SO-A4-RIVET-M → L</code>" if lenh == "/hoatoc" else ""),
                     reply_to=m["message_id"])
    ma, nd = p[0].lstrip("#"), (p[1] if len(p) > 1 else "").lstrip("- ")
    doi = lenh == "/hoatoc" and la_doi(nd)
    dong, o = nhanh_dong(ma)
    canh = ""
    if lenh in ("/note", "/hoatoc") and o and o["st"] in (59, 60, 61, 71, 72, 74):
        canh = "\n⚠️ <b>Đơn đã rời kho</b> — không sửa trong đơn được nữa. Đổi size → mở /doi (đổi sau giao)."
    if doi and canh:   # đơn đã rời kho: không mở thẻ khoá bước (sẽ treo + nhắc mãi) → CS mở /doi
        return tsend(c, f"🚚 Đơn <code>{esc(ma)}</code> đã rời kho — không đổi size hoả tốc được nữa.\n" + dong
                     + "\nKhách vẫn cần đổi → mở <b>/doi</b> (đổi sau giao).", reply_to=m["message_id"])
    if doi and not sku_doi(nd)[1]:
        canh += "\nℹ️ Ghi rõ <code>SKU cũ → size mới</code> để bot tự kiểm Nhanh khi kho bấm đã đổi."
    with TK._LOCK:
        n = 1 + max([int(re.sub(r"\D", "", str(r.get("ID", ""))) or 0) for r in rows(VIEC)] + [0])
        r = {"ID": f"V{n}", "Loại": HT_DOI if doi else LOAI_VIEC[lenh][0], "Mã đơn": ma, "Nội dung": nd, "Người giao": who,
             "Lúc giao": now().strftime("%Y-%m-%d %H:%M"), "Trạng thái": "Chờ đổi size" if doi else "Chờ làm",
             "Nhanh": re.sub(r"<[^>]+>", "", dong)}
        r["_id"] = add(VIEC, r)
    r["Nhanh"] = dong
    kho = str(TK.E.get("CHAT_ID") or "")
    if doi and kho and str(c) != kho:   # việc đổi size là của KHO → thẻ có nút nằm ở nhóm Kho
        mid = tsend(kho, "🔥 " + the_viec(r) + canh + f"\n(gửi từ nhóm khác: {esc(who)})", nut_viec(r, lenh))
        tsend(c, f"🔥 Đã chuyển {esc(r['ID'])} (hoả tốc đổi size) sang <b>nhóm Kho</b>. Kho đổi xong mới book ship."
              + canh, reply_to=m["message_id"])
        c_the = kho
    else:
        mid = tsend(c, ("🔥 " if doi else "") + the_viec(r) + canh, nut_viec(r, lenh), reply_to=m["message_id"])
        c_the = c
    if mid:
        TG.kho("update", table=TG.sname(VIEC), id=r["_id"], fields={"Thẻ tin": TG.mk(c_the, mid) + "|" + lenh})


def on_cb(cq, p):
    u = cq["from"]
    who = ten(u)
    if p[1] == "ckdu":
        if str(u["id"]) not in TK.duyet_ids():
            return answer(cq, "Chỉ chủ shop", True)
        n = 0
        for r in rows(CK):
            if not r.get("Chủ shop xác nhận"):
                TG.kho("update", table=TG.sname(CK), id=r["_id"], fields={"Chủ shop xác nhận": f"✅ {now():%d/%m %H:%M}"})
                n += 1
        answer(cq, f"Đã xác nhận {n} bill")
        return tedit(cq["message"]["chat"]["id"], cq["message"]["message_id"],
                     esc(cq["message"].get("text", "")) + f"\n\n✅ Đã xác nhận {n} bill")
    if p[1] == "v":
        if not TK.is_member(u["id"]) and not (chat() and _la_tv(chat(), u["id"])):
            return answer(cq, "Bạn chưa ở nhóm", True)
        vid, a = p[2], p[3]
        r = next((x for x in rows(VIEC) if x.get("ID") == vid), None)
        if not r:
            return answer(cq, "Không thấy việc", True)
        lenh = str(r.get("Thẻ tin", "")).split("|")[-1] or "/goi"
        c, mid = cq["message"]["chat"]["id"], cq["message"]["message_id"]
        if r.get("Trạng thái") == "Chờ đổi size" and a in ("book", "xong", "goi"):   # nút cũ còn trên thẻ
            return answer(cq, "Chưa đổi size xong — bấm ✅ Đã đổi size trước", True)
        if a in ("doisize", "doiep"):
            if r.get("Trạng thái") != "Chờ đổi size":
                return answer(cq, "Đã đổi rồi")
            cu, moi = sku_doi(r.get("Nội dung"))
            if a == "doisize" and moi:
                import giu_don as GD
                kq, ly = GD.kiem_doi(r.get("Mã đơn"), cu, moi)
                if kq == "sai":
                    answer(cq, "Nhanh chưa đúng size", True)
                    return tsend(c, f"⚠️ {esc(r['ID'])}: <b>{esc(ly)}</b>.\nSửa đơn trên Nhanh rồi bấm lại ✅ Đã đổi size "
                                    "(bot kiểm lại sau lần đồng bộ Nhanh kế tiếp). Đã sửa ở chỗ khác (VD trên sàn) → bấm nút dưới.",
                                 [[{"text": "✅ Đã kiểm tay — đúng rồi", "callback_data": f"ch:v:{r['ID']}:doiep"}]], reply_to=mid)
                ghi = f" · Nhanh: {ly}" if kq == "ok" else f" · chưa kiểm được Nhanh ({ly})"
            else:
                ghi = " · kiểm tay" if a == "doiep" else ""
            dong_moi, _ = nhanh_dong(r.get("Mã đơn"))
            f = {"Trạng thái": "Chờ làm", "Nội dung": (str(r.get("Nội dung") or "") + f" — ✅ đã đổi size ({who} "
                 f"{now():%H:%M}){ghi}").strip()}
            if dong_moi:
                f["Nhanh"] = re.sub(r"<[^>]+>", "", dong_moi)
            TG.kho("update", table=TG.sname(VIEC), id=r["_id"], fields=f)
            r.update(f)
            if dong_moi:
                r["Nhanh"] = dong_moi
            answer(cq, "Đã đổi size")
            if a == "doiep":   # bấm từ tin cảnh báo → sửa thẻ gốc
                m = re.match(r"tg:(-?\d+):(\d+)", str(r.get("Thẻ tin") or ""))
                if m:
                    tedit(m.group(1), int(m.group(2)), "🔥 " + the_viec(r), nut_viec(r, lenh))
                return tedit(c, mid, esc(cq["message"].get("text", "")) + f"\n✅ {esc(who)} xác nhận đã đổi")
            return tedit(c, mid, "🔥 " + the_viec(r), nut_viec(r, lenh))
        st = {"goi": "Đã gói", "book": "Đã book ship", "xong": "Xong", "dadi": "Xong"}[a]
        f = {"Trạng thái": st, "Người làm": who, "Lúc xong": now().strftime("%Y-%m-%d %H:%M")}
        if a == "dadi":
            f["Nội dung"] = (str(r.get("Nội dung") or "") + " — đơn đã đi, không sửa kịp").strip()
        TG.kho("update", table=TG.sname(VIEC), id=r["_id"], fields=f)
        r.update(f)
        answer(cq, st)
        tedit(c, mid, ("🔥 " if r.get("Loại") == HT_DOI else "") + the_viec(r), nut_viec(r, lenh))
        if a == "dadi":
            tsend(c, f"🚚 {esc(r['ID'])}: đơn {esc(r.get('Mã đơn'))} đã đi — CS báo khách, "
                     "cần đổi thì mở /doi.", reply_to=mid)
    if p[1] == "cs":
        return cs_cb(cq, p)


_TV = {}


def _la_tv(c, uid):
    k = (c, uid)
    if k in _TV and time.time() - _TV[k][0] < 600:
        return _TV[k][1]
    r = TG.api("getChatMember", {"chat_id": c, "user_id": int(uid)})
    ok = bool(r.get("ok") and r["result"]["status"] in ("creator", "administrator", "member", "restricted"))
    _TV[k] = (time.time(), ok)
    return ok


# ======================= CS chốt ca =======================

CS_STATE = {}  # message_id -> {who, ton, tick, anh}
CS_MG = {}     # media_group_id -> key phiếu (ảnh 2,3… của album gửi kèm /chotca)
NHOM_TEN = {"ca": "💬", "don": "🧾", "note": "📝"}


def ca_hien_tai(t=None):
    """(tên ca, giờ bắt đầu) của NVBH: Ca 1 10–16h, Ca 2 16–22h (chốt ca 2 trễ sau 0h vẫn tính ngày trước)."""
    t = t or now()
    if t.hour < 4:
        t = t - timedelta(hours=t.hour + 1)
        return "Ca 2", t.replace(hour=16, minute=0, second=0, microsecond=0)
    if t.hour < 16:
        return "Ca 1", t.replace(hour=10, minute=0, second=0, microsecond=0)
    return "Ca 2", t.replace(hour=16, minute=0, second=0, microsecond=0)


def nvbh_ca(ca=None, t=None):
    """[(tên, telegram id)] NVBH trong ca theo ~/orbit-runtime/lich/ca.json."""
    try:
        import json
        d = json.load(open(LICH_F))
    except Exception:
        return []
    ca, bd = ca_hien_tai(t) if ca is None else (ca, t or now())
    ds = (d.get("lich", {}).get("NVBH", {}).get(bd.strftime("%Y-%m-%d")) or {}).get(ca) or []
    return [(n, d.get("nguoi", {}).get(n)) for n in ds]


def tag(ds):
    return ", ".join(f'<a href="tg://user?id={i}">{esc(n)}</a>' if i else esc(n) for n, i in ds)


def kiem_ticket(tu):
    """Việc còn mở: (tin ca khách / xác nhận đơn / note khách gửi từ `tu` chưa bấm xong, ticket đổi trả đang chờ CS,
    việc store /goi /note /hoatoc chưa xong). Không còn CSKH riêng (19/11) → NVBH lo hết."""
    import json
    xong = set()
    try:
        for l in open(CA_NUT):
            if '"nut"' in l:
                e = json.loads(l)
                if e.get("nut") == "xong":
                    xong.add((str(e.get("chat")), int(e.get("mid") or 0)))
    except OSError:
        pass
    nhom, ts = {}, tu.timestamp()   # 1 khách/đơn gửi 2 lần = 1 việc; bấm xong ở tin nào cũng tính xong
    try:
        for l in open(CA_LOG):
            if not l.strip():
                continue
            x = json.loads(l)
            if x.get("nhom", "ca") not in NHOM_TEN or x.get("time", 0) < ts:
                continue
            k = (x.get("nhom", "ca"), str(x.get("khach") or ""), str(x.get("order") or ""))
            g = nhom.setdefault(k, {"x": x, "xong": False})
            g["x"] = x
            g["xong"] = g["xong"] or (str(x.get("chat")), int(x.get("mid") or 0)) in xong
    except OSError:
        pass
    ca = [g["x"] for g in nhom.values() if not g["xong"]]
    try:
        tk = [r for r in TK.all_rows() if r.get("Trạng thái") in CS_ST]
    except BaseException:
        tk = []
    try:
        viec = [r for r in rows(VIEC) if r.get("Trạng thái") not in ("Xong", "Huỷ")]
    except BaseException:
        viec = []
    return ca, tk, viec


def link_ca(x):
    c = str(x.get("chat") or "")
    return f"https://t.me/c/{c[4:]}/{x.get('mid')}" if c.startswith("-100") else ""


def ds_ticket(ca, tk, viec=(), toi_da=12):
    L = []
    for x in ca[:toi_da]:
        lk = link_ca(x)
        nd = NHOM_TEN.get(x.get("nhom", "ca"), "") + " " + esc(re.sub(r"^\[[^\]]*\]\s*", "", x.get("ca", ""))) + f" · {esc(x.get('khach') or '')}" + (f" · đơn {esc(x.get('order'))}" if str(x.get("order") or "").lower() not in ("", "-", "chua co", "chưa có") else "")
        L.append(f'• <a href="{lk}">{nd}</a>' if lk else f"• {nd}")
    if len(ca) > toi_da:
        L.append(f"• … thêm {len(ca) - toi_da} tin khách")
    for r in tk[:toi_da]:
        L.append(f"• 🎫 {esc(r.get('ID'))} {esc(r.get('Loại'))} đơn {esc(r.get('Mã đơn'))} — {esc(r.get('Trạng thái'))}")
    if len(tk) > toi_da:
        L.append(f"• … thêm {len(tk) - toi_da} ticket đổi trả")
    for r in list(viec)[:toi_da]:
        L.append(f"• 🛍 {esc(r.get('ID'))} {esc(r.get('Loại'))} đơn {esc(r.get('Mã đơn'))} — {esc(r.get('Trạng thái'))}")
    if len(viec) > toi_da:
        L.append(f"• … thêm {len(viec) - toi_da} việc store")
    return "\n".join(L)


def kiem_text(ca, tk, viec):
    if not (ca or tk or viec):
        return "✅ không còn việc mở"
    return f"còn {len(ca)} tin khách + {len(tk)} ticket đổi trả + {len(viec)} việc store"


def cs_kiem(st):
    bd = datetime.fromisoformat(st["bd"]) if st.get("bd") else ca_hien_tai()[1]
    ca, tk, viec = kiem_ticket(bd.replace(hour=10, minute=0))   # tin khách từ 10h hôm đó: ca 1 sót thì ca 2 lo tiếp
    pn = kiem_pn_chua(st)
    if pn:
        viec = list(viec) + [pn]
    st["kiem"] = kiem_text(ca, tk, viec) + (":\n" + ds_ticket(ca, tk, viec, 8) if (ca or tk or viec) else "")
    st["kiem_luc"] = now().strftime("%H:%M")
    return ca, tk, viec


def pn_nhac(ca):
    """Ca 2: kho PN hôm nay có đi hàng mà chưa kiểm → thêm 1 dòng vào tin nhắc chốt ca."""
    if ca != "Ca 2":
        return ""
    try:
        import kho_flow as KF
        ds = KF.ds_kiem_pn()
        if ds and not any(r.get("Ngày") == ngay() and r.get("Kho") == "PN" for r in rows(KF.KIEM)):
            return (f"\n🔢 <b>Kiểm kho PN</b>: hôm nay đi {len(ds)} mã — đếm hàng trên kệ rồi gõ <code>/kiemkho</code> + các số "
                    "(thẻ danh sách bot gửi 21:50). Việc này nằm trong phiếu chốt ca, chưa kiểm là phiếu báo còn việc mở.")
    except BaseException as e:
        print("hen: pn_nhac lỗi", e)
    return ""


def kiem_pn_chua(st):
    """Ca 2: kho PN hôm nay có đi hàng mà chưa /kiemkho → 1 việc còn mở."""
    if st.get("ca") != "Ca 2":
        return None
    try:
        import kho_flow as KF
        ds = KF.ds_kiem_pn()
        if not ds:
            return None
        if any(r.get("Ngày") == ngay() and r.get("Kho") == "PN" for r in rows(KF.KIEM)):
            return None
    except BaseException as e:
        print("chotca: kiểm PN lỗi", e)
        return None
    return {"ID": "🔢", "Loại": f"Kiểm kho PN ({len(ds)} mã)", "Mã đơn": "—", "Trạng thái": "chưa /kiemkho"}


def anh_fid(m):
    return max(m["photo"], key=lambda x: x.get("file_size", 0))["file_id"] if m.get("photo") else ""


def cs_ve(st):
    """Vẽ lại phiếu chốt ca (sau khi thêm ảnh / tick)."""
    if st.get("mid"):
        tedit(st["chat"], st["mid"], cs_text(st), cs_btn(st["key"], st))


def chotca(m, arg):
    c, who = m["chat"]["id"], ten(m.get("from"))
    mg = m.get("media_group_id")
    if mg and mg in CS_MG:   # ảnh 2,3… của album kèm /chotca
        st = TK.STATE_KF.get("cs" + CS_MG[mg])
        if st and anh_fid(m):
            st["anh"].append(anh_fid(m)); TK._save(); cs_ve(st)
        return
    ton = {}
    for k, pat in (("Meta", r"meta|fb|ig"), ("TikTok", r"tiktok|tt"), ("Shopee", r"shopee|sp"),
                   ("Zalo OA", r"oa"), ("Zalo", r"zalo(?!\s*oa)")):
        mm = re.search(rf"(?:{pat})\D{{0,6}}(\d+)", arg.lower())
        if mm:
            ton[k] = int(mm[1])
    ca, bd = ca_hien_tai()
    key = str(m["message_id"])
    st = {"who": who, "ton": ton, "tick": [False] * len(CHECK), "uid": m["from"]["id"], "ca": ca, "bd": bd.isoformat(),
          "anh": [anh_fid(m)] if anh_fid(m) else [], "chat": c, "key": key}
    if mg:
        CS_MG[mg] = key
    cs_kiem(st)
    CS_STATE[key] = st
    TK.STATE_KF["cs" + key] = st
    st["mid"] = tsend(c, cs_text(st), cs_btn(key, st), reply_to=m["message_id"])
    if st["mid"]:   # trả lời (reply) phiếu bằng ảnh store → gắn vào phiếu
        TK.PEND[f"{c}:{st['mid']}"] = {"id": key, "f": "cs_anh", "u": st["uid"]}
    TK._save()


def cs_text(st):
    ton, n = st["ton"], len(st.get("anh") or [])
    return (f"📋 <b>CHỐT CA NVBH</b> {now():%d/%m} · {esc(st.get('ca', ''))} · {esc(st['who'])}\n"
            f"Tin tồn: " + (", ".join(f"{k} {v}" for k, v in ton.items()) if ton else
                            "<i>chưa ghi — gõ lại /chotca meta 0 tiktok 0 shopee 0 oa 0 zalo 0</i>")
            + "\n📷 Ảnh store: " + (f"<b>{n} ảnh</b> ✅" if n else
                                    "<b>chưa có</b> — trả lời tin này (reply) bằng ảnh store: quầy, kệ/móc, két, phòng thử, sàn")
            + "\n" + "\n".join(f"{'✅' if t else '⬜'} {c}" for c, t in zip(CHECK, st["tick"]))
            + (f"\n\n🤖 <b>Việc còn mở</b> (kiểm {st.get('kiem_luc', '')}): {st['kiem']}" if st.get("kiem") else ""))


def cs_btn(mid, st):
    b = [[{"text": f"{'✅' if t else '⬜'} {c}", "callback_data": f"ch:cs:{mid}:{i}"}] for i, (c, t) in enumerate(zip(CHECK, st["tick"]))]
    return b + [[{"text": "🔄 Kiểm lại việc còn mở", "callback_data": f"ch:cs:{mid}:kiem"}],
                [{"text": "📤 Gửi chốt ca", "callback_data": f"ch:cs:{mid}:gui"}]]


def cs_anh(m, p):
    st = TK.STATE_KF.get("cs" + p["id"])
    c = m["chat"]["id"]
    if not st:
        return tsend(c, "Phiếu chốt ca đã gửi/hết hạn — gõ /chotca lại nếu cần.", reply_to=m["message_id"])
    TK.PEND[f"{c}:{st['mid']}"] = p; TK._save()   # giữ để nhận thêm ảnh (album)
    if not anh_fid(m):
        return tsend(c, "Cần <b>ảnh</b> store: trả lời phiếu chốt ca bằng ảnh nhé.", reply_to=m["message_id"])
    st["anh"].append(anh_fid(m)); TK._save()
    cs_ve(st)


def cs_cb(cq, p):
    key, a = p[2], p[3]
    st = CS_STATE.get(key) or TK.STATE_KF.get("cs" + key)
    if not st:
        return answer(cq, "Phiếu cũ, gõ /chotca lại", True)
    c, mid = cq["message"]["chat"]["id"], cq["message"]["message_id"]
    st.setdefault("chat", c); st.setdefault("key", key); st.setdefault("anh", []); st["mid"] = mid
    if a == "kiem":
        answer(cq, "Đang kiểm…")
        cs_kiem(st); TK.STATE_KF["cs" + key] = st; TK._save()
        return tedit(c, mid, cs_text(st), cs_btn(key, st))
    if a == "gui":
        if not st["anh"]:
            return answer(cq, "Cần ít nhất 1 ảnh store: trả lời (reply) phiếu này bằng ảnh rồi bấm Gửi.", True)
        answer(cq, "Bot đang kiểm việc còn mở…")
        ca, tk, viec = cs_kiem(st)
        bao_het = st["tick"][TICKET_I]
        sach = not ca and not tk and not viec
        kq = kiem_text(ca, tk, viec)
        rid = add(CS, {"Ngày": ngay(), "Giờ": now().strftime("%H:%M"), "Người": st["who"], "Ca": st.get("ca", ""),
                 "Ảnh": ", ".join("tg:" + f for f in st["anh"]), "Số ảnh store": len(st["anh"]), "Việc store còn": len(viec),
                 **{f"Tồn {k}": v for k, v in st["ton"].items()},
                 "Checklist": "; ".join(f"{'✓' if t else '✗'} {k}" for k, t in zip(CHECK, st["tick"])),
                 "Còn tồn việc": ", ".join(k for k, t in zip(CHECK, st["tick"]) if not t),
                 "Báo hết ticket": "Rồi" if bao_het else "Chưa",
                 "Ticket CSKH còn": len(ca), "Ticket đổi trả còn": len(tk),
                 "Bot kiểm": kq + (" · BÁO SAI" if bao_het and not sach else "")})
        try:
            TG.xem_anh(CS, rid, "Ảnh", TG.download(st["anh"][0]))
        except BaseException as e:
            print("cua_hang: ảnh chốt ca lỗi", e, flush=True)
        TK.PEND.pop(f"{c}:{mid}", None)
        thieu = [k for k, t in zip(CHECK, st["tick"]) if not t]
        st.pop("kiem", None)
        tedit(c, mid, cs_text(st) + "\n\n📤 Đã ghi Sheet" + (f" · ⚠️ chưa tick: {', '.join(thieu)}" if thieu else " · checklist đủ ✅")
              + f"\n🤖 Bot kiểm: {kq}")
        if not sach:
            ql = [(f"Quản lý", i) for i in sorted(TK.duyet_ids())]
            dau = (f"🚨 <b>{esc(st['who'])} báo ĐÃ XỬ LÝ HẾT nhưng bot kiểm còn sót</b>" if bao_het
                   else f"⚠️ <b>{esc(st['who'])} chốt {esc(st.get('ca', ''))} còn việc chưa xử lý</b>")
            t = (dau + f" ({len(ca)} tin khách chưa bấm ✅ xong, {len(tk)} ticket đổi trả chờ CS, {len(viec)} việc store chưa xong):\n"
                 + ds_ticket(ca, tk, viec) + f"\n👉 <a href=\"tg://user?id={st['uid']}\">{esc(st['who'])}</a> xử lý + bấm nút xong trên từng tin"
                 + (f"\ncc {tag(ql)}" if ql and bao_het else ""))
            tsend(c, t)
            if bao_het:
                for i in TK.duyet_ids():
                    tsend(i, t)
        TK.STATE_KF.pop("cs" + key, None); CS_STATE.pop(key, None); TK._save()
        for g in [g for g, k in CS_MG.items() if k == key]:
            CS_MG.pop(g, None)
        return
    st["tick"][int(a)] = not st["tick"][int(a)]
    TK.STATE_KF["cs" + key] = st
    answer(cq)
    tedit(c, mid, cs_text(st), cs_btn(key, st))


# ======================= lịch =======================

HT_NHAC_F = os.path.join(TK.ROOT, "logs", "hoatoc_nhac.json")


def nhac_hoatoc(send=False):
    """Hoả tốc đổi size nằm "Chờ đổi size" quá N phút (canh_bao.json hoa_toc_doi_size_phut, mặc định 30)
    → nhắc nhóm Kho, mỗi thẻ tối đa 1 lần / N phút. Gọi từ hen + sau mỗi lần đồng bộ Nhanh."""
    import json
    try:
        phut = int(json.load(open(os.path.join(TK.ROOT, "knowledge", "canh_bao.json"), encoding="utf-8"))
                   .get("hoa_toc_doi_size_phut") or 30)
    except Exception:
        phut = 30
    try:
        da = json.load(open(HT_NHAC_F))
    except Exception:
        da = {}
    ds = []
    for r in rows(VIEC):
        if r.get("Trạng thái") != "Chờ đổi size":
            continue
        try:
            tuoi = (now() - datetime.strptime(str(r.get("Lúc giao"))[:16], "%Y-%m-%d %H:%M")).total_seconds() / 60
        except ValueError:
            continue
        lan = da.get(r["ID"])
        if tuoi >= phut and (not lan or (now() - datetime.strptime(lan, "%Y-%m-%d %H:%M")).total_seconds() >= phut * 60):
            ds.append((r, int(tuoi)))
    if not ds:
        return []
    t = (f"🔥 <b>Hoả tốc CHƯA ĐỔI SIZE</b> (quá {phut} phút) — đổi trên Nhanh rồi bấm ✅ trên thẻ, chưa đổi KHÔNG book ship:\n"
         + "\n".join(f"• {esc(r['ID'])} đơn <code>{esc(r.get('Mã đơn'))}</code> — {esc(str(r.get('Nội dung') or '')[:70])} "
                     f"({p_} phút, {esc(r.get('Người giao'))})" for r, p_ in ds))
    kho = str(TK.E.get("CHAT_ID") or "") or chat()
    if send:
        for r, _ in ds:
            da[r["ID"]] = now().strftime("%Y-%m-%d %H:%M")
        try:
            json.dump(da, open(HT_NHAC_F, "w"))
        except Exception as e:
            print("hoatoc: không ghi được sổ nhắc", e)
    return [(kho, t)]


def hen(send=False):
    h, mi = now().hour, now().minute
    out = []
    try:
        out.extend(nhac_hoatoc(send))
    except Exception as e:
        print("hen: nhắc hoả tốc lỗi", e)
    if h in (10, 14, 18):
        treo = [r for r in rows(VIEC) if r.get("Trạng thái") not in ("Xong", "Huỷ")
                and (now() - datetime.strptime(str(r.get("Lúc giao"))[:16], "%Y-%m-%d %H:%M")).total_seconds() > 7200]
        if treo:
            out.append((chat() or TK.E.get("CHAT_ID"), "⏰ <b>Việc treo quá 2 giờ</b>\n" + "\n".join(
                f"• {esc(r['ID'])} {esc(r.get('Loại'))} đơn {esc(r.get('Mã đơn'))} — {esc(r.get('Trạng thái'))} "
                f"({esc(r.get('Người giao'))})" for r in treo[:25])))
        try:   # ticket đổi trả kẹt quá hạn ở bất kỳ bước nào → nhóm phải làm (canh_bao.json ticket_han_gio)
            out.extend(TK.nhac_tre(im=True).items())
        except Exception as e:
            print("hen: nhắc ticket quá hạn lỗi", e)
        try:   # hàng hoàn kho đã nhận mà Nhanh chưa nhập hoàn (nhap_hoan.py)
            import nhap_hoan as NHH
            out.extend(NHH.nhac())
        except Exception as e:
            print("hen: nhắc nhập hoàn lỗi", e)
    if h == 10:   # checklist đầu ca kho chưa tick đủ → nhắc nhóm kho + chủ shop
        try:
            import kho_flow as KF
            st = KF.dc_st()
            chua = [c for c, t in zip(KF.DAU_CA, st["tick"]) if not t]
            if chua and TK.E.get("CHAT_ID"):
                t = "⏰ <b>10h — đầu ca kho chưa xong</b>: " + "; ".join(esc(c) for c in chua) + "\nGõ /dauca để tick."
                out.append((TK.E.get("CHAT_ID"), t))
                for o in TK.duyet_ids():
                    out.append((o, t))
        except Exception as e:
            print("hen: checklist kho lỗi", e)
    if h == 21 and mi < 45:
        gui_so_ck(send)
    if h in (15, 21) and mi >= 45 and chat():   # cuối ca NVBH: nhắc người trong ca chốt ca
        ca = "Ca 1" if h == 15 else "Ca 2"
        if not [r for r in rows(CS) if r.get("Ngày") == ngay() and r.get("Ca") == ca]:
            ds = nvbh_ca(ca, now())
            out.append((chat(), f"🕙 {tag(ds) or 'NVBH'} ơi chốt {ca}: gõ <code>/chotca meta 0 tiktok 0 shopee 0 oa 0 zalo 0</code> "
                                "rồi <b>trả lời phiếu bằng ảnh store</b> + tick checklist — mục cuối: đã xử lý hết việc (bot tự kiểm lại)." + pn_nhac(ca)))
        if h == 21:   # 21:50 cuối ca 2: kiểm kho Phú Nhuận (chỉ khi hôm nay PN có đi hàng; chủ shop 21/11)
            try:
                import kho_flow as KF
                if send:
                    KF.gui_the_pn(chat(), tag(nvbh_ca("Ca 2", now())))
                else:
                    print(KF.tin_kiem_pn())
            except Exception as e:
                print("hen: kiểm kho PN lỗi", e)
    if (h, mi >= 15) in ((16, True), (22, True)) and chat():   # quá giờ chưa chốt → báo quản lý
        ca = "Ca 1" if h == 16 else "Ca 2"
        if not [r for r in rows(CS) if r.get("Ngày") == ngay() and r.get("Ca") == ca]:
            ds = nvbh_ca(ca, now().replace(hour=10 if ca == "Ca 1" else 16))
            t = f"⏰ {ca} NVBH ({tag(ds) or 'chưa rõ người'}) <b>chưa chốt ca</b>. Gõ /chotca giúp nhé."
            out.append((chat(), t))
            for o in TK.duyet_ids():
                out.append((o, t))
    if h == 22 and mi >= 15 and chat():   # 22:20 kho PN có đi hàng mà chưa kiểm → nhắc nhóm + quản lý
        try:
            import kho_flow as KF
            ds = KF.ds_kiem_pn()
            if ds and not any(r.get("Ngày") == ngay() and r.get("Kho") == "PN" for r in rows(KF.KIEM)):
                t = f"⏰ Kho Phú Nhuận hôm nay đi {len(ds)} mã mà <b>chưa kiểm kho</b> ({tag(nvbh_ca('Ca 2', now().replace(hour=16)))}). Gõ /kiemkho giúp nhé."
                out.append((chat(), t))
                for o in TK.duyet_ids():
                    out.append((o, t))
        except Exception as e:
            print("hen: nhắc kiểm PN lỗi", e)
    if now().weekday() == 6 and h == 22:
        out.append((TK.duyet_ids() and sorted(TK.duyet_ids())[0], bao_cao_tuan()))
    for c, t in out:
        print(re.sub(r"<[^>]+>", "", t))
        if send and c:
            tsend(c, t)


def bao_cao_tuan():
    t0 = (now() - timedelta(days=7)).strftime("%Y-%m-%d")
    k = [r for r in rows(KET) if str(r.get("Ngày", "")) >= t0]
    chi = {}
    for r in k:
        if r.get("Loại") == "Chi":
            chi[r.get("Loại chi") or "Khác"] = chi.get(r.get("Loại chi") or "Khác", 0) + TK.tien(r.get("Số tiền"))
    kc = [r for r in k if r.get("Loại") == "Kết ca"]
    lech = [r for r in k if TK.tien(r.get("Lệch"))]
    ck = [r for r in rows(CK) if str(r.get("Ngày", "")) >= t0]
    cs = [r for r in rows(CS) if str(r.get("Ngày", "")) >= t0]
    return ("📊 <b>Tuần cửa hàng + CS</b>\n"
            f"Thu: TM {tien(sum(TK.tien(r.get('Thu TM')) for r in kc))} · CK {tien(sum(TK.tien(r.get('Thu CK')) for r in kc))}"
            f" · thẻ {tien(sum(TK.tien(r.get('Thu thẻ')) for r in kc))}\n"
            f"Chi két: " + ", ".join(f"{a} {tien(b)}" for a, b in sorted(chi.items(), key=lambda x: -x[1])) + "\n"
            f"Két lệch: {len(lech)} lần" + (" (" + ", ".join(f"{esc(r.get('Ngày'))[5:]} {tien(r.get('Lệch'))}" for r in lech[:6]) + ")" if lech else "")
            + f"\nBill CK: {len(ck)} ({tien(sum(TK.tien(r.get('Số tiền')) for r in ck))}), chưa xác nhận "
              f"{len([r for r in ck if not r.get('Chủ shop xác nhận')])}\n"
            f"NVBH chốt ca: {len(cs)}/14 ca, báo hết ticket mà bot thấy sót: {len([r for r in cs if 'BÁO SAI' in str(r.get('Bot kiểm') or '')])}, ca còn việc tồn: {len([r for r in cs if r.get('Còn tồn việc')])}")


def setup():
    TG.kho("setup", tables={TG.sname(KET): KET_COLS, TG.sname(CK): CK_COLS, TG.sname(VIEC): VIEC_COLS,
                            TG.sname(CS): CS_COLS})


TK.EXT_CMDS.update({"/moca": moca, "/chi": chi, "/thu": thu, "/ketca": ketca, "/ket": ket, "/bill": bill,
                    "/billthieu": billthieu, "/goi": lambda m, a: giao_viec(m, a, "/goi"),
                    "/note": lambda m, a: giao_viec(m, a, "/note"), "/hoatoc": lambda m, a: giao_viec(m, a, "/hoatoc"),
                    "/chotca": chotca})
TK.EXT_NHOM.update({k: ("CH_CHAT_ID",) for k in ("/moca", "/chi", "/thu", "/ketca", "/ket", "/bill", "/billthieu",
                                                   "/goi", "/chotca")})
TK.EXT_NHOM.update({k: ("CHAT_ID", "TICKET_CHAT_ID", "CH_CHAT_ID") for k in ("/note", "/hoatoc")})
TK.EXT_CB["ch"] = on_cb
TK.EXT_REPLY.update({"ch_anh": on_reply, "cs_anh": cs_anh})

if __name__ == "__main__":
    import lark as Lk
    TK.init(Lk.load_env(), start_worker=False)
    a = sys.argv[1:] or ["help"]
    if a[0] == "setup":
        setup(); print("đã tạo bảng", KET, CK, VIEC, CS)
    elif a[0] == "doanhthu":   # JSON doanh thu từng lần kết ca (cho bot HCNS xếp rank NVBH): doanhthu YYYY-MM-DD YYYY-MM-DD
        import json as _j
        tu, den = (a[1], a[2]) if len(a) > 2 else (ngay(), ngay())
        out = []
        for r in rows(KET):
            if r.get("Loại") != "Kết ca" or not (tu <= str(r.get("Ngày", ""))[:10] <= den):
                continue
            tong = sum(TK.tien(r.get(k)) for k in ("Thu TM", "Thu CK", "Thu thẻ"))
            out.append({"ngay": str(r.get("Ngày"))[:10], "gio": str(r.get("Giờ", "")), "tong": tong, "nguoi": r.get("Người", "")})
        print(_j.dumps(out, ensure_ascii=False))
    elif a[0] == "hen":
        hen("--send" in a)
    elif a[0] == "hoatoc":   # sau mỗi lần đồng bộ Nhanh (nhanh.py sau_sync): hoả tốc đổi size chưa đổi quá N phút
        for c_, t_ in nhac_hoatoc("--send" in a):
            print(re.sub(r"<[^>]+>", "", t_))
            if "--send" in a and c_:
                tsend(c_, t_)
    elif a[0] == "soCK":
        gui_so_ck("--send" in a)
    else:
        print(__doc__)
