// Đọc danh sách đơn CẦN GỬI trên Seller Center (Claude in Chrome, Chrome chủ shop đã đăng nhập). CHỈ ĐỌC, không bấm nút đơn.
// Chạy nguyên file trong tab:
//   TikTok:  https://seller-vn.tiktok.com/order?selected_sort=6&tab=to_ship   → gọi  await __docTikTok()
//   Shopee:  https://banhang.shopee.vn/portal/sale/order?type=toship&source=all → gọi  await __docShopee()
// Mỗi hàm trả {n, tong} (tong = số sàn hiển thị) và để kết quả CSV ở window.__out ("ma|mvd|tt|giao" mỗi dòng).
// YÊU CẦU HOÀN (tác vụ lịch hoàn tiền, cũng chỉ đọc):
//   TikTok:  https://seller-vn.tiktok.com/order/return?tab=800   (tab "Đang chờ bạn") → await __docHoanTikTok()
//   Shopee:  https://banhang.shopee.vn/portal/sale/returnrefundcancel                → await __docHoanShopee()
//   → window.__out CSV "ma|loai|ly_do|tt|han|kv|tien|nut|mvd" (nut: phan_hoi = cần duyệt/từ chối, khang_nghi = đã tự hoàn,
//     còn kháng nghị được, xac_nhan = Shopee chờ xác nhận hàng trả về, dang_tra = người mua đang gửi trả (kiện chưa về),
//     kiem_hang = Shopee đã hoàn tiền, kho kiểm hàng hoàn (sai/thiếu → khiếu nại), bang_chung = cần bằng chứng). KHÔNG lấy tên/username khách.
// KÉO ĐƠN VỀ NHANH (chủ shop cho phép 12/11/2026 — nút DUY NHẤT bot được bấm trên Nhanh, chỉ kéo đơn/trạng thái từ sàn về):
//   https://nhanh.vn/ecommerce/shopee/order  hoặc  https://nhanh.vn/ecommerce/tiktok/order
//   → await __layDonNhanh(["mã đơn sàn", ...])  (Tải đơn › Đơn hàng cụ thể › Tải dữ liệu) → window.__out "ma|ket_qua"
// Kết quả dài: lấy từng khúc  window.__out.slice(i*900, (i+1)*900)  tới khi rỗng, ghép lại.
window.__ngu = ms => new Promise(r => setTimeout(r, ms));

window.__docTikTok = async () => {
  await __ngu(3000);
  const parse = () => {
    const t = document.body.innerText, re = /\b(5[78]\d{16})\b/g, pos = [];
    let m;
    while ((m = re.exec(t))) pos.push([m[1], m.index]);
    return pos.map(([id, i], k) => {
      const seg = t.slice(i, (pos[k + 1] || [0, i + 600])[1]);
      return {ma: id, mvd: '', tt: (seg.match(/Đang chờ vận chuyển|Đang chờ lấy hàng|Chờ lấy hàng/) || [''])[0],
              giao: (seg.match(/Hỏa tốc|Hoả tốc|Giao nhanh 24h|Giao trong ngày|Vận chuyển tiêu chuẩn/) || [''])[0]};
    });
  };
  const all = {};
  for (let p = 0; p < 30; p++) {
    for (const o of parse()) all[o.ma] = o;
    const nx = document.querySelector('.p-pagination-item-next, .core-pagination-item-next, [class*=pagination-item-next]');
    if (!nx || /disabled/.test(nx.className) || nx.getAttribute('aria-disabled') === 'true') break;
    nx.click(); await __ngu(2500);
  }
  const v = Object.values(all);
  window.__out = v.map(o => [o.ma, o.mvd, o.tt, o.giao].join('|')).join('\n');
  return {n: v.length, tong: +((document.body.innerText.match(/Cần gửi\s*(\d+)/) || [])[1] || 0)};
};

window.__docShopee = async () => {
  await __ngu(3500);
  const tatCa = async nhan => {   // bỏ lọc mặc định (Shopee hay tự lọc "Hạn giao hàng hôm nay", "Chưa xử lý")
    const lab = [...document.querySelectorAll('*')].find(e => e.childElementCount < 3 && e.textContent.trim() === nhan);
    let box = lab;
    for (let i = 0; i < 4 && box && !/Tất cả/.test(box.textContent.replace(nhan, '')); i++) box = box.parentElement;
    const opt = box && [...box.querySelectorAll('*')].find(e => e.childElementCount === 0 && e.textContent.trim() === 'Tất cả');
    if (opt) { opt.click(); await __ngu(3000); }
  };
  await tatCa('Trạng thái đơn hàng'); await tatCa('Hạn giao hàng');
  const p1 = document.querySelector('.eds-pager__page');
  if (p1 && !/active/.test(p1.className)) { p1.click(); await __ngu(3000); }
  const parse = () => {
    const t = document.body.innerText, re = /Mã đơn hàng\s*([0-9A-Z]{14})/g, pos = [];
    let m;
    while ((m = re.exec(t))) pos.push([m[1], m.index]);
    return pos.map(([id, i], k) => {
      const seg = t.slice(i, (pos[k + 1] || [0, i + 900])[1]);
      return {ma: id, mvd: (seg.match(/\b(SPXVN\w{8,}|VN\d{9,}\w?|[A-Z]{2,4}\d{8,}\w*)\b/) || [''])[0],
              tt: (seg.match(/Chờ lấy hàng|Chưa xử lý|Đã xử lý/) || [''])[0],
              giao: /Hỏa Tốc|Hoả Tốc|Hỏa tốc|Siêu Tốc|Giao Trong Ngày/.test(seg) ? 'Hỏa tốc' : ''};
    });
  };
  const all = {};
  for (let p = 0; p < 30; p++) {
    for (const o of parse()) all[o.ma] = o;
    const pages = [...document.querySelectorAll('.eds-pager__page')];
    const nx = pages[pages.findIndex(e => /active/.test(e.className)) + 1];
    if (!nx) break;
    nx.click(); await __ngu(3000);
  }
  const v = Object.values(all);
  window.__out = v.map(o => [o.ma, o.mvd, o.tt, o.giao].join('|')).join('\n');
  return {n: v.length, tong: +((document.body.innerText.match(/(\d+) Results/) || [])[1] || 0)};
};

window.__csv = v => v.map(o => [o.ma, o.loai, o.ly_do, o.tt, o.han, o.kv, o.tien, o.nut, o.mvd]
  .map(x => String(x || '').replace(/[|\n]/g, ' ').trim()).join('|')).join('\n');

window.__docHoanTikTok = async () => {
  await __ngu(4000);
  const parse = () => {
    const t = document.body.innerText, re = /ID đơn hàng\s*:\s*(5[78]\d{16})/g, pos = [];
    let m;
    while ((m = re.exec(t))) pos.push([m[1], m.index]);
    return pos.map(([id, i], k) => {
      const s = t.slice(i, (pos[k + 1] || [0, i + 1500])[1]), g = x => (s.match(x) || [])[1] || '';
      return {ma: id, loai: g(/\n(Trả hàng và hoàn tiền|Chỉ hoàn tiền[^\n]*|Đổi hàng[^\n]*)\n/), ly_do: g(/Lý do:([^\n]+)/),
              tt: g(/\n(Đang chờ[^\n]*|Yêu cầu[^\n]*|Đang xem xét[^\n]*|Chờ[^\n]*)\n/), han: g(/\nCòn(?: lại)? ([^\n]+)\n/),
              kv: g(/Trạng thái kho vận trả hàng\n([^\n]+)\n/), tien: g(/Hoàn tiền\n([\d.]+₫)/),
              nut: /\n(Phản hồi|Xem xét|Phê duyệt|Chấp nhận)\n/.test(s) && !/Kháng nghị/.test(s) ? 'phan_hoi' : /Kháng nghị/.test(s) ? 'khang_nghi' : '',
              mvd: ''};
    });
  };
  const all = {};
  let p = 0;
  for (; p < 15; p++) {
    for (const o of parse()) all[o.ma] = o;
    const nx = document.querySelector('.p-pagination-item-next, .core-pagination-item-next, [class*=pagination-item-next]');
    if (!nx || /disabled/.test(nx.className) || nx.getAttribute('aria-disabled') === 'true') break;
    nx.click(); await __ngu(3000);
  }
  const v = Object.values(all);
  window.__out = __csv(v);
  const so = x => +((document.body.innerText.match(x) || [])[1] || 0);
  return {n: v.length, tong: so(/Đang chờ bạn\s*(\d+)/), can_24h: so(/Respond within 24 hours\s*(\d+)|Phản hồi trong vòng 24 giờ\s*(\d+)/)};
};

window.__docHoanShopee = async () => {
  await __ngu(4000);
  const tab = [...document.querySelectorAll('*')].find(e => e.childElementCount === 0 && /^Đơn Trả hàng Hoàn tiền/.test(e.textContent.trim()));
  if (tab) { tab.click(); await __ngu(3000); }
  const parse = () => {
    const t = document.body.innerText, re = /Mã đơn hàng\s*([0-9A-Z]{14})\s*Mã yêu cầu trả hàng\s*([0-9A-Z]{12,18})/g, pos = [];
    let m;
    while ((m = re.exec(t))) pos.push([m[1], m[2], m.index]);
    return pos.map(([id, rq, i], k) => {
      const s = t.slice(i, (pos[k + 1] || [0, 0, i + 1500])[2]), g = x => (s.match(x) || [])[1] || '';
      const pa = s.match(/\n(Trả hàng & Hoàn tiền|Chỉ hoàn tiền|Hoàn tiền ngay)\n([^\n]+)\n/) || [];
      const ld = s.match(/\n-\n([^\n]+)\n-\n(?:Trả hàng & Hoàn tiền|Chỉ hoàn tiền|Hoàn tiền ngay)/) || [];
      const kv = [...s.matchAll(/\n(Đã giao|Chưa lấy hàng|Đang giao[^\n]*|Đang vận chuyển[^\n]*|Đã lấy hàng)\n/g)].map(x => x[1]);
      const tt = pa[2] || '';
      return {ma: id, loai: pa[1] || '', ly_do: (ld[1] || '').replace(/ \(.*\)/, ''), tt, han: g(/trước (\d\d-\d\d-\d{4})/), kv: kv[kv.length - 1] || '',
              tien: g(/Hoàn tiền\n₫([\d.]+)/), mvd: (s.match(/\b(SPXVN\w{8,}|GHN\w{6,}|VN\d{9,}\w?)\b/) || [''])[0],
              nut: /^Chờ bạn/.test(tt) ? 'xac_nhan' : /bằng chứng/i.test(s) ? 'bang_chung' : /đang trả hàng/i.test(tt) ? 'dang_tra' : /^Đã hoàn tiền/.test(tt) ? 'kiem_hang'
                 : /phản hồi/i.test(s) ? 'phan_hoi' : ''};
    });
  };
  const all = {};
  const chips = [...document.querySelectorAll('button')].filter(b => /^(Kiểm tra hàng hoàn|Cần cung cấp bằng chứng|Phản hồi quyết định hoàn tiền của Shopee)\s*\(\d+\)/.test(b.textContent.trim()));
  for (const c of chips) {
    c.click(); await __ngu(3500);
    for (let p = 0; p < 10; p++) {
      for (const o of parse()) all[o.ma] = Object.assign(o, {nut: o.nut || 'phan_hoi'});   // trong chip = đều đang chờ shop
      const pages = [...document.querySelectorAll('.eds-pager__page')];
      const nx = pages[pages.findIndex(e => /active/.test(e.className)) + 1];
      if (!nx) break;
      nx.click(); await __ngu(3000);
    }
    c.click(); await __ngu(2500);   // bỏ chọn chip
  }
  if (!chips.length) for (const o of parse()) if (o.nut) all[o.ma] = o;   // không thấy chip: lấy trang đầu
  const v = Object.values(all);
  window.__out = __csv(v);
  return {n: v.length, tong: +((document.body.innerText.match(/Đơn Trả hàng Hoàn tiền\s*\((\d+)\)/) || [])[1] || 0), chips: chips.length};
};
window.__layDonNhanh = async (mas) => {
  const bam = (re, tag = '*') => { const e = [...document.querySelectorAll(tag)].filter(x => x.childElementCount < 3 && re.test(x.textContent.trim()) && x.offsetParent).pop(); if (e) e.click(); return !!e; };   // phần tử sâu nhất
  await __ngu(3000);
  if (!bam(/^Tải đơn$/, 'button, a, span, div')) return {loi: 'không thấy nút Tải đơn'};
  await __ngu(1500);
  if (!bam(/^Đơn hàng cụ thể$/)) return {loi: 'không thấy tab Đơn hàng cụ thể'};
  await __ngu(1000);
  const ta = [...document.querySelectorAll('textarea')].find(x => x.offsetParent);
  if (!ta) return {loi: 'không thấy ô nhập mã'};
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
  set.call(ta, mas.join('\n')); ta.dispatchEvent(new Event('input', {bubbles: true})); ta.dispatchEvent(new Event('change', {bubbles: true}));
  await __ngu(500);
  const nut = [...document.querySelectorAll('button')].filter(b => /Tải dữ liệu/.test(b.textContent) && b.offsetParent).pop();
  if (!nut) return {loi: 'không thấy nút Tải dữ liệu'};
  nut.click();
  let t = '';
  for (let i = 0; i < 60; i++) {   // tối đa ~2 phút
    await __ngu(2000);
    t = document.body.innerText;
    if (/Cập nhật thành công|Thất bại\s*[1-9]/.test(t) && mas.every(m => t.includes(m))) break;
  }
  const kq = mas.map(m => { const r = t.match(new RegExp(m + '\\s*\\n?\\s*([^\\n]+)')); return m + '|' + (r ? r[1].trim() : '?'); });
  window.__out = kq.join('\n');
  return {n: mas.length, ok: (t.match(/Thành công\s*(\d+)/) || [])[1], loi_sl: (t.match(/Thất bại\s*(\d+)/) || [])[1]};
};
'san sang'

// Tra MÃ TEM HOÀN (kho quét /hoan) → ID đơn gốc, trên trang Trả hàng TikTok (https://seller-vn.tiktok.com/order/return).
// Dùng đúng truy vấn ô tìm kiếm của trang (CHỈ ĐỌC danh sách). codes: mảng mã. Kết quả window.__out "mã|ID đơn" mỗi dòng
// (ID rỗng = không ra; "nhieu:…" = ra nhiều đơn, bot bỏ qua).
window.__traMaHoanTikTok = async (codes) => {
  await __ngu(3000);
  const e = performance.getEntriesByType('resource').map(x => x.name)
    .find(u => /seller-vn\.tiktok\.com\/api\/.*[?&]oec_seller_id=/.test(u));
  if (!e) return {loi: 'không thấy oec_seller_id (trang chưa tải xong / chưa đăng nhập)'};
  const q = new URL(e).searchParams, p = new URLSearchParams();
  for (const k of ['locale', 'language', 'oec_seller_id', 'seller_id', 'aid', 'app_name']) if (q.get(k)) p.set(k, q.get(k));
  const url = '/api/v1/reverse/component/orders/list?' + p, out = {};
  for (const c of codes) {
    const body = {search_condition: {tab: {str_value_list: ['100']}, order_sort_comp: {str_value_list: ['OrderSort_UPADTE_TIME_DESC']},
                  search_numbers: {str_value_list: [c]}}, pagination_type: 0, offset: 0, count: 20, component_version: 'hit_ui_opt'};
    try {
      const j = await (await fetch(url, {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(body),
                                         credentials: 'include'})).json();
      const ids = [...new Set((j.data?.cards || []).map(x => (JSON.stringify(x)
        .match(/"bulk_shipping_popup_print_result_order_id","(\d+)"/) || [])[1]).filter(Boolean))];
      out[c] = ids.length === 1 ? ids[0] : ids.length ? 'nhieu:' + ids.join(',') : '';
    } catch (err) { out[c] = ''; }
    await __ngu(400);
  }
  window.__out = Object.entries(out).map(([k, v]) => k + '|' + v).join('\n');
  return {n: codes.length, ra: Object.values(out).filter(v => /^\d+$/.test(v)).length};
};
