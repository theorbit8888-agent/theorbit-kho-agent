#!/bin/bash
# Cài listener bot kho chạy nền (launchd), tự bật lại khi máy khởi động hoặc listener chết.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
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
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Đã bật listener. Log: $DIR/logs/listener.out"
