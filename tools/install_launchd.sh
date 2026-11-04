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
for p in "$PLIST" "$NHAC"; do launchctl unload "$p" 2>/dev/null || true; launchctl load "$p"; done
echo "Đã bật listener + cảnh báo 9h. Log: $DIR/logs/listener.out, $DIR/logs/nhac.out"
