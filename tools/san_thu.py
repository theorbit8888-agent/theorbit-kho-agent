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
  # ...                   ghi chú, bỏ qua
Dòng nhiều dòng (dán mẫu): kết thúc dòng bằng \\ để nối dòng sau.
"""
import html, json, os, re, sys, time

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SAN = os.path.join(ROOT, "logs", "san-thu")
DB = os.path.join(SAN, "sheet.json")
os.makedirs(SAN, exist_ok=True)
if "--reset" in sys.argv:
    for f in os.listdir(SAN):
        p = os.path.join(SAN, f)
        if os.path.isfile(p):
            os.remove(p)
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
TK.STATE = os.path.join(SAN, "ticket_state.json")
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
    if int(t["chat"]) < 0:   # bấm nút trong nhóm nào thì đang đứng ở nhóm đó
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
