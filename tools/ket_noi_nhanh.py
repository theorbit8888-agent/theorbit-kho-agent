#!/usr/bin/env python3
"""/ketnoinhanh — chủ shop kết nối bot kho với Nhanh Open API NGAY TRÊN ĐIỆN THOẠI (nhắn riêng bot kho).

1. Bot hỏi Secret key của app "Orbit Bot Kho" (open.nhanh.vn/app/detail?id=APP_ID) → chủ shop dán → bot lưu, XOÁ tin.
2. Bot gửi nút cấp quyền Nhanh → chủ shop đăng nhập Giám đốc, cấp quyền → trình duyệt nhảy sang google.com?accessCode=…
3. Chủ shop copy nguyên địa chỉ đó gửi bot → bot đổi lấy accessToken (sống 1 năm), lưu, xoá tin, đọc Nhanh lần đầu
   và bật lịch đọc 30 phút/lần.
Mã chỉ nằm ở ~/.config/orbit-kho/nhanh_api.env (quyền 600); không in ra log, không gửi lại vào chat.
"""
import json, os, re, secrets, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orbit_tg as TG  # noqa: E402
import ticket as TK  # noqa: E402
import nhanh_api as NA  # noqa: E402

APP_ID = "78827"          # app "Orbit Bot Kho" tạo trên open.nhanh.vn ngày 12/11/2026
RETURN = "https://www.google.com/"
HAN = 15 * 60
_F = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "ket_noi_nhanh.json")
try:   # giữ bước đang dở qua lần khởi động lại bot (chỉ lưu bước + verifyCode, KHÔNG lưu mã)
    KN = {int(k): v for k, v in json.load(open(_F)).items()}
except Exception:
    KN = {}                   # uid -> {"buoc": "secret"|"url", "vc", "han"}


def _luu_kn():
    try:
        with open(_F, "w") as fh:
            json.dump(KN, fh)
        os.chmod(_F, 0o600)
    except Exception:
        pass


def la_chu(uid):
    return str(uid) == str(TK.E.get("OWNER_TELE_ID", ""))


def luu(cap):
    f = NA.ENV
    os.makedirs(os.path.dirname(f), exist_ok=True)
    cu = [l for l in (open(f).readlines() if os.path.exists(f) else []) if l.split("=", 1)[0] not in cap]
    with open(f + ".tmp", "w") as fh:
        fh.writelines(cu + [f"{k}={v}\n" for k, v in cap.items()])
    os.chmod(f + ".tmp", 0o600)
    os.replace(f + ".tmp", f)


def xoa(m):
    TG.api("deleteMessage", {"chat_id": m["chat"]["id"], "message_id": m["message_id"]})


def cmd(m, arg):
    uid, chat = m["from"]["id"], m["chat"]["id"]
    if not la_chu(uid):
        return TK.tsend(chat, "Chỉ chủ shop dùng lệnh này.")
    KN[uid] = {"buoc": "secret", "han": time.time() + HAN}
    _luu_kn()
    TK.tsend(chat, "🔌 <b>Kết nối bot kho với Nhanh (API chính thức)</b>\n\n"
                   f"<b>Bước 1/2:</b> mở trang app <b>Orbit Bot Kho</b> (App ID {APP_ID}), copy <b>Secret key</b> "
                   "rồi dán vào đây. Bot lưu xong sẽ <b>xoá tin của bạn</b> ngay.\n/huy để dừng.",
             [[{"text": "🔑 Mở trang app trên Nhanh", "url": f"https://open.nhanh.vn/app/detail?id={APP_ID}"}]])


def tra_loi(m):
    uid, chat = m["from"]["id"], m["chat"]["id"]
    w = KN.get(uid)
    text = (m.get("text") or "").strip()
    if not w:
        if la_chu(uid) and re.fullmatch(r"[A-Za-z0-9_\-]{40,}", text):   # dán mã mà chưa gõ lệnh: xoá, không chuyển đi đâu
            xoa(m)
            TK.tsend(chat, "🔒 Tin vừa rồi giống mã bí mật nên bot đã xoá, không lưu. Muốn kết nối Nhanh thì gõ "
                           "/ketnoinhanh trước rồi mới dán Secret key.")
            return True
        return False
    if time.time() > w["han"]:
        KN.pop(uid, None); _luu_kn()
        TK.tsend(chat, "⌛ Quá 15 phút. Gõ lại /ketnoinhanh.")
        return True
    if w["buoc"] == "secret":
        sec = re.sub(r"\s+", "", text)
        xoa(m)
        if len(sec) < 16 or not re.fullmatch(r"[A-Za-z0-9_\-]+", sec):
            TK.tsend(chat, "Không giống Secret key (phải là một chuỗi dài chữ + số). Dán lại giúp.")
            return True
        luu({"NHANH_APP_ID": APP_ID, "NHANH_SECRET": sec})
        vc = secrets.token_urlsafe(24).replace("-", "a").replace("_", "b")[:32]
        w.update(buoc="url", vc=vc, han=time.time() + HAN)
        _luu_kn()
        link = f"https://nhanh.vn/oauth?appId={APP_ID}&service=pos&verifyCode={vc}&returnLink={RETURN}"
        TK.tsend(chat, "✅ Đã lưu Secret key (đã xoá tin).\n\n"
                       "<b>Bước 2/2:</b> bấm nút dưới → đăng nhập tài khoản <b>Giám đốc</b> → chọn <b>The ORBIT</b> → "
                       "tích đủ quyền <b>Sản phẩm, Đơn hàng, Kho</b> → Đồng ý.\n"
                       "Trình duyệt sẽ nhảy sang <b>google.com</b>: copy <b>nguyên địa chỉ</b> trên thanh địa chỉ rồi gửi vào đây "
                       "(trong 10 phút).",
                 [[{"text": "✅ Cấp quyền cho bot trên Nhanh", "url": link}]])
        return True
    # bước url: đổi accessCode lấy accessToken
    ac = (re.search(r"[?&]accessCode=([^&#\s]+)", text) or [None, None])[1]
    if not ac:
        TK.tsend(chat, "Chưa thấy <code>accessCode=</code> trong tin. Gửi nguyên địa chỉ google.com sau khi cấp quyền.")
        return True
    xoa(m)
    e = NA.env()
    req = urllib.request.Request(f"https://pos.open.nhanh.vn/v3.0/app/getaccesstoken?appId={APP_ID}", method="POST",
                                 data=json.dumps({"accessCode": ac, "verifyCode": w["vc"]}).encode(),
                                 headers={"Authorization": e.get("NHANH_SECRET", ""), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.load(r)
    except urllib.error.HTTPError as x:
        try:
            j = json.loads(x.read().decode() or "{}")
        except Exception:
            j = {"messages": f"HTTP {x.code}"}
    except Exception as x:
        j = {"messages": repr(x)[:150]}
    if j.get("code") != 1:
        KN.pop(uid, None); _luu_kn()
        loi = j.get("messages") or j.get("errorCode") or "không rõ"
        TK.tsend(chat, f"❌ Nhanh từ chối: {TK.esc(str(loi)[:300])}\n"
                       "Nếu báo chưa cho phép Open API: vào Nhanh → Cài đặt → bật <b>Cho phép kết nối Open API</b> "
                       "(tài khoản Giám đốc), rồi gõ lại /ketnoinhanh. Sai Secret key cũng báo lỗi này.")
        return True
    d = j["data"]
    luu({"NHANH_ACCESS_TOKEN": d["accessToken"], "NHANH_BUSINESS_ID": d["businessId"], "NHANH_HET_HAN": d.get("expiredAt")})
    KN.pop(uid, None); _luu_kn()
    het = ""
    try:
        het = time.strftime("%d/%m/%Y", time.localtime(int(d.get("expiredAt"))))
    except (TypeError, ValueError):
        pass
    TK.tsend(chat, f"✅ <b>Đã kết nối Nhanh</b> (doanh nghiệp {TK.esc(str(d['businessId']))}"
                   + (f", dùng tới {het}" if het else "") + ").\nBot đang đọc tồn + đơn lần đầu (1–2 phút), "
                   "sau đó tự đọc 30 phút/lần.")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.Popen(f'"{root}/.venv/bin/python" "{root}/tools/nhanh.py" sync >> "{root}/logs/nhanh-sync.out" 2>&1; '
                     'P="$HOME/Library/LaunchAgents/vn.theorbit.kho-agent.nhanh.plist"; '
                     '[ -f "$P" ] && { launchctl unload "$P" 2>/dev/null; launchctl load "$P"; }',
                     shell=True, cwd=root, start_new_session=True)
    return True


def huy(uid):
    return KN.pop(uid, None) is not None


TK.EXT_PRIV["/ketnoinhanh"] = cmd
TK.EXT_TEXT.insert(0, tra_loi)
