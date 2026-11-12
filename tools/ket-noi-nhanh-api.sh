#!/bin/bash
# Kết nối bot kho với Nhanh.vn qua Open API v3 (đọc tồn + đơn liên tục, không qua Chrome).
# CHỦ SHOP tự chạy trên Mac mini:  bash ~/kho-agent/tools/ket-noi-nhanh-api.sh
# Mã bí mật chỉ đi qua clipboard (pbpaste) → file ~/.config/orbit-kho/nhanh_api.env (quyền 600), không in ra màn hình.
set -e
F="$HOME/.config/orbit-kho/nhanh_api.env"; mkdir -p "$(dirname "$F")"; touch "$F"; chmod 600 "$F"
RETURN="https://www.google.com/"
luu() { grep -v "^$1=" "$F" > "$F.tmp" || true; echo "$1=$2" >> "$F.tmp"; mv "$F.tmp" "$F"; chmod 600 "$F"; }

echo "== Bước 1/3: App ID =="
read -r -p "Gõ App ID (số, ở trang chi tiết app trên open.nhanh.vn/apps) rồi Enter: " APP
[[ "$APP" =~ ^[0-9]+$ ]] || { echo "App ID phải là số."; exit 1; }
luu NHANH_APP_ID "$APP"

echo; echo "== Bước 2/3: Secret key =="
read -r -p "Copy 'Secret key' của app (Cmd+C) rồi bấm Enter... " _
SEC="$(pbpaste | tr -d '[:space:]')"
[ ${#SEC} -ge 16 ] || { echo "Clipboard không giống secret key (quá ngắn). Copy lại rồi chạy lại."; exit 1; }
luu NHANH_SECRET "$SEC"; echo "✅ Đã lưu secret key (${#SEC} ký tự)."

echo; echo "== Bước 3/3: Cấp quyền =="
VC="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)"
URL="https://nhanh.vn/oauth?appId=$APP&service=pos&verifyCode=$VC&returnLink=$RETURN"
echo "Mở trang cấp quyền Nhanh (đăng nhập tài khoản GIÁM ĐỐC, chọn The ORBIT, tích đủ quyền Sản phẩm/Đơn hàng/Kho)."
open "$URL" || echo "Mở link này: $URL"
echo "Cấp quyền xong trình duyệt sẽ nhảy sang google.com với địa chỉ có 'accessCode=...'."
read -r -p "Copy NGUYÊN địa chỉ trên thanh địa chỉ (Cmd+L, Cmd+C) rồi bấm Enter (trong 10 phút)... " _
BACK="$(pbpaste)"
AC="$(printf '%s' "$BACK" | sed -n 's/.*[?&]accessCode=\([^&#]*\).*/\1/p')"
[ -n "$AC" ] || { echo "Không thấy accessCode trong địa chỉ vừa copy. Chạy lại từ đầu."; exit 1; }
R="$(curl -s -X POST "https://pos.open.nhanh.vn/v3.0/app/getaccesstoken?appId=$APP" \
  -H "Authorization: $SEC" -H "Content-Type: application/json" \
  -d "{\"accessCode\":\"$AC\",\"verifyCode\":\"$VC\"}")"
printf '%s' "$R" | /usr/bin/python3 -c '
import json, sys, os
r = json.load(sys.stdin)
if r.get("code") != 1:
    print("❌ Nhanh từ chối:", r.get("messages") or r.get("errorCode")); sys.exit(1)
d = r["data"]; f = os.path.expanduser("~/.config/orbit-kho/nhanh_api.env")
L = [l for l in open(f) if not l.startswith(("NHANH_ACCESS_TOKEN=", "NHANH_BUSINESS_ID=", "NHANH_HET_HAN="))]
L += ["NHANH_ACCESS_TOKEN=" + str(d["accessToken"]) + "\n", "NHANH_BUSINESS_ID=" + str(d["businessId"]) + "\n",
      "NHANH_HET_HAN=" + str(d.get("expiredAt")) + "\n"]
open(f, "w").writelines(L); os.chmod(f, 0o600)
print("✅ Đã kết nối Nhanh API. Doanh nghiệp:", d["businessId"], "· hết hạn:", d.get("expiredAt"))
print("   Quyền:", ", ".join(map(str, d.get("permissions") or [])) or "(không rõ)")
'
# bật job đọc Nhanh 30 phút/lần (plist do install_launchd.sh tạo sẵn) + đọc ngay lần đầu
PL="$HOME/Library/LaunchAgents/vn.theorbit.kho-agent.nhanh.plist"
cd "$HOME/kho-agent" && .venv/bin/python tools/nhanh.py sync && echo "✅ Bot đã đọc Nhanh lần đầu."
[ -f "$PL" ] && { launchctl unload "$PL" 2>/dev/null; launchctl load "$PL"; echo "✅ Đã bật đọc Nhanh 30 phút/lần."; }
echo "Xong. Nhắn Claude: 'đã kết nối API Nhanh'."
