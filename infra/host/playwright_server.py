"""Persistent host-side Chromium with GPU acceleration, exposing the
Chrome DevTools Protocol (CDP) endpoint so docker-api's Playwright
client can attach via `chromium.connect_over_cdp(...)`.

This is the GPU-accelerated path for headless map rendering on GB10.
Containerized Chromium does not get usable GPU on this hardware (12
hours of investigation: runtime: nvidia, --privileged, --device=/dev/dri,
host PID ns — all ruled out). Host Chromium with ANGLE/EGL is the only
working option.

Architecture: this script binds CDP to 127.0.0.1:9222 only. cdp_forward.py
forwards 172.17.0.1:9222 -> 127.0.0.1:9222 so docker-api can reach it
across the docker bridge. Both run as USER-SCOPE systemd units at
`~/.config/systemd/user/` — see README.md for the sudo-free install.

Surfaceless EGL: no X display / no Xvfb required. libEGL_nvidia
creates a surfaceless context directly against the GPU when Chromium
is spawned with `--headless=new --ozone-platform=headless` and the
process env carries `EGL_PLATFORM=surfaceless`. Verified 2026-07-01
on DGX Spark 7.2.3 — WebGL renderer reports
`ANGLE (NVIDIA Corporation, NVIDIA GB10/PCIe, OpenGL ES 3.2)`,
`max_texture_size 32768` (hardware limit, not SwiftShader's software
limit). Full end-to-end SITEMP render 7.1s parity with the previous
Xvfb-backed path.

Started by ~/.config/systemd/user/chromium-cdp.service.
"""
import asyncio
import os
import sys
from playwright.async_api import async_playwright

CDP_PORT = int(os.environ.get("PW_CDP_PORT", "9222"))
CDP_HOST = os.environ.get("PW_CDP_HOST", "127.0.0.1")


async def main():
    # Force surfaceless EGL context creation on the NVIDIA driver.
    # `libEGL_nvidia.so.580.159.03` (ships natively on DGX OS 7.2.3)
    # supports EGL_KHR_platform_surfaceless — no X display / no Xvfb
    # needed. See the surfaceless test at
    # infra/host/README.md#verify for the empirical confirmation.
    os.environ["EGL_PLATFORM"] = "surfaceless"
    # Belt + suspenders: explicitly drop DISPLAY so Chromium can't
    # accidentally fall back to X even if an Xvfb was left running.
    os.environ.pop("DISPLAY", None)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                f"--remote-debugging-port={CDP_PORT}",
                f"--remote-debugging-address={CDP_HOST}",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                # New headless mode (Chromium 105+, uses Ozone).
                # Old `--headless` needed an X display / Xvfb;
                # `--headless=new` supports surfaceless EGL directly.
                "--headless=new",
                # Ozone's headless platform: no X, no Wayland — GPU
                # context is created against the surfaceless EGL
                # platform set via the EGL_PLATFORM env above.
                "--ozone-platform=headless",
                # NVIDIA GB10 GPU flags — verified working on this
                # host via ANGLE-EGL against libEGL_nvidia.
                "--use-gl=angle",
                "--use-angle=gl-egl",
                "--ignore-gpu-blocklist",
                "--enable-gpu-rasterization",
                "--enable-zero-copy",
                # nvidia-container-toolkit's seccomp filter doesn't
                # expose every syscall Chromium's GPU sandbox wants.
                # Disable the sandbox at the GPU-process layer — the
                # main process still runs unsandboxed via --no-sandbox
                # so this is not an added exposure.
                "--disable-gpu-sandbox",
            ],
        )
        sys.stderr.write(
            f"[pw-server] Chromium CDP listening at http://{CDP_HOST}:{CDP_PORT}\n"
        )
        sys.stderr.flush()
        # Block forever — exit when killed.
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
