# Bật bot Lark cho agent Kho (chủ shop làm một lần, ~10 phút)

Cách chạy: một chương trình nhỏ trên máy Mac (`tools/listener.py`) giữ kết nối với Lark. **Rảnh thì không tốn token.** Chỉ khi có người tag **@Kho Agent Orbit** thì nó mới gọi Claude xử lý tin đó, ghi Base và trả lời trong luồng. Máy Mac phải bật (không ngủ) thì bot mới trả lời; tắt máy thì tin vẫn nằm trong Lark, bật lại thì tag lại.

## 1. Tạo app bot
1. Vào **open.larksuite.com/app** → *Create custom app* → tên `Kho Agent Orbit` → bật **Bot** (Features → Bot).
2. **Permissions & Scopes** — thêm đúng các quyền này:
   - `im:message` (gửi/trả lời tin)
   - `im:message.group_at_msg:readonly` (**chỉ** nhận tin có tag bot trong nhóm — KHÔNG thêm `im:message.group_msg`, quyền đó bắt bot nhận mọi tin → tốn)
   - `im:message.p2p_msg:readonly` (nhắn riêng cho bot)
   - `im:chat:readonly`
   - `bitable:app` (đọc/ghi Base)
   - `wiki:wiki:readonly` (Base nằm trong Wiki)
3. **Events & Callbacks** → Subscription mode: chọn **Receive events through persistent connection** (kết nối dài, không cần URL) → Add event **`im.message.receive_v1`** (Receive messages).
4. **Version Management** → tạo version → Publish → admin (ORBIT HOOD) duyệt.

## 2. Cho bot vào nhóm + vào Base
1. Nhóm kho (đề xuất tạo nhóm **KHO - HÀNG VỀ & RESTOCK**, hoặc dùng nhóm kho sẵn có) → Settings → Bots → Add → `Kho Agent Orbit`. Có thể thêm bot vào cả nhóm **KHO - CSKH THE ORBIT** để kho tag bot ở đó.
2. Mở Base **THE ORBIT — Product Launch & Restock** → `...` → *Add document app* / *Share* → thêm `Kho Agent Orbit` quyền **có thể chỉnh sửa**. (Base nằm trong Wiki: nếu không thấy, vào trang Wiki → Settings → thêm bot làm thành viên có quyền sửa.)

## 3. Lưu secret (gõ trong Terminal, KHÔNG dán vào chat)
Lấy App ID / App Secret ở *Credentials & Basic Info*. Copy App Secret rồi chạy:
```bash
mkdir -p ~/.config/orbit-kho && printf 'APP_ID=%s\nAPP_SECRET=%s\n' "cli_xxx" "$(pbpaste)" > ~/.config/orbit-kho/lark.env && chmod 600 ~/.config/orbit-kho/lark.env
```
(thay `cli_xxx` bằng App ID). Tuỳ chọn thêm dòng `CLAUDE_MODEL=sonnet`.

## 4. Đăng nhập Claude Code cho chạy nền (1 lần)
Listener gọi Claude Code ở chế độ không giao diện; bản trong app Claude chưa đăng nhập cho chế độ này. Cài CLI rồi đăng nhập:
```bash
curl -fsSL https://claude.ai/install.sh | bash
```
```bash
~/.local/bin/claude auth login
```
(đăng nhập trên trình duyệt; thông tin lưu trong Keychain của máy, không cần token trong file env). Đã làm 04/11/2026: CLI 2.1.318 ở `~/.local/bin/claude`.

## 5. Kiểm tra
```bash
cd ~/Desktop/kho-agent && python3 tools/lark.py chats && python3 tools/lark.py tables
```
```bash
cd ~/Desktop/kho-agent && python3 tools/lark.py setup-base
```
(in kế hoạch thêm bảng/cột; đúng thì chạy lại với `--apply`). Rồi chạy thử listener (chưa gọi Claude):
```bash
cd ~/Desktop/kho-agent && .venv/bin/python tools/listener.py --dry
```
Tag bot trong nhóm → Terminal phải in nội dung tin. Ctrl+C để dừng.

## 6. Cho chạy nền tự bật cùng máy
```bash
cd ~/Desktop/kho-agent && ./tools/install_launchd.sh
```
Log: `logs/listener.out`, tin đã nhận `logs/inbox.jsonl`, lỗi `logs/loi.jsonl`. Tắt: `launchctl unload ~/Library/LaunchAgents/vn.theorbit.kho-agent.plist`.
