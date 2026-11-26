#!/usr/bin/env python3
"""SỔ TRÊN GOOGLE SHEET "KHO DỮ LIỆU" — chủ shop chốt 14/11/2026: mọi dữ liệu CSKH + kho (đổi, hoàn, huỷ…)
phải nằm trên Sheet để tự kiểm lại. Bảng đơn đổi/trả có Tên/SĐT/Địa chỉ KH (chủ shop 16/11/2026) — Sheet riêng, không dán vào nhóm.

Bảng (trên Sheet có tiền tố "SP "):
  DD · ĐƠN ĐỔI           agent CSKH ghi bằng lệnh `add` (mỗi món đổi 1 dòng; trùng mã sàn + SKU cũ thì sửa dòng cũ)
  YH · YÊU CẦU HOÀN SÀN  đồng bộ từ logs/hoan_san.json (+ kho đã duyệt/khiếu nại, giờ /hoan)
  HU · HỦY SAU IN        đồng bộ từ logs/huy_sau_in.json
  (Hàng hoàn về /hoan đã có ở 09 · HÀNG HOÀN NHẬN.)
Đồng bộ chỉ gửi dòng đổi (băm nội dung, nhớ ở logs/so_sheet.json). Tự chạy: cuối mỗi lượt hoan_san + sau mỗi lần đồng bộ Nhanh.

  python3 tools/so_sheet.py add [--loai doi|tra] --ma-san X [--kenh tiktok|shopee|web|meta|zalo|store] [--ma-nhanh N] [--mvd JT…] --sku-cu A --sku-moi B
                                [--phi 25000|0] [--ly-do "đổi size"] --ten "Tên KH" --sdt 09… --dc "Địa chỉ" [--nvbh "Tên NV đã kiểm"] [--nguoi "ai ghi"] [--ngay YYYY-MM-DD]
  python3 tools/so_sheet.py xem <mã sàn|mã Nhanh>   # đọc lại dòng vừa ghi
  python3 tools/so_sheet.py dongbo      # đồng bộ YH + HU
  python3 tools/so_sheet.py setup       # tạo/thêm cột 3 bảng
"""
import hashlib, json, os, re, sys
from datetime import datetime, timedelta

import orbit_tg as TG

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CACHE = os.path.join(ROOT, "logs", "so_sheet.json")

DOI = "DD · ĐƠN ĐỔI"
DOI_COLS = ["Ngày", "Loại", "Kênh", "Mã đơn sàn", "Mã đơn Nhanh", "MVĐ J&T", "SKU cũ", "SKU mới", "Phí đổi", "Lý do",
            "Tên KH", "SĐT KH", "Địa chỉ KH", "NVBH đã kiểm", "Người ghi", "Ghi lúc", "Ghi chú"]
YC = "YH · YÊU CẦU HOÀN SÀN"
YC_COLS = ["Mã yêu cầu", "Kênh", "Loại", "Lý do khách", "Trạng thái sàn", "Việc shop", "MVĐ", "Hạn sàn",
           "Kiện về shop", "Kho /hoan lúc", "Kho xử lý", "Kho xử lý lúc", "Bot thấy lần đầu", "Bot thấy lần cuối",
           "Còn trên trang sàn"]
HUY = "HU · HỦY SAU IN"
HUY_COLS = ["Mã đơn Nhanh", "Mã đơn sàn", "MVĐ", "Kênh", "Ngày huỷ", "Bot thấy lúc", "Lý do huỷ", "Kho đã giữ lại",
            "Kho giữ lúc"]
VIEC = {"phan_hoi": "Phản hồi yêu cầu", "xac_nhan": "Xác nhận hàng trả về", "bang_chung": "Gửi bằng chứng",
        "dang_tra": "Khách đang gửi trả", "khang_nghi": "Sàn đã hoàn (còn quyền kháng nghị)",
        "kiem_hang": "Sàn đã hoàn (kiểm hàng)"}
TEN = {"tiktok": "TikTok", "shopee": "Shopee", "web": "Web", "meta": "Meta", "facebook": "Meta", "zalo": "Zalo", "store": "Store"}
SDT = re.compile(r"(?<!\d)(0|\+?84)\d{8,10}(?!\d)")


def _doc(f, mac=None):
    try:
        return json.load(open(f))
    except Exception:
        return {} if mac is None else mac


def _ghi(f, d):
    os.makedirs(os.path.dirname(f), exist_ok=True)
    json.dump(d, open(f + ".tmp", "w"), ensure_ascii=False, indent=1)
    os.replace(f + ".tmp", f)


def setup():
    TG.kho("setup", tables={TG.sname(DOI): DOI_COLS, TG.sname(YC): YC_COLS, TG.sname(HUY): HUY_COLS})


def _bam(r):
    return hashlib.md5(json.dumps(r, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def _upsert(bang, khoa, rows, het=None):
    """rows: [dict có cột khoa]. Chỉ gửi dòng mới/đổi. het: {cột: giá trị} ghi cho dòng đã có mà lần này không còn."""
    cache = _doc(CACHE)
    c = cache.get(bang)
    if c is None:                      # lần đầu: map dòng đã có trên Sheet
        setup()
        c = {str(r.get(khoa)): [r["_id"], ""] for r in TG.rows(bang, fresh=True) if r.get(khoa)}
    moi, sua = [], 0
    thay = set()
    for r in rows:
        k, h = str(r[khoa]), _bam(r)
        thay.add(k)
        if k in c:
            if c[k][1] != h:
                TG.kho("update", table=TG.sname(bang), id=c[k][0], fields=r)
                c[k][1], sua = h, sua + 1
        else:
            moi.append((k, r, h))
    if het:
        for k, v in c.items():
            if k not in thay and v[1] != "het":
                TG.kho("update", table=TG.sname(bang), id=v[0], fields=het)
                v[1], sua = "het", sua + 1
    for i in range(0, len(moi), 50):
        part = moi[i:i + 50]
        ids = TG.kho("add", table=TG.sname(bang), rows=[r for _, r, _ in part])
        for (k, _, h), rid in zip(part, ids):
            c[k] = [rid, h]
    cache[bang] = c
    _ghi(CACHE, cache)
    return len(moi), sua


def _gio(s):
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(str(s)[:19 if f.endswith("S") else 16], f)
        except ValueError:
            pass
    return None


def dong_yc():
    import hoan_san as HS
    st, luc = HS._doc(HS.STATE), HS._doc(HS.KHO_LUC)
    rows = []
    for m, v in st.items():
        xl = HS.da_xu_ly(dict(v, ma=m)) or {}
        han = ""
        if v.get("han_gio") is not None and _gio(v.get("lan_cuoi")):
            han = (_gio(v["lan_cuoi"]) + timedelta(hours=float(v["han_gio"]))).strftime("%Y-%m-%d %H:%M")
        mvd = str(v.get("mvd") or "")
        rows.append({
            "Mã yêu cầu": str(m), "Kênh": TEN.get(v.get("kenh"), v.get("kenh") or ""), "Loại": v.get("loai") or "",
            "Lý do khách": v.get("ly_do") or "", "Trạng thái sàn": v.get("tt") or "",
            "Việc shop": VIEC.get(v.get("nut"), v.get("nut") or ""), "MVĐ": mvd, "Hạn sàn": han,
            "Kiện về shop": v.get("lan_ve") or "",
            "Kho /hoan lúc": v.get("lan_kho") or next((x for t, x in luc.items() if mvd and t.lower() == mvd.lower()), ""),
            "Kho xử lý": HS.xl_txt(xl["xl"]) if xl.get("xl") else "", "Kho xử lý lúc": xl.get("luc", ""),
            "Bot thấy lần đầu": v.get("lan_dau") or "", "Bot thấy lần cuối": v.get("lan_cuoi") or "",
            "Còn trên trang sàn": "có"})
    rows = [{k: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for k, v in r.items()} for r in rows]
    return _upsert(YC, "Mã yêu cầu", rows, het={"Còn trên trang sàn": "không"} if rows else None)


def dong_huy():
    import xuat_kho as XK
    rows = []
    for k, v in _doc(XK.HUY_F).items():
        g = v.get("giu") or {}
        rows.append({"Mã đơn Nhanh": str(k), "Mã đơn sàn": str(v.get("ma_san") or ""), "MVĐ": str(v.get("ma") or ""),
                     "Kênh": TEN.get(v.get("kenh"), v.get("kenh") or ""), "Ngày huỷ": v.get("huy") or "",
                     "Bot thấy lúc": v.get("thay") or "", "Lý do huỷ": v.get("st_ten") or "",
                     "Kho đã giữ lại": g.get("who", "") if g else "", "Kho giữ lúc": g.get("luc", "") if g else ""})
    return _upsert(HUY, "Mã đơn Nhanh", rows)


def dong_bo():
    out = {}
    for ten, f in (("YH", dong_yc), ("HU", dong_huy)):
        try:
            out[ten] = f()
        except BaseException as e:      # TG.kho() có thể sys.exit
            out[ten] = f"lỗi: {e}"
    return out


def add(a):
    def lay(k, mac=""):
        return a[a.index(k) + 1].strip() if k in a and a.index(k) + 1 < len(a) else mac
    r = {"Ngày": lay("--ngay", datetime.now().strftime("%Y-%m-%d")), "Loại": {"tra": "Trả", "trả": "Trả"}.get(lay("--loai").lower(), "Đổi"),
         "Kênh": TEN.get(lay("--kenh").lower(), lay("--kenh")),
         "Mã đơn sàn": lay("--ma-san"), "Mã đơn Nhanh": lay("--ma-nhanh"), "MVĐ J&T": lay("--mvd"),
         "SKU cũ": lay("--sku-cu").upper(), "SKU mới": lay("--sku-moi").upper(), "Phí đổi": lay("--phi"),
         "Lý do": lay("--ly-do"), "Tên KH": lay("--ten"), "SĐT KH": lay("--sdt"), "Địa chỉ KH": lay("--dc"), "NVBH đã kiểm": lay("--nvbh"), "Người ghi": lay("--nguoi", "agent CSKH"),
         "Ghi lúc": datetime.now().strftime("%Y-%m-%d %H:%M"), "Ghi chú": lay("--ghi-chu")}
    if not (r["Mã đơn sàn"] or r["Mã đơn Nhanh"]) or (r["Loại"] == "Đổi" and not r["SKU mới"]):
        sys.exit("thiếu: cần --ma-san (hoặc --ma-nhanh); đơn đổi cần thêm --sku-moi")
    if any(SDT.search(r[c]) for c in ("Lý do", "Ghi chú", "NVBH đã kiểm")):
        sys.exit("không ghi SĐT khách lên Sheet — bỏ số điện thoại khỏi lý do/ghi chú")
    if r["Phí đổi"]:
        p = re.sub(r"[^\d]", "", r["Phí đổi"].lower().replace("k", "000"))
        r["Phí đổi"] = p or r["Phí đổi"]
    setup()
    ma = r["Mã đơn sàn"] or r["Mã đơn Nhanh"]
    cu = next((x for x in TG.rows(DOI, fresh=True)
               if (str(x.get("Mã đơn sàn") or x.get("Mã đơn Nhanh")) == ma) and str(x.get("SKU cũ") or "") == r["SKU cũ"]), None)
    f = {k: v for k, v in r.items() if v != ""}
    if cu:
        if "--ngay" not in a:           # sửa dòng cũ: giữ ngày đổi ban đầu
            f.pop("Ngày", None)
        if "--nguoi" not in a:
            f.pop("Người ghi", None)
        TG.kho("update", table=TG.sname(DOI), id=cu["_id"], fields=f)
        return "sửa", cu["_id"]
    return "thêm", TG.kho("add", table=TG.sname(DOI), rows=[f])[0]


if __name__ == "__main__":
    import lark as Lk, ticket as TK
    TK.init(Lk.load_env(), start_worker=False)
    a = sys.argv[1:] or ["help"]
    if a[0] == "add":
        kq, rid = add(a[1:])
        print(f"đã {kq} 1 dòng ở bảng SP {DOI} ({rid})")
    elif a[0] == "xem" and len(a) > 1:
        hit = [x for x in TG.rows(DOI, fresh=True) if a[1] in (str(x.get("Mã đơn sàn")), str(x.get("Mã đơn Nhanh")))]
        for x in hit:
            print({c: x.get(c) for c in DOI_COLS if x.get(c) not in (None, "")})
        print(f"{len(hit)} dòng")
    elif a[0] == "dongbo":
        print(dong_bo())
    elif a[0] == "setup":
        setup(); print("ok")
    else:
        print(__doc__)
