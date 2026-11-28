#!/usr/bin/env python3
"""TICKET CS trên Telegram + Google Sheet (thay Lark Base "ORBIT - CS - Danh sách Ticket CS", 12 bảng gộp 1).

Chạy chung listener bot kho (@theorbit_kho_bot): listener.py gọi TG.poll(..., pre=ticket.on_update).
Luồng cố định có nút bấm, KHÔNG gọi Claude → nhanh, không tốn quota.

Loại ticket (gộp 12 bảng Lark):
  /doi      Đổi hàng sau giao (DHS)        /doitruoc Đổi trước khi giao (DHT)
  /tra      Trả hàng hoàn tiền (THT)        /doihoan  Đòi hàng hoàn: đơn bom, đơn đổi quá hạn (DHH)
  /suco     Sự cố giao: bưu tá ký toàn phần, GH1P sai, thất lạc (SCG)
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
        "Phạt kho", "Kho giải trình", "Ngày đóng", "Thẻ tin", "Lịch sử", "STK hoàn", "Bill hoàn tiền", "Chi tiết lệch"]
DONG = ("Đóng", "Đã huỷ")

KENH = ["TikTok", "Shopee", "Website", "Facebook", "Khác"]
LY_DO = {  # lý do -> lỗi do ai
    "Kho gửi sai size/mẫu/màu": "Kho", "Kho gửi thiếu hàng": "Kho", "Hàng lỗi sản xuất": "Sản xuất",
    "Hư hỏng khi vận chuyển": "ĐVVC", "KH đổi size/mẫu (không lỗi)": "Khách", "Khác": "Chưa rõ"}
LY_DO_LOAI = {
    "doi": list(LY_DO), "tra": list(LY_DO),
    "doitruoc": ["KH đổi ý trước khi giao", "Live/CS tư vấn sai", "Lên đơn nhầm", "Khác"],
    "doihoan": ["Đơn bom (KH không nhận)", "Đơn đổi quá hạn chưa hoàn về", "Hàng hoàn thất lạc", "Khác"],
    "suco": ["Bưu tá ký nhận toàn phần (không thu hàng cũ)", "Giao 1 phần sai", "Thất lạc", "Hư hỏng khi giao", "Khác"],
}
# Ô trong mẫu dán: khoá -> (cột Sheet, kiểu, nhãn trong mẫu, các chữ nhận ra nhãn, câu hỏi khi thiếu)
F = {
    "ma": ("Mã đơn", "text", "Mã đơn", ("mã đơn", "ma don", "mã", "ma", "đơn", "don", "order"), "Mã đơn?"),
    "ten": ("Tên KH", "text", "Tên KH", ("tên", "ten", "khách", "khach", "kh"), "Tên khách?"),
    "sdt": ("SĐT KH", "phone", "SĐT", ("sđt", "sdt", "số điện thoại", "so dien thoai", "phone", "đt", "dt"),
            "SĐT khách?"),
    "dc": ("Địa chỉ KH", "text", "Địa chỉ", ("địa chỉ", "dia chi", "đc", "dc"), "Địa chỉ nhận hàng?"),
    "sku": ("SKU", "sku", "SKU", ("sku", "mẫu", "mau", "size", "đổi", "doi"),
            "SKU khách đang cầm → SKU đổi sang? (VD: SO-A4-RIVET-S → L)"),
    "sku_cu": ("SKU khách đang cầm", "text", "SKU", ("sku", "mẫu", "mau", "sp"), "SKU khách trả?"),
    "chenh": ("Chênh giá KH trả thêm", "num", "Bù thêm", ("bù", "bu", "chênh", "chenh", "cod"), ""),
    "tien": ("Tiền hoàn KH", "num", "Tiền hoàn", ("tiền", "tien", "hoàn", "hoan"), "Số tiền hoàn cho khách?"),
    "mvd": ("MVĐ hoàn về", "text", "MVĐ", ("mvđ", "mvd", "vận đơn", "van don", "mã vận"), ""),
    "stk": ("STK hoàn", "text", "STK hoàn", ("stk", "số tk", "tài khoản", "tai khoan", "ngân hàng", "bank"), ""),
    "ghi": ("Chi tiết", "text", "Ghi chú", ("ghi chú", "ghi chu", "ghi", "mô tả", "mo ta", "note", "lỗi", "loi"), ""),
}
LOAI = {  # mã: (tiền tố, tên, ô trong mẫu (* = bắt buộc), trạng thái đầu)
    "doi": ("DHS", "Đổi hàng sau giao", ["ma*", "ten*", "sdt*", "dc*", "sku*", "chenh", "ghi"], "Chờ gọi KH"),
    "doitruoc": ("DHT", "Đổi trước khi giao", ["ma*", "sku*", "ghi"], "Chờ kho đổi trong đơn"),
    "tra": ("THT", "Trả hàng hoàn tiền", ["ma*", "ten*", "sdt*", "sku_cu*", "tien*", "stk", "ghi"], "Chờ duyệt"),
    "doihoan": ("DHH", "Đòi hàng hoàn", ["ma*", "mvd", "ghi"], "Chờ đòi ĐVVC"),
    "suco": ("SCG", "Sự cố giao hàng", ["ma*", "mvd", "ghi"], "Chờ khiếu nại ĐVVC"),
    "hoan": ("HHV", "Hàng hoàn lỗi/tráo/thiếu", [], "Chờ khiếu nại sàn"),
}
TEN_LOAI = {v[1]: k for k, v in LOAI.items()}
TEN_LOAI["Hàng hoàn về (chưa rõ ticket)"] = "hoan"   # tên cũ trước 19/11
BTN = {
    "Chờ gọi KH": [("📦 Đã gọi + tạo đơn đi (gõ MVĐ)", "don_di"), ("📵 Chưa nghe máy", "goi_ko"),
                   ("🗑 KH huỷ đổi", "huy")],
    "Chờ tạo đơn đi": [("📦 Đã tạo đơn đi (gõ MVĐ)", "don_di")],
    "Chờ hàng hoàn về": [("📥 Kho nhận hàng hoàn", "nhan"), ("📣 Đã đòi ĐVVC", "doi_dvvc")],
    "Chờ nhập kho QLBH": [("✅ Đã nhập kho QLBH", "nhap")],
    "Chờ kho đổi trong đơn": [("✅ Kho đã đổi trong đơn", "doi_xong"), ("🚚 Đơn đã đi rồi", "da_di")],
    "Chờ duyệt": [("✅ Duyệt", "duyet"), ("❌ Từ chối", "tuchoi")],
    "Chờ hoàn tiền": [("💸 Đã hoàn tiền KH", "hoan_tien")],
    "Chờ đòi ĐVVC": [("📣 Đã đòi ĐVVC", "doi_dvvc"), ("📥 Kho nhận hàng hoàn", "nhan")],
    "Chờ khiếu nại ĐVVC": [("📣 Đã khiếu nại ĐVVC", "kn")],
    "Chờ ĐVVC trả lời": [("✅ Đã giải quyết", "xl_ok"), ("💸 ĐVVC đền tiền", "den")],
    "Chờ CS gắn đơn": [("🔗 Gắn mã đơn", "gan")],   # kiện hoàn xấu mà Nhanh không ra đơn
    # kiện hoàn lỗi/tráo/thiếu (chủ shop 14/11: KHO khiếu nại trên sàn; 19/11: 1 kiện = 1 ticket, 2 bước là xong)
    "Chờ khiếu nại sàn": [("⚠️ Đã khiếu nại trên sàn", "kn_san"), ("✅ Không khiếu nại (đã duyệt hoàn)", "bo_kn")],
    "Chờ sàn trả lời": [("✅ Sàn chấp nhận / đền", "san_ok"), ("❌ Sàn từ chối", "san_ko")],
}
TINH_TRANG = ["✅ Nguyên vẹn", "⚠️ Không nguyên vẹn (lỗi/bẩn)", "🔀 Bị tráo hàng", "➖ Thiếu hàng"]
XAU = TINH_TRANG[1:]
LENH = ("/tk", "/ticket", "/doi", "/doitruoc", "/tra", "/doihoan", "/suco", "/hoan", "/xem", "/dangdo",
        "/huy", "/start", "/dangnhapnhanh")

E = {}
ME = {}
EXT_CMDS = {}   # lệnh -> fn(m, arg)        (kho_flow.py đăng ký: /hangve /chotdi /chothoan /kiemkho /kho)
EXT_CB = {}     # tiền tố callback -> fn(cq, parts)
EXT_REPLY = {}  # loại câu hỏi chờ trả lời -> fn(m, p)
ALBUM = {}      # media_group_id -> (lệnh, lúc): ảnh 2,3… của 1 album gửi kèm /hoan, /chothoan
EXT_PRIV = {}   # lệnh dùng được khi nhắn riêng bot -> fn(m, arg)
EXT_TEXT = []   # fn(m) -> True nếu đã nhận tin chữ/ảnh trong chat riêng (phiếu của module khác)
EXT_BAN = []    # fn(uid) -> True nếu người này đang dở phiếu của module khác
EXT_START = {}  # /start <mã> (nút mở chat riêng) -> fn(m, arg)
EXT_NHOM = {}   # lệnh -> các biến env nhóm được dùng (vd ("CH_CHAT_ID",)); không khai = mọi nhóm của bot
TEN_NHOM = {"CHAT_ID": "Kho hàng về & restock", "TICKET_CHAT_ID": "Đổi trả CS-Kho", "CH_CHAT_ID": "CS & Cửa hàng"}


def nhom_ok(lenh, chat):
    """None = được dùng ở nhóm này; ngược lại trả câu nhắc đúng nhóm."""
    keys = EXT_NHOM.get(lenh)
    if not keys:
        return None
    if str(chat) in {str(E.get(k) or "") for k in keys}:
        return None
    return f"Lệnh {lenh} dùng trong nhóm " + " / ".join(f"<b>{TEN_NHOM.get(k, k)}</b>" for k in keys) + "."
HOAN = "09 · HÀNG HOÀN NHẬN"
HOAN_COLS = ["Ngày", "MVĐ", "Ticket", "Tình trạng", "Người nhận", "Ảnh", "Ảnh (xem)", "Sàn báo hoàn", "Ghi chú",
             "Sản phẩm", "Đơn Nhanh", "Nhập hoàn Nhanh"]   # cột cuối: bot tự ghi khi Nhanh đã nhập hoàn (nhap_hoan.py)
WIZ = {}    # uid -> phiếu đang hỏi
PEND = {}   # "chat:mid" của tin bot hỏi -> {id, f, u}
STATE_KF = {}  # kho_flow: đợt hàng về -> id các dòng 03
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
        STATE_KF.update(st.get("kf", {}))
    except Exception:
        pass
    if start_worker:
        threading.Thread(target=_worker, daemon=True).start()


def _save():
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    keep = dict(list(PEND.items())[-300:])
    PEND.clear(); PEND.update(keep)
    kf = dict(list(STATE_KF.items())[-200:])
    STATE_KF.clear(); STATE_KF.update(kf)
    json.dump({"wiz": WIZ, "pend": PEND, "kf": STATE_KF}, open(STATE, "w"), ensure_ascii=False)


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


def chuan_lenh(tok):
    """'/Hoàn@bot' → '/hoan': bỏ dấu, chữ thường, bỏ @bot (team hay gõ /hoàn, /HOAN, /Đối soát…)."""
    import unicodedata
    t = str(tok or "").split("@")[0].lower().replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def ten(u):
    return " ".join(x for x in ((u or {}).get("first_name"), (u or {}).get("last_name")) if x) or str((u or {}).get("id"))


def is_member(uid):
    uid = str(uid)
    if uid in duyet_ids():
        return True
    hit = _MEM.get(uid)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    ok = False
    for c in (tchat(), str(E.get("CHAT_ID") or "")):
        if c:
            r = TG.api("getChatMember", {"chat_id": c, "user_id": int(uid)})
            if r.get("ok") and r["result"]["status"] in ("creator", "administrator", "member", "restricted"):
                ok = True; break
    _MEM[uid] = (time.time(), ok)
    return ok


# ======================= Sheet =======================

def setup():
    TG.kho("setup", tables={TG.sname(BANG): COLS, TG.sname(HOAN): HOAN_COLS})


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
    if r.get("Loại") in DOI_LOAI and ({"Trạng thái", "MVĐ đi", "SKU đổi sang", "Mã đơn"} & set(fields)):
        so_doi_nen(r)
    return r


# ---- sổ đơn đổi/trả chung (chủ shop 18/11): ticket /tk đổi/trả cũng ghi vào bảng "SP DD · ĐƠN ĐỔI"
# (cùng bảng agent CSKH ghi bằng so_sheet.py add) → 1 nơi theo dõi mọi đơn đổi/trả, link đã ghim trong các nhóm.
DOI_BANG = "DD · ĐƠN ĐỔI"
DOI_LOAI = {"Đổi hàng sau giao": "Đổi", "Đổi trước khi giao": "Đổi", "Trả hàng hoàn tiền": "Trả"}
TEN_K = {"TikTok": "TikTok", "Shopee": "Shopee", "Website": "Web", "Facebook": "Meta", "Khác": "Khác"}


def so_doi(r):
    loai = DOI_LOAI.get(r.get("Loại"))
    if not loai:
        return None
    ma = str(r.get("Mã đơn") or "").strip()
    nhanh_id = re.fullmatch(r"\d{8,10}", ma) is not None
    sdt_re = re.compile(r"(?<!\d)(0|\+?84)\d{8,10}(?!\d)")
    ly = re.sub(sdt_re, "[SĐT]", " · ".join(x for x in (r.get("Lý do"), r.get("Chi tiết")) if x))
    phi = tien(r.get("Phí ship KH trả")) + tien(r.get("Chênh giá KH trả thêm"))
    f = {"Ngày": str(r.get("Ngày tạo") or "")[:10] or datetime.now().strftime("%Y-%m-%d"), "Loại": loai,
         "Kênh": TEN_K.get(r.get("Kênh"), r.get("Kênh") or ""),
         "Mã đơn sàn": "" if nhanh_id else ma, "Mã đơn Nhanh": ma if nhanh_id else "",
         "MVĐ J&T": r.get("MVĐ đi") or "", "SKU cũ": str(r.get("SKU khách đang cầm") or "").upper(),
         "SKU mới": str(r.get("SKU đổi sang") or "").upper(), "Phí đổi": phi if phi else "", "Lý do": ly,
         "Tên KH": r.get("Tên KH") or "", "SĐT KH": r.get("SĐT KH") or "", "Địa chỉ KH": r.get("Địa chỉ KH") or "",
         "Người ghi": f"{r.get('Người tạo') or ''} (bot /tk)",
         "Ghi lúc": datetime.now().strftime("%Y-%m-%d %H:%M"),
         "Ghi chú": f"Ticket {r.get('ID')} · {r.get('Trạng thái') or ''} ({r.get('Loại')})"}
    f = {k: v for k, v in f.items() if v not in ("", None)}
    rs = TG.rows(DOI_BANG, fresh=True)
    cu = next((x for x in rs if f"Ticket {r.get('ID')} " in str(x.get("Ghi chú") or "")), None)
    if not cu and ma:   # agent CSKH đã ghi đơn này rồi → gộp vào dòng đó, không tạo trùng
        cu = next((x for x in rs if ma.lower().lstrip("#") in (str(x.get("Mã đơn sàn") or "").lower().lstrip("#"),
                                                             str(x.get("Mã đơn Nhanh") or "").lower())
                   and x.get("Loại", "Đổi") == loai and "Ticket " not in str(x.get("Ghi chú") or "")), None)
    if cu:
        if "Ticket " not in str(cu.get("Ghi chú") or "") and cu.get("Ghi chú"):
            f["Ghi chú"] = f"{cu.get('Ghi chú')} · {f['Ghi chú']}"
        for k in ("Ngày", "Người ghi"):
            if cu.get(k):
                f.pop(k, None)
        for k in list(f):   # không đè dữ liệu agent đã ghi bằng ô trống/khác kiểu
            if k in ("SKU cũ", "SKU mới", "Tên KH", "SĐT KH", "Địa chỉ KH", "Mã đơn Nhanh", "Mã đơn sàn") and cu.get(k):
                f.pop(k)
        TG.kho("update", table=TG.sname(DOI_BANG), id=cu["_id"], fields=f)
        return cu["_id"]
    return TG.kho("add", table=TG.sname(DOI_BANG), rows=[f])[0]


def so_doi_nen(r):
    def chay():
        try:
            so_doi(dict(r))
        except BaseException as e:
            print("ticket: ghi sổ đơn đổi lỗi", repr(e)[:200], flush=True)
    threading.Thread(target=chay, daemon=True).start()


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
    """Tồn thật từ Nhanh.vn (cache nhanh.py); chưa có thì tra bảng 05 TÌNH TRẠNG HÀNG (gần đúng theo chữ)."""
    try:
        import nhanh as NH
        p = NH.ton_sku(sku)
        if p is not None and NH.con_moi(180):
            return (f"Nhanh: có thể bán {p.get('co_the_ban')}, trong kho {p.get('trong_kho')}"
                    + (f", đang giao {p.get('dang_giao')}" if p.get("dang_giao") else "")
                    + f" ({NH.meta().get('dong_bo', '')[11:]})")
    except Exception:
        pass
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
    import nhanh as NH
    return NH.link_sp(sku)


def sp_don(ma):
    """Đơn Nhanh theo MVĐ/mã đơn + chuỗi sản phẩm có tên: 'Tên (SKU) x1; …'. Không thấy → (None, "").
    Thứ tự: đơn đi (MVĐ/mã sàn/ID) → bỏ đuôi '-001' của GHN → MVĐ hoàn SAU GIAO trên Shopee/TikTok (API trả hàng)."""
    try:
        import nhanh as NH
        o = NH.don_theo_ma(ma)
        m2 = re.sub(r"-\d{1,3}$", "", str(ma))
        if not o and m2 != str(ma):
            o = NH.don_theo_ma(m2)
        if not o:
            import nhanh_api as NA
            r = _TRA_HOAN.get(str(ma).upper())
            if r is None:
                r = _TRA_HOAN[str(ma).upper()] = NA.tra_hoan(ma) or {}
            if r:
                o = {"id": r["nhanh_id"], "kenh": r["kenh"], "ma_san": r["ma_san"], "mvd": str(ma), "sp": r["sp"],
                     "st_ten": f"KHÁCH TRẢ SAU GIAO · {r['loai']} · {r['tt_san']}" + (f" · lý do: {r['ly_do']}" if r["ly_do"] else ""),
                     "tra_sau_giao": r}
        ps = NH.products() if o else {}
    except Exception as e:
        print("ticket: tra đơn Nhanh lỗi", repr(e)[:150], flush=True)
        return None, ""
    if not o:
        return None, ""
    def ten_sp(c):
        t = (ps.get(c) or ps.get(str(c).upper()) or {}).get("ten")
        return f"{t} ({c})" if t else str(c)
    t = o.get("tra_sau_giao")
    if t:   # kiện khách trả (bài dạy D002): chỉ các món khách YÊU CẦU TRẢ, đúng số lượng + đơn gốc để đối chiếu
        phai = [f"{ten_sp(x['ma'])} x{x['sl']}" for x in t["sp"]] + [f"{x} (chưa rõ mã)" for x in t.get("chua_ghep", [])]
        goc = "; ".join(f"{x['ma']} x{x['sl']}" for x in t.get("don_goc", []))
        sp = "; ".join(phai) or "; ".join(t["sp_san"])
        return o, sp + (f" ‖ Đơn gốc gồm: {goc}" if goc else "")
    return o, "; ".join(f"{ten_sp(x['ma'])} x{x['sl']}" for x in o["sp"])


_TRA_HOAN = {}   # MVĐ -> kết quả tra trả hàng sàn (tránh gọi API lặp)


def don_nhanh(ma):
    """Dòng mô tả đơn trên Nhanh theo MVĐ/mã đơn (để kho đối chiếu hàng trong kiện)."""
    o, sp = sp_don(ma)
    if not o:
        return ""
    import nhanh as NH
    return (f"📦 Nhanh: đơn {NH.TEN_KENH.get(o['kenh'], o['kenh'])} {o['ma_san'] or o['id']} ({o['st_ten']})\n"
            + f"Trong kiện phải có: <b>{esc(sp.split(' ‖ ')[0])}</b>"
            + (f"\n<i>{esc(sp.split(' ‖ ')[1])} — khách chỉ trả các món trên</i>" if " ‖ " in sp else ""))


# ======================= thẻ ticket =======================

def mask(x):
    x = str(x or "")
    return ("…" + x[-4:]) if len(x) > 5 else x


def card(r, rieng=False):
    loai = r.get("Loại", "")
    L = [f"🎫 <b>{esc(r['ID'])}</b> · {esc(loai)}",
         (f"Kênh: {esc(r.get('Kênh'))} · " if r.get("Kênh") else "")
         + (f"Đơn: <code>{esc(r.get('Mã đơn'))}</code>" if r.get("Mã đơn") else "Đơn: (chưa rõ)")]
    if rieng and r.get("STK hoàn"):
        L.append(f"🏦 Hoàn vào: {esc(r.get('STK hoàn'))}")
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
    if r.get("Chi tiết lệch"):
        L.append(f"📝 Lệch: {esc(r.get('Chi tiết lệch'))}" + (" · 📸 có ảnh" if r.get("Ảnh hàng hoàn") else ""))
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


# ======================= mở ticket (nhắn riêng): 1 tin dán mẫu + 1–2 nút =======================

def o(k):
    return k.rstrip("*")


def mau(loai):
    return "\n".join(f"{F[o(k)][2]}: " + ("cũ → mới" if o(k) == "sku" else "0" if o(k) == "chenh" else "")
                     for k in LOAI[loai][2])


# ---- /tk <mã đơn>: bot tra Nhanh → gợi ý loại theo trạng thái đơn + điền sẵn khách/SKU (chủ shop 18/11: luồng cũ rườm rà)
ST_TRUOC = ("Đơn mới", "Đã xác nhận", "Đang đóng gói", "Chờ khách xác nhận", "Chờ lấy hàng", "Đóng gói xong", "Chờ thu gom")
ST_HOAN = ("Đã chuyển hoàn", "Xác nhận hoàn", "Đang chuyển hoàn", "Chuyển hoàn")
PRE = {}      # mã -> thông tin đơn đã tra (để nút bấm không tra lại)
CHO_MA = {}   # uid -> lúc: đang chờ người gõ mã đơn sau /tk


def thong_tin_don(ma):
    ma = str(ma).strip()
    if ma in PRE and time.time() - PRE[ma]["luc"] < 1800:
        return PRE[ma]
    o, sp = sp_don(ma)
    if not o:
        return None
    i = {"o": o, "sp": sp, "luc": time.time(), "ten": "", "sdt": "", "dc": ""}
    try:
        import nhanh_api as NA
        d = NA.goi("order/list", {"filters": {"ids": [int(o["id"])]}, "paginator": {"size": 1}}).get("data") or []
        a = (d[0].get("shippingAddress") or {}) if d else {}
        sach = lambda x: "" if "*" in str(x or "") else str(x or "")   # sàn che (B** Q***g) → bỏ, hỏi người tạo
        i.update(ten=sach(a.get("name")), sdt=sach(a.get("mobile")), dc=sach(a.get("address")))
    except Exception as e:
        print("ticket: tra khách Nhanh lỗi", repr(e)[:150], flush=True)
    PRE[ma] = i
    return i


def goi_y(o):
    st = o.get("st_ten") or ""
    if o.get("tra_sau_giao"):
        return ["tra", "doi"]
    if st in ST_HOAN:
        return ["doihoan"]
    if st == "Thành công":
        return ["doi", "tra", "suco"]
    if st == "Đang chuyển":
        return ["suco", "doihoan"]
    if st in ST_TRUOC or not st:
        return ["doitruoc"]
    return [k for k in LOAI if k != "hoan"]


def tu_dong(uid, chat, ma, by):
    ma = ma.strip().split()[0][:40]
    CHO_MA.pop(uid, None)
    tsend(chat, f"🔎 Đang tra đơn <code>{esc(ma)}</code> trên Nhanh…")
    i = thong_tin_don(ma)
    if not i:
        b = [[{"text": LOAI[k][1], "callback_data": f"tk:mm:{k}:{ma}"}] for k in LOAI if k != "hoan"]
        return tsend(chat, f"⚠️ Không thấy đơn <code>{esc(ma)}</code> trên Nhanh (đơn quá 14 ngày hoặc sai mã). "
                           "Chọn loại, bot mở mẫu có sẵn mã đơn:", b)
    o = i["o"]
    gy = goi_y(o)
    import nhanh as NH
    t = (f"📦 Đơn {esc(NH.TEN_KENH.get(o['kenh'], o['kenh']))} <code>{esc(o.get('ma_san') or o['id'])}</code> · "
         f"<b>{esc(o.get('st_ten'))}</b>\nSP: {esc(i['sp'].split(' ‖ ')[0])}"
         + (f"\nKhách: {esc(i['ten'])}" + (f" · SĐT …{esc(i['sdt'][-3:])}" if i["sdt"] else "") if i["ten"] else "")
         + f"\n\n👉 Bot gợi ý: <b>{esc(LOAI[gy[0]][1])}</b>. Bấm 1 nút — bot điền sẵn mã đơn, kênh, khách, SKU; "
           "bạn chỉ trả lời phần còn thiếu.")
    b = [[{"text": ("⭐ " if k == gy[0] else "") + LOAI[k][1], "callback_data": f"tk:mm:{k}:{ma}"}] for k in gy]
    khac = [k for k in LOAI if k not in gy and k != "hoan"]
    if khac:
        b.append([{"text": "Loại khác…", "callback_data": f"tk:mk:{ma}"}])
    tsend(chat, t, b)


def dien_san(w, ma):
    i = thong_tin_don(ma)
    if not i:
        return False
    o_ = i["o"]
    keys = [o(k) for k in LOAI[w["loai"]][2]]
    w["d"]["Mã đơn"] = o_.get("ma_san") or o_["id"]
    w["doan"] = {"tiktok": "TikTok", "shopee": "Shopee"}.get(o_.get("kenh")) or doan_kenh(w["d"]["Mã đơn"])
    if "ten" in keys and i["ten"]:
        w["d"]["Tên KH"] = i["ten"]
    if "sdt" in keys and i["sdt"] and dat(w, "sdt", i["sdt"]):
        w["d"].pop("SĐT KH", None)   # SĐT sàn bị che → hỏi
    if "dc" in keys and i["dc"]:
        w["d"]["Địa chỉ KH"] = i["dc"]
    w["sp_list"] = [x["ma"] for x in o_.get("sp") or [] if x.get("ma")]
    if len(w["sp_list"]) == 1 and ("sku" in keys or "sku_cu" in keys):
        w["d"]["SKU khách đang cầm"] = w["sp_list"][0]
    w["form"] = True
    return True


def wiz_start(uid, chat, loai, by, ma=""):
    WIZ[uid] = {"loai": loai, "d": {}, "anh": [], "chat": chat, "by": by, "ma0": ma}
    if ma and dien_san(WIZ[uid], ma):
        w = WIZ[uid]
        co = [f"{c}: {esc(str(w['d'][c])[:60])}" for c in ("Mã đơn", "Tên KH", "Địa chỉ KH", "SKU khách đang cầm") if w["d"].get(c)]
        tsend(chat, f"🎫 <b>{LOAI[loai][1]}</b> — bot đã điền sẵn:\n" + "\n".join(co) + "\n(/huy để dừng)")
        return ask(uid)
    _save()
    tsend(chat, f"🎫 <b>{LOAI[loai][1]}</b>\nBấm vào mẫu dưới để chép, điền rồi gửi lại <b>1 tin</b> "
                "(không cần đủ ô không bắt buộc; /huy để dừng):")
    mau_ = mau(loai)
    if ma:
        mau_ = re.sub(r"^(Mã đơn:).*$", lambda x: f"{x.group(1)} {ma}", mau_, count=1, flags=re.M)
    tsend(chat, f"<code>{esc(mau_)}</code>")


def norm(s):
    return re.sub(r"\s+", " ", s.strip().lower())


def doc_sku(w, v):
    m = re.split(r"\s*(?:→|->|=>|>|sang)\s*", v.strip(), maxsplit=1)
    cu = m[0].strip()
    w["d"]["SKU khách đang cầm"] = cu
    if len(m) > 1 and m[1].strip():
        moi = m[1].strip()
        if "-" in cu and "-" not in moi and len(moi) <= 4:  # "SO-A4-RIVET-S → L"
            moi = cu.rsplit("-", 1)[0] + "-" + moi
        w["d"]["SKU đổi sang"] = moi
        w["d"]["Tồn SKU đổi"] = ton(moi)


def dat(w, key, v):
    """Ghi 1 ô; trả lỗi (chữ) nếu sai."""
    col, kind = F[key][0], F[key][1]
    v = v.strip()
    if v in ("", "-"):
        return None
    if kind == "phone":
        d = re.sub(r"\D", "", v)
        d = "0" + d[2:] if d.startswith("84") else d
        if not re.fullmatch(r"0\d{9}", d):
            return f"SĐT \"{v}\" chưa đúng (10 số)."
        v = d
    elif kind == "num":
        n = parse_num(v)
        if n is None:
            return f"\"{v}\" chưa phải số tiền (VD 0, 25000, 50k)."
        v = n
    elif kind == "sku":
        return doc_sku(w, v)
    if key == "ma":
        w["doan"] = doan_kenh(v)
    w["d"][col] = v
    return None


def doc_mau(w, text):
    """Đọc tin dán mẫu: dòng 'Nhãn: giá trị' (nhãn sai/thiếu thì điền theo thứ tự ô)."""
    keys = [o(k) for k in LOAI[w["loai"]][2]]
    loi, tu_do = [], []
    da = set()
    for line in [x for x in text.splitlines() if x.strip()]:
        lab, sep, val = line.partition(":")
        k = None
        if sep:
            nl = norm(lab)
            for kk in keys:
                if kk not in da and any(nl == a or nl.startswith(a + " ") for a in F[kk][3]):
                    k = kk; break
        if k is None:  # không nhãn: nhận SĐT / mã đơn theo dạng, còn lại điền theo thứ tự
            raw = line.strip()
            if "sdt" in keys and "sdt" not in da and re.fullmatch(r"[\d .+]{9,14}", raw):
                k, val = "sdt", raw
            elif "ma" in keys and "ma" not in da and doan_kenh(raw):
                k, val = "ma", raw
            else:
                tu_do.append(raw)
                continue
        da.add(k)
        e = dat(w, k, val)
        if e:
            loi.append(e)
    for raw in tu_do:
        for kk in keys:
            if kk not in da and kk not in ("chenh",):
                da.add(kk)
                e = dat(w, kk, raw)
                if e:
                    loi.append(e)
                break
    w["form"] = True
    return loi


def thieu(w):
    for k in LOAI[w["loai"]][2]:
        if not k.endswith("*"):
            continue
        k = o(k)
        if k == "sku":
            if not w["d"].get("SKU khách đang cầm") or (w["loai"] in ("doi", "doitruoc") and not w["d"].get("SKU đổi sang")):
                return k
        elif not w["d"].get(F[k][0]):
            return k
    return None


def can_anh(w):
    if w["loai"] in ("doi", "tra"):
        return LY_DO.get(w["d"].get("Lý do", "")) in ("Kho", "Sản xuất", "ĐVVC")
    return w["loai"] == "suco"


def buoc(w):
    if not w.get("form"):
        return "form"
    k = thieu(w)
    if k:
        return k
    if not w["d"].get("Kênh"):
        return "kenh"
    if not w["d"].get("Lý do"):
        return "ly_do"
    if can_anh(w) and not w.get("anh_xong"):
        return "anh"
    return None


def ask(uid):
    w = WIZ[uid]
    b = buoc(w)
    _save()
    if b is None:
        return confirm(uid)
    if b == "form":
        return
    if b == "kenh":
        if w.get("doan"):
            w["d"]["Kênh"] = w["doan"]
            return ask(uid)
        return tsend(w["chat"], "Kênh bán?", [[{"text": x, "callback_data": f"tk:w:kenh:{i}"}] for i, x in enumerate(KENH)])
    if b == "ly_do":
        return tsend(w["chat"], "Lý do?", [[{"text": x, "callback_data": f"tk:w:ly_do:{i}"}]
                                           for i, x in enumerate(LY_DO_LOAI[w["loai"]])])
    if b == "anh":
        return tsend(w["chat"], "📷 Gửi ảnh (lỗi / tag / kiện), xong bấm ✅.",
                     [[{"text": "✅ Xong ảnh", "callback_data": "tk:w:anh:xong"},
                       {"text": "Không có ảnh", "callback_data": "tk:w:anh:bo"}]])
    if b in ("sku", "sku_cu") and w.get("sp_list"):
        ds = ", ".join(w["sp_list"][:8])
        if b == "sku" and w["d"].get("SKU khách đang cầm"):
            return tsend(w["chat"], f"Đổi <b>{esc(w['d']['SKU khách đang cầm'])}</b> sang size/mẫu nào? "
                                    "(gõ size VD <code>L</code>, hoặc SKU mới đầy đủ)")
        if b == "sku":
            return tsend(w["chat"], f"Đơn có: {esc(ds)}\nKhách đổi món nào sang gì? (VD <code>{esc(w['sp_list'][0])} → L</code>)")
        return tsend(w["chat"], f"Đơn có: {esc(ds)}\nKhách trả món nào? (gõ SKU)")
    tsend(w["chat"], F[b][4])


def wiz_text(uid, text):
    w = WIZ[uid]
    b = buoc(w)
    if b == "form":
        loi = doc_mau(w, text)
        if loi:
            tsend(w["chat"], "⚠️ " + "\n⚠️ ".join(esc(x) for x in loi))
        return ask(uid)
    if b == "sku" and w["d"].get("SKU khách đang cầm") and not re.search(r"→|->|=>|>|sang", text):
        text = f"{w['d']['SKU khách đang cầm']} → {text.strip()}"
    if b in F:
        e = dat(w, b, text)
        if e:
            return tsend(w["chat"], "⚠️ " + esc(e) + " Gõ lại giúp mình.")
        return ask(uid)
    if b == "anh":
        if text.strip() in ("-", "không", "ko", "xong"):
            w["anh_xong"] = True
            return ask(uid)
        return tsend(w["chat"], "Gửi ảnh rồi bấm ✅ Xong ảnh (hoặc Không có ảnh).")
    if b in ("kenh", "ly_do"):
        return tsend(w["chat"], "Bấm 1 nút ở trên giúp mình nhé.")
    tsend(w["chat"], "Bấm ✅ Tạo ticket hoặc 🗑 Huỷ ở tin trên.")


def wiz_photo(uid, m):
    w = WIZ[uid]
    w["anh"].append(max(m["photo"], key=lambda p: p.get("file_size", 0))["file_id"])
    _save()
    if buoc(w) != "anh":
        return  # ảnh gửi sớm (kèm mẫu) vẫn giữ lại
    g = m.get("media_group_id")
    if g and w.get("g") == g:
        return
    w["g"] = g
    tsend(w["chat"], "📷 Đã nhận ảnh.", [[{"text": "✅ Xong ảnh", "callback_data": "tk:w:anh:xong"}]])


def wiz_choice(uid, key, val, by=None):
    w = WIZ.get(uid)
    if not w:
        return
    if val == "huy":
        WIZ.pop(uid, None); _save()
        return tsend(w["chat"], "Đã huỷ.")
    if val == "tao":
        if buoc(w) is not None:   # nút "Tạo" của phiếu cũ (đã Làm lại / chưa điền đủ) → không tạo ticket rỗng
            return tsend(w["chat"], "Phiếu đã làm lại / chưa đủ thông tin — điền tiếp phiếu mới nhé.")
        return create(uid)
    if val == "lam_lai":
        return wiz_start(uid, w["chat"], w["loai"], w["by"], w.get("ma0", ""))
    if key == "trung":
        w["trung_ok"] = True
        return ask(uid)
    if key != buoc(w):
        return  # nút cũ
    if key == "anh":
        if val == "xong" and not w["anh"]:
            return tsend(w["chat"], "Chưa có ảnh nào. Gửi ảnh hoặc bấm Không có ảnh.")
        w["anh_xong"] = True
    elif key == "kenh":
        w["d"]["Kênh"] = KENH[int(val)]
    elif key == "ly_do":
        w["d"]["Lý do"] = LY_DO_LOAI[w["loai"]][int(val)]
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
    trung = [x for x in find(d.get("Mã đơn", ""), open_only=True)] if not w.get("trung_ok") else []
    fake = dict(d, ID="(mới)", **{"Loại": LOAI[w["loai"]][1], "Trạng thái": LOAI[w["loai"]][3],
                                 "Người tạo": w["by"]})
    t = card(fake, rieng=True) + (f"\n📷 {len(w['anh'])} ảnh" if w["anh"] else "")
    if d.get("SKU đổi sang") and not d.get("Tồn SKU đổi"):
        t += f"\n📦 Bảng kho chưa có mẫu này — <a href=\"{esc(nhanh_link(d['SKU đổi sang']))}\">check tồn Nhanh</a>"
    if trung:
        t += f"\n\n⚠️ Mã đơn này đang có <b>{esc(trung[0]['ID'])}</b> ({esc(trung[0].get('Trạng thái'))})"
    _save()
    tsend(w["chat"], t, [[{"text": "✅ Tạo ticket", "callback_data": "tk:w:x:tao"}],
                         [{"text": "✏️ Làm lại", "callback_data": "tk:w:x:lam_lai"},
                          {"text": "🗑 Huỷ", "callback_data": "tk:w:x:huy"}]])


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
    if name in DOI_LOAI:
        so_doi_nen(row)
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
    t = f"🧾 <b>Cần duyệt</b> · {esc(r['ID'])} ({esc(r.get('Loại'))})\n{esc(vi)}\n\n" + card(r) + \
        (f"\n🏦 Hoàn vào: {esc(r.get('STK hoàn'))}" if r.get("STK hoàn") else "")  # chỉ gửi riêng chủ shop
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
    elif a in ("nhap", "nhap_ep"):
        if r.get("Nhập kho QLBH"):
            return answer(cq, "Đã nhập rồi")
        ghi = ""
        if a == "nhap":   # đọc Nhanh (chỉ đọc): có phiếu nhập trả của đơn gốc chưa — chống bấm nút mà quên nhập
            try:
                import nhap_hoan as NHH
                ok, ly = NHH.Nhanh().da_nhap(r.get("MVĐ hoàn về"), r.get("Mã đơn")) if NHH.NH.con_moi(240) else (None, "dữ liệu Nhanh cũ")
            except Exception as e:
                ok, ly = None, f"lỗi đọc Nhanh: {e}"
            if ok is False:
                answer(cq, "Nhanh chưa có phiếu nhập trả", True)
                return tsend(chat, f"⚠️ {esc(r['ID'])}: <b>Nhanh chưa có phiếu nhập trả</b> ({esc(ly)}).\n"
                                   "Nhập trả trên Nhanh (knowledge/SOP_NHANH_HOAN_DOI.md) — bot tự tick sau lần đồng bộ kế tiếp. "
                                   "Đã nhập cách khác → bấm nút dưới.",
                             [[{"text": "✅ Đã kiểm tay — Nhanh có rồi", "callback_data": f"tk:a:{r['ID']}:nhap_ep"}]], reply_to=mid)
            ghi = f" · Nhanh: {ly}" if ok else f" · chưa kiểm được Nhanh ({ly})"
        else:
            ghi = " · kiểm tay (Nhanh chưa có phiếu lúc bấm)"
        upd(r, {"Nhập kho QLBH": f"✓ {who} {now()}{ghi}"}, "nhập kho QLBH" + ghi, who)
        return finish(r, who)
    elif a in ("doi_xong", "doi_ep"):
        if st != "Chờ kho đổi trong đơn":
            return answer(cq, "Ticket đã qua bước này")
        ghi = "kho đã đổi trong đơn"
        if a == "doi_xong":   # đọc Nhanh (chỉ đọc): đơn đã mang SKU mới chưa — chống bấm nút mà quên sửa đơn
            try:
                import giu_don as GD
                kq, ly = GD.kiem_doi(r.get("Mã đơn"), r.get("SKU khách đang cầm"), r.get("SKU đổi sang"))
            except Exception as e:
                kq, ly = "chua_ro", f"lỗi đọc Nhanh: {e}"
            if kq == "sai":
                answer(cq, "Nhanh chưa đúng size", True)
                return tsend(chat, f"⚠️ {esc(r['ID'])}: <b>{esc(ly)}</b>.\nSửa đơn trên Nhanh rồi bấm lại ✅ Kho đã đổi trong đơn "
                                   "(bot kiểm lại sau lần đồng bộ kế tiếp). Đã sửa ở chỗ khác (VD trên sàn) → bấm nút dưới.",
                             [[{"text": "✅ Đã kiểm tay — đúng rồi", "callback_data": f"tk:a:{r['ID']}:doi_ep"}]], reply_to=mid)
            ghi += f" · Nhanh: {ly}" if kq == "ok" else f" · chưa kiểm được Nhanh ({ly})"
        else:
            ghi += " · kiểm tay (Nhanh chưa khớp lúc bấm)"
        upd(r, {"Trạng thái": "Đóng", "Ngày đóng": today()}, ghi, who)
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
        answer(cq)
        return prompt(chat, mid, tid, "bill_hoan", u,
                      f"💸 {esc(who)} trả lời tin này bằng <b>ảnh bill chuyển khoản hoàn tiền</b> {esc(tid)} → ticket tự đóng.")
    elif a in ("xl_ok", "xl_ko", "den"):
        v = {"xl_ok": "đã xử lý xong", "xl_ko": "không xử lý được", "den": "ĐVVC đền tiền"}[a]
        upd(r, {"Trạng thái": "Đóng", "Ngày đóng": today()}, v, who)
    elif a == "kn":
        upd(r, {"Trạng thái": "Chờ ĐVVC trả lời"}, "đã khiếu nại ĐVVC", who)
    elif a == "kn_san":
        upd(r, {"Trạng thái": "Chờ sàn trả lời"}, "đã khiếu nại trên sàn", who)
        _san_xl(r, "k", who)
    elif a in ("bo_kn", "san_ok", "san_ko"):
        v = {"bo_kn": "không khiếu nại (đã duyệt hoàn trên sàn)", "san_ok": "sàn chấp nhận / đền",
             "san_ko": "sàn từ chối khiếu nại"}[a]
        upd(r, {"Trạng thái": "Đóng", "Ngày đóng": today(), "Duyệt": f"Kết quả: {v} ({who} {now()})"}, v, who)
        if a == "bo_kn":
            _san_xl(r, "d", who)
    elif a == "gan":
        return prompt(chat, mid, tid, "gan", u, f"🔗 {esc(who)} trả lời tin này: <b>mã đơn</b> hoặc <b>ID ticket</b>")
    refresh(r)
    if str(r.get("Thẻ tin") or "") != f"tg:{chat}:{mid}":   # bấm ở tin nhóm Kho, không phải thẻ
        tedit(chat, mid, esc(cq["message"].get("text", "")) + f"\n\n✔️ {esc(who)}: {esc(r.get('Trạng thái'))}", btns(r))


def _doi_chieu_1(chat, ma):
    """1 kiện: ghi sổ đối chiếu sàn (giờ kho quét, chờ sàn) và trả 1 dòng để gộp vào tin hỏi tình trạng → kho chỉ thấy 1 tin."""
    try:
        import hoan_san
        k = hoan_san.ghi_doi_chieu(chat, [ma])[0][1]
        return k, "\n" + k["dong"].lstrip("• ")
    except Exception as e:
        print("ticket: đối chiếu sàn lỗi", repr(e)[:200], flush=True)
        return {}, ""


def _nut_san_dung(tem):
    """Kiện nguyên vẹn mà sàn có yêu cầu trả hàng → nhắc bấm đồng ý hoàn trên sàn + 1 nút xác nhận."""
    try:
        import hoan_san
        if hoan_san.doi_chieu(tem).get("kq") in ("khop", "lech"):
            return ("\n→ Vào sàn bấm <b>đồng ý hoàn / xác nhận nhận hàng</b>, xong bấm nút dưới.",
                    [[{"text": "✅ Đã duyệt hoàn trên sàn", "callback_data": f"hs:d:{tem}"[:64]}]])
    except Exception as e:
        print("ticket: đối chiếu sàn lỗi", repr(e)[:200], flush=True)
    return "", None


def _san_xl(r, xl, who):
    """Đồng bộ ngược sang sổ đối chiếu sàn (hoan_san): kho bấm trên thẻ = đã bấm trên sàn → tắt nhắc nhóm Kho."""
    try:
        import hoan_san
        hoan_san.danh_dau(str(r.get("MVĐ hoàn về") or ""), xl, who, str(r.get("Mã đơn") or ""))
    except Exception as e:
        print("ticket: đồng bộ hoan_san lỗi", e, flush=True)


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
    t, b = _nut_san_dung(str(r.get("MVĐ hoàn về") or "")) if v not in XAU else ("", None)
    tedit(chat, mid, f"📥 {esc(tid)}: {esc(v)} — {esc(who)}" + t, b)
    nhan_hoan(r, v, who)
    if v in XAU:
        hoi_lech(chat, mid, tid, u, v)


def nhan_hoan(r, v, who):
    loai = TEN_LOAI.get(r.get("Loại"), "")
    nxt = {"doi": "Chờ nhập kho QLBH", "tra": "Chờ hoàn tiền", "doihoan": "Chờ nhập kho QLBH",
           }.get(loai, r.get("Trạng thái"))
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
    if p.get("f") in EXT_REPLY:
        PEND.pop(f"{m['chat']['id']}:{m['reply_to_message']['message_id']}", None); _save()
        return EXT_REPLY[p["f"]](m, p)
    u = m.get("from") or {}
    who = ten(u)
    chat = m["chat"]["id"]
    r = get(p["id"])
    if not r:
        return
    t = (m.get("text") or m.get("caption") or "").strip()
    f = p["f"]
    key = f"{chat}:{m['reply_to_message']['message_id']}"
    if f == "bill_hoan":
        if not m.get("photo"):
            return prompt(chat, m["message_id"], r["ID"], "bill_hoan", u,
                          f"Cần <b>ảnh bill</b>: {esc(who)} trả lời tin này bằng ảnh chuyển khoản.")
        PEND.pop(key, None); _save()
        fid = max(m["photo"], key=lambda x: x.get("file_size", 0))["file_id"]
        upd(r, {"Bill hoàn tiền": "tg:" + fid, "Trạng thái": "Đóng", "Ngày đóng": today()}, "đã hoàn tiền KH (có bill)", who)
        tsend(chat, f"✅ {esc(r['ID'])}: đã hoàn tiền, lưu bill, đóng ticket.", reply_to=m["message_id"])
        return refresh(r, f"💸 Đã hoàn tiền KH — {esc(who)} (có bill)", True)
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
                "Ngày gửi đi": today(), "Trạng thái": "Chờ hàng hoàn về",
                "Gọi KH": (str(r.get("Gọi KH") or "") + f" đồng ý {now()}").strip()}, f"tạo đơn đi {parts[0]}", who)
        tsend(chat, "✅", reply_to=m["message_id"])
        refresh(r)
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
            upd(r, {"Mã đơn": t, "Trạng thái": "Chờ khiếu nại sàn"}, f"gắn mã đơn {t}", who)
            refresh(r, f"🔗 Gắn mã đơn {esc(t)} → kho khiếu nại trên sàn, xong bấm nút trên thẻ.", True)


# ======================= lệnh =======================

def menu(chat, private):
    if private:
        b = [[{"text": f"{LOAI[k][1]}", "callback_data": f"tk:m:{k}"}] for k in LOAI if k != "hoan"]
        return tsend(chat, "🎫 Mở ticket loại nào?", b)
    un = me()["username"]
    b = [[{"text": LOAI[k][1], "url": f"https://t.me/{un}?start=tk_{k}"}] for k in LOAI if k != "hoan"]
    tsend(chat, "🎫 Mở ticket: bấm 1 loại → bot mở chat riêng (SĐT/địa chỉ chỉ khai ở chat riêng).\n"
                "Kho nhận hàng hoàn: <code>/hoan MVĐ</code> · Xem: <code>/xem mã</code> · Đang dở: /dangdo", b)


def ma_list(text):
    return [t for t in re.split(r"[\s,;]+", text) if len(t) >= 6 and re.fullmatch(r"[#A-Za-z0-9\-]+", t)]


def log_hoan(ma, who, ticket="", tt="", fid=""):
    """Ghi 1 kiện hoàn vào bảng 09 (đã có dòng 'sàn báo hoàn' cho MVĐ này thì cập nhật dòng đó)."""
    o, sp = sp_don(ma)
    them = {"Sản phẩm": sp, "Đơn Nhanh": (o.get("ma_san") or o.get("id")) if o else ""}
    for r in TG.rows(HOAN, fresh=True):
        if str(r.get("MVĐ", "")).lower() == ma.lower() and not r.get("Người nhận"):
            f = {"Ngày": today(), "Người nhận": who, "Ticket": ticket, "Tình trạng": tt or "✅ Nguyên vẹn",
                 "Ảnh": "tg:" + fid if fid else "", **them}
            TG.kho("update", table=TG.sname(HOAN), id=r["_id"], fields=f)
            TG._CACHE.pop(TG.sname(HOAN), None)
            return dict(r, **f)
    row = {"Ngày": today(), "MVĐ": ma, "Ticket": ticket, "Tình trạng": tt or "✅ Nguyên vẹn", "Người nhận": who,
           "Ảnh": "tg:" + fid if fid else "", **them}
    row["_id"] = TG.kho("add", table=TG.sname(HOAN), rows=[row])[0]
    TG._CACHE.pop(TG.sname(HOAN), None)
    if fid:
        try:
            TG.xem_anh(HOAN, row["_id"], "Ảnh", TG.download(fid))
        except BaseException as e:
            print("ticket: ảnh xem lỗi", e, flush=True)
    return row


def doc_ma_anh(m, chu=False):
    """Mã vạch/QR trên ảnh (tem vận đơn). Ảnh nén của Telegram vẫn đọc được tem chụp gần."""
    try:
        import mavach
        fid = max(m["photo"], key=lambda x: x.get("file_size", 0))["file_id"]
        return mavach.doc(TG.download(fid), chu=chu)
    except Exception as e:
        print("ticket: đọc mã vạch lỗi", e, flush=True)
        return []


def da_quet(ma):
    """Kiện này kho đã quét /hoan rồi (bảng 09 có người nhận)?"""
    return next((r for r in TG.rows(HOAN, fresh=True)
                 if str(r.get("MVĐ", "")).lower() == ma.lower() and r.get("Người nhận")), None)


def cmd_hoan(m, arg):
    """Kho nhận kiện hoàn. 1 mã: chọn tình trạng. Nhiều mã (mỗi dòng 1 MVĐ): ghi hết là nguyên vẹn,
    kiện nào thuộc ticket CS thì hỏi tình trạng riêng. Kiện đã quét rồi thì bỏ qua + báo."""
    chat, u = m["chat"]["id"], m.get("from") or {}
    who = ten(u)
    mas = []
    for x in ma_list(arg):
        if x.lower() not in {y.lower() for y in mas}:
            mas.append(x)
    trung = [(x, da_quet(x)) for x in mas]
    trung = [(x, r) for x, r in trung if r and not find(x, open_only=True)]
    if trung:
        tsend(chat, "♻️ Đã quét rồi, bỏ qua: " + ", ".join(
            f"<code>{esc(x)}</code> ({esc(r.get('Người nhận'))} {esc(str(r.get('Ngày', ''))[5:])})" for x, r in trung),
            reply_to=m["message_id"])
        mas = [x for x in mas if x not in {t[0] for t in trung}]
        if not mas:
            return
    if not mas:
        return tsend(chat, "📷 Nhanh nhất: <b>chụp tem vận đơn</b>, chú thích <code>/hoan</code> — bot tự đọc mã "
                           "(chụp nhiều tem 1 ảnh hoặc gửi nhiều ảnh 1 lần đều được). Hoặc gõ <code>/hoan MVĐ</code>.",
                     reply_to=m["message_id"])
    fid = max(m["photo"], key=lambda x: x.get("file_size", 0))["file_id"] if m.get("photo") else ""
    if len(mas) == 1:
        ma = mas[0]
        rs = find(ma, open_only=True)
        if rs:
            r = rs[0]
            m["_doi_chieu"] = True
            if TEN_LOAI.get(r.get("Loại")) == "hoan":
                return tsend(chat, f"♻️ Kiện này đã có ticket <b>{esc(r['ID'])}</b>, không mở thêm.\n\n" + card(r), btns(r),
                             reply_to=m["message_id"])
            if fid:
                old = str(r.get("Ảnh hàng hoàn") or "")
                upd(r, {"Ảnh hàng hoàn": (old + ", " if old else "") + "tg:" + fid}, "ảnh hàng hoàn", who)
                if not old:
                    try:
                        TG.xem_anh(BANG, r["_id"], "Ảnh hàng hoàn", TG.download(fid))
                    except BaseException as e:
                        print("ticket: ảnh xem lỗi", e, flush=True)
            b = [[{"text": t, "callback_data": f"tk:t:{r['ID']}:{k}"}] for k, t in enumerate(TINH_TRANG)]
            dn = don_nhanh(ma)
            _, dc = _doi_chieu_1(chat, ma)
            return tsend(chat, card(r) + (f"\n{dn}" if dn else "") + (f"\n🔎 Sàn: {dc.strip()}" if dc else "")
                         + "\n\n📥 Hàng hoàn về tình trạng thế nào?", b, reply_to=m["message_id"])
        m["_doi_chieu"] = True
        row = log_hoan(ma, who, fid=fid)
        b = [[{"text": t, "callback_data": f"tk:h:{row['_id']}:{k}"}] for k, t in enumerate(TINH_TRANG)]
        dn = don_nhanh(ma)
        _, dc = _doi_chieu_1(chat, ma)
        return tsend(chat, f"📥 Đã ghi kiện hoàn <code>{esc(ma)}</code> (không thuộc ticket CS nào)."
                           + (f"\n{dn}" if dn else "\n(Nhanh chưa thấy mã này)") + (f"\n🔎 Sàn: {dc.strip()}" if dc else "")
                           + "\n\nMở kiện kiểm, tình trạng?", b, reply_to=m["message_id"])
    co_tk, le, ds = [], 0, []
    for ma in mas:
        rs = find(ma, open_only=True)
        if rs:
            co_tk.append(rs[0])
        else:
            row = log_hoan(ma, who); le += 1
            ds.append(f"• <code>{esc(ma)}</code>: " + (esc(row.get("Sản phẩm")) if row.get("Sản phẩm") else "<i>Nhanh chưa thấy</i>"))
    tsend(chat, f"📥 Đã ghi <b>{len(mas)}</b> kiện hoàn: {le} kiện thường (mặc định nguyên vẹn — kiện nào "
                f"thiếu/tráo/lỗi gõ <code>/hoan MVĐ</code> riêng để báo)" + (f", {len(co_tk)} kiện thuộc ticket CS ↓" if co_tk else ".")
                + ("\n\n<b>Trong kiện phải có:</b>\n" + "\n".join(ds[:20]) + (f"\n… và {len(ds) - 20} kiện nữa" if len(ds) > 20 else "")
                   if ds else ""),
          reply_to=m["message_id"])
    for r in co_tk:
        b = [[{"text": t, "callback_data": f"tk:t:{r['ID']}:{k}"}] for k, t in enumerate(TINH_TRANG)]
        tsend(chat, card(r) + "\n\n📥 Tình trạng?", b)


def hoan_le(cq, rid, k):
    """Kho chọn tình trạng cho kiện hoàn không thuộc ticket. Xấu → mở HHV cho CS xử lý với sàn."""
    u = cq["from"]
    who = ten(u)
    if not is_member(u["id"]):
        return answer(cq, "Bạn chưa ở nhóm kho / đổi trả", True)
    v = TINH_TRANG[int(k)]
    answer(cq, v)
    TG.kho("update", table=TG.sname(HOAN), id=rid, fields={"Tình trạng": v})
    TG._CACHE.pop(TG.sname(HOAN), None)
    r9 = next((r for r in TG.rows(HOAN, fresh=True) if r["_id"] == rid), {})
    chat, mid = cq["message"]["chat"]["id"], cq["message"]["message_id"]
    if v not in XAU:
        t, b = _nut_san_dung(str(r9.get("MVĐ", "")))
        return tedit(chat, mid, f"📥 <code>{esc(r9.get('MVĐ'))}</code>: {esc(v)} — {esc(who)}" + t, b)
    # 1 kiện = 1 ticket: kiện này đã có ticket (bấm lại / quét lại) → dùng ticket cũ, không mở thêm
    mvd = str(r9.get("MVĐ", "")).strip()
    cu = get(r9.get("Ticket")) if r9.get("Ticket") else None
    cu = cu or next((x for x in find(mvd, open_only=True) if TEN_LOAI.get(x.get("Loại")) == "hoan"), None) if mvd else cu
    if cu:
        if cu.get("Tình trạng hàng hoàn") != v:
            upd(cu, {"Tình trạng hàng hoàn": v}, f"kho sửa tình trạng: {v}", who)
            refresh(cu)
        tedit(chat, mid, f"📥 <code>{esc(mvd)}</code>: {esc(v)} — {esc(who)} → ticket <b>{esc(cu['ID'])}</b> (đã có, không mở thêm)"
              f" · ➡️ {esc(cu.get('Trạng thái'))}", btns(cu))
        if not (cu.get("Ảnh hàng hoàn") and cu.get("Chi tiết lệch")):
            hoi_lech(chat, mid, cu["ID"], u, v)
        return
    with _LOCK:
        tid = new_id("HHV")
        row = {"ID": tid, "Loại": LOAI["hoan"][1], "Trạng thái": "Chờ CS gắn đơn", "MVĐ hoàn về": r9.get("MVĐ", ""),
               "Ngày tạo": datetime.now().strftime("%Y-%m-%d %H:%M"), "Người tạo": who, "Tình trạng hàng hoàn": v,
               "Ngày hàng hoàn về": today(), "Người nhận hoàn": who,
               "Ảnh hàng hoàn": r9.get("Ảnh", ""), "Lịch sử": f"{now()} {who}: kho nhận kiện hoàn {v}, chưa rõ đơn"}
        o, sp = sp_don(r9.get("MVĐ", ""))
        if o:   # Nhanh biết đơn → gắn sẵn cho CS
            import nhanh as NH
            row.update({"Mã đơn": o.get("ma_san") or o.get("id"), "Kênh": NH.TEN_KENH.get(o["kenh"], o["kenh"]),
                        "Chi tiết": f"Trong kiện phải có: {sp}", "Trạng thái": "Chờ khiếu nại sàn"})
            row["Lịch sử"] = f"{now()} {who}: kho nhận kiện hoàn {v}, Nhanh: đơn {row['Mã đơn']}"
        row["_id"] = TG.kho("add", table=TG.sname(BANG), rows=[row])[0]
        TG._CACHE.pop(TG.sname(BANG), None)
    TG.kho("update", table=TG.sname(HOAN), id=rid, fields={"Ticket": tid})
    tedit(chat, mid, f"📥 <code>{esc(r9.get('MVĐ'))}</code>: {esc(v)} — {esc(who)} → ghi <b>{tid}</b>\n"
          + ("→ Khiếu nại trên sàn (kèm video mở kiện + video đóng gói), xong bấm nút dưới." if row.get("Mã đơn")
             else "→ Nhanh chưa ra đơn: CS tìm đơn rồi bấm 🔗 Gắn mã đơn trên thẻ ở nhóm Đổi trả."),
          btns(row) if row.get("Mã đơn") else None)
    ro = f"Nhanh: đơn {row['Mã đơn']}" if row.get("Mã đơn") else "chưa rõ đơn"
    refresh(row, f"📥 Kho nhận kiện hoàn <b>{esc(v)}</b>, {esc(ro)} → "
                 + ("kho khiếu nại trên sàn (kèm video mở kiện), xong bấm nút trên thẻ" if row.get("Mã đơn")
                    else "CS tìm đơn rồi bấm 🔗 Gắn mã đơn"), True)
    if not row.get("Mã đơn"):
        for u2 in duyet_ids():
            tsend(u2, f"⚠️ <b>Hàng hoàn {esc(v)}</b> ({esc(ro)})\n\n" + card(row))
    hoi_lech(chat, mid, tid, u, v)


LECH_HOI = {"⚠️ Không nguyên vẹn (lỗi/bẩn)": "món nào lỗi/bẩn, lỗi gì",
            "🔀 Bị tráo hàng": "món nào bị tráo, nhận được món gì thay vào",
            "➖ Thiếu hàng": "thiếu món nào, bao nhiêu cái"}


def hoi_lech(chat, mid, tid, u, v):
    prompt(chat, mid, tid, "lech", u, f"📸 {esc(ten(u))} trả lời tin này bằng <b>ẢNH hàng trong kiện</b>, chú thích ghi "
                                      f"<b>{LECH_HOI.get(v, 'lệch thế nào')}</b> (bằng chứng để khiếu nại sàn/ĐVVC).")


def on_lech(m, p):
    """Kho trả lời ảnh + ghi chú cho kiện thiếu/tráo/lỗi → lưu vào ticket, báo chủ shop."""
    u, chat = m.get("from") or {}, m["chat"]["id"]
    who = ten(u)
    r = get(p["id"])
    if not r:
        return
    t = (m.get("text") or m.get("caption") or "").strip()
    f = {}
    if m.get("photo"):
        fid = max(m["photo"], key=lambda x: x.get("file_size", 0))["file_id"]
        old = str(r.get("Ảnh hàng hoàn") or "")
        f["Ảnh hàng hoàn"] = (old + ", " if old else "") + "tg:" + fid
        if not old:
            try:
                TG.xem_anh(BANG, r["_id"], "Ảnh hàng hoàn", TG.download(fid))
            except BaseException as e:
                print("ticket: ảnh xem lỗi", e, flush=True)
    if t:
        f["Chi tiết lệch"] = (str(r.get("Chi tiết lệch") or "") + "; " if r.get("Chi tiết lệch") else "") + t
    if f:
        upd(r, f, "kho ghi chi tiết lệch" + (f": {t}" if t else " (ảnh)"), who)
        r = get(p["id"]) or r
    thieu = [x for x, ok in (("ảnh", r.get("Ảnh hàng hoàn")), ("ghi chú lệch gì", r.get("Chi tiết lệch"))) if not ok]
    if thieu:
        return prompt(chat, m["message_id"], r["ID"], "lech", u,
                      f"Còn thiếu <b>{' + '.join(thieu)}</b>: {esc(who)} trả lời tin này để bổ sung.")
    tiep = ("Kho khiếu nại trên sàn (kèm video mở kiện + video đóng gói) rồi bấm <b>⚠️ Đã khiếu nại trên sàn</b> trên thẻ."
            if r.get("Trạng thái") == "Chờ khiếu nại sàn" else
            "CS tìm đơn rồi bấm 🔗 Gắn mã đơn trên thẻ." if r.get("Trạng thái") == "Chờ CS gắn đơn" else "CS/chủ shop xử lý tiếp.")
    tsend(chat, f"✅ {esc(r['ID'])}: đã lưu ảnh + chi tiết lệch. {tiep}", reply_to=m["message_id"])
    refresh(r, f"📝 Lệch: {esc(r.get('Chi tiết lệch'))} ({esc(who)})", True)
    for q in duyet_ids():
        tsend(q, f"📝 <b>{esc(r['ID'])}</b> kho báo lệch: {esc(r.get('Chi tiết lệch'))}\n\n" + card(r))


EXT_REPLY["lech"] = on_lech


def cmd_xem(m, arg, private):
    chat = m["chat"]["id"]
    if not arg.strip():
        return tsend(chat, "Gõ <code>/xem mã</code> (mã ticket, mã đơn hoặc MVĐ). Ticket đang dở: /dangdo", reply_to=m["message_id"])
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
        if str(cq.get("data", "")).split(":")[0] in ("tk",) + tuple(EXT_CB):
            JOBS.put(u); return True
        return False
    m = u.get("message") or {}
    if not m:
        return False
    chat, typ = str(m["chat"]["id"]), m["chat"]["type"]
    uid = (m.get("from") or {}).get("id")
    text = (m.get("text") or m.get("caption") or "").strip()
    lenh = chuan_lenh(text.split()[0]) if text.startswith("/") else ""
    par = m.get("reply_to_message")
    if par and f"{chat}:{par['message_id']}" in PEND:
        JOBS.put(u); return True
    mg = m.get("media_group_id")
    if mg and lenh in ("/hoan", "/chothoan", "/giao", "/giulai", "/chotca"):
        ALBUM[mg] = (lenh, time.time())
    elif mg and not lenh and mg in ALBUM and time.time() - ALBUM[mg][1] < 120:
        JOBS.put(u); return True
    if typ == "private":
        if (uid in WIZ or lenh in LENH or lenh in EXT_PRIV or str(uid) != str(E.get("OWNER_TELE_ID", ""))
                or any(f(uid) for f in EXT_BAN)
                or re.fullmatch(r"[A-Za-z0-9_\-]{40,}", text)):   # chuỗi giống mã bí mật: bot tự xử lý, không chuyển agent
            JOBS.put(u); return True
        return False
    if chat == tchat() and lenh in LENH:
        JOBS.put(u); return True
    if chat in (str(E.get("CHAT_ID", "")),) and lenh in ("/hoan", "/xem", "/dangdo") + tuple(EXT_CMDS):
        JOBS.put(u); return True
    if chat in (tchat(), str(E.get("CH_CHAT_ID", ""))) and lenh in EXT_CMDS:
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
        if p[0] == "tk" and len(p) > 1 and p[1] in ("x", "huy") and "tn" in EXT_CB:
            return EXT_CB["tn"](cq, p)   # nút /tonkho gửi trước 26/11 (tk:x / tk:huy) → kho_flow, không phải ticket
        if p[0] in EXT_CB:
            return EXT_CB[p[0]](cq, p)
        if p[1] == "w":
            answer(cq)
            TG.api("editMessageReplyMarkup", {"chat_id": cq["message"]["chat"]["id"],
                                              "message_id": cq["message"]["message_id"],
                                              "reply_markup": {"inline_keyboard": []}})
            if WIZ.get(uid):
                wiz_choice(uid, p[2], p[3])
            return
        if p[1] == "mm":   # mở ticket với mã đơn có sẵn
            answer(cq)
            if not is_member(uid):
                return tsend(cq["message"]["chat"]["id"], "Bạn cần ở nhóm Đổi trả mới mở được ticket.")
            wiz_start(uid, cq["message"]["chat"]["id"], p[2], ten(cq["from"]), ma=":".join(p[3:]))
            return
        if p[1] == "mk":   # loại khác cho đơn đã tra
            answer(cq)
            ma = ":".join(p[2:])
            b = [[{"text": LOAI[k][1], "callback_data": f"tk:mm:{k}:{ma}"}] for k in LOAI if k != "hoan"]
            return tsend(cq["message"]["chat"]["id"], f"Chọn loại ticket cho đơn <code>{esc(ma)}</code>:", b)
        if p[1] == "m":
            answer(cq)
            if not is_member(uid):
                return tsend(cq["message"]["chat"]["id"], "Bạn cần ở nhóm Đổi trả mới mở được ticket.")
            return wiz_start(uid, cq["message"]["chat"]["id"], p[2], ten(cq["from"]))
        if p[1] == "a":
            return act(cq, p[2], p[3])
        if p[1] == "t":
            return tinh_trang(cq, p[2], p[3])
        if p[1] == "h":
            return hoan_le(cq, p[2], p[3])
        return answer(cq)
    m = u["message"]
    chat, typ = m["chat"]["id"], m["chat"]["type"]
    uid = (m.get("from") or {}).get("id")
    text = (m.get("text") or m.get("caption") or "").strip()
    par = m.get("reply_to_message")
    if par and f"{chat}:{par['message_id']}" in PEND:
        return on_prompt_reply(m, PEND[f"{chat}:{par['message_id']}"])
    parts = text.split(maxsplit=1)
    lenh = chuan_lenh(parts[0]) if text.startswith("/") else ""
    arg = parts[1].strip() if len(parts) > 1 else ""
    mg = m.get("media_group_id")
    if not lenh and mg and mg in ALBUM:
        lenh = ALBUM[mg][0]
        if lenh == "/chotca":
            text = "/chotca"
    if lenh in ("/hoan", "/chothoan", "/giao", "/giulai") and m.get("photo") and not ma_list(arg):
        ma_anh = doc_ma_anh(m, chu=lenh == "/chothoan")
        if not ma_anh:
            return tsend(chat, "📷 Chưa đọc được mã vạch trong ảnh. Chụp gần + rõ tem (mã vạch nằm ngang, đủ sáng), "
                               "hoặc gõ mã: <code>" + lenh + " MVĐ</code>", reply_to=m["message_id"])
        arg = "\n".join(ma_anh)
        tsend(chat, f"📷 Đọc được {len(ma_anh)} mã: " + ", ".join(f"<code>{esc(x)}</code>" for x in ma_anh),
              reply_to=m["message_id"])
    private = typ == "private"
    if lenh == "/huy" and uid in WIZ:
        WIZ.pop(uid, None); _save()
        return tsend(chat, "Đã huỷ phiếu.")
    if private and uid in WIZ and not lenh:
        if m.get("photo"):
            wiz_photo(uid, m)
            if text and buoc(WIZ[uid]) == "form":
                wiz_text(uid, text)
            return
        return wiz_text(uid, text)
    if private and not lenh and uid not in WIZ and uid in CHO_MA and time.time() - CHO_MA[uid] < 900 \
            and text and not m.get("photo") and ma_list(text):
        if not is_member(uid):
            return tsend(chat, "Bạn cần ở nhóm Đổi trả mới mở được ticket.")
        return tu_dong(uid, chat, ma_list(text)[0], ten(m.get("from")))
    if private and not lenh and uid not in WIZ:
        for f in EXT_TEXT:
            if f(m):
                return
    if private and not is_member(uid):
        return tsend(chat, "Bot này chỉ làm việc trong nhóm của The Orbit. Bạn cần được thêm vào nhóm "
                           "<b>The Orbit · Đổi trả</b> trước.")
    if private and lenh in EXT_PRIV:
        return EXT_PRIV[lenh](m, arg)
    if lenh == "/start" and arg.split("_")[0] in EXT_START:
        return EXT_START[arg.split("_")[0]](m, arg)
    if lenh == "/start" and arg.startswith("tkm_"):
        return tu_dong(uid, chat, arg[4:], ten(m.get("from")))
    if lenh in ("/tk", "/ticket") and ma_list(arg):
        ma = ma_list(arg)[0]
        if private:
            return tu_dong(uid, chat, ma, ten(m.get("from")))
        return tsend(chat, f"🎫 Mở ticket đơn <code>{esc(ma)}</code>: bấm nút → bot tra đơn, gợi ý loại, điền sẵn thông tin "
                           "(chat riêng vì có SĐT/địa chỉ).",
                     [[{"text": "🎫 Mở ticket đơn này", "url": f"https://t.me/{me()['username']}?start=tkm_{ma[:40]}"}]],
                     reply_to=m["message_id"])
    if lenh in ("/tk", "/ticket") and private:
        CHO_MA[uid] = time.time()
        b = [[{"text": LOAI[k][1], "callback_data": f"tk:m:{k}"}] for k in LOAI if k != "hoan"]
        return tsend(chat, "🎫 <b>Gửi mã đơn hoặc MVĐ</b> — bot tự tra Nhanh, gợi ý loại ticket và điền sẵn khách/SKU.\n"
                           "Không có mã đơn thì chọn loại bên dưới:", b)
    if lenh == "/start" and arg.startswith("tk_") and arg[3:] in LOAI:
        return wiz_start(uid, chat, arg[3:], ten(m.get("from")))
    loai = lenh.lstrip("/")
    if loai in LOAI and loai != "hoan" and private:
        return wiz_start(uid, chat, loai, ten(m.get("from")), (ma_list(arg) or [""])[0])
    if lenh == "/dangnhapnhanh":
        if str(uid) not in duyet_ids():
            return tsend(chat, "Chỉ chủ shop dùng lệnh này.")
        import nhanh_api as NA
        if NA.co_api():
            return tsend(chat, "✅ Bot kho đã nối Nhanh qua API (tự đọc 30 phút/lần), không cần đăng nhập Chrome nữa. "
                               "Mã API hết hạn/bị thu hồi thì gõ /ketnoinhanh.")
        import subprocess
        subprocess.Popen([os.path.join(ROOT, ".venv", "bin", "python"), os.path.join(ROOT, "tools", "nhanh.py"), "login"],
                         cwd=ROOT, stdout=open(os.path.join(ROOT, "logs", "nhanh-login.out"), "a"),
                         stderr=subprocess.STDOUT, start_new_session=True)
        return tsend(chat, "🔑 Đã mở cửa sổ Chrome riêng trên máy Mac: đăng nhập Nhanh.vn trong 15 phút, xong cửa sổ tự đóng.")
    if lenh in EXT_CMDS and not private:
        sai = nhom_ok(lenh, chat)
        if sai:
            return tsend(chat, sai, reply_to=m["message_id"])
        return EXT_CMDS[lenh](m, arg)
    if lenh == "/hoan":
        kq = cmd_hoan(m, arg)
        mas = list(dict.fromkeys(x for x in ma_list(arg)))
        if mas and not m.get("_doi_chieu"):   # 1 kiện đã gộp đối chiếu vào tin hỏi tình trạng   # đối chiếu yêu cầu trả hàng trên sàn → KHỚP/LỆCH + nút cho kho (chủ shop chốt 14/11)
            try:
                import hoan_san
                hoan_san.gui_doi_chieu(m["chat"]["id"], mas, reply_to=m["message_id"])
            except Exception as e:
                print("ticket: đối chiếu sàn lỗi", repr(e)[:200], flush=True)
        return kq
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
    nhom("⚠️ Hàng hoàn xấu chưa khiếu nại sàn", [r for r in mo if r.get("Trạng thái") == "Chờ khiếu nại sàn"],
         lambda r: f"{esc(r['ID'])} đơn {esc(r.get('Mã đơn'))} · {esc(r.get('Tình trạng hàng hoàn'))}")
    nhom("⏳ Đã khiếu nại, chờ sàn trả lời", [r for r in mo if r.get("Trạng thái") == "Chờ sàn trả lời"],
         lambda r: f"{esc(r['ID'])} đơn {esc(r.get('Mã đơn'))}")
    nhom("🧾 Chờ chủ shop duyệt", [r for r in mo if r.get("Trạng thái") == "Chờ duyệt"],
         lambda r: f"{esc(r['ID'])} {esc(r.get('Loại'))}")
    nhom("⚖️ Lỗi kho chờ xác nhận phạt", [r for r in rs if str(r.get("Phạt kho", "")).startswith("Chờ")],
         lambda r: f"{esc(r['ID'])} {esc(r.get('Lý do'))}")
    da_co = {"Chờ hàng hoàn về", "Chờ gọi KH", "Chờ tạo đơn đi", "Chờ CS gắn đơn", "Chờ khiếu nại sàn",
             "Chờ sàn trả lời", "Chờ duyệt"}   # các mục trên đã liệt kê
    tre = [(r, g, c) for r, g, c in qua_han(rs) if r.get("Trạng thái") not in da_co]
    if tre:
        L.append(f"\n<b>⏳ Quá hạn ở bước khác</b> ({len(tre)})")
        L.extend(dong_tre(r, g, c) for r, g, c in tre[:20])
    hq = [r for r in rs if str(r.get("Ngày tạo", ""))[:10] ==
          datetime.fromtimestamp(time.time() - 86400).strftime("%Y-%m-%d")]
    if hq:
        dem = {}
        for r in hq:
            dem[r.get("Loại")] = dem.get(r.get("Loại"), 0) + 1
        L.append("\n<b>Hôm qua</b>: " + ", ".join(f"{k} {v}" for k, v in dem.items()))
    if datetime.now().weekday() == 0:
        L.append(bao_cao_tuan(rs))
        if send:
            try:   # thống kê lý do hoàn theo mẫu tuần trước → file theo dõi của CEO
                import ly_do_hoan
                ly_do_hoan.ghi()
            except Exception as e:
                print("ticket: ly_do_hoan lỗi", e, flush=True)
    text = "\n".join(L)
    if len(L) == 1:
        text += "\nKhông có việc trễ 🎉"
    print(re.sub(r"<[^>]+>", "", text))
    if send and tchat():
        tsend(tchat(), text)


# ---- quá hạn từng bước (knowledge/canh_bao.json → ticket_han_gio) -------------------------------------------------
# Bản 9h ở trên chỉ bắt vài bước; ticket kẹt ở bước khác (đổi trong đơn, hoàn tiền, ĐVVC, nhập QLBH…) bị im.
# nhac_tre(): mọi ticket đang dở nằm ở 1 bước quá số giờ cho phép → nhắc đúng nhóm phải làm (kho / đổi trả).
# Gọi 10h/14h/18h từ cua_hang.py hen; 9h nhac() gộp thêm mục "Quá hạn ở bước khác".

def han_buoc():
    try:
        c = json.load(open(os.path.join(ROOT, "knowledge", "canh_bao.json"), encoding="utf-8"))
        return {k: v for k, v in (c.get("ticket_han_gio") or {}).items() if not k.startswith("_")}
    except Exception as e:
        print("ticket: không đọc được ticket_han_gio", e, flush=True)
        return {}


def vao_buoc(r):
    """Lúc ticket vào bước hiện tại = dòng 'Lịch sử' cuối (dd/mm HH:MM, không có năm); không có → Ngày tạo."""
    dong = [x for x in str(r.get("Lịch sử") or "").splitlines() if x.strip()]
    if dong:
        m = re.match(r"(\d{2})/(\d{2}) (\d{2}):(\d{2})", dong[-1].strip())
        if m:
            d, th, h, mi = (int(x) for x in m.groups())
            n = datetime.now()
            try:
                t = datetime(n.year, th, d, h, mi)
                return t if t <= n else datetime(n.year - 1, th, d, h, mi)   # qua năm mới
            except ValueError:
                pass
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(r.get("Ngày tạo") or "")[:16 if "H" in f else 10], f)
        except ValueError:
            continue
    return None


def qua_han(rs=None):
    """[(ticket, số giờ đã nằm ở bước, cấu hình bước)] — ticket đang dở quá hạn bước hiện tại."""
    han = han_buoc()
    out = []
    for r in (all_rows() if rs is None else rs):
        st = r.get("Trạng thái")
        if not r.get("ID") or st in DONG or st not in han:
            continue
        t = vao_buoc(r)
        if not t:
            continue
        gio = (datetime.now() - t).total_seconds() / 3600
        if gio >= float(han[st].get("gio") or 24):
            out.append((r, gio, han[st]))
    return sorted(out, key=lambda x: -x[1])


def _gio_txt(g):
    return f"{int(g)} giờ" if g < 48 else f"{int(g // 24)} ngày"


def dong_tre(r, g, cfg):
    return (f"• <b>{esc(r['ID'])}</b> {esc(r.get('Loại'))} · đơn <code>{esc(r.get('Mã đơn') or '?')}</code> — "
            f"<b>{esc(r.get('Trạng thái'))}</b> {_gio_txt(g)} (hạn {cfg.get('gio')}h) → {esc(cfg.get('viec') or '')}")


def nhac_tre(send=False, im=False):
    """Nhắc ticket quá hạn theo nhóm phải làm. Trả {chat: text}. im=True: không in (người gọi tự in + gửi)."""
    nhom = {"kho": str(E.get("CHAT_ID") or ""), "doitra": tchat()}
    gom = {}
    for r, g, cfg in qua_han():
        gom.setdefault(cfg.get("nhom") or "doitra", []).append(dong_tre(r, g, cfg))
    out = {}
    for k, ds in gom.items():
        c = nhom.get(k) or tchat()
        t = (f"⏳ <b>Ticket quá hạn — {'KHO làm' if k == 'kho' else 'CS làm'}</b> ({len(ds)})\n" + "\n".join(ds[:25])
             + ("\n…" if len(ds) > 25 else "") + "\nXong bước nào bấm nút trên thẻ ticket (hoặc /xem mã).")
        out[c] = (out.get(c, "") + "\n\n" + t).strip()
    for c, t in out.items():
        if not im:
            print(re.sub(r"<[^>]+>", "", t))
        if send and c:
            tsend(c, t)
    if not out and not im:
        print("Không có ticket quá hạn")
    return out


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
    elif a[0] == "tre":   # ticket quá hạn từng bước (cua_hang.py hen gọi 10/14/18h)
        nhac_tre("--send" in a)
    else:
        print(__doc__)
