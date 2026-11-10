#!/usr/bin/env python3
"""Nghe tin Lark có TAG bot "Kho Agent Orbit" rồi mới gọi Claude xử lý (không đọc nền, không tốn token khi rảnh).

Dùng kết nối dài (WebSocket) của Lark: không cần mở port/URL public. Bot chỉ nhận tin khi bị @ trong nhóm
(quyền im:message.group_at_msg:readonly) hoặc khi được nhắn riêng.
  .venv/bin/python tools/listener.py          # chạy (launchd giữ chạy nền: xem SETUP_LARK.md)
  .venv/bin/python tools/listener.py --dry    # chỉ in tin nhận được, không gọi Claude
Env thêm trong ~/.config/orbit-kho/lark.env: CLAUDE_CODE_OAUTH_TOKEN (từ `claude setup-token`),
tuỳ chọn CLAUDE_BIN, CLAUDE_MODEL (mặc định sonnet).
"""
import glob, json, os, queue, subprocess, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lark as L
import orbit_tg as TG
import ticket as TK  # ticket CS (đổi/trả/hoàn) — nút bấm + phiếu nhắn riêng, không gọi Claude
import kho_flow  # noqa: F401
import cua_hang  # noqa: F401  CS + cửa hàng: /moca /chi /ketca /bill /goi /note /hoatoc /chotca  việc thủ kho: /hangve /chotdi /chothoan /kiemkho /kho (đăng ký vào ticket)

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LOG = os.path.join(ROOT, "logs")
DRY = "--dry" in sys.argv
env = L.load_env()
OWNER = env.get("OWNER_TELE_ID", "")  # Telegram ID chủ shop (thay open_id Lark khi kiểm "chủ shop duyệt/chốt")
jobs = queue.Queue()
seen = set()


def log(name, obj):
    os.makedirs(LOG, exist_ok=True)
    with open(os.path.join(LOG, name), "a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def claude_bin():
    if env.get("CLAUDE_BIN"):
        return env["CLAUDE_BIN"]
    for p in ("~/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if os.path.exists(os.path.expanduser(p)):
            return os.path.expanduser(p)
    found = sorted(glob.glob(os.path.expanduser(
        "~/Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude")), key=os.path.getmtime)
    return found[-1] if found else "claude"


def on_message(data):  # Lark (dự phòng khi không có TELEGRAM_BOT_TOKEN)
    m = data.event.message
    if m.message_id in seen:  # Lark có thể gửi lại cùng 1 sự kiện
        return
    seen.add(m.message_id)
    jobs.put({"id": m.message_id, "chat": m.chat_id, "chat_type": m.chat_type,
              "parent": m.parent_id, "sender": data.event.sender.sender_id.open_id,
              "time": int(m.create_time) // 1000})


def on_tele(j):
    if j["id"] in seen:
        return
    seen.add(j["id"])
    j["recv"] = time.time()
    jobs.put(j)


def recent(j, hours=3, n=6):
    """Các tin tag bot gần đây trong cùng nhóm + câu bot đã trả lời: tin rời nhau vẫn là một việc."""
    def rows(name):
        try:
            return [json.loads(x) for x in open(os.path.join(LOG, name))]
        except FileNotFoundError:
            return []
    said = {r["to"]: r["text"] for r in rows("replies.jsonl")}
    prev = [r for r in rows("inbox.jsonl") if r.get("chat") == j["chat"] and r["id"] != j["id"]
            and j["time"] - hours * 3600 <= r.get("time", 0) <= j["time"]][-n:]
    out = []
    for r in prev:
        out.append(f"[{time.strftime('%H:%M %d/%m', time.localtime(r['time']))}] người kho: {r.get('text', '')}")
        if r["id"] in said:
            out.append(f"   bot đã trả lời: {said[r['id']]}")
    return "\n".join(out)


def handle(j):
    if j.get("album"):  # album ảnh tới thành nhiều tin liền nhau: chờ đủ ảnh rồi mới đọc
        time.sleep(max(0, j["recv"] + 5 - time.time()))
    tk = L.token(env)
    m = L.get_msg(tk, j["id"])
    text = L.msg_text(m)
    parent = L.msg_text(L.get_msg(tk, j["parent"])) if j.get("parent") else ""
    j |= {"text": text, "parent_text": parent}
    log("inbox.jsonl", j)
    print(time.strftime("%H:%M"), text[:120], flush=True)
    if DRY:
        return
    prompt = (
        "Có tin " + ("Telegram" if TG.tg_on() else "Lark") + " mới TAG bot kho. Xử lý theo CLAUDE.md.\n"
        f"message_id: {j['id']}\nchat_id: {j['chat']} ({j['chat_type']})\n"
        + (f"người gửi: {j.get('sender_name', '')} (Telegram ID {j['sender']})"
           + (" — CHỦ SHOP" if OWNER and j["sender"] == OWNER else "") + "\n"
           if TG.tg_on() else f"người gửi (open_id): {j['sender']}\n")
        + f"lúc: {time.strftime('%H:%M %d/%m/%Y', time.localtime(j['time']))}\n"
        f"nội dung:\n{text}\n"
        + (f"\nđang trả lời trong luồng của tin gốc:\n{parent}\n" if parent else "")
        + (f"\nCác tin gần đây trong nhóm (cũ → mới). Tin mới thường là bổ sung cho việc đang dở ở đây, "
           f"ghép lại rồi xử lý, đừng hỏi lại cái đã có:\n{ctx}\n" if (ctx := recent(j)) else "")
        + f"\nXong thì BẮT BUỘC trả lời bằng: python3 tools/lark.py reply {j['id']} \"...\""
    )
    cmd = [claude_bin(), "-p", prompt, "--model", env.get("CLAUDE_MODEL", "sonnet"),
           "--permission-mode", "acceptEdits", "--max-turns", "30",
           "--allowedTools", "Bash(python3 tools/lark.py:*)", "Read", "Edit", "Write", "Glob", "Grep"]
    try:
        run_env = dict(os.environ)
        if env.get("CLAUDE_CODE_OAUTH_TOKEN"):
            run_env["CLAUDE_CODE_OAUTH_TOKEN"] = env["CLAUDE_CODE_OAUTH_TOKEN"]
        r = subprocess.run(cmd, cwd=ROOT, env=run_env, capture_output=True, text=True, timeout=600)
        log("runs.jsonl", {"id": j["id"], "rc": r.returncode, "out": r.stdout[-2000:], "err": r.stderr[-1000:]})
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-300:] or r.stdout[-300:])
    except Exception as e:
        log("loi.jsonl", {"id": j["id"], "err": str(e)})
        L.reply(tk, j["id"], "⚠️ Bot kho chưa xử lý được tin này (đã lưu lại). Nhờ bạn kho cập nhật tay vào Base giúp nhé.")


def worker():
    while True:
        j = jobs.get()
        try:
            handle(j)
        except Exception as e:
            log("loi.jsonl", {"id": j.get("id"), "err": repr(e)})
        jobs.task_done()


def main():
    threading.Thread(target=worker, daemon=True).start()
    if TG.tg_on():
        chats = [env.get("CHAT_ID")] + [v for k, v in env.items() if k.endswith("_CHAT_ID") and k != "SX_CHAT_ID" and not k.startswith("LARK_")]
        TK.init(env)
        TG.poll(on_tele, chats, allow_users=[OWNER], pre=TK.on_update); return
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import P2ImMessageReceiveV1  # noqa: F401
    h = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(on_message).build()
    cli = lark.ws.Client(env["APP_ID"], env["APP_SECRET"], event_handler=h,
                         domain=lark.LARK_DOMAIN, log_level=lark.LogLevel.WARNING)
    print("Đang nghe tin tag bot kho…" + (" (dry)" if DRY else ""), flush=True)
    cli.start()


if __name__ == "__main__":
    main()
