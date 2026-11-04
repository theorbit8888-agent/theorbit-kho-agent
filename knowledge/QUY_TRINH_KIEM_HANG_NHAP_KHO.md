# Quy trình kiểm hàng trước khi nhập kho (tóm tắt từ Lark "The ORBIT - WH - Quy trình Kiểm hàng Trước khi nhập kho - Ver 1", 21/02/2025)

**Nguyên tắc số 1: nhập kho theo số WH kiểm thực tế, tuyệt đối không theo bill NCC/xưởng.** Bill sai → tồn phần mềm sai → đồng bộ tồn lên sàn sai (SKU thiếu thì mất đơn, SKU thừa thì khách đặt mà không có hàng → đánh giá xấu); bill thiếu → trả thừa tiền NCC.

| Bước | Ai | Việc | Ghi chú |
|---|---|---|---|
| 1. Chuẩn bị | WHM | Nhận báo gửi hàng + bill kiểm kê NCC; chuẩn bị mẫu đối (mẫu chuẩn), thước, bảng size, bảng kiểm in sẵn theo SKU con, biên bản thiếu kiện | Không in bảng kiểm sẵn → mất thời gian ghi tay |
| 2. NCC trả hàng | WHM | Đòi bill xuất hàng (mã phiếu, SKU con, SL) — giấy hoặc ảnh gửi nhóm | Thiếu bill phải đòi bằng được |
| 3. Kiểm số kiện/bao/thùng | WHM | So với NCC báo. Thiếu/rách → lập biên bản 2 bản, ký 2 bên với shipper, chụp ảnh, báo NCC trong 2h | Không lập biên bản: phạt 200.000đ/lần |
| 4. Kiểm ngoại quan kiện | WHM | Rách/hư → biên bản với người giao + ảnh, báo NCC | Phạt luỹ tiến: nhắc → 20k → 100k → 500k → sa thải |
| 5. Chia hàng | WHM | Chia bao/thùng cho các WH kiểm song song | |
| 6. Kiểm số lượng + chất lượng | WH | Kiểm **cuốn chiếu** từng bao: đếm theo SKU con, so mẫu đối về màu/size/đường may/thông số; hàng lỗi để riêng | Không đổ nhiều bao ra cùng lúc → lẫn hàng |
| 7. Cộng phiếu | WHM | Cộng tổng các phiếu kiểm | |
| 8. So bill | WHM | SKU lệch bill → kiểm lại lần 2; vẫn lệch thì **lấy số kiểm lần 2 của công ty**. NCC chưa gửi bill → giục; chưa có thì nhập theo số mình kiểm | |
| 9. Báo cáo kiểm hàng | WHM | Ngày nhập, kho, người kiểm, SKU con, SL, tình trạng bill (đủ/thiếu/thừa), ID phiếu nhập QLBH, giá nhập | Lỗi hay gặp: dùng giá nhập phiếu cũ → giá vốn sai |
| 10. Nhập kho | WH | Nhập Nhanh.vn, xếp đúng vị trí | |
| 11. Lưu bill | WH | Lưu bill giấy vào hồ sơ + file mềm đính kèm phiếu nhập | |

Giám sát: quản lý kho kiểm random ≥30% số lần nhập kho trong tháng. Sự cố thiếu/thừa/lỗi → báo NCC ngay để tính lại tiền.

**Gắn với Base:** bước 9 = 1 dòng bảng `03 · NHẬP KHO` (tag bot báo hàng về là đủ). Form báo cáo cũ của KB Group trong tài liệu gốc vẫn dùng được; bảng 03 là bản gọn cho các phòng xem.
