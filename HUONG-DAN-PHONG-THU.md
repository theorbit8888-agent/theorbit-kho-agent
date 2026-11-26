# Phòng kho giả lập trên Telegram — cho quản lý kho / người hoàn thiện bot kho

Chạy **đúng code bot kho thật** trên máy bạn, với **bot + nhóm Telegram THỬ** của bạn.
Bạn bấm nút, gửi ảnh, gõ lệnh trong Telegram y như nhân viên thật, nhưng:
- Google Sheet, Nhanh.vn, Seller Center, Chrome: **giả hết** (dữ liệu ở `logs/phong-thu/` trên máy bạn).
- Không đụng bot, nhóm, Sheet hay Nhanh thật của shop. Tool tự chặn nếu dán nhầm token bot thật.

## 1. Tải gì về
Chỉ cần repo này + Python 3 (Mac có sẵn) + Telegram:
```
git clone https://github.com/theorbit8888-agent/theorbit-kho-agent.git
cd theorbit-kho-agent
```
Repo riêng tư: chủ shop phải mời tài khoản GitHub của bạn trước.
**Không** tải: file env, token, `logs/` của máy chủ shop (đã chặn trong .gitignore).

## 2. Dựng phòng thử (làm 1 lần, ~10 phút)
1. Telegram → **@BotFather** → `/newbot` → đặt tên, vd `orbit_kho_thu_<tên bạn>_bot` → lấy **token**.
   Tiếp `/setprivacy` → chọn bot → **Disable** (để bot đọc được tin trong nhóm).
2. Tạo 3 nhóm Telegram, thêm bot thử vào cả 3 (và người muốn thử cùng):
   - `THỬ · Kho` (thay nhóm Kho hàng về & restock)
   - `THỬ · Đổi trả CS-Kho` (ticket)
   - `THỬ · CS & Cửa hàng` (két, chốt ca)
3. Chạy `python3 tools/phong_thu.py --cai` → dán token → vào từng nhóm gõ `/chatid@<tên bot thử>`,
   nhắn riêng bot 1 câu → Enter. Tool tự ghi `~/.config/orbit-kho-thu/thu.env` (nằm ngoài repo).

## 3. Chạy
```
python3 tools/phong_thu.py          # bật bot thử, để cửa sổ này mở; Ctrl+C để tắt
python3 tools/phong_thu.py --reset  # xoá sạch dữ liệu giả, làm lại từ đầu
```
Trong nhóm thử gõ như thật: `/kho`, `/hangve rivet`, `/hoan SPX…`, `/indon`, `/giao`, `/kiemkho`,
`/tk`, `/moca 4tr`, `/chotca …`, bấm nút, trả lời tin bot bằng ảnh…

## 4. Lệnh giả lập `/thu` (chỉ người cài phòng thử gõ được)
| Lệnh | Giả cái gì |
|---|---|
| `/thu nhanh-gia` | Nhanh có tồn + đơn 14 ngày (thử dự báo hết hàng, `/kho`, `/kiemkho`) |
| `/thu nhanh-don` | 9 đơn chờ gửi TikTok/Shopee/Web (thử `/indon`, `/giao`, đối soát) |
| `/thu nhanh-st TT1001 59` | Nhanh đồng bộ: ĐVVC đã lấy (59) / khách huỷ (63) |
| `/thu luc 10:15` | Giả đồng hồ + chạy mọi việc hẹn giờ lúc đó (10:15 đơn huỷ sau in, 17:30 kiểm kho, 21:45 chốt ca…) |
| `/thu gio-that` | Về giờ thật |
| `/thu doisoat`, `gio10`, `canhhuy`, `dubao`, `phieu`, `thieu` | Chạy tay từng việc hẹn giờ |
| `/thu nhanh-hoan MVĐ 72`, `nhanh-tra MÃ`, `doisoat-hoan` | Hàng hoàn ĐVVC / khách trả |
| `/thu cskh-note` | Bot CSKH báo đơn có ghi chú vào nhóm kho |
| `/thu xem` · `/thu xem 05` | Xem Sheet giả |

Đủ danh sách lệnh: đầu file `tools/san_thu.py`. Thử nhanh trong terminal không cần Telegram:
`python3 tools/san_thu.py kich-ban/day-du.txt`.

## 5. Hiện đang chạy thật trên Telegram (để biết phòng thử phủ tới đâu)
| Đang chạy ở máy chủ shop | Nhóm thật | Phòng thử |
|---|---|---|
| Bot kho `listener.py`: lệnh + nút + ticket + cửa hàng | Kho · Hàng về & restock; Đổi trả CS-Kho; CS & Cửa hàng | ✅ chạy đúng code |
| Hẹn giờ kho `kho_flow.py hen` 9:02 10:15 12:00 17:00 17:30 18:00 | Kho | ✅ `/thu luc HH:MM` |
| Hẹn giờ cửa hàng `cua_hang.py hen` 10/14/18h, 15:50, 16:20, 21:30, 21:50, 22:05, 22:20 | CS & Cửa hàng | ✅ `/thu luc HH:MM` |
| Nhắc ticket 9:05 `ticket.py nhac` | Đổi trả | ✅ `/thu luc 9:05` |
| Đồng bộ Nhanh 3 phút / 30 phút `nhanh.py sync` | — | 🟡 giả bằng `/thu nhanh-…` |
| Nhắc kho 9:00 `lark.py nhac` | Kho | ❌ chưa |
| Tin Claude đọc khi tag bot bằng chữ tự do | Kho | ❌ phòng thử chỉ trả "tin chữ tự do do Claude đọc ở máy thật" |
| Bot CSKH báo ca / xác nhận đơn / note khách (tag kho) | CSKH ca cần xử lý; Xác nhận đơn; Note khách | 🟡 chỉ `/thu cskh-note` |
| Đọc Seller Center 7h30 + hoàn sàn 8h30/15h30 (tác vụ lịch Claude, Chrome) | Kho; Đổi trả | 🟡 giả bằng `/thu so-san …`, `/thu hoan-san …` với file csv trong `kich-ban/` |
| Bot HCNS (điểm danh, lịch ca → tag người trong ca) | Điểm danh | ❌ chưa (phòng thử không tag theo ca) |

## 6. Tải về xong: việc cần làm tiếp (dán từng câu vào Claude Code trong thư mục repo)
Phòng thử đã chạy được ngay. Các phần dưới còn giả/chưa có, làm dần theo thứ tự:
1. **Đồng bộ Nhanh:** "Đọc tools/nhanh_api.py + tools/nhanh.py. Viết lệnh `/thu nhanh-mau` nạp tồn + đơn giả có cấu trúc giống hệt logs/nhanh/ thật (products.json, orders.json, meta.json, nhap_tra.json), đủ trường hợp: đơn chờ gửi, đã lấy, huỷ sau in, hoàn, combo. Không gọi API Nhanh thật."
2. **Đọc Seller Center (7h30 + hoàn sàn 8h30/15h30):** "Đọc tools/doc_san.js, xuat_kho.py sosan, hoan_san.py. Làm `/thu san-mau` giả kết quả đọc TikTok/Shopee (dùng csv mẫu trong kich-ban/) rồi chạy đúng luồng so sàn ↔ Nhanh và báo nhóm như 7h30 thật."
3. **Tin chữ tự do (tag bot bằng câu thường):** "Ở máy thật listener.py gọi Claude đọc CLAUDE.md rồi ghi Sheet. Cho phòng thử một chế độ gọi Claude Code trên máy mình (claude -p) với Sheet giả, để thử kho nhắn kiểu tự nhiên."
4. **Nhắc kho 9h (`lark.py nhac`):** "Cho `/thu luc 9:00` chạy luôn nhắc kho 9h vào nhóm THỬ · Kho, đọc Sheet giả."
5. **Lịch ca HCNS (tag người trong ca):** "Tạo file lịch ca giả giống ~/orbit-runtime/lich/ca.json (tên + Telegram ID người thử) để bot tag đúng người theo ca."
6. **Bot CSKH vào nhóm kho:** "Thêm nhóm THỬ · Xác nhận đơn + THỬ · Note khách; `/thu cskh-don`, `/thu cskh-note` gửi tin đúng mẫu tools/lark_notify.py bên agent CSKH (--group don/note), có tag kho."
Mỗi việc xong: chạy lại phòng thử + `kich-ban/`, mở Pull Request ghi đã thử gì. **Không** xin token/API thật của shop: phần nào cần dữ liệu thật thì chủ shop thử trên máy thật.

## 7. Sửa xong: gửi về cho chủ shop thế nào
1. Làm trên nhánh riêng: `git checkout -b <tên-bạn>/<việc>` (vd `my/hangve-anh`).
2. Chạy lại phòng thử + `python3 tools/san_thu.py kich-ban/day-du.txt`; luồng mới thì thêm 1 file `kich-ban/<việc>.txt`
   (có cả ví dụ KHÔNG áp dụng) — máy chủ shop sẽ tự chạy mọi kịch bản này trước khi lên bot thật.
3. `git push -u origin <nhánh>` → trên GitHub bấm **Compare & pull request**, ghi: sửa gì, đã thử kịch bản nào.
4. Chủ shop duyệt. Máy chạy thật dùng `bash tools/cap_nhat.sh thu <nhánh>` (chạy hết kịch bản trên bản sao riêng)
   → `bash tools/cap_nhat.sh len <nhánh>` (gộp, cài lại job, kiểm bot còn chạy). Lỗi thì `cap_nhat.sh lui` quay về bản cũ.
   Kịch bản nào hỏng là **không** lên được, nên đừng gửi nhánh chưa chạy thử.

## 8. Luật
- **Không bao giờ** chạy `tools/listener.py` hay dán token bot thật vào máy bạn: 2 máy nghe 1 bot sẽ giành tin, bot thật chạy sai.
- Không đưa SĐT/STK/CCCD khách hoặc nhân viên vào code, kịch bản, nhóm thử.
- Sửa code: nhánh riêng → chạy lại phòng thử + `kich-ban/` → Pull Request → chủ shop duyệt rồi mới lên bot thật.
