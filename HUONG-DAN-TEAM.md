# Hướng dẫn team cùng build agent kho / Telegram vận hành The Orbit

## Agent này làm gì
Bot Telegram @theorbit_kho_bot lo 3 nhóm: **Kho hàng về & restock**, **Đổi trả CS-Kho** (ticket), **CS & Cửa hàng** (két, chuyển khoản, giao việc, chốt ca). Dữ liệu ghi vào Google Sheet qua Apps Script; đọc Nhanh.vn qua Chrome đã đăng nhập (không có API).
Đọc thêm: `CLAUDE.md` (luật + mô tả từng luồng), `SETUP_LARK.md`.

## Code ở đâu
| File | Việc |
|---|---|
| `tools/listener.py` | vòng nghe Telegram, nạp các module dưới |
| `tools/orbit_tg.py` | thư viện Telegram dùng chung (bản gốc ở telegram-agent/lib) |
| `tools/ticket.py` | ticket đổi/trả/hoàn, lỗi kho → phạt |
| `tools/kho_flow.py` | /hangve /hoan /chotdi /chothoan /kiemkho /nhanh, cảnh báo cháy hàng |
| `tools/cua_hang.py` | /moca /chi /thu /ketca /bill /goi /note /hoatoc /chotca |
| `tools/nhanh.py` | đọc Nhanh.vn bằng Chrome (Playwright, hồ sơ riêng) |
| `tools/lark.py` | đọc/ghi Lark Base + Sheet, nhắc 9h |
| `tools/install_launchd.sh` | cài job chạy nền trên Mac chủ shop |

## Có 2 cách tham gia

### A. Góp ý (không cần cài gì)
- Dùng bot thật trong nhóm như bình thường, hoặc chạy sân thử ở dưới.
- Thấy gì chưa ổn → GitHub repo → **Issues → New issue → "Góp ý / báo lỗi bot kho"**, điền 4 dòng (làm trên điện thoại được).
- Chủ shop/agent đọc Issue, sửa, cập nhật bot.

### B. Hoàn thiện code (chỉ cần Claude Code)
1. `git clone https://github.com/theorbit8888-agent/theorbit-kho-agent.git` → mở thư mục bằng Claude Code.
2. Chạy **sân thử** — bot giả chạy ngay trên máy, KHÔNG cần bot/nhóm/Sheet thật, không gửi tin thật:
   - `python3 tools/san_thu.py` → gõ như đang chat: `kho: /kho`, `ch: /moca 4tr`, `la kho`, `bam 1`, `xem`.
   - `python3 tools/san_thu.py kich-ban/mau.txt` → chạy kịch bản có sẵn (thêm kịch bản mới vào `kich-ban/`).
   - `python3 tools/san_thu.py --reset` → xoá dữ liệu thử.
   - Nhờ Claude: "chạy sân thử kịch bản mau.txt, tìm chỗ khó dùng và sửa".
3. Sửa xong: chạy lại kịch bản cho chắc → tạo nhánh → đẩy lên → mở **Pull Request** ghi rõ sửa gì, đã thử kịch bản nào.
4. Chủ shop duyệt → agent cập nhật lên máy chạy thật.

(Phần đọc Nhanh.vn / sàn cần Chrome đã đăng nhập của shop → sân thử bỏ qua, chủ shop thử trên máy thật.)

## Menu lệnh "/" trong Telegram (tự động, bàn giao không cần làm tay)
Gõ "/" trong nhóm → Telegram hiện đúng lệnh của nhóm đó kèm mô tả. Bot **tự khai báo mỗi lần khởi động**
(`tools/menu_lenh.py`, gọi từ `listener.py` và `phong_thu.py`), không cần vào @BotFather `/setcommands`.
- Lệnh nào hiện ở nhóm nào: bot tự đọc từ code (lệnh các module đăng ký + nhóm được dùng).
- ID nhóm: đọc từ env (`CHAT_ID`, `TICKET_CHAT_ID`, `CH_CHAT_ID`).
- **Bàn giao / đổi bot / đổi nhóm / máy mới:** sửa env (token, ID nhóm) → khởi động lại bot → menu tự cập nhật.
  Nhóm bị Telegram nâng lên supergroup thì ID nhóm đổi (dạng `-100…`) → sửa env như trên.
- **Thêm lệnh mới:** thêm 1 dòng mô tả vào `MO_TA` trong `tools/menu_lenh.py` (lệnh dùng ở mọi nhóm thì thêm cả `NHA`).
  Quên → `python3 tools/menu_lenh.py kiem` báo lỗi → `cap_nhat.sh thu` không cho lên bot thật.
- Xem trước menu: `python3 tools/menu_lenh.py xem`.

## Luật bắt buộc
- **Không bao giờ** chạy `listener.py` bằng token bot thật (dùng sân thử là đủ): 2 máy cùng nghe 1 bot sẽ giành tin của nhau, bot thật chạy sai.
- Không commit/gửi file env, token, cookie, log (`logs/` đã bị .gitignore).
- Không đưa SĐT / STK / CCCD khách hay nhân viên vào code, test hay nhóm đông.
- Làm trên nhánh riêng → mở Pull Request → chủ shop duyệt → chủ shop `git pull` trên máy chạy thật + chạy lại `tools/install_launchd.sh`.
- Dùng Claude Code cũng được: mở thư mục repo, Claude tự đọc `CLAUDE.md`.
