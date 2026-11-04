# Cảnh báo kho — agent tự học, lên dần v1 → v2 → v3

Bot kho tự gửi cảnh báo vào nhóm **KHO - HÀNG VỀ & RESTOCK** lúc 9h sáng (`python3 tools/lark.py nhac --send`). Lượt nhắc này không gọi Claude nên không tốn token. Ngưỡng số nằm ở `knowledge/canh_bao.json`.

## Cảnh báo đang chạy (v1)
| Cảnh báo | Khi nào báo | Bảng | Ngưỡng |
|---|---|---|---|
| Hàng đặt lại chưa về | đặt ≥ 10 ngày chưa tick "Đã về đủ" | 02 | `dat_lai_chua_ve.so_ngay` |
| Quá hẹn hàng về | qua "Hẹn hàng về" mà chưa về đủ | 02 | — |
| Demo chưa về | "Đang làm demo", gửi xưởng ≥ 7 ngày (hoặc quá "Hạn demo") | 01 | `demo_chua_ve.so_ngay` |
| Sản xuất quá hẹn | "Đang sản xuất"/"Chờ hàng về", quá "Hẹn hàng về", chưa có ngày nhận kho | 01 | — |
| ⏰ Đơn sắp hết hạn trên sàn | đơn hoàn/khiếu nại chưa Đóng, hạn sàn còn ≤ 24h | 06 | `don_van_de_sap_het_han.so_gio` |
| Đơn vấn đề tồn đọng | chưa Đóng sau ≥ 3 ngày từ ngày phát sinh | 06 | `don_van_de_ton_dong.so_ngay` |
| Chưa nhập Nhanh.vn | hàng về / hàng hoàn nguyên vẹn mà ≥ 1 ngày chưa tick nhập Nhanh.vn | 03, 06 | `chua_nhap_nhanh.so_ngay` |
| Thiếu đối soát | hôm qua chưa có dòng đối soát TikTok/Shopee | 07 | `thieu_doi_soat.san` |
| Thiếu dữ liệu | dòng thiếu ngày nên không nhắc được | 01 | — |

## Agent tự học thế nào
Mỗi lần xử lý tin được tag, agent để ý 3 thứ:
1. **Ngưỡng sai thực tế.** Ví dụ: xưởng A luôn giao 14 ngày nên nhắc ở ngày 10 là nhắc thừa; hoặc chủ shop/trưởng kho nói "từ nay đặt 7 ngày chưa về là nhắc". Có người chốt thì agent sửa số trong `canh_bao.json` và ghi 1 dòng vào **Nhật ký thay đổi** bên dưới. Chưa ai chốt thì chỉ ghi vào **Đề xuất**.
2. **Lỗi lặp lại mà chưa có cảnh báo.** Ví dụ: cùng 1 mẫu bị giao sai size 3 lần/tuần; hàng hoàn nằm kho quá 2 ngày chưa kiểm. Agent ghi vào **Đề xuất** (vấn đề, đã gặp mấy lần, cảnh báo nên thêm, ngưỡng gợi ý).
3. **Cột Base hay bị bỏ trống** làm cảnh báo không chạy được (VD "Ngày gửi demo"). Agent nhắc người nhắn tin bổ sung và ghi vào **Đề xuất**.

Đề xuất cần sửa code (cảnh báo kiểu mới) sẽ được làm ở phiên bản sau. Agent **không** tự sửa `tools/` khi đang xử lý tin.

## Lộ trình
- **v1 (đang chạy):** ghi sổ hàng về, đặt lại, đơn vấn đề, đối soát; trả lời tình trạng hàng cho CSKH; 9 cảnh báo 9h sáng ở trên; ngưỡng chỉnh được không cần sửa code.
- **v2 (khi có đủ dữ liệu ~1 tháng):** agent tự đề xuất ngưỡng theo dữ liệu thật (xưởng nào hay trễ bao nhiêu ngày, mẫu nào hoàn nhiều); cảnh báo sắp hết hàng theo tốc độ bán; báo cáo tuần (hoàn/huỷ theo sàn, lệch bill theo xưởng, đơn trễ); nhắc theo người (tag đúng người phụ trách).
- **v3 (khi có quyền Nhanh.vn/sàn):** tự lấy tồn và đơn từ Nhanh.vn để so tồn Base với tồn thật; tự phát hiện đơn trễ bàn giao; gợi ý số lượng đặt lại theo tốc độ bán + thời gian xưởng.

## Đề xuất (agent ghi, chủ shop/trưởng kho duyệt)
| Ngày | Vấn đề gặp | Số lần | Đề xuất | Trạng thái |
|---|---|---|---|---|

## Nhật ký thay đổi ngưỡng
| Ngày | Thay đổi | Ai chốt | Lý do |
|---|---|---|---|
| 04/11/2026 | Tạo v1: đặt lại 10 ngày, demo 7 ngày, hạn sàn 24h, tồn đọng 3 ngày, chưa nhập Nhanh 1 ngày | chủ shop | yêu cầu ban đầu |
