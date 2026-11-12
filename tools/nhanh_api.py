#!/usr/bin/env python3
"""Đọc Nhanh.vn qua Open API v3 (không cần Chrome, không bị Cloudflare). Ghi cùng định dạng cache với nhanh.py sync
(logs/nhanh/products.json, orders.json, meta.json) nên mọi chỗ khác của bot dùng y nguyên.

Mã lấy bằng tools/ket-noi-nhanh-api.sh (chủ shop chạy) → ~/.config/orbit-kho/nhanh_api.env
(NHANH_APP_ID, NHANH_SECRET, NHANH_ACCESS_TOKEN, NHANH_BUSINESS_ID, NHANH_HET_HAN). Token sống 1 năm, không refresh.
Tài liệu: https://developers.nhanh.group/pos/  ·  giới hạn 150 lần gọi / 30 giây / URL.
"""
import json, os, time, urllib.request, urllib.error
from datetime import datetime, timedelta

ENV = os.path.expanduser("~/.config/orbit-kho/nhanh_api.env")
BASE = "https://pos.open.nhanh.vn/v3.0"
KENH_ID = {48: "tiktok", 42: "shopee"}   # còn lại (Admin/Website/Facebook/Zalo…) = "ngoai"
TEN_ST = {40: "Đã đóng gói", 42: "Đang đóng gói", 43: "Chờ thu gom", 54: "Đơn mới", 55: "Đang xác nhận", 56: "Đã xác nhận",
          57: "Chờ khách xác nhận", 58: "Hãng vận chuyển hủy đơn", 59: "Đang chuyển", 60: "Thành công", 61: "Thất bại",
          63: "Khách hủy", 64: "Hệ thống hủy", 68: "Hết hàng", 71: "Đang chuyển hoàn", 72: "Đã chuyển hoàn",
          73: "Đổi kho xuất hàng", 74: "Xác nhận hoàn"}


def env():
    d = {}
    if os.path.exists(ENV):
        for line in open(ENV):
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                d[k] = v
    return d


def co_api():
    e = env()
    return bool(e.get("NHANH_APP_ID") and e.get("NHANH_ACCESS_TOKEN") and e.get("NHANH_BUSINESS_ID"))


class LoiApi(Exception):
    pass


def goi(path, body):
    e = env()
    url = f"{BASE}/{path}?appId={e['NHANH_APP_ID']}&businessId={e['NHANH_BUSINESS_ID']}"
    for lan in range(4):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": e["NHANH_ACCESS_TOKEN"], "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                j = json.load(r)
        except urllib.error.HTTPError as x:
            try:
                j = json.loads(x.read().decode() or "{}")
            except Exception:
                j = {"code": 0, "messages": f"HTTP {x.code}"}
        except Exception as x:
            j = {"code": 0, "messages": repr(x)[:200]}
        if j.get("code") == 1:
            return j
        if j.get("errorCode") == "ERR_429":   # bị khoá tạm: chờ tới unlockedAt
            cho = max(5, int((j.get("data") or {}).get("unlockedAt", time.time() + 30) - time.time()) + 2)
            time.sleep(min(cho, 120)); continue
        msg = str(j.get("messages", ""))
        if lan < 3 and ("HTTP 5" in msg or msg.startswith(("URLError", "TimeoutError", "timeout"))):
            time.sleep(3); continue
        raise LoiApi(f"{path}: {j.get('errorCode') or ''} {j.get('messages')}"[:300])
    raise LoiApi(f"{path}: thử 4 lần không được")


def tat_ca(path, filters, size=100, toi_da=200, extra=None, sort=True):
    out, nxt, n = [], None, 0
    while n < toi_da:
        body = {"filters": filters, "paginator": {"size": size}}
        if sort:   # order/list không cho sort (mặc định id giảm dần)
            body["paginator"]["sort"] = {"id": "desc"}
        if nxt:
            body["paginator"]["next"] = nxt
        if extra:
            body.update(extra)
        j = goi(path, body)
        out += j.get("data") or []
        nxt = (j.get("paginator") or {}).get("next")
        n += 1
        if not nxt:
            break
        time.sleep(0.25)
    return out


def _gio(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
    except (TypeError, ValueError):
        return str(ts or "")


def _so(x):
    try:
        f = float(x)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return None


def products():
    prods = {}
    for x in tat_ca("product/list", {"gpid": 3}):   # sản phẩm con + sản phẩm đơn (bỏ sản phẩm cha)
        if not x.get("code"):
            continue
        inv = x.get("inventory") or {}
        prods[x["code"]] = {"ten": x.get("name"), "ton": _so(inv.get("remain")), "trong_kho": _so(inv.get("remain")),
                            "co_the_ban": _so(inv.get("available")), "dang_giao": _so(inv.get("shipping")),
                            "giu": _so(inv.get("holding")), "loi": _so(inv.get("damaged"))}
    return prods


def orders(ngay=14):
    tu = int((datetime.now() - timedelta(days=ngay)).timestamp())
    dons = {}
    for o in tat_ca("order/list", {"createdAtFrom": tu, "createdAtTo": int(time.time())}, toi_da=400, sort=False):
        i, c, ch = o.get("info") or {}, o.get("carrier") or {}, o.get("channel") or {}
        dons[str(i.get("id"))] = {
            "id": str(i.get("id")), "kenh": KENH_ID.get(_so(ch.get("saleChannel")), "ngoai"),
            "ma_san": str(ch.get("appOrderId") or ""), "mvd": str(c.get("carrierCode") or ""), "dvvc": c.get("name") or "",
            "st": _so(i.get("status")), "st_ten": i.get("statusName") or TEN_ST.get(_so(i.get("status")), ""), "tao": _gio(i.get("createdAt")),
            "cap_nhat": _gio(i.get("updatedAt")), "gui_dvvc": _gio(c.get("sendCarrierAt")), "kho": str(i.get("depotId") or ""),
            "sp": [{"ma": p.get("code"), "sl": _so(p.get("quantity"))} for p in (o.get("products") or [])]}
    return dons


def sync(ngay=14):
    import nhanh as NH
    prods, dons = products(), orders(ngay)
    m = NH.meta() or {}
    m.setdefault("bat_dau", datetime.now().strftime("%Y-%m-%d %H:%M"))
    m.update(dong_bo=datetime.now().strftime("%Y-%m-%d %H:%M"), so_sp=len(prods), so_don=len(dons), loi="", nguon="api")
    NH._ghi("products.json", prods); NH._ghi("orders.json", dons); NH._ghi("meta.json", m)
    return m


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if not co_api():
        print("Chưa có mã API Nhanh → chủ shop chạy: bash ~/kho-agent/tools/ket-noi-nhanh-api.sh"); sys.exit(2)
    print(sync())
