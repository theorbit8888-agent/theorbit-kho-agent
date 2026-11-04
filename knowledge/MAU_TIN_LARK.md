# Mẫu tin kho nhắn bot + cách agent ghi

Người kho nhắn tự nhiên, không cần đúng mẫu. Đây là các dạng hay gặp và bảng phải ghi. Luôn tag **@Kho Agent Orbit** (không tag thì bot không thấy — cố ý, để không tốn token).

| Người kho nhắn | Agent làm |
|---|---|
| `@Kho Agent hàng về TENEBRA đen: M 20, L 30, XL 10 — lỗi 2 L — kho tổng — bill xưởng ghi L 32` | 03: thêm dòng (SL bill 62, kiểm thực tế 60, lỗi 2, nhập 58, Lệch bill = Thiếu). 02: cộng SL đã nhận vào dòng đặt lại đang mở của TENEBRA. 05: TENEBRA → "Còn hàng", xoá "Hàng về dự kiến". `export`. Trả lời + hỏi "đã nhập Nhanh.vn chưa?" |
| `@Kho Agent đặt lại AURA đen M50 L50, hẹn về 15–18/11, chị Lan theo` | 02: thêm dòng (SL đặt 100, "Màu / Size", hẹn về, người phụ trách, Trạng thái đặt = Đã đặt). 05: AURA → "Hết - chờ restock" + "Hàng về dự kiến 15–18/11" nếu đang hết. |
| `@Kho Agent TENEBRA hết L rồi` / `sắp hết M` | 05: cập nhật dòng mẫu/size. Xem 02 có đặt lại đang mở không → điền "Hàng về dự kiến". `export`. |
| `@Kho Agent AURA xưởng lùi sang 20–22/11` | 02: sửa "Hẹn hàng về" + ghi chú lý do/ngày hẹn cũ. 05: sửa "Hàng về dự kiến". `export`. |
| `@Kho Agent đơn hoàn 5791xxxx TikTok khách trả, nhận rồi, nguyên tag` | 06: thêm/sửa dòng (Loại = Hoàn - khách trả, Trạng thái = Chờ duyệt, Kết quả = Nguyên vẹn - nhập lại). Nhắc: nhập lại Nhanh.vn + người duyệt bấm trên sàn trước hạn. |
| `@Kho Agent đơn 2501xxxx Shopee giao thất bại, hàng đang quay về` | 06: Loại = Hoàn - giao thất bại, Trạng thái = Chờ hàng về kho. |
| `@Kho Agent huỷ đơn 5791xxxx, đã rút hàng khỏi khay` | 06: Loại = Huỷ, Trạng thái = Đóng, ghi chú "rút trước bàn giao". |
| `@Kho Agent đối soát 4/11 TikTok cần gửi 120, đóng 118, bàn giao 118, 2 đơn hết hàng` | 07: thêm dòng "04/11 - TikTok". Lệch ≠ 0 → hỏi mã đơn lệch nếu chưa có. |
| `@Kho Agent TENEBRA còn size L không?` / `AURA bao giờ về?` | Chỉ đọc 05 + 02 (+01) rồi trả lời. Không ghi. |
| `@Kho Agent hôm nay còn việc gì?` | Đọc 06 (chưa Đóng, hạn gần) + 02 (quá hẹn về) + 07 (hôm nay chưa có dòng) → liệt kê việc còn lại. |

## Quy ước ghi
- Tên sản phẩm: theo bảng 01 (VD "ORBIT TENEBRA", "ORBIT AURA"). Người nhắn "tenebra" → khớp "ORBIT TENEBRA".
- Size/màu: dạng `Đen: M20 L30 XL10` (bảng 02 cột "Màu / Size", bảng 03/05 cột "Size/màu"). "Người phụ trách" ở 02 là cột người Lark: chỉ ghi được open_id (VD người gửi tin); tên khác thì ghi vào "Vướng mắc"/ghi chú. "SL còn thiếu", "Tình trạng" ở 02 là cột tự tính — không ghi.
- Ngày: `YYYY-MM-DD` khi gọi `lark.py`.
- Cột chọn (Kho nhận, Trạng thái, Loại, Sàn…) chỉ ghi đúng lựa chọn có sẵn; "kho tổng" = "Kho Tổng Q2", "cửa hàng/PN" = "Kho Cửa hàng PN". Tool tự khớp gần đúng, mơ hồ thì báo lỗi kèm danh sách.
- Nguồn tin: `lark:<message_id> <tên/ngày>`.

## Quy luật học thêm (agent tự ghi khi gặp)
