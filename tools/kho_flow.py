#!/usr/bin/env python3
"""Việc thủ kho trên Telegram (nhóm "The Orbit - Kho hàng về & restock"), luồng cố định có nút, không gọi Claude.

  /hangve   hàng về: dán từng dòng "SKU/mẫu size  bill  thực tế  lỗi" → bot so bill, ghi 03, cộng 02, sửa 05,
            báo thiếu/thừa/lỗi cho chủ shop; nút "Đã báo NCC", "Đã nhập Nhanh (gõ ID phiếu)"
  /chotdi   chốt đơn đi cuối ca: "Sàn  cần gửi  đã đóng  đã bàn giao  huỷ" → ghi 07, chỉ ra lệch
  /chothoan đối soát hàng hoàn 17h: dán danh sách MVĐ sàn báo hoàn → so với kiện kho đã quét /hoan
            → liệt kê kiện shipper chưa trả (đòi shipper) + kiện kho nhận mà sàn không báo
  /kiemkho  kiểm kho: "SKU  tồn Nhanh  đếm thực tế" → ghi 10, chỉ ra lệch; nút "Đã điều chỉnh Nhanh"
  /kho      menu + mẫu chép
Lịch (launchd vn.theorbit.kho-agent.flow, `kho_flow.py hen`): 9:02 gợi ý mẫu kiểm kho hôm nay + kiện sàn báo hoàn
mà chưa nhận; 17:00 nhắc chốt ca (2 mẫu); 18:00 nhắc lại nếu chưa chốt.
Đăng ký vào ticket.py (EXT_CMDS / EXT_CB / EXT_REPLY) nên chạy chung hàng đợi, chung listener kho.
"""
import os, re, subprocess, sys, time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orbit_tg as TG  # noqa: E402
import ticket as TK  # noqa: E402

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


def khop(mau, name):
    """Dòng bảng 02/05 (tên) có phải mẫu này không."""
    n = name.lower()
    return mau.lower() in n or ten_mau(mau).lower() in n


# ======================= /hangve =======================

def hangve(m, arg):
    chat, u = m["chat"]["id"], m.get("from") or {}
    who = ten(u)
    ncc, kho, items, bo = "", "Kho Tổng Q2", [], []
    for line in [x.strip() for x in arg.splitlines() if x.strip() and not x.strip().startswith("(")]:
        low = line.lower()
        if low.startswith(("ncc", "xưởng", "xuong", "nhà cung cấp")):
            ncc = line.split(":", 1)[-1].strip(); continue
        if low.startswith("kho"):
            v = line.split(":", 1)[-1].strip().lower()
            kho = next((k2 for k1, k2 in KHO_TEN.items() if k1 in v), kho); continue
        d = doc_dong(line)
        if d and d[2]:
            items.append(d)
        else:
            bo.append(line)
    if not items:
        return tsend(chat, "Chưa đọc được dòng hàng nào. Mẫu:\n" + MAU["hangve"], reply_to=m["message_id"])
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


def cap_nhat_02_05(items, kho):
    """Cộng SL đã nhận vào 02, chuyển 05 sang Còn hàng, xuất file tình trạng cho CSKH. Trả câu tóm tắt."""
    out = []
    try:
        gom = {}
        for mau, size, nums in items:
            thuc = nums[1] if len(nums) >= 2 else nums[0]
            loi = nums[2] if len(nums) >= 3 else 0
            g = gom.setdefault(mau, {"sl": 0, "size": []})
            g["sl"] += thuc - loi
            if size:
                g["size"].append(f"{size}{thuc - loi}")
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
                if khop(mau, str(r.get("Tên sản phẩm", ""))):
                    TG.kho("update", table=TG.sname(TINH), id=r["_id"],
                           fields={"Tình trạng": "Còn hàng", "Cập nhật lúc": today(), "Hàng về dự kiến": "",
                                   "Ghi chú kho": f"Về {datetime.now():%d/%m}: {' '.join(g['size']) or g['sl']}",
                                   "CSKH được nói": "Mẫu này shop đã có hàng, bạn chốt size để shop lên đơn nha"})
                    out.append(f"05: {r.get('Tên sản phẩm')} → Còn hàng")
                    break
        TG._CACHE.clear()
        if out:
            subprocess.run([sys.executable, os.path.join(ROOT, "tools", "lark.py"), "export"], cwd=ROOT,
                           capture_output=True, timeout=120)
    except BaseException as e:
        print("kho_flow: cập nhật 02/05 lỗi", e, flush=True)
    return " · ".join(out)


# ======================= /chotdi =======================

def chotdi(m, arg):
    chat, who = m["chat"]["id"], ten(m.get("from"))
    L, lech_all = [], []
    for line in [x for x in arg.splitlines() if x.strip()]:
        t = line.replace(":", " ").replace("/", " ").split()
        if not t or t[0].lower() not in SAN:
            continue
        san = SAN[t[0].lower()]
        n = [int(x) for x in t[1:] if x.isdigit()] + [0, 0, 0, 0]
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


# ======================= /chothoan =======================

def chothoan(m, arg):
    chat, who = m["chat"]["id"], ten(m.get("from"))
    san_bao, goc = [], {}
    for x in TK.ma_list(arg):
        if x.lower() not in SAN and x.lower() not in san_bao:
            san_bao.append(x.lower()); goc[x.lower()] = x
    if not san_bao:
        return tsend(chat, "Dán danh sách MVĐ sàn báo đã hoàn về kho (mỗi dòng 1 mã). Mẫu:\n" + MAU["chothoan"],
                     reply_to=m["message_id"])
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

def kiemkho(m, arg):
    chat, who = m["chat"]["id"], ten(m.get("from"))
    dot = f"KK{m['message_id']}"
    rows, L, lech_n = [], [], 0
    for line in [x for x in arg.splitlines() if x.strip()]:
        d = doc_dong(line)
        if not d or len(d[2]) < 2:
            continue
        mau, size, nums = d
        nhanh, thuc = nums[0], nums[1]
        lech = thuc - nhanh
        sku = f"{mau}-{size}" if size and "-" in mau else f"{mau} {size}".strip()
        rows.append({"Ngày": today(), "SKU": sku, "Tên mẫu": ten_mau(mau), "Tồn Nhanh": nhanh, "Đếm thực tế": thuc,
                     "Lệch": lech, "Người kiểm": who, "Đợt": dot})
        if lech:
            lech_n += 1
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


def goi_y_kiem(n=5):
    """Mẫu cần kiểm hôm nay: xoay vòng bảng SKU Nhanh (bỏ phụ kiện), ~5 mẫu/ngày."""
    maus = [k for k in sku_bang() if not k.startswith(("PK-", "CB-"))]
    if not maus:
        return []
    i = (datetime.now().timetuple().tm_yday * n) % len(maus)
    return (maus + maus)[i:i + n]


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
    if p["f"] == "kf_nhanh":
        for rid in TK.STATE_KF.get(p["id"], []):
            TG.kho("update", table=TG.sname(NHAP), id=rid, fields={"Đã nhập Nhanh.vn": "✓", "ID phiếu nhập Nhanh": t})
        TG._CACHE.pop(TG.sname(NHAP), None)
        return tsend(chat, f"✅ Đã ghi phiếu nhập Nhanh <code>{esc(t)}</code>", reply_to=m["message_id"])
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
}


def menu(m, arg):
    tsend(m["chat"]["id"],
          "🏬 <b>Việc kho trên Telegram</b> — chép mẫu, điền, gửi 1 tin:\n\n"
          f"📦 <b>Hàng về</b> (ảnh bill để ở chú thích nếu có):\n<code>{esc(MAU['hangve'])}</code>\n\n"
          f"↩️ <b>Nhận hàng hoàn</b>: <code>/hoan MVĐ</code> (nhiều kiện: mỗi dòng 1 MVĐ)\n\n"
          f"🚚 <b>Chốt đơn đi</b> (17h):\n<code>{esc(MAU['chotdi'])}</code>\n\n"
          f"🧾 <b>Đối soát hàng hoàn</b> (17h):\n<code>{esc(MAU['chothoan'])}</code>\n\n"
          f"🔢 <b>Kiểm kho</b>:\n<code>{esc(MAU['kiemkho'])}</code>", reply_to=m["message_id"])


def hen(send=False):
    """Chạy theo lịch: 9h gợi ý kiểm kho + kiện hoàn còn thiếu; 17h nhắc chốt ca; 18h nhắc lại nếu chưa chốt."""
    h = datetime.now().hour
    out = None
    if h < 12:
        maus = goi_y_kiem()
        cho = [r for r in TG.rows(TK.HOAN, fresh=True) if not r.get("Người nhận")]
        mau_kiem = "/kiemkho\n(SKU | tồn Nhanh | đếm thực tế)\n" + "\n".join(f"{k}-{s} " for k in maus for s in (sku_bang()[k][1] or [""]))
        out = ("🔢 <b>Kiểm kho hôm nay</b> (xoay vòng, đếm xong điền tồn Nhanh + số đếm):\n"
               f"<code>{esc(mau_kiem)}</code>")
        if cho:
            out += (f"\n\n↩️ <b>{len(cho)} kiện sàn báo hoàn mà kho chưa nhận</b>:\n"
                    + "\n".join(f"• <code>{esc(r.get('MVĐ'))}</code> (báo {esc(r.get('Sàn báo hoàn'))})" for r in cho[:30])
                    + "\n→ đòi shipper / khiếu nại ĐVVC")
    else:
        da = {r.get("Sàn") for r in TG.rows(DS, fresh=True) if r.get("Ngày") == today()}
        nhan = len([r for r in TG.rows(TK.HOAN, fresh=True) if r.get("Ngày") == today() and r.get("Người nhận")])
        if h >= 18 and {"TikTok", "Shopee"} <= da:
            return print("đã chốt ca, không nhắc")
        out = ("🕔 <b>CHỐT CA</b>" + (" — nhắc lại, chưa thấy chốt" if h >= 18 else "")
               + f"\nHôm nay kho đã quét {nhan} kiện hoàn.\n\n"
               f"1️⃣ Chốt đơn đi:\n<code>{esc(MAU['chotdi'])}</code>\n\n"
               f"2️⃣ Đối soát hàng hoàn: vào Seller Center/Nhanh lấy danh sách đơn đã hoàn hôm nay, dán:\n"
               f"<code>{esc(MAU['chothoan'])}</code>")
    print(re.sub(r"<[^>]+>", "", out))
    if send and kchat():
        tsend(kchat(), out)


def setup():
    TG.kho("setup", tables={TG.sname(KIEM): KIEM_COLS,
                            TG.sname(NHAP): ["Ảnh bill", "Ảnh bill (xem)"]})


TK.EXT_CMDS.update({"/hangve": hangve, "/chotdi": chotdi, "/chothoan": chothoan, "/kiemkho": kiemkho, "/kho": menu})
TK.EXT_CB["kf"] = on_cb
TK.EXT_REPLY.update({"kf_nhanh": on_reply, "kf_lechdi": on_reply})
if not hasattr(TK, "STATE_KF"):
    TK.STATE_KF = {}

if __name__ == "__main__":
    import lark as Lk
    TK.init(Lk.load_env(), start_worker=False)
    a = sys.argv[1:] or ["help"]
    if a[0] == "setup":
        TK.setup(); setup(); print("đã tạo bảng 09, 10, cột ảnh bill")
    elif a[0] == "hen":
        hen("--send" in a)
    else:
        print(__doc__)
