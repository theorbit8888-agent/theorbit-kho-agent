#!/usr/bin/env python3
"""TICKET CS trên Telegram + Google Sheet (thay Lark Base "ORBIT - CS - Danh sách Ticket CS", 12 bảng gộp 1).

Chạy chung listener bot kho (@theorbit_kho_bot): listener.py gọi TG.poll(..., pre=ticket.on_update).
Luồng cố định có nút bấm, KHÔNG gọi Claude → nhanh, không tốn quota.

Loại ticket (gộp 12 bảng Lark):
  /doi      Đổi hàng sau giao (DHS)        /doitruoc Đổi trước khi giao (DHT)
  /tra      Trả hàng hoàn tiền (THT)        /doihoan  Đòi hàng hoàn: đơn bom, đơn đổi quá hạn (DHH)
  /rate     Rate tiêu cực (RTC)             /suco     Sự cố giao: bưu tá ký toàn phần, GH1P sai, thất lạc (SCG)
  /hoan <MVĐ|mã đơn>  kho báo hàng hoàn về → ghép đúng ticket (không có thì mở HHV cho CS gắn đơn)
  /xem <ID|mã đơn|MVĐ>   /dangdo   /tk (menu)
Mở ticket = nhắn RIÊNG với bot (có SĐT/địa chỉ). Nhóm "Đổi trả" chỉ thấy thẻ ticket không có SĐT/địa chỉ.
Lỗi do KHO → báo ngay trong nhóm + nhắn chủ shop, nút Phạt / Không phạt / Kho giải trình.

CLI (không cần listener):
  python3 tools/ticket.py setup          # tạo bảng trên Sheet
  python3 tools/ticket.py nhac [--send]  # nhắc 9h: quá 12 ngày chưa hoàn về, chờ gọi, chờ duyệt, phạt kho; T2 thêm báo cáo tuần
Env (~/.config/orbit-kho/lark.env): TICKET_CHAT_ID, OWNER_TELE_ID, tuỳ chọn TICKET_DUYET_IDS (cách nhau dấu phẩy),
PHI_SHIP (mặc định 25000), NGUONG_DUYET (mặc định 100000), QUA_HAN_HOAN (mặc định 12 ngày).
"""
import html, json, os, queue, re, sys, threading, time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orbit_tg as TG  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BANG = "TK · TICKET CS"
COLS = ["ID", "Loại", "Trạng thái", "Ngày tạo", "Người tạo", "Kênh", "Mã đơn", "Tên KH", "SĐT KH", "Địa chỉ KH",
        "SKU khách đang cầm", "SKU đổi sang", "Tồn SKU đổi", "Lý do", "Lỗi do", "Chi tiết", "Ảnh", "Ảnh (xem)",
        "Chênh giá KH trả thêm", "Phí ship shop trả", "Phí ship KH trả", "Tiền hoàn KH", "Tổng chi phí shop",
        "Gọi KH", "MVĐ đi", "MVĐ hoàn về", "Ngày gửi đi", "Ngày hàng hoàn về", "Tình trạng hàng hoàn",
        "Người nhận hoàn", "Ảnh hàng hoàn", "Ảnh hàng hoàn (xem)", "Nhập kho QLBH", "Cần duyệt", "Duyệt",
        "Phạt kho", "Kho giải trình", "Ngày đóng", "Thẻ tin", "Lịch sử"]
DONG = ("Đóng", "Đã huỷ")

KENH = ["TikTok", "Shopee", "Website", "Facebook", "Khác"]
LY_DO = {  # lý do -> lỗi do ai
    "Kho gửi sai size/mẫu/màu": "Kho", "Kho gửi thiếu hàng": "Kho", "Hàng lỗi sản xuất": "Sản xuất",
    "Hư hỏng khi vận chuyển": "ĐVVC", "KH đổi size/mẫu (không lỗi)": "Khách", "Khác": "Chưa rõ"}
Q = {
    "ma": ("Mã đơn", "text", "Mã đơn trên sàn / mã đơn web?"),
    "kenh": ("Kênh", "choice", "Kênh bán?", KENH),
    "ten": ("Tên KH", "text", "Tên khách?"),
    "user": ("Tên KH", "text", "Tên / username khách?"),
    "sdt": ("SĐT KH", "phone", "SĐT khách? (chỉ lưu Sheet, không hiện trong nhóm)"),
    "dc": ("Địa chỉ KH", "text", "Địa chỉ nhận hàng đổi?"),
    "sku_cu": ("SKU khách đang cầm", "text", "SKU khách đang cầm (mẫu-màu-size)?"),
    "sku_moi": ("SKU đổi sang", "sku", "Đổi sang SKU nào?"),
    "ly_do": ("Lý do", "choice", "Lý do?", list(LY_DO)),
    "ly_do_truoc": ("Lý do", "choice", "Lý do đổi trước khi giao?",
                    ["KH đổi ý trước khi giao", "Live/CS tư vấn sai", "Lên đơn nhầm", "Khác"]),
    "ly_do_doi": ("Lý do", "choice", "Đòi hàng hoàn vì?",
                  ["Đơn bom (KH không nhận)", "Đơn đổi quá hạn chưa hoàn về", "Hàng hoàn thất lạc", "Khác"]),
    "suco": ("Lý do", "choice", "Sự cố gì?",
             ["Bưu tá ký nhận toàn phần (không thu hàng cũ)", "Giao 1 phần sai", "Thất lạc", "Hư hỏng khi giao",
              "Khác"]),
    "sao": ("Lý do", "choice", "Khách đánh giá mấy sao?", ["1 sao", "2 sao", "3 sao"]),
    "chi_tiet": ("Chi tiết", "text?", "Mô tả ngắn (gõ - nếu không có)"),
    "noi_dung": ("Chi tiết", "text?", "Nội dung đánh giá của khách (gõ - nếu không có)"),
    "anh": ("Ảnh", "photo", "Gửi ảnh (lỗi / tag / kiện / đánh giá…). Gửi xong bấm ✅ Xong ảnh."),
    "chenh": ("Chênh giá KH trả thêm", "num", "Khách trả thêm bao nhiêu tiền chênh giá? (0 nếu cùng giá)"),
    "tien": ("Tiền hoàn KH", "num", "Số tiền hoàn cho khách?"),
    "mvd": ("MVĐ hoàn về", "text?", "Mã vận đơn của kiện (gõ - nếu chưa có)?"),
}
LOAI = {  # mã: (tiền tố, tên, câu hỏi, trạng thái đầu)
    "doi": ("DHS", "Đổi hàng sau giao",
            ["ma", "kenh", "ten", "sdt", "dc", "sku_cu", "sku_moi", "ly_do", "chi_tiet", "anh", "chenh"], "Chờ gọi KH"),
    "doitruoc": ("DHT", "Đổi trước khi giao", ["ma", "kenh", "sku_cu", "sku_moi", "ly_do_truoc", "chi_tiet"],
                 "Chờ kho đổi trong đơn"),
    "tra": ("THT", "Trả hàng hoàn tiền", ["ma", "kenh", "ten", "sdt", "sku_cu", "ly_do", "chi_tiet", "anh", "tien"],
            "Chờ duyệt"),
    "doihoan": ("DHH", "Đòi hàng hoàn", ["ma", "kenh", "mvd", "ly_do_doi", "chi_tiet"], "Chờ đòi ĐVVC"),
    "rate": ("RTC", "Rate tiêu cực", ["ma", "kenh", "user", "sao", "noi_dung", "anh"], "Chờ liên hệ KH"),
    "suco": ("SCG", "Sự cố giao hàng", ["ma", "kenh", "mvd", "suco", "chi_tiet", "anh"], "Chờ khiếu nại ĐVVC"),
    "hoan": ("HHV", "Hàng hoàn về (chưa rõ ticket)", [], "Chờ CS gắn đơn"),
}
TEN_LOAI = {v[1]: k for k, v in LOAI.items()}
BTN = {
    "Chờ gọi KH": [("📞 Đã gọi – KH đồng ý", "goi_ok"), ("📵 Chưa nghe máy", "goi_ko"), ("🗑 KH huỷ đổi", "huy")],
    "Chờ tạo đơn đi": [("📦 Đã tạo đơn đi (gõ MVĐ)", "don_di")],
    "Chờ hàng hoàn về": [("📥 Kho nhận hàng hoàn", "nhan"), ("📣 Đã đòi ĐVVC", "doi_dvvc")],
    "Chờ nhập kho QLBH": [("✅ Đã nhập kho QLBH", "nhap")],
    "Chờ kho đổi trong đơn": [("✅ Kho đã đổi trong đơn", "doi_xong"), ("🚚 Đơn đã đi rồi", "da_di")],
    "Chờ duyệt": [("✅ Duyệt", "duyet"), ("❌ Từ chối", "tuchoi")],
    "Chờ hoàn tiền": [("💸 Đã hoàn tiền KH", "hoan_tien")],
    "Chờ đòi ĐVVC": [("📣 Đã đòi ĐVVC", "doi_dvvc"), ("📥 Kho nhận hàng hoàn", "nhan")],
    "Chờ liên hệ KH": [("✅ Đã xử lý cho KH", "xl_ok"), ("➖ Không xử lý được", "xl_ko")],
    "Chờ khiếu nại ĐVVC": [("📣 Đã khiếu nại ĐVVC", "kn")],
    "Chờ ĐVVC trả lời": [("✅ Đã giải quyết", "xl_ok"), ("💸 ĐVVC đền tiền", "den")],
    "Chờ CS gắn đơn": [("🔗 Gắn mã đơn / ticket", "gan"), ("✅ Đã nhập kho QLBH", "nhap")],
}
TINH_TRANG = ["✅ Nguyên vẹn", "⚠️ Không nguyên vẹn (lỗi/bẩn)", "🔀 Bị tráo hàng", "➖ Thiếu hàng"]
XAU = TINH_TRANG[1:]
LENH = ("/tk", "/ticket", "/doi", "/doitruoc", "/tra", "/doihoan", "/rate", "/suco", "/hoan", "/xem", "/dangdo",
        "/huy", "/start")

E = {}
ME = {}
WIZ = {}    # uid -> phiếu đang hỏi
PEND = {}   # "chat:mid" của tin bot hỏi -> {id, f, u}
JOBS = queue.Queue()
_MEM = {}   # uid -> (lúc, là thành viên?)
_LOCK = threading.Lock()
STATE = os.path.join(ROOT, "logs", "ticket_state.json")


# ======================= khởi động =======================

def init(env, start_worker=True):
    E.clear(); E.update(env)
    try:
        st = json.load(open(STATE))
        WIZ.update({int(k): v for k, v in st.get("wiz", {}).items()}); PEND.update(st.get("pend", {}))
    except Exception:
        pass
    if start_worker:
        threading.Thread(target=_worker, daemon=True).start()


def _save():
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    keep = dict(list(PEND.items())[-300:])
    PEND.clear(); PEND.update(keep)
    json.dump({"wiz": WIZ, "pend": PEND}, open(STATE, "w"), ensure_ascii=False)


def tchat():
    return str(E.get("TICKET_CHAT_ID") or "")


def duyet_ids():
    return {x.strip() for x in (E.get("TICKET_DUYET_IDS", "") + "," + E.get("OWNER_TELE_ID", "")).split(",")
            if x.strip()}


def phi():
    return int(E.get("PHI_SHIP") or 25000)


def me():
    if not ME:
        ME.update(TG.must(TG.api("getMe"), "getMe"))
    return ME


# ======================= Telegram nhỏ =======================

def tsend(chat, text, btns=None, reply_to=None, force=False):
    body = {"chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
    if btns:
        body["reply_markup"] = {"inline_keyboard": btns}
    elif force:
        body["reply_markup"] = {"force_reply": True, "selective": True}
    if reply_to:
        body["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    r = TG.api("sendMessage", body)
    if not r.get("ok"):
        print(time.strftime("%H:%M"), "ticket: gửi lỗi", chat, r.get("description"), flush=True)
        return None
    TG.save_msg(r["result"])
    return r["result"]["message_id"]


def tedit(chat, mid, text, btns=None):
    body = {"chat_id": chat, "message_id": mid, "text": text[:4000], "parse_mode": "HTML",
            "disable_web_page_preview": True, "reply_markup": {"inline_keyboard": btns or []}}
    r = TG.api("editMessageText", body)
    return r.get("ok") or "not modified" in str(r.get("description"))


def answer(cq, text=None, alert=False):
    TG.api("answerCallbackQuery", {"callback_query_id": cq["id"], **({"text": text[:190], "show_alert": alert}
                                                                       if text else {})})


def esc(x):
    return html.escape(str(x or ""))


def ten(u):
    return " ".join(x for x in ((u or {}).get("first_name"), (u or {}).get("last_name")) if x) or str((u or {}).get("id"))


def is_member(uid):
    uid = str(uid)
    if uid in duyet_ids():
        return True
    if not tchat():
        return False
    hit = _MEM.get(uid)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    r = TG.api("getChatMember", {"chat_id": tchat(), "user_id": int(uid)})
    ok = r.get("ok") and r["result"]["status"] in ("creator", "administrator", "member", "restricted")
    _MEM[uid] = (time.time(), bool(ok))
    return bool(ok)


# ======================= Sheet =======================

def setup():
    TG.kho("setup", tables={TG.sname(BANG): COLS})


def all_rows(fresh=True):
    return TG.rows(BANG, fresh=fresh)


def find(key, open_only=False):
    """Tìm ticket theo ID / mã đơn / MVĐ (mới nhất trước)."""
    k = str(key).strip().lower().lstrip("#")
    if not k:
        return []
    out = []
    for r in reversed(all_rows()):
        if open_only and r.get("Trạng thái") in DONG:
            continue
        vals = [str(r.get(c, "")).strip().lower().lstrip("#") for c in ("ID", "Mã đơn", "MVĐ đi", "MVĐ hoàn về")]
        if k in vals:
            out.append(r)
    return out


def get(tid):
    for r in all_rows():
        if r.get("ID") == tid:
            return r
    return None


def upd(r, fields, log=None, who=""):
    if log:
        fields["Lịch sử"] = (str(r.get("Lịch sử") or "") + f"\n{now()} {who}: {log}").strip()
    TG.kho("update", table=TG.sname(BANG), id=r["_id"], fields=fields)
    TG._CACHE.pop(TG.sname(BANG), None)
    r.update(fields)
    return r


def now():
    return datetime.now().strftime("%d/%m %H:%M")


def today():
    return datetime.now().strftime("%Y-%m-%d")


def new_id(prefix):
    n = 20000
    for r in all_rows():
        m = re.search(r"(\d+)$", str(r.get("ID", "")))
        if m:
            n = max(n, int(m[1]))
    return f"{prefix}{n + 1}"


def tien(v):
    try:
        return int(float(str(v or 0).replace(",", "")))
    except ValueError:
        return parse_num(str(v)) or 0


def vnd(v):
    return f"{tien(v):,}".replace(",", ".") + "đ"


def parse_num(s):
    s = s.lower().replace(" ", "").replace("đ", "").replace("vnd", "")
    m = re.match(r"^(\d+(?:[.,]\d+)?)(k|nghìn|ngàn|tr|triệu)?$", s)
    if not m:
        return None
    x = m[1]
    if m[2]:
        x = float(x.replace(",", "."))
        return int(x * (1000 if m[2] in ("k", "nghìn", "ngàn") else 1_000_000))
    return int(x.replace(".", "").replace(",", ""))


def doan_kenh(ma):
    ma = ma.strip()
    if re.fullmatch(r"5\d{16,18}", ma):
        return "TikTok"
    if re.fullmatch(r"\d{6}[A-Z0-9]{6,10}", ma.upper()):
        return "Shopee"
    if ma.startswith("#"):
        return "Website"
    return None


def ton(sku):
    """Tra tồn trong bảng 05 TÌNH TRẠNG HÀNG của kho (gần đúng theo chữ)."""
    try:
        rs = TG.rows("05 · TÌNH TRẠNG HÀNG")
    except BaseException:
        return ""
    toks = [t for t in re.split(r"[\s\-_/]+", sku.lower()) if t]
    best = []
    for r in rs:
        txt = f"{r.get('Tên sản phẩm', '')} {r.get('Size/màu', '')}".lower()
        hit = sum(1 for t in toks if t in txt)
        if hit:
            best.append((hit, f"{r.get('Tên sản phẩm', '')} {r.get('Size/màu', '')}: {r.get('Tình trạng', '?')}"))
    best.sort(key=lambda x: -x[0])
    return "; ".join(b for _, b in best[:2]) if best and best[0][0] >= max(1, len(toks) - 1) else ""


def nhanh_link(sku):
    import urllib.parse
    return ("https://nhanh.vn/product/item/index?storeId=143192&depotId%5B%5D=146426&name="
            + urllib.parse.quote(sku) + "&remainByPr=0")


# ======================= thẻ ticket =======================

def mask(x):
    x = str(x or "")
    return ("…" + x[-4:]) if len(x) > 5 else x


def card(r, rieng=False):
    loai = r.get("Loại", "")
    L = [f"🎫 <b>{esc(r['ID'])}</b> · {esc(loai)}",
         (f"Kênh: {esc(r.get('Kênh'))} · " if r.get("Kênh") else "")
         + (f"Đơn: <code>{esc(r.get('Mã đơn'))}</code>" if r.get("Mã đơn") else "Đơn: (chưa rõ)")]
    if rieng and (r.get("Tên KH") or r.get("SĐT KH") or r.get("Địa chỉ KH")):
        L.append(f"KH: {esc(r.get('Tên KH'))} · {esc(r.get('SĐT KH'))}\n{esc(r.get('Địa chỉ KH'))}")
    if r.get("SKU khách đang cầm") or r.get("SKU đổi sang"):
        s = esc(r.get("SKU khách đang cầm"))
        if r.get("SKU đổi sang"):
            s += f" → <b>{esc(r.get('SKU đổi sang'))}</b>"
            if r.get("Tồn SKU đổi"):
                s += f" ({esc(r.get('Tồn SKU đổi'))})"
        L.append("SKU: " + s)
    if r.get("Lý do"):
        ld = f"Lý do: {esc(r.get('Lý do'))}"
        if r.get("Lỗi do") and r.get("Lỗi do") not in ("Chưa rõ",):
            ld += f" → lỗi <b>{esc(r.get('Lỗi do'))}</b>"
        L.append(ld)
    if r.get("Chi tiết"):
        L.append(f"📝 {esc(r.get('Chi tiết'))[:300]}")
    tienL = []
    if tien(r.get("Phí ship shop trả")) or tien(r.get("Phí ship KH trả")):
        tienL.append(f"ship shop {vnd(r.get('Phí ship shop trả'))} / KH {vnd(r.get('Phí ship KH trả'))}")
    if tien(r.get("Chênh giá KH trả thêm")):
        tienL.append(f"KH bù {vnd(r.get('Chênh giá KH trả thêm'))} (COD)")
    if tien(r.get("Tiền hoàn KH")):
        tienL.append(f"hoàn KH {vnd(r.get('Tiền hoàn KH'))}")
    if tienL:
        L.append("💰 " + " · ".join(tienL))
    if r.get("MVĐ đi") or r.get("MVĐ hoàn về"):
        f = (lambda x: esc(x)) if rieng else mask
        L.append(f"🚚 MVĐ đi {f(r.get('MVĐ đi')) or '-'} · hoàn về {f(r.get('MVĐ hoàn về')) or '-'}"
                 + (f" (gửi {esc(r.get('Ngày gửi đi'))})" if r.get("Ngày gửi đi") else ""))
    if r.get("Tình trạng hàng hoàn"):
        L.append(f"📥 Hàng hoàn: {esc(r.get('Tình trạng hàng hoàn'))} ({esc(r.get('Ngày hàng hoàn về'))}, "
                 f"{esc(r.get('Người nhận hoàn'))})")
    if r.get("Phạt kho"):
        L.append(f"⚖️ Phạt kho: {esc(r.get('Phạt kho'))}")
    if r.get("Duyệt"):
        L.append(f"🧾 {esc(r.get('Duyệt'))}")
    L.append(f"➡️ <b>{esc(r.get('Trạng thái'))}</b> · tạo bởi {esc(r.get('Người tạo'))}")
    return "\n".join(L)


def btns(r):
    st = r.get("Trạng thái", "")
    b = BTN.get(st, [])
    if r.get("Loại") == LOAI["tra"][1] and st == "Chờ hàng hoàn về":
        b = [b[0]]
    rows_ = [[{"text": t, "callback_data": f"tk:a:{r['ID']}:{a}"}] for t, a in b]
    return rows_


def refresh(r, note=None, notify=False):
    """Sửa thẻ trong nhóm theo trạng thái mới; notify=True: thêm 1 tin ngắn trả lời thẻ (có thông báo)."""
    ref = str(r.get("Thẻ tin") or "")
    m = re.match(r"tg:(-?\d+):(\d+)$", ref)
    if m:
        tedit(m[1], int(m[2]), card(r), btns(r))
        if notify and note:
            tsend(m[1], note, reply_to=int(m[2]))
    elif tchat():
        mid = tsend(tchat(), card(r), btns(r))
        if mid:
            upd(r, {"Thẻ tin": TG.mk(tchat(), mid)})


# ======================= phiếu hỏi (nhắn riêng) =======================

def wiz_start(uid, chat, loai, by):
    WIZ[uid] = {"loai": loai, "i": 0, "d": {}, "anh": [], "chat": chat, "by": by}
    _save()
    pre, name, qs, _ = LOAI[loai]
    tsend(chat, f"🎫 <b>{name}</b> — {len(qs)} câu. Gõ /huy để dừng.")
    ask(uid)


def ask(uid):
    w = WIZ[uid]
    qs = LOAI[w["loai"]][2]
    if w["i"] >= len(qs):
        return confirm(uid)
    q = Q[qs[w["i"]]]
    col, kind, text = q[0], q[1], q[2]
    b = None
    if kind == "choice":
        opts = list(q[3])
        if qs[w["i"]] == "kenh" and w.get("doan"):
            opts.remove(w["doan"]); opts.insert(0, w["doan"])
        w["opts"] = opts
        b = [[{"text": o + (" (đoán theo mã đơn)" if k == 0 and w.get("doan") == o else ""),
               "callback_data": f"tk:w:{w['i']}:{k}"}] for k, o in enumerate(opts)]
    elif kind == "photo":
        b = [[{"text": "✅ Xong ảnh", "callback_data": f"tk:w:{w['i']}:xong"},
              {"text": "Không có ảnh", "callback_data": f"tk:w:{w['i']}:bo"}]]
    _save()
    tsend(w["chat"], f"<b>{w['i'] + 1}/{len(qs)}</b> {esc(text)}", b)


def wiz_text(uid, text):
    w = WIZ[uid]
    qs = LOAI[w["loai"]][2]
    key = qs[w["i"]] if w["i"] < len(qs) else None
    if not key:
        return tsend(w["chat"], "Bấm ✅ Tạo ticket hoặc 🗑 Huỷ ở tin trên.")
    col, kind = Q[key][0], Q[key][1]
    t = text.strip()
    if kind == "choice":
        return tsend(w["chat"], "Bấm 1 nút ở câu trên giúp mình nhé.")
    if kind == "photo":
        if t in ("-", "không", "ko", "xong"):
            return wiz_choice(uid, w["i"], "xong" if w["anh"] or t == "xong" else "bo")
        return tsend(w["chat"], "Gửi ảnh, rồi bấm ✅ Xong ảnh (hoặc Không có ảnh).")
    if kind == "text?" and t == "-":
        t = ""
    elif kind == "phone":
        d = re.sub(r"\D", "", t)
        if d.startswith("84"):
            d = "0" + d[2:]
        if not re.fullmatch(r"0\d{9}", d):
            return tsend(w["chat"], "SĐT chưa đúng (10 số, bắt đầu bằng 0). Gõ lại giúp mình.")
        t = d
    elif kind == "num":
        n = parse_num(t)
        if n is None:
            return tsend(w["chat"], "Gõ số tiền thôi nhé (VD 0, 25000, 50k).")
        t = n
    elif len(t) < 2 and kind != "text?":
        return tsend(w["chat"], "Ngắn quá, gõ lại giúp mình.")
    w["d"][col] = t
    if key == "ma":
        w["doan"] = doan_kenh(t)
        trung = find(t, open_only=True)
        if trung and not w.get("trung_ok"):
            w["trung"] = trung[0]["ID"]
            _save()
            return tsend(w["chat"], f"⚠️ Mã đơn này đang có ticket <b>{esc(trung[0]['ID'])}</b> "
                                    f"({esc(trung[0].get('Loại'))} · {esc(trung[0].get('Trạng thái'))}). Vẫn tạo mới?",
                         [[{"text": "Vẫn tạo mới", "callback_data": f"tk:w:{w['i']}:trung_ok"},
                           {"text": "🗑 Thôi", "callback_data": f"tk:w:{w['i']}:huy"}]])
    if key == "sku_moi":
        w["d"]["Tồn SKU đổi"] = ton(t)
        tsend(w["chat"], ("📦 Tồn theo bảng kho: " + esc(w["d"]["Tồn SKU đổi"])) if w["d"]["Tồn SKU đổi"]
              else f"📦 Không thấy mẫu này trong bảng tình trạng hàng — check Nhanh: {esc(nhanh_link(t))}")
    w["i"] += 1
    ask(uid)


def wiz_photo(uid, m):
    w = WIZ[uid]
    qs = LOAI[w["loai"]][2]
    if w["i"] >= len(qs) or Q[qs[w["i"]]][1] != "photo":
        return tsend(w["chat"], "Chưa tới câu gửi ảnh — trả lời câu đang hỏi trước nhé.")
    w["anh"].append(max(m["photo"], key=lambda p: p.get("file_size", 0))["file_id"])
    _save()
    g = m.get("media_group_id")
    if g and w.get("g") == g:
        return
    w["g"] = g
    tsend(w["chat"], f"📷 Đã nhận ảnh. Gửi thêm hoặc bấm ✅ Xong ảnh.",
          [[{"text": "✅ Xong ảnh", "callback_data": f"tk:w:{w['i']}:xong"}]])


def wiz_choice(uid, i, val, by=None):
    w = WIZ.get(uid)
    if not w:
        return
    if val == "huy":
        WIZ.pop(uid, None); _save()
        return tsend(w["chat"], "Đã huỷ phiếu.")
    if val == "tao":
        return create(uid)
    if val == "lam_lai":
        return wiz_start(uid, w["chat"], w["loai"], w["by"])
    if int(i) != w["i"]:
        return  # nút cũ
    qs = LOAI[w["loai"]][2]
    key = qs[w["i"]]
    if val == "trung_ok":
        w["trung_ok"] = True; w["i"] += 1; return ask(uid)
    if Q[key][1] == "photo":
        if val == "xong" and not w["anh"]:
            return tsend(w["chat"], "Chưa có ảnh nào. Gửi ảnh hoặc bấm Không có ảnh.")
        w["i"] += 1
        return ask(uid)
    opt = w.get("opts") or Q[key][3]
    v = opt[int(val)]
    w["d"][Q[key][0]] = v
    tsend(w["chat"], f"→ {esc(v)}")
    w["i"] += 1
    ask(uid)


def tinh_phi(d, loai):
    loi = LY_DO.get(d.get("Lý do", ""), "")
    if loai == "doitruoc":
        loi = {"Lên đơn nhầm": "CS", "Live/CS tư vấn sai": "CS/Live"}.get(d.get("Lý do"), "Khách")
    if loai in ("suco", "doihoan"):
        loi = "ĐVVC" if loai == "suco" else ""
    d["Lỗi do"] = loi
    if loai == "doi":
        shop_loi = loi in ("Kho", "Sản xuất", "ĐVVC")
        d["Phí ship shop trả"] = 2 * phi() if shop_loi else phi()
        d["Phí ship KH trả"] = 0 if shop_loi else phi()
    elif loai == "tra":
        d["Phí ship shop trả"] = phi() if loi in ("Kho", "Sản xuất", "ĐVVC") else 0
    d["Tổng chi phí shop"] = tien(d.get("Phí ship shop trả")) + tien(d.get("Tiền hoàn KH"))
    return d


def confirm(uid):
    w = WIZ[uid]
    d = tinh_phi(w["d"], w["loai"])
    fake = dict(d, ID="(mới)", **{"Loại": LOAI[w["loai"]][1], "Trạng thái": LOAI[w["loai"]][3],
                                 "Người tạo": w["by"]})
    _save()
    tsend(w["chat"], "Kiểm tra lại:\n\n" + card(fake, rieng=True) + (f"\n📷 {len(w['anh'])} ảnh" if w["anh"] else ""),
          [[{"text": "✅ Tạo ticket", "callback_data": "tk:w:0:tao"}],
           [{"text": "✏️ Làm lại", "callback_data": "tk:w:0:lam_lai"}, {"text": "🗑 Huỷ", "callback_data": "tk:w:0:huy"}]])


def create(uid):
    w = WIZ.pop(uid, None)
    _save()
    if not w:
        return
    loai = w["loai"]
    pre, name, _, st = LOAI[loai]
    d = tinh_phi(w["d"], loai)
    with _LOCK:
        tid = new_id(pre)
        row = dict(d, **{"ID": tid, "Loại": name, "Trạng thái": st, "Ngày tạo": datetime.now().strftime("%Y-%m-%d %H:%M"),
                         "Người tạo": w["by"], "Ảnh": ", ".join("tg:" + f for f in w["anh"]),
                         "Cần duyệt": "✓" if loai == "tra" else "",
                         "Phạt kho": "Chờ chủ shop xác nhận" if d.get("Lỗi do") == "Kho" else "",
                         "Lịch sử": f"{now()} {w['by']}: tạo"})
        rid = TG.kho("add", table=TG.sname(BANG), rows=[{k: v for k, v in row.items() if k in COLS}])[0]
        TG._CACHE.pop(TG.sname(BANG), None)
    row["_id"] = rid
    if w["anh"]:
        try:
            TG.xem_anh(BANG, rid, "Ảnh", TG.download(w["anh"][0]))
        except BaseException as e:
            print("ticket: ảnh xem lỗi", e, flush=True)
    refresh(row)
    tsend(w["chat"], f"✅ Đã tạo <b>{tid}</b>" + (" và báo nhóm Đổi trả." if tchat() else
                                                 " (chưa có nhóm Đổi trả: TICKET_CHAT_ID trống)."))
    if loai == "doi":
        tsend(w["chat"], kich_ban(row))
    if row.get("Phạt kho"):
        bao_loi_kho(row)
    if loai == "tra":
        bao_duyet(row, "Hoàn tiền " + vnd(row.get("Tiền hoàn KH")))


def kich_ban(r):
    shop_loi = r.get("Lỗi do") in ("Kho", "Sản xuất", "ĐVVC")
    phi_txt = ("Lần này lỗi bên shop nên shop chịu toàn bộ phí ship ạ." if shop_loi
               else f"Shop hỗ trợ 1 chiều, anh/chị chỉ chịu {vnd(r.get('Phí ship KH trả'))} phí ship ạ.")
    chenh = tien(r.get("Chênh giá KH trả thêm"))
    cod = f" Anh/chị gửi bưu tá thêm {vnd(chenh)} tiền chênh giá giúp em." if chenh else ""
    return ("📞 <b>Kịch bản gọi khách</b> (chỉ gửi cho bạn)\n"
            f"1. Alo, có phải anh/chị {esc(r.get('Tên KH'))} không ạ? Em gọi từ CSKH The ORBIT ({esc(r.get('Kênh'))}).\n"
            f"2. Em hỗ trợ anh/chị đổi sang <b>{esc(r.get('SKU đổi sang'))}</b> đúng không ạ?\n"
            "3. Sản phẩm cũ anh/chị còn tag, chưa giặt chưa ạ?\n"
            "4. 2–3 ngày nữa bưu tá giao hàng mới. Đây là đơn GIAO 1 PHẦN: bưu tá đưa hàng mới và nhận lại hàng cũ, "
            "anh/chị đưa luôn hàng cũ cho bưu tá giúp em.\n"
            f"5. {phi_txt}{cod}\n\n"
            "💬 <b>Tin nhắn nhắc lại</b> (gửi qua kênh shop đang chat với khách):\n"
            f"<code>The ORBIT xác nhận đổi sang {esc(r.get('SKU đổi sang'))}. Khi bưu tá giao hàng mới, anh/chị gửi lại "
            f"hàng cũ (còn tag) cho bưu tá nhé. {phi_txt}{cod}</code>\n\n"
            "Gọi xong bấm nút trên thẻ ticket trong nhóm.")


def bao_loi_kho(r):
    t = (f"⚠️ <b>LỖI KHO</b> · {esc(r['ID'])}\n{esc(r.get('Lý do'))}: {esc(r.get('SKU khách đang cầm'))}"
         + (f" (khách cần {esc(r.get('SKU đổi sang'))})" if r.get("SKU đổi sang") else "")
         + (f"\n📝 {esc(r.get('Chi tiết'))}" if r.get("Chi tiết") else "")
         + f"\nChi phí shop chịu: {vnd(r.get('Tổng chi phí shop'))}\nChờ chủ shop xác nhận phạt.")
    b = [[{"text": "⚖️ Phạt kho", "callback_data": f"tk:a:{r['ID']}:phat"},
          {"text": "🙅 Không phạt", "callback_data": f"tk:a:{r['ID']}:khong_phat"}],
         [{"text": "📝 Kho giải trình", "callback_data": f"tk:a:{r['ID']}:giai_trinh"}]]
    if tchat():
        tsend(tchat(), t, b)
    for u in duyet_ids():
        tsend(u, t, b)


def bao_duyet(r, vi):
    t = f"🧾 <b>Cần duyệt</b> · {esc(r['ID'])} ({esc(r.get('Loại'))})\n{esc(vi)}\n\n" + card(r)
    b = [[{"text": "✅ Duyệt", "callback_data": f"tk:a:{r['ID']}:duyet"},
          {"text": "❌ Từ chối", "callback_data": f"tk:a:{r['ID']}:tuchoi"}]]
    for u in duyet_ids():
        tsend(u, t, b)


# ======================= nút trên thẻ =======================

def finish(r, who):
    """Bước cuối: cần duyệt (hàng hoàn xấu / chi phí > ngưỡng) thì sang Chờ duyệt, không thì Đóng."""
    xau = r.get("Tình trạng hàng hoàn") in XAU
    vuot = tien(r.get("Tổng chi phí shop")) > int(E.get("NGUONG_DUYET") or 100000)
    if (xau or vuot) and not r.get("Duyệt"):
        upd(r, {"Trạng thái": "Chờ duyệt", "Cần duyệt": "✓"}, "chờ duyệt", who)
        bao_duyet(r, ("Hàng hoàn " + r.get("Tình trạng hàng hoàn")) if xau else
                  f"Chi phí shop {vnd(r.get('Tổng chi phí shop'))}")
        return refresh(r, "🧾 Chờ chủ shop duyệt", True)
    upd(r, {"Trạng thái": "Đóng", "Ngày đóng": today()}, "đóng", who)
    refresh(r)


def act(cq, tid, a):
    u = cq["from"]
    who = ten(u)
    uid = str(u["id"])
    r = get(tid)
    if not r:
        return answer(cq, "Không thấy ticket", True)
    chat = cq["message"]["chat"]["id"]
    mid = cq["message"]["message_id"]
    if a in ("duyet", "tuchoi", "phat", "khong_phat") and uid not in duyet_ids():
        return answer(cq, "Chỉ chủ shop / người duyệt bấm được", True)
    if not is_member(uid):
        return answer(cq, "Bạn chưa ở nhóm Đổi trả", True)
    st = r.get("Trạng thái")
    if a in ("phat", "khong_phat"):
        v = "Phạt" if a == "phat" else "Không phạt"
        upd(r, {"Phạt kho": f"{v} ({who} {now()})"}, f"phạt kho: {v}", who)
        answer(cq, v)
        tedit(chat, mid, cq["message"].get("text", "") + f"\n\n⚖️ {v} — {who}")
        refresh(r, f"⚖️ Lỗi kho: <b>{v}</b> ({esc(who)})", True)
        return
    if a == "giai_trinh":
        answer(cq)
        return prompt(chat, mid, tid, "giai_trinh", u, f"📝 {esc(who)} trả lời tin này để giải trình lỗi kho {tid}")
    allowed = [x[1] for x in BTN.get(st, [])]
    if a not in allowed:
        return answer(cq, f"Ticket đang ở bước: {st}", True)
    answer(cq)
    if a == "goi_ok":
        upd(r, {"Gọi KH": f"Đồng ý ({now()})", "Trạng thái": "Chờ tạo đơn đi"}, "gọi KH đồng ý", who)
    elif a == "goi_ko":
        n = str(r.get("Gọi KH") or "").count("chưa nghe") + 1
        upd(r, {"Gọi KH": (str(r.get("Gọi KH") or "") + f" chưa nghe {now()};").strip()}, f"chưa nghe máy lần {n}", who)
        return refresh(r, f"📵 Gọi lần {n} khách chưa nghe ({esc(who)})", True)
    elif a == "huy":
        upd(r, {"Trạng thái": "Đã huỷ", "Ngày đóng": today()}, "huỷ", who)
    elif a == "don_di":
        return prompt(chat, mid, tid, "don_di", u, f"📦 {esc(who)} trả lời tin này: <b>MVĐ đơn đi</b> và "
                                                   "<b>MVĐ hoàn về</b> (nếu có), cách nhau dấu cách")
    elif a == "nhan":
        b = [[{"text": t, "callback_data": f"tk:t:{tid}:{k}"}] for k, t in enumerate(TINH_TRANG)]
        tsend(chat, f"📥 {esc(tid)}: hàng hoàn về tình trạng thế nào?", b, reply_to=mid)
        return
    elif a == "doi_dvvc":
        upd(r, {"Trạng thái": "Chờ hàng hoàn về"} if st == "Chờ đòi ĐVVC" else {}, "đã đòi ĐVVC", who)
        return refresh(r, f"📣 {esc(who)} đã đòi ĐVVC", True)
    elif a == "nhap":
        upd(r, {"Nhập kho QLBH": f"✓ {who} {now()}"}, "nhập kho QLBH", who)
        return finish(r, who)
    elif a == "doi_xong":
        upd(r, {"Trạng thái": "Đóng", "Ngày đóng": today()}, "kho đã đổi trong đơn", who)
    elif a == "da_di":
        upd(r, {"Trạng thái": "Đóng", "Ngày đóng": today()}, "đơn đã đi, không đổi kịp", who)
        refresh(r, "🚚 Đơn đã đi rồi. Khách vẫn muốn đổi → CS mở /doi (đổi sau giao).", True)
        return
    elif a in ("duyet", "tuchoi"):
        ok = a == "duyet"
        upd(r, {"Duyệt": f"{'Duyệt' if ok else 'Từ chối'} bởi {who} {now()}"}, "duyệt" if ok else "từ chối", who)
        if ok and r.get("Loại") == LOAI["tra"][1]:
            upd(r, {"Trạng thái": "Chờ hoàn tiền" if r.get("Ngày hàng hoàn về") else "Chờ hàng hoàn về"})
        else:
            upd(r, {"Trạng thái": "Đóng", "Ngày đóng": today()})
        if str(chat) != tchat():
            tedit(chat, mid, cq["message"].get("text", "") + f"\n\n{'✅ Đã duyệt' if ok else '❌ Đã từ chối'}")
        return refresh(r, f"{'✅ Đã duyệt' if ok else '❌ Từ chối'} ({esc(who)})", True)
    elif a == "hoan_tien":
        upd(r, {"Trạng thái": "Đóng", "Ngày đóng": today()}, "đã hoàn tiền KH", who)
    elif a in ("xl_ok", "xl_ko", "den"):
        v = {"xl_ok": "đã xử lý xong", "xl_ko": "không xử lý được", "den": "ĐVVC đền tiền"}[a]
        upd(r, {"Trạng thái": "Đóng", "Ngày đóng": today()}, v, who)
    elif a == "kn":
        upd(r, {"Trạng thái": "Chờ ĐVVC trả lời"}, "đã khiếu nại ĐVVC", who)
    elif a == "gan":
        return prompt(chat, mid, tid, "gan", u, f"🔗 {esc(who)} trả lời tin này: <b>mã đơn</b> hoặc <b>ID ticket</b>")
    refresh(r)


def tinh_trang(cq, tid, k):
    u = cq["from"]
    who = ten(u)
    if not is_member(u["id"]):
        return answer(cq, "Bạn chưa ở nhóm Đổi trả", True)
    r = get(tid)
    if not r:
        return answer(cq, "Không thấy ticket", True)
    v = TINH_TRANG[int(k)]
    answer(cq, v)
    chat, mid = cq["message"]["chat"]["id"], cq["message"]["message_id"]
    tedit(chat, mid, f"📥 {esc(tid)}: {esc(v)} — {esc(who)}")
    nhan_hoan(r, v, who)
    prompt(chat, mid, tid, "anh_hoan", u, f"📷 {esc(who)} trả lời tin này bằng <b>ảnh kiện hàng hoàn</b> "
                                         "(gõ - nếu không có ảnh)")


def nhan_hoan(r, v, who):
    loai = TEN_LOAI.get(r.get("Loại"), "")
    nxt = {"doi": "Chờ nhập kho QLBH", "tra": "Chờ hoàn tiền", "doihoan": "Chờ nhập kho QLBH",
           "hoan": "Chờ CS gắn đơn"}.get(loai, r.get("Trạng thái"))
    f = {"Tình trạng hàng hoàn": v, "Ngày hàng hoàn về": today(), "Người nhận hoàn": who, "Trạng thái": nxt}
    if v in XAU:
        f["Cần duyệt"] = "✓"
        if loai == "tra":  # hàng trả về bị tráo/thiếu/lỗi: chủ shop duyệt lại trước khi hoàn tiền
            f.update({"Trạng thái": "Chờ duyệt", "Duyệt": ""})
    upd(r, f, f"hàng hoàn về: {v}", who)
    if v in XAU and loai == "tra":
        bao_duyet(r, f"Hàng trả về {v} — có hoàn tiền {vnd(r.get('Tiền hoàn KH'))} không? (Từ chối = khiếu nại sàn)")
    refresh(r, f"📥 Hàng hoàn về: <b>{esc(v)}</b> ({esc(who)})" + ("\n⚠️ Chờ chủ shop xem" if v in XAU else ""), True)
    if v in XAU and loai != "tra":
        for u in duyet_ids():
            tsend(u, f"⚠️ <b>Hàng hoàn {esc(v)}</b>\n\n" + card(r))


def prompt(chat, reply_to, tid, f, u, text):
    mention = f'<a href="tg://user?id={u["id"]}">{esc(ten(u))}</a>'
    mid = tsend(chat, text.replace(esc(ten(u)), mention, 1), reply_to=reply_to, force=True)
    if mid:
        PEND[f"{chat}:{mid}"] = {"id": tid, "f": f, "u": u["id"]}
        _save()


def on_prompt_reply(m, p):
    u = m.get("from") or {}
    who = ten(u)
    chat = m["chat"]["id"]
    r = get(p["id"])
    if not r:
        return
    t = (m.get("text") or m.get("caption") or "").strip()
    f = p["f"]
    key = f"{chat}:{m['reply_to_message']['message_id']}"
    if f == "anh_hoan":
        if m.get("photo"):
            fid = max(m["photo"], key=lambda x: x.get("file_size", 0))["file_id"]
            old = str(r.get("Ảnh hàng hoàn") or "")
            upd(r, {"Ảnh hàng hoàn": (old + ", " if old else "") + "tg:" + fid}, "ảnh hàng hoàn", who)
            if not old:
                try:
                    TG.xem_anh(BANG, r["_id"], "Ảnh hàng hoàn", TG.download(fid))
                except BaseException as e:
                    print("ticket: ảnh xem lỗi", e, flush=True)
            if not m.get("media_group_id"):
                tsend(chat, f"📷 Đã lưu ảnh vào {esc(r['ID'])}", reply_to=m["message_id"])
            return  # giữ PEND để nhận thêm ảnh trong album
        PEND.pop(key, None); _save()
        return
    if not t:
        return tsend(chat, "Gõ chữ trả lời giúp mình nhé.", reply_to=m["message_id"])
    PEND.pop(key, None); _save()
    if f == "don_di":
        parts = t.split()
        upd(r, {"MVĐ đi": parts[0], "MVĐ hoàn về": parts[1] if len(parts) > 1 else r.get("MVĐ hoàn về", ""),
                "Ngày gửi đi": today(), "Trạng thái": "Chờ hàng hoàn về"}, f"tạo đơn đi {parts[0]}", who)
        refresh(r, f"📦 Đã gửi đơn đi ({esc(who)}). Kho chờ nhận hàng hoàn.", True)
    elif f == "giai_trinh":
        upd(r, {"Kho giải trình": (str(r.get("Kho giải trình") or "") + f"\n{who}: {t}").strip()}, "kho giải trình", who)
        tsend(chat, "📝 Đã ghi giải trình.", reply_to=m["message_id"])
        for u2 in duyet_ids():
            tsend(u2, f"📝 Kho giải trình {esc(r['ID'])} ({esc(who)}):\n{esc(t)}")
    elif f == "gan":
        goc = [x for x in find(t) if x["ID"] != r["ID"]]
        if goc:
            g = goc[0]
            upd(g, {"Tình trạng hàng hoàn": r.get("Tình trạng hàng hoàn"), "Ngày hàng hoàn về": r.get("Ngày hàng hoàn về"),
                    "Người nhận hoàn": r.get("Người nhận hoàn"), "Ảnh hàng hoàn": r.get("Ảnh hàng hoàn", ""),
                    "MVĐ hoàn về": g.get("MVĐ hoàn về") or r.get("MVĐ hoàn về")}, f"gắn hàng hoàn {r['ID']}", who)
            nxt = {"doi": "Chờ nhập kho QLBH", "tra": "Chờ hoàn tiền", "doihoan": "Chờ nhập kho QLBH"}.get(
                TEN_LOAI.get(g.get("Loại")), g.get("Trạng thái"))
            if g.get("Trạng thái") not in DONG:
                upd(g, {"Trạng thái": nxt})
            refresh(g, f"🔗 Đã gắn hàng hoàn từ {esc(r['ID'])}", True)
            upd(r, {"Trạng thái": "Đóng", "Ngày đóng": today(), "Mã đơn": g.get("Mã đơn")}, f"gắn vào {g['ID']}", who)
            refresh(r)
        else:
            upd(r, {"Mã đơn": t}, f"gắn mã đơn {t}", who)
            refresh(r, f"🔗 Gắn mã đơn {esc(t)} (chưa có ticket nào với mã này). Nhập kho xong bấm ✅.", True)


# ======================= lệnh =======================

def menu(chat, private):
    if private:
        b = [[{"text": f"{LOAI[k][1]}", "callback_data": f"tk:m:{k}"}] for k in LOAI if k != "hoan"]
        return tsend(chat, "🎫 Mở ticket loại nào?", b)
    un = me()["username"]
    b = [[{"text": LOAI[k][1], "url": f"https://t.me/{un}?start=tk_{k}"}] for k in LOAI if k != "hoan"]
    tsend(chat, "🎫 Mở ticket: bấm 1 loại → bot mở chat riêng (SĐT/địa chỉ chỉ khai ở chat riêng).\n"
                "Kho nhận hàng hoàn: <code>/hoan MVĐ</code> · Xem: <code>/xem mã</code> · Đang dở: /dangdo", b)


def cmd_hoan(m, arg):
    chat, u = m["chat"]["id"], m.get("from") or {}
    if not arg:
        return tsend(chat, "Gõ <code>/hoan MVĐ</code> (hoặc mã đơn / ID ticket).", reply_to=m["message_id"])
    rs = find(arg, open_only=True)
    if not rs:
        with _LOCK:
            tid = new_id("HHV")
            row = {"ID": tid, "Loại": LOAI["hoan"][1], "Trạng thái": "Chờ CS gắn đơn", "MVĐ hoàn về": arg,
                   "Ngày tạo": datetime.now().strftime("%Y-%m-%d %H:%M"), "Người tạo": ten(u),
                   "Lịch sử": f"{now()} {ten(u)}: kho báo hàng hoàn, chưa có ticket"}
            row["_id"] = TG.kho("add", table=TG.sname(BANG), rows=[row])[0]
            TG._CACHE.pop(TG.sname(BANG), None)
        rs = [row]
        tsend(chat, f"Không thấy ticket nào có mã <code>{esc(arg)}</code> → mở <b>{tid}</b> để CS gắn đơn sau.",
              reply_to=m["message_id"])
        refresh(row)
    r = rs[0]
    b = [[{"text": t, "callback_data": f"tk:t:{r['ID']}:{k}"}] for k, t in enumerate(TINH_TRANG)]
    tsend(chat, card(r) + "\n\n📥 Hàng hoàn về tình trạng thế nào?", b, reply_to=m["message_id"])


def cmd_xem(m, arg, private):
    chat = m["chat"]["id"]
    rs = find(arg)
    if not rs:
        return tsend(chat, f"Không thấy ticket <code>{esc(arg)}</code>.", reply_to=m["message_id"])
    for r in rs[:3]:
        tsend(chat, card(r, rieng=private), btns(r) if not private else None, reply_to=m["message_id"])


def cmd_dangdo(m):
    rs = [r for r in all_rows() if r.get("Trạng thái") not in DONG and r.get("ID")]
    if not rs:
        return tsend(m["chat"]["id"], "Không có ticket đang dở 🎉")
    by = {}
    for r in rs:
        by.setdefault(r["Trạng thái"], []).append(r)
    L = [f"📋 <b>{len(rs)} ticket đang dở</b>"]
    for st, xs in by.items():
        L.append(f"\n<b>{esc(st)}</b> ({len(xs)})")
        for r in xs[:15]:
            L.append(f"• {esc(r['ID'])} {esc(r.get('Kênh'))} {esc(r.get('SKU đổi sang') or r.get('Lý do'))[:40]} "
                     f"— {tuoi(r)} ngày")
    tsend(m["chat"]["id"], "\n".join(L))


def tuoi(r, col="Ngày tạo"):
    try:
        return (datetime.now() - datetime.strptime(str(r.get(col))[:10], "%Y-%m-%d")).days
    except ValueError:
        return 0


# ======================= nhận update từ listener =======================

def on_update(u):
    """Gọi từ TG.poll (luồng nghe). Trả True nếu là việc của ticket (đẩy vào hàng đợi riêng)."""
    if not E:
        return False
    cq = u.get("callback_query")
    if cq:
        if str(cq.get("data", "")).startswith("tk:"):
            JOBS.put(u); return True
        return False
    m = u.get("message") or {}
    if not m:
        return False
    chat, typ = str(m["chat"]["id"]), m["chat"]["type"]
    uid = (m.get("from") or {}).get("id")
    text = (m.get("text") or m.get("caption") or "").strip()
    lenh = text.split()[0].lower().split("@")[0] if text.startswith("/") else ""
    par = m.get("reply_to_message")
    if par and f"{chat}:{par['message_id']}" in PEND:
        JOBS.put(u); return True
    if typ == "private":
        if uid in WIZ or lenh in LENH or str(uid) != str(E.get("OWNER_TELE_ID", "")):
            JOBS.put(u); return True
        return False
    if chat == tchat() and lenh in LENH:
        JOBS.put(u); return True
    if chat in (str(E.get("CHAT_ID", "")),) and lenh in ("/hoan", "/xem", "/dangdo"):
        JOBS.put(u); return True
    return False


def _worker():
    while True:
        u = JOBS.get()
        try:
            handle(u)
        except BaseException as e:
            print(time.strftime("%H:%M"), "ticket lỗi:", repr(e), flush=True)
            try:
                c = (u.get("message") or (u.get("callback_query") or {}).get("message") or {}).get("chat", {}).get("id")
                if c:
                    tsend(c, "⚠️ Bot ticket gặp lỗi khi xử lý, thử lại giúp mình (đã ghi log).")
            except BaseException:
                pass


def handle(u):
    cq = u.get("callback_query")
    if cq:
        p = cq["data"].split(":")
        uid = cq["from"]["id"]
        if p[1] == "w":
            answer(cq)
            TG.api("editMessageReplyMarkup", {"chat_id": cq["message"]["chat"]["id"],
                                              "message_id": cq["message"]["message_id"],
                                              "reply_markup": {"inline_keyboard": []}})
            if WIZ.get(uid):
                wiz_choice(uid, p[2], p[3])
            return
        if p[1] == "m":
            answer(cq)
            if not is_member(uid):
                return tsend(cq["message"]["chat"]["id"], "Bạn cần ở nhóm Đổi trả mới mở được ticket.")
            return wiz_start(uid, cq["message"]["chat"]["id"], p[2], ten(cq["from"]))
        if p[1] == "a":
            return act(cq, p[2], p[3])
        if p[1] == "t":
            return tinh_trang(cq, p[2], p[3])
        return answer(cq)
    m = u["message"]
    chat, typ = m["chat"]["id"], m["chat"]["type"]
    uid = (m.get("from") or {}).get("id")
    text = (m.get("text") or m.get("caption") or "").strip()
    par = m.get("reply_to_message")
    if par and f"{chat}:{par['message_id']}" in PEND:
        return on_prompt_reply(m, PEND[f"{chat}:{par['message_id']}"])
    parts = text.split(maxsplit=1)
    lenh = parts[0].lower().split("@")[0] if text.startswith("/") else ""
    arg = parts[1].strip() if len(parts) > 1 else ""
    private = typ == "private"
    if lenh == "/huy" and uid in WIZ:
        WIZ.pop(uid, None); _save()
        return tsend(chat, "Đã huỷ phiếu.")
    if private and uid in WIZ and not lenh:
        if m.get("photo"):
            return wiz_photo(uid, m)
        return wiz_text(uid, text)
    if private and not is_member(uid):
        return tsend(chat, "Bot này chỉ làm việc trong nhóm của The Orbit. Bạn cần được thêm vào nhóm "
                           "<b>The Orbit · Đổi trả</b> trước.")
    if lenh == "/start" and arg.startswith("tk_") and arg[3:] in LOAI:
        return wiz_start(uid, chat, arg[3:], ten(m.get("from")))
    loai = lenh.lstrip("/")
    if loai in LOAI and loai != "hoan" and private:
        return wiz_start(uid, chat, loai, ten(m.get("from")))
    if lenh == "/hoan":
        return cmd_hoan(m, arg)
    if lenh == "/xem":
        return cmd_xem(m, arg, private)
    if lenh == "/dangdo":
        return cmd_dangdo(m)
    return menu(chat, private)


# ======================= nhắc 9h + báo cáo =======================

def nhac(send=False):
    rs = [r for r in all_rows() if r.get("ID")]
    mo = [r for r in rs if r.get("Trạng thái") not in DONG]
    qh = int(E.get("QUA_HAN_HOAN") or 12)
    L = [f"🎫 <b>Ticket CS — {datetime.now().strftime('%d/%m')}</b> · {len(mo)} đang dở"]

    def nhom(tit, xs, f):
        if xs:
            L.append(f"\n<b>{tit}</b> ({len(xs)})")
            L.extend("• " + f(r) for r in xs[:20])
    nhom(f"⏰ Quá {qh} ngày chưa hoàn về → đòi ĐVVC",
         [r for r in mo if r.get("Trạng thái") == "Chờ hàng hoàn về" and tuoi(r, "Ngày gửi đi") > qh],
         lambda r: f"{esc(r['ID'])} gửi {esc(r.get('Ngày gửi đi'))} ({tuoi(r, 'Ngày gửi đi')} ngày)")
    nhom("📞 Chưa gọi khách quá 1 ngày", [r for r in mo if r.get("Trạng thái") == "Chờ gọi KH" and tuoi(r) >= 1],
         lambda r: f"{esc(r['ID'])} {esc(r.get('Kênh'))} — {tuoi(r)} ngày")
    nhom("📦 Chưa tạo đơn đi", [r for r in mo if r.get("Trạng thái") == "Chờ tạo đơn đi"],
         lambda r: f"{esc(r['ID'])} → {esc(r.get('SKU đổi sang'))}")
    nhom("🔗 Hàng hoàn chưa rõ đơn", [r for r in mo if r.get("Trạng thái") == "Chờ CS gắn đơn"],
         lambda r: f"{esc(r['ID'])} MVĐ {mask(r.get('MVĐ hoàn về'))}")
    nhom("🧾 Chờ chủ shop duyệt", [r for r in mo if r.get("Trạng thái") == "Chờ duyệt"],
         lambda r: f"{esc(r['ID'])} {esc(r.get('Loại'))}")
    nhom("⚖️ Lỗi kho chờ xác nhận phạt", [r for r in rs if str(r.get("Phạt kho", "")).startswith("Chờ")],
         lambda r: f"{esc(r['ID'])} {esc(r.get('Lý do'))}")
    hq = [r for r in rs if str(r.get("Ngày tạo", ""))[:10] ==
          datetime.fromtimestamp(time.time() - 86400).strftime("%Y-%m-%d")]
    if hq:
        dem = {}
        for r in hq:
            dem[r.get("Loại")] = dem.get(r.get("Loại"), 0) + 1
        L.append("\n<b>Hôm qua</b>: " + ", ".join(f"{k} {v}" for k, v in dem.items()))
    if datetime.now().weekday() == 0:
        L.append(bao_cao_tuan(rs))
    text = "\n".join(L)
    if len(L) == 1:
        text += "\nKhông có việc trễ 🎉"
    print(re.sub(r"<[^>]+>", "", text))
    if send and tchat():
        tsend(tchat(), text)


def bao_cao_tuan(rs):
    t0 = datetime.fromtimestamp(time.time() - 7 * 86400).strftime("%Y-%m-%d")
    w = [r for r in rs if str(r.get("Ngày tạo", ""))[:10] >= t0]
    if not w:
        return "\n📊 <b>Tuần qua</b>: 0 ticket"
    dem, loi, chi = {}, {}, 0
    for r in w:
        dem[r.get("Loại")] = dem.get(r.get("Loại"), 0) + 1
        if r.get("Lỗi do"):
            loi[r["Lỗi do"]] = loi.get(r["Lỗi do"], 0) + 1
        chi += tien(r.get("Tổng chi phí shop"))
    xau = [r for r in rs if str(r.get("Ngày hàng hoàn về", ""))[:10] >= t0 and r.get("Tình trạng hàng hoàn") in XAU]
    kho = [r for r in w if r.get("Lỗi do") == "Kho"]
    return ("\n📊 <b>Tuần qua</b>: " + f"{len(w)} ticket — " + ", ".join(f"{k} {v}" for k, v in dem.items())
            + "\nLỗi do: " + ", ".join(f"{k} {v} ({v * 100 // len(w)}%)" for k, v in sorted(loi.items(), key=lambda x: -x[1]))
            + f"\nLỗi kho: {len(kho)} · phạt: {sum(1 for r in kho if str(r.get('Phạt kho', '')).startswith('Phạt'))}"
            + f"\nHàng hoàn xấu (tráo/thiếu/lỗi): {len(xau)}"
            + f"\nChi phí shop: {vnd(chi)}")


if __name__ == "__main__":
    import lark as Lk
    env = Lk.load_env()
    init(env, start_worker=False)
    a = sys.argv[1:] or ["help"]
    if a[0] == "setup":
        setup(); print("Đã tạo/bổ sung bảng", TG.sname(BANG))
    elif a[0] == "nhac":
        nhac("--send" in a)
    else:
        print(__doc__)
