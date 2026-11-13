#!/usr/bin/env python3
"""Việc thủ kho trên Telegram (nhóm "The Orbit - Kho hàng về & restock"), luồng cố định có nút, không gọi Claude.

  /dathang  đặt lại / chốt SX: mẫu, SL (mặc định 250), size (1:1:1), về (khoảng ngày / "15 ngày") → ghi 02, 05, xuất CSKH
  /hangve   hàng về: dán từng dòng "SKU/mẫu size  bill  thực tế  lỗi" → bot so bill, ghi 03, cộng 02, sửa 05,
            báo thiếu/thừa/lỗi cho chủ shop; nút "Đã báo NCC", "Đã nhập Nhanh (gõ ID phiếu)"
  /chotdi   chốt đơn đi cuối ca: "Sàn  cần gửi  đã đóng  đã bàn giao  huỷ" → ghi 07, chỉ ra lệch
  /chothoan đối soát hàng hoàn 17h: dán danh sách MVĐ sàn báo hoàn → so với kiện kho đã quét /hoan
            → liệt kê kiện shipper chưa trả (đòi shipper) + kiện kho nhận mà sàn không báo
  /kiemkho  kiểm kho: "SKU  tồn Nhanh  đếm thực tế" → ghi 10, chỉ ra lệch; nút "Đã điều chỉnh Nhanh"
  /kho      menu + mẫu chép
Lịch (launchd vn.theorbit.kho-agent.flow, `kho_flow.py hen`): 9:02 gợi ý mẫu kiểm kho hôm nay + kiện sàn báo hoàn
mà chưa nhận; 10:15 đơn huỷ sau in còn trong khay (trước shipper ~10h30); 17:00 nhắc chốt ca (2 mẫu); 18:00 nhắc lại nếu chưa chốt.
Đăng ký vào ticket.py (EXT_CMDS / EXT_CB / EXT_REPLY) nên chạy chung hàng đợi, chung listener kho.
"""
import os, re, subprocess, sys, time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orbit_tg as TG  # noqa: E402
import ticket as TK  # noqa: E402
import nhanh as NH  # noqa: E402  (chỉ đọc cache logs/nhanh/, đồng bộ bằng `nhanh.py sync`)

ROOT = TK.ROOT
NHAP = "03 · NHẬP KHO"
DAT = "02 · HÀNG ĐẶT LẠI"
TINH = "05 · TÌNH TRẠNG HÀNG"
DS = "07 · ĐỐI SOÁT NGÀY"
KIEM = "10 · KIỂM KHO"
KIEM_COLS = ["Ngày", "SKU", "Tên mẫu", "Tồn Nhanh", "Đếm thực tế", "Lệch", "Người kiểm", "Đã điều chỉnh Nhanh", "Đợt"]
SIZES = {"XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "FREE", "F"}
SAN = {"tiktok": "TikTok", "tt": "TikTok", "tts": "TikTok", "shopee": "Shopee", "sp": "Shopee", "spe": "Shopee",
       "web": "Web/Meta", "website": "Web/Meta", "fb": "Web/Meta", "meta": "Web/Meta", "facebook": "Web/Meta"}
KHO_TEN = {"q2": "Kho Tổng Q2", "tổng": "Kho Tổng Q2", "tong": "Kho Tổng Q2",
           "pn": "Kho Cửa hàng PN", "phú nhuận": "Kho Cửa hàng PN", "cửa hàng": "Kho Cửa hàng PN", "ch": "Kho Cửa hàng PN"}
esc, tsend, tedit, answer, ten = TK.esc, TK.tsend, TK.tedit, TK.answer, TK.ten


def kchat():
    return str(TK.E.get("CHAT_ID") or "")


def today():
    return datetime.now().strftime("%Y-%m-%d")


# ======================= SKU =======================

_SKU = {}


def sku_bang():
    """Bảng mã mẫu Nhanh → tên (knowledge/SKU_NHANH.md + SKU.md)."""
    if _SKU:
        return _SKU
    for f in ("SKU_NHANH.md",):
        try:
            for line in open(os.path.join(ROOT, "knowledge", f)):
                m = re.match(r"\|\s*`([^`]+)`\s*\|\s*([^|]+)\|\s*([^|]*)\|", line)
                if m:
                    _SKU[m[1].upper()] = (m[2].strip(), m[3].split())
        except FileNotFoundError:
            pass
    return _SKU


def doc_dong(line):
    """'SO-A4-RIVET-S 20 18 1' / 'DRIFT CAR M 80' / 'SO-A4-RIVET-M 20/18/1' → (mã/tên mẫu, size, [số])."""
    t = line.replace("/", " ").replace("|", " ").replace(":", " ").split()
    nums = []
    while t and re.fullmatch(r"\d+", t[-1]):
        nums.insert(0, int(t.pop()))
    if not t:
        return None
    size = ""
    if len(t) == 1 and "-" in t[0]:
        p = t[0].upper().rsplit("-", 1)
        if p[1] in SIZES:
            return p[0], p[1], nums
        return t[0].upper(), "", nums
    if t[-1].upper() in SIZES:
        size = t.pop().upper()
    return " ".join(t), size, nums


def ten_mau(mau):
    hit = sku_bang().get(mau.upper())
    return hit[0] if hit else mau


def tim_ten(mau):
    """Tên chuẩn Nhanh của mẫu: mã SKU, hoặc mọi chữ của mẫu đều có trong đúng 1 tên (POLO 777 → 777 DENIM POLO)."""
    hit = sku_bang().get(mau.upper())
    if hit:
        return hit[0]
    chu = set(mau.lower().split())
    ten = {v[0] for v in sku_bang().values() if chu <= set(v[0].lower().split())}
    return ten.pop() if len(ten) == 1 else None


def tim_sku(tu, toi_da=6):
    """Mẫu khớp từ khoá (tên hoặc mã, không dấu cũng được). Trả [(mã mẫu, tên, [size])]."""
    import unicodedata
    bo_dau = lambda s: "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn").replace("đ", "d")
    chu = bo_dau(tu).split()
    if not chu:
        return []
    out = []
    for ma, (ten_, sizes) in sku_bang().items():
        hay = bo_dau(ma + " " + ten_)
        if all(c in hay for c in chu):
            out.append((ma, ten_, sizes))
    return out[:toi_da]


def mau_hangve(ds):
    """Mẫu /hangve điền sẵn SKU (chỉ cần gõ số bill + số thực tế)."""
    L = ["/hangve", "NCC: ", "Kho: Q2"]
    for ma, _, sizes in ds:
        for s in (sizes or [""]):
            L.append(f"{ma}-{s}  " if s else f"{ma}  ")
    return "\n".join(L)


def goi_y_sku(chat, reply_to, tu=""):
    if tu:
        ds = tim_sku(tu)
        if not ds:
            return tsend(chat, f"Không thấy mẫu nào khớp \"{esc(tu)}\". Gõ ngắn hơn, VD <code>/hangve rivet</code>.",
                         reply_to=reply_to)
        return tsend(chat, f"📦 Mẫu khớp \"{esc(tu)}\": " + "; ".join(f"{esc(t)}" for _, t, _ in ds)
                     + "\n👇 Bấm vào khung để chép, điền <b>số bill  số thực tế  số lỗi</b> sau mỗi SKU (thiếu lỗi thì bỏ), "
                       "gửi lại:\n<code>" + esc(mau_hangve(ds)) + "</code>", reply_to=reply_to)
    cho = [r for r in TG.rows(DAT) if str(r.get("Trạng thái đặt", "")) not in ("Đã về", "Huỷ", "Hủy", "Đã nhận")]
    nut = [[{"text": f"📦 {str(r.get('Tên sản phẩm'))[:30]}", "callback_data": f"kf:goiy:{str(r.get('Tên sản phẩm'))[:40]}"}]
           for r in cho[:8] if r.get("Tên sản phẩm")]
    tsend(chat, "📦 <b>Hàng về</b>: gõ <code>/hangve tên mẫu</code> (VD <code>/hangve rivet</code>) → bot đưa sẵn mã SKU + size, "
                "chỉ cần điền số."
          + ("\nHoặc bấm hàng đang chờ về:" if nut else ""), nut or None, reply_to=reply_to)


def giai_ma(mau, size):
    """Mẫu kho gõ → (mã mẫu Nhanh | "", tên chuẩn, lỗi). lỗi = "" (ổn) | "size" (mẫu có, size không có) | "khong" (không thấy).
    Thứ tự: mã mẫu đúng · SKU đầy đủ trên Nhanh · tên khớp đúng 1 mẫu."""
    up = mau.upper().strip()
    bang = sku_bang()
    ma = up if up in bang else ""
    if not ma and NH.meta() and NH.ton_sku(f"{up}-{size}" if size else up):
        return up, (NH.ton_sku(f"{up}-{size}" if size else up) or {}).get("ten") or up, ""
    if not ma:
        ten_ = tim_ten(mau)
        ma = next((k for k, v in bang.items() if v[0] == ten_), "") if ten_ else ""
    if not ma:
        return "", mau, "khong"
    sizes = [x.upper() for x in bang[ma][1]]
    if size and sizes and size.upper() not in sizes and not (NH.meta() and NH.ton_sku(f"{ma}-{size}")):
        return ma, bang[ma][0], "size"
    return ma, bang[ma][0], ""


def dang_dat(mau):
    """Mẫu đang có ở 02 (đặt lại/chốt SX) hoặc 05 (sắp mở bán) → mẫu mới chưa có SKU Nhanh vẫn nhận hàng về được."""
    try:
        return any(khop(mau, str(r.get("Tên sản phẩm", ""))) for t in (DAT, TINH) for r in TG.rows(t))
    except Exception:
        return False


def khop(mau, name):
    """Dòng bảng 02/05 (tên) có phải mẫu này không."""
    n = name.lower()
    return mau.lower() in n or ten_mau(mau).lower() in n


# ======================= /hangve =======================

def hangve(m, arg):
    chat, u = m["chat"]["id"], m.get("from") or {}
    who = ten(u)
    ncc, kho, items, bo = "", "Kho Tổng Q2", [], []
    moi_ok = False
    for line in [x.strip() for x in arg.splitlines() if x.strip() and not x.strip().startswith("(")]:
        low = line.lower()
        if low.startswith(("ncc", "xưởng", "xuong", "nhà cung cấp")) and ":" in line:
            ncc = line.split(":", 1)[-1].strip(); continue
        if low.startswith(("mới", "moi", "mẫu mới", "mau moi")) and ":" in line:
            moi_ok = True; continue
        if low.startswith("kho") and ":" in line:
            v = line.split(":", 1)[-1].strip().lower()
            kho = next((k2 for k1, k2 in KHO_TEN.items() if k1 in v), kho); continue
        d = doc_dong(line)
        if d and d[2]:
            items.append(d)
        else:
            bo.append(line)
    if not items:
        tu = " ".join(bo).strip()
        return goi_y_sku(chat, m["message_id"], tu)
    # đối chiếu từng dòng với mã Nhanh: dòng không ra mẫu thì KHÔNG ghi (nhập Nhanh sai mã = lệch tồn), hỏi lại
    chuan, hoi, chua_nh = [], [], []
    for mau, size, nums in items:
        ma, ten_, loi = giai_ma(mau, size)
        if not loi:
            chuan.append((ma, size, nums)); continue
        if loi == "khong" and (moi_ok or dang_dat(mau)):   # mẫu mới (đang đặt/sắp mở bán) chưa có SKU Nhanh
            chuan.append((mau, size, nums)); chua_nh.append(mau); continue
        goi = tim_sku(mau.split()[0] if mau.split() else mau, 3) if loi == "khong" else []
        hoi.append(f"• <code>{esc(mau)} {esc(size)}</code>: " + (
            f"mẫu {esc(ten_)} không có size {esc(size)} trên Nhanh (có: {esc(' '.join(sku_bang()[ma][1]))})" if loi == "size"
            else "không thấy mẫu này trên Nhanh" + (" — có phải: " + ", ".join(f"<code>{esc(k)}</code> {esc(t)}" for k, t, _ in goi) if goi else "")))
    items = chuan
    if hoi:
        tsend(chat, "❓ <b>Chưa ghi các dòng này</b> (không khớp mã Nhanh → nhập Nhanh dễ sai mã, lệch tồn):\n" + "\n".join(hoi)
              + "\n→ Sửa mã/size rồi gửi lại riêng các dòng đó (gõ <code>/hangve tên mẫu</code> để bot đưa sẵn mã). "
                "Mẫu mới chưa tạo trên Nhanh: thêm dòng <code>Mới: có</code>.", reply_to=m["message_id"])
    if not items:
        return
    fid = max(m["photo"], key=lambda x: x.get("file_size", 0))["file_id"] if m.get("photo") else ""
    dot = f"HV{m['message_id']}"
    rows, L = [], []
    tong = {"nhap": 0, "thieu": 0, "thua": 0, "loi": 0}
    for mau, size, nums in items:
        bill = nums[0] if len(nums) >= 2 else None
        thuc = nums[1] if len(nums) >= 2 else nums[0]
        loi = nums[2] if len(nums) >= 3 else 0
        lech = "Chưa có bill" if bill is None else "Khớp" if bill == thuc else "Thiếu" if thuc < bill else "Thừa"
        nhap = thuc - loi
        tong["nhap"] += nhap; tong["loi"] += loi
        if bill is not None:
            tong["thieu"] += max(0, bill - thuc); tong["thua"] += max(0, thuc - bill)
        rows.append({"Tên sản phẩm": ten_mau(mau) + (f" ({mau})" if ten_mau(mau) != mau else ""), "Ngày nhận": today(),
                     "Size/màu": size, "SL theo bill": "" if bill is None else bill, "SL kiểm thực tế": thuc,
                     "SL lỗi QC": loi, "SL nhập kho": nhap, "Lệch bill": lech, "Kho nhận": kho, "Người kiểm": who,
                     "Ghi chú": f"NCC: {ncc}" if ncc else "", "Nguồn tin": dot,
                     "Ảnh bill": "tg:" + fid if fid else ""})
        dau = "✅" if lech in ("Khớp", "Chưa có bill") and not loi else "⚠️"
        L.append(f"{dau} {esc(mau)} {esc(size)}: " + (f"bill {bill} · " if bill is not None else "")
                 + f"thực {thuc}" + (f" · <b>{lech.lower()} {abs(bill - thuc)}</b>" if lech in ("Thiếu", "Thừa") else "")
                 + (f" · <b>lỗi {loi}</b>" if loi else ""))
    ids = TG.kho("add", table=TG.sname(NHAP), rows=rows)
    TG._CACHE.pop(TG.sname(NHAP), None)
    if fid:
        try:
            TG.xem_anh(NHAP, ids[0], "Ảnh bill", TG.download(fid))
        except BaseException as e:
            print("kho_flow: ảnh bill lỗi", e, flush=True)
    cap = cap_nhat_02_05(items, kho)
    van_de = tong["thieu"] or tong["thua"] or tong["loi"]
    t = (f"📦 <b>HÀNG VỀ</b> {datetime.now():%d/%m %H:%M} · {esc(kho)}" + (f" · NCC {esc(ncc)}" if ncc else "")
         + f" · {esc(who)}\n" + "\n".join(L)
         + f"\n\n<b>Nhập kho {tong['nhap']}</b>" + (f" · thiếu {tong['thieu']}" if tong["thieu"] else "")
         + (f" · thừa {tong['thua']}" if tong["thua"] else "") + (f" · lỗi {tong['loi']}" if tong["loi"] else "")
         + (f"\n🔄 {cap}" if cap else "")
         + (f"\n⚠️ Bỏ qua dòng không đọc được: {esc('; '.join(bo))[:200]}" if bo else "")
         + (f"\n🆕 Chưa có mã trên Nhanh: {esc(', '.join(dict.fromkeys(chua_nh)))} → <b>tạo SKU trên Nhanh trước</b> rồi mới nhập kho Nhanh"
            if chua_nh else "")
         + ("\n\n⚠️ Lệch/lỗi: lập biên bản với shipper/NCC, báo NCC trong 2h." if van_de else "")
         + "\n➡️ Nhập Nhanh.vn theo <b>số thực tế</b> rồi bấm nút.")
    TK.STATE_KF[dot] = ids
    TK._save()
    b = ([[{"text": "📝 Đã báo NCC / lập biên bản", "callback_data": f"kf:ncc:{dot}"}]] if van_de else []) + \
        [[{"text": "✅ Đã nhập Nhanh (gõ ID phiếu)", "callback_data": f"kf:nhanh:{dot}"}]]
    tsend(chat, t, b, reply_to=m["message_id"])
    if van_de:
        for o in TK.duyet_ids():
            tsend(o, "⚠️ <b>Hàng về lệch/lỗi</b>\n" + t)


def tinh_05(mau, g, r):
    """Dòng 05 sau hàng về, THEO SIZE: size của dòng (trống = mọi size của mẫu) đều đã có (vừa về hoặc Nhanh còn bán)
    → Còn hàng; về 1 phần → vẫn Còn hàng nhưng CSKH chỉ được nói các size đã có; dòng size khác không về → không sửa."""
    ve = g["sz"]
    dong = {x for x in re.split(r"[\s,/;]+", str(r.get("Size/màu") or "").upper()) if x in SIZES}
    ma = mau.upper() if mau.upper() in sku_bang() else ""
    tat_ca = dong or {x.upper() for x in (sku_bang().get(ma, ("", []))[1] if ma else [])}
    goc = {"Cập nhật lúc": today(), "Ghi chú kho": f"Về {datetime.now():%d/%m}: {' '.join(g['size']) or g['sl']}"}
    if not ve or not tat_ca:   # kho không ghi size / không biết mẫu có size gì → như cũ
        return dict(goc, **{"Tình trạng": "Còn hàng", "Hàng về dự kiến": "",
                            "CSKH được nói": "Mẫu này shop đã có hàng, bạn chốt size để shop lên đơn nha"})
    if dong and not (dong & ve):
        return None
    con_ban = {x for x in tat_ca - ve if ma and NH.meta() and ((NH.ton_sku(f"{ma}-{x}") or {}).get("co_the_ban") or 0) > 0}
    co = (tat_ca & ve) | con_ban
    thieu = tat_ca - co
    thu = [x for x in ("XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "FREE", "F") if x in co]
    if not thieu:
        return dict(goc, **{"Tình trạng": "Còn hàng", "Hàng về dự kiến": "",
                            "CSKH được nói": f"Mẫu này shop đã có hàng size {', '.join(thu)}, bạn chốt size để shop lên đơn nha"})
    tx = [x for x in ("XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "FREE", "F") if x in thieu]
    return dict(goc, **{"Tình trạng": "Còn hàng", "_thieu": " ".join(tx),
                        "Ghi chú kho": goc["Ghi chú kho"] + f" · size {' '.join(tx)} chưa có",
                        "CSKH được nói": f"Mẫu này shop đã có lại size {', '.join(thu)}; size {', '.join(tx)} chưa có hàng, "
                                         "shop báo bạn khi về nha"})


# ======================= đối chiếu PHIẾU NHẬP NHANH (tự tick "Đã nhập Nhanh", bắt nhập sai số) =======================

NHAP_ST = os.path.join(ROOT, "logs", "nhap_nhanh.json")


def phieu_nhap(tu):
    """Phiếu nhập kho Nhanh từ ngày tu (Open API, chỉ đọc). None = không có API."""
    import nhanh_api as NA
    return NA.phieu_nhap(tu) if NA.co_api() else None


def sku_dong(r):
    """Dòng 03 → ({SKU: SL nhập kho}, {SKU: SL lỗi}). Tên 'ARCHIVE TEE (TS-D2-ARCHIVE)' + size, hoặc 'M 50, L 98'."""
    ten_ = str(r.get("Tên sản phẩm") or "")
    m = re.search(r"\(([A-Z0-9]+(?:-[A-Z0-9]+)+)\)", ten_)
    ma = m[1] if m else (giai_ma(ten_, "")[0] or "")
    if not ma:
        return {}, {}
    sz = str(r.get("Size/màu") or "").upper()
    cap = re.findall(r"(?<![A-Z0-9])(XXL|2XL|3XL|XS|XL|FREE|S|M|L|F)\s+(\d+)", sz)
    if cap:
        return {f"{ma}-{x}": int(n) for x, n in cap}, {}
    x = next((t for t in reversed(re.split(r"[\s,/;]+", sz)) if t in SIZES), "")
    k = f"{ma}-{x}" if x else ma
    n = int(TK.tien(r.get("SL nhập kho")) or 0)
    return ({k: n} if n else {}), {k: int(TK.tien(r.get("SL lỗi QC")) or 0)}


def doi_chieu_nhap(send=False):
    """Dòng 03 chưa tick 'Đã nhập Nhanh' (14 ngày) ↔ phiếu nhập Nhanh. Khớp đủ SKU + SL → tự tick; cùng SKU mà khác SL
    → báo lệch 1 lần (tồn Nhanh đang sai). Trả text đã/sẽ gửi."""
    import json
    han = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    tat = TG.rows(NHAP, fresh=True)
    cho = [r for r in tat if not r.get("Đã nhập Nhanh.vn") and str(r.get("Ngày nhận") or "") >= han]
    if not cho:
        return ""
    tu = (datetime.strptime(min(str(r.get("Ngày nhận"))[:10] for r in cho), "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    bills = phieu_nhap(tu)
    if bills is None:
        return ""
    dung = set()   # (phiếu, SKU) đã gán cho dòng đã tick
    for r in tat:
        if r.get("Đã nhập Nhanh.vn"):
            for bid in re.findall(r"\d{4,}", str(r.get("ID phiếu nhập Nhanh") or "")):
                dung |= {(bid, k) for k in sku_dong(r)[0]}
    try:
        st = json.load(open(NHAP_ST))
    except Exception:
        st = {}
    lo = {}
    for r in cho:
        lo.setdefault(str(r.get("Nguồn tin") or f"{r.get('Ngày nhận')}·{r.get('Tên sản phẩm')}"), []).append(r)
    ok, lech = [], []
    for key, rs in lo.items():
        can, loi = {}, {}
        for r in rs:
            a, b = sku_dong(r)
            for k, v in a.items():
                can[k] = can.get(k, 0) + v
            for k, v in b.items():
                loi[k] = loi.get(k, 0) + v
        if not can:
            continue
        ngay = (datetime.strptime(min(str(r.get("Ngày nhận"))[:10] for r in rs), "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        bs = [b for b in bills if b["ngay"] >= ngay]
        hop = None
        for b in bs:   # 1 phiếu có đủ mọi SKU của lô
            if all(k in b["sp"] and (b["id"], k) not in dung for k in can):
                diff = {k: b["sp"][k] for k, v in can.items() if b["sp"][k] != v}
                if not diff:
                    hop = ([b["id"]], {}); break
                hop = hop or ([b["id"]], diff)
        if not hop or hop[1]:   # lô chia nhiều phiếu: mỗi SKU khớp đúng SL ở 1 phiếu
            ids = []
            for k, v in can.items():
                b = next((b for b in bs if b["sp"].get(k) == v and (b["id"], k) not in dung), None)
                if not b:
                    ids = []; break
                ids.append(b["id"])
            if ids:
                hop = (list(dict.fromkeys(ids)), {})
        if not hop:
            continue
        ids, diff = hop
        ten_ = ", ".join(dict.fromkeys(re.sub(r"\s*\([^)]*\)\s*$", "", str(r.get("Tên sản phẩm") or "")) for r in rs))
        if not diff:
            for r in rs:
                TG.kho("update", table=TG.sname(NHAP), id=r["_id"],
                       fields={"Đã nhập Nhanh.vn": "✓", "ID phiếu nhập Nhanh": ", ".join(ids) + " (bot đối chiếu)"})
            dung |= {(i, k) for i in ids for k in can}
            ok.append(f"• {esc(ten_)} về {str(rs[0].get('Ngày nhận'))[8:10]}/{str(rs[0].get('Ngày nhận'))[5:7]}: "
                      f"phiếu <code>{', '.join(ids)}</code> — {sum(can.values())} cái khớp")
            st.pop(key, None)
            continue
        dau = json.dumps([ids, diff], sort_keys=True)
        if st.get(key) == dau:
            continue   # đã báo lệch này rồi
        st[key] = dau
        lech.append(f"• {esc(ten_)} · phiếu <code>{ids[0]}</code>: " + "; ".join(
            f"{esc(k)} Nhanh <b>{nb}</b> ≠ kho kiểm <b>{can[k]}</b>"
            + (" (Nhanh nhập cả hàng lỗi QC?)" if loi.get(k) and nb == can[k] + loi[k] else "") for k, nb in diff.items()))
    TG._CACHE.pop(TG.sname(NHAP), None)
    os.makedirs(os.path.dirname(NHAP_ST), exist_ok=True)
    json.dump(st, open(NHAP_ST, "w"), ensure_ascii=False, indent=1)
    L = []
    if ok:
        L.append("✅ <b>Bot đã đối chiếu phiếu nhập Nhanh</b> (khớp số kho kiểm, tự tick Đã nhập Nhanh):\n" + "\n".join(ok))
    if lech:
        L.append("⚠️ <b>PHIẾU NHẬP NHANH LỆCH SỐ KHO KIỂM</b> → tồn Nhanh đang sai, sửa phiếu trên Nhanh theo <b>số thực tế</b> "
                 "(hàng lỗi QC không nhập vào tồn bán):\n" + "\n".join(lech))
    t = "\n\n".join(L)
    if t:
        print(re.sub(r"<[^>]+>", "", t))
        if send and kchat():
            tsend(kchat(), t)
    return t


def kiem_id_phieu(rids, t):
    """Kho gõ ID phiếu nhập: so phiếu đó với các dòng 03 vừa tick. Trả 1 dòng ghi chú ("" nếu không kiểm được)."""
    ids = re.findall(r"\d{4,}", t)
    rs = [r for r in TG.rows(NHAP, fresh=True) if r.get("_id") in set(rids)]
    if not ids or not rs:
        return ""
    try:
        bills = phieu_nhap((datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d"))
    except Exception as e:
        print("kho_flow: đọc phiếu nhập lỗi", repr(e)[:200], flush=True)
        return ""
    if bills is None:
        return ""
    sp = {}
    for b in bills:
        if b["id"] in ids:
            for k, v in b["sp"].items():
                sp[k] = sp.get(k, 0) + v
    if not sp:
        return f"\n⚠️ Không thấy phiếu nhập <code>{esc(', '.join(ids))}</code> trên Nhanh (14 ngày) — gõ đúng ID chưa?"
    can = {}
    for r in rs:
        for k, v in sku_dong(r)[0].items():
            can[k] = can.get(k, 0) + v
    sai = [f"{esc(k)} Nhanh {sp.get(k, 0)} ≠ kho {v}" for k, v in can.items() if sp.get(k, 0) != v]
    return ("\n⚠️ <b>Phiếu Nhanh lệch số kho kiểm</b>: " + "; ".join(sai) + " → sửa phiếu theo số thực tế") if sai \
        else "\n🔎 Bot đã đối chiếu: phiếu Nhanh khớp số kho kiểm."


def cap_nhat_02_05(items, kho):
    """Cộng SL đã nhận vào 02, chuyển 05 sang Còn hàng, xuất file tình trạng cho CSKH. Trả câu tóm tắt."""
    out = []
    try:
        gom = {}
        for mau, size, nums in items:
            thuc = nums[1] if len(nums) >= 2 else nums[0]
            loi = nums[2] if len(nums) >= 3 else 0
            g = gom.setdefault(mau, {"sl": 0, "size": [], "sz": set()})
            g["sl"] += thuc - loi
            if size:
                g["size"].append(f"{size}{thuc - loi}")
                if thuc - loi > 0:
                    g["sz"].add(size.upper())
        for mau, g in gom.items():
            for r in TG.rows(DAT, fresh=True):
                if khop(mau, str(r.get("Tên sản phẩm", ""))) and r.get("Trạng thái đặt") not in ("Đã về đủ", "Huỷ"):
                    da = TK.tien(r.get("SL đã nhận")) + g["sl"]
                    dat = TK.tien(r.get("SL đặt"))
                    st = "Đã về đủ" if dat and da >= dat else "Về 1 phần"
                    TG.kho("update", table=TG.sname(DAT), id=r["_id"],
                           fields={"SL đã nhận": da, "Trạng thái đặt": st, "Đã về đủ": "✓" if st == "Đã về đủ" else "",
                                   "Kho nhận": kho})
                    out.append(f"02: {r.get('Tên sản phẩm')} {da}/{dat or '?'}")
                    break
            for r in TG.rows(TINH, fresh=True):
                if not khop(mau, str(r.get("Tên sản phẩm", ""))):
                    continue
                f = tinh_05(mau, g, r)
                if f:
                    thieu = f.pop("_thieu", "")
                    TG.kho("update", table=TG.sname(TINH), id=r["_id"], fields=f)
                    out.append(f"05: {r.get('Tên sản phẩm')} {r.get('Size/màu') or ''} → {f['Tình trạng']}"
                               + (f" (size {thieu} chưa có)" if thieu else ""))
        TG._CACHE.clear()
        if out:
            subprocess.run([sys.executable, os.path.join(ROOT, "tools", "lark.py"), "export"], cwd=ROOT,
                           capture_output=True, timeout=120)
    except BaseException as e:
        print("kho_flow: cập nhật 02/05 lỗi", e, flush=True)
    return " · ".join(out)


# ======================= /dathang =======================

def ve_khoang(v):
    """'22-25/11' / '22/11' / '15 ngày' / 'sx 15 ngày' → (ngày ISO bắt đầu, 'dd–dd/mm') hoặc (None, '')."""
    v = v.strip().lower()
    m = re.search(r"(\d+)\s*ngày", v)
    if m:
        a = datetime.now() + timedelta(days=int(m[1]))
        b = a + timedelta(days=3)
        return a.strftime("%Y-%m-%d"), (f"{a:%d}–{b:%d/%m}" if a.month == b.month else f"{a:%d/%m}–{b:%d/%m}")
    m = re.search(r"(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\s*/\s*(\d{1,2})", v)
    if m:
        nam = datetime.now().year
        try:
            a = datetime(nam, int(m[3]), int(m[1]))
        except ValueError:
            return None, ""
        if a < datetime.now() - timedelta(days=60):
            a = a.replace(year=nam + 1)
        return a.strftime("%Y-%m-%d"), (f"{m[1]}–{m[2]}/{m[3]}" if m[2] else f"{m[1]}/{m[3]}")
    return None, ""


def dathang(m, arg):
    """Đặt lại / chốt SX: ghi 02 mỗi mẫu 1 dòng, cập nhật 05 cho CSKH, xuất file. Mặc định 250/mẫu, M:L:XL 1:1:1."""
    chat, who = m["chat"]["id"], ten(m.get("from"))
    maus, sl, size, ve, nguoi, ghi, loai = [], 250, "M:L:XL = 1:1:1", "", "", "", ""
    lines = [x.strip() for x in arg.splitlines() if x.strip() and not x.strip().startswith("(")]
    if len(lines) == 1 and ":" not in lines[0]:   # 1 dòng: /dathang AURA 250 về 20-22/11
        t = lines[0]
        mv = re.search(r"\b(về|ve|sx)\b(.*)$", t, re.I)
        if mv:
            ve, t = mv[2], t[:mv.start()]
        ms = list(re.finditer(r"\b(\d{2,4})\b", t))   # số cuối = SL (tên mẫu có thể có số, vd POLO 777)
        if ms and (len(ms) > 1 or t[ms[-1].end():].strip() == ""):
            sl, t = int(ms[-1][1]), (t[:ms[-1].start()] + t[ms[-1].end():])
        maus = [x.strip() for x in re.split(r",| và | va ", t) if x.strip()]
    else:
        for line in lines:
            k, _, v = line.partition(":")
            k, v = k.strip().lower(), v.strip()
            if k.startswith(("mẫu", "mau", "sp", "sản phẩm")):
                maus += [x.strip() for x in re.split(r",| và | va ", v) if x.strip()]
            elif k.startswith(("sl", "số lượng")):
                sl = TK.tien(re.sub(r"[^\d]", "", v)) or sl
            elif k.startswith("size"):
                size = v or size
            elif k.startswith(("về", "ve", "sx", "ngày về")):
                ve = v
            elif k.startswith(("người", "nguoi", "nhận", "phụ trách")):
                nguoi = v.lstrip("@")
            elif k.startswith(("loại", "loai")):
                loai = v
            elif k.startswith(("ghi chú", "ghi chu")):
                ghi = v
    if not maus:
        return tsend(chat, "Chưa đọc được mẫu nào. Mẫu:\n" + MAU["dathang"], reply_to=m["message_id"])
    ngay_ve, khoang = ve_khoang(ve) if ve else (None, "")
    tinh = TG.rows(TINH, fresh=True)
    L, cap05 = [], []
    for mau in maus:
        chuan = tim_ten(mau)
        ten_ = chuan or mau.upper()
        dong05 = next((r for r in tinh if khop(ten_, str(r.get("Tên sản phẩm", ""))) or
                       khop(mau, str(r.get("Tên sản phẩm", "")))), None)
        da_ban = chuan is not None
        moi = loai.lower().startswith(("sx", "mới", "moi")) if loai else (dong05 is None and not da_ban)
        TG.kho("add", table=TG.sname(DAT), rows=[{
            "Tên sản phẩm": ten_, "SL đặt": sl, "Màu / Size": size, "Ngày đặt": today(),
            "Hẹn hàng về": ngay_ve or "", "Trạng thái đặt": "Đang SX", "Người phụ trách": nguoi or who,
            "Vướng mắc": "; ".join(x for x in (("Mẫu mới chốt SX" if moi else "Đặt lại"),
                                               f"về dự kiến {khoang}" if khoang else "chưa có ngày về", ghi) if x),
            "Nguồn tin": f"tg:{m['message_id']} {who} {datetime.now():%d/%m}"}])
        L.append(f"• <b>{esc(ten_)}</b>: {sl} cái · {esc(size)}" + (f" · về {esc(khoang)}" if khoang else ""))
        ve05 = khoang or "chưa có ngày"
        if dong05 is None:
            TG.kho("add", table=TG.sname(TINH), rows=[{
                "Tên sản phẩm": ten_, "Size/màu": "M, L, XL", "Tình trạng": "Sắp mở bán" if moi else "Sắp hết",
                "Hàng về dự kiến": ve05,
                "CSKH được nói": "Mẫu này shop đang sản xuất, có hàng shop báo ngay, bạn theo dõi shop nha" if moi else
                                 "Size nào đang hết shop đang về thêm hàng, có hàng shop báo ngay, bạn theo dõi shop nha",
                "Cập nhật lúc": today(), "Ghi chú kho": f"Đặt {sl} ngày {datetime.now():%d/%m}"}])
            cap05.append(f"{ten_} → {'Sắp mở bán' if moi else 'Sắp hết, chờ hàng'}")
        else:
            f = {"Hàng về dự kiến": ve05, "Cập nhật lúc": today(),
                 "Ghi chú kho": f"Đặt lại {sl} ngày {datetime.now():%d/%m}"}
            if dong05.get("Tình trạng") in ("Hết - chờ restock", "Hết - không restock", ""):
                f |= {"Tình trạng": "Hết - chờ restock",
                      "CSKH được nói": "Mẫu này shop đang về thêm hàng, có hàng shop báo ngay, bạn theo dõi shop nha"}
            TG.kho("update", table=TG.sname(TINH), id=dong05["_id"], fields=f)
            cap05.append(f"{dong05.get('Tên sản phẩm')} → về {ve05}")
    st = dh_st()
    for mau in maus:
        ma = mau.upper() if mau.upper() in sku_bang() else next((k for k, v in sku_bang().items() if v[0] == tim_ten(mau)), None)
        if ma:
            st.setdefault(ma, {}).update(tt="da_dat", luc=today(), ai=who)
    dh_luu(st)
    TG._CACHE.clear()
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "lark.py"), "export"], cwd=ROOT,
                   capture_output=True, timeout=120)
    tsend(chat, f"🧵 <b>ĐẶT HÀNG</b> {datetime.now():%d/%m} · {esc(who)}" + (f" · nhận: {esc(nguoi)}" if nguoi else "")
          + "\n" + "\n".join(L) + f"\n🔄 02 đã ghi · 05: {esc('; '.join(cap05))} (CSKH đã thấy)"
          + ("" if khoang else "\n⚠️ Chưa có ngày về: gõ lại kèm <code>Về: 22-25/11</code> hoặc <code>Về: 15 ngày</code>")
          + "\n➡️ Hàng về thì <code>/hangve</code>, bot tự cộng vào đơn đặt này.", reply_to=m["message_id"])


# ======================= /chotdi =======================

def chotdi(m, arg):
    chat, who = m["chat"]["id"], ten(m.get("from"))
    L, lech_all = [], []
    for line in [x for x in arg.splitlines() if x.strip()]:
        t = line.replace(":", " ").replace("/", " ").split()
        if not t or t[0].lower() not in SAN:
            continue
        san = SAN[t[0].lower()]
        so = [int(x) for x in t[1:] if x.isdigit()]
        if len(so) == 1:  # chỉ số kiện bàn giao thực tế → so với Nhanh
            L.append(so_voi_nhanh(san, so[0], who)); lech_all += ["x"] if "⚠️" in L[-1] else []
            continue
        n = so + [0, 0, 0, 0]
        can, dong, giao, huy = n[:4]
        if not (can or dong or giao or huy):
            continue
        chua_dong = max(0, can - huy - dong)
        chua_giao = max(0, dong - giao)
        lech = []
        if chua_dong:
            lech.append(f"{chua_dong} đơn chưa đóng")
        if chua_giao:
            lech.append(f"{chua_giao} đơn đóng rồi chưa bàn giao")
        ghi = "; ".join(lech) or "khớp"
        key = f"{today()} - {san}"
        old = [r for r in TG.rows(DS, fresh=True) if r.get("Ngày - Sàn") == key]
        f = {"Ngày - Sàn": key, "Ngày": today(), "Sàn": san, "Đơn cần gửi": can, "Đã đóng": dong,
             "Đã bàn giao ĐVVC": giao, "Lệch/ghi chú": ghi + (f"; huỷ {huy}" if huy else ""), "Người làm": who}
        if old:
            TG.kho("update", table=TG.sname(DS), id=old[0]["_id"], fields=f)
        else:
            TG.kho("add", table=TG.sname(DS), rows=[f])
        L.append(f"{'✅' if not lech else '⚠️'} <b>{san}</b>: cần {can} · đóng {dong} · giao {giao}"
                 + (f" · huỷ {huy}" if huy else "") + (f"\n   → <b>{'; '.join(lech)}</b>" if lech else ""))
        lech_all += lech
    TG._CACHE.pop(TG.sname(DS), None)
    if not L:
        return tsend(chat, "Chưa đọc được dòng nào. Mẫu:\n" + MAU["chotdi"], reply_to=m["message_id"])
    t = f"🚚 <b>CHỐT ĐƠN ĐI</b> {datetime.now():%d/%m} · {esc(who)}\n" + "\n".join(L)
    if lech_all:
        t += "\n\nTìm mã đơn lệch ngay trong ca (Nhanh.vn ↔ Seller Center), xong bấm nút."
    tsend(chat, t, [[{"text": "🔍 Đã xử lý đơn lệch (gõ ghi chú)", "callback_data": f"kf:lechdi:{today()}"}]]
          if lech_all else None, reply_to=m["message_id"])


NH_KENH = {"TikTok": "tiktok", "Shopee": "shopee", "Web/Meta": "ngoai"}


def so_voi_nhanh(san, giao, who):
    cc = NH.chot_ca().get(NH_KENH.get(san), {"chua_gui": [], "gui_hom_nay": 0})
    nh = cc["gui_hom_nay"]
    chua = len(cc["chua_gui"])
    lech = giao - nh
    ghi = ("khớp Nhanh" if not lech else f"bàn giao {giao} ≠ Nhanh {nh}") + (f"; còn {chua} đơn chưa gửi" if chua else "")
    key = f"{today()} - {san}"
    f = {"Ngày - Sàn": key, "Ngày": today(), "Sàn": san, "Đơn cần gửi": nh + chua, "Đã bàn giao ĐVVC": giao,
         "Lệch/ghi chú": ghi, "Người làm": who}
    old = [r for r in TG.rows(DS, fresh=True) if r.get("Ngày - Sàn") == key]
    TG.kho("update", table=TG.sname(DS), id=old[0]["_id"], fields=f) if old else TG.kho("add", table=TG.sname(DS), rows=[f])
    return (f"{'✅' if not lech and not chua else '⚠️'} <b>{san}</b>: bàn giao {giao} · Nhanh ghi gửi ĐVVC hôm nay {nh}"
            + (f"\n   → <b>lệch {'+' if lech > 0 else ''}{lech}</b>" if lech else "")
            + (f"\n   → còn <b>{chua}</b> đơn chưa gửi" if chua else ""))


def bao_nhanh_chot_ca():
    """Khối tóm tắt từ Nhanh cho tin 17h."""
    if not NH.con_moi(120):
        return ""
    L = [f"📊 <b>Nhanh.vn</b> (cập nhật {NH.meta().get('dong_bo', '')[11:]}):"]
    for k, v in NH.chot_ca().items():
        if not v["chua_gui"] and not v["gui_hom_nay"]:
            continue
        cg = v["chua_gui"]
        L.append(f"• {NH.TEN_KENH.get(k, k)}: gửi ĐVVC hôm nay <b>{v['gui_hom_nay']}</b>"
                 + (f" · <b>còn {len(cg)} đơn chưa gửi</b>: " + ", ".join(f"{o['ma_san'] or o['id']} ({o['st_ten']})"
                                                                     for o in cg[:6]) + ("…" if len(cg) > 6 else "")
                    if cg else " · hết đơn chờ"))
    return "\n".join(L)


BAT_DAU_HOAN = "2026-11-11"   # ngày kho bắt đầu quét /hoan — đơn gửi trước ngày này gom riêng "kiểm 1 lần"


def _ds_ma(xs, n=30):
    return "\n".join(f"• <code>{esc(o['mvd'] or o['ma_san'])}</code> {NH.TEN_KENH.get(o['kenh'], '')} {esc(o['st_ten'])}"
                     + (f" ({esc(o['dvvc'])})" if o.get("dvvc") else "") for o in xs[:n]) + (f"\n… và {len(xs) - n} đơn nữa" if len(xs) > n else "")


def doi_soat_hoan_nhanh():
    """So hàng hoàn trên Nhanh với kiện kho đã quét /hoan. Trả (text, số cần đòi/kiểm).
    2 loại: (1) hoàn ĐVVC/giao thất bại — kiện về với MVĐ gửi; (2) khách trả hàng — tem hoàn MỚI, Nhanh tạo đơn trả
    '<mã sàn>R'. Mã tem hoàn → đơn gốc qua sổ logs/ma_hoan.json (tác vụ lịch tra trên sàn)."""
    if not NH.con_moi(120):
        return "", 0
    quet = {}
    for r in TG.rows(TK.HOAN, fresh=True):
        if not r.get("Người nhận"):
            continue
        m = NH.chuan_ma(r.get("MVĐ"))
        for k in (m, NH.goc_hoan(m).lower()):
            if k:
                quet[k] = r
    khop = set()

    def thay(o):
        for k in (o["mvd"].lower(), o["ma_san"].lower(), o["ma_san"].lower()[:-1] if o["ma_san"].endswith("R") else "", o["id"]):
            if k and k in quet:
                khop.add(quet[k]["_id"])
                return True
        return False

    def gui(o):
        return (o["gui_dvvc"] or o["tao"])[:10]

    dvvc = NH.hang_hoan()
    chua = [o for o in dvvc if not thay(o)]
    moi = sorted([o for o in chua if gui(o) >= BAT_DAU_HOAN], key=gui)
    cu = [o for o in chua if gui(o) < BAT_DAU_HOAN]
    tra = [o for o in NH.don_tra() if o["tao"][:10] >= BAT_DAU_HOAN]
    tra_chua = [o for o in tra if not thay(o)]
    # kiện kho đã quét (từ ngày bắt đầu) mà không khớp đơn hoàn nào trên Nhanh
    le, nhanh_chua, nt = [], [], NH.nhap_tra()
    r_goc = {x["ma_san"][:-1] for x in NH.don_tra(30)}
    for r in TG.rows(TK.HOAN, fresh=True):
        if not r.get("Người nhận") or r["_id"] in khop or str(r.get("Ngày") or "")[:10] < BAT_DAU_HOAN:
            continue
        if NH.goc_hoan(r.get("MVĐ")) in r_goc:      # tem hoàn đã tra ra đơn sàn, đơn đó Nhanh đã nhập trả (R)
            continue
        o = NH.don_theo_ma(r.get("MVĐ"))
        if o and o["st"] not in NH.HOAN_ST and o["id"] not in nt and o["ma_san"] not in r_goc:
            nhanh_chua.append((r, o))
        elif not o:
            le.append(r)
    L = [f"↩️ <b>Hàng hoàn (Nhanh ↔ kho quét /hoan)</b> — tính từ {BAT_DAU_HOAN[8:]}/{BAT_DAU_HOAN[5:7]}"]
    n_dv = len([o for o in dvvc if gui(o) >= BAT_DAU_HOAN])
    da_ve = [o for o in moi if o["st"] == 72]          # Nhanh ghi "Đã chuyển hoàn"
    dang_ve = [o for o in moi if o["st"] != 72]        # Đang chuyển hoàn / Xác nhận hoàn / Thất bại
    L.append(f"📦 <b>Hoàn ĐVVC / giao thất bại</b>: Nhanh {n_dv} · kho đã quét {n_dv - len(moi)}"
             + (f" · <b>chưa quét {len(moi)}</b>" if moi else " ✅"))
    if da_ve:
        L.append(f"  Nhanh ghi <b>Đã chuyển hoàn</b> mà kho chưa /hoan ({len(da_ve)}) → kiện trên kệ chưa? có thì quét:\n" + _ds_ma(da_ve))
    if dang_ve:
        L.append(f"  Đang trên đường về / mới xác nhận hoàn ({len(dang_ve)}) → shipper trả thì quét; quá 7 ngày chưa về thì đòi ĐVVC:\n"
                 + _ds_ma(dang_ve))
    if tra:
        L.append(f"🔁 <b>Khách trả hàng</b>: kho đã nhập trả trên Nhanh {len(tra)} đơn (tồn Nhanh đã cộng lại)"
                 + (f" · <b>{len(tra_chua)} đơn chưa có /hoan</b> → CSKH chưa có tình trạng kiện (lần sau: quét <code>/hoan</code> tem hoàn trước, rồi mới nhập Nhanh)"
                    if tra_chua else " · /hoan đủ ✅"))
    if nhanh_chua:
        L.append(f"⚠️ <b>Kho đã nhận {len(nhanh_chua)} kiện mà Nhanh chưa nhập trả</b> (tồn Nhanh đang thiếu) → vào Nhanh nhập trả:\n"
                 + "\n".join(f"• <code>{esc(r.get('MVĐ'))}</code> → đơn {esc(o['ma_san'] or o['id'])} "
                              f"{NH.TEN_KENH.get(o['kenh'], '')} ({esc(o['st_ten'])})" for r, o in nhanh_chua[:20]))
    if le:
        L.append(f"❔ {len(le)} kiện kho quét chưa ra đơn Nhanh (tem hoàn Shopee/TikTok bot tra trên sàn lúc 8h30 + 15h30; còn lại là đơn gửi trước 14 ngày): "
                 + ", ".join(f"<code>{esc(r.get('MVĐ'))}</code>" for r in le[:15]) + ("…" if len(le) > 15 else ""))
    if cu:
        L.append(f"🗂 <b>{len(cu)} đơn hoàn gửi trước {BAT_DAU_HOAN[8:]}/{BAT_DAU_HOAN[5:7]}</b> (trước khi có /hoan) chưa quét → "
                 "kiểm kệ hàng hoàn 1 lần: có kiện thì <code>/hoan MVĐ</code>, không có thì báo trưởng kho:\n" + _ds_ma(cu, 15))
    if moi:
        L.append("Shipper trả kiện nào thì quét <code>/hoan MVĐ</code> (tem hoàn hay tem gửi đều được); kiện không về → đòi shipper / ĐVVC.")
    return "\n".join(L), len(moi) + len(nhanh_chua)


def ma_hoan_can(ngay=14):
    """Mã kho quét /hoan (≤ `ngay` ngày) chưa ra đơn Nhanh và chưa có trong sổ tem hoàn → {"tiktok": [...], "shopee": [...]}."""
    tu = (datetime.now() - timedelta(days=ngay)).strftime("%Y-%m-%d")
    out = {"tiktok": [], "shopee": []}
    for r in TG.rows(TK.HOAN, fresh=True):
        m = NH.chuan_ma(r.get("MVĐ")).upper()
        if not m or str(r.get("Ngày") or "")[:10] < tu or NH.goc_hoan(m) or NH.don_theo_ma(m):
            continue
        k = "shopee" if m.startswith(("SPXVN", "VN")) else "tiktok" if re.fullmatch(r"\d{9,15}", m) else ""
        if k and m not in out[k]:
            out[k].append(m)
    return out


def canh_bao_nhap(ngay=14, cover=7, toi_thieu=5):
    """Từ Nhanh: SKU sắp cháy (tồn bán được < `cover` ngày theo tốc độ bán 14 ngày) và SKU nên xả (tồn nhiều, 14 ngày
    không bán). Giống báo cáo "Cảnh báo nhập hàng ngay / Cảnh báo SKU cần xả tồn" của Base kho KB Group."""
    if not NH.con_moi(240):
        return ""
    ban = {}
    for o in NH.orders().values():
        if o["st"] in (58, 63, 64):  # huỷ
            continue
        for x in o["sp"]:
            ban[x["ma"]] = ban.get(x["ma"], 0) + int(x.get("sl") or 0)
    chay, xa = [], []
    for ma, p in NH.products().items():
        if ma.startswith(("TEST", "PK-A0-STICKER", "CB-")):  # combo: tồn tính theo SP con
            continue
        sl, ton = ban.get(ma, 0), int(p.get("co_the_ban") or 0)
        if sl >= toi_thieu:
            ngay_con = ton / (sl / ngay)
            if ngay_con < cover:
                chay.append((ngay_con, ma, ton, sl))
        elif sl == 0 and int(p.get("trong_kho") or 0) >= 50:
            xa.append((int(p.get("trong_kho") or 0), ma))
    chay.sort(); xa.sort(reverse=True)
    t = ""
    if chay:
        t += (f"🔥 <b>Sắp cháy hàng</b> (bán {ngay} ngày, còn bán được < {cover} ngày):\n"
              + "\n".join(f"• {esc(ma)}: còn {ton}, bán {sl}/{ngay}n → <b>~{d:.0f} ngày</b>" for d, ma, ton, sl in chay[:15]))
    if xa:
        t += ("\n\n🧊 <b>Tồn nhiều, {0} ngày không bán</b> (cân nhắc xả/đẩy ads):\n".format(ngay)
              + "\n".join(f"• {esc(ma)}: {n}" for n, ma in xa[:10]))
    return t.strip()


# ======================= Dự báo hết hàng → chủ shop quyết đặt / không restock =======================
# Mỗi sáng (hen): mẫu nào có size sẽ hết trước khi kịp sản xuất (tồn bán được / tốc độ bán < lead + đệm)
# → nhắn riêng chủ shop kèm nút. Chưa bấm thì mai nhắc lại. Quyết định lưu ở logs/dat_hang.json.

DH_STATE = os.path.join(ROOT, "logs", "dat_hang.json")


def dh_cfg():
    import json
    try:
        c = json.load(open(os.path.join(ROOT, "knowledge", "canh_bao.json"))).get("du_bao_dat_hang", {})
    except (OSError, ValueError):
        c = {}
    return {"bat": True, "ngay_ban": 14, "lead": 15, "dem": 5, "toi_thieu": 5, "da_dat_im": 30, "hoan": 3} | c


def dh_st():
    import json
    try:
        return json.load(open(DH_STATE))
    except (OSError, ValueError):
        return {}


def dh_luu(st):
    import json
    os.makedirs(os.path.dirname(DH_STATE), exist_ok=True)
    json.dump(st, open(DH_STATE, "w"), ensure_ascii=False, indent=1)


def ma_mau(sku):
    p = sku.upper().rsplit("-", 1)
    return p[0] if len(p) == 2 and p[1] in SIZES else sku.upper()


def du_bao():
    """[(ngày còn ít nhất, mã mẫu, tên, [(size, bán được, bán N ngày, ngày còn)])] — mẫu có size sẽ hết trước lead+đệm."""
    c = dh_cfg()
    if not NH.con_moi(24 * 60):
        return None
    ban = {}
    for o in NH.orders().values():
        if o.get("st") in (58, 63, 64):  # huỷ
            continue
        for x in o.get("sp") or []:
            for ma, sl in NH.bung_combo(str(x.get("ma")), int(x.get("sl") or 0)):   # bán combo = bán SP con
                ban[ma] = ban.get(ma, 0) + int(sl)
    gom = {}
    for ma, p in NH.products().items():
        if ma.startswith(("TEST", "PK-A0-STICKER", "CB-")):
            continue
        sl, ton = ban.get(ma, 0), max(0, int(p.get("co_the_ban") or 0))
        if sl < c["toi_thieu"]:
            continue
        con = ton / (sl / c["ngay_ban"])
        if con < c["lead"] + c["dem"]:
            mau = ma_mau(ma)
            ten_ = re.sub(r"\s*-\s*\w+$", "", str(p.get("ten") or mau))
            g = gom.setdefault(mau, {"ten": ten_, "size": []})
            g["size"].append((ma[len(mau) + 1:] or ma, ton, sl, con))
    out = [(min(s[3] for s in g["size"]), mau, g["ten"], sorted(g["size"], key=lambda s: s[3]))
           for mau, g in gom.items()]
    return sorted(out)


def dh_dang_dat(mau, ten_):
    """Đã có đơn đặt chưa về (bảng 02) cho mẫu này chưa."""
    for r in TG.rows(DAT):
        if r.get("Trạng thái đặt") in ("Đã về đủ", "Huỷ") or r.get("Đã về đủ"):
            continue
        n = str(r.get("Tên sản phẩm", ""))
        if khop(mau, n) or khop(ten_, n):
            return True
    return False


def dh_can_hoi(mau, ten_, st):
    c, s = dh_cfg(), st.get(mau) or {}
    if s.get("tt") == "khong":
        return False
    if s.get("tt") == "da_dat" and s.get("luc", "") >= (datetime.now() - timedelta(days=c["da_dat_im"])).strftime("%Y-%m-%d"):
        return False
    if s.get("tt") == "hoan" and s.get("den", "") > today():
        return False
    return not dh_dang_dat(mau, ten_)


def dh_dong(d, mau, ten_, sizes):
    het = (datetime.now() + timedelta(days=d)).strftime("%d/%m")
    t = f"• <b>{esc(ten_)}</b> <code>{esc(mau)}</code> — " + ("<b>đã hết 1 size</b>" if d < 1 else f"hết ~<b>{het}</b> ({d:.0f} ngày)")
    return t + "\n   " + " · ".join(f"{esc(s)}: còn {ton}, bán {sl}" + ("" if con >= 60 else f" → {con:.0f}n")
                                    for s, ton, sl, con in sizes)


def dh_nut(mau, ten_):
    n = ten_.replace("ORBIT ", "").replace("The ORBIT ", "")[:14]
    return [{"text": f"✅ Đặt {n}", "callback_data": f"kf:ddat:{mau}"},
            {"text": "🚫 Không restock", "callback_data": f"kf:dkhong:{mau}"},
            {"text": "⏰ 3 ngày", "callback_data": f"kf:dhoan:{mau}"}]


def nhac_dat_hang(send=False):
    """Sáng: nhắn riêng chủ shop các mẫu sắp hết chưa quyết. Mỗi ngày nhắc lại tới khi bấm."""
    c = dh_cfg()
    if not c["bat"]:
        return ""
    ds = du_bao()
    if ds is None:
        return ""
    st = dh_st()
    hoi = [x for x in ds if dh_can_hoi(x[1], x[2], st)][:10]
    if not hoi:
        return ""
    nhac = sum(1 for _, mau, _, _ in hoi if (st.get(mau) or {}).get("hoi_lan"))
    t = (f"🔔 <b>Dự báo hết hàng — cần anh/chị quyết</b> ({len(hoi)} mẫu"
         + (f", {nhac} mẫu nhắc lại" if nhac else "") + f")\nTính theo bán {c['ngay_ban']} ngày; sản xuất ~{c['lead']} ngày "
         f"nên mẫu hết trước {c['lead'] + c['dem']} ngày là phải đặt ngay.\n\n"
         + "\n".join(dh_dong(*x) for x in hoi)
         + "\n\nBấm <b>Đặt</b> rồi trả lời SL + ngày về (bot ghi vào kho, báo CSKH). Chưa bấm thì mai nhắc lại.")
    for _, mau, _, _ in hoi:
        s = st.setdefault(mau, {})
        s["hoi_lan"] = s.get("hoi_lan", 0) + (1 if send else 0)
        s["hoi_luc"] = today()
    if send:
        dh_luu(st)
        for o in TK.duyet_ids():
            tsend(o, t, [dh_nut(x[1], x[2]) for x in hoi])
    else:
        print(re.sub(r"<[^>]+>", "", t))
    return t


def dh_bo_nut(cq, mau):
    kb = ((cq["message"].get("reply_markup") or {}).get("inline_keyboard") or [])
    return [r for r in kb if not any(mau in str(b.get("callback_data", "")) for b in r)]


def dh_cb(cq, kind, mau):
    u, who = cq["from"], ten(cq["from"])
    chat, mid = cq["message"]["chat"]["id"], cq["message"]["message_id"]
    old = cq["message"].get("text", "")
    if str(u["id"]) not in TK.duyet_ids():
        return answer(cq, "Chỉ chủ shop quyết đặt hàng", True)
    st = dh_st()
    s = st.setdefault(mau, {})
    ten_ = ten_mau(mau)
    if kind == "ddat":
        return TK.prompt(chat, mid, mau, "kf_ddat", u,
                         f"✅ {esc(who)} trả lời tin này: <b>SL + ngày về</b> cho {esc(ten_)}, vd <code>200 về 15 ngày</code> "
                         "(mặc định size 1:1:1). Gõ <code>0</code> nếu chỉ đánh dấu đã đặt.")
    if kind == "dkhong":
        s.update(tt="khong", luc=today(), ai=who)
        dh_luu(st)
        dh_05_khong(mau, ten_)
        return tedit(chat, mid, esc(old) + f"\n\n🚫 {esc(ten_)}: không restock — {esc(who)} (bot thôi nhắc, CSKH đã biết)",
                     dh_bo_nut(cq, mau))
    if kind == "dhoan":
        den = (datetime.now() + timedelta(days=dh_cfg()["hoan"])).strftime("%Y-%m-%d")
        s.update(tt="hoan", den=den, ai=who)
        dh_luu(st)
        return tedit(chat, mid, esc(old) + f"\n\n⏰ {esc(ten_)}: nhắc lại {den[8:]}/{den[5:7]} — {esc(who)}",
                     dh_bo_nut(cq, mau))


def dh_05_khong(mau, ten_):
    """Không restock → bảng 05 cho CSKH: còn thì 'chốt sớm', hết thì 'Hết - không restock'."""
    ton = sum(max(0, int(p.get("co_the_ban") or 0)) for ma, p in NH.products().items() if ma_mau(ma) == mau)
    f = {"Cập nhật lúc": today(), "Ghi chú kho": f"Không restock (chủ shop {datetime.now():%d/%m})", "Hàng về dự kiến": "",
         "Tình trạng": "Hết - không restock" if ton == 0 else "Sắp hết",
         "CSKH được nói": "Mẫu này shop không sản xuất thêm nữa ạ" if ton == 0 else
                          "Mẫu này shop không về thêm, size nào còn thì bạn chốt sớm giúp shop nha"}
    try:
        r = next((r for r in TG.rows(TINH, fresh=True) if khop(mau, str(r.get("Tên sản phẩm", "")))
                  or khop(ten_, str(r.get("Tên sản phẩm", "")))), None)
        if r:
            TG.kho("update", table=TG.sname(TINH), id=r["_id"], fields=f)
        else:
            TG.kho("add", table=TG.sname(TINH), rows=[{"Tên sản phẩm": ten_, "Size/màu": "", **f}])
        TG._CACHE.clear()
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "lark.py"), "export"], cwd=ROOT,
                       capture_output=True, timeout=120)
    except BaseException as e:
        print("kho_flow: 05 không restock lỗi", e, flush=True)


def dh_reply(m, p):
    mau, t = p["id"], (m.get("text") or "").strip()
    st = dh_st()
    st.setdefault(mau, {}).update(tt="da_dat", luc=today(), ai=ten(m.get("from")))
    dh_luu(st)
    if t in ("0", ""):
        return tsend(m["chat"]["id"], f"✅ Đã đánh dấu {esc(ten_mau(mau))} đã đặt, bot thôi nhắc.", reply_to=m["message_id"])
    # ghi như /dathang trong nhóm kho để kho + CSKH cùng thấy
    dathang({"chat": {"id": kchat() or m["chat"]["id"]}, "from": m.get("from"), "message_id": None}, f"{mau} {t}")
    tsend(m["chat"]["id"], "✅ Đã ghi đặt hàng, báo nhóm kho + CSKH.", reply_to=m["message_id"])


def dubao(m, arg):
    """/dubao: xem dự báo + quyết định đã có. /dubao bo MÃ: bỏ quyết định (để bot hỏi lại)."""
    chat = m["chat"]["id"]
    a = arg.split()
    if a[:1] == ["bo"] and len(a) > 1:
        st = dh_st()
        st.pop(a[1].upper(), None)
        dh_luu(st)
        return tsend(chat, f"↩️ Bỏ quyết định của {esc(a[1].upper())}, sáng mai bot hỏi lại nếu vẫn sắp hết.",
                     reply_to=m["message_id"])
    ds = du_bao()
    if ds is None:
        return tsend(chat, "Chưa có dữ liệu Nhanh trong 24h (chủ shop nhắn /dangnhapnhanh cho bot).", reply_to=m["message_id"])
    st = dh_st()
    nhan = {"khong": "🚫 không restock", "da_dat": "✅ đã đặt", "hoan": "⏰ hẹn nhắc"}
    L = [dh_dong(*x) + (f"\n   {nhan.get((st.get(x[1]) or {}).get('tt'), '')}" if (st.get(x[1]) or {}).get("tt") else
                        ("\n   📦 có đơn đặt chưa về (bảng 02)" if dh_dang_dat(x[1], x[2]) else "\n   ❓ chưa quyết"))
         for x in ds[:20]]
    tsend(chat, "📈 <b>Dự báo hết hàng</b>\n\n" + ("\n".join(L) or "Không mẫu nào sắp hết 🎉")
          + "\n\nBỏ quyết định: <code>/dubao bo MÃ</code>", reply_to=m["message_id"])


# ======================= /chothoan =======================

def chothoan(m, arg):
    chat, who = m["chat"]["id"], ten(m.get("from"))
    san_bao, goc = [], {}
    for x in TK.ma_list(arg):
        if x.lower() not in SAN and x.lower() not in san_bao:
            san_bao.append(x.lower()); goc[x.lower()] = x
    if not san_bao:
        t, thieu = doi_soat_hoan_nhanh()
        if t:
            return tsend(chat, t, [[{"text": "📣 Đã đòi shipper", "callback_data": f"kf:doiship:{today()}"}]]
                         if thieu else None, reply_to=m["message_id"])
        return tsend(chat, "Chưa có dữ liệu Nhanh mới. Dán danh sách MVĐ sàn báo đã hoàn (mỗi dòng 1 mã). Mẫu:\n"
                     + MAU["chothoan"], reply_to=m["message_id"])
    rows = TG.rows(TK.HOAN, fresh=True)
    nhan = {str(r.get("MVĐ", "")).lower(): r for r in rows if r.get("Người nhận")}
    co, thieu = [], []
    for x in san_bao:
        (co if x in nhan else thieu).append(x)
    for x in co:
        r = nhan[x]
        if not r.get("Sàn báo hoàn"):
            TG.kho("update", table=TG.sname(TK.HOAN), id=r["_id"], fields={"Sàn báo hoàn": today()})
    da_co = {str(r.get("MVĐ", "")).lower() for r in rows}
    moi = [{"Ngày": today(), "MVĐ": goc[x], "Tình trạng": "❌ Sàn báo hoàn, kho chưa nhận", "Sàn báo hoàn": today()}
           for x in thieu if x not in da_co]
    if moi:
        TG.kho("add", table=TG.sname(TK.HOAN), rows=moi)
    hom_nay = [r for r in rows if r.get("Người nhận") and r.get("Ngày") == today()
               and str(r.get("MVĐ", "")).lower() not in san_bao]
    TG._CACHE.pop(TG.sname(TK.HOAN), None)
    key = f"{today()} - Hàng hoàn"
    f = {"Ngày - Sàn": key, "Ngày": today(), "Sàn": "Khác", "Hàng hoàn nhận": len(co),
         "Lệch/ghi chú": f"sàn báo {len(san_bao)}, kho nhận {len(co)}, thiếu {len(thieu)}", "Người làm": who}
    old = [r for r in TG.rows(DS, fresh=True) if r.get("Ngày - Sàn") == key]
    TG.kho("update", table=TG.sname(DS), id=old[0]["_id"], fields=f) if old else TG.kho("add", table=TG.sname(DS), rows=[f])
    TG._CACHE.pop(TG.sname(DS), None)
    t = (f"↩️ <b>ĐỐI SOÁT HÀNG HOÀN</b> {datetime.now():%d/%m %H:%M} · {esc(who)}\n"
         f"Sàn báo hoàn: <b>{len(san_bao)}</b> · kho đã nhận: <b>{len(co)}</b>"
         + (f" · <b>shipper chưa trả: {len(thieu)}</b>" if thieu else " ✅ đủ"))
    if thieu:
        t += "\n\n❌ <b>Chưa nhận</b> (đòi shipper / ĐVVC):\n" + "\n".join(f"• <code>{esc(goc[x])}</code>" for x in thieu[:40])
        t += "\nShipper trả thêm thì quét <code>/hoan MVĐ</code> là tự gạch."
    if hom_nay:
        t += "\n\n⚠️ Kho nhận hôm nay mà sàn chưa báo hoàn:\n" + "\n".join(
            f"• <code>{esc(r.get('MVĐ'))}</code>" for r in hom_nay[:20])
    tsend(chat, t, [[{"text": "📣 Đã đòi shipper", "callback_data": f"kf:doiship:{today()}"}]] if thieu else None,
          reply_to=m["message_id"])
    if len(thieu) >= 3:
        for o in TK.duyet_ids():
            tsend(o, f"↩️ Hàng hoàn {datetime.now():%d/%m}: shipper còn thiếu {len(thieu)}/{len(san_bao)} kiện.")


# ======================= /kiemkho =======================

def ds_kiem_hom_nay():
    return [f"{k}-{s}" if s else k for k in goi_y_kiem() for s in (sku_bang()[k][1] or [""])]


def kiemkho(m, arg):
    chat, who = m["chat"]["id"], ten(m.get("from"))
    dot = f"KK{m['message_id']}"
    ds = ds_kiem_hom_nay()
    so_ = arg.replace(",", " ").split()
    if not arg.strip():
        return tsend(chat, "🔢 <b>Kiểm kho hôm nay</b> — đếm theo thứ tự rồi gõ <b>chỉ các số</b>: "
                           f"<code>/kiemkho {' '.join(['0'] * min(len(ds), 4))} …</code>\n"
                     + "\n".join(f"{i}. {esc(s)}" for i, s in enumerate(ds, 1))
                     + "\n(SKU khác: mỗi dòng <code>SKU  số đếm</code>)", reply_to=m["message_id"])
    if so_ and all(re.fullmatch(r"\d+", x) for x in so_):
        if len(so_) != len(ds):
            return tsend(chat, f"Danh sách hôm nay có <b>{len(ds)}</b> SKU mà bạn gõ <b>{len(so_)}</b> số. "
                               "Gõ /kiemkho để xem lại thứ tự.", reply_to=m["message_id"])
        arg = "\n".join(f"{s} {n}" for s, n in zip(ds, so_))
    rows, L, lech_n = [], [], 0
    for line in [x for x in arg.splitlines() if x.strip()]:
        d = doc_dong(line)
        if not d or not d[2]:
            continue
        mau, size, nums = d
        if len(nums) == 1:  # chỉ ghi số đếm → lấy tồn trong kho từ Nhanh
            p = NH.ton_sku(f"{mau}-{size}" if size else mau)
            nhanh = None if p is None or p.get("trong_kho") is None else int(p["trong_kho"] or 0)
            thuc = nums[0]
        else:
            nhanh, thuc = nums[0], nums[1]
        lech = None if nhanh is None else thuc - nhanh
        sku = f"{mau}-{size}" if size and "-" in mau else f"{mau} {size}".strip()
        rows.append({"Ngày": today(), "SKU": sku, "Tên mẫu": ten_mau(mau), "Tồn Nhanh": "" if nhanh is None else nhanh,
                     "Đếm thực tế": thuc, "Lệch": "" if lech is None else lech, "Người kiểm": who, "Đợt": dot})
        if lech:
            lech_n += 1
        if nhanh is None:
            L.append(f"📝 {esc(sku)}: đếm {thuc} (chưa có tồn Nhanh để so)")
        else:
            L.append(f"{'✅' if not lech else '⚠️'} {esc(sku)}: Nhanh {nhanh} · đếm {thuc}"
                     + (f" · <b>{'+' if lech > 0 else ''}{lech}</b>" if lech else ""))
    if not rows:
        return tsend(chat, "Mỗi dòng: SKU  tồn Nhanh  đếm thực tế. Mẫu:\n" + MAU["kiemkho"], reply_to=m["message_id"])
    TG.kho("add", table=TG.sname(KIEM), rows=rows)
    TG._CACHE.pop(TG.sname(KIEM), None)
    t = (f"🔢 <b>KIỂM KHO</b> {datetime.now():%d/%m} · {esc(who)} · {len(rows)} SKU, lệch {lech_n}\n" + "\n".join(L))
    if lech_n:
        t += "\n\nĐếm lại SKU lệch 1 lần nữa → vẫn lệch thì điều chỉnh Nhanh + tìm nguyên nhân, rồi bấm nút."
    tsend(chat, t, [[{"text": "✅ Đã điều chỉnh Nhanh", "callback_data": f"kf:dc:{dot}"}]] if lech_n else None,
          reply_to=m["message_id"])
    if lech_n:
        for o in TK.duyet_ids():
            tsend(o, "⚠️ <b>Kiểm kho lệch</b>\n" + t)


def ban_hom_qua(hom_nay=False):
    """Số lượng hàng ĐI theo mã mẫu (đơn đã giao ĐVVC hôm qua — hoặc hôm nay nếu hom_nay=True, theo Nhanh)."""
    from collections import Counter
    hq = (datetime.now() - timedelta(days=0 if hom_nay else 1)).date()
    keys = sorted(sku_bang(), key=len, reverse=True)
    c = Counter()
    for o in NH.orders().values():
        if not (NH._ngay(o.get("gui_dvvc")) == hq or (o.get("st") == 59 and NH._ngay(o.get("cap_nhat")) == hq)):
            continue
        for sp in o.get("sp") or []:
            ma = str(sp.get("ma") or "").upper()
            mau = next((k for k in keys if ma == k or ma.startswith(k + "-")), None)
            if mau and not mau.startswith(("PK-", "CB-")):
                c[mau] += int(sp.get("sl") or 1)
    return c


def goi_y_kiem(n=5):
    """Mẫu cần kiểm hôm nay: ưu tiên mẫu BÁN RA HÔM QUA (nhiều nhất trước), thiếu thì bù bằng xoay vòng bảng SKU
    (bỏ phụ kiện/combo). Chốt 1 lần/ngày để danh sách 9h và /kiemkho luôn khớp thứ tự."""
    k = "kiem" + today()
    toi = datetime.now().hour >= 17   # danh sách gửi 17h30: lấy hàng ĐI HÔM NAY (kiểm sau khi đi đơn)
    cu = TK.STATE_KF.get(k)
    if cu and (cu.get("toi") or not toi):
        return cu["maus"]
    maus = [m for m in sku_bang() if not m.startswith(("PK-", "CB-"))]
    if not maus:
        return []
    try:
        ban = ban_hom_qua(hom_nay=toi)
    except Exception as e:
        print("kho_flow: đọc hàng bán hôm qua lỗi", e, flush=True)
        ban = {}
    chon = [m for m, _ in sorted(ban.items(), key=lambda x: -x[1])][:n]
    i = (datetime.now().timetuple().tm_yday * n) % len(maus)
    for m in (maus + maus)[i:]:
        if len(chon) >= n:
            break
        if m not in chon:
            chon.append(m)
    TK.STATE_KF[k] = {"maus": chon, "ban": {m: ban[m] for m in chon if m in ban}, "toi": toi}
    TK._save()
    return chon


def ly_do_kiem(mau):
    st = TK.STATE_KF.get("kiem" + today()) or {}
    b = st.get("ban", {}).get(mau)
    return (f"đi {'hôm nay' if st.get('toi') else 'hôm qua'} {b}") if b else "xoay vòng"


# ======================= nút =======================

def on_cb(cq, p):
    u = cq["from"]
    who = ten(u)
    if not TK.is_member(u["id"]):
        return answer(cq, "Bạn chưa ở nhóm kho", True)
    kind, key = p[1], p[2]
    chat, mid = cq["message"]["chat"]["id"], cq["message"]["message_id"]
    old = cq["message"].get("text", "")
    answer(cq)
    if kind == "dca":
        st = dc_st()
        i = int(key)
        st["tick"][i] = "" if st["tick"][i] else f"{who} {datetime.now():%H:%M}"
        TK._save()
        return tedit(chat, mid, dc_text(st), dc_btn(st))
    if kind in ("ddat", "dkhong", "dhoan"):
        return dh_cb(cq, kind, key)
    if kind == "goiy":
        return goi_y_sku(chat, mid, ":".join(p[2:]))
    if kind == "ncc":
        for rid in TK.STATE_KF.get(key, []):
            TG.kho("update", table=TG.sname(NHAP), id=rid, fields={"Ghi chú": f"Đã báo NCC/lập biên bản ({who})"})
        return tedit(chat, mid, esc(old) + f"\n\n📝 Đã báo NCC / lập biên bản — {esc(who)}",
                     [[{"text": "✅ Đã nhập Nhanh (gõ ID phiếu)", "callback_data": f"kf:nhanh:{key}"}]])
    if kind == "nhanh":
        return TK.prompt(chat, mid, key, "kf_nhanh", u, f"✅ {esc(who)} trả lời tin này bằng <b>ID phiếu nhập Nhanh</b>")
    if kind == "lechdi":
        return TK.prompt(chat, mid, key, "kf_lechdi", u, f"🔍 {esc(who)} trả lời tin này: đơn lệch là gì, đã xử lý sao?")
    if kind == "doiship":
        return tedit(chat, mid, esc(old) + f"\n\n📣 Đã đòi shipper — {esc(who)} {datetime.now():%H:%M}")
    if kind == "dc":
        for r in TG.rows(KIEM, fresh=True):
            if r.get("Đợt") == key and str(r.get("Lệch", "0")) not in ("0", "0.0", ""):
                TG.kho("update", table=TG.sname(KIEM), id=r["_id"], fields={"Đã điều chỉnh Nhanh": f"✓ {who}"})
        TG._CACHE.pop(TG.sname(KIEM), None)
        return tedit(chat, mid, esc(old) + f"\n\n✅ Đã điều chỉnh Nhanh — {esc(who)}")


def on_reply(m, p):
    chat, who = m["chat"]["id"], ten(m.get("from"))
    t = (m.get("text") or "").strip()
    if p["f"] == "kf_ddat":
        return dh_reply(m, p)
    if p["f"] == "kf_nhanh":
        rids = TK.STATE_KF.get(p["id"], [])
        kq = kiem_id_phieu(rids, t)   # có API Nhanh: so phiếu với số kho kiểm
        sai = kq.startswith("\n⚠️")
        for rid in rids:   # phiếu sai/không thấy → CHƯA tick, bot đối chiếu tiếp sau mỗi lần đồng bộ Nhanh
            TG.kho("update", table=TG.sname(NHAP), id=rid,
                   fields={"ID phiếu nhập Nhanh": t + " (⚠️ chưa khớp Nhanh)"} if sai else {"Đã nhập Nhanh.vn": "✓", "ID phiếu nhập Nhanh": t})
        TG._CACHE.pop(TG.sname(NHAP), None)
        return tsend(chat, (f"📝 Đã ghi ID <code>{esc(t)}</code> nhưng <b>chưa tick Đã nhập Nhanh</b>" if sai
                            else f"✅ Đã ghi phiếu nhập Nhanh <code>{esc(t)}</code>") + kq
                     + ("\n→ Sửa trên Nhanh xong bot tự đối chiếu lại (30 phút/lần)." if sai else ""), reply_to=m["message_id"])
    if p["f"] == "kf_lechdi":
        for r in TG.rows(DS, fresh=True):
            if r.get("Ngày") == p["id"] and "khớp" not in str(r.get("Lệch/ghi chú", "")):
                TG.kho("update", table=TG.sname(DS), id=r["_id"],
                       fields={"Lệch/ghi chú": f"{r.get('Lệch/ghi chú')} → {who}: {t}"})
        TG._CACHE.pop(TG.sname(DS), None)
        return tsend(chat, "📝 Đã ghi.", reply_to=m["message_id"])


# ======================= mẫu + menu + lịch =======================

MAU = {
    "hangve": "/hangve\nNCC: \nKho: Q2\n(SKU | bill | thực tế | lỗi)\nSO-A4-RIVET-S 20 20 0",
    "chotdi": "/chotdi\n(sàn | cần gửi | đã đóng | đã bàn giao | huỷ)\nTikTok 0 0 0 0\nShopee 0 0 0 0\nWeb 0 0 0 0",
    "chothoan": "/chothoan\n(dán MVĐ sàn báo đã hoàn, mỗi dòng 1 mã)",
    "kiemkho": "/kiemkho\n(SKU | tồn Nhanh | đếm thực tế)\nSO-A4-RIVET-S 12 12",
    "dathang": "/dathang\nMẫu: DRIFT CAR, ISOLENT TEE\nSL: 250\nSize: M:L:XL = 1:1:1\nVề: 15 ngày\nNgười: Huyền",
}


def menu(m, arg):
    tsend(m["chat"]["id"],
          "🏬 <b>Việc kho trên Telegram</b> — chép mẫu, điền, gửi 1 tin:\n\n"
          f"🧵 <b>Đặt hàng / chốt SX</b> (mặc định 250/mẫu, 1:1:1; 1 dòng cũng được: "
          f"<code>/dathang AURA 250 về 20-22/11</code>):\n<code>{esc(MAU['dathang'])}</code>\n\n"
          "📦 <b>Hàng về</b>: gõ <code>/hangve tên mẫu</code> (VD <code>/hangve rivet</code>) → bot đưa sẵn SKU + size, "
          "chỉ điền số bill + thực tế\n\n"
          "↩️ <b>Hàng hoàn</b>: <b>chụp tem vận đơn</b>, chú thích <code>/hoan</code> → bot tự đọc mã "
          "(nhiều tem 1 ảnh / nhiều ảnh 1 lần đều được)\n\n"
          "🖨 <b>In đơn</b>: gõ /indon → số tem cần in từng sàn, đơn chưa có MVĐ, đơn sắp quá hạn\n"
          "🚚 <b>Giao shipper</b>: <b>chụp tem</b> (nhiều kiện 1 ảnh), chú thích <code>/giao</code> → bot so từng kiện, "
          "đơn huỷ báo giữ lại ngay. /doisoat xem lệch bất cứ lúc nào (bot tự đối soát 17h + 9h hôm sau)\n"
          "⛔ <b>Đơn huỷ sau khi in</b>: bot báo ngay khi khách huỷ → rút kiện ra, <b>chụp tem</b> chú thích "
          "<code>/giulai</code>. Gõ /giulai xem kiện huỷ còn thiếu\n\n"
          f"🚚 <b>Chốt đơn đi</b> (17h, đếm tay nếu chưa quét):\n<code>{esc(MAU['chotdi'])}</code>\n\n"
          "🧾 <b>Đối soát hàng hoàn</b> (17h): chụp màn hình danh sách hoàn trên sàn, chú thích <code>/chothoan</code>\n\n"
          "🔢 <b>Kiểm kho</b>: 17h30 bot gửi danh sách (mẫu đi nhiều nhất hôm nay) · gõ /kiemkho xem lại → gõ <code>/kiemkho</code> + các số đếm theo thứ tự",
          reply_to=m["message_id"])


# ======================= checklist đầu ca + phiếu điểm cuối ngày =======================

DAU_CA = ["Kéo đơn sàn về Nhanh đủ (so số đơn từng Seller Center)", "Xử lý hoả tốc + đơn sắp quá hạn chuẩn bị",
          "Đọc ghi chú đơn (/note) + thẻ việc còn treo", "Đơn hết hàng/tồn ảo đã báo CS",
          "Kiện hoàn hôm qua đã mở kiểm hết"]


def dc_st(ngay=None):
    k = "dauca" + (ngay or today())
    st = TK.STATE_KF.get(k)
    if not st:
        st = TK.STATE_KF[k] = {"tick": [""] * len(DAU_CA)}
    return st


def dc_text(st):
    return ("☀️ <b>ĐẦU CA KHO</b> " + datetime.now().strftime("%d/%m") + " — làm xong mục nào bấm mục đó (10h bot kiểm):\n"
            + "\n".join(f"{'✅' if t else '⬜'} {c}" + (f" <i>({esc(t)})</i>" if t else "") for c, t in zip(DAU_CA, st["tick"])))


def dc_btn(st):
    return [[{"text": f"{'✅' if t else '⬜'} {c[:40]}", "callback_data": f"kf:dca:{i}"}] for i, (c, t) in enumerate(zip(DAU_CA, st["tick"]))]


def dauca(m, arg):
    st = dc_st()
    tsend(m["chat"]["id"], dc_text(st), dc_btn(st))


def phieu_diem():
    """Phiếu điểm kho cuối ngày cho chủ shop: chỉ liệt kê việc CHƯA xong / có vấn đề."""
    hn = today()
    L, xau = [f"📋 <b>PHIẾU ĐIỂM KHO</b> {datetime.now():%d/%m}"], 0

    def dong(ok, t):
        nonlocal xau
        xau += 0 if ok else 1
        L.append(("✅ " if ok else "❌ ") + t)
    st = dc_st()
    chua = [c for c, t in zip(DAU_CA, st["tick"]) if not t]
    dong(not chua, "Đầu ca: " + ("đủ" if not chua else f"thiếu {len(chua)} mục — " + "; ".join(chua)))
    ds = [r for r in TG.rows(DS, fresh=True) if r.get("Ngày") == hn]
    san = {r.get("Sàn") for r in ds}
    dong({"TikTok", "Shopee"} <= san, "Chốt đơn đi 17h: " + (", ".join(sorted(x for x in san if x and x != "Khác")) or "chưa chốt"))
    dong(any(str(r.get("Ngày - Sàn", "")).endswith("Hàng hoàn") for r in ds), "Đối soát hoàn (/chothoan)")
    hoan = TG.rows(TK.HOAN, fresh=True)
    nhan = [r for r in hoan if r.get("Ngày") == hn and r.get("Người nhận")]
    cho = [r for r in hoan if r.get("Sàn báo hoàn") and not r.get("Người nhận")]
    dong(not cho, f"Hàng hoàn: hôm nay quét {len(nhan)} kiện" + (f" · <b>{len(cho)} kiện sàn báo mà chưa về</b>: "
         + ", ".join(str(r.get("MVĐ")) for r in cho[:8]) if cho else ""))
    kk = [r for r in TG.rows(KIEM, fresh=True) if r.get("Ngày") == hn]
    lech = [r for r in kk if str(r.get("Lệch", "")) not in ("", "0") and not r.get("Đã điều chỉnh Nhanh")]
    dong(bool(kk) and not lech, f"Kiểm kho: {len(kk)} SKU" + (f" · <b>{len(lech)} lệch chưa điều chỉnh</b>" if lech else "")
         if kk else "Kiểm kho: <b>chưa làm</b>")
    nh = [r for r in TG.rows(NHAP, fresh=True) if r.get("Ngày nhận") == hn]
    ncc = [r for r in nh if r.get("Lệch bill") in ("Thiếu", "Thừa") and "NCC" not in str(r.get("Ghi chú", ""))]
    chua_nh = [r for r in nh if not r.get("Đã nhập Nhanh.vn")]
    if nh:
        dong(not ncc and not chua_nh, f"Hàng về: {len(nh)} dòng" + (f" · {len(ncc)} lệch chưa báo NCC" if ncc else "")
             + (f" · {len(chua_nh)} chưa nhập Nhanh" if chua_nh else ""))
    try:
        import cua_hang as CH
        treo = [r for r in TG.rows(CH.VIEC, fresh=True) if r.get("Trạng thái") not in ("Xong", "Huỷ", "Hủy")]
    except Exception:
        treo = []
    dong(not treo, "Thẻ việc (hoả tốc/note/gói): " + ("hết treo" if not treo else
         f"<b>{len(treo)} còn treo</b> — " + ", ".join(f"{r.get('ID')} {r.get('Loại')}" for r in treo[:8])))
    tk = [r for r in TK.all_rows() if r.get("Trạng thái") == "Chờ nhập kho QLBH"]
    gt = [r for r in TK.all_rows() if str(r.get("Phạt kho", "")).startswith("Chờ")]
    if tk or gt:
        dong(False, (f"{len(tk)} ticket chờ kho nhập QLBH " if tk else "") + (f"· {len(gt)} lỗi kho chờ xử lý" if gt else ""))
    L.insert(1, "🟢 Kho hôm nay ổn" if not xau else f"🔴 <b>{xau} việc chưa xong</b>")
    return "\n".join(L)


def tin_kiem_kho():
    maus = goi_y_kiem()
    ds = ds_kiem_hom_nay()
    n_ban = sum(1 for m in maus if ly_do_kiem(m) != "xoay vòng")
    return ("🔢 <b>KIỂM KHO HÔM NAY</b> (" + (f"{n_ban} mẫu đi nhiều nhất hôm nay + xoay vòng" if n_ban else "xoay vòng")
            + ") — đếm theo thứ tự rồi gõ <b>chỉ các số</b>, "
            f"VD <code>/kiemkho {' '.join(['12'] * min(len(ds), 3))} …</code>"
            + (" (bot tự so tồn Nhanh)" if NH.con_moi(180) else "") + ":\n"
            + "\n".join(f"{i}. {esc(s)}" for i, s in enumerate(ds, 1)))


def hen(send=False):
    """Chạy theo lịch: 9h gợi ý kiểm kho + kiện hoàn còn thiếu; 17h nhắc chốt ca; 18h nhắc lại nếu chưa chốt."""
    h = datetime.now().hour
    out = None
    if h == 17 and datetime.now().minute >= 25:   # 17h30: danh sách kiểm kho (sau khi đi đơn xong)
        t = tin_kiem_kho()
        print(re.sub(r"<[^>]+>", "", t))
        if send and kchat():
            tsend(kchat(), t)
        return
    if h == 10:   # 10h15: TRƯỚC KHI SHIPPER LẤY (~10h30) — đơn huỷ sau in còn nằm trong khay giao → rút ra
        try:
            import nhanh_api as NA
            if NA.co_api():
                NA.sync()
        except Exception as e:
            print("kho_flow: đọc Nhanh 10h lỗi", repr(e)[:200], flush=True)
        if not NH.con_moi(90):
            return print("10h: Nhanh cũ, không báo")
        xuat_kho.huy_cap_nhat()
        ht, n = xuat_kho.huy_bao()
        if not n:
            return print("10h: không có đơn huỷ sau in cần rút")
        t = "⏰ <b>10h15 — TRƯỚC KHI SHIPPER LẤY</b>: kiểm khay giao, rút các kiện này ra NGAY\n\n" + ht
        print(re.sub(r"<[^>]+>", "", t))
        if send and kchat():
            tsend(kchat(), t)
        return
    if h in (12, 18) and datetime.now().minute < 25:   # D004: 12h & 18h đối soát đơn đã in mà shipper chưa quét
        try:
            ts = xuat_kho.doi_soat_shipper()
        except BaseException as e:
            ts = []
            print("kho_flow: đối soát shipper lỗi", repr(e)[:200], flush=True)
        for t in ts:
            print(re.sub(r"<[^>]+>", "", t))
            if send and kchat():
                tsend(kchat(), t)
        if h == 12:
            return
    if h >= 18 and send:
        pd = phieu_diem()
        print(re.sub(r"<[^>]+>", "", pd))
        for o in TK.duyet_ids():
            tsend(o, pd)
    if h < 12:
        try:
            nhac_dat_hang(send)
        except BaseException as e:
            print("kho_flow: dự báo đặt hàng lỗi", e, flush=True)
    if h < 12 and send and kchat():
        st = dc_st()
        if not any(st["tick"]):
            tsend(kchat(), dc_text(st), dc_btn(st))
        cho = [r for r in TG.rows(TK.HOAN, fresh=True) if not r.get("Người nhận")]
        out = "☀️ <b>ĐẦU NGÀY KHO</b> · 🔢 danh sách kiểm kho gửi lúc <b>17h30</b> (sau khi đi đơn)"
        hoan_t, thieu = doi_soat_hoan_nhanh()
        if thieu:
            out += "\n\n" + hoan_t
        cb = canh_bao_nhap()
        if cb:
            out += "\n\n" + cb
        xs = xuat_kho.bao_sang()
        if xs:
            out += "\n\n" + xs
        if cho:
            out += (f"\n\n↩️ <b>{len(cho)} kiện sàn báo hoàn mà kho chưa nhận</b>:\n"
                    + "\n".join(f"• <code>{esc(r.get('MVĐ'))}</code> (báo {esc(r.get('Sàn báo hoàn'))})" for r in cho[:30])
                    + "\n→ đòi shipper / khiếu nại ĐVVC")
    else:
        da = {r.get("Sàn") for r in TG.rows(DS, fresh=True) if r.get("Ngày") == today() and r.get("Người làm") != xuat_kho.BOT}
        nhan = len([r for r in TG.rows(TK.HOAN, fresh=True) if r.get("Ngày") == today() and r.get("Người nhận")])
        if h >= 18 and {"TikTok", "Shopee"} <= da:
            return print("đã chốt ca, không nhắc")
        nh = bao_nhanh_chot_ca()
        hoan_t, _ = doi_soat_hoan_nhanh()
        xt, _ = xuat_kho.bao_chieu()
        if nh:
            out = ("🕔 <b>CHỐT CA</b>" + (" — nhắc lại, chưa thấy chốt" if h >= 18 else "")
                   + f"\nHôm nay kho đã quét {nhan} kiện hoàn.\n\n{nh}\n\n{hoan_t}\n\n"
                   "1️⃣ Đếm kiện đã bàn giao shipper (theo biên bản) rồi gửi:\n"
                   "<code>/chotdi\nTikTok \nShopee \nWeb </code>\n"
                   "2️⃣ Hàng hoàn: quét nốt kiện shipper vừa trả bằng <code>/hoan MVĐ</code>, rồi gõ /chothoan để đối soát lại.")
            if xt:
                out += "\n\n" + xt
        else:
            out = ("🕔 <b>CHỐT CA</b>" + (" — nhắc lại, chưa thấy chốt" if h >= 18 else "")
                   + f"\nHôm nay kho đã quét {nhan} kiện hoàn. (Chưa đọc được Nhanh — điền tay)\n\n"
                   f"1️⃣ Chốt đơn đi:\n<code>{esc(MAU['chotdi'])}</code>\n\n"
                   f"2️⃣ Đối soát hàng hoàn: lấy danh sách đơn đã hoàn hôm nay trên Nhanh/Seller Center, dán:\n"
                   f"<code>{esc(MAU['chothoan'])}</code>")
    if not out or out.startswith("☀️ <b>ĐẦU NGÀY KHO</b>") and "\n" not in out:
        return print("9h: không có việc cần báo")
    print(re.sub(r"<[^>]+>", "", out))
    if send and kchat():
        tsend(kchat(), out)


def nhanh_tt(m, arg):
    mt = NH.meta()
    if not mt:
        return tsend(m["chat"]["id"], "Chưa đọc Nhanh lần nào (chủ shop nhắn /dangnhapnhanh cho bot).", reply_to=m["message_id"])
    t = (f"📊 Nhanh.vn — cập nhật {esc(mt.get('dong_bo'))}, {mt.get('so_sp')} SKU, {mt.get('so_don')} đơn 14 ngày"
         + (f"\n⚠️ Lỗi gần nhất: {esc(mt.get('loi'))}" if mt.get("loi") else ""))
    if arg.strip():
        p = NH.ton_sku(arg.strip())
        if p and p.get("combo"):   # combo: Nhanh để tồn 0, tồn thật theo SP con
            t += (f"\n<b>{esc(arg.strip().upper())}</b> là <b>combo</b> — bán được <b>{NH.ton_combo(arg.strip().upper()) if NH.ton_combo(arg.strip().upper()) is not None else '?'}</b> combo (theo SP con):"
                  + "".join(f"\n• {esc(c['ma'])} ×{c.get('sl') or 1}: có thể bán {(NH.ton_sku(c['ma']) or {}).get('co_the_ban', '?')}"
                            for c in p["combo"]))
        else:
            t += (f"\n<b>{esc(arg.strip().upper())}</b>: trong kho {p.get('trong_kho', '?')} · có thể bán {p.get('co_the_ban', '?')} · "
                  f"đang giao {p.get('dang_giao', '?')} · lỗi {p.get('loi', '?')}") if p else f"\nKhông thấy SKU {esc(arg)}"
    else:
        t += "\n" + bao_nhanh_chot_ca()
    tsend(m["chat"]["id"], t, reply_to=m["message_id"])


def setup():
    TG.kho("setup", tables={TG.sname(KIEM): KIEM_COLS,
                            TG.sname(NHAP): ["Ảnh bill", "Ảnh bill (xem)"]})


# ======================= cảnh báo từ Seller Center (TikTok/Shopee) =======================

def san_bao(d, send=False, luon=False):
    """d = {"tiktok": {...}, "shopee": {...}} do tác vụ lịch (Claude in Chrome, Chrome của chủ shop) đọc từ Seller Center.
    Chỉ gửi nhóm kho khi có việc gấp (tự huỷ, quá hạn, hoả tốc, huỷ sau chuẩn bị hàng) hoặc luon=True."""
    tt, sp = d.get("tiktok") or {}, d.get("shopee") or {}
    g = lambda x, k: int(x.get(k) or 0)
    L, gap = [], False
    if tt:
        L.append(f"<b>TikTok</b>: cần gửi trong 24h <b>{g(tt, 'can_gui_24h')}</b>"
                 + (f" (hoả tốc {g(tt, 'hoa_toc')})" if g(tt, "hoa_toc") else "")
                 + (f" · ⚠️ <b>sắp tự huỷ {g(tt, 'tu_huy_24h')}</b>" if g(tt, "tu_huy_24h") else "")
                 + (f" · ⛔ <b>quá hạn {g(tt, 'qua_han')}</b>" if g(tt, "qua_han") else "")
                 + (f" · vấn đề gửi hàng/kho vận {g(tt, 'van_de_kho')}" if g(tt, "van_de_kho") else "")
                 + (f" · yêu cầu trả hàng {g(tt, 'tra_hang')}" if g(tt, "tra_hang") else ""))
        gap |= bool(g(tt, "tu_huy_24h") or g(tt, "qua_han") or g(tt, "hoa_toc"))
    if sp:
        L.append(f"<b>Shopee</b>: chờ lấy hàng {g(sp, 'cho_lay')}"
                 + (f" · 🔥 <b>hoả tốc cần bàn giao ngay {g(sp, 'hoa_toc_can_ban_giao')}</b>" if g(sp, "hoa_toc_can_ban_giao") else "")
                 + (f" · ⛔ <b>{g(sp, 'huy_sau_chuan_bi')} đơn huỷ sau khi chuẩn bị hàng → GIỮ LẠI kiện, không giao ĐVVC</b>"
                    if g(sp, "huy_sau_chuan_bi") else "")
                 + (f" · trả hàng/huỷ {g(sp, 'tra_hang_huy')}" if g(sp, "tra_hang_huy") else ""))
        gap |= bool(g(sp, "hoa_toc_can_ban_giao") or g(sp, "huy_sau_chuan_bi"))
    if not L:
        return print("không có số liệu sàn")
    t = f"🛒 <b>SÀN {datetime.now():%H:%M}</b>\n" + "\n".join(L)
    if d.get("ghi_chu"):
        t += "\n" + esc(d["ghi_chu"])[:400]
    print(re.sub(r"<[^>]+>", "", t))
    if send and kchat() and (gap or luon):
        tsend(kchat(), t)


TK.EXT_CMDS.update({"/dubao": dubao, "/dathang": dathang, "/hangve": hangve, "/chotdi": chotdi, "/chothoan": chothoan, "/kiemkho": kiemkho, "/kho": menu,
                    "/nhanh": nhanh_tt, "/dauca": dauca})
TK.EXT_NHOM.update({k: ("CHAT_ID",) for k in ("/dathang", "/hangve", "/chotdi", "/chothoan", "/kiemkho")})
TK.EXT_CB["kf"] = on_cb
TK.EXT_REPLY.update({"kf_ddat": on_reply, "kf_nhanh": on_reply, "kf_lechdi": on_reply})
if not hasattr(TK, "STATE_KF"):
    TK.STATE_KF = {}

import xuat_kho  # noqa: E402  /indon /giao /doisoat: đối soát in đơn → bàn giao theo từng MVĐ

if __name__ == "__main__":
    import lark as Lk
    TK.init(Lk.load_env(), start_worker=False)
    a = sys.argv[1:] or ["help"]
    if a[0] == "setup":
        TK.setup(); setup(); print("đã tạo bảng 09, 10, cột ảnh bill")
    elif a[0] == "dubao":   # python3 tools/kho_flow.py dubao [--send]: chạy thử nhắc đặt hàng
        nhac_dat_hang("--send" in a)
    elif a[0] == "nhapnhanh":   # sau mỗi lần đồng bộ Nhanh: đối chiếu phiếu nhập ↔ hàng về (03)
        doi_chieu_nhap("--send" in a)
    elif a[0] == "mahoan-can":   # mã tem hoàn kho đã quét mà bot chưa ra đơn → tác vụ lịch tra trên sàn
        for k, v in ma_hoan_can().items():
            print(k + ":", ",".join(v))
    elif a[0] == "mahoan-ghi":   # python3 tools/kho_flow.py mahoan-ghi <file "mã|ID đơn"> tiktok|shopee
        cap = dict(l.strip().split("|", 1) for l in open(a[1], encoding="utf-8") if "|" in l)
        print("ghi mới:", NH.ghi_ma_hoan(cap, a[2] if len(a) > 2 else ""), "/", len(cap), "mã")
    elif a[0] == "hen":
        hen("--send" in a)
    elif a[0] == "sanbao":  # python3 tools/kho_flow.py sanbao '<json>' [--send] [--luon]
        import json as _j
        san_bao(_j.loads(a[1]), "--send" in a, "--luon" in a)
    else:
        print(__doc__)
