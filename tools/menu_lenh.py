#!/usr/bin/env python3
"""MENU LỆNH "/" TRONG TELEGRAM — tự dựng từ code, tự khai báo mỗi lần bot khởi động (bàn giao không cần làm tay).

Telegram chỉ gợi ý lệnh bot đã khai báo (setMyCommands). listener.py / phong_thu.py gọi dat_menu(env) lúc khởi động:
  • LỆNH NÀO, NHÓM NÀO: đọc thẳng từ code — lệnh các module đăng ký (TK.EXT_CMDS, TK.LENH) + nhóm được dùng (TK.EXT_NHOM).
    Lệnh không khai nhóm (dùng ở mọi nhóm) thì xếp theo NHA bên dưới.
  • ID NHÓM: đọc từ env (CHAT_ID, TICKET_CHAT_ID, CH_CHAT_ID) → đổi bot / đổi nhóm / máy mới chỉ cần sửa env + khởi động lại.
  • MÔ TẢ: bảng MO_TA bên dưới — chỗ DUY NHẤT phải sửa tay khi thêm lệnh mới.
Thêm lệnh mới mà quên MO_TA → `menu_lenh.py kiem` báo lỗi → `cap_nhat.sh thu` KHÔNG cho lên bot thật.

  python3 tools/menu_lenh.py xem      # in menu từng nhóm (không gọi Telegram)
  python3 tools/menu_lenh.py kiem     # kiểm lệnh thiếu mô tả / không biết nhóm (thoát 1 nếu lỗi)
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NHOM = {"CHAT_ID": "Kho · Hàng về & restock", "TICKET_CHAT_ID": "Đổi trả CS-Kho", "CH_CHAT_ID": "CS & Cửa hàng"}

# Mô tả hiện trong menu (≤ 256 ký tự). Thứ tự ở đây = thứ tự trong menu.
MO_TA = {
    # kho
    "/kho": "Menu kho + mẫu chép sẵn",
    "/hangve": "Hàng về: điền bill + đếm thực tế + lỗi",
    "/dathang": "Đặt hàng lại / chốt sản xuất",
    "/tonkho": "Xem tồn từng size: /tonkho tên-mẫu",
    "/kiemkho": "Kiểm kho: đếm thực tế so với Nhanh",
    "/indon": "In đơn: hôm nay in bao nhiêu tem",
    "/giao": "Giao shipper: chụp tem, chú thích /giao",
    "/giulai": "Đơn huỷ sau in: rút kiện + chụp tem",
    "/doisoat": "Đối soát cần gửi ↔ đã giao ↔ sàn",
    "/chotdi": "Chốt đơn đi cuối ca theo sàn",
    "/chothoan": "Đối soát hàng hoàn 17h",
    "/dauca": "Checklist đầu ca kho",
    "/dubao": "Dự báo hết hàng",
    "/tonghoploi": "Tổng hợp hàng lỗi / thiếu / tráo",
    "/nhanh": "Dữ liệu Nhanh cập nhật lúc nào",
    # ticket
    "/tk": "Mở ticket đổi / trả / hoàn / sự cố",
    "/doi": "Đổi hàng sau giao",
    "/doitruoc": "Đổi trước khi giao",
    "/tra": "Trả hàng hoàn tiền",
    "/doihoan": "Đòi hàng hoàn (bom, quá hạn, thất lạc)",
    "/suco": "Sự cố giao hàng",
    "/hoan": "Kiện hoàn về kho: /hoan MVĐ (hoặc chụp tem)",
    "/xem": "Xem ticket: /xem mã-đơn | MVĐ | ID",
    "/dangdo": "Ticket đang dở",
    # cửa hàng
    "/moca": "Mở ca: /moca số-tiền-két-đếm",
    "/chi": "Chi tiền mặt: /chi 35k ship grab",
    "/thu": "Thu tiền mặt ngoài đơn: /thu 200k nội dung",
    "/ketca": "Kết ca: dán mẫu, bot tính két",
    "/ket": "Két hiện tại phải có",
    "/bill": "Sổ chuyển khoản: /bill mã-đơn số-tiền lý-do + ảnh",
    "/billthieu": "Chủ shop: đánh dấu CK chưa nhận được",
    "/goi": "Nhờ store gói / book ship: /goi mã-đơn ghi-chú",
    "/chotca": "Chốt ca 16h / 22h (ảnh store + checklist)",
    # chung
    "/note": "Ghi chú đơn cho kho: /note mã-đơn nội-dung",
    "/hoatoc": "Đơn hoả tốc (đổi size: /hoatoc mã đổi SKU → size)",
    # chat riêng
    "/huy": "Dừng phiếu đang khai",
    "/day": "Dạy bot 1 quy tắc mới",
    "/dangday": "Bài dạy đang dở",
}
# Lệnh dùng được ở mọi nhóm (code không khai EXT_NHOM) → hiện ở nhóm nào. "rieng" = chat riêng với bot.
NHA = {
    "/kho": ("CHAT_ID",), "/dauca": ("CHAT_ID",), "/dubao": ("CHAT_ID",), "/nhanh": ("CHAT_ID",),
    "/tk": ("TICKET_CHAT_ID", "rieng"), "/doi": ("TICKET_CHAT_ID",), "/doitruoc": ("TICKET_CHAT_ID",),
    "/tra": ("TICKET_CHAT_ID",), "/doihoan": ("TICKET_CHAT_ID",), "/suco": ("TICKET_CHAT_ID",),
    "/hoan": ("CHAT_ID", "TICKET_CHAT_ID"), "/xem": ("CHAT_ID", "TICKET_CHAT_ID", "rieng"),
    "/dangdo": ("TICKET_CHAT_ID",), "/huy": ("rieng",), "/day": ("rieng",), "/dangday": ("rieng",),
}
AN = {"/ticket", "/start", "/dangnhapnhanh"}   # bí danh / lệnh hệ thống / chỉ chủ shop dùng 1 lần → không đưa vào menu


def _nap():
    """Nạp mọi module đăng ký lệnh (như listener) rồi trả registry của ticket.py."""
    import ticket as TK
    for m in ("kho_flow", "cua_hang", "xuat_kho", "hoan_san", "tru_ton", "chuyen_kho", "day_bot"):
        try:
            __import__(m)
        except Exception as e:
            print(f"menu: không nạp được {m}: {e}", flush=True)
    return TK


def dung_menu():
    """{ 'CHAT_ID' | 'TICKET_CHAT_ID' | 'CH_CHAT_ID' | 'rieng': [(lệnh không '/', mô tả)] } + [lỗi]."""
    TK = _nap()
    lenh = (set(TK.EXT_CMDS) | set(TK.LENH)) - AN
    out, loi = {k: [] for k in list(NHOM) + ["rieng"]}, []
    thu_tu = {c: i for i, c in enumerate(MO_TA)}
    for c in sorted(lenh, key=lambda x: (thu_tu.get(x, 999), x)):
        if c not in MO_TA:
            loi.append(f"{c}: chưa có mô tả trong MO_TA (tools/menu_lenh.py)")
            continue
        nhom = list(TK.EXT_NHOM.get(c) or NHA.get(c) or ())
        if c in getattr(TK, "EXT_PRIV", {}) and "rieng" not in nhom:
            nhom.append("rieng")
        if not nhom:
            loi.append(f"{c}: không biết hiện ở nhóm nào — thêm vào NHA (tools/menu_lenh.py)")
            continue
        ten = c[1:]
        if len(ten) > 32 or not ten.replace("_", "").isalnum() or ten != ten.lower():
            loi.append(f"{c}: tên lệnh Telegram không nhận (chữ thường, số, _; ≤ 32)")
            continue
        for k in nhom:
            out.setdefault(k, []).append((ten, MO_TA[c][:256]))
    return out, loi


def dat_menu(env, api=None, them=None):
    """Khai báo menu "/" cho từng nhóm có trong env + chat riêng. them: {nhóm: [(lệnh, mô tả)]} thêm/đè (phòng thử)."""
    if api is None:
        import orbit_tg as TG
        api = TG.api
    menu, loi = dung_menu()
    for x in loi:
        print("menu ⚠️", x, flush=True)
    for k, ds in (them or {}).items():
        cu = dict(menu.get(k, []))
        cu.update(dict(ds))
        menu[k] = list(cu.items())
    ok, can = 0, 0
    for k, ds in menu.items():
        if not ds:
            continue
        if k == "rieng":
            scope = {"type": "all_private_chats"}
        else:
            c = str(env.get(k) or "")
            if not c:
                continue
            scope = {"type": "chat", "chat_id": int(c)}
        can += 1
        r = api("setMyCommands", {"commands": [{"command": a, "description": b} for a, b in ds[:100]], "scope": scope})
        if r.get("ok"):
            ok += 1
        else:
            print(f"menu: {NHOM.get(k, k)} lỗi {r.get('description')}", flush=True)
    print(f"menu lệnh: đã đặt {ok}/{can} danh sách", flush=True)
    return ok


if __name__ == "__main__":
    os.environ.setdefault("SAN_THU_DIR", "/tmp/menu-lenh-kiem")   # chỉ nạp module, không đụng dữ liệu
    a = sys.argv[1:] or ["xem"]
    menu, loi = dung_menu()
    if a[0] == "kiem":
        for x in loi:
            print("❌", x)
        print("✅ menu lệnh đủ mô tả + nhóm" if not loi else f"LỖI: {len(loi)} lệnh chưa vào menu được")
        sys.exit(1 if loi else 0)
    for k, ds in menu.items():
        print(f"\n[{NHOM.get(k, 'Chat riêng với bot')}]")
        for c, d in ds:
            print(f"  /{c} — {d}")
    for x in loi:
        print("⚠️", x)
