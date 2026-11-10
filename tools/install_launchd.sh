#!/bin/bash
# Cài listener bot kho chạy nền (launchd), tự bật lại khi máy khởi động hoặc listener chết + cảnh báo kho 9h sáng.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd -P)"  # đường thật: launchd không được đọc ~/Desktop
PLIST=~/Library/LaunchAgents/vn.theorbit.kho-agent.plist
mkdir -p "$DIR/logs" ~/Library/LaunchAgents
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>vn.theorbit.kho-agent</string>
  <key>ProgramArguments</key><array>
    <string>$DIR/.venv/bin/python</string><string>$DIR/tools/listener.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DIR/logs/listener.out</string>
  <key>StandardErrorPath</key><string>$DIR/logs/listener.out</string>
</dict></plist>
EOF
# Cảnh báo kho mỗi sáng 9h (chỉ đọc Base + gửi tin, không gọi Claude)
NHAC=~/Library/LaunchAgents/vn.theorbit.kho-agent.nhac.plist
cat > "$NHAC" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>vn.theorbit.kho-agent.nhac</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>$DIR/tools/lark.py</string><string>nhac</string><string>--send</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$DIR/logs/nhac.out</string>
  <key>StandardErrorPath</key><string>$DIR/logs/nhac.out</string>
</dict></plist>
EOF
# Ticket CS 9:05 sáng: quá hạn hoàn, chưa gọi, chờ duyệt, phạt kho; thứ 2 thêm báo cáo tuần (tools/ticket.py)
TK=~/Library/LaunchAgents/vn.theorbit.kho-agent.ticket.plist
cat > "$TK" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>vn.theorbit.kho-agent.ticket</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>$DIR/tools/ticket.py</string><string>nhac</string><string>--send</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>5</integer></dict>
  <key>StandardOutPath</key><string>$DIR/logs/ticket-nhac.out</string>
  <key>StandardErrorPath</key><string>$DIR/logs/ticket-nhac.out</string>
</dict></plist>
EOF
# Việc thủ kho (tools/kho_flow.py hen): 9:02 gợi ý kiểm kho + kiện sàn báo hoàn chưa nhận; 17:00 chốt ca; 18:00 nhắc lại
KF=~/Library/LaunchAgents/vn.theorbit.kho-agent.flow.plist
cat > "$KF" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>vn.theorbit.kho-agent.flow</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>$DIR/tools/kho_flow.py</string><string>hen</string><string>--send</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartCalendarInterval</key><array>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>2</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$DIR/logs/flow.out</string>
  <key>StandardErrorPath</key><string>$DIR/logs/flow.out</string>
</dict></plist>
EOF
for p in "$PLIST" "$NHAC" "$TK" "$KF"; do launchctl unload "$p" 2>/dev/null || true; launchctl load "$p"; done
echo "Đã bật listener + cảnh báo 9h + ticket 9:05 + việc kho 9:02/17:00/18:00. Log: $DIR/logs/listener.out, nhac.out, ticket-nhac.out, flow.out"
