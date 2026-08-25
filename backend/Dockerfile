# The unified geo-agent image — the ONE-CONTAINER ATO LAW made real
# per the researched design (scratch/docs/oob/collabora-nested-setup-
# research.md): the PINNED Collabora CODE image is the FINAL BASE (its
# file capabilities on coolforkit-caps/coolmount survive as lower-layer
# xattrs — a COPY --from reconstruction loses them), and the Python
# runtime overlays it narrowly via /usr/local. The editor runs as a
# DIRECT SUBPROCESS under the entrypoint supervisor (setpriv to the
# cool user); jails stay ENABLED via the capability forkit with
# mount_jail_tree=false (link/copy population — the probed-safe mode
# under Docker's default seccomp/AppArmor with cap_add MKNOD only).
# Nested OCI runtimes and Docker-in-Docker are REJECTED (effectively
# privileged); disabling jails is REJECTED (macro surface).

# Stage 1 — build the React frontend that geo-agent serves + Playwright
# drives. Runs entirely in a node image; the runtime image never sees npm.
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json ./
COPY frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ .
RUN npm run build   # → /build/dist


# Stage 2 — build Python + native packages against Debian 13 (the same
# libc generation as the pinned Collabora base, both trixie).
FROM python:3.11-slim AS python-build
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt


# Stage 3 — the exact pinned Collabora runtime is the final base OS.
# Multi-arch digest (amd64/arm64/ppc64le). Collabora Online 25.04.9.2
# on Debian 13; /start-collabora-online.sh, the cool user (1001), the
# systemplate, and the capability forkit all intact.
FROM collabora/code@sha256:cfbf62dbed7f3a2bebeb634235c606613813a1857f85111da3a97db316029bba AS runtime
USER root
WORKDIR /app
ENV PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

# Python's official Debian build lives entirely under /usr/local —
# the narrow overlay. Its dynamically linked Debian libraries are
# installed explicitly.
COPY --from=python-build /usr/local/ /usr/local/
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    netbase \
    tzdata \
    libbz2-1.0 \
    libcrypt1 \
    libdb5.3t64 \
    libffi8 \
    libgdbm6t64 \
    liblzma5 \
    libncursesw6 \
    libreadline8t64 \
    libsqlite3-0 \
    libssl3t64 \
    libtinfo6 \
    libuuid1 \
    libzstd1 \
    zlib1g \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -c "import dbm.gnu, ssl, sqlite3"

# Playwright's Chromium + system libs: the unified container renders
# BY ITSELF when PYTHO_RENDER_CDP is empty; on spark the host CDP
# Chromium serves instead and this browser sits unused.
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# MinIO server baked into THIS image (one-container law). Loopback
# only; artifacts ride the S3 API; the S3 mirror is a background
# concern the engine never thinks about.
ARG TARGETARCH
RUN ARCH="${TARGETARCH:-amd64}" \
    && curl -fsSL -o /usr/local/bin/minio \
       "https://dl.min.io/server/minio/release/linux-${ARCH}/minio" \
    && chmod +x /usr/local/bin/minio

# The editor patch assets at the exact absolute paths the patch
# consumes, applied ONCE at build time (immutable image; a bundle/
# monkeypatch mismatch fails the BUILD, never first boot). The two
# pyuno debs are arch-vendored: absent for this arch = the Python/UNO
# macro bridge is skipped LOUDLY (viewer unaffected) — vendor the
# matching debs to restore it (recorded in the SBOM notes).
COPY editor/patch-editor.sh /patch-editor.sh
COPY editor/military_macro/ /military_macro/
COPY editor/pytho-logo.svg /pytho-logo.svg
COPY editor/editor-icons/ /editor-icons/
COPY editor/images_sukapura_svg.zip /images_sukapura_svg.zip
COPY editor/scripts/ /pytho-scripts/
COPY editor/debs/ /pytho-debs/
RUN chmod 0755 /patch-editor.sh \
    && PYTHO_EDITOR_PATCH_ONLY=1 /patch-editor.sh \
    && coolconfig update-system-template \
    && grep -q 'window.autoShowFeedback=false' /usr/share/coolwsd/browser/dist/global.js \
    && getcap /usr/bin/coolforkit-caps | grep -q cap_sys_chroot \
    && rm -rf /var/lib/apt/lists/* /tmp/mscorefonts

# Application files after the expensive editor/browser layers so source
# changes never re-download browsers or re-patch the editor.
COPY --from=frontend-build /build/dist /srv/geo-agent
COPY backend/ .
COPY backend/entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

EXPOSE 8000

# The Collabora base's own entrypoint is /start-collabora-online.sh —
# an explicit ENTRYPOINT is REQUIRED or /entrypoint.sh would be passed
# to it as an argument.
ENTRYPOINT ["/entrypoint.sh"]
