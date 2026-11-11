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

## Cài để thử (máy của bạn, KHÔNG đụng nhóm thật)
1. `git clone <repo>` → `cd kho-agent` → `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/playwright install chrome`
2. Tạo **bot thử** bằng @BotFather, 3 **nhóm Telegram thử**, thêm bot vào nhóm.
3. Xin chủ shop **bản copy Google Sheet** (không phải Sheet thật) + deploy Apps Script của bản copy.
4. `mkdir -p ~/.config/orbit-kho-test && cp lark.env.example ~/.config/orbit-kho-test/lark.env` rồi điền đồ thử.
5. Chạy: `ORBIT_KHO_ENV=~/.config/orbit-kho-test/lark.env .venv/bin/python tools/listener.py`

## Luật bắt buộc
- **Không bao giờ** chạy bằng token bot thật: 2 máy cùng nghe 1 bot sẽ giành tin của nhau, bot thật chạy sai.
- Không commit/gửi file env, token, cookie, log (`logs/` đã bị .gitignore).
- Không đưa SĐT / STK / CCCD khách hay nhân viên vào code, test hay nhóm đông.
- Làm trên nhánh riêng → mở Pull Request → chủ shop duyệt → chủ shop `git pull` trên máy chạy thật + chạy lại `tools/install_launchd.sh`.
- Dùng Claude Code cũng được: mở thư mục repo, Claude tự đọc `CLAUDE.md`.
