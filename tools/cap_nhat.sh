#!/bin/bash
# CẬP NHẬT BOT KHO TRÊN MÁY CHẠY THẬT (máy chủ shop) — code team làm trên GitHub về máy, có thử trước + quay lại.
#
#   bash tools/cap_nhat.sh xem              # có gì mới trên GitHub: nhánh/đề xuất của team, đổi những file nào
#   bash tools/cap_nhat.sh thu <nhánh>      # chạy MỌI kịch bản kich-ban/*.txt trên bản sao riêng của nhánh đó
#                                           #   (không đụng bot thật, không đọc env/token thật) → ĐẠT / LỖI
#   bash tools/cap_nhat.sh len [nhánh]      # chủ shop đã duyệt: thử lại → gộp vào main → đẩy GitHub
#                                           #   → cài lại job nền (install_launchd.sh) → kiểm bot còn chạy
#                                           #   (không ghi nhánh = lấy main trên GitHub, vd đề xuất đã gộp trên web)
#   bash tools/cap_nhat.sh lui              # bot lỗi sau khi lên: quay về đúng bản trước lần `len` gần nhất
#
# Luật: chỉ chạy trên máy chủ shop. Máy còn sửa tay chưa commit → dừng, không gộp đè.
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd -P)"
TMP="${TMPDIR:-/tmp}/kho-cap-nhat"
LABEL=vn.theorbit.kho-agent

do_() { printf '\033[1m%s\033[0m\n' "$*"; }

sach() {   # máy chạy thật không được có code sửa tay chưa commit (sẽ bị đè / làm lệch GitHub)
  local d; d=$(git status --porcelain --untracked-files=no)
  if [ -n "$d" ]; then
    do_ "⛔ Máy đang có code sửa tay chưa commit:"; echo "$d"
    echo "→ commit + push các sửa này trước (luật: sửa code bot kho xong phải đẩy GitHub trong ngày), rồi chạy lại."
    exit 1
  fi
}

thu_nhanh() {   # $1 = ref (nhánh/commit) → chạy mọi kịch bản trên bản sao riêng, HOME giả
  local ref="$1" wt="$TMP/thu-$$" home="$TMP/home-$$" loi=0 n=0
  rm -rf "$wt" "$home"; mkdir -p "$home" "$TMP"
  git worktree add -q --detach "$wt" "$ref" || { echo "Không mở được $ref"; return 2; }
  for k in "$wt"/kich-ban/*.txt; do
    n=$((n+1))
    out="$TMP/$(basename "$k").out"
    ( cd "$wt" && HOME="$home" SAN_THU_DIR="$TMP/du-lieu-$$-$n" python3 tools/san_thu.py "$k" ) >"$out" 2>&1
    rc=$?
    if [ $rc -ne 0 ] || grep -q "Traceback" "$out"; then
      loi=$((loi+1)); echo "  ❌ $(basename "$k") (rc=$rc) — xem $out"; grep -m3 -E "Error|Traceback" "$out" | sed 's/^/     /'
    else
      echo "  ✅ $(basename "$k") ($(grep -c '🤖' "$out") tin bot)"
    fi
  done
  # phòng thử phải import được (thiếu file như tru_ton.py 26/11 là lỗi ngay ở đây)
  ( cd "$wt" && HOME="$home" python3 -c "import sys; sys.path.insert(0,'tools'); import phong_thu" ) >"$TMP/import.out" 2>&1 \
    && echo "  ✅ phòng thử import được" || { loi=$((loi+1)); echo "  ❌ phòng thử không import được:"; tail -3 "$TMP/import.out"; }
  # menu "/" Telegram: lệnh mới phải có mô tả + nhóm (tools/menu_lenh.py), không thì không hiện khi gõ "/"
  ( cd "$wt" && HOME="$home" SAN_THU_DIR="$TMP/du-lieu-$$-menu" python3 tools/menu_lenh.py kiem ) >"$TMP/menu.out" 2>&1 \
    && echo "  ✅ menu lệnh đủ mô tả" || { loi=$((loi+1)); echo "  ❌ menu lệnh thiếu:"; grep "❌" "$TMP/menu.out" | head -5; }
  git worktree remove --force "$wt"; rm -rf "$home" "$TMP"/du-lieu-$$-*
  [ $loi -eq 0 ] && { do_ "ĐẠT: $n kịch bản, 0 lỗi"; return 0; } || { do_ "LỖI: $loi chỗ hỏng / $n kịch bản → KHÔNG lên bot thật"; return 1; }
}

case "${1:-xem}" in
xem)
  git fetch -q --prune origin || exit 1
  do_ "main trên GitHub mới hơn máy: $(git rev-list --count HEAD..origin/main) commit"
  git log --oneline HEAD..origin/main | sed 's/^/  /'
  do_ "Nhánh của team chưa gộp vào main:"
  for b in $(git branch -r --no-merged origin/main | grep -v HEAD); do
    echo "  • ${b#origin/} — $(git log -1 --format='%an, %ar: %s' "$b")"
    git diff --stat origin/main..."$b" | tail -1 | sed 's/^/      /'
  done
  echo "Thử: bash tools/cap_nhat.sh thu <nhánh>"
  ;;
thu)
  [ -n "${2:-}" ] || { echo "Ghi tên nhánh: bash tools/cap_nhat.sh thu <nhánh>"; exit 1; }
  git fetch -q origin
  ref="origin/${2#origin/}"; git rev-parse -q --verify "$ref" >/dev/null || ref="$2"
  do_ "Thử $ref (bản sao riêng, không đụng bot thật):"
  git diff --stat HEAD..."$ref" | tail -1
  thu_nhanh "$ref"
  ;;
len)
  sach
  git fetch -q origin || exit 1
  if [ -n "${2:-}" ]; then ref="origin/${2#origin/}"; git rev-parse -q --verify "$ref" >/dev/null || ref="$2"; else ref=origin/main; fi
  do_ "1/4 Thử $ref trước khi lên:"
  thu_nhanh "$ref" || exit 1
  truoc=$(git rev-parse HEAD)
  git tag -f "truoc-cap-nhat" "$truoc" >/dev/null
  echo "$truoc $(date '+%F %T') $ref" >> logs/cap_nhat.log
  do_ "2/4 Gộp $ref vào main (bản cũ giữ ở tag truoc-cap-nhat = ${truoc:0:7})"
  git merge -q --no-edit "$ref" || { git merge --abort; do_ "⛔ Đụng code (conflict) → không gộp. Nhờ người làm nhánh cập nhật theo main rồi thử lại."; exit 1; }
  git push -q origin main || echo "⚠️ chưa đẩy được GitHub (máy vẫn chạy bản mới) — đẩy lại sau: git push origin main"
  do_ "3/4 Cài lại job nền"
  bash tools/install_launchd.sh >/dev/null 2>&1 || { do_ "⚠️ install_launchd.sh lỗi"; }
  sleep 6
  do_ "4/4 Kiểm bot"
  pid=$(launchctl list | awk -v l="$LABEL" '$3==l{print $1}')
  if [ -n "$pid" ] && [ "$pid" != "-" ]; then
    do_ "✅ Đã lên: $(git log -1 --format='%h %s') — bot kho đang chạy (pid $pid). Lỗi gì: bash tools/cap_nhat.sh lui"
  else
    do_ "❌ Bot kho KHÔNG chạy sau khi lên → đang quay lại bản cũ"; tail -20 logs/listener.out; exec bash "$0" lui
  fi
  ;;
lui)
  git rev-parse -q --verify truoc-cap-nhat >/dev/null || { echo "Chưa có lần cập nhật nào để quay lại"; exit 1; }
  sach
  t=$(git rev-parse truoc-cap-nhat)
  [ "$(git rev-parse HEAD)" = "$t" ] && { echo "Đang ở đúng bản trước rồi"; exit 0; }
  do_ "Quay lại bản ${t:0:7} (giữ lịch sử: tạo commit đảo ngược, không xoá gì)"
  git revert --no-edit --no-commit "$t"..HEAD && git commit -q -m "Quay lại bản trước cập nhật (${t:0:7})" || { git revert --abort; exit 1; }
  git push -q origin main || echo "⚠️ chưa đẩy được GitHub"
  bash tools/install_launchd.sh >/dev/null 2>&1; sleep 6
  launchctl list | awk -v l="$LABEL" '$3==l{print "bot kho pid " $1}'
  echo "$(date '+%F %T') LUI về ${t:0:7}" >> logs/cap_nhat.log
  ;;
*) sed -n 2,12p "$0" ;;
esac
