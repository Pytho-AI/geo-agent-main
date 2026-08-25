#!/bin/bash
#
# Geo-agent host-side installer.
#
# The map render driver used to live in pytho-app. Under Task 6 of the
# map API unification plan it moved into geo-agent — the systemd units
# and Python venv install path came with it. Run this on every host
# that renders products (spark edge + cloud EC2 for now).
#
# Usage:
#   ./scripts/install_geoagent.sh --host-render
#
# The --host-render flag installs USER-SCOPE systemd units under
# ~/.config/systemd/user/ that spawn a headless Chromium bound to CDP
# on 127.0.0.1:9222 (chromium-cdp.service) and forward it to
# 172.17.0.1:9222 for docker bridge reach (cdp-forward.service). No
# sudo required beyond the one-time `loginctl enable-linger $USER` a
# sysadmin runs on the base image.
#
# See infra/host/README.md for the full design + verification steps.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HOST_RENDER=0
for arg in "$@"; do
    case "$arg" in
        --host-render) HOST_RENDER=1 ;;
        --help|-h)
            cat <<EOF
usage: install_geoagent.sh [--host-render]

  --host-render   Install user-scope host-side chromium-cdp +
                  cdp-forward systemd units so the geo-agent
                  container's /api/v1/render endpoint can drive
                  a GPU-accelerated Chromium via CDP over the
                  docker bridge. Sudo-free; base-image
                  responsibility is one-time
                  \`loginctl enable-linger \$USER\`.
EOF
            exit 0
            ;;
    esac
done

if [ "$HOST_RENDER" != "1" ]; then
    echo "nothing to do (pass --host-render to install the render units)"
    exit 0
fi

install_host_render() {
    echo "==> installing host-side chromium-cdp + cdp-forward (user scope)"

    local REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
    local HOST_DIR="$REPO_ROOT/infra/host"
    local UNIT_DIR="$HOME/.config/systemd/user"
    local VENV="$HOME/.venvs/pw-gpu"

    if [ ! -d "$HOST_DIR" ]; then
        echo "  ERROR: $HOST_DIR not found. Run this from inside a geo-agent checkout."
        return 1
    fi

    # Standard checkout location expected by the unit files (%h/geo-agent).
    if [ "$REPO_ROOT" != "$HOME/geo-agent" ] && [ ! -e "$HOME/geo-agent" ]; then
        echo "  symlinking $HOME/geo-agent -> $REPO_ROOT (unit ExecStart paths)"
        ln -sfn "$REPO_ROOT" "$HOME/geo-agent"
    fi

    # Python venv with playwright.
    if [ ! -x "$VENV/bin/python" ]; then
        echo "  creating venv at $VENV"
        python3 -m venv "$VENV"
    fi

    local WHEELS="$REPO_ROOT/airgap/wheels"
    if [ -d "$WHEELS" ]; then
        echo "  installing playwright from airgap wheels ($WHEELS)"
        "$VENV/bin/pip" install --no-index --find-links "$WHEELS" playwright
    else
        echo "  installing playwright from pypi (no airgap wheels found)"
        "$VENV/bin/pip" install playwright
    fi

    local BROWSER_TAR="$REPO_ROOT/airgap/playwright-browsers.tar.gz"
    local PW_CACHE="$HOME/.cache/ms-playwright"
    if [ ! -d "$PW_CACHE" ] || [ -z "$(ls -A "$PW_CACHE" 2>/dev/null)" ]; then
        if [ -f "$BROWSER_TAR" ]; then
            echo "  unpacking Playwright browsers from $BROWSER_TAR"
            mkdir -p "$PW_CACHE"
            tar -xzf "$BROWSER_TAR" -C "$PW_CACHE"
        else
            echo "  downloading Playwright browsers via playwright install (needs network)"
            "$VENV/bin/playwright" install chromium
        fi
    fi

    mkdir -p "$UNIT_DIR"
    install -m 0644 "$HOST_DIR/chromium-cdp.service" "$UNIT_DIR/chromium-cdp.service"
    install -m 0644 "$HOST_DIR/cdp-forward.service"  "$UNIT_DIR/cdp-forward.service"
    echo "  units installed at $UNIT_DIR"

    systemctl --user daemon-reload
    systemctl --user enable --now chromium-cdp.service cdp-forward.service

    echo "==> verifying"
    sleep 3
    if curl -sf --max-time 5 http://127.0.0.1:9222/json/version >/dev/null; then
        echo "  chromium-cdp OK on 127.0.0.1:9222"
    else
        echo "  WARN: 127.0.0.1:9222 not responding — check \`systemctl --user status chromium-cdp.service\`"
    fi
    if curl -sf --max-time 5 http://172.17.0.1:9222/json/version >/dev/null; then
        echo "  cdp-forward OK on 172.17.0.1:9222 (docker bridge)"
    else
        echo "  WARN: 172.17.0.1:9222 not responding — check \`systemctl --user status cdp-forward.service\`"
    fi

    if ! loginctl show-user "$USER" 2>/dev/null | grep -q Linger=yes; then
        echo ""
        echo "  NOTE: systemd user lingering is NOT enabled for $USER."
        echo "        Without linger, these units die when you log out and"
        echo "        don't start at boot. Ask a sysadmin to run once:"
        echo "          sudo loginctl enable-linger $USER"
    fi
}

install_host_render
