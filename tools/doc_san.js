// Đọc danh sách đơn CẦN GỬI trên Seller Center (Claude in Chrome, Chrome chủ shop đã đăng nhập). CHỈ ĐỌC, không bấm nút đơn.
// Chạy nguyên file trong tab:
//   TikTok:  https://seller-vn.tiktok.com/order?selected_sort=6&tab=to_ship   → gọi  await __docTikTok()
//   Shopee:  https://banhang.shopee.vn/portal/sale/order?type=toship&source=all → gọi  await __docShopee()
// Mỗi hàm trả {n, tong} (tong = số sàn hiển thị) và để kết quả CSV ở window.__out ("ma|mvd|tt|giao" mỗi dòng).
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
    const nx = document.querySelector('.p-pagination-item-next');
    if (!nx || /disabled/.test(nx.className)) break;
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
'san sang'
