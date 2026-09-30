#!/usr/bin/env bash
# Set up, install, update, restart or remove the air-notify systemd user service (Raspberry Pi / Linux).
# Runs as your user, no sudo. To start at boot it needs linger (`loginctl enable-linger`).
set -euo pipefail

cd "$(dirname "$0")/.."
APP_DIR="$PWD"
UNIT="air-notify.service"
UNIT_DIR="$HOME/.config/systemd/user"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

[[ -x "$UV" ]] || { echo "uv not found; install it first (see README)." >&2; exit 1; }

setup() {
  # --locked: install exactly what uv.lock pins (hash-checked), and fail if it's out of date.
  "$UV" sync --locked --no-dev
  mkdir -p "$HOME/.local/bin" "$UNIT_DIR"
  ln -sf "$APP_DIR/.venv/bin/air-notify" "$HOME/.local/bin/air-notify"
  sed "s#@APP_DIR@#$APP_DIR#g" "deploy/$UNIT" > "$UNIT_DIR/$UNIT"
  chmod 0644 "$UNIT_DIR/$UNIT"
  systemctl --user daemon-reload
}

case "${1:-}" in
  setup)
    # Dependencies + the `air-notify` command + the unit, without starting anything.
    setup
    echo "Ready. 'air-notify' is in ~/.local/bin. Start the service with: $0 install"
    ;;
  install)
    setup
    systemctl --user enable --now "$UNIT"
    [[ "$(loginctl show-user "$USER" -p Linger --value)" == yes ]] \
      || echo "Note: run 'sudo loginctl enable-linger $USER' so it also runs at boot."
    echo "Installed and started $UNIT. Logs: journalctl --user-unit air-notify -f"
    ;;
  update)
    git pull --ff-only
    setup
    systemctl --user restart "$UNIT"
    echo "Updated to $(git log --oneline -1) and restarted."
    ;;
  restart)
    # Needed after editing config.toml (it's read once at start).
    systemctl --user restart "$UNIT"
    echo "Restarted $UNIT"
    ;;
  uninstall)
    systemctl --user disable --now "$UNIT" 2>/dev/null || true
    rm -f "$UNIT_DIR/$UNIT" "$HOME/.local/bin/air-notify"
    systemctl --user daemon-reload
    echo "Removed $UNIT"
    ;;
  *)
    echo "usage: $0 setup|install|update|restart|uninstall" >&2
    exit 2
    ;;
esac
