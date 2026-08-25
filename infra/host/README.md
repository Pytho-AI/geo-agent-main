# Host-side user systemd units for headless map rendering

The headless map renderer (`backend/app/services/render/headless.py`,
behind `POST /api/v1/render`) connects via CDP to a HOST-side Chromium
for GPU acceleration on spark. GB10 doesn't deliver usable GPU to
containerized Chromium (12 hours of investigation: no combination of
`runtime: nvidia`, `--privileged`, `--device=/dev/dri`, host PID
namespace worked). Host Chromium with ANGLE/EGL is the only working
path — see `feedback_gb10_host_chrome_only.md` in the agent memory.

Two user-scope services running as the invoking user:

1. **`chromium-cdp.service`** runs `playwright_server.py` — spawns
   Chromium with `--headless=new --ozone-platform=headless
   --use-gl=angle --use-angle=gl-egl`, with `EGL_PLATFORM=surfaceless`
   in the env. Chromium binds CDP on `127.0.0.1:9222`.

2. **`cdp-forward.service`** runs `cdp_forward.py` — listens on
   `172.17.0.1:9222` (the docker bridge IP from the host's perspective)
   and forwards each connection to `127.0.0.1:9222`. This is how the
   geo-agent backend container reaches the host Chromium.

The geo-agent backend connects via
`chromium.connect_over_cdp(PYTHO_RENDER_CDP)` (compose default
`http://172.17.0.1:9222`). When `PYTHO_RENDER_CDP` is set and the
connect fails, the render FAILS loudly — restart the units; there is no
silent degrade on a GPU host. Hosts without GPU Chromium (cloud EC2)
skip this install entirely and set `PYTHO_RENDER_CDP=` (empty): the
backend then launches the Chromium baked into its own image and renders
through SwiftShader (correct output, CPU speed).

## No Xvfb, no sudo

The units are **user-scope** (`~/.config/systemd/user/`), not system-
scope (`/etc/systemd/system/`). The geo-agent install itself does NOT
require `sudo` — everything lives under the invoking user's home.

Chromium uses **surfaceless EGL**: `libEGL_nvidia.so.580.159.03` (ships
natively on DGX OS 7.2.3) creates a GPU context without an X display,
so **no Xvfb package is required**. Verified 2026-07-01: WebGL renderer
reports `ANGLE (NVIDIA Corporation, NVIDIA GB10/PCIe, OpenGL ES 3.2)`
and `max_texture_size 32768` (hardware limit, not SwiftShader's
software limit). Full end-to-end SITEMP render 7.1s parity with the
previous Xvfb-backed path.

## Base image (sysadmin, one-time per host)

The only step that needs root is enabling systemd user lingering so
the units survive reboot without a logged-in session:

```bash
sudo loginctl enable-linger $USER
```

If the deploy user doesn't already exist, create it first:

```bash
sudo useradd -m -s /bin/bash pytho
sudo loginctl enable-linger pytho
```

That's the whole sudo footprint. Every subsequent geo-agent deploy on
the host is sudo-free.

## One-time install per checkout (sudo-free)

Run as the deploy user, from the repo root:

```bash
cd ~/geo-agent
./scripts/install_geoagent.sh --host-render
```

The script:

1. Creates a Python venv at `~/.venvs/pw-gpu`.
2. Installs `playwright` from the airgap pip wheel cache under
   `airgap/wheels/` (or from pypi.org if online).
3. Unpacks the pre-packaged Playwright browsers tarball to
   `~/.cache/ms-playwright/` if it isn't already there.
4. Copies `chromium-cdp.service` + `cdp-forward.service` from
   `infra/host/` to `~/.config/systemd/user/`.
5. Runs `systemctl --user daemon-reload` and
   `systemctl --user enable --now chromium-cdp.service
   cdp-forward.service`.
6. Verifies via `curl http://127.0.0.1:9222/json/version` and (if
   docker is running) a curl from inside the geo-agent backend
   container to `http://172.17.0.1:9222/json/version`.

If you deploy the repo somewhere other than `~/geo-agent`, the script
symlinks it for you (`ln -sfn <checkout> ~/geo-agent`) — the unit files
reference `%h/geo-agent/` (systemd `%h` = user's home dir), so the
symlink is what keeps the ExecStart paths stable.

## Update flow

The units source Python scripts from `~/geo-agent/infra/host/`. When
the scripts change:

```bash
git -C ~/geo-agent pull
systemctl --user restart chromium-cdp.service cdp-forward.service
```

No `daemon-reload` needed unless the `.service` files themselves
changed.

## Verify

```bash
# Both units active
systemctl --user is-active chromium-cdp.service cdp-forward.service
# → active
# → active

# CDP endpoint reachable on loopback
curl -s http://127.0.0.1:9222/json/version | head -3
# → { "Browser": "HeadlessChrome/148.0.7778.0", ... }

# Reachable from inside a container via the docker bridge
docker exec geo-agent-backend-1 curl -s http://172.17.0.1:9222/json/version | head -3
# → same output

# GPU actually attached (spark only; on EC2 SwiftShader is the plan)
nvidia-smi --query-compute-apps=pid,used_memory --format=csv | grep headless_shell
# → non-zero VRAM allocation during renders
```

If a WebGL context probe is more your speed:

```bash
~/.venvs/pw-gpu/bin/python -c "
import asyncio, json
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.connect_over_cdp('http://127.0.0.1:9222')
        ctx = b.contexts[0] if b.contexts else await b.new_context()
        p = await ctx.new_page()
        await p.goto('data:text/html,<canvas id=c></canvas>')
        info = await p.evaluate('''() => {
            const c = document.getElementById(\"c\");
            const gl = c.getContext(\"webgl2\") || c.getContext(\"webgl\");
            const ext = gl.getExtension(\"WEBGL_debug_renderer_info\");
            return {
                renderer: gl.getParameter(ext.UNMASKED_RENDERER_WEBGL),
                max_tex: gl.getParameter(gl.MAX_TEXTURE_SIZE),
            };
        }''')
        print(json.dumps(info, indent=2))
asyncio.run(main())
"
# Spark should print: ANGLE (NVIDIA Corporation, NVIDIA GB10/PCIe, ...) + max_tex 32768
# c5.xlarge should print: ANGLE (SwiftShader) + max_tex ~16384
```

## Troubleshooting

* the geo-agent backend raises `CDP connect to http://172.17.0.1:9222
  failed` and renders 500 → either chromium-cdp or cdp-forward isn't
  running (with `PYTHO_RENDER_CDP` set there is deliberately no
  in-container fallback — a GPU host must not silently degrade).
  `systemctl --user status chromium-cdp.service cdp-forward.service`
* `curl http://127.0.0.1:9222/json/version` works but
  `curl http://172.17.0.1:9222/json/version` doesn't → cdp-forward
  isn't running (chromium is fine).
* Renders are slow / missing GPU → the WebGL probe above will tell
  you if ANGLE is hitting the GB10 or falling back to SwiftShader.
  If it says SwiftShader on spark, check that `EGL_PLATFORM=surfaceless`
  is actually set in the process env (`systemctl --user show
  chromium-cdp.service --property Environment` — should include it),
  and that `libEGL_nvidia.so.*` is present under
  `/usr/lib/aarch64-linux-gnu/`.
* Reboots dropped the services → `sudo loginctl enable-linger $USER`
  wasn't run on this host. That's the one sudo step the sysadmin must
  do once per host.
