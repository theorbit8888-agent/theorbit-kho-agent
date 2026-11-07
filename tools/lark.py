#!/usr/bin/env python3
"""Lark cho agent Kho (bot app riêng "Kho Agent Orbit").
Secret: ~/.config/orbit-kho/lark.env (APP_ID, APP_SECRET; tuỳ chọn CHAT_ID, BASE_WIKI_TOKEN) - không commit.

Tin nhắn:
  python3 tools/lark.py chats                       # nhóm bot đang ở
  python3 tools/lark.py msg <message_id>            # đọc 1 tin (kèm tin gốc nếu là trả lời trong luồng)
  python3 tools/lark.py reply <message_id> "nội dung"   # trả lời đúng luồng tin được tag
  python3 tools/lark.py send "nội dung" [chat_id]   # gửi tin mới vào nhóm

Lark Base "THE ORBIT — Product Launch & Restock":
  python3 tools/lark.py tables                      # danh sách bảng
  python3 tools/lark.py fields <bảng>               # cột + kiểu
  python3 tools/lark.py list <bảng> [từ khoá]       # đọc dòng (lọc theo từ khoá nếu có)
  python3 tools/lark.py add <bảng> '{"Cột":"giá trị"}'
  python3 tools/lark.py update <bảng> <record_id> '{"Cột":"giá trị"}'
  python3 tools/lark.py setup-base [--apply]        # tạo bảng/cột còn thiếu theo SCHEMA (mặc định chỉ in kế hoạch)
  python3 tools/lark.py export                      # ghi xuat/TINH_TRANG_HANG.md cho agent CSKH đọc
  python3 tools/lark.py hoi <tên sản phẩm>          # tra nhanh tình trạng/restock 1 mẫu (chỉ đọc)
  python3 tools/lark.py nhac [--send]               # cảnh báo kho đến hạn (ngưỡng: knowledge/canh_bao.json)
<bảng> = số đầu tên ("02", "05") hoặc một phần tên ("HÀNG ĐẶT LẠI"). Ngày ghi dạng 2026-11-04.
"""
import json, os, re, sys, time, urllib.request, urllib.error, urllib.parse
from datetime import date, datetime, timedelta

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ENV = os.path.expanduser("~/.config/orbit-kho/lark.env")
API = "https://open.larksuite.com/open-apis"
WIKI_TOKEN = "YZtmwmmGYiL24ZkseBRl2Kn3gng"  # THE ORBIT — Product Launch & Restock

# Kiểu cột Lark Base: 1 chữ, 2 số, 3 chọn 1, 5 ngày, 7 checkbox, 15 link
KHO = ["Kho Tổng Q2", "Kho Cửa hàng PN"]
SAN = ["TikTok", "Shopee", "Web/Meta", "Khác"]
SCHEMA = {
    "02 · HÀNG ĐẶT LẠI": [  # bảng có sẵn: chỉ thêm cột thiếu, không sửa/xoá cột cũ
        ("SKU", 1),  # cột "Màu / Size" đã có sẵn
        ("Trạng thái đặt", 3, ["Đã đặt", "Đang SX", "Về 1 phần", "Đã về đủ", "Huỷ"]),
        ("Ngày về thực tế", 5), ("Kho nhận", 3, KHO), ("Nguồn tin", 1),
    ],
    "03 · NHẬP KHO": [
        ("Tên sản phẩm", 1), ("Ngày nhận", 5), ("Size/màu", 1),
        ("SL theo bill", 2), ("SL kiểm thực tế", 2), ("SL lỗi QC", 2), ("SL nhập kho", 2),
        ("Lệch bill", 3, ["Khớp", "Thiếu", "Thừa", "Chưa có bill"]),
        ("Kho nhận", 3, KHO), ("Người kiểm", 1), ("Đã nhập Nhanh.vn", 7),
        ("ID phiếu nhập Nhanh", 1), ("Ghi chú", 1), ("Nguồn tin", 1),
    ],
    "05 · TÌNH TRẠNG HÀNG": [
        ("Tên sản phẩm", 1), ("Size/màu", 1),
        ("Tình trạng", 3, ["Còn hàng", "Sắp hết", "Hết - chờ restock", "Hết - không restock", "Sắp mở bán"]),
        ("Hàng về dự kiến", 1), ("CSKH được nói", 1), ("Cập nhật lúc", 5), ("Ghi chú kho", 1),
    ],
    "06 · ĐƠN CÓ VẤN ĐỀ": [
        ("Mã đơn", 1), ("Sàn", 3, SAN),
        ("Loại", 3, ["Hoàn - khách trả", "Hoàn - giao thất bại", "Huỷ", "Giao sai/thiếu",
                     "Thất lạc/hư hỏng", "Khiếu nại/tranh chấp"]),
        ("Ngày phát sinh", 5), ("Hạn xử lý trên sàn", 5),
        ("Trạng thái", 3, ["Mới", "Chờ hàng về kho", "Đã nhận - đang kiểm", "Chờ duyệt",
                           "Đã duyệt", "Khiếu nại sàn", "Đóng"]),
        ("Kết quả kiểm hàng hoàn", 3, ["Nguyên vẹn - nhập lại", "Lỗi/bẩn - không bán",
                                       "Thiếu/sai hàng", "Chưa nhận được"]),
        ("Đã nhập lại Nhanh.vn", 7), ("Mã vận đơn", 1), ("Người xử lý", 1), ("Ghi chú", 1),
    ],
    "07 · ĐỐI SOÁT NGÀY": [
        ("Ngày - Sàn", 1), ("Ngày", 5), ("Sàn", 3, SAN),
        ("Đơn cần gửi", 2), ("Đã đóng", 2), ("Đã bàn giao ĐVVC", 2), ("Đơn trễ/quá hạn", 2),
        ("Hàng hoàn nhận", 2), ("Lệch/ghi chú", 1), ("Người làm", 1),
    ],
}


def load_env():
    d = {}
    with open(ENV) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1); d[k] = v
    return d


def call(method, path, tk=None, body=None):
    req = urllib.request.Request(API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json; charset=utf-8",
                 **({"Authorization": "Bearer " + tk} if tk else {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Lark lỗi {e.code}: {e.read().decode()[:400]}")
    if out.get("code"):
        sys.exit(f"Lark lỗi {out.get('code')}: {out.get('msg')}")
    return out


def token(env):
    r = call("POST", "/auth/v3/tenant_access_token/internal",
             body={"app_id": env["APP_ID"], "app_secret": env["APP_SECRET"]})
    return r["tenant_access_token"]


# ---------- tin nhắn ----------

def msg_text(m):
    """Nội dung chữ của 1 tin (text/post), thay @_user_N bằng tên."""
    try:
        c = json.loads(m["body"]["content"])
    except Exception:
        return m.get("body", {}).get("content", "")
    if m.get("msg_type") == "post":
        c = c.get("content") or next(iter(c.values()), {}).get("content", [])
        t = "\n".join("".join(x.get("text", "") or x.get("user_name", "") for x in line) for line in c)
    elif m.get("msg_type") == "text":
        t = c.get("text", "")
    else:
        t = f"[{m.get('msg_type')}]"
    for mt in m.get("mentions", []) or []:
        t = t.replace(mt.get("key", ""), "@" + mt.get("name", ""))
    return t


def get_msg(tk, mid):
    items = call("GET", f"/im/v1/messages/{mid}", tk).get("data", {}).get("items", [])
    return items[0] if items else None


def send(tk, chat, text):
    r = call("POST", "/im/v1/messages?receive_id_type=chat_id", tk,
             {"receive_id": chat, "msg_type": "text", "content": json.dumps({"text": text})})
    return r["data"]["message_id"]


def reply(tk, mid, text):
    r = call("POST", f"/im/v1/messages/{mid}/reply", tk,
             {"msg_type": "text", "content": json.dumps({"text": text})})
    return r["data"]["message_id"]


# ---------- Base ----------

def app_token(env, tk):
    w = env.get("BASE_WIKI_TOKEN", WIKI_TOKEN)
    node = call("GET", f"/wiki/v2/spaces/get_node?token={w}", tk)["data"]["node"]
    return node["obj_token"]


def tables(tk, app):
    return call("GET", f"/bitable/v1/apps/{app}/tables?page_size=100", tk)["data"].get("items", [])


def find_table(tk, app, key):
    ts = tables(tk, app)
    hits = [t for t in ts if t["name"] == key or t["name"].startswith(key + " ") or t["name"].startswith(key + "·")]
    hits.sort(key=lambda t: t["name"] not in SCHEMA)  # trùng số ("02") thì ưu tiên bảng của agent kho
    if hits:
        return hits[0]
    for t in ts:
        if key.lower() in t["name"].lower():
            return t
    sys.exit(f"Không thấy bảng '{key}'. Có: " + ", ".join(t["name"] for t in ts))


def fields(tk, app, tid):
    return call("GET", f"/bitable/v1/apps/{app}/tables/{tid}/fields?page_size=100", tk)["data"].get("items", [])


def records(tk, app, tid):
    out, pt = [], ""
    while True:
        r = call("GET", f"/bitable/v1/apps/{app}/tables/{tid}/records?page_size=500"
                        + (f"&page_token={pt}" if pt else ""), tk)["data"]
        out += r.get("items") or []
        if not r.get("has_more"):
            return out
        pt = r["page_token"]


def plain(v):
    """Giá trị ô Base -> chữ đọc được."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "✓" if v else ""
    if isinstance(v, (int, float)):
        if v > 1e12:  # ngày (ms)
            return datetime.fromtimestamp(v / 1000).strftime("%d/%m/%Y")
        return str(int(v)) if float(v).is_integer() else str(v)
    if isinstance(v, list):
        return ", ".join(plain(x) for x in v)
    if isinstance(v, dict):
        return v.get("text") or v.get("name") or v.get("link") or json.dumps(v, ensure_ascii=False)
    return str(v)


def row(rec):
    return {k: plain(v) for k, v in rec["fields"].items()} | {"_id": rec["record_id"]}


def coerce(tk, app, tid, data):
    """Đổi giá trị nhập (chữ) sang đúng kiểu cột."""
    fs = fields(tk, app, tid)
    types = {f["field_name"]: f["type"] for f in fs}
    opts = {f["field_name"]: [o["name"] for o in (f.get("property") or {}).get("options", [])] for f in fs}
    out = {}
    for k, v in data.items():
        if k not in types:
            sys.exit(f"Bảng không có cột '{k}'. Cột: {', '.join(types)}")
        t = types[k]
        if t == 5 and isinstance(v, str):
            v = int(datetime.strptime(v[:10], "%Y-%m-%d").timestamp() * 1000)
        elif t == 2 and isinstance(v, str):
            v = float(v)
        elif t == 7 and isinstance(v, str):
            v = v.lower() in ("1", "true", "x", "có", "co", "yes")
        elif t == 1 and not isinstance(v, str):
            v = str(v)
        elif t == 3 and opts[k] and v not in opts[k]:  # chọn 1: chỉ nhận lựa chọn có sẵn, khớp gần đúng
            near = [o for o in opts[k] if o.lower().startswith(str(v).lower()) or str(v).lower() in o.lower()]
            if len(near) != 1:
                sys.exit(f"Cột '{k}' chỉ nhận: {', '.join(opts[k])}")
            v = near[0]
        elif t == 11 and isinstance(v, str):  # cột người: cần open_id (ou_...), tên thì ghi vào cột chữ khác
            if not v.startswith("ou_"):
                sys.exit(f"Cột '{k}' là kiểu người Lark, cần open_id ou_... (open_id người gửi có trong tin)")
            v = [{"id": v}]
        elif t in (19, 20, 1001, 1002, 1005):
            sys.exit(f"Cột '{k}' tự tính, không ghi được")
        out[k] = v
    return out


def field_body(spec):
    name, typ = spec[0], spec[1]
    b = {"field_name": name, "type": typ}
    if typ == 3:
        b["property"] = {"options": [{"name": o} for o in spec[2]]}
    return b


def setup_base(tk, app, apply):
    have = {t["name"]: t["table_id"] for t in tables(tk, app)}
    plan = []
    for name, specs in SCHEMA.items():
        if name in have:
            exist = {f["field_name"] for f in fields(tk, app, have[name])}
            for s in specs:
                if s[0] not in exist:
                    plan.append(("cột", name, s))
        else:
            plan.append(("bảng", name, specs))
    if not plan:
        print("Base đã đủ bảng/cột theo SCHEMA."); return
    for kind, name, s in plan:
        print(f"+ {kind} {name}: " + (s[0] if kind == "cột" else ", ".join(x[0] for x in s)))
        if not apply:
            continue
        if kind == "bảng":
            call("POST", f"/bitable/v1/apps/{app}/tables", tk,
                 {"table": {"name": name, "default_view_name": "Lưới",
                            "fields": [field_body(x) for x in s]}})
        else:
            call("POST", f"/bitable/v1/apps/{app}/tables/{have[name]}/fields", tk, field_body(s))
    print("Đã áp dụng." if apply else "(chưa áp dụng — chạy lại với --apply)")


def rows_of(tk, app, key):
    t = find_table(tk, app, key)
    return [row(r) for r in records(tk, app, t["table_id"])]


def name_of(r):
    return r.get("Tên sản phẩm") or r.get("Mục") or r.get("Mã đơn") or ""


def export(tk, app):
    """Bản đọc cho agent CSKH: tình trạng từng mẫu + hàng đặt lại chưa về."""
    st = [r for r in rows_of(tk, app, "05") if name_of(r)]
    re_ = [r for r in rows_of(tk, app, "02") if name_of(r)]
    now = datetime.now().strftime("%H:%M %d/%m/%Y")
    L = [f"# Tình trạng hàng & restock — The Orbit",
         f"Xuất từ Lark Base lúc {now} (agent kho). CSKH: chỉ nói đúng cột \"CSKH được nói\"; "
         "ngày về luôn là khoảng dự kiến, không hứa ngày cụ thể. Tồn chính xác vẫn tra Nhanh.vn/sàn.", "",
         "## Tình trạng theo mẫu", "| Mẫu | Size/màu | Tình trạng | Về dự kiến | CSKH được nói | Cập nhật |",
         "|---|---|---|---|---|---|"]
    for r in sorted(st, key=name_of):
        L.append("| " + " | ".join(r.get(k, "").replace("|", "/").replace("\n", " ") for k in
                 ("Tên sản phẩm", "Size/màu", "Tình trạng", "Hàng về dự kiến", "CSKH được nói", "Cập nhật lúc")) + " |")
    if not st:
        L.append("| (chưa có dữ liệu) | | | | | |")
    L += ["", "## Hàng đặt lại chưa về đủ", "| Mẫu | Size/màu | SL đặt | SL đã nhận | Hẹn về | Trạng thái |",
          "|---|---|---|---|---|---|"]
    open_ = [r for r in re_ if not r.get("Đã về đủ") and r.get("Trạng thái đặt") not in ("Đã về đủ", "Huỷ")]
    for r in open_:
        L.append("| " + " | ".join(r.get(k, "").replace("|", "/") for k in
                 ("Tên sản phẩm", "Màu / Size", "SL đặt", "SL đã nhận", "Hẹn hàng về", "Trạng thái đặt")) + " |")
    if not open_:
        L.append("| (không có) | | | | | |")
    os.makedirs(os.path.join(ROOT, "xuat"), exist_ok=True)
    p = os.path.join(ROOT, "xuat", "TINH_TRANG_HANG.md")
    open(p, "w").write("\n".join(L) + "\n")
    print("đã ghi", os.path.normpath(p))


def hoi(tk, app, kw):
    kw = kw.lower()
    for key in ("05", "02", "01"):
        t = find_table(tk, app, key)
        hits = [row(r) for r in records(tk, app, t["table_id"]) if kw in name_of(row(r)).lower()]
        for h in hits:
            print(f"[{t['name']}] " + " | ".join(f"{k}: {v}" for k, v in h.items() if v and k != "_id"))
    print("(hết)")


# ---------- nhắc việc kho (chạy 9h sáng, không gọi Claude) ----------

def to_date(v):
    """'04/11/2026' (ô ngày) hoặc chữ người gõ '4/11', '2026-11-04' -> date."""
    v = (v or "").strip()
    for f in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(v[:10], f).date()
        except ValueError:
            pass
    m = re.match(r"(\d{1,2})[/-](\d{1,2})$", v)
    if m:
        d = date(date.today().year, int(m[2]), int(m[1]))
        return d.replace(year=d.year - 1) if d > date.today() else d
    return None


def nhac(tk, app):
    cb = json.load(open(os.path.join(ROOT, "knowledge", "canh_bao.json")))
    on = lambda k: cb.get(k, {}).get("bat")
    today = date.today()
    ngay = lambda r, k: to_date(r.get(k))
    out = {}
    add = lambda nhom, s: out.setdefault(nhom, []).append("• " + s)

    if on("dat_lai_chua_ve") or on("qua_hen_hang_ve"):
        for r in rows_of(tk, app, "02"):
            if not name_of(r) or r.get("Đã về đủ") or r.get("Trạng thái đặt") in ("Đã về đủ", "Huỷ"):
                continue
            dat, hen = ngay(r, "Ngày đặt"), ngay(r, "Hẹn hàng về")
            ly_do = []
            if on("dat_lai_chua_ve") and dat and (today - dat).days >= cb["dat_lai_chua_ve"]["so_ngay"]:
                ly_do.append(f"đặt {(today - dat).days} ngày chưa về đủ")
            if on("qua_hen_hang_ve") and hen and hen < today:
                ly_do.append(f"quá hẹn về {(today - hen).days} ngày")
            if ly_do:
                ai = r.get("Người phụ trách") or "người phụ trách"
                add("Hàng đặt lại chưa về", f"{name_of(r)} {r.get('Màu / Size', '')}: {', '.join(ly_do)} "
                    f"(đã nhận {r.get('SL đã nhận') or 0}/{r.get('SL đặt') or '?'}, hẹn {r.get('Hẹn hàng về') or 'chưa có'}) "
                    f"→ {ai} hỏi {r.get('Xưởng / NCC') or 'xưởng'}, báo kho ngày về mới")

    if on("demo_chua_ve") or on("sx_qua_hen"):
        for r in rows_of(tk, app, "01"):
            b = r.get("Đang ở bước")
            if not name_of(r):
                continue
            if on("demo_chua_ve") and b == "Đang làm demo":
                gui, han = ngay(r, "Ngày gửi demo"), ngay(r, "Hạn demo")
                if gui and (today - gui).days >= cb["demo_chua_ve"]["so_ngay"]:
                    add("Demo / sản xuất chưa về", f"{name_of(r)}: demo gửi xưởng {(today - gui).days} ngày chưa về → hỏi {r.get('Xưởng / NCC') or 'xưởng'}")
                elif han and han < today:
                    add("Demo / sản xuất chưa về", f"{name_of(r)}: quá hạn demo {(today - han).days} ngày → hỏi {r.get('Xưởng / NCC') or 'xưởng'}")
                elif not gui and not han:
                    add("Thiếu dữ liệu", f"{name_of(r)}: đang làm demo nhưng chưa ghi 'Ngày gửi demo' → không nhắc được")
            if on("sx_qua_hen") and b in ("Đang sản xuất", "Chờ hàng về") and not r.get("Ngày nhận kho thực tế"):
                hen = ngay(r, "Hẹn hàng về")
                if hen and hen < today:
                    add("Demo / sản xuất chưa về", f"{name_of(r)}: sản xuất quá hẹn về {(today - hen).days} ngày (SL {r.get('SL đặt SX') or '?'}) → hỏi xưởng, báo CSKH lùi ngày")

    if on("don_van_de_sap_het_han") or on("don_van_de_ton_dong") or on("chua_nhap_nhanh"):
        for r in rows_of(tk, app, "06"):
            if not name_of(r):
                continue
            mo = r.get("Trạng thái") != "Đóng"
            han, ps = ngay(r, "Hạn xử lý trên sàn"), ngay(r, "Ngày phát sinh")
            ten = f"{r.get('Sàn', '')} {name_of(r)} ({r.get('Loại', '')})"
            if mo and on("don_van_de_sap_het_han") and han and (han - today).days * 24 <= cb["don_van_de_sap_het_han"]["so_gio"]:
                add("⏰ Đơn sắp hết hạn trên sàn", f"{ten}: hạn {r.get('Hạn xử lý trên sàn')} → {r.get('Người xử lý') or 'người duyệt'} xử lý trên sàn")
            elif mo and on("don_van_de_ton_dong") and ps and (today - ps).days >= cb["don_van_de_ton_dong"]["so_ngay"]:
                add("Đơn vấn đề tồn đọng", f"{ten}: {(today - ps).days} ngày vẫn '{r.get('Trạng thái') or 'Mới'}'")
            if on("chua_nhap_nhanh") and r.get("Kết quả kiểm hàng hoàn") == "Nguyên vẹn - nhập lại" and not r.get("Đã nhập lại Nhanh.vn"):
                add("Chưa nhập Nhanh.vn", f"hàng hoàn {ten} nguyên vẹn nhưng chưa nhập lại tồn")
    if on("chua_nhap_nhanh"):
        for r in rows_of(tk, app, "03"):
            nh = ngay(r, "Ngày nhận")
            if name_of(r) and not r.get("Đã nhập Nhanh.vn") and nh and (today - nh).days >= cb["chua_nhap_nhanh"]["so_ngay"]:
                add("Chưa nhập Nhanh.vn", f"{name_of(r)} {r.get('Size/màu', '')}: nhận {r.get('Ngày nhận')}, SL nhập {r.get('SL nhập kho') or '?'} chưa tick nhập Nhanh.vn")

    if on("thieu_doi_soat"):
        hom_qua = today - timedelta(days=1)
        co = {r.get("Sàn") for r in rows_of(tk, app, "07") if ngay(r, "Ngày") == hom_qua}
        thieu = [s for s in cb["thieu_doi_soat"]["san"] if s not in co]
        if thieu:
            add("Đối soát", f"chưa có đối soát {hom_qua:%d/%m} cho {', '.join(thieu)} → người kho nhắn số cần gửi/đã đóng/đã bàn giao")
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, a = sys.argv[1], sys.argv[2:]
    env = load_env(); tk = token(env)
    if cmd == "chats":
        for c in call("GET", "/im/v1/chats?page_size=100", tk)["data"].get("items", []):
            print(c["chat_id"], c["name"])
    elif cmd == "msg":
        m = get_msg(tk, a[0])
        print(msg_text(m))
        if m.get("parent_id"):
            print("--- trả lời cho tin:\n" + msg_text(get_msg(tk, m["parent_id"])))
    elif cmd == "reply":
        print("đã trả lời", reply(tk, a[0], a[1]))
        os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)  # để lượt sau nhớ bot đã nói gì
        with open(os.path.join(ROOT, "logs", "replies.jsonl"), "a") as f:
            f.write(json.dumps({"to": a[0], "time": int(time.time()), "text": a[1]}, ensure_ascii=False) + "\n")
    elif cmd == "send":
        chat = a[1] if len(a) > 1 else env.get("CHAT_ID") or sys.exit("Thiếu chat_id (hoặc CHAT_ID trong env)")
        print("đã gửi", send(tk, chat, a[0]))
    else:
        app = app_token(env, tk)
        if cmd == "tables":
            for t in tables(tk, app):
                print(t["table_id"], t["name"])
        elif cmd == "fields":
            for f in fields(tk, app, find_table(tk, app, a[0])["table_id"]):
                print(f["type"], f["field_name"])
        elif cmd == "list":
            rs = rows_of(tk, app, a[0])
            if len(a) > 1:
                rs = [r for r in rs if a[1].lower() in json.dumps(r, ensure_ascii=False).lower()]
            print(json.dumps([{k: v for k, v in r.items() if v} for r in rs], ensure_ascii=False, indent=1))
        elif cmd == "add":
            t = find_table(tk, app, a[0])
            r = call("POST", f"/bitable/v1/apps/{app}/tables/{t['table_id']}/records", tk,
                     {"fields": coerce(tk, app, t["table_id"], json.loads(a[1]))})
            print("đã thêm", r["data"]["record"]["record_id"], "vào", t["name"])
        elif cmd == "update":
            t = find_table(tk, app, a[0])
            call("PUT", f"/bitable/v1/apps/{app}/tables/{t['table_id']}/records/{a[1]}", tk,
                 {"fields": coerce(tk, app, t["table_id"], json.loads(a[2]))})
            print("đã sửa", a[1], "trong", t["name"])
        elif cmd == "setup-base":
            setup_base(tk, app, "--apply" in a)
        elif cmd == "export":
            export(tk, app)
        elif cmd == "hoi":
            hoi(tk, app, " ".join(a))
        elif cmd == "nhac":
            out = nhac(tk, app)
            text = "\n\n".join(f"{k}:\n" + "\n".join(v) for k, v in out.items())
            print(text or "(không có cảnh báo)")
            if out and "--send" in a:
                send(tk, env.get("CHAT_ID") or sys.exit("Thiếu CHAT_ID trong env"),
                     f"⏰ Kho cần xử lý hôm nay ({date.today():%d/%m}):\n\n" + text)
        else:
            sys.exit(__doc__)


if __name__ == "__main__":
    main()
