// Chạy TRONG tab nhanh.vn đã đăng nhập (Chrome của chủ shop, qua Claude in Chrome): đọc tồn + đơn 14 ngày
// (TikTok, Shopee, ngoài sàn) rồi gửi vào máy nhận tools/nhan_nhanh.py (127.0.0.1:8765, __TOKEN__ = ~/.config/orbit-kho/nhanh_token)
// → ghi logs/nhanh/ (cùng định dạng với nhanh.py sync). Trả về 1 dòng tóm tắt.
window.__orbitSync = 'DANG_CHAY'; (async () => {
  const BIZ = '199869';
  const csrf = decodeURIComponent((document.cookie.match(/Npos-Csrf-Token-V1=([^;]+)/) || [])[1] || '');
  if (!csrf || location.pathname.startsWith('/login')) return 'CHUA_DANG_NHAP';
  const call = async (path, params) => {
    for (let lan = 0; lan < 3; lan++) {
      try {
        const r = await fetch(path + '?businessId=' + BIZ, {method: 'POST', headers: {'Npos-Csrf-Token-V1': csrf,
          'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded'},
          body: new URLSearchParams(Object.assign({businessId: BIZ}, params))});
        const j = await r.json();
        if (j.code === 1) return j.data || {};
      } catch (e) {}
      await new Promise(s => setTimeout(s, 1500));
    }
    throw new Error('Nhanh lỗi ' + path);
  };
  const pages = async (path, params, max) => {
    let out = [], p = 1, tong = 1;
    while (p <= tong && p <= max) {
      const d = await call(path, Object.assign({page: p}, params));
      out = out.concat(d.result || []); tong = +d.totalPages || 1; p++;
      await new Promise(s => setTimeout(s, 300));
    }
    return out;
  };
  const d = n => { const x = new Date(Date.now() - n * 864e5); return x.toISOString().slice(0, 10); };
  const prods = {};
  for (const x of await pages('/product/item/index', {}, 60)) {
    if (x.code && !x.childCount) prods[x.code] = {ten: x.name, ton: x.remain, trong_kho: x.remainInDepot,
      co_the_ban: x.available, dang_giao: x.shipping, giu: x.holding, loi: x.damaged};
  }
  const KENH = {tiktok: '/ecommerce/tiktok/order', shopee: '/ecommerce/shopee/order', ngoai: '/order/manage/index'};
  const dons = {};
  for (const [k, path] of Object.entries(KENH)) {
    for (const o of await pages(path, {fromDate: d(14), toDate: d(0)}, 80)) {
      const i = o.info || {}, c = o.carrier || {}, ch = o.channel || {};
      dons[String(i.id)] = {id: String(i.id), kenh: k, ma_san: String(ch.apiOrderId || ''), mvd: String(c.carrierCode || ''),
        dvvc: c.name || '', st: i.status, st_ten: i.statusName || '', tao: i.createdDateTime || '',
        cap_nhat: i.updatedDateTime || '', gui_dvvc: c.sendCarrierDate || '', kho: (o.depot || {}).name || '',
        sp: (o.products || []).map(p => ({ma: p.code, sl: p.quantity}))};
    }
  }
  const now = new Date(), pad = n => String(n).padStart(2, '0');
  const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
  const body = JSON.stringify({dong_bo: stamp, products: prods, orders: dons});
  window.__orbitData = body;
  const r = await fetch('http://127.0.0.1:8765/', {method: 'POST', headers: {'Content-Type': 'application/json',
    'X-Orbit-Token': '__TOKEN__'}, body, targetAddressSpace: 'local'});
  if (!r.ok) throw new Error('may nhan tra ' + r.status);
  return `OK ${Object.keys(prods).length} SKU, ${Object.keys(dons).length} don, ${stamp}`;
})().then(r => window.__orbitSync = r).catch(e => window.__orbitSync = 'LOI ' + e.message); 'BAT_DAU'
