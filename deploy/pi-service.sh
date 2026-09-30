#!/usr/bin/env bash
# Install, update, restart or remove the air-notify systemd user service (Raspberry Pi / Linux).
# Runs as your user, no sudo. To start at boot it needs linger (`loginctl enable-linger`).
set -euo pipefail

cd "$(dirname "$0")/.."
UNIT="air-notify.service"
UNIT_DIR="$HOME/.config/systemd/user"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

[[ "$PWD" == "$HOME/air-notify" ]] || { echo "Clone the repo to ~/air-notify; the service expects that path." >&2; exit 1; }
[[ -x "$UV" ]] || { echo "uv not found; install it first (see README)." >&2; exit 1; }

install_app() {
  # --locked: install exactly what uv.lock pins (hash-checked), and fail if it's out of date.
  "$UV" sync --locked --no-dev
  mkdir -p "$HOME/.local/bin" "$UNIT_DIR"
  ln -sf "$PWD/.venv/bin/air-notify" "$HOME/.local/bin/air-notify"
  install -m 0644 "deploy/$UNIT" "$UNIT_DIR/$UNIT"
  systemctl --user daemon-reload
}

case "${1:-install}" in
  install)
    install_app
    systemctl --user enable --now "$UNIT"
    [[ "$(loginctl show-user "$USER" -p Linger --value)" == yes ]] \
      || echo "Note: run 'sudo loginctl enable-linger $USER' so it also runs at boot."
    echo "Installed and started $UNIT. Logs: journalctl --user -u air-notify -f"
    ;;
  update)
    git pull --ff-only
    install_app
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
    rm -f "$UNIT_DIR/$UNIT"
    systemctl --user daemon-reload
    echo "Removed $UNIT"
    ;;
  *)
    echo "usage: $0 [install|update|restart|uninstall]" >&2
    exit 2
    ;;
esac
