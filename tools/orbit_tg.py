#!/usr/bin/env python3
"""Telegram + Google Sheet thay cho Lark (The Orbit, 11/2026: Lark hết quota API, chat chuyển sang Telegram).

Bản gốc: ~/Desktop/telegram-agent/lib/orbit_tg.py — chép y nguyên vào tools/ của từng agent (kho, R&D).
lark.py của agent vẫn gọi call()/raw() theo đường API Lark như cũ; khi env bật, module này làm thay:
  - TELEGRAM_BOT_TOKEN có  -> /im/v1/... (đọc tin, trả lời, gửi, tải ảnh) đi qua Telegram.
  - KHO_URL + KHO_SECRET có -> /bitable/... và /wiki/... đi qua Google Sheet (Apps Script "KHO DỮ LIỆU").
Mã tin dạng  tg:<chat_id>:<message_id>.  Tin Telegram không đọc lại được qua API, nên listener lưu mọi tin
nhận/gửi vào logs/tg/ để lệnh `msg <id>` đọc lại (kể cả tin gốc của luồng và ảnh trong album).
Bảng trên Sheet có tiền tố "SP " (VD "SP 08 · TEST & ĐO BÁN") để không lẫn với bảng HCNS cùng file;
agent vẫn gọi tên cũ "08 · TEST & ĐO BÁN" / "08".
"""
import json, os, re, sys, time, uuid, urllib.request, urllib.error, urllib.parse
from datetime import datetime

S = {"env": {}, "schema": {}, "extra": {}, "root": ".", "prefix": "SP "}
# Kiểu cột (theo mã Lark: 2 số, 5 ngày, 7 tick, 17 ảnh) của các bảng có sẵn từ trước mà SCHEMA trong code không ghi.
PRODUCT_TYPES = {
    "01 · FLOW SẢN PHẨM": {"SL đặt SX": 2, "Ngày chốt SX": 5, "Ngày gửi demo": 5, "Hạn design": 5, "Hạn demo": 5,
                          "Hẹn hàng về": 5, "Ngày nhận kho thực tế": 5, "Ngày mở bán": 5, "HÌNH ẢNH DESIGN": 17,
                          "Ảnh demo": 17},
    "02 · HÀNG ĐẶT LẠI": {"SL đặt": 2, "SL đã nhận": 2, "Ngày đặt": 5, "Hẹn hàng về": 5, "Đã về đủ": 7},
}
_CACHE = {}  # tên bảng sheet -> (lúc, rows)


def init(env, schema, root, extra_types=None):
    extra = {k: dict(v) for k, v in PRODUCT_TYPES.items()}
    for k, v in (extra_types or {}).items():
        extra.setdefault(k, {}).update(v)
    S.update(env=env, schema=schema or {}, root=root, extra=extra)


def tg_on():
    return bool(S["env"].get("TELEGRAM_BOT_TOKEN"))


def sheet_on():
    return bool(S["env"].get("KHO_URL") and S["env"].get("KHO_SECRET"))


def handles(path):
    p = path.split("?")[0]
    if p.startswith(("/bitable/", "/wiki/", "/drive/")):
        return sheet_on()
    if p.startswith("/im/"):
        return tg_on()
    return False


# ======================= Telegram =======================

def api(method, body=None, timeout=70, files=None):
    url = f"https://api.telegram.org/bot{S['env']['TELEGRAM_BOT_TOKEN']}/{method}"
    if files:
        b = uuid.uuid4().hex
        data = b""
        for k, v in (body or {}).items():
            v = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            data += f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        for k, (name, blob) in files.items():
            data += (f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{name}\"\r\n"
                     "Content-Type: application/octet-stream\r\n\r\n").encode() + blob + b"\r\n"
        data += f"--{b}--\r\n".encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    else:
        req = urllib.request.Request(url, data=json.dumps(body or {}).encode(),
                                     headers={"Content-Type": "application/json"})
    for lan in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                out = json.loads(e.read().decode())
            except Exception:
                out = {"ok": False, "description": f"HTTP {e.code}"}
            ra = (out.get("parameters") or {}).get("retry_after")
            if ra and lan < 2:
                time.sleep(min(ra, 30)); continue
            return out
        except Exception as e:
            if lan == 2:
                return {"ok": False, "description": f"không kết nối được Telegram: {e}"}
            time.sleep(3)


def must(r, what):
    if not r.get("ok"):
        sys.exit(f"Telegram lỗi ({what}): {r.get('description')}")
    return r["result"]


def mk(chat, mid):
    return f"tg:{chat}:{mid}"


def parse(mid):
    m = re.match(r"tg:(-?\d+):(\d+)$", str(mid))
    if not m:
        sys.exit(f"Mã tin '{mid}' không phải tin Telegram (dạng tg:<chat>:<id>).")
    return m[1], int(m[2])


def _dir():
    d = os.path.join(S["root"], "logs", "tg")
    os.makedirs(d, exist_ok=True)
    return d


def save_msg(m):
    """Lưu 1 tin Telegram (dict gốc) để đọc lại sau. Tin trả lời mang theo tin gốc -> lưu luôn tin gốc."""
    if not m or "message_id" not in m:
        return
    if m.get("reply_to_message"):
        save_msg(m["reply_to_message"])
    p = os.path.join(_dir(), f"{m['chat']['id']}_{m['message_id']}.json")
    if os.path.exists(p) and "reply_to_message" not in m:
        try:  # bản đã lưu đầy đủ hơn (có reply_to) thì giữ
            if "reply_to_message" in json.load(open(p)):
                return
        except Exception:
            pass
    with open(p, "w") as f:
        json.dump(m, f, ensure_ascii=False)
    if m.get("media_group_id"):
        with open(os.path.join(_dir(), f"album_{m['chat']['id']}_{m['media_group_id']}.txt"), "a") as f:
            f.write(f"{m['message_id']}\n")


def load_msg(chat, mid):
    p = os.path.join(_dir(), f"{chat}_{mid}.json")
    return json.load(open(p)) if os.path.exists(p) else None


def photo_ids(m):
    """file_id ảnh của tin (ảnh lớn nhất; ảnh gửi dạng file cũng tính), gồm cả các ảnh cùng album."""
    def one(x):
        if x.get("photo"):
            return [x["photo"][-1]["file_id"]]
        d = x.get("document") or {}
        return [d["file_id"]] if str(d.get("mime_type", "")).startswith("image/") else []
    if not m:
        return []
    if m.get("media_group_id"):
        p = os.path.join(_dir(), f"album_{m['chat']['id']}_{m['media_group_id']}.txt")
        ids = sorted({int(x) for x in open(p).read().split()} if os.path.exists(p) else {m["message_id"]})
        out = []
        for i in ids:
            out += one(load_msg(m["chat"]["id"], i) or {})
        return out or one(m)
    return one(m)


def album_text(m):
    """Chữ của tin; tin trong album thường chỉ 1 ảnh có chú thích -> lấy chú thích của cả album."""
    t = m.get("text") or m.get("caption") or ""
    if t or not m.get("media_group_id"):
        return t
    p = os.path.join(_dir(), f"album_{m['chat']['id']}_{m['media_group_id']}.txt")
    for i in sorted({int(x) for x in open(p).read().split()} if os.path.exists(p) else []):
        x = load_msg(m["chat"]["id"], i) or {}
        if x.get("caption"):
            return x["caption"]
    return ""


def who(u):
    if not u:
        return ""
    n = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x)
    return n + (f" @{u['username']}" if u.get("username") else "")


def to_lark(m):
    """Tin Telegram -> dạng tin Lark mà lark.py đang đọc (msg_text, image_keys, parent_id)."""
    chat = m["chat"]["id"]
    text = album_text(m)
    pics = photo_ids(m)
    if pics:
        content = {"content": [[{"tag": "text", "text": ln}] for ln in (text.split("\n") if text else [])]
                   + [[{"tag": "img", "image_key": k} for k in pics]]}
        typ = "post"
    else:
        content, typ = {"text": text}, "text"
    par = m.get("reply_to_message")
    return {"message_id": mk(chat, m["message_id"]), "chat_id": str(chat), "msg_type": typ,
            "body": {"content": json.dumps(content, ensure_ascii=False)},
            "parent_id": mk(chat, par["message_id"]) if par else None,
            "create_time": str(m.get("date", 0) * 1000),
            "sender": {"id": str((m.get("from") or {}).get("id", "")),
                       "sender_type": "app" if (m.get("from") or {}).get("is_bot") else "user",
                       "name": who(m.get("from"))},
            "mentions": []}


def send(chat, text, reply_to=None):
    """Gửi chữ (tự cắt tin dài). Trả mã tin đầu tiên."""
    first = None
    parts = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [""]
    for k, part in enumerate(parts):
        body = {"chat_id": chat, "text": part, "disable_web_page_preview": True}
        if reply_to and k == 0:
            body["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        m = must(api("sendMessage", body), "gửi tin")
        save_msg(m)
        first = first or mk(m["chat"]["id"], m["message_id"])
    return first


def reply(mid, text):
    chat, i = parse(mid)
    return send(chat, text, reply_to=i)


def reply_photo(mid, path, caption=None):
    chat, i = parse(mid)
    blob = open(path, "rb").read()
    body = {"chat_id": chat, "reply_parameters": {"message_id": i, "allow_sending_without_reply": True}}
    if caption:
        body["caption"] = caption[:1000]
    kind = "photo" if len(blob) < 9_500_000 else "document"
    r = api("sendPhoto" if kind == "photo" else "sendDocument", body, files={kind: (os.path.basename(path), blob)},
            timeout=180)
    if not r.get("ok") and kind == "photo":  # ảnh quá khổ -> gửi dạng file
        r = api("sendDocument", body, files={"document": (os.path.basename(path), blob)}, timeout=180)
    m = must(r, "gửi ảnh")
    save_msg(m)
    return mk(m["chat"]["id"], m["message_id"])


def download(file_id):
    f = must(api("getFile", {"file_id": file_id}), "lấy ảnh")
    url = f"https://api.telegram.org/file/bot{S['env']['TELEGRAM_BOT_TOKEN']}/{f['file_path']}"
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def get_msg(mid):
    chat, i = parse(mid)
    m = load_msg(chat, i)
    if not m:
        sys.exit(f"Chưa lưu tin {mid} (bot chỉ đọc được tin nó đã nhận/gửi từ lúc chạy Telegram).")
    return to_lark(m)


def chats():
    e = S["env"]
    return [{"chat_id": e[k], "name": k} for k in sorted(e) if (k == "CHAT_ID" or k.endswith("_CHAT_ID")) and e[k]]


# ======================= gửi song song sang Lark (tới khi bỏ hẳn Lark) =======================
# Tin MỚI bot gửi vào nhóm (báo cáo, cảnh báo 9h, lệnh sản xuất...) gửi thêm 1 bản vào nhóm Lark cũ nếu env có
# LARK_<tên biến nhóm> (VD LARK_CHAT_ID, LARK_SX_CHAT_ID). Tắt hẳn: LARK_MIRROR=0 hoặc xoá các dòng LARK_*.
# Lỗi Lark (VD hết quota) không làm hỏng tin Telegram.

def lark_mirror(tele_chat, text):
    e = S["env"]
    if e.get("LARK_MIRROR") == "0" or not e.get("APP_ID"):
        return
    var = next((k for k in e if (k == "CHAT_ID" or k.endswith("_CHAT_ID")) and not k.startswith("LARK_")
                and str(e[k]) == str(tele_chat)), None)
    lark_chat = e.get("LARK_" + var) if var else None
    if not lark_chat:
        return
    api_ = "https://open.larksuite.com/open-apis"
    try:
        def post(path, body, tk=None):
            req = urllib.request.Request(api_ + path, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json; charset=utf-8",
                                                  **({"Authorization": "Bearer " + tk} if tk else {})})
            with urllib.request.urlopen(req, timeout=15) as r:
                out = json.load(r)
            if out.get("code"):
                raise RuntimeError(f"{out.get('code')} {out.get('msg')}")
            return out
        tk = post("/auth/v3/tenant_access_token/internal", {"app_id": e["APP_ID"], "app_secret": e["APP_SECRET"]})[
            "tenant_access_token"]
        post("/im/v1/messages?receive_id_type=chat_id", {"receive_id": lark_chat, "msg_type": "text",
                                                        "content": json.dumps({"text": text})}, tk)
        print("(đã gửi thêm bản Lark)", file=sys.stderr)
    except Exception as ex:
        msg = ex.read().decode()[:200] if hasattr(ex, "read") else str(ex)[:200]
        print(f"(bản Lark không gửi được: {msg})", file=sys.stderr)


# ======================= Google Sheet (thay Lark Base) =======================

def kho(action, **b):
    body = json.dumps({"action": action, "secret": S["env"]["KHO_SECRET"], **b}, ensure_ascii=False).encode()
    for lan in range(3):
        try:
            req = urllib.request.Request(S["env"]["KHO_URL"], data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.load(r)
            break
        except Exception as e:
            if lan == 2:
                sys.exit(f"Sheet lỗi kết nối: {e}")
            time.sleep(3)
    if not out.get("ok"):
        sys.exit(f"Sheet lỗi: {out.get('error')}")
    return out["data"]


def sname(name):
    return name if name.startswith(S["prefix"]) else S["prefix"] + name


def uname(name):
    return name[len(S["prefix"]):] if name.startswith(S["prefix"]) else name


def specs(name):
    out = {}
    for s in S["schema"].get(name, []):
        out[s[0]] = (s[1], s[2] if len(s) > 2 else [])
    for k, t in (S["extra"].get(name) or {}).items():
        out.setdefault(k, (t, []))
    return out


def sheet_tables():
    return [t for t in kho("tables") if t["name"].startswith(S["prefix"])]


def rows(name, fresh=False):
    sn = sname(name)
    hit = _CACHE.get(sn)
    if hit and not fresh and time.time() - hit[0] < 20:
        return hit[1]
    rs = kho("list", table=sn)
    _CACHE[sn] = (time.time(), rs)
    return rs


def _ms(v):
    v = str(v).strip()
    for f, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10), ("%d/%m/%Y", 10)):
        try:
            return int(datetime.strptime(v[:n], f).timestamp() * 1000)
        except ValueError:
            pass
    return v


def to_rec(name, r):
    ty, f = specs(name), {}
    for k, v in r.items():
        if k == "_id" or v in ("", None):
            continue
        t = ty.get(k, (1, []))[0]
        if t == 2:
            try:
                v = float(str(v).replace(",", ""))
            except ValueError:
                pass
        elif t in (5, 1001, 1002):
            v = _ms(v)
        elif t == 7:
            v = str(v).strip().lower() in ("true", "1", "✓", "x", "có", "co", "yes")
        elif t == 17:
            try:
                v = json.loads(v) if str(v)[:1] == "[" else [x.strip() for x in str(v).split(",") if x.strip()]
            except ValueError:
                v = [str(v)]
            v = [x if isinstance(x, dict) else {"file_token": x, "name": x} for x in v]
        else:
            v = v if isinstance(v, str) else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))
        f[k] = v
    return {"record_id": r.get("_id"), "fields": f}


def to_cell(name, data):
    ty, out = specs(name), {}
    for k, v in data.items():
        t = ty.get(k, (1, []))[0]
        if t in (5, 1001, 1002) and isinstance(v, (int, float)) and v > 1e11:
            v = datetime.fromtimestamp(v / 1000).strftime("%Y-%m-%d %H:%M").replace(" 00:00", "")
        elif t == 7 or isinstance(v, bool):
            v = "✓" if (v is True or str(v).lower() in ("1", "true", "x", "có", "co", "yes", "✓")) else ""
        elif t == 17 and isinstance(v, list):
            v = json.dumps([x.get("file_token") if isinstance(x, dict) else x for x in v], ensure_ascii=False)
        elif t == 11 and isinstance(v, list):
            v = ", ".join(x.get("name") or x.get("id", "") if isinstance(x, dict) else str(x) for x in v)
        elif isinstance(v, float) and v.is_integer():
            v = int(v)
        elif isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        out[k] = v
    return out


def fields(name):
    sp = specs(name)
    have = []
    for t in kho("tables"):
        if t["name"] == sname(name):
            have = [c for c in t["cols"] if c != "_id"]
    cols = have + [c for c in sp if c not in have]
    return [{"field_name": c, "type": sp.get(c, (1, []))[0],
             "property": {"options": [{"name": o} for o in sp.get(c, (1, []))[1]]} if sp.get(c, (1, []))[1] else {}}
            for c in cols]


def xem_anh(table, rid, col, blob, name="anh.jpg"):
    """Chèn bản thu nhỏ (480px) của ảnh vào ô "<col> (xem)" để mở Sheet là thấy (action "anh" của Apps Script,
    phiên bản 4). Lỗi thì bỏ qua — ảnh gốc vẫn ở Telegram / trên máy."""
    import base64, subprocess, tempfile
    if not sheet_on() or not blob:
        return
    try:
        src = tempfile.mktemp(suffix=os.path.splitext(name)[1] or ".jpg")
        open(src, "wb").write(blob)
        nho = tempfile.mktemp(suffix=".jpg")
        subprocess.run(["/usr/bin/sips", "-Z", "480", "-s", "format", "jpeg", "-s", "formatOptions", "55", src,
                        "--out", nho], capture_output=True)
        data = open(nho, "rb").read() if os.path.exists(nho) else blob
        kho("anh", table=sname(table), id=rid, col=f"{col} (xem)", b64=base64.b64encode(data).decode(), alt=name)
        _CACHE.pop(sname(table), None)
    except BaseException as e:  # kho() có thể sys.exit
        print(f"(không chèn được ảnh xem vào Sheet: {e})", file=sys.stderr)


# ======================= giả lập đường API Lark =======================

def call(method, path, body=None):
    u = urllib.parse.urlparse(path)
    q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
    parts = [urllib.parse.unquote(x) for x in u.path.strip("/").split("/")]

    if u.path.startswith("/wiki/v2/spaces/get_node"):
        return {"code": 0, "data": {"node": {"obj_token": "sheet"}}}

    if parts[:3] == ["bitable", "v1", "apps"]:
        rest = parts[4:]
        if rest == ["tables"]:
            if method == "GET":
                return {"code": 0, "data": {"items": [{"table_id": uname(t["name"]), "name": uname(t["name"])}
                                                       for t in sheet_tables()]}}
            t = body["table"]
            kho("setup", tables={sname(t["name"]): [f["field_name"] for f in t.get("fields", [])]})
            return {"code": 0, "data": {"table_id": t["name"]}}
        tid, kind = rest[1], rest[2]
        if kind == "fields":
            if method == "GET":
                return {"code": 0, "data": {"items": fields(tid)}}
            kho("setup", tables={sname(tid): [body["field_name"]]})
            return {"code": 0, "data": {}}
        if kind == "records":
            if len(rest) == 3 and method == "GET":
                return {"code": 0, "data": {"items": [to_rec(tid, r) for r in rows(tid)], "has_more": False}}
            if len(rest) == 3 and method == "POST":
                rid = kho("add", table=sname(tid), rows=[to_cell(tid, body["fields"])])[0]
                _CACHE.pop(sname(tid), None)
                return {"code": 0, "data": {"record": {"record_id": rid, "fields": body["fields"]}}}
            rid = rest[3]
            if method == "GET":
                for r in rows(tid, fresh=True):
                    if r.get("_id") == rid:
                        return {"code": 0, "data": {"record": to_rec(tid, r)}}
                sys.exit(f"Không thấy dòng {rid} trong {tid}")
            if method in ("PUT", "PATCH"):
                kho("update", table=sname(tid), id=rid, fields=to_cell(tid, body["fields"]))
                _CACHE.pop(sname(tid), None)
                return {"code": 0, "data": {"record": {"record_id": rid}}}

    if u.path == "/im/v1/messages" and method == "POST":
        c = json.loads(body["content"])
        mid = send(body["receive_id"], c.get("text", ""))
        lark_mirror(body["receive_id"], c.get("text", ""))
        return {"code": 0, "data": {"message_id": mid}}
    if parts[:3] == ["im", "v1", "messages"] and len(parts) == 4 and method == "GET":
        return {"code": 0, "data": {"items": [get_msg(parts[3])]}}
    if parts[:3] == ["im", "v1", "messages"] and parts[-1] == "reply" and method == "POST":
        c = json.loads(body["content"])
        if body.get("msg_type") == "image" and c.get("image_key", "").startswith("file:"):
            return {"code": 0, "data": {"message_id": reply_photo(parts[3], c["image_key"][5:])}}
        return {"code": 0, "data": {"message_id": reply(parts[3], c.get("text", ""))}}
    if parts[:3] == ["im", "v1", "chats"] and method == "GET":
        return {"code": 0, "data": {"items": chats()}}
    if parts[:3] == ["im", "v1", "messages"] and parts[-1] in ("urgent_app", "urgent_phone"):
        return {"code": 0, "data": {}}  # Telegram không có Buzz: người gọi tự tag + nhắn riêng
    sys.exit(f"Đường Lark '{method} {path}' chưa có bản Telegram/Sheet.")


def raw(method, path, data=None, ctype=None):
    u = urllib.parse.urlparse(path)
    parts = u.path.strip("/").split("/")
    if parts[:3] == ["im", "v1", "messages"] and len(parts) >= 6 and parts[4] == "resources":
        return download(urllib.parse.unquote(parts[5]))
    sys.exit(f"Đường Lark '{method} {path}' chưa có bản Telegram/Sheet.")


def save_file(blob, name):
    """Thay cho tải ảnh lên Lark Base: lưu ảnh trên máy, ô ảnh ghi 'file:<đường>' (Drive đã gần đầy)."""
    d = os.path.join(S["root"], "anh-base")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, re.sub(r"[^\w.\-]+", "_", name))
    open(p, "wb").write(blob)
    return "file:" + os.path.abspath(p)


# ======================= nghe tin (listener) =======================

def poll(on_job, allow_chats, allow_users=(), state_name="tg_offset", pre=None):
    """Long-polling Telegram. Lưu mọi tin; gọi on_job(job) khi tin gọi bot: tag @bot, trả lời tin của bot,
    lệnh /..., hoặc nhắn riêng (chỉ người trong allow_users). Nhóm ngoài allow_chats: bỏ qua (trừ /chatid).
    pre(update) -> True: update đã được module khác nhận (VD ticket.py: nút bấm, phiếu nhắn riêng), bỏ qua ở đây.
    Bấm nút (callback_query) chỉ đi qua pre."""
    me = must(api("getMe"), "getMe")
    uname_ = "@" + me["username"].lower()
    stf = os.path.join(S["root"], "logs", state_name)
    off = int(open(stf).read().strip() or 0) if os.path.exists(stf) else 0
    allow_chats = {str(c) for c in allow_chats if c}
    allow_users = {str(u) for u in allow_users if u}
    print(f"Đang nghe Telegram {uname_} — nhóm: {', '.join(sorted(allow_chats)) or '(chưa có)'}", flush=True)
    while True:
        r = api("getUpdates", {"offset": off, "timeout": 50,
                               "allowed_updates": ["message", "edited_message", "my_chat_member", "callback_query"]},
                timeout=70)
        if not r.get("ok"):
            print(time.strftime("%H:%M"), "Telegram lỗi:", r.get("description"), flush=True)
            time.sleep(10); continue
        for u in r["result"]:
            off = u["update_id"] + 1
            if u.get("callback_query"):
                _pre(pre, u)
                continue
            m = u.get("message")
            if u.get("my_chat_member"):
                c = u["my_chat_member"]["chat"]
                print(time.strftime("%H:%M"), "bot được thêm/bỏ ở nhóm", c.get("title"), c["id"], flush=True)
            if not m:
                continue
            if m.get("migrate_to_chat_id"):
                print(time.strftime("%H:%M"), f"⚠️ nhóm {m['chat']['id']} đổi thành siêu nhóm {m['migrate_to_chat_id']}"
                      " → sửa chat id trong lark.env", flush=True)
                continue
            save_msg(m)
            chat, typ = str(m["chat"]["id"]), m["chat"]["type"]
            text = (m.get("text") or m.get("caption") or "")
            low = text.lower()
            if low.startswith("/chatid"):
                send(chat, f"chat id: {chat}", reply_to=m["message_id"]); continue
            sender = str((m.get("from") or {}).get("id", ""))
            if (m.get("from") or {}).get("is_bot"):
                continue
            if _pre(pre, u):
                continue
            if typ == "private":
                if sender not in allow_users:
                    send(chat, "Bot này chỉ làm việc trong nhóm của The Orbit.", reply_to=m["message_id"]); continue
            elif chat not in allow_chats:
                continue
            else:
                par = m.get("reply_to_message") or {}
                lenh = low.split()[0] if low.startswith("/") else ""
                goi = uname_ in low or ((par.get("from") or {}).get("id") == me["id"]) or \
                    (lenh and ("@" not in lenh or lenh.endswith(uname_)))
                if not goi:
                    continue
            on_job({"id": mk(chat, m["message_id"]), "chat": chat, "chat_type": "p2p" if typ == "private" else "group",
                    "parent": mk(chat, m["reply_to_message"]["message_id"]) if m.get("reply_to_message") else None,
                    "sender": sender, "sender_name": who(m.get("from")), "time": m.get("date", int(time.time())),
                    "album": bool(m.get("media_group_id")) or bool((m.get("reply_to_message") or {}).get("media_group_id"))})
        with open(stf, "w") as f:
            f.write(str(off))


def _pre(pre, u):
    if not pre:
        return False
    try:
        return bool(pre(u))
    except BaseException as e:  # lỗi module phụ không làm chết listener
        print(time.strftime("%H:%M"), "pre lỗi:", repr(e), flush=True)
        return False
