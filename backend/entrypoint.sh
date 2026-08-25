#!/usr/bin/bash
# geo-agent unified-container supervisor (the ONE-CONTAINER ATO law):
# MinIO + the editor (upstream: Collabora coolwsd) + uvicorn run as
# three supervised children; any child's exit terminates the container
# so compose restarts the whole accredited unit. The editor starts as
# the cool user via setpriv (never root, never
# --disable-cool-user-checking); its capability forkit acquires
# CHOWN/FOWNER/SYS_CHROOT from file capabilities — do NOT add
# --no-new-privs anywhere here, it breaks that transition.
set -Eeuo pipefail

mkdir -p /app/data /opt/cool/child-roots /opt/cool/cache
chown cool:cool /opt/cool/child-roots /opt/cool/cache 2>/dev/null || true

children=()
stopped=0

stop_children() {
    if [ "$stopped" -eq 1 ]; then
        return
    fi
    stopped=1
    trap - EXIT INT TERM
    if [ "${#children[@]}" -gt 0 ]; then
        kill -TERM "${children[@]}" 2>/dev/null || true
        wait "${children[@]}" 2>/dev/null || true
    fi
}

trap stop_children EXIT INT TERM

MINIO_DATA_DIR="${MINIO_DATA_DIR:-/app/data/minio}"
mkdir -p "$MINIO_DATA_DIR"
export MINIO_ROOT_USER="${MINIO_ROOT_USER:-geoagent}"
export MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-geoagent-artifacts}"
minio server "$MINIO_DATA_DIR" \
    --address 127.0.0.1:9000 \
    --console-address 127.0.0.1:9001 \
    > /app/data/minio.log 2>&1 &
children+=("$!")

# The editor serves under net.service_root=/geo-api/v1/editor so
# cool.html's ABSOLUTE asset URLs (/geo-api/v1/editor/browser/...)
# route back through the backend proxy — the outer proxy carries
# no root-path (/browser, /cool) forwards in this topology.
# mount_jail_tree=false selects link/copy jail population (the jail
# stays ENABLED via the capability forkit). Jails live on the image
# filesystem (/opt/cool/child-roots) — disposable process state,
# never the data volume. aliasgroup1 matches the internal WOPISrc
# exactly (loopback:8000 — this backend).
collabora_params=(
    --o:ssl.enable=false
    --o:ssl.termination=true
    # net.listen=any: the editor port is published on the host so the
    # consumer's nginx proxies session traffic (WS + statics) NATIVELY
    # — the session path's encoded WOPI URL must cross byte-for-byte
    # and no application bridge can guarantee that. Loopback-only
    # would reset the published port. WOPI callbacks still dial
    # loopback:8000; the host firewall scopes external exposure.
    --o:net.listen=any
    --o:net.proto=IPv4
    --o:net.service_root=/geo-api/v1/editor
    --o:mount_jail_tree=false
    --o:security.capabilities=true
    --o:security.seccomp=true
    '--o:storage.wopi.alias_groups[@mode]=groups'
    --o:admin_console.enable=false
    --o:welcome.enable=false
    --o:home_mode.enable=false
    --o:logging.level=warning
)
collabora_extra_params="${collabora_params[*]}"

if [ -x /start-collabora-online.sh ]; then
    setpriv --reuid=cool --regid=cool --init-groups \
        env \
        HOME=/opt/cool \
        USER=cool \
        LOGNAME=cool \
        DONT_GEN_SSL_CERT=YES \
        aliasgroup1="${WOPI_INTERNAL_ORIGIN:-http://127.0.0.1:8000}" \
        "extra_params=${collabora_extra_params}" \
        /start-collabora-online.sh \
        > /app/data/editor.log 2>&1 &
    children+=("$!")
fi

uvicorn_args=()
if [ -n "${UVICORN_EXTRA_ARGS:-}" ]; then
    read -r -a uvicorn_args <<< "$UVICORN_EXTRA_ARGS"
fi
uvicorn app.main:app --host 0.0.0.0 --port 8000 "${uvicorn_args[@]}" &
children+=("$!")

set +e
wait -n "${children[@]}"
status=$?
set -e
stop_children
exit "$status"
