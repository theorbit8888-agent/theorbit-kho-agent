#!/usr/bin/env python3
"""SÂN THỬ — chạy thử bot kho NGAY TRÊN MÁY, không cần bot Telegram, nhóm hay Google Sheet thật.

Telegram và Sheet đều là giả: tin bot trả lời in ra màn hình, dữ liệu ghi vào logs/san-thu/sheet.json.
Không gửi tin thật, không đụng dữ liệu thật. Dành cho team góp ý / hoàn thiện code (kể cả nhờ Claude Code chạy).

  python3 tools/san_thu.py                 # gõ tay từng dòng (xem HUONG DAN ở dưới)
  python3 tools/san_thu.py kich-ban.txt    # chạy 1 file kịch bản (mỗi dòng 1 lệnh như gõ tay)
  python3 tools/san_thu.py --reset         # xoá dữ liệu sân thử, làm lại từ đầu
  thêm --co-nhanh: dùng dữ liệu Nhanh đã đồng bộ trên máy (logs/nhanh/, chỉ máy chủ shop có)

HƯỚNG DẪN (mỗi dòng):
  kho: /hangve ...        gửi tin vào nhóm Kho          (nhóm: kho | doitra | ch | rieng)
  doitra: /tk             gửi vào nhóm Đổi trả CS-Kho
  ch: /moca 4tr           gửi vào nhóm CS & Cửa hàng
  rieng: ...              nhắn riêng với bot
  la cs | la kho | la chu | la la     đổi người đang gõ (CS Mai / Kho Tuấn / Chủ shop / người lạ)
  bam 2                   bấm nút số 2 của tin có nút gần nhất (bam 2 @3 = nút 2 của tin #3)
  tra <nội dung>          trả lời (reply) tin bot vừa hỏi "trả lời tin này" (tra anh = trả lời bằng ảnh)
  anh [chú thích]         gửi 1 ảnh (giả) vào nhóm đang đứng, có thể kèm lệnh: anh /hoan SPX123
  xem <tên bảng>          in dữ liệu 1 bảng (xem = liệt kê các bảng)
  phieu                   in phiếu điểm kho cuối ngày (bot gửi chủ shop 18h)
  nhanh-gia               nạp dữ liệu Nhanh giả (tồn + đơn 14 ngày) để thử dự báo hết hàng
  nhanh-don               nạp 9 đơn chờ gửi giả (thử /indon /giao /doisoat)
  nhanh-st MVĐ 59|63      giả Nhanh đồng bộ: ĐVVC đã lấy / khách huỷ
  doisoat                 chạy đối soát chiều như lịch 17h
  so-san tt.csv sp.csv    giả 7h30: danh sách sàn cần gửi (csv "ma|mvd|tt|giao", - = không đọc được sàn) so với Nhanh
  canlay tt.csv sp.csv    giả 7h30 bước 3b: in mã đơn bot sẽ bấm Tải đơn trên Nhanh
  nhanh-them MÃ MVĐ kênh SKU   giả bấm Tải đơn xong: Nhanh có thêm đơn (chờ gửi)
  thieu                   in sổ "đơn sàn mà Nhanh chưa có" (như nhắc 9h/17h)
  nhanh-phieu ID SKU:SL,SKU:SL   giả kho tạo phiếu nhập trên Nhanh (hôm nay)
  doichieu-nhap           như sau mỗi lần đồng bộ Nhanh: đối chiếu phiếu nhập ↔ hàng về (03), tự tick / báo lệch
  gio10                   chạy lượt 10h15 (đơn huỷ sau in trước khi shipper lấy)
  canhhuy                 như sau mỗi lần đồng bộ Nhanh: báo đơn vừa huỷ sau khi in (rút kiện)
  nhanh-hoan MVĐ 72|74|71|61 [ngày gửi]   giả đơn hoàn ĐVVC / giao thất bại trên Nhanh
  nhanh-tra MÃ_SÀN        giả kho nhập trả trên Nhanh (Nhanh tạo đơn trả MÃ_SÀN+R)
  mahoan-can              in mã tem hoàn kho quét mà bot chưa ra đơn (tác vụ lịch sẽ tra trên sàn)
  mahoan TEM MÃ_SÀN       giả tác vụ lịch tra tem hoàn trên sàn ra đơn gốc
  doisoat-hoan            đối soát hàng hoàn Nhanh ↔ kho quét /hoan (như tin 9h/17h)
  hoan-lui N              lùi mốc "bot thấy lần đầu / kiện về / kho /hoan" trong sổ hoan-san N GIỜ LÀM (thử nhắc theo hạn)
  lydo                    thống kê lý do hoàn theo mẫu TUẦN NÀY (bot ghi tuần trước vào file CEO 9h thứ 2)
  hoan-san tt.csv sp.csv  giả tác vụ đọc yêu cầu hoàn TikTok/Shopee → báo nhóm Đổi trả + Kho (csv: xem tools/hoan_san.py)
  dubao                   chạy nhắc đặt hàng buổi sáng (bot nhắn riêng chủ shop, có nút)
  nhanh-sp MVĐ SKU        giả kho sửa sản phẩm trong đơn trên Nhanh (đổi size trước khi giao)
  nhanh-phieutra MÃ       giả kho nhập hoàn kho / nhập trả trên Nhanh (phiếu nhập trả của đơn gốc)
  nhaphoan                như sau mỗi lần đồng bộ Nhanh: tick bảng 09, đóng ticket QLBH, kiểm SKU đơn đi đổi
  nhaphoan-nhac           như 10/14/18h: kiện nguyên vẹn đã nhận mà Nhanh chưa nhập hoàn
  hoan-lui-ngay MVĐ N     lùi ngày nhận của dòng 09 N ngày (thử nhắc nhập hoàn)
  tk-tre                  nhắc ticket quá hạn từng bước (như lịch 10/14/18h)
  tk-lui ID GIỜ           lùi mốc vào bước hiện tại của ticket N giờ (thử nhắc quá hạn)
  hoatoc-lui V-ID PHÚT    lùi thẻ hoả tốc đổi size N phút rồi chạy nhắc "chưa đổi size"
  # ...                   ghi chú, bỏ qua
Dòng nhiều dòng (dán mẫu): kết thúc dòng bằng \\ để nối dòng sau.
"""
import html, json, os, re, sys, time

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SAN = os.environ.get("SAN_THU_DIR") or os.path.join(ROOT, "logs", "san-thu")   # phong_thu.py dùng thư mục riêng
DB = os.path.join(SAN, "sheet.json")
os.makedirs(SAN, exist_ok=True)
if "--reset" in sys.argv:
    for f in os.listdir(SAN):
        p = os.path.join(SAN, f)
        if os.path.isfile(p):
            os.remove(p)
        elif f == "nhanh":   # dữ liệu Nhanh giả (nhanh-gia)
            import shutil
            shutil.rmtree(p, ignore_errors=True)
    print("Đã xoá dữ liệu sân thử."); sys.exit()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orbit_tg as TG  # noqa: E402

NHOM = {"kho": -1008888, "doitra": -1009999, "ch": -1007777}
TEN_NHOM = {v: k for k, v in NHOM.items()}
NGUOI = {"cs": (11, "CS Mai"), "kho": (22, "Kho Tuấn"), "chu": (1000, "Chủ shop"), "la": (777, "Người lạ")}
TEN = {uid: t for uid, t in NGUOI.values()}
ENV = {"TELEGRAM_BOT_TOKEN": "san-thu", "KHO_URL": "san-thu", "KHO_SECRET": "san-thu", "OWNER_TELE_ID": "1000",
       "CHAT_ID": str(NHOM["kho"]), "TICKET_CHAT_ID": str(NHOM["doitra"]), "CH_CHAT_ID": str(NHOM["ch"])}

# ---------------- Sheet giả (JSON) ----------------
def _doc():
    try:
        return json.load(open(DB))
    except Exception:
        return {"tables": {}, "next": 1}


def _ghi(d):
    json.dump(d, open(DB, "w"), ensure_ascii=False, indent=1)


def fake_kho(action, **b):
    d = _doc(); T = d["tables"]
    if action == "tables":
        return [{"name": n, "cols": t["cols"]} for n, t in T.items()]
    if action == "setup":
        for n, cols in (b.get("tables") or {}).items():
            t = T.setdefault(n, {"cols": [], "rows": []})
            t["cols"] += [c for c in cols if c not in t["cols"]]
        _ghi(d); return {}
    t = T.setdefault(b.get("table", "?"), {"cols": [], "rows": []})
    if action == "list":
        return [dict(r) for r in t["rows"]]
    if action == "add":
        ids = []
        for r in b.get("rows") or []:
            rid = f"r{d['next']}"; d["next"] += 1
            t["rows"].append(dict(r, _id=rid)); ids.append(rid)
            t["cols"] += [c for c in r if c not in t["cols"]]
        _ghi(d); return ids
    if action == "update":
        for r in t["rows"]:
            if r["_id"] == b.get("id"):
                r.update(b.get("fields") or {})
        _ghi(d); return {}
    if action == "delete":
        ids = set(b.get("ids") or [b.get("id")])
        t["rows"] = [r for r in t["rows"] if r["_id"] not in ids]
        _ghi(d); return {}
    if action == "anh":
        for r in t["rows"]:
            if r["_id"] == b.get("id"):
                r[b.get("col", "Ảnh")] = "[ảnh]"
        _ghi(d); return {}
    return {}


# ---------------- Telegram giả ----------------
MID = [int(time.time()) % 100000 * 10]
TIN = {}      # số thứ tự -> {chat, mid, text, nut:[(nhãn, data)]}
SO = [0]
CUOI = {"nut": None, "hoi": {}}


def _in_tin(method, b, mid):
    SO[0] += 1
    nut = [(x["text"], x.get("callback_data") or x.get("url")) for row in (b.get("reply_markup") or {}).get("inline_keyboard", []) for x in row]
    # như Telegram thật: tin trả về trong nút bấm là chữ trơn (bỏ thẻ HTML, giải mã &lt; &amp;)
    tron = html.unescape(re.sub(r"<[^>]+>", "", b.get("text", "")))
    if method.startswith("edit"):   # tin bị sửa: bản cũ không còn nút
        for t in TIN.values():
            if t["mid"] == mid and str(t["chat"]) == str(b["chat_id"]):
                t["nut"] = []
    TIN[SO[0]] = {"chat": b["chat_id"], "mid": mid, "text": tron, "nut": nut}
    noi = TEN_NHOM.get(int(b["chat_id"])) if str(b["chat_id"]).lstrip("-").isdigit() else None
    noi = f"nhóm {noi}" if noi else f"riêng → {TEN.get(int(b['chat_id']), b['chat_id'])}"
    sua = " (sửa tin)" if method == "editMessageText" else ""
    txt = TG.re.sub(r"<[^>]+>", "", b.get("text", "")) if hasattr(TG, "re") else b.get("text", "")
    print(f"\n🤖 #{SO[0]} [{noi}]{sua}\n{txt}")
    for i, (n, _) in enumerate(nut, 1):
        print(f"   [{i}] {n}")
    if nut:
        CUOI["nut"] = SO[0]
    if (b.get("reply_markup") or {}).get("force_reply") or "trả lời tin này" in b.get("text", ""):
        CUOI["hoi"][str(b["chat_id"])] = mid


def fake_api(method, body=None, timeout=70, files=None):
    b = body or {}
    if method == "getMe":
        return {"ok": True, "result": {"id": 1, "username": "theorbit_kho_bot", "is_bot": True, "first_name": "Bot kho (thử)"}}
    if method == "getChatMember":
        return {"ok": True, "result": {"status": "left" if b.get("user_id") == 777 else "member"}}
    if method in ("sendMessage", "sendPhoto", "sendDocument", "editMessageText", "editMessageCaption"):
        if "caption" in b and "text" not in b:
            b = dict(b, text=b["caption"])
        if method.startswith("edit"):
            mid = b.get("message_id")
        else:
            MID[0] += 1; mid = MID[0]
        _in_tin(method, b, mid)
        return {"ok": True, "result": {"message_id": mid, "chat": {"id": b["chat_id"], "type": "group"},
                                        "date": int(time.time()), "text": b.get("text", "")}}
    if method == "editMessageReplyMarkup":
        kb = (b.get("reply_markup") or {}).get("inline_keyboard")
        for t in TIN.values():   # như Telegram: tin bị gỡ nút thì không bấm được nữa
            if t["mid"] == b.get("message_id") and str(t["chat"]) == str(b.get("chat_id")):
                t["nut"] = [(x["text"], x.get("callback_data") or x.get("url")) for row in (kb or []) for x in row]
        if not kb:
            CUOI["nut"] = max((k for k, t in TIN.items() if t["nut"]), default=None)
            print(f"   (bot gỡ nút của tin {b.get('message_id')})")
        return {"ok": True, "result": True}
    if method == "answerCallbackQuery":
        if b.get("text"):
            print(f"   💬 popup: {b['text']}")
        return {"ok": True, "result": True}
    if method == "getFile":
        return {"ok": True, "result": {"file_path": "x.jpg"}}
    return {"ok": True, "result": True}


TG.api = fake_api
ANH_THAT = [None]
TG.download = lambda fid: ANH_THAT[0] or b"\xff\xd8\xff\xe0 anh gia san thu"
TG.kho = fake_kho

import re  # noqa: E402
TG.re = re
import lark as Lk  # noqa: E402
Lk.load_env = lambda: dict(ENV)
import ticket as TK  # noqa: E402
import kho_flow  # noqa: E402,F401
import cua_hang  # noqa: E402,F401
import day_bot  # noqa: E402,F401
day_bot.DRAFT_F = os.path.join(SAN, "day_nhap.json")
day_bot.SU_KIEN = os.path.join(SAN, "day_su_kien.log")

import nhanh as NH  # noqa: E402
import types  # noqa: E402
# chặn mọi việc chạy ngoài (xuất Sheet thật, mở Chrome Nhanh, nhắn chủ shop thật qua bot thật)
_sp = types.SimpleNamespace(run=lambda *a, **k: print("   (sân thử: bỏ qua lệnh chạy ngoài)"),
                            Popen=lambda *a, **k: print("   (sân thử: bỏ qua mở Chrome Nhanh)"),
                            STDOUT=None, PIPE=None)
kho_flow.subprocess = _sp
kho_flow.TON_MOI = False   # sân thử: không đọc API Nhanh thật lúc /kiemkho
TK.__dict__["subprocess"] = _sp
import subprocess as _real_sp  # noqa: E402
_goc_popen = _real_sp.Popen


class _ChanNhanh(_goc_popen):   # chỉ chặn mở Chrome Nhanh; công cụ khác (đọc mã vạch) chạy bình thường
    def __init__(self, args, *a, **k):
        if any("nhanh.py" in str(x) for x in (args if isinstance(args, (list, tuple)) else [args])):
            raise RuntimeError("sân thử: bỏ qua mở Chrome Nhanh")
        super().__init__(args, *a, **k)


_real_sp.Popen = _ChanNhanh
NH.bao_loi = lambda *a, **k: print("   (sân thử: Nhanh lỗi — bỏ qua báo chủ shop)")
if "--co-nhanh" not in sys.argv:   # mặc định không dùng dữ liệu Nhanh trên máy (máy team không có)
    NH.CACHE = os.path.join(SAN, "nhanh")
    import nhanh_api as _NA
    _NA.co_api = lambda: False   # sân thử không gọi API Nhanh thật
TK.STATE = os.path.join(SAN, "ticket_state.json")
kho_flow.DH_STATE = os.path.join(SAN, "dat_hang.json")   # quyết định đặt hàng thử, không đụng file thật
import xuat_kho  # noqa: E402
xuat_kho.STATE = os.path.join(SAN, "xuat_kho.json")
xuat_kho.SAN_DIR = os.path.join(SAN, "san")
xuat_kho.HUY_F = os.path.join(SAN, "huy_sau_in.json")
xuat_kho.THIEU_F = os.path.join(SAN, "nhanh_thieu.json")
xuat_kho.LAY_F = os.path.join(SAN, "san", "lay_nhanh.json")
kho_flow.NHAP_ST = os.path.join(SAN, "nhap_nhanh.json")
NH.MA_HOAN_F = os.path.join(SAN, "ma_hoan.json")   # sổ mã tem hoàn → đơn gốc (giả)
PHIEU_F = os.path.join(SAN, "phieu_nhap.json")   # phiếu nhập Nhanh giả (nhanh-phieu)
kho_flow.phieu_nhap = lambda tu: [b for b in (json.load(open(PHIEU_F)) if os.path.exists(PHIEU_F) else []) if b["ngay"] >= tu]
import hoan_san  # noqa: E402
import tru_ton  # noqa: E402
tru_ton.STATE_F = os.path.join(SAN, "tru_ton.json")
cua_hang.HT_NHAC_F = os.path.join(SAN, "hoatoc_nhac.json")   # sổ "đã nhắc hoả tốc chưa đổi size"
import nhap_hoan  # noqa: E402
nhap_hoan.STATE_F = os.path.join(SAN, "nhap_hoan.json")
tru_ton.BAT_F = os.path.join(SAN, "tru_ton_bat")
tru_ton.xuat_nhanh = lambda kho, sp, gc: "THU-" + str(int(time.time()))   # không bao giờ ghi Nhanh thật
tru_ton.dieu_chinh = lambda kho, lech, gc: "xuất THU-1"
kho_flow.XUONG_F = os.path.join(SAN, "xuong.json")
import chuyen_kho  # noqa: E402
chuyen_kho.STATE_F = os.path.join(SAN, "chuyen_kho.json")
CK_F = os.path.join(SAN, "ck_nhanh.json")   # phiếu chuyển kho giả (ck-xuat / ck-nhap)
def _ck_doc(ngay=7):
    d = json.load(open(CK_F)) if os.path.exists(CK_F) else {"x": {}, "n": {}}
    return d["x"], d["n"]
chuyen_kho.doc_nhanh = _ck_doc
hoan_san.STATE = os.path.join(SAN, "hoan_san.json")
hoan_san.LDH.SO = os.path.join(SAN, "hoan_ly_do.json")
hoan_san.XU_LY = os.path.join(SAN, "hoan_xu_ly.json")
import so_sheet
so_sheet.CACHE = os.path.join(SAN, "so_sheet.json")
hoan_san.CHO = os.path.join(SAN, "hoan_cho_san.json")
hoan_san.KHO_LUC = os.path.join(SAN, "hoan_kho_luc.json")
hoan_san.LOI_DOC = os.path.join(SAN, "hoan_san_loi.json")
hoan_san.LDH.OUT = os.path.join(SAN, "ly-do-hoan.md")
TK.init(dict(ENV), start_worker=False)
TG.S["root"] = SAN

DANG = {"uid": NGUOI["cs"][0], "chat": NHOM["kho"]}


def _u(uid):
    return {"id": uid, "first_name": TEN[uid], "is_bot": False, "username": f"thu{uid}"}


def chay(upd):
    try:
        if TK.on_update(upd):
            TK.handle(upd)
        else:
            print("   (bot không xử lý tin này — tin thường/không phải lệnh)")
    except SystemExit as e:
        print(f"   ⚠️ bot báo lỗi: {e}")


def gui(text=None, photo=False, reply=None):
    MID[0] += 1
    chat = DANG["chat"]
    m = {"message_id": MID[0], "date": int(time.time()), "from": _u(DANG["uid"]),
         "chat": {"id": chat, "type": "private" if chat == DANG["uid"] else "group"}}
    if photo:
        m["photo"] = [{"file_id": f"ANH{MID[0]}", "file_size": 1000}]
        if text:
            m["caption"] = text
    elif text is not None:
        m["text"] = text
    if reply:
        m["reply_to_message"] = {"message_id": reply, "from": {"id": 1, "is_bot": True}}
    chay({"update_id": MID[0], "message": m})


def bam(arg):
    p = arg.split("@")
    so = int(p[1]) if len(p) > 1 else CUOI["nut"]
    t = TIN.get(so)
    if not t or not t["nut"]:
        return print("   (không có tin có nút)")
    i = int(p[0]) - 1
    nhan, data = t["nut"][i]
    print(f"👆 {TEN[DANG['uid']]} bấm [{nhan}]")
    if int(t["chat"]) < 0 or int(t["chat"]) == DANG["uid"]:   # bấm nút ở nhóm / chat riêng nào thì đang đứng ở đó
        DANG["chat"] = int(t["chat"])
    if data and data.startswith("http"):
        m = re.search(r"[?&]start=([\w-]+)", data)
        if not m:
            return print(f"   (nút mở link: {data})")
        print("   (mở chat riêng với bot)")
        DANG["chat"] = DANG["uid"]
        return gui(f"/start {m.group(1)}")
    MID[0] += 1
    chay({"update_id": MID[0], "callback_query": {"id": f"cq{MID[0]}", "from": _u(DANG["uid"]), "data": data,
          "message": {"message_id": t["mid"], "chat": {"id": t["chat"], "type": "group"}, "text": t["text"]}}})


def xem(ten):
    T = _doc()["tables"]
    if not ten:
        return print("Các bảng: " + ", ".join(f"{n} ({len(t['rows'])})" for n, t in T.items()))
    n = next((k for k in T if ten.lower() in k.lower()), None)
    if not n:
        return print("   không có bảng đó")
    for r in T[n]["rows"][-15:]:
        print("  • " + " | ".join(f"{k}: {v}" for k, v in r.items() if v not in ("", None)))


def dong(line):
    line = line.strip()
    if not line or line.startswith("#"):
        return
    print(f"\n👤 {TEN[DANG['uid']]} › {line}")
    m = re.match(r"(kho|doitra|ch|rieng):\s*(.*)", line, re.S)
    if m:
        DANG["chat"] = DANG["uid"] if m.group(1) == "rieng" else NHOM[m.group(1)]
        return gui(m.group(2))
    cmd, _, rest = line.partition(" ")
    if cmd == "la" and rest in NGUOI:
        DANG["uid"] = NGUOI[rest][0]
        if DANG["chat"] > 0:
            DANG["chat"] = DANG["uid"]
        return print(f"   → giờ đang là {TEN[DANG['uid']]}")
    if cmd == "bam":
        return bam(rest)
    if cmd == "tra":
        r = CUOI["hoi"].get(str(DANG["chat"]))
        if rest == "anh" or rest.startswith("anh "):
            return gui(rest[4:] or None, photo=True, reply=r)
        return gui(rest, reply=r)
    if cmd == "anh":
        if rest.startswith("file:"):   # anh file:/đường/dẫn.jpg /hoan  → ảnh thật (thử đọc mã vạch)
            duong, _, cap = rest[5:].partition(" ")
            ANH_THAT[0] = open(os.path.expanduser(duong), "rb").read()
            return gui(cap or None, photo=True)
        return gui(rest or None, photo=True)
    if cmd == "xem":
        return xem(rest)
    if cmd == "nhanh-gia":   # Rivet M sắp hết, Redline đã hết M, Archive dư hàng
        os.makedirs(NH.CACHE, exist_ok=True)
        sp = {"SO-A4-RIVET-S": ("ORBIT RIVET WASHED SHORTS - S", 23, 20), "SO-A4-RIVET-M": ("ORBIT RIVET WASHED SHORTS - M", 7, 38),
              "SO-A4-RIVET-L": ("ORBIT RIVET WASHED SHORTS - L", 10, 12), "SO-A4-RIVET-XL": ("ORBIT RIVET WASHED SHORTS - XL", 55, 6),
              "TS-H2-REDLINE-M": ("REDLINE TEE - M", 0, 17), "TS-H2-REDLINE-L": ("REDLINE TEE - L", 5, 9),
              "TS-D2-ARCHIVE-S": ("ARCHIVE TEE - S", 234, 8)}
        pr = {k: {"ten": v[0], "co_the_ban": v[1], "trong_kho": v[1]} for k, v in sp.items()}
        pr["CB-RIVETREDLINE-ML"] = {"ten": "COMBO RIVET M + REDLINE L", "co_the_ban": 0, "trong_kho": 0,
                                    "combo": [{"ma": "SO-A4-RIVET-M", "sl": 1}, {"ma": "TS-H2-REDLINE-L", "sl": 1}]}
        json.dump(pr, open(os.path.join(NH.CACHE, "products.json"), "w"))
        json.dump({str(i): {"id": str(i), "kenh": "tiktok", "ma_san": f"58{i:010d}", "mvd": f"GIA{i:06d}", "dvvc": "",
                            "st": 60, "st_ten": "Thành công", "tao": time.strftime("%Y-%m-%d 09:00:00"), "cap_nhat": "",
                            "gui_dvvc": "", "kho": "KHO TỔNG - CN QUẬN 2", "sp": [{"ma": k, "sl": v[2]}]}
                   for i, (k, v) in enumerate(list(sp.items()) + [("CB-RIVETREDLINE-ML", ("", 0, 4))])},
                  open(os.path.join(NH.CACHE, "orders.json"), "w"))
        json.dump({"dong_bo": time.strftime("%Y-%m-%d %H:%M")}, open(os.path.join(NH.CACHE, "meta.json"), "w"))
        return print("   (đã nạp Nhanh giả: Rivet, Redline, Archive)")
    if cmd == "nhanh-don":   # đơn chờ gửi giả: TikTok 5 (1 chưa MVĐ, 1 tồn 30h), Shopee 3, Web 1
        os.makedirs(NH.CACHE, exist_ok=True)
        p = os.path.join(NH.CACHE, "orders.json")
        od = json.load(open(p)) if os.path.exists(p) else {}
        cu = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 30 * 3600))
        for i, (k, mvd) in enumerate([("tiktok", "TT1001"), ("tiktok", "TT1002"), ("tiktok", "TT1003"), ("tiktok", "TT1004"),
                                      ("tiktok", ""), ("shopee", "SPXVN2001"), ("shopee", "SPXVN2002"),
                                      ("shopee", "SPXVN2003"), ("ngoai", "GHN3001")]):
            oid = str(9000 + i)
            od[oid] = {"id": oid, "kenh": k, "ma_san": f"58{9000 + i}", "mvd": mvd, "dvvc": "", "st": 42,
                       "st_ten": "Đang đóng gói", "tao": cu if mvd == "TT1001" else time.strftime("%Y-%m-%d 08:00:00"),
                       "cap_nhat": "", "gui_dvvc": "", "kho": "KHO TỔNG - CN QUẬN 2", "sp": [{"ma": "SO-A4-RIVET-L", "sl": 1}]}
        json.dump(od, open(p, "w"))
        json.dump({"dong_bo": time.strftime("%Y-%m-%d %H:%M")}, open(os.path.join(NH.CACHE, "meta.json"), "w"))
        return print("   (đã nạp 9 đơn chờ gửi giả)")
    if cmd == "nhanh-st":    # nhanh-st MVĐ 59|63  → giả Nhanh đồng bộ: ĐVVC đã lấy (59) / khách huỷ (63)
        p = os.path.join(NH.CACHE, "orders.json")
        od = json.load(open(p))
        ma, so = rest.split()
        for o in od.values():
            if o["mvd"] == ma:
                o["st"] = int(so); o["st_ten"] = {59: "Đang chuyển", 63: "Khách huỷ", 68: "Hết hàng", 60: "Thành công"}.get(int(so), so)
                o["cap_nhat"] = time.strftime("%Y-%m-%d %H:%M:%S")
        json.dump(od, open(p, "w"))
        return print(f"   (Nhanh: {ma} → {so})")
    if cmd == "nhanh-sp":    # nhanh-sp MVĐ SKU  → giả kho sửa sản phẩm trong đơn trên Nhanh (đổi size trước giao)
        p = os.path.join(NH.CACHE, "orders.json")
        od = json.load(open(p))
        ma, sku = rest.split()
        for o in od.values():
            if ma.lower() in (o["mvd"].lower(), o["ma_san"].lower(), o["id"]):
                o["sp"] = [{"ma": sku.upper(), "sl": 1}]
        json.dump(od, open(p, "w"))
        json.dump({"dong_bo": time.strftime("%Y-%m-%d %H:%M")}, open(os.path.join(NH.CACHE, "meta.json"), "w"))
        return print(f"   (Nhanh: đơn {ma} giờ là {sku.upper()})")
    if cmd == "nhanh-phieutra":   # nhanh-phieutra MÃ  → giả kho nhập hoàn / nhập trả trên Nhanh: phiếu nhập trả của đơn gốc
        o = NH.don_theo_ma(rest.strip())
        if not o:
            return print(f"   (Nhanh chưa có đơn {rest.strip()})")
        p = os.path.join(NH.CACHE, "nhap_tra.json")
        nt = json.load(open(p)) if os.path.exists(p) else {}
        nt[o["id"]] = {"bill": str(700000 + len(nt)), "luc": time.strftime("%Y-%m-%d %H:%M:%S"), "nguoi": "Kho Tuấn",
                       "kho": "", "sp": [[x["ma"], x["sl"], ""] for x in o.get("sp") or []]}
        json.dump(nt, open(p, "w"))
        return print(f"   (Nhanh: phiếu nhập trả đơn {o['ma_san'] or o['id']})")
    if cmd == "nhaphoan":    # như sau mỗi lần đồng bộ Nhanh: tick bảng 09, đóng ticket QLBH, kiểm SKU đơn đi đổi
        nhap_hoan.dong_bo(send=True)
        return
    if cmd == "nhaphoan-nhac":   # như 10/14/18h: kiện nguyên vẹn đã nhận mà Nhanh chưa nhập hoàn
        for c_, t_ in nhap_hoan.nhac():
            TK.tsend(c_, t_)
        return
    if cmd == "hoan-lui-ngay":   # hoan-lui-ngay MVĐ N → lùi cột Ngày của dòng 09 N ngày (thử nhắc nhập hoàn)
        ma, n = rest.split()
        for r in TG.rows(TK.HOAN, fresh=True):
            if str(r.get("MVĐ")) == ma:
                TG.kho("update", table=TG.sname(TK.HOAN), id=r["_id"],
                       fields={"Ngày": time.strftime("%Y-%m-%d", time.localtime(time.time() - int(n) * 86400))})
        return print(f"   (09: {ma} lùi {n} ngày)")
    if cmd == "tk-tre":      # như lịch 10/14/18h: ticket quá hạn từng bước (canh_bao.json ticket_han_gio)
        TK.nhac_tre(send=True)
        return
    if cmd == "tk-lui":      # tk-lui ID GIỜ → lùi mốc "vào bước hiện tại" của ticket (thử nhắc quá hạn)
        tid, gio = rest.split()
        r = TK.get(tid)
        if not r:
            return print(f"   (không thấy ticket {tid})")
        t = time.strftime("%d/%m %H:%M", time.localtime(time.time() - float(gio) * 3600))
        TK.upd(r, {"Lịch sử": (str(r.get("Lịch sử") or "") + f"\n{t} sân thử: lùi {gio} giờ").strip()})
        return print(f"   ({tid} vào bước hiện tại lúc {t})")
    if cmd == "hoatoc-lui":  # hoatoc-lui V-ID PHÚT → lùi "Lúc giao" thẻ việc rồi chạy nhắc hoả tốc chưa đổi size
        vid, ph = rest.split()
        import cua_hang as CH
        for r in CH.rows(CH.VIEC):
            if r.get("ID") == vid:
                t = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - float(ph) * 60))
                TG.kho("update", table=TG.sname(CH.VIEC), id=r["_id"], fields={"Lúc giao": t})
        for c_, t_ in CH.nhac_hoatoc(send=True):
            TK.tsend(c_, t_)
        return
    if cmd in ("so-san", "canlay"):   # so-san kich-ban/so-tt.csv kich-ban/so-sp.csv
        f = (rest.split() + ["-", "-"])[:2]
        opt = {"--" + k: (os.path.join(ROOT, x) if not os.path.isabs(x) else x) for k, x in zip(("tiktok", "shopee"), f) if x != "-"}
        d = xuat_kho.doc_csv_san(opt)
        if cmd == "canlay":
            out = xuat_kho.can_lay(d)
            os.makedirs(os.path.dirname(xuat_kho.LAY_F), exist_ok=True)
            json.dump(dict(out, ngay=xuat_kho.KF.today()), open(xuat_kho.LAY_F, "w"))
            return print("   BOT SẼ BẤM TẢI ĐƠN:", json.dumps(out, ensure_ascii=False))
        os.makedirs(xuat_kho.SAN_DIR, exist_ok=True)
        fj = os.path.join(xuat_kho.SAN_DIR, xuat_kho.KF.today() + ".json")
        json.dump(d, open(fj, "w"), ensure_ascii=False)
        xuat_kho.so_san_file(fj, send=False, doi=False)
        return
    if cmd == "nhanh-them":   # nhanh-them 580000000000000099 TT9999 tiktok SO-A4-RIVET-L
        ma_, mvd, k, sku = (rest.split() + ["", "", "SO-A4-RIVET-L"])[:4]
        p = os.path.join(NH.CACHE, "orders.json")
        od = json.load(open(p)) if os.path.exists(p) else {}
        oid = str(9500 + len(od))
        od[oid] = {"id": oid, "kenh": k, "ma_san": ma_, "mvd": mvd, "dvvc": "", "st": 42, "st_ten": "Đang đóng gói",
                   "tao": time.strftime("%Y-%m-%d 07:00:00"), "cap_nhat": "", "gui_dvvc": "", "kho": "KHO TỔNG - CN QUẬN 2",
                   "sp": [{"ma": sku, "sl": 1}]}
        json.dump(od, open(p, "w"))
        return print(f"   (Nhanh có thêm đơn {ma_} {mvd})")
    if cmd == "nhanh-hoan":   # nhanh-hoan GIA000001 72 [YYYY-MM-DD gửi]  → giả đơn hoàn ĐVVC (72 Đã chuyển hoàn, 74, 71, 61)
        p = os.path.join(NH.CACHE, "orders.json")
        od = json.load(open(p))
        ma, so, ngay = (rest.split() + [time.strftime("%Y-%m-%d")])[:3]
        for o in od.values():
            if o["mvd"] == ma or o["ma_san"] == ma:
                o.update(st=int(so), st_ten={72: "Đã chuyển hoàn", 74: "Xác nhận hoàn", 71: "Đang chuyển hoàn", 61: "Thất bại"}
                         .get(int(so), so), cap_nhat=time.strftime("%Y-%m-%d %H:%M:%S"), gui_dvvc=ngay + " 10:00:00")
        json.dump(od, open(p, "w"))
        return print(f"   (Nhanh: {ma} → hoàn {so}, gửi {ngay})")
    if cmd == "nhanh-tra":   # nhanh-tra 580000000003 → giả kho nhập trả trên Nhanh (Nhanh tạo đơn trả '<mã sàn>R')
        p = os.path.join(NH.CACHE, "orders.json")
        od = json.load(open(p))
        g = next((o for o in od.values() if o["ma_san"] == rest.strip()), None)
        oid = str(9800 + len(od))
        od[oid] = {"id": oid, "kenh": g["kenh"] if g else "tiktok", "ma_san": rest.strip() + "R", "mvd": "", "dvvc": "",
                   "st": 72, "st_ten": "Đã chuyển hoàn", "tao": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "cap_nhat": time.strftime("%Y-%m-%d %H:%M:%S"), "gui_dvvc": "", "kho": "", "sp": g["sp"] if g else []}
        json.dump(od, open(p, "w"))
        return print(f"   (Nhanh: nhập trả đơn {rest.strip()} → đơn trả {rest.strip()}R)")
    if cmd == "mahoan-can":
        return print("   CẦN TRA TRÊN SÀN:", json.dumps(kho_flow.ma_hoan_can(), ensure_ascii=False))
    if cmd == "mahoan":   # mahoan 854000000001 580000000003 → giả tác vụ lịch tra tem hoàn trên TikTok ra đơn gốc
        tem, ma_ = rest.split()[:2]
        return print("   (sổ tem hoàn: ghi mới", NH.ghi_ma_hoan({tem: ma_}, "tiktok"), ")")
    if cmd == "doisoat-hoan":
        t, n = kho_flow.doi_soat_hoan_nhanh()
        return print(re.sub(r"<[^>]+>", "", t) or "   (chưa có dữ liệu Nhanh)", f"\n   [cần xử lý: {n}]")
    if cmd == "nhanh-phieu":   # nhanh-phieu 180001 TS-H2-REDLINE-M:20,SO-A4-RIVET-M:38
        bid, _, ds = rest.partition(" ")
        bs = json.load(open(PHIEU_F)) if os.path.exists(PHIEU_F) else []
        bs.append({"id": bid, "ngay": time.strftime("%Y-%m-%d"), "kho": "", "mo_ta": "",
                   "sp": {k: int(v) for k, v in (x.split(":") for x in ds.split(",") if ":" in x)}})
        json.dump(bs, open(PHIEU_F, "w"))
        return print(f"   (Nhanh: phiếu nhập {bid} {ds})")
    if cmd in ("ck-xuat", "ck-nhap"):   # ck-xuat 343 Q2>PN SKU:SL,SKU:SL  |  ck-nhap 343 SKU:SL,...
        w = rest.split()
        d = json.load(open(CK_F)) if os.path.exists(CK_F) else {"x": {}, "n": {}}
        ds = w[-1]
        prods = [{"code": k, "quantity": int(v)} for k, v in (x.split(":") for x in ds.split(",") if ":" in x)]
        if cmd == "ck-xuat":
            tu, den = {"Q2": 205577, "PN": 206425}[w[1].split(">")[0]], {"Q2": 205577, "PN": 206425}[w[1].split(">")[1]]
            d["x"][w[0]] = {"id": 900000 + int(w[0]), "date": time.strftime("%Y-%m-%d"), "depotId": tu, "related": {"depotId": den},
                            "requirementBillId": int(w[0]), "created": {"name": "Thu Huyền", "createdAt": time.time()}, "products": prods}
        else:
            d["n"][w[0]] = {"id": 910000 + int(w[0]), "requirementBillId": int(w[0]),
                            "created": {"name": "Kim Thi", "createdAt": time.time()}, "products": prods}
        json.dump(d, open(CK_F, "w"))
        return print(f"   (Nhanh: {cmd} #{w[0]} {ds})")
    if cmd == "ck-quet":
        return print("   " + chuyen_kho.quet(True))
    if cmd == "ck-lui":   # lùi mốc thời gian thẻ chuyển kho (thử nhắc)
        st = json.load(open(chuyen_kho.STATE_F))
        for x in st.values():
            x["tao"] -= 4 * 3600
            if x.get("nhan"): x["nhan"]["ts"] -= 3600
        json.dump(st, open(chuyen_kho.STATE_F, "w"))
        return print("   (lùi 4 tiếng)")
    if cmd == "doichieu-nhap":
        return print(re.sub(r"<[^>]+>", "", kho_flow.doi_chieu_nhap(True)) and "" or "   (không có gì mới để báo)")
    if cmd == "gio10":
        import datetime as _dt
        class _D(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return _dt.datetime.now().replace(hour=10, minute=15)
        kho_flow.datetime = _D
        try:
            kho_flow.hen(True)
        finally:
            kho_flow.datetime = _dt.datetime
        return
    if cmd == "thieu":
        return print(re.sub(r"<[^>]+>", "", xuat_kho.thieu_bao()) or "   (sổ Nhanh thiếu: trống)")
    if cmd == "doisoat":     # chạy đối soát chiều (17h) như lịch
        return print(re.sub(r"<[^>]+>", "", xuat_kho.bao_chieu()[0]))
    if cmd == "canhhuy":
        return print(re.sub(r"<[^>]+>", "", xuat_kho.canh_huy(True)) or "   (không có đơn huỷ sau in mới)")
    if cmd == "lydo":
        return print(hoan_san.LDH.bao(hoan_san.datetime.now()))
    if cmd == "hoan-lui":   # hoan-lui 3 → mọi mốc trong sổ hoan-san lùi 3 giờ làm (8h–22h)
        from datetime import timedelta
        n, st = float(rest or 0), json.load(open(hoan_san.STATE))
        def lui(s_):
            t = hoan_san._dt(s_)
            if not t:
                return s_
            x = t
            while hoan_san.gio_lam(x, t) < n:
                x -= timedelta(minutes=10)
            return x.strftime("%Y-%m-%d %H:%M")
        for v in st.values():
            for k_ in ("lan_dau", "lan_ve", "lan_kho"):
                if k_ in v:
                    v[k_] = lui(v[k_])
        json.dump(st, open(hoan_san.STATE, "w"), ensure_ascii=False, indent=1)
        kl = hoan_san._doc(hoan_san.KHO_LUC)
        hoan_san._ghi(hoan_san.KHO_LUC, {t: lui(v) for t, v in kl.items()})
        return print(f"   (lùi sổ hoan-san {n:g} giờ làm)")
    if cmd == "hoan-san":   # hoan-san kich-ban/hoan-tiktok.csv kich-ban/hoan-shopee.csv
        f = rest.split()
        d = {"luc": time.strftime("%H:%M")}
        for k, x in zip(("tiktok", "shopee"), f):
            d[k] = hoan_san.doc_csv(os.path.join(ROOT, x) if not os.path.isabs(x) else x)
        return print("   TÓM TẮT:", hoan_san.chay(d, True))
    if cmd == "dubao":
        kho_flow.nhac_dat_hang(True)
        return
    if cmd == "phieu":   # phiếu điểm kho cuối ngày (bot gửi chủ shop 18h)
        return print(re.sub(r"<[^>]+>", "", kho_flow.phieu_diem()))
    gui(line)


def main():
    files = [a for a in sys.argv[1:] if not a.startswith("--")]
    if files:
        buf = ""
        for l in open(files[0], encoding="utf-8"):
            l = l.rstrip("\n")
            if l.endswith("\\"):
                buf += l[:-1] + "\n"; continue
            dong(buf + l); buf = ""
        return
    print(__doc__.split("HƯỚNG DẪN")[1])
    print("Đang ở nhóm kho, là CS Mai. Gõ 'thoat' để thoát.")
    buf = ""
    while True:
        try:
            l = input("› ")
        except EOFError:
            break
        if l.strip() == "thoat":
            break
        if l.endswith("\\"):
            buf += l[:-1] + "\n"; continue
        dong(buf + l); buf = ""


if __name__ == "__main__":
    main()
