# SOP Nhanh.vn — nhập hoàn kho hàng sàn + đơn đổi hàng

Soạn từ video hướng dẫn của chủ shop (quay màn hình 27/11/2026, ~10 phút). Video có lời nói nhưng chưa chép được thành chữ,
nên phần dưới chỉ ghi những gì **thấy trên màn hình**. Chỗ đánh dấu ❓ là chỗ cần chủ shop xác nhận.

Bot **chỉ đọc** Nhanh: mọi thao tác dưới đây do kho làm tay. Bot đối chiếu sau mỗi lần đồng bộ Nhanh (`tools/nhap_hoan.py`).

---

## A. Nhập hoàn kho — hàng sàn trả về (Shopee / TikTok)
Dùng cho: khách trả hàng hoàn tiền, giao thất bại / đơn bom (hoàn ĐVVC).

**Bắt đầu từ bảng `SP 09 · HÀNG HOÀN NHẬN`**: kiện kho đã quét `/hoan`, cột trạng thái **MỚI** = chưa nhập Nhanh.

1. Nhanh › **Kênh bán › Sàn TMĐT › Trả hàng hoàn tiền** → chọn tab sàn (**Shopee** / **Tiktok**).
2. Bấm **Nhập hoàn kho**.
3. Chọn **biên bản bàn giao** ở ô bên phải (VD `3869 - 27/11 - KHO TỔNG - CN QUẬN 2 - SPX Express`).
   Chưa có biên bản hôm nay → bấm **+** → *Thêm biên bản bàn giao*:
   - Kho hàng: **KHO TỔNG - CN QUẬN 2**
   - Hãng vận chuyển: theo kiện (**SPX Express** cho Shopee, **J&T Express** cho TikTok…)
   - Loại biên bản: **Nhận HVC hoàn về**
   - Biên bản sàn: **Biên bản Shopee** / TikTok
   - Ghi chú (nếu có) → **Lưu**
4. Ô quét: để **"ID yêu cầu trả hàng / Mã vận đơn trả"** rồi quét/gõ tem hoàn.
   - Đơn **giao thất bại / đang hoàn** (VD tem `GYECH…` của Giao Hàng Nhanh): đổi ô chọn sang **"Mã vận đơn gốc"** rồi quét.
5. Kiểm dòng sản phẩm hiện ra: **SL xuất**, **SL khách nhận**, **SL mất** → **SL hoàn = SL xuất − SL khách nhận − SL mất**.
   - Khách đã nhận một phần / mất hàng → sửa SL khách nhận / SL mất.
   - Khách đòi hoàn tiền mà không trả hàng → điền SL mất + trạng thái **"Không được đền bù"** (theo hướng dẫn bên phải màn hình Nhanh).
6. Bấm **Xác nhận** → góc phải báo *"Đơn hàng … cập nhật hoàn kho thành công"*; bảng **Đơn hàng đã xác nhận hoàn**
   có dòng mới *Đơn hoàn một phần · Đã hoàn*.
7. Về bảng 09: đổi cột trạng thái dòng đó **MỚI → HOÀN THÀNH**.
   👉 Từ 28/11 bot tự ghi cột **"Nhập hoàn Nhanh" ✅** sau lần đồng bộ kế tiếp (không cần đổi tay nữa).

**Kiện lỗi / bị tráo / thiếu** (cột 09 = Không nguyên vẹn / Bị tráo hàng, trạng thái **CHỜ XỬ LÝ**): **KHÔNG nhập hoàn kho trên Nhanh**
(chủ shop chốt 28/11/2026) — xử lý khiếu nại theo ticket HHV. Bot không nhắc nhập các kiện này.

**Tra thêm khi không chắc đơn** (video): Shopee Seller Center › *Đơn Trả hàng/Hoàn tiền hoặc Đơn hủy* › tìm theo tên người mua
(VD đơn GYECHMT4 đã huỷ tự động, khiếu nại bị từ chối → ghi chú ở cột O bảng 09); TikTok Seller Center › *Quản lý đơn hàng*.

---

## B. Đơn đổi hàng (đổi size sau giao) — nhập hàng khách trả về
Trường hợp mẫu trong video: đơn Shopee gốc `261116EH0UXTJK` (ID Nhanh **886786089**, áo Orlymbit **XL**), shop đã gửi
**đơn đi đổi** `888775492` (nhãn **Đơn đi_Đổi**, J&T, size **L**, ghi chú *"261116EH0UXTJK-Đổi hàng … Sang JS-G3-ORLYMBIT-L
Shopee, đổi size XL→L, phí 25k"*). Khi áo **XL** khách gửi về tới kho:

1. Nhanh › **Đơn hàng › Danh sách đơn hàng** → ô **Mã vận đơn** gõ mã đơn đi / mã đơn sàn để tìm đơn đổi.
2. Nhanh › **Kênh bán › Shopee** (hoặc TikTok) → ô **ID Shopee** gõ mã đơn sàn gốc → **Lọc** → ra đơn gốc (886786089).
3. Ở đơn gốc bấm menu **≡** (góc phải) → tạo đơn trả → Nhanh mở trang **Thêm đơn hàng** (`order/manage/add?…&idReturn=<ID gốc>`):
   - Loại: **Khách trả lại hàng**, ô bên dưới tự điền **ID đơn gốc**.
   - Sản phẩm: món khách **trả về** (VD `JS-G3-ORLYMBIT-XL` × 1), **Chọn kho: KHO TỔNG - CN QUẬN 2**.
   - Nhãn **Đơn về_Đổi**, ghi chú CSKH nếu cần.
   - Phần **Vận chuyển**: **tick ô "Tự vận chuyển"** (chủ shop chốt 28/11/2026 — luôn tick, không chọn hãng).
   - Bấm **(F9) Lưu**.
4. Về **Danh sách đơn hàng**: đơn mới có ghi chú *"<mã sàn> (Trả từ đơn: <ID gốc>)"*, nhãn **Đơn về_Đổi**.
   Tick đơn → **Thao tác › Đổi trạng thái** → **Thành công** (ngày giao thành công = hôm nay) → **Đổi trạng thái**.
   → **Phải chuyển Thành công thì Nhanh mới cộng tồn** món khách trả (chủ shop chốt 28/11/2026); Nhanh tạo phiếu nhập trả
   "Trả từ đơn: <ID gốc>" — bot dựa vào phiếu này để đóng ticket. Lưu xong mà quên đổi trạng thái → tồn chưa cộng, ticket không đóng.
5. Ticket đổi sau giao (DHS) ở nhóm Đổi trả: bước **"Chờ nhập kho QLBH"**.
   👉 Từ 28/11 bot tự tick + đóng ticket khi Nhanh có phiếu nhập trả của đơn gốc. Kho bấm "Đã nhập kho QLBH" mà Nhanh
   chưa có phiếu → bot nhắc nhập trước (có nút "Đã kiểm tay" nếu nhập cách khác).

**Đơn đi đổi**: CS tạo trên Nhanh (sản phẩm = SKU **đổi sang**, nhãn **Đơn đi_Đổi**). Khi CS gõ MVĐ đơn đi vào ticket, bot đối
chiếu: đơn đi trên Nhanh không có SKU đổi sang → báo nhóm Đổi trả 1 lần.

---

## Bot làm gì (tools/nhap_hoan.py)
| Lúc | Việc |
|---|---|
| Sau mỗi lần đồng bộ Nhanh | Bảng 09: Nhanh có phiếu nhập trả / đơn trả `R` / "Đã chuyển hoàn" → ghi cột **Nhập hoàn Nhanh ✅** |
| Sau mỗi lần đồng bộ Nhanh | Ticket "Chờ nhập kho QLBH": Nhanh có phiếu nhập trả của đơn gốc → tự tick + đóng |
| Sau mỗi lần đồng bộ Nhanh | Ticket đổi sau giao có MVĐ đơn đi: đơn đi thiếu SKU đổi sang → báo 1 lần |
| 10h / 14h / 18h | Kiện **nguyên vẹn** đã nhận quá `nhap_hoan_ngay` ngày (canh_bao.json, mặc định 1) mà Nhanh chưa nhập → nhắc nhóm Kho kèm các bước ở mục A |

## Quy định chủ shop đã chốt (28/11/2026)
1. Kiện **bị tráo / lỗi**: **không** nhập hoàn kho trên Nhanh.
2. Đơn về đổi: luôn **tick "Tự vận chuyển"**, rồi **đổi trạng thái sang Thành công** thì Nhanh mới cộng tồn.

## ❓ Còn cần chủ shop xác nhận
- Cột trạng thái tay ở bảng 09 (MỚI / CHỜ XỬ LÝ / HOÀN THÀNH): giữ song song hay bỏ, dùng cột bot "Nhập hoàn Nhanh"?
