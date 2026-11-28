#!/usr/bin/env python3
"""NHẬP HOÀN KHO / ĐƠN ĐỔI TRÊN NHANH — bot ĐỐI CHIẾU (chỉ đọc), kho vẫn thao tác trên Nhanh theo
knowledge/SOP_NHANH_HOAN_DOI.md (soạn từ video hướng dẫn của chủ shop 27/11/2026).

Trước: kho nhập hoàn kho trên Nhanh xong phải tự đổi cột trạng thái bảng 09 (MỚI → HOÀN THÀNH), tự bấm
"Đã nhập kho QLBH" trên ticket đổi/trả — quên là tồn Nhanh thiếu mà không ai biết.
Giờ, sau mỗi lần đồng bộ Nhanh (`nhap_hoan.py dongbo`, gọi từ nhanh.py sau_sync):
  • Bảng 09 · HÀNG HOÀN NHẬN: Nhanh đã có phiếu nhập trả / đơn trả cho kiện → cột "Nhập hoàn Nhanh" tự ghi ✅.
  • Ticket "Chờ nhập kho QLBH": Nhanh có phiếu nhập trả của đơn gốc → tự tick + đóng (như kho bấm nút).
  • Ticket đổi sau giao đã có MVĐ đơn đi: đơn đi trên Nhanh không có SKU đổi sang → báo nhóm Đổi trả 1 lần.
10h/14h/18h (cua_hang.py hen → nhac()): kiện NGUYÊN VẸN kho đã nhận quá N ngày (canh_bao.json nhap_hoan_ngay, mặc định 1)
mà Nhanh chưa nhập hoàn → nhắc nhóm Kho kèm các bước làm. Kiện lỗi / tráo / thiếu: không nhắc (giữ khiếu nại, xem SOP).

"Đã nhập trên Nhanh" = phiếu nhập trả có đơn gốc (bill type 1, "Trả từ đơn: <ID>") HOẶC Nhanh có đơn trả "<mã sàn>R"
HOẶC đơn gốc Nhanh ghi "Đã chuyển hoàn" (72).

  python3 tools/nhap_hoan.py dongbo [--send]
  python3 tools/nhap_hoan.py nhac [--send]
"""
import json, os, re, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orbit_tg as TG  # noqa: E402
import ticket as TK  # noqa: E402
import nhanh as NH  # noqa: E402

COT = "Nhập hoàn Nhanh"   # cột mới ở bảng 09 (TK.HOAN_COLS)
STATE_F = os.path.join(TK.ROOT, "logs", "nhap_hoan.json")
esc = TK.esc
BUOC = ("Nhanh › Kênh bán › Sàn TMĐT › Trả hàng hoàn tiền › tab Shopee/TikTok › <b>Nhập hoàn kho</b> → chọn biên bản "
        "(Kho tổng Q2 + hãng VC, loại \"Nhận HVC hoàn về\") → quét tem (đơn giao thất bại: chọn \"Mã vận đơn gốc\") → "
        "kiểm SL → <b>Xác nhận</b>. Đơn đổi web/ngoài sàn: mở đơn gốc → ≡ → đơn \"Khách trả lại hàng\" → Lưu → Đổi trạng thái "
        "Thành công. Chi tiết: knowledge/SOP_NHANH_HOAN_DOI.md")


def _bat_dau():
    try:
        import kho_flow as KF
        return KF.BAT_DAU_HOAN
    except Exception:
        return "2026-11-14"


def _cau_hinh():
    try:
        return json.load(open(os.path.join(TK.ROOT, "knowledge", "canh_bao.json"), encoding="utf-8"))
    except Exception:
        return {}


def _doc_st():
    try:
        return json.load(open(STATE_F))
    except Exception:
        return {}


def _luu_st(s):
    try:
        os.makedirs(os.path.dirname(STATE_F), exist_ok=True)
        json.dump(s, open(STATE_F, "w"), ensure_ascii=False)
    except Exception as e:
        print("nhap_hoan: không ghi được sổ", e, flush=True)


class Nhanh:
    """Ảnh chụp dữ liệu Nhanh 1 lần đọc (phiếu nhập trả + đơn trả 'R')."""
    def __init__(self):
        self.nt = NH.nhap_tra() or {}
        self.r_goc = {x["ma_san"][:-1].lower() for x in NH.don_tra(30)}

    def da_nhap(self, ma=None, ma_don=None):
        """(True/False/None, giải thích). None = Nhanh chưa thấy đơn → chưa kết luận được."""
        o = None
        for k in (ma, ma_don):
            if k and not o:
                o = NH.don_theo_ma(k)
        goc = NH.goc_hoan(ma) if ma else ""
        if goc and goc.lower() in self.r_goc:
            return True, f"Nhanh có đơn trả {goc}R"
        if not o:
            return None, "Nhanh chưa thấy đơn"
        if o["id"] in self.nt:
            b = self.nt[o["id"]]
            return True, f"phiếu nhập trả {b.get('bill')} ({str(b.get('luc') or '')[:16]})"
        if o["ma_san"] and o["ma_san"].lower() in self.r_goc:
            return True, f"Nhanh có đơn trả {o['ma_san']}R"
        if o.get("st") == 72:
            return True, "Nhanh ghi Đã chuyển hoàn"
        return False, f"đơn {o['ma_san'] or o['id']} trên Nhanh: {o.get('st_ten') or o.get('st')}"


def _xau(r):
    return any(x in str(r.get("Tình trạng") or "").lower() for x in ("lỗi", "tráo", "thiếu", "không nguyên"))


def dong_bo(send=False):
    """Sau đồng bộ Nhanh: tick bảng 09, đóng ticket QLBH, kiểm SKU đơn đi đổi. Trả danh sách việc đã làm."""
    if not NH.meta():
        print("nhap_hoan: chưa có dữ liệu Nhanh"); return []
    N, out, st = Nhanh(), [], _doc_st()
    bd = _bat_dau()
    # 1) bảng 09: tự ghi cột "Nhập hoàn Nhanh"
    for r in TG.rows(TK.HOAN, fresh=True):
        if r.get(COT) or not r.get("Người nhận") or str(r.get("Ngày") or "")[:10] < bd:
            continue
        ok, ly = N.da_nhap(r.get("MVĐ"), r.get("Đơn Nhanh"))
        if ok:
            if send:
                TG.kho("update", table=TG.sname(TK.HOAN), id=r["_id"],
                       fields={COT: f"✅ {datetime.now():%d/%m %H:%M} · {ly} (bot)"})
            out.append(f"09 {r.get('MVĐ')}: đã nhập hoàn ({ly})")
    TG._CACHE.pop(TG.sname(TK.HOAN), None)
    # 2) ticket chờ nhập kho QLBH: Nhanh có phiếu nhập trả của đơn gốc → tick + đóng
    for r in TK.all_rows():
        if r.get("Trạng thái") != "Chờ nhập kho QLBH" or r.get("Nhập kho QLBH"):
            continue
        ok, ly = N.da_nhap(r.get("MVĐ hoàn về"), r.get("Mã đơn"))
        if ok:
            if send:
                TK.upd(r, {"Nhập kho QLBH": f"✓ bot: {ly}"}, f"Nhanh đã nhập trả ({ly})", "bot")
                TK.finish(r, "bot")
            out.append(f"{r['ID']}: Nhanh đã nhập trả → đóng")
    # 3) đổi sau giao: đơn đi trên Nhanh phải có SKU đổi sang (báo 1 lần / ticket)
    da = st.setdefault("don_di", {})
    for r in TK.all_rows():
        if r.get("Loại") != TK.LOAI["doi"][1] or not r.get("MVĐ đi") or r.get("Trạng thái") in TK.DONG or r["ID"] in da:
            continue
        moi = re.sub(r"\s+", "", str(r.get("SKU đổi sang") or "")).upper()
        o = NH.don_theo_ma(r.get("MVĐ đi"))
        if not moi or not o:
            continue   # Nhanh chưa đồng bộ đơn đi → lần sau kiểm
        co = {re.sub(r"\s+", "", str(p.get("ma") or "")).upper() for p in o.get("sp") or []}
        if send:
            da[r["ID"]] = "ok" if moi in co else "sai"
        if moi not in co:
            import khung as KH
            t = KH.the("Đơn đi đổi hàng sai món", f"{r.get('Mã đơn')} (ticket {r['ID']} · đơn đi {r.get('MVĐ đi')})",
                       f"Khách đổi sang {KH.ten_sku(moi)} nhưng đơn đi trên Nhanh là "
                       + (", ".join(KH.ten_sku(x) for x in sorted(co)) or "(trống)"),
                       ["Mở đơn đi trên Nhanh, sửa đúng món đổi sang", "Kiểm trước khi shipper lấy hàng"], "CS", icon="⚠️")
            out.append(re.sub(r"<[^>]+>", "", t))
            if send and TK.tchat():
                TK.tsend(TK.tchat(), t)
    if send:
        _luu_st(st)
    for x in out:
        print(x)
    if not out:
        print("nhap_hoan: không có gì mới")
    return out


def nhac(send=False):
    """[(chat, text)] — kiện nguyên vẹn kho đã nhận quá N ngày mà Nhanh chưa nhập hoàn (nhắc nhóm Kho)."""
    if not NH.meta():
        return []
    ngay = int(_cau_hinh().get("nhap_hoan_ngay") or 1)
    han = (datetime.now() - timedelta(days=ngay)).strftime("%Y-%m-%d")
    N, ds, bd = Nhanh(), [], _bat_dau()
    for r in TG.rows(TK.HOAN, fresh=True):
        d = str(r.get("Ngày") or "")[:10]
        if r.get(COT) or not r.get("Người nhận") or d < bd or d > han or _xau(r):
            continue
        ok, ly = N.da_nhap(r.get("MVĐ"), r.get("Đơn Nhanh"))
        if ok is False:
            import khung as KH
            sp = "; ".join(KH.ten_sku(m) + (f" x{n}" if n else "") for m, n in
                           re.findall(r"([A-Z0-9][A-Z0-9-]+-[A-Z0-9]+)\)?\s*x(\d+)", str(r.get("Sản phẩm") or ""))) \
                or str(r.get("Sản phẩm") or "")[:60]
            ds.append(f"• <b>{esc(r.get('MVĐ'))}</b> · nhận ngày {esc(d[8:10])}/{esc(d[5:7])} · {esc(sp)}")
    if not ds:
        return []
    import khung as KH
    t = KH.the("Hàng hoàn chưa nhập trên Nhanh", None,
               f"{len(ds)} kiện nguyên vẹn đã về kho quá {ngay} ngày, Nhanh chưa nhập hoàn → tồn Nhanh đang thiếu",
               ["Nhanh › Kênh bán › Sàn TMĐT › Trả hàng hoàn tiền › tab Shopee/TikTok › Nhập hoàn kho",
                "Chọn biên bản bàn giao (Kho tổng Q2, loại \"Nhận HVC hoàn về\")",
                "Quét tem (giao thất bại: chọn \"Mã vận đơn gốc\") → kiểm số lượng → Xác nhận",
                "Bot tự ghi ✅ ở bảng 09 sau lần đồng bộ kế tiếp"],
               "Kho", icon="📥", them=["", "<b>Các kiện:</b>"] + ds[:25] + (["…"] if len(ds) > 25 else [])
               + ["<i>Đơn đổi web/ngoài sàn: xem knowledge/SOP_NHANH_HOAN_DOI.md mục B</i>"])
    return [(str(TK.E.get("CHAT_ID") or ""), t)]


if __name__ == "__main__":
    import lark as Lk
    TK.init(Lk.load_env(), start_worker=False)
    a = sys.argv[1:] or ["help"]
    if a[0] == "dongbo":
        dong_bo("--send" in a)
    elif a[0] == "nhac":
        for c, t in nhac():
            print(re.sub(r"<[^>]+>", "", t))
            if "--send" in a and c:
                TK.tsend(c, t)
    else:
        print(__doc__)
