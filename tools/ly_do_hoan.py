#!/usr/bin/env python3
"""THỐNG KÊ LÝ DO HOÀN THEO MẪU — mỗi thứ 2 (CEO 14/11/2026, phương án hậu mãi TikTok mục E).

Gom 1 tuần (thứ 2 → CN) từ 4 nguồn, mỗi đơn tính 1 ca (trùng nguồn thì lấy lý do rõ nhất):
  1. Sổ lý do sàn `logs/hoan_ly_do.json` (hoan_san.py ghi mỗi lần đọc trang Trả hàng TikTok/Shopee: lý do khách chọn).
  2. Ticket CS (bảng TK · TICKET CS): Loại + Lý do + SKU khách đang cầm.
  3. Nhanh: đơn trả `<mã sàn>R` (khách trả hàng) + đơn hoàn ĐVVC/giao thất bại (st 61/71/72/74) → SKU trong đơn.
  4. Bảng 09 · HÀNG HOÀN NHẬN: kho kiểm thấy lỗi/tráo/thiếu.
Ra bảng theo MẪU (bỏ size), mẫu nào ≥3 ca cùng lý do trong tuần → ⚠️ (CEO họp R&D + ads).
  python3 tools/ly_do_hoan.py [--tuan YYYY-MM-DD (ngày bất kỳ trong tuần, mặc định tuần trước)] [--ghi]
--ghi: ghi/thay mục tuần đó trong ~/Desktop/ceo-agent/theo-doi/ly-do-hoan.md (không có cờ = chỉ in).
Bot gọi tự động lúc nhắc ticket 9h sáng thứ 2 (ticket.nhac --send).
"""
import json, os, re, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import nhanh as NH

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SO = os.path.join(ROOT, "logs", "hoan_ly_do.json")
OUT = os.path.expanduser("~/Desktop/ceo-agent/theo-doi/ly-do-hoan.md")
NGUONG = 3


def ghi_so(ds, kenh):
    """hoan_san gọi: [{ma, ly_do, loai}] → sổ (chỉ thêm, giữ lần đầu thấy)."""
    try:
        so = json.load(open(SO))
    except Exception:
        so = {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for x in ds:
        if x.get("ma") and x["ma"] not in so:
            so[x["ma"]] = {"kenh": kenh, "ly_do": (x.get("ly_do") or "").strip(), "loai": x.get("loai", ""), "luc": now}
    os.makedirs(os.path.dirname(SO), exist_ok=True)
    tmp = SO + ".tmp"
    json.dump(so, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, SO)


def mau_cua(sku):
    """SKU → (mã mẫu bỏ size, tên mẫu)."""
    sku = str(sku or "").strip().upper()
    if not sku:
        return "", ""
    p = NH.products() if NH.meta() else {}
    ten = re.sub(r"\s*-\s*(XXL|XL|L|M|S|FREE ?SIZE|\d{2})\s*$", "", (p.get(sku) or {}).get("ten", ""), flags=re.I)
    ma = re.sub(r"-(XXL|XL|L|M|S|FS|\d{2})$", "", sku)
    return ma, ten or ma


def _sp_don(ma):
    o = NH.don_theo_ma(ma) if NH.meta() and ma else None
    if not o:
        return None, []
    out = []
    for s in o.get("sp", []):
        for m, _ in NH.bung_combo(s["ma"], s.get("sl", 1)):
            if not str(m).upper().startswith("PK-"):      # bỏ phụ kiện/quà tặng
                out.append(m)
    return o, out


def gom(tu, den):
    """{ma đơn: {"ly_do", "nguon", "sku": [..], "kho": tình trạng lỗi}} trong [tu, den)."""
    t0, t1 = tu.strftime("%Y-%m-%d"), den.strftime("%Y-%m-%d")
    trong = lambda s: t0 <= str(s or "")[:10] < t1
    ca = {}

    def them(ma, ly_do, nguon, sku=None, uu_tien=0):
        k = str(ma).strip()
        if not k:
            return
        o, sp = _sp_don(k)
        key = str(o["id"]) if o else k
        c = ca.setdefault(key, {"ly_do": "", "nguon": set(), "sku": [], "kho": "", "_u": -1})
        c["nguon"].add(nguon)
        if ly_do and uu_tien > c["_u"]:
            c["ly_do"], c["_u"] = ly_do, uu_tien
        c["sku"] = c["sku"] or ([sku] if isinstance(sku, str) and sku else sp or list(sku or []))

    try:
        so = json.load(open(SO))
    except Exception:
        so = {}
    for ma, v in so.items():
        if trong(v.get("luc")):
            them(ma, v.get("ly_do") or "", "sàn", uu_tien=3)
    try:
        import orbit_tg as TG, ticket as TK
        for r in TG.rows(TK.BANG, fresh=True):
            if trong(r.get("Ngày tạo")) and r.get("Mã đơn") and r.get("Lý do"):
                them(r["Mã đơn"], f"{r.get('Lý do')}", "ticket", r.get("SKU khách đang cầm"), uu_tien=2)
        hoan09 = list(TG.rows(TK.HOAN, fresh=True))
    except Exception as e:
        print("ly_do_hoan: không đọc được Sheet", e, file=sys.stderr)
        hoan09 = []
    if NH.meta():
        for o in NH.orders().values():
            if o.get("st") not in NH.HOAN_ST or not trong(o.get("cap_nhat") or o.get("tao")):
                continue
            ms = str(o.get("ma_san") or "")
            if ms.endswith("R"):
                sp_r = [m for x in o.get("sp", []) for m, _ in NH.bung_combo(x["ma"]) if not str(m).upper().startswith("PK-")]
                them(ms[:-1], "Khách trả hàng (chưa có lý do)", "Nhanh", sp_r, uu_tien=0)
            else:
                them(ms or o["id"], "Hoàn ĐVVC / giao thất bại", "Nhanh", uu_tien=1)
    for r in hoan09:
        tt = str(r.get("Tình trạng") or "")
        if not trong(r.get("Ngày")) or not tt or "✅" in tt:
            continue
        m = str(r.get("MVĐ") or "")
        o = NH.don_theo_ma(m) or (NH.don_theo_ma(NH.goc_hoan(m)) if NH.goc_hoan(m) else None) if NH.meta() else None
        if o:
            key = str(o["id"])
            if key not in ca:
                them(o.get("ma_san") or key, "", "kho")
            ca.setdefault(key, {"ly_do": "", "nguon": set(), "sku": [], "kho": "", "_u": -1})["kho"] = tt
    return ca


def bang(ca):
    theo = defaultdict(lambda: {"ten": "", "n": 0, "ly": Counter(), "kho": Counter()})
    khong_ro = 0
    for c in ca.values():
        maus = {mau_cua(s) for s in c["sku"] if s} - {("", "")}
        if not maus:
            khong_ro += 1
            continue
        for ma, ten in maus:
            t = theo[ma]
            t["ten"], t["n"] = ten, t["n"] + 1
            t["ly"][c["ly_do"] or "Chưa rõ lý do"] += 1
            if c["kho"]:
                t["kho"][re.sub(r"^\W+\s*", "", c["kho"])] += 1
    return sorted(theo.items(), key=lambda kv: -kv[1]["n"]), khong_ro


def tuan(ngay=None):
    d = ngay or (datetime.now() - timedelta(days=7))
    tu = (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return tu, tu + timedelta(days=7)


def bao(ngay=None):
    tu, den = tuan(ngay)
    ca = gom(tu, den)
    rows, khong_ro = bang(ca)
    tieu = f"## Tuần {tu:%d/%m}–{den - timedelta(days=1):%d/%m/%Y}"
    L = [tieu, f"_Bot kho ghi {datetime.now():%d/%m %H:%M} · {len(ca)} đơn hoàn/trả/đổi · nguồn: lý do sàn, ticket CS, Nhanh, bảng 09_", ""]
    canh = [(ma, t, ly, n) for ma, t in rows for ly, n in t["ly"].items() if n >= NGUONG and not ly.startswith(("Chưa rõ", "Khách trả hàng (chưa", "Hoàn ĐVVC"))]
    if canh:
        L.append(f"**⚠️ Mẫu ≥{NGUONG} ca cùng lý do khách chọn → CEO họp R&D (form/size) + ads (ảnh có gây hiểu sai không):**")
        L += [f"- {t['ten']} (`{ma}`): {n} ca **{ly}**" for ma, t, ly, n in canh]
        L.append("")
    if rows:
        L += ["| Mẫu | Số ca | Lý do (số ca) | Kho kiểm thấy lỗi |", "|---|---:|---|---|"]
        for ma, t in rows[:40]:
            L.append(f"| {t['ten']} `{ma}` | {t['n']} | " + ", ".join(f"{k} {v}" for k, v in t["ly"].most_common())
                     + " | " + (", ".join(f"{k} {v}" for k, v in t["kho"].most_common()) or "—") + " |")
    else:
        L.append("Không có ca hoàn nào trong tuần." if not ca else "Chưa ra mẫu được ca nào (xem dòng cuối).")
    tong = Counter(c["ly_do"] or "Chưa rõ lý do" for c in ca.values())
    if tong:
        L += ["", "**Lý do cả tuần:** " + ", ".join(f"{k} {v}" for k, v in tong.most_common())]
    dv = [(t["ten"], t["ly"]["Hoàn ĐVVC / giao thất bại"]) for _, t in rows if t["ly"]["Hoàn ĐVVC / giao thất bại"] >= NGUONG]
    if dv:
        L.append("_Giao thất bại nhiều (không phải lỗi form, xem lại xác nhận đơn/COD): " + ", ".join(f"{a} {b}" for a, b in dv) + "_")
    if khong_ro:
        L.append(f"_{khong_ro} ca chưa ra mẫu (đơn ngoài 14 ngày cache Nhanh hoặc chưa map tem hoàn)._")
    chua = sum(1 for c in ca.values() if not c["ly_do"] or c["ly_do"].startswith(("Khách trả hàng (chưa", "Chưa rõ")))
    if chua:
        L.append(f"_{chua} ca chưa có lý do khách chọn trên sàn (sổ lý do sàn bắt đầu ghi từ 14/11; tác vụ đọc sàn kẹt quyền 13–14/11)._")
    return "\n".join(L)


def ghi(ngay=None):
    t = bao(ngay)
    tieu = t.splitlines()[0]
    try:
        cu = open(OUT, encoding="utf-8").read()
    except Exception:
        cu = "# Lý do hoàn theo mẫu — mỗi thứ 2 (bot kho ghi)\n\nMẫu ≥3 ca/tuần cùng lý do → CEO họp R&D + ads.\n"
    parts = re.split(r"(?m)^(?=## Tuần )", cu)
    head, secs = parts[0], [p for p in parts[1:] if not p.startswith(tieu)]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(head.rstrip() + "\n\n" + t + "\n\n" + "".join(s.rstrip() + "\n\n" for s in secs))
    return OUT


if __name__ == "__main__":
    import lark as Lk, ticket as TK
    TK.init(Lk.load_env(), start_worker=False)
    a = sys.argv[1:]
    d = datetime.strptime(a[a.index("--tuan") + 1], "%Y-%m-%d") if "--tuan" in a else None
    if "--ghi" in a:
        print("đã ghi", ghi(d))
    else:
        print(bao(d))
