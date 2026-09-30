# air-notify

Push notifications (via [ntfy](https://ntfy.sh)) when an AirTag arrives at or leaves places you define.
It's a small daemon built on [FindMy.py](https://github.com/malmeloo/FindMy.py) that polls Apple's Find My network every 15 minutes.

## Where your data goes

| What | Where it lives | Who sees it |
|---|---|---|
| Apple ID password, iCloud tokens, device identity | macOS Keychain, item `air-notify` / `apple-session` | Apple only (the password never crosses the network; login uses SRP) |
| AirTag private keys | Keychain `air-notify` / `airtag` | Nobody. Apple only receives hashes of the rotating public keys, and locations are decrypted locally |
| ntfy topic | Keychain `air-notify` / `ntfy` | ntfy server |
| Alert text: zone name + time, **never coordinates** | ntfy | ntfy server |
| Zones (home/school coordinates) | `~/.config/air-notify/config.toml` (0600) | Nobody |
| Zone state, queued alerts | `~/.config/air-notify/state.json` (0600) | Nobody |

**Network hosts:** `gsa.apple.com`, `setup.icloud.com`, `gateway.icloud.com` and your ntfy server.
There is one more: `anisette.dl.mikealmel.ooo`, the FindMy.py maintainer's server. It's contacted **once**, to download Apple's anisette libraries into `ani_libs.bin` (already done). It receives no account data.

Other hardening:
- **Logging:** FindMy.py's own logs are capped at WARNING, because it logs the Apple ID at INFO and its anisette dependency logs device secrets at DEBUG.
- **Dependencies:** `findmy` is pinned to `>=0.10.2,<0.11`, because earlier versions skipped TLS verification. `uv.lock` pins every dependency by hash; review the FindMy.py changelog and diff before running `uv lock --upgrade`.

## Setup

**Before you start:**
- FindMy.py can't log in to Apple accounts that use **Security Keys** or passkey-only sign-in. Check Settings → Apple Account → Sign-In & Security.
- Install the ntfy app on your phone.

```sh
uv sync
cp config.example.toml ~/.config/air-notify/config.toml   # then edit the zones
```

### 1. Export the AirTag keys (one time; the most sensitive step)

On macOS 15+ the keys can't be read from local files, so they're exported from iCloud with the **OpenTagViewer exporter**.
It was audited before use:
- It contacts only Apple hosts and uses local anisette.
- It doesn't join your iCloud Keychain trust circle.
- It never writes your password or tokens to disk.

It needs your Apple ID, 2FA, and the screen-lock passcode of one of your devices. Run it yourself, in your own terminal.

```sh
umask 077 && mkdir -p ~/airtag-export && cd ~/airtag-export
git clone --branch exporter-v1.5.1 --depth 1 https://github.com/parawanderer/OpenTagViewer.git
git -C OpenTagViewer rev-parse HEAD      # must print bf9cf9b44e710fb07a2f83c7f5f9f8966a9636dc
cp ~/.config/air-notify/ani_libs.bin .   # reuse the libs: no second download
cd OpenTagViewer/python && uv sync --frozen --no-dev
uv run python -m exporter.cli --source icloud --no-password \
  --anisette-libs ~/airtag-export/ani_libs.bin -o ~/airtag-export/tags.zip
```

- Don't pass `--anisette-url`.
- Pick the AirTag when asked.
- If your account only offers SMS 2FA and it loops back to the code prompt (OpenTagViewer issue #236), stop instead of burning codes.

Then import the keys straight from the zip into the Keychain (nothing is extracted to disk), and clean up:

```sh
cd ~/dev/air-notify
uv run air-notify import-airtag ~/airtag-export/tags.zip --delete-source
rm -rf ~/airtag-export "$HOME/Library/Application Support/OpenTagViewer"
```

Finally, open **account.apple.com → Devices** and remove the "MacBook Pro" entry (serial `0PENTAG…`) that the exporter signed in as.

Optional: before deleting, drag `tags.zip` into 1Password as a backup. Re-exporting is a hassle.

### 2. Log in, set up ntfy, check

```sh
uv run air-notify login      # Apple ID + password (hidden) + 2FA code
uv run air-notify set-ntfy   # topic (hidden) + sends a test push
uv run air-notify check      # one fetch: inside/outside + distance per zone
```

For ntfy, subscribe to a long random topic in the app first (e.g. from `openssl rand -hex 16`). Anyone who knows the topic can read the alerts.

### 3. Run it in the background

```sh
deploy/launchagent.sh install     # also: restart (after config edits), uninstall
```

## Day to day

```sh
uv run air-notify status          # running? paused? last report, zone states
tail -f ~/Library/Logs/air-notify.log
```

Every safeguard that kicks in sends an ntfy alert:

| Situation | What the daemon does | You do |
|---|---|---|
| Apple rejects the session | Stops polling | `air-notify login` |
| Apple returns an error (429 rate limit, 503, anything unexpected) | Stops polling | `air-notify resume` when you're ready |
| Can't reach Apple (offline) | Retries once after 1 min, then every 15 min. One alert when the outage starts, one when it recovers | Nothing |
| Daemon crashed and restarted | Carries on. After 3 crashes within an hour it stops polling | `air-notify resume` |

A stopped daemon stays stopped across restarts and reboots. Alerts that can't be delivered are queued until ntfy is reachable again.

## Limitations

- **Near-owner blind spot:** Apple's network gets no reports while the AirTag is close to one of *your* devices. When you're home too, "arrived home" may not fire.
- **Latency:** usually 1–60 minutes, depending on other people's iPhones passing by. Alerts show when the tag was actually seen.
- **Sleep:** nothing is polled while the Mac sleeps.
- **Apple changes:** changes on Apple's side occasionally break FindMy.py. Watch its releases.

## Raspberry Pi (later)

- Use a **64-bit** OS: `unicorn` has no armv7 wheels.
- The Pi has no Keychain. Add a `SecretStore` backend in `keystore.py`, e.g. a 0600 file owned by a dedicated user, or systemd-creds. Replace the LaunchAgent with a systemd unit.
