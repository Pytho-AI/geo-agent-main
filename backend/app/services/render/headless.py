"""Playwright-based headless renderer for map states.

Loads geo-agent's own React SPA at `/geo-app/headless?map_id=...&bbox=...`
inside a process-wide warm Chromium, waits for `window.__renderReady === true`
(set by OperationsMapHeadless once MapLibre finishes its first idle and all
symbol/sprite work has landed), screenshots the canvas, returns JPEG bytes.

The React bundle is the same one the analyst edits with, so the captured
image matches what the user sees in the editor — no second renderer to
drift against.

Concurrency
-----------
One process-wide Chromium with per-render isolated contexts. Launching a
browser costs ~1.5-3 s (main process spawn + GPU process spawn + renderer
fork); keeping it warm and recycling contexts (~50 ms each) cuts ~2 s off
every render after the first. A semaphore (`RENDER_CONCURRENCY`, default
4) caps in-flight pages so a burst of renders can't stack enough tabs in
the warm browser to exhaust the backend container's memory.

Browser acquisition — two modes, keyed on PYTHO_RENDER_CDP
-----------------------------------------------------------
- PYTHO_RENDER_CDP set (spark default, http://172.17.0.1:9222): connect
  over CDP to the HOST-side GPU Chromium (chromium-cdp.service, installed
  by scripts/install_geoagent.sh --host-render). GB10 gives no GPU to
  containerized Chromium, so on spark this is the only correct path — a
  dead host Chromium is an operator problem (restart the unit), never a
  silent degrade.
- PYTHO_RENDER_CDP unset or EMPTY (cloud / unified-container mode): launch
  the Chromium bundled into this image by the Dockerfile's
  `playwright install --with-deps chromium`. Without a GPU it renders
  WebGL through SwiftShader — correct output, CPU-speed. Set
  `PYTHO_RENDER_CDP=` (empty) in .env to select this mode under compose,
  whose default otherwise points at the host CDP bridge address.

RENDER_WEBGL applies to the LAUNCH mode only ("swiftshader"/"software"
forces SwiftShader explicitly; anything else lets Chromium pick, which on
a GPU-less host is SwiftShader anyway). In CDP mode the host service owns
its own GL flags (infra/host/playwright_server.py).
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# CDP endpoint of a host-side Chromium. Non-empty -> connect_over_cdp
# (spark GPU path). Empty/unset -> launch the image-bundled Chromium
# in-process (cloud / unified-container path).
_CDP_ENDPOINT = (os.environ.get("PYTHO_RENDER_CDP") or "").strip()

# URL the render Chromium uses to reach the SPA it screenshots. The
# frontend lives in this same container's static mount at
# /geo-app/headless. Defaults per mode:
#   - CDP mode: the HOST-side Chromium reaches it via https://localhost
#     (a consumer nginx on the shared host routes /geo-app/ here).
#   - Launch mode: the browser runs INSIDE this container, so it hits
#     uvicorn directly at http://127.0.0.1:8000 — fully self-contained
#     (the /geo-api alias in main.py makes the SPA's API calls resolve).
# Override via GEO_AGENT_RENDER_HOST_BASE.
_GEO_AGENT_BASE = (
    (os.environ.get("GEO_AGENT_RENDER_HOST_BASE") or "").strip()
    or ("https://localhost" if _CDP_ENDPOINT else "http://127.0.0.1:8000")
)

# Concurrent in-flight pages cap inside the warm browser. ~150 MB peak
# per context — 4 keeps a render burst comfortably inside a few GB.
_RENDER_CONCURRENCY = int(os.environ.get("RENDER_CONCURRENCY", "4"))

# Optional GPU bypass.
_RENDER_WEBGL = os.environ.get("RENDER_WEBGL", "hardware").lower().strip()

# Process-wide warm browser pool. The Playwright driver subprocess is
# bound to the asyncio loop that called `async_playwright().start()`.
# When that loop closes (most commonly: tool_render_map runs via
# asyncio.run() which spawns a transient loop, or a FastAPI background
# task's loop ends), the driver becomes orphaned but
# `_BROWSER.is_connected()` keeps returning True because the WS to the
# WebKit process is still nominally open. Subsequent renders queue
# requests into the dead driver and hang forever (the asyncio reaper
# eventually logs "Loop ... that handles pid X is closed").
#
# Recovery: track which loop owns the warm state. If a render arrives
# on a different loop, tear down + re-init. Every Playwright call is
# also wrapped in asyncio.wait_for so a hung driver gets killed within
# a bounded window even when the per-call Playwright timeout fails to
# fire (which it does when the driver subprocess is dead).
_BROWSER_INIT_LOCK = threading.Lock()  # cross-loop singleton mutex
_BROWSER = None  # type: ignore[var-annotated]
_PLAYWRIGHT = None  # type: ignore[var-annotated]
_PW_CTX_MGR = None  # async_playwright() handle; held to prevent GC.
_OWNER_LOOP: Optional[asyncio.AbstractEventLoop] = None
_LAUNCH_GEN = 0  # bumped each re-init; surfaces in logs to track churn

# Per-loop concurrency semaphore. asyncio.Semaphore binds to the loop
# it's first awaited on; a module-level instance would reject every
# subsequent loop with RuntimeError. Lazy per-loop creation handles
# the sync-wrapper (asyncio.run) callers cleanly.
_SEM_BY_LOOP: dict[int, asyncio.Semaphore] = {}
_SEM_DICT_LOCK = threading.Lock()


def _get_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    key = id(loop)
    with _SEM_DICT_LOCK:
        sem = _SEM_BY_LOOP.get(key)
        if sem is None:
            sem = asyncio.Semaphore(_RENDER_CONCURRENCY)
            _SEM_BY_LOOP[key] = sem
        return sem


def _invalidate_warm_state() -> None:
    """Drop refs to the (likely dead) Playwright + browser. Caller must
    hold _BROWSER_INIT_LOCK. Do NOT await close() on the objects — when
    the driver subprocess is dead, the close hangs. We drop refs and
    let the OS reap the orphaned subprocess (`Loop that handles pid X
    is closed` is exactly that reaping)."""
    global _BROWSER, _PLAYWRIGHT, _PW_CTX_MGR, _OWNER_LOOP
    global _WARM_FAST_CTX, _WARM_FAST_PAGE, _WARM_FAST_KEY
    _BROWSER = None
    _PLAYWRIGHT = None
    _PW_CTX_MGR = None
    _OWNER_LOOP = None
    # Warm fast-mode context is owned by the (now-dead) browser; drop
    # refs so the next fast render builds a fresh one against the new
    # warm browser.
    _WARM_FAST_CTX = None
    _WARM_FAST_PAGE = None
    _WARM_FAST_KEY = None
    # Also drop semaphores tied to loops we no longer own — they'd leak
    # otherwise across loop generations.
    with _SEM_DICT_LOCK:
        _SEM_BY_LOOP.clear()


@dataclass
class RenderOptions:
    # 16:9 by default so the headless capture matches what the finished
    # product embeds into: ATP 2-01.3 landscape Letter DOCX (map area
    # ~10 in x 5.5 in ≈ 1.82:1) and 16:9 PPTX slides (1.78:1). The editor
    # (OperationsMap.tsx) locks its inner map container to a 16:9 wrapper
    # so the analyst sees the same framing the exporter captures.
    width: int = 1920
    height: int = 1080
    bbox: Optional[list[float]] = None      # [west, south, east, north] override
    layers: Optional[list[str]] = None      # subset of layer names to draw
    # 60s ceiling — goto + ready-signal wait + screenshot encode at
    # 2560x1440 commonly takes 15-30s on a busy GPU; 30s default tripped
    # the screenshot encoder mid-flight even when goto + ready completed
    # in time.
    timeout_ms: int = 60_000
    pixel_ratio: float = 1.5                # for crisper raster output
    # Per-render product type. Passed as the ?product_type= URL param to
    # OperationsMapHeadless. Frontend treats it as an opaque tag — the
    # actual per-product behavior (basemap raster, allowed kinds, layer
    # visibility, etc.) flows through the schema-driven URL primitives
    # below, NOT through frontend product-type switches.
    product_type: Optional[str] = None

    # ------------------------------------------------------------------
    # Schema-driven map render primitives. Every field is read by
    # tool_render_map from the active product schema (templates/products/
    # *.py map_* keys) and forwarded as a URL param to
    # OperationsMapHeadless. The frontend reads them as primitives and
    # applies directly --- no product-type switches in any client code.
    # ------------------------------------------------------------------
    # Tileserver style id for the basemap raster. Resolved from
    # schema's `map_basemap`. One of "default" / "terrain" / "topo" /
    # "satellite".
    basemap: Optional[str] = None
    # MapLibre layer ids on the OMT vector basemap that should be VISIBLE
    # (anything else is hidden via setLayoutProperty). Resolved from
    # schema's `map_basemap_layer_visibility`.
    basemap_layer_visibility: Optional[list[str]] = None
    # MapLibre layer ids in the doctrinal-MCOO layer set that should be
    # VISIBLE. Resolved from schema's `map_doctrinal_layer_visibility`.
    doctrinal_layer_visibility: Optional[list[str]] = None
    # SITEMP-style zoom-tiered topographic contour overlay. Resolved
    # from schema's `map_show_topographic_contours`.
    show_topographic_contours: Optional[bool] = None
    # Cluster individual mil_unit features into echelon icons. Resolved
    # from schema's `map_cluster_mil_units`.
    cluster_mil_units: Optional[bool] = None
    # Compact AA labels along the chevron. Resolved from schema's
    # `map_compact_aa_labels`.
    compact_aa_labels: Optional[bool] = None
    # Compact legend (tight packing for product types with many
    # symbols). Resolved from schema's `map_compact_legend_labels`.
    compact_legend_labels: Optional[bool] = None
    # Fast-path flag for the live-edit refresh_map endpoint. When True:
    #   - areTilesLoaded wait is capped at 5s (instead of 32s). Edge
    #     basemap tiles "never converging" is the common case; the
    #     compositor paints whatever is loaded, and the analyst only
    #     edited unit positions in the center of the AO anyway.
    #   - The post-tile 1500ms symbol-flush sleep is skipped. The SVG
    #     paint pass has already completed by the time __renderReady is
    #     true; the extra wait is paranoia for cold renders.
    # Net: 5-8s of render instead of 35-50s for the refresh case where
    # the basemap raster is already cached in Chromium's HTTP cache.
    # Full product renders keep the conservative defaults.
    fast: bool = False
    # Include one product record's DRAFT layer rows (the record's own
    # figure paints project + its own layer — fifth edition #2.2).
    include_draft_of: Optional[str] = None


# Reusable warm context + page for fast-mode renders. Module-level so
# every render hits the same in-memory HTTP cache: basemap raster tiles,
# vector tile sources, font glyph PBFs, the React bundle JS — all loaded
# once on the first render, then served from cache on every subsequent
# refresh_map. Big win for the analyst-edit loop where the tileserver
# state is unchanged between Done-editing clicks but the entity state is.
# Full (non-fast) renders still go through fresh contexts so dev-iteration
# style edits surface immediately.
_WARM_FAST_CTX = None
_WARM_FAST_PAGE = None
_WARM_FAST_KEY: Optional[tuple] = None  # (w, h, pixel_ratio) signature


async def _get_warm_browser():
    """Return the process-wide warm WebKit, launching it on first call
    and recovering from (a) a crashed browser by re-launching or (b) a
    loop-mismatch (the warm state was started under a different asyncio
    loop that has since closed) by tearing down + re-initializing.

    Held across renders so the GPU process + renderer cache stay warm —
    a fresh launch drops hardware-accel benefits for short workloads."""
    global _BROWSER, _PLAYWRIGHT, _PW_CTX_MGR, _OWNER_LOOP, _LAUNCH_GEN
    current_loop = asyncio.get_running_loop()

    # Fast path: warm state belongs to THIS loop and is connected.
    if _BROWSER is not None and _OWNER_LOOP is current_loop:
        try:
            if _BROWSER.is_connected():
                return _BROWSER
        except Exception:
            pass  # fall through to re-init under the lock

    # Slow path: re-init under the cross-loop init mutex. threading.Lock
    # (not asyncio.Lock) so any loop can take it without binding issues.
    with _BROWSER_INIT_LOCK:
        # Re-check under the lock — another concurrent caller on this
        # same loop may have already initialized.
        if _BROWSER is not None and _OWNER_LOOP is current_loop:
            try:
                if _BROWSER.is_connected():
                    return _BROWSER
            except Exception:
                pass

        if _OWNER_LOOP is not None and _OWNER_LOOP is not current_loop:
            logger.warning(
                "render: warm browser was owned by a different loop "
                "(gen=%d) — discarding and re-initializing for new loop",
                _LAUNCH_GEN,
            )
        _invalidate_warm_state()

        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError(
                "playwright is not installed. It ships in "
                "backend/requirements.txt and the image bakes its Chromium "
                "via `playwright install --with-deps chromium` "
                "(backend/Dockerfile) — a bare checkout needs both."
            ) from e
        _PW_CTX_MGR = async_playwright()
        _PLAYWRIGHT = await _PW_CTX_MGR.start()
        if _CDP_ENDPOINT:
            # CDP mode (spark): host-side GPU Chromium. The endpoint is
            # exposed by a host systemd unit (chromium-cdp.service) that
            # launches the Chromium binary DIRECTLY (not via Playwright
            # launch, which adds --remote-debugging-pipe and silently
            # overrides --remote-debugging-port); cdp-forward.service
            # exposes it on the docker bridge at 172.17.0.1:9222.
            # GB10 gives no GPU to containerized Chromium, so when this
            # endpoint is configured a dead host Chromium is an OPERATOR
            # problem (restart chromium-cdp.service) — never a silent
            # in-container degrade.
            try:
                _BROWSER = await _PLAYWRIGHT.chromium.connect_over_cdp(
                    _CDP_ENDPOINT)
            except Exception as e:
                raise RuntimeError(
                    f"CDP connect to {_CDP_ENDPOINT} failed. Host Chromium "
                    "down? Check `systemctl --user status "
                    "chromium-cdp.service cdp-forward.service` (installed "
                    "by scripts/install_geoagent.sh --host-render). On a "
                    "host with no GPU Chromium, set PYTHO_RENDER_CDP= "
                    "(empty) to use the in-container browser instead."
                ) from e
            mode = f"CDP {_CDP_ENDPOINT}"
        else:
            # Launch mode (cloud / unified container): drive the Chromium
            # baked into this image. WebGL goes through SwiftShader when
            # no GPU is present — correct output at CPU speed.
            _BROWSER = await _PLAYWRIGHT.chromium.launch(
                headless=True,
                args=_chromium_launch_args(),
            )
            mode = "in-container launch"
        _OWNER_LOOP = current_loop
        _LAUNCH_GEN += 1
        logger.info(
            "render: browser ready via %s (gen=%d, webgl=%s); base=%s",
            mode, _LAUNCH_GEN, _RENDER_WEBGL, _GEO_AGENT_BASE,
        )
        return _BROWSER


async def render_map_to_png(map_id: UUID, opts: Optional[RenderOptions] = None) -> bytes:
    """Render the given map to JPEG bytes. Reuses the warm browser pool;
    creates a fresh isolated context per render for clean cookies / storage.

    Every Playwright call is wrapped in asyncio.wait_for. Playwright's
    own per-call timeouts (`page.goto(timeout=...)`, etc.) fail to fire
    when the driver subprocess is hung — the timer lives in the same
    coroutine that's blocked on the dead driver, so it never gets to
    run. asyncio.wait_for is the last-resort kill: the timer lives in
    the calling coroutine and can cancel the wait independently.

    On any Playwright exception OR an asyncio.TimeoutError, the warm
    state is invalidated and the render is retried ONCE with a freshly-
    launched browser. A second failure propagates."""
    opts = opts or RenderOptions()

    url = _build_url(map_id, opts)
    # Asyncio-side ceilings — generous padding on top of Playwright's
    # own opts.timeout_ms so we don't double-trip on healthy renders
    # but still kill a hung driver within a bounded window.
    pw_s = max(opts.timeout_ms / 1000.0, 30.0)
    long_s = pw_s + 10.0

    last_err: Optional[BaseException] = None
    for attempt in (1, 2):
        sem = _get_semaphore()
        sem_remaining = getattr(sem, "_value", "?")  # private but stable
        logger.info(
            "render: url=%s gl=%s attempt=%d concurrency_remaining=~%s",
            url, _RENDER_WEBGL, attempt, sem_remaining,
        )

        try:
            browser = await asyncio.wait_for(_get_warm_browser(), timeout=60.0)
            async with sem:
                # Fast mode reuses a warm context+page so basemap raster
                # tiles, vector sources, glyphs, and the React bundle JS
                # all stay in HTTP cache across renders. The analyst-edit
                # refresh loop hits the same tile URLs every time — only
                # the /map/state response (entity positions) changes.
                use_warm = bool(opts.fast)
                warm_key = (opts.width, opts.height, opts.pixel_ratio)
                global _WARM_FAST_CTX, _WARM_FAST_PAGE, _WARM_FAST_KEY
                ctx_is_warm = False
                if use_warm and _WARM_FAST_PAGE is not None and _WARM_FAST_KEY == warm_key:
                    try:
                        _ = _WARM_FAST_PAGE.url
                        ctx = _WARM_FAST_CTX
                        page = _WARM_FAST_PAGE
                        ctx_is_warm = True
                    except Exception as exc:
                        logger.warning("render: stashed warm page dead, dropping: %s", exc)
                        _WARM_FAST_CTX = _WARM_FAST_PAGE = None
                        _WARM_FAST_KEY = None
                logger.info(
                    "render: fast=%s use_warm=%s ctx_is_warm=%s "
                    "stashed_key=%s want_key=%s",
                    opts.fast, use_warm, ctx_is_warm,
                    _WARM_FAST_KEY, warm_key,
                )
                if not ctx_is_warm:
                    ctx = await asyncio.wait_for(
                        browser.new_context(
                            viewport={"width": opts.width, "height": opts.height},
                            device_scale_factor=opts.pixel_ratio,
                            # Internal-CA self-signed cert on
                            # https://172.17.0.1 (IDX 26 internal mesh).
                            # Without this Chromium aborts the navigation
                            # at the TLS handshake and the page never
                            # loads, leaving the JPG path empty even
                            # though docker-api curl succeeds (curl -k
                            # ignores the cert, browser doesn't).
                            ignore_https_errors=True,
                        ),
                        timeout=15.0,
                    )
                    page = await asyncio.wait_for(ctx.new_page(), timeout=10.0)
                    page.on("pageerror", lambda err: logger.warning("render-pageerror: %s", err))
                    page.on(
                        "console",
                        lambda msg: msg.type in ("error", "warning")
                        and logger.warning("render-console[%s]: %s", msg.type, msg.text),
                    )
                    # Cache-disable is intentionally NOT applied in fast
                    # mode — the whole point of warm-context reuse is that
                    # basemap tiles + glyphs + bundle.js stay in cache.
                    # Full (non-fast) renders keep the cache-bust so
                    # tileserver-style edits during dev iteration surface
                    # immediately. Cache-disable is a no-op on WebKit
                    # (no CDP support) anyway, but Chromium-CDP renders
                    # honored it and lost the cache benefit.
                    if not opts.fast:
                        try:
                            cdp = await ctx.new_cdp_session(page)
                            await cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
                        except Exception as exc:
                            logger.warning("render: failed to disable HTTP cache: %s", exc)
                try:
                    # `networkidle` waits for the network to stay quiet for 500ms.
                    # At 2560x1440 with a busy basemap + maaamet-placenames vector
                    # tiles, the tile loader trickles requests for the full 30s
                    # timeout window and networkidle never trips. Switch to
                    # `domcontentloaded` (fires as soon as the React app mounts)
                    # and rely on the `__renderReady` flag — which already gates
                    # on map.loaded() + areTilesLoaded() — as the real signal.
                    await asyncio.wait_for(
                        page.goto(url, wait_until="domcontentloaded",
                                  timeout=opts.timeout_ms),
                        timeout=long_s,
                    )
                    await asyncio.wait_for(
                        page.wait_for_function(
                            "window.__renderReady === true",
                            timeout=opts.timeout_ms,
                        ),
                        timeout=long_s,
                    )
                    # __renderReady is set in OperationsMapHeadless after the
                    # initial paint, but raster basemap tiles on the AO edges
                    # can still be in-flight. Fast mode caps at 5s; full mode
                    # at 30s. If it never converges (one bad tile can hold
                    # this false forever), log and continue rather than hang.
                    # Fast mode tile cap. Was 5s; bumped to 20s because
                    # on a cold Chromium HTTP cache the first refresh
                    # downloads ~120 basemap tiles, and 5s was leaving
                    # half the map unrendered. With chromium-cdp's
                    # persistent on-disk cache, the SECOND refresh
                    # onwards finishes well under 20s anyway — this
                    # ceiling just covers the cold-cache case.
                    tile_wait_ms = 20_000 if opts.fast else 30_000
                    tile_wait_outer = (tile_wait_ms / 1000.0) + 2
                    try:
                        await asyncio.wait_for(
                            page.wait_for_function(
                                """() => {
                                  const m = window.__map;
                                  if (!m) return false;
                                  return m.loaded() && m.areTilesLoaded();
                                }""",
                                timeout=tile_wait_ms,
                                polling=400,
                            ),
                            timeout=tile_wait_outer,
                        )
                        logger.info("render: tiles fully loaded post-renderReady")
                    except Exception:
                        try:
                            still = await page.evaluate(
                                """() => {
                                  const m = window.__map;
                                  if (!m) return -1;
                                  let pending = 0;
                                  for (const k of Object.keys(m.style.sourceCaches || {})) {
                                    const sc = m.style.sourceCaches[k];
                                    if (sc && sc._tiles) {
                                      for (const t of Object.values(sc._tiles)) {
                                        if (t.state !== 'loaded' && t.state !== 'errored') pending++;
                                      }
                                    }
                                  }
                                  return pending;
                                }""",
                            )
                            logger.warning("render: areTilesLoaded timeout, %s tiles still pending", still)
                        except Exception:
                            logger.warning("render: areTilesLoaded timeout, pending count unavailable")
                    # Symbol-flush wait (full mode only — fast mode skips).
                    # Even after areTilesLoaded, the SVG doctrinal paint can
                    # have a draw queued for the next frame. 1500ms covers
                    # 37 mil-sym SVGs competing for texture-upload bandwidth.
                    if not opts.fast:
                        await page.wait_for_timeout(1500)
                    # JPEG q=90 instead of PNG. PNG zlib hit the screenshot
                    # ceiling at 2560x1440; JPEG finishes in 1-3s and is
                    # visually indistinguishable at print DPI.
                    jpg = await asyncio.wait_for(
                        page.screenshot(
                            type="jpeg",
                            quality=90,
                            animations="disabled",
                            caret="hide",
                            clip={"x": 0, "y": 0,
                                  "width": opts.width, "height": opts.height},
                            timeout=opts.timeout_ms,
                        ),
                        timeout=long_s,
                    )
                    return jpg
                finally:
                    if opts.fast:
                        # Stash the warm context+page so the next fast
                        # render reuses the HTTP cache. Don't close.
                        _WARM_FAST_CTX = ctx
                        _WARM_FAST_PAGE = page
                        _WARM_FAST_KEY = warm_key
                        logger.info("render: stashed warm ctx+page key=%s", warm_key)
                    else:
                        # ctx.close on a dead driver hangs — bound it.
                        try:
                            await asyncio.wait_for(ctx.close(), timeout=5.0)
                        except Exception:
                            pass
        except asyncio.TimeoutError as e:
            last_err = e
            logger.warning(
                "render: attempt %d hit asyncio.wait_for timeout — "
                "warm browser is dead, invalidating + retrying once",
                attempt,
            )
            with _BROWSER_INIT_LOCK:
                _invalidate_warm_state()
            if attempt == 2:
                raise RuntimeError(
                    f"headless render timed out twice on {url}"
                ) from e
        except Exception as e:
            # Other Playwright errors (browser crash mid-render, target
            # closed, etc.) — discard warm state and retry once. A second
            # failure means the issue is upstream (bad URL, dead nginx,
            # etc.) and not a stale-browser symptom; propagate.
            last_err = e
            logger.warning(
                "render: attempt %d failed (%s: %s) — invalidating warm "
                "browser and retrying once",
                attempt, type(e).__name__, str(e)[:200],
            )
            with _BROWSER_INIT_LOCK:
                _invalidate_warm_state()
            if attempt == 2:
                raise

    # Unreachable — the for-loop always either returns or raises. Belt-
    # and-suspenders just to satisfy the type-checker.
    raise RuntimeError(f"headless render failed unexpectedly: {last_err}")


def _chromium_launch_args() -> list[str]:
    # Privacy / telemetry kill-list. Chrome stable phones home far more
    # than Chromium does by default — every one of these has been
    # observed sending traffic to Google in a fresh-launch packet
    # capture. The render container runs air-gapped on IDX 26 anyway,
    # but the flags also strip ~200-400 ms of cold-launch overhead the
    # network-init code paths add.
    args = [
        "--no-sandbox",                              # required in container
        "--disable-dev-shm-usage",                   # /dev/shm too small
        "--disable-background-networking",           # safe-browsing, GAIA, fcm
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-breakpad",                        # no crash uploads
        "--disable-client-side-phishing-detection",
        "--disable-component-update",                # no live extension updates
        "--disable-default-apps",
        "--disable-domain-reliability",              # no DNS / cert reports
        "--disable-sync",                            # no signed-in sync
        "--disable-translate",
        "--metrics-recording-only",                  # UMA off
        "--mute-audio",
        "--no-default-browser-check",
        "--no-first-run",
        "--no-pings",                                # no <a ping=…> beacons
        "--password-store=basic",                    # no kwallet/secret-service
        "--use-mock-keychain",
        "--safebrowsing-disable-auto-update",
        "--disable-features="
        "Translate,"
        "BackForwardCache,"
        "AcceptCHFrame,"
        "AutoExpandDetailsElement,"
        "InterestFeedV2,"
        "MediaRouter,"
        "DialMediaRouteProvider,"
        "OptimizationHints,"
        "OptimizationGuideModelDownloading,"
        "CalculateNativeWinOcclusion,"
        "AutofillServerCommunication,"
        "CertificateTransparencyComponentUpdater,"
        "Reporting,"
        "PrivacySandboxSettings4,"
        "GlobalMediaControls,"
        "MediaSessionService",
    ]
    # Software WebGL. Newer Chromium refuses the SwiftShader WebGL
    # fallback unless it's explicitly allowed; without this flag a
    # GPU-less container gets `webglcontextcreationerror` and MapLibre
    # never paints. Host-GPU flag sets live in the host service
    # (infra/host/playwright_server.py), not here — this function only
    # ever configures the in-container launch.
    args.append("--enable-unsafe-swiftshader")
    if _RENDER_WEBGL in ("swiftshader", "software"):
        # Force SwiftShader even if some GPU is visible.
        args.extend(["--use-gl=angle", "--use-angle=swiftshader"])
    return args


def _build_url(map_id: UUID, opts: RenderOptions) -> str:
    params = [f"map_id={map_id}", f"w={opts.width}", f"h={opts.height}"]
    if opts.bbox and len(opts.bbox) == 4:
        params.append("bbox=" + ",".join(str(v) for v in opts.bbox))
    # Allowed overlay/entity kinds (from schema map_overlay_kinds). The
    # frontend filters its feature collections by this list before
    # painting, so no product-specific kind-checks live in the client.
    if opts.layers:
        params.append("layers=" + ",".join(opts.layers))
    if opts.product_type:
        params.append(f"product_type={opts.product_type}")
    # ----- Schema-driven render primitives. -----
    # Tileserver style id (basemap raster). One of "default" / "terrain" / "topo" / "satellite".
    if opts.basemap:
        params.append(f"basemap={opts.basemap}")
    # Comma-separated MapLibre layer ids that should be VISIBLE on the
    # OMT vector basemap. Anything not listed is hidden.
    if opts.basemap_layer_visibility:
        params.append("basemap_layers="
                      + ",".join(opts.basemap_layer_visibility))
    # Comma-separated MapLibre layer ids that should be VISIBLE in the
    # doctrinal-MCOO layer set (created by applyDoctrinalControlMeasures).
    if opts.doctrinal_layer_visibility:
        params.append("doctrinal_layers="
                      + ",".join(opts.doctrinal_layer_visibility))
    # Boolean primitives — pass as 0/1 strings so the frontend's
    # truthy check against the URL value is unambiguous (empty / absent
    # vs "0" vs "1").
    if opts.show_topographic_contours is not None:
        params.append(
            f"contours={1 if opts.show_topographic_contours else 0}")
    if opts.cluster_mil_units is not None:
        params.append(
            f"cluster_units={1 if opts.cluster_mil_units else 0}")
    if opts.compact_aa_labels is not None:
        params.append(
            f"compact_aa={1 if opts.compact_aa_labels else 0}")
    if opts.compact_legend_labels is not None:
        params.append(
            f"compact_legend={1 if opts.compact_legend_labels else 0}")
    # One record's draft layer joins the paint (the record's own
    # figure — fifth edition #2.2). The headless page forwards it to
    # /map/state verbatim.
    if opts.include_draft_of:
        params.append(f"include_draft_of={opts.include_draft_of}")
    # Informational param — actual DPR is set on the browser context above.
    params.append(f"pixel_ratio={opts.pixel_ratio}")
    base = _GEO_AGENT_BASE.rstrip("/")
    return f"{base}/geo-app/headless?{'&'.join(params)}"


def render_map_to_png_sync(map_id: UUID, opts: Optional[RenderOptions] = None) -> bytes:
    """Sync convenience wrapper for callers outside an asyncio loop."""
    return asyncio.run(render_map_to_png(map_id, opts))
