#!/usr/bin/env bash
# Install, restart or remove the air-notify LaunchAgent: runs the daemon while you're logged
# in, restarts it (at most every 5 min) if it crashes.
set -euo pipefail

LABEL="local.air-notify"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$PROJECT_DIR/.venv/bin/air-notify"
LOG="$HOME/Library/Logs/air-notify.log"
DOMAIN="gui/$(id -u)"

case "${1:-install}" in
  install)
    [[ -x "$BIN" ]] || { echo "Missing $BIN; run 'uv sync' first." >&2; exit 1; }
    mkdir -p "$(dirname "$PLIST")"
    touch "$LOG" && chmod 600 "$LOG"
    # Runs the venv's entry point directly: a stable interpreter path means the Keychain
    # keeps trusting it without prompts. KeepAlive only on failure: exit 0 means "needs you".
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$BIN</string><string>run</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>300</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "Installed and started $LABEL. Logs: $LOG"
    ;;
  restart)
    # Needed after editing config.toml (it's read once at start).
    launchctl kickstart -k "$DOMAIN/$LABEL"
    echo "Restarted $LABEL"
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed $LABEL"
    ;;
  *)
    echo "usage: $0 [install|restart|uninstall]" >&2
    exit 2
    ;;
esac
