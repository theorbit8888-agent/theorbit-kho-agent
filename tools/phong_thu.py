#!/usr/bin/env python3
"""PHÒNG KHO GIẢ LẬP TRÊN TELEGRAM — chạy đúng code bot kho thật trên BOT + NHÓM TELEGRAM THỬ của bạn.

Khác sân thử (san_thu.py, gõ trong terminal): ở đây bạn bấm nút, gửi ảnh, trả lời tin… ngay trong Telegram
như nhân viên thật. Chỉ Telegram là thật (bot + nhóm THỬ do bạn tạo). Google Sheet, Nhanh.vn, sàn, Chrome:
GIẢ HẾT (dữ liệu ở logs/phong-thu/). Không bao giờ đụng bot, nhóm, Sheet hay Nhanh thật của shop.

CÀI 1 LẦN (xem HUONG-DAN-PHONG-THU.md):
  1. Telegram → @BotFather → /newbot → lấy token bot THỬ (đừng dùng @theorbit_kho_bot).
  2. Tạo 3 nhóm thử: "THỬ · Kho", "THỬ · Đổi trả CS-Kho", "THỬ · CS & Cửa hàng"; thêm bot thử vào cả 3.
  3. python3 tools/phong_thu.py --cai   → hỏi token, tự dò chat id 3 nhóm + Telegram ID của bạn, ghi
     ~/.config/orbit-kho-thu/thu.env (không nằm trong repo, không commit).
CHẠY:
  python3 tools/phong_thu.py            → bot thử nghe 3 nhóm; Ctrl+C để tắt
  python3 tools/phong_thu.py --reset    → xoá dữ liệu giả, làm lại từ đầu

TRONG TELEGRAM (chỉ người có ID trong OWNER_TELE_ID = "chủ shop" của phòng thử, gõ ở nhóm nào cũng được):
  /thu                 → danh sách lệnh giả lập
  /thu luc 17:30       → giả đồng hồ 17:30 và chạy mọi việc hẹn giờ của lúc đó (nhắc kho, két, ticket 9h…)
  /thu nhanh-gia       → nạp tồn + đơn Nhanh giả (lệnh nào của sân thử cũng gõ được sau /thu, vd /thu doisoat)
  /thu cskh-note       → giả bot CSKH báo 1 đơn có ghi chú vào nhóm kho (như nhóm Note khách thật)
  /thu xem 05          → in bảng Sheet giả
Còn lại gõ y như nhóm thật: /kho, /hangve, /hoan, /indon, /giao, /moca, /tk, bấm nút…
"""
import contextlib, io, json, os, re, sys, time
from datetime import datetime, timedelta

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(TOOLS, ".."))
sys.path.insert(0, TOOLS)
SAN = os.path.join(ROOT, "logs", "phong-thu")
ENVF = os.path.expanduser(os.environ.get("ORBIT_KHO_THU_ENV", "~/.config/orbit-kho-thu/thu.env"))
THAT = os.path.expanduser("~/.config/orbit-kho/lark.env")   # env bot THẬT (chỉ máy chủ shop có) — chỉ để chặn trùng
CAN = ("TELEGRAM_BOT_TOKEN", "CHAT_ID", "TICKET_CHAT_ID", "CH_CHAT_ID", "OWNER_TELE_ID")
TEN_BOT_THAT = {"theorbit_kho_bot", "theorbit_cskh_bot", "theorbit_rnd_bot", "theorbit_hcns_bot"}


def doc_env(p):
    d = {}
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            if "=" in l and not l.lstrip().startswith("#"):
                k, v = l.strip().split("=", 1); d[k.strip()] = v.strip()
    return d


def tg_raw(token, method, body=None):
    import urllib.request
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            return json.load(r)
    except Exception as e:
        return {"ok": False, "description": str(e)[:200]}


def chan_bot_that(token):
    """Không bao giờ chạy phòng thử bằng bot thật: 2 máy cùng nghe 1 bot sẽ giành tin, bot thật chạy sai."""
    if token and token == doc_env(THAT).get("TELEGRAM_BOT_TOKEN"):
        sys.exit("⛔ Token này là bot THẬT của shop. Tạo bot thử riêng bằng @BotFather.")
    r = tg_raw(token, "getMe")
    if not r.get("ok"):
        sys.exit("⛔ Token sai hoặc không có mạng: " + str(r.get("description")))
    u = r["result"]["username"].lower()
    if u in TEN_BOT_THAT:
        sys.exit(f"⛔ @{u} là bot THẬT của shop. Tạo bot thử riêng bằng @BotFather.")
    return u


def cai():
    print(__doc__.split("CHẠY:")[0])
    tok = input("Dán token bot THỬ: ").strip()
    u = chan_bot_that(tok)
    print(f"OK bot thử @{u}. Giờ vào TỪNG nhóm thử gõ: /chatid@{u}  (3 nhóm), rồi nhắn riêng bot 1 câu bất kỳ.")
    input("Gõ xong thì bấm Enter… ")
    nhom, toi = {}, ""
    for up in tg_raw(tok, "getUpdates", {"timeout": 1}).get("result", []):
        m = up.get("message") or {}
        c = m.get("chat") or {}
        if c.get("type") in ("group", "supergroup"):
            nhom[str(c["id"])] = c.get("title", "")
        elif c.get("type") == "private":
            toi = str((m.get("from") or {}).get("id", ""))
    if len(nhom) < 3 or not toi:
        print("Chưa thấy đủ 3 nhóm + tin nhắn riêng:", nhom, toi or "(chưa có ID của bạn)")
        print("→ Kiểm bot đã ở trong nhóm chưa; nhóm phải tắt Privacy (BotFather /setprivacy → Disable) hoặc tag bot.")
        return
    def chon(tu, mac):
        k = next((i for i, t in nhom.items() if any(x in t.lower() for x in tu)), None)
        return k or input(f"Chat id nhóm {mac} ({nhom}): ").strip()
    env = {"TELEGRAM_BOT_TOKEN": tok, "CHAT_ID": chon(("kho",), "Kho"),
           "TICKET_CHAT_ID": chon(("đổi", "doi", "ticket"), "Đổi trả"), "CH_CHAT_ID": chon(("cửa", "cua", "cs &"), "CS & Cửa hàng"),
           "OWNER_TELE_ID": toi, "TICKET_DUYET_IDS": toi}
    os.makedirs(os.path.dirname(ENVF), exist_ok=True)
    with open(ENVF, "w") as f:
        f.write("# Phòng kho giả lập — bot + nhóm THỬ. KHÔNG commit, KHÔNG dán token bot thật vào đây.\n")
        f.write("".join(f"{k}={v}\n" for k, v in env.items()))
    os.chmod(ENVF, 0o600)
    print("Đã ghi", ENVF, "→ chạy: python3 tools/phong_thu.py")


# ---------------- đồng hồ giả (để thử việc hẹn giờ) ----------------
LECH = [timedelta(0)]
_DT = datetime   # giữ lớp gốc: dat_gio thay `datetime` ở các module khác bằng GioGia


class GioGia(datetime):
    @classmethod
    def now(cls, tz=None):
        return _DT.now(tz) + LECH[0]

    @classmethod
    def today(cls):
        return cls.now()


def dat_gio(hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    n = _DT.now()
    LECH[0] = n.replace(hour=h, minute=m, second=0, microsecond=0) - n
    for mod in list(sys.modules.values()):
        if getattr(mod, "__file__", "") and os.path.dirname(os.path.abspath(mod.__file__)) == TOOLS \
                and mod.__name__ not in (__name__, "phong_thu") and getattr(mod, "datetime", None) in (_DT, GioGia):
            mod.datetime = GioGia


def dung(E, reset=False):
    """Dựng phòng thử: mọi thứ giả trừ Telegram. Trả (TG, pre, on_job, chats)."""
    os.environ["SAN_THU_DIR"] = SAN

    import orbit_tg as TG
    api_that, tai_that = TG.api, TG.download
    argv = sys.argv
    sys.argv = [argv[0]] + (["--reset"] if reset else [])
    try:
        import san_thu as ST   # dựng mọi thứ giả: Sheet, Nhanh, sàn, Chrome, file trạng thái → logs/phong-thu/
    except SystemExit:
        sys.exit("Đã xoá dữ liệu phòng thử.")
    sys.argv = argv
    import lark as Lk
    import ticket as TK
    import kho_flow, cua_hang, xuat_kho, hoan_san, tru_ton, chuyen_kho  # noqa: F401  (đăng ký lệnh như listener)
    try:
        import ket_noi_nhanh  # noqa: F401
        ket_noi_nhanh.__dict__.get("subprocess")
    except Exception:
        pass

    env = dict(E, KHO_URL="gia-lap", KHO_SECRET="gia-lap")   # Sheet bật nhưng TG.kho đã bị thay bằng Sheet giả
    TG.api, TG.download = api_that, tai_that                 # chỉ Telegram là thật (bot thử)
    TG.S["env"] = env
    Lk.load_env = lambda: dict(env)
    TK.init(dict(env), start_worker=True)
    TG.S["root"] = SAN
    os.makedirs(os.path.join(SAN, "logs"), exist_ok=True)
    assert TG.kho is ST.fake_kho, "Sheet chưa bị thay bằng Sheet giả — dừng cho an toàn"

    def tra(chat, txt, mid=None):
        for i in range(0, len(txt) or 1, 3800):
            TG.send(chat, txt[i:i + 3800], reply_to=mid)

    def thu(m):
        chat, mid = str(m["chat"]["id"]), m["message_id"]
        lenh = (m.get("text") or "").split(None, 1)
        rest = lenh[1].strip() if len(lenh) > 1 else ""
        if not rest:
            return tra(chat, "🧪 PHÒNG THỬ — lệnh giả lập (chỉ chủ phòng thử):\n"
                       "/thu luc 17:30 — giả giờ + chạy việc hẹn giờ lúc đó\n/thu gio-that — về giờ thật\n"
                       "/thu cskh-note — giả bot CSKH báo đơn có ghi chú\n/thu xem [bảng] — xem Sheet giả\n"
                       "/thu nhanh-gia | nhanh-don | nhanh-st MVĐ 59 | doisoat | gio10 | canhhuy | dubao | phieu | thieu …\n"
                       "(đủ danh sách: đầu file tools/san_thu.py)", mid)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                cmd, _, arg = rest.partition(" ")
                if cmd == "luc":
                    dat_gio(arg)
                    print(f"⏰ đồng hồ giả: {GioGia.now():%H:%M} — chạy việc hẹn giờ")
                    h, mi = GioGia.now().hour, GioGia.now().minute
                    kho_flow.hen(send=True)
                    cua_hang.hen(send=True)
                    if (h, mi) >= (9, 5) and h == 9:
                        TK.nhac(send=True)
                elif cmd == "gio-that":
                    LECH[0] = timedelta(0); print("đã về giờ thật")
                elif cmd == "cskh-note":
                    TG.send(E["CHAT_ID"], "📝 [NOTE KHÁCH – giả lập bot CSKH] Meta · đơn 890000001 · MVĐ SPXVN0000000001\n"
                            "Khách dặn: bọc túi giấy, giao giờ hành chính.\n👉 Kho: kiểm khi đóng gói.")
                    print("đã gửi tin giả của bot CSKH")
                elif cmd in ("kho:", "doitra:", "ch:", "rieng:", "la", "bam", "tra", "anh"):
                    print("lệnh này của sân thử terminal — ở đây gõ/bấm thẳng trong Telegram")
                else:
                    ST.dong(rest)
            except SystemExit as e:
                print("⚠️", e)
            except Exception as e:
                print("⚠️ lỗi:", repr(e)[:300])
        out = re.sub(r"^\s*👤 [^\n]*\n", "", buf.getvalue())
        out = re.sub(r"\n{3,}", "\n\n", out).strip() or "(xong, không có in gì)"
        tra(chat, "🧪 " + out, mid)

    goc = TK.on_update

    def pre(u):
        m = u.get("message") or {}
        t = (m.get("text") or "").strip()
        if re.match(r"/thu(@\w+)?(\s|$)", t, re.I):
            if str((m.get("from") or {}).get("id")) == str(E["OWNER_TELE_ID"]):
                thu(m)
            else:
                TG.send(str(m["chat"]["id"]), "Lệnh /thu chỉ dành cho chủ phòng thử.", reply_to=m["message_id"])
            return True
        return goc(u)

    def on_job(j):   # tin chữ tự do tag bot: máy thật gọi Claude (listener.py); phòng thử không gọi
        TG.reply(j["id"], "🧪 Phòng thử: tin chữ tự do ở bot thật do Claude đọc + ghi Sheet. Ở đây chỉ chạy lệnh /… và nút bấm.")

    chats = [E["CHAT_ID"], E["TICKET_CHAT_ID"], E["CH_CHAT_ID"]] + [v for k, v in E.items() if k.endswith("_CHAT_ID")]
    return TG, pre, on_job, chats


def main():
    if "--cai" in sys.argv:
        return cai()
    E = doc_env(ENVF)
    thieu = [k for k in CAN if not E.get(k)]
    if thieu:
        sys.exit(f"Thiếu {', '.join(thieu)} trong {ENVF} → chạy: python3 tools/phong_thu.py --cai")
    ten = chan_bot_that(E["TELEGRAM_BOT_TOKEN"])
    TG, pre, on_job, chats = dung(E, "--reset" in sys.argv)
    try:   # menu "/" từng nhóm thử như bot thật; /thu ở phòng thử = lệnh giả lập (thu tiền mặt không thử được ở đây)
        import menu_lenh as ML
        gl = [("thu", "PHÒNG THỬ: lệnh giả lập — gõ /thu xem danh sách")]
        ML.dat_menu(E, TG.api, them={"CHAT_ID": gl, "TICKET_CHAT_ID": gl, "CH_CHAT_ID": gl})
    except Exception as e:
        print("menu lệnh lỗi:", e, flush=True)
    print(f"🧪 PHÒNG KHO GIẢ LẬP — bot thử @{ten}. Dữ liệu giả: {SAN}. Ctrl+C để tắt.", flush=True)
    TG.send(E["CHAT_ID"], "🧪 Phòng kho giả lập đã bật. Gõ /kho xem lệnh kho, /thu xem lệnh giả lập (Sheet/Nhanh đều GIẢ).")
    try:
        TG.poll(on_job, chats, allow_users=[E["OWNER_TELE_ID"]], pre=pre, state_name="tg_offset_thu")
    except KeyboardInterrupt:
        print("\nĐã tắt phòng thử.")


if __name__ == "__main__":
    main()
