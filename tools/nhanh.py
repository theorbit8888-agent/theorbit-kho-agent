#!/usr/bin/env python3
"""Đọc Nhanh.vn qua trình duyệt trên máy (không cần API): đơn TikTok, Shopee, đơn ngoài sàn, tồn từng SKU.

Dùng 1 hồ sơ Chrome RIÊNG (~/orbit-runtime/nhanh-chrome), không đụng Chrome đang dùng. Chủ shop đăng nhập 1 lần:
  .venv/bin/python tools/nhanh.py login     # mở cửa sổ Chrome, người tự đăng nhập Nhanh, xong tự đóng
Đồng bộ (launchd vn.theorbit.kho-agent.nhanh, 30 phút/lần 7h–23h, chạy ẩn):
  .venv/bin/python tools/nhanh.py sync      # ghi logs/nhanh/products.json + orders.json
Các module khác chỉ ĐỌC file cache (hàm products(), orders(), don_theo_ma()) nên không tranh nhau trình duyệt.
Gọi đúng các đường web Nhanh dùng (POST /order/manage/index, /ecommerce/{tiktok,shopee}/order, /product/item/index)
bằng fetch trong trang đã đăng nhập (cookie + Npos-Csrf-Token-V1). Hết phiên → nhắn chủ shop đăng nhập lại.
"""
import fcntl, json, os, sys, time
from datetime import datetime, timedelta

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PROFILE = os.path.expanduser("~/orbit-runtime/nhanh-chrome")
CACHE = os.path.join(ROOT, "logs", "nhanh")
BIZ = os.environ.get("NHANH_BUSINESS_ID", "199869")
KENH = {"tiktok": "/ecommerce/tiktok/order", "shopee": "/ecommerce/shopee/order", "ngoai": "/order/manage/index"}
TEN_KENH = {"tiktok": "TikTok", "shopee": "Shopee", "ngoai": "Ngoài sàn"}
HOAN_ST = {61, 71, 72, 74}          # Thất bại, Đang hoàn, Đã hoàn, Xác nhận hoàn
CHUA_GUI_ST = {54, 56, 57, 42}      # Mới, Đã xác nhận, Chờ xác nhận, Đang đóng gói
JS = """async ([path, params]) => {
  const csrf = decodeURIComponent((document.cookie.match(/Npos-Csrf-Token-V1=([^;]+)/) || [])[1] || '');
  const r = await fetch(path + '?businessId=' + params.businessId, {method: 'POST', headers: {'Npos-Csrf-Token-V1': csrf,
    'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded'}, body: new URLSearchParams(params)});
  return await r.text();
}"""


class CanDangNhap(Exception):
    pass


# ======================= trình duyệt =======================

def _ctx(pw, headless):
    os.makedirs(PROFILE, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        PROFILE, channel="chrome", headless=headless, locale="vi-VN", viewport={"width": 1400, "height": 900},
        args=["--disable-blink-features=AutomationControlled"])


def login(timeout=1800):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = _ctx(pw, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://nhanh.vn/login")
        print("Mở cửa sổ Chrome riêng: đăng nhập Nhanh.vn (chọn đúng doanh nghiệp The ORBIT). Xong cửa sổ tự đóng.",
              flush=True)
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(3)
            try:
                if dang_nhap_ok(page):
                    print("✅ Đã đăng nhập Nhanh.vn — phiên lưu trong hồ sơ riêng.", flush=True)
                    time.sleep(2)
                    ctx.close()
                    import subprocess  # bật lịch đọc Nhanh 30 phút/lần (plist do install_launchd.sh tạo sẵn)
                    pl = os.path.expanduser("~/Library/LaunchAgents/vn.theorbit.kho-agent.nhanh.plist")
                    if os.path.exists(pl):
                        subprocess.run(["launchctl", "unload", pl], capture_output=True)
                        subprocess.run(["launchctl", "load", pl], capture_output=True)
                    return True
            except Exception:
                pass
        ctx.close()
        print("Hết giờ chờ đăng nhập.", flush=True)
        return False


def dang_nhap_ok(page):
    ck = {c["name"]: c["value"] for c in page.context.cookies("https://nhanh.vn")}
    return bool(ck.get("Npos-Csrf-Token-V1")) and ck.get("isSignin") in ("1", "true") and "/login" not in page.url


class Phien:
    """Mở Chrome ẩn với hồ sơ riêng, gọi đường web Nhanh. Dùng: with Phien() as p: p.call(...)"""

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        os.makedirs(CACHE, exist_ok=True)
        self.lockf = open(os.path.join(CACHE, ".lock"), "w")
        fcntl.flock(self.lockf, fcntl.LOCK_EX)
        self.pw = sync_playwright().start()
        self.ctx = _ctx(self.pw, headless=True)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.goto(f"https://nhanh.vn/product/item/index?businessId={BIZ}", wait_until="domcontentloaded")
        time.sleep(2)
        if "/login" in self.page.url or not dang_nhap_ok(self.page):
            self.__exit__(None, None, None)
            raise CanDangNhap("Phiên Nhanh.vn hết hạn — cần đăng nhập lại")
        return self

    def call(self, path, **params):
        params = {"businessId": BIZ, **{k: str(v) for k, v in params.items()}}
        for lan in range(3):
            txt = self.page.evaluate(JS, [path, params])
            try:
                j = json.loads(txt)
            except ValueError:
                if "login" in txt[:500].lower():
                    raise CanDangNhap("Nhanh trả về trang đăng nhập")
                time.sleep(2); continue
            if j.get("code") == 1:
                return j.get("data") or {}
            time.sleep(2)
        raise RuntimeError(f"Nhanh lỗi {path}: {str(j)[:200]}")

    def pages(self, path, max_pages=80, **params):
        out, p, tong = [], 1, 1
        while p <= tong and p <= max_pages:
            d = self.call(path, page=p, **params)
            out += d.get("result") or []
            tong = int(d.get("totalPages") or 1)
            p += 1
            time.sleep(0.4)
        return out

    def __exit__(self, *a):
        for f in (lambda: self.ctx.close(), lambda: self.pw.stop()):
            try:
                f()
            except Exception:
                pass
        try:
            fcntl.flock(self.lockf, fcntl.LOCK_UN); self.lockf.close()
        except Exception:
            pass


# ======================= đồng bộ =======================

def gon_don(o, kenh):
    i, c, ch = o.get("info") or {}, o.get("carrier") or {}, o.get("channel") or {}
    return {"id": str(i.get("id")), "kenh": kenh, "ma_san": str(ch.get("apiOrderId") or ""),
            "mvd": str(c.get("carrierCode") or ""), "dvvc": c.get("name") or "", "st": i.get("status"),
            "st_ten": i.get("statusName") or "", "tao": i.get("createdDateTime") or "",
            "cap_nhat": i.get("updatedDateTime") or "", "gui_dvvc": c.get("sendCarrierDate") or "",
            "kho": (o.get("depot") or {}).get("name") or "",
            "sp": [{"ma": p.get("code"), "sl": p.get("quantity")} for p in (o.get("products") or [])]}


def sync(ngay=14):
    d0 = (datetime.now() - timedelta(days=ngay)).strftime("%Y-%m-%d")
    d1 = datetime.now().strftime("%Y-%m-%d")
    with Phien() as p:
        sps = p.pages("/product/item/index", max_pages=60)
        prods = {x["code"]: {"ten": x.get("name"), "ton": x.get("remain"), "trong_kho": x.get("remainInDepot"),
                             "co_the_ban": x.get("available"), "dang_giao": x.get("shipping"),
                             "giu": x.get("holding"), "loi": x.get("damaged")}
                 for x in sps if x.get("code") and not x.get("childCount")}
        dons = {}
        for k, path in KENH.items():
            for o in p.pages(path, max_pages=80, fromDate=d0, toDate=d1):
                g = gon_don(o, k)
                dons[g["id"]] = g
    meta = _doc("meta.json") or {}
    meta.setdefault("bat_dau", datetime.now().strftime("%Y-%m-%d %H:%M"))
    meta.update(dong_bo=datetime.now().strftime("%Y-%m-%d %H:%M"), so_sp=len(prods), so_don=len(dons), loi="")
    _ghi("products.json", prods); _ghi("orders.json", dons); _ghi("meta.json", meta)
    return meta


def _ghi(name, obj):
    os.makedirs(CACHE, exist_ok=True)
    tmp = os.path.join(CACHE, name + ".tmp")
    json.dump(obj, open(tmp, "w"), ensure_ascii=False)
    os.replace(tmp, os.path.join(CACHE, name))


def _doc(name):
    try:
        return json.load(open(os.path.join(CACHE, name)))
    except (FileNotFoundError, ValueError):
        return None


def nhap(thu_muc="~/Downloads"):
    """Nhận file orbit-nhanh-sync-*.json do nhanh_sync.js tải về (đọc từ Chrome đang đăng nhập của chủ shop),
    ghi vào cache, xoá file tải về. Trả meta hoặc None nếu không có file."""
    import glob
    fs = sorted(glob.glob(os.path.join(os.path.expanduser(thu_muc), "orbit-nhanh-sync-*.json")), key=os.path.getmtime)
    if not fs:
        return None
    d = json.load(open(fs[-1]))
    for f in fs:
        os.remove(f)
    m = _doc("meta.json") or {}
    m.setdefault("bat_dau", d["dong_bo"])
    m.update(dong_bo=d["dong_bo"], so_sp=len(d["products"]), so_don=len(d["orders"]), loi="", nguon="chrome")
    _ghi("products.json", d["products"]); _ghi("orders.json", d["orders"]); _ghi("meta.json", m)
    return m


# ======================= đọc cache (module khác dùng) =======================

def meta():
    return _doc("meta.json") or {}


def products():
    return _doc("products.json") or {}


def orders():
    return _doc("orders.json") or {}


def con_moi(phut=120):
    m = meta()
    try:
        return (datetime.now() - datetime.strptime(m["dong_bo"], "%Y-%m-%d %H:%M")).total_seconds() < phut * 60
    except (KeyError, ValueError):
        return False


def don_theo_ma(ma):
    """Tìm đơn theo MVĐ / mã đơn sàn / ID Nhanh. Mã tem hoàn (khác MVĐ gửi) → đơn gốc qua sổ logs/ma_hoan.json."""
    k = chuan_ma(ma)
    for kk in (k, goc_hoan(k).lower()):
        for o in orders().values():
            if kk and kk in (o["mvd"].lower(), o["ma_san"].lower(), o["id"]):
                return o
    return None


# ---- mã tem HOÀN → đơn gốc -------------------------------------------------------------------------------------
# Khách trả hàng: ĐVVC dán tem hoàn MỚI (TikTok 854…, Shopee SPXVN0… 17 số) ≠ MVĐ lúc gửi → kho quét /hoan bằng tem này.
# Tác vụ lịch 8h30/15h30 tra mã đó trên trang Trả hàng của sàn (ô tìm kiếm "Mã vận đơn trả hàng", chỉ đọc) → ghi sổ.
# JT hoàn đơn ngoài sàn dán tem "<MVĐ>-001" → bỏ đuôi.
MA_HOAN_F = os.path.join(ROOT, "logs", "ma_hoan.json")


def chuan_ma(ma):
    import re
    return re.sub(r"-\d{3}$", "", str(ma or "").strip().lower().lstrip("#"))


def ma_hoan():
    try:
        return json.load(open(MA_HOAN_F, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def goc_hoan(ma):
    """Mã tem hoàn → mã đơn sàn gốc ('' nếu chưa tra được)."""
    return (ma_hoan().get(chuan_ma(ma)) or {}).get("ma_san", "")


def ghi_ma_hoan(cap, kenh):
    """cap = {mã tem hoàn: mã đơn sàn}. Chỉ ghi khi ra đúng 1 đơn. Trả số mã mới ghi."""
    import re
    d, moi = ma_hoan(), 0
    for k, v in cap.items():
        k, v = chuan_ma(k), str(v or "").strip()
        if k and re.fullmatch(r"[0-9A-Z]{10,20}", v) and (d.get(k) or {}).get("ma_san") != v:
            d[k] = {"ma_san": v, "kenh": kenh, "luc": datetime.now().strftime("%Y-%m-%d %H:%M")}
            moi += 1
    tmp = MA_HOAN_F + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, MA_HOAN_F)
    return moi


def nhap_tra():
    """{ID đơn Nhanh: phiếu nhập trả} — đơn đã được kho nhập trả trên Nhanh (gồm đơn trả '<mã sàn>R')."""
    return _doc("nhap_tra.json") or {}


def don_tra(ngay=14):
    """Khách TRẢ HÀNG đã nhập trả trên Nhanh: Nhanh tạo đơn trả '<mã đơn sàn>R' (không MVĐ) kèm phiếu nhập trả."""
    return [o for o in orders().values() if o["ma_san"].endswith("R") and o["st"] in HOAN_ST
            and (_ngay(o["tao"]) or datetime.now().date()) >= datetime.now().date() - timedelta(days=ngay)]


def ton_sku(sku):
    return products().get(str(sku).upper()) or products().get(str(sku))


def bung_combo(ma, sl=1):
    """SKU combo CB-… → [(SKU con, SL)] (theo thành phần combo trên Nhanh); SKU thường → [(ma, sl)]."""
    p = products().get(str(ma)) or {}
    if p.get("combo"):
        return [(c["ma"], (c.get("sl") or 1) * sl) for c in p["combo"]]
    return [(str(ma), sl)]


def ton_combo(ma):
    """Số combo bán được = min(có thể bán SP con // SL trong combo). None nếu không phải combo / thiếu dữ liệu."""
    p = products().get(str(ma)) or {}
    if not p.get("combo"):
        return None
    xs = []
    for c in p["combo"]:
        con = products().get(c["ma"]) or {}
        if con.get("co_the_ban") is None:
            return None
        xs.append(max(0, int(con["co_the_ban"])) // max(1, int(c.get("sl") or 1)))
    return min(xs) if xs else None


def link_sp(sku):
    import urllib.parse
    return f"https://nhanh.vn/product/item/index?name={urllib.parse.quote(sku)}&businessId={BIZ}"


def _ngay(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def chot_ca():
    """Số đơn từng kênh: chưa gửi (theo trạng thái), đã giao ĐVVC hôm nay."""
    hn = datetime.now().date()
    out = {}
    for o in orders().values():
        k = out.setdefault(o["kenh"], {"chua_gui": [], "gui_hom_nay": 0})
        if o["st"] in CHUA_GUI_ST:
            k["chua_gui"].append(o)
        # đơn sàn không có ngày gửi ĐVVC → coi "chuyển sang Đang chuyển (59) hôm nay" là đã bàn giao hôm nay
        if _ngay(o["gui_dvvc"]) == hn or (o["st"] == 59 and _ngay(o["cap_nhat"]) == hn):
            k["gui_hom_nay"] += 1
    return out


def hang_hoan(ngay=14):
    """Đơn đang/đã hoàn trên Nhanh (từ lúc bot bắt đầu theo dõi, tối đa `ngay` ngày)."""
    m = meta()
    moc = max(datetime.now().date() - timedelta(days=ngay), _ngay(m.get("bat_dau", "")) or datetime.now().date())
    return [o for o in orders().values() if o["st"] in HOAN_ST and o["mvd"] and (_ngay(o["cap_nhat"]) or moc) >= moc]


# ======================= chạy =======================

def bao_loi(msg):
    """Hết phiên / lỗi: nhắn chủ shop tối đa 1 lần / 6 giờ."""
    m = meta()
    try:
        last = datetime.strptime(m.get("bao_loi_luc", "2000-01-01 00:00"), "%Y-%m-%d %H:%M")
    except ValueError:
        last = datetime(2000, 1, 1)
    m["loi"] = msg
    if (datetime.now() - last).total_seconds() > 6 * 3600:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import lark as Lk, ticket as TK
            TK.init(Lk.load_env(), start_worker=False)
            for u in TK.duyet_ids():
                goi_y = ("Bot đọc Nhanh qua API: báo Claude kiểm tra; nếu mã hết hạn/bị thu hồi thì gõ <b>/ketnoinhanh</b> để nối lại."
                         if "API" in msg else "Nhắn <b>/dangnhapnhanh</b> cho bot kho khi đang ngồi máy Mac — bot mở cửa sổ "
                         "để anh/chị đăng nhập lại.")
                TK.tsend(u, f"⚠️ Bot kho không đọc được Nhanh.vn: {TK.esc(msg)}\n{goi_y}")
            m["bao_loi_luc"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        except BaseException as e:
            print("không nhắn được:", e)
    _ghi("meta.json", m)


def gmv_nv(tu, den):
    """GMV bán lẻ theo người bán từ hoá đơn Nhanh (/pos/bill/index): NV bán hàng nếu có gắn, không thì người tạo
    hoá đơn (NVBH đứng quầy). Hoá đơn trả trừ ra. -> {tên đầy đủ: {"gmv", "hd"}}; ghi thêm logs/nhanh/gmv_nv.json."""
    out = {}
    with Phien() as ph:
        for b in ph.pages("/pos/bill/index", max_pages=60, fromDate=tu, toDate=den):
            i = b.get("info") or {}
            ai = (i.get("saleName") or i.get("createdByName") or "").strip()
            if not ai:
                continue
            tien = float((b.get("payment") or {}).get("totalAmount") or 0)
            dau = -1 if "trả" in str(i.get("typeName", "")).lower() else 1
            x = out.setdefault(ai, {"gmv": 0.0, "hd": 0})
            x["gmv"] += dau * tien; x["hd"] += 1
    _ghi("gmv_nv.json", {"tu": tu, "den": den, "luc": datetime.now().strftime("%Y-%m-%d %H:%M"), "nv": out})
    return out


def sau_sync():
    """Đồng bộ xong: báo nhóm Kho đơn vừa huỷ sau khi in (rút kiện trước khi shipper tới)."""
    import subprocess
    try:
        subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "xuat_kho.py"),
                        "canhhuy", "--send"], timeout=120)
    except Exception as e:
        print("canh huy loi:", e)
    try:   # hàng về đã nhập Nhanh chưa / nhập đúng số chưa (đối chiếu phiếu nhập)
        subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kho_flow.py"),
                        "nhapnhanh", "--send"], timeout=180)
    except Exception as e:
        print("doi chieu nhap loi:", e)
    try:   # sổ huỷ sau in / yêu cầu hoàn lên Sheet (chủ shop 14/11)
        subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "so_sheet.py"),
                        "dongbo"], timeout=300)
    except Exception as e:
        print("so_sheet loi:", e)


if __name__ == "__main__":
    a = sys.argv[1:] or ["help"]
    if a[0] == "gmv":   # nhanh.py gmv YYYY-MM-DD YYYY-MM-DD -> JSON (bot HCNS xếp rank NVBH)
        import nhanh_api as NA
        if NA.co_api():
            print(json.dumps(NA.gmv_nv(a[1], a[2]), ensure_ascii=False)); sys.exit(0)
        try:
            print(json.dumps(gmv_nv(a[1], a[2]), ensure_ascii=False))
        except CanDangNhap as e:
            print(json.dumps({"_loi": "chua_dang_nhap"})); sys.exit(2)
        sys.exit(0)
    if a[0] == "login":
        sys.exit(0 if login() else 1)
    elif a[0] == "sync":
        import nhanh_api as NA
        if NA.co_api():   # có Open API: đọc thẳng máy chủ Nhanh, 24/24, không cần Chrome
            try:
                print(NA.sync())
            except Exception as e:
                bao_loi(f"lỗi API Nhanh: {e}"[:300]); raise
            sau_sync()
            sys.exit(0)
        if "--gio" in a and not (7 <= datetime.now().hour < 23):
            sys.exit(0)
        try:
            print(sync())
        except CanDangNhap as e:
            bao_loi(str(e)); sys.exit(2)
        except Exception as e:
            bao_loi(f"lỗi đồng bộ: {e}"[:300]); raise
        sau_sync()
    elif a[0] == "nhap":
        print(nhap() or "không có file orbit-nhanh-sync-*.json trong Downloads")
    elif a[0] == "xem":
        m = meta(); print(m)
        cc = chot_ca()
        for k, v in cc.items():
            print(TEN_KENH.get(k, k), "chưa gửi", len(v["chua_gui"]), "gửi hôm nay", v["gui_hom_nay"])
        print("hàng hoàn theo dõi:", len(hang_hoan()))
    else:
        print(__doc__)
