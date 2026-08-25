# CLAUDE.md — geo-agent

## What this service is

Geo-Agent is THE map subsystem — a STANDALONE service with ONE public
surface. It owns everything map-related: the analyst map UI, basemap
tile rendering and caching, vector label tiles, map-state/overlay data,
the realtime channel, natural-language map operations, and server-side
product-map rendering.

Consumers (pytho-app edge, V Corps, cloud, anything) reach it at its
host-published port — `http://<host>:9845` — and NOTHING else. No
consumer ever joins geo-agent's docker network, proxies its tileserver,
or caches its tiles. That coupling existed once (shared `pytho-net`,
per-consumer nginx tile caches, `docker-compose.pytho.yml` overlay) and
was ripped out 2026-07-06; do not reintroduce any of it.

## Compose stack (docker-compose.yml — the ONE compose file)

- **backend** (FastAPI, host port **9845** — the single public surface).
  Serves the `/api/v1` REST API (also aliased at `/geo-api/*` by a pure
  ASGI rewrite in main.py, so the SPA's baked-in `/geo-api/v1` default
  works with OR without a consumer nginx), the WebSocket, the render
  endpoint, ALL tile endpoints, and the built React frontend as static
  files under `/geo-app` (SPA fallback; baked into the image by the
  multistage Dockerfile, stage 1 node build → `/srv/geo-agent`).
- **tilecache** (nginx:1.27-alpine, INTERNAL only). On-disk tile cache
  fronting the tileserver — tileserver-gl has no persistent cache of its
  own; its deployment docs direct you to front it with a caching proxy.
  365d TTL, `proxy_cache_lock` collapses MapLibre's ~20-tile pan bursts.
  Also owns the ESRI World Imagery satellite proxy (TMS y-flip) and the
  **self-resolving Protomaps planet URL** (below).
- **tileserver** (tileserver-gl v5.6.0, INTERNAL only — no host port).
  Renders `default` + `terrain` + `topo` + `labels` styles from
  Protomaps planet PMTiles + Mapterhorn terrain DEM
  (`tiles.mapterhorn.com/{z}/{x}/{y}.webp`). Zero local tile archives.
  Depends on tilecache: it opens the planet archive THROUGH it.
  Style/sprite edits MUST bump `$style_rev` in
  `infra/tilecache/nginx.conf` in the same commit — rendered tiles are
  cached 365d and the rev is the only invalidation.
- **db** (imresamu/postgis:16-3.4 — multi-arch; upstream postgis is
  amd64-only and the DGX Spark is aarch64). Host port 9846. Entities,
  overlays, routes, snapshots.

## The self-resolving planet PMTiles (never pin a date)

Protomaps prunes dated builds (`build.protomaps.com/YYYYMMDD.pmtiles`)
off its CDN after a few weeks, so a pinned date rots: fresh tileserver
starts 404 + crash-loop, and running ones break mid-flight when their
build is pruned.

`infra/tileserver/tileserver-config.json` therefore points at the STABLE
internal URL `http://tilecache:8080/planet.pmtiles`. An njs handler
(`infra/tilecache/pmtiles_resolver.js`) resolves it at request time:
probe dated builds counting down from tomorrow (UTC), lock the newest
200 into a shared dict, proxy all range reads to it. On a mid-flight
upstream 404 the stale handler re-probes, re-locks, and serves that
request itself via a buffered ranged `ngx.fetch` (an
`r.internalRedirect` from an `error_page` context does NOT re-enter the
proxy — mock-CDN verified; the buffered fetch is the fix, with
`js_fetch_max_response_buffer_size 32m` for directory-sized reads).

NEVER "fix" a tile outage by pinning a date in tileserver-config.json.
Diagnose with `docker logs geo-agent-tilecache-1 | grep -E "locked|pmtiles"` —
look for `locked onto build` / `re-locked onto` lines.

## Tile endpoints (backend/app/api/v1/tiles.py)

All tiles enter through the backend — consumers and the frontend never
see the tileserver or tilecache:

- `GET /api/v1/tiles/basemap/{default|terrain|topo}/{z}/{x}/{y}.jpg` —
  opaque rendered raster, JPG on purpose (disk/cache footprint).
- `GET /api/v1/tiles/basemap/satellite/{z}/{x}/{y}.jpg` — ESRI proxy.
- `GET /api/v1/tiles/vector/basemap/{z}/{x}/{y}.pbf` — raw Protomaps
  vector tiles feeding the CLIENT-SIDE place-label symbol layers (labels
  stay upright under rotation; decluttered by Protomaps `min_zoom`).
  Never bake labels into the raster.
- `GET /api/v1/tiles/dem/{z}/{x}/{y}.webp` — Mapterhorn Terrarium DEM
  via the tilecache's /dem block. Feeds the CLIENT-SIDE contour source
  (`frontend/src/geo-agent/utils/contours.js`): brown topo-sheet
  contours ride the `topo` basemap; the black doctrinal treatment is
  gated by the `map_show_topographic_contours` schema primitive
  (headless: ?contours= param; live/edit: the stored render spec via
  GET /api/v1/render/spec/{map_uuid}). Contours are never baked into
  the raster.
- `GET /api/v1/tiles/labels/{z}/{x}/{y}.png` — legacy raster labels.
- `GET /api/v1/fonts/{fontstack}/{range}.pbf` — glyphs.

## Render (backend/app/services/render/headless.py + api/v1/render.py)

`POST /api/v1/render` renders a product map to JPG by driving headless
Chromium against this service's OWN frontend at `/geo-app/headless` and
waiting for `window.__renderReady` — the exported product is the exact
MapLibre + tactical-paint pipeline the analyst edits with.

Two browser modes, keyed on `PYTHO_RENDER_CDP`:

- **Set (spark default `http://172.17.0.1:9222`)** — connect over CDP to
  the HOST-side GPU Chromium (chromium-cdp.service; GB10 gives no GPU to
  containerized Chromium, see `infra/host/README.md` — 12 hours of
  validation behind that). A dead host Chromium FAILS the render loudly;
  the fix is `systemctl --user restart chromium-cdp.service`, never a
  silent degrade.
- **Empty (`PYTHO_RENDER_CDP=` in .env) — cloud / unified container** —
  the backend launches the Chromium baked into its own image
  (`playwright install --with-deps chromium` in backend/Dockerfile).
  WebGL runs through SwiftShader (`--enable-unsafe-swiftshader` is
  passed; newer Chromium refuses software WebGL without it). Correct
  output at CPU speed; the render base defaults to
  `http://127.0.0.1:8000` so the whole loop stays inside the container.

## Agentic self-iteration / headless verification

The map is verifiable WITHOUT a human eyeball or a GPU — never write off
a black canvas as "headless doesn't work":

- **RAF backstop is in the product** (`frontend/src/geo-agent/utils/
  rafBackstop.js`, imported first in main.jsx). Chromium suspends
  requestAnimationFrame in hidden/backgrounded/automation tabs, which
  used to freeze MapLibre's deferred style load at a black canvas. The
  shim timer-backstops every RAF callback, so background tabs and
  automation harnesses load the map like a foreground tab. If the canvas
  is black anyway, it is a REAL bug — read the console, don't blame the
  harness.
- **Driving your own Chromium at the UI**: pass
  `--enable-unsafe-swiftshader` when the browser runs without GPU
  (`--disable-gpu`, headless CI boxes) — without it newer Chromium
  refuses the SwiftShader WebGL context and MapLibre dies with
  `webglcontextcreationerror` before painting anything.
- **Standalone works**: the backend serves `/geo-api/*` natively (alias
  middleware in main.py), so `http://localhost:9845/geo-app/
  operations-map` is a fully functional analyst UI with no consumer
  nginx in front.
- **Ready signals to wait on**: `/geo-app/headless` sets
  `window.__renderReady === true` after paint settles and exposes
  `window.__map` for probes (`map.loaded()`, `areTilesLoaded()`,
  `queryRenderedFeatures`). `window.__doctrinalPainted` flips when the
  doctrinal SVG pass has drawn.
- **The authoritative check is `POST /api/v1/render`**: it drives the real SPA
  through the real tile plane and returns the JPG — open the bytes and
  LOOK at them. `{"map_uuid": …, "persist": true}` then
  `GET /api/v1/render/latest/{map_uuid}.jpg` re-fetches it.
- **Whole-stack check**: `./deploy.sh` (or `./rebuild.sh <target>`) ends
  with the verification battery against :9845.

## Frontend (frontend/ — React + Vite + MapLibre)

The analyst map UI (`/geo-app/operations-map`: sidebar toggles,
right-click generate, edit-map, per-COA SITEMP, signal reports) and the
chrome-less render target (`/geo-app/headless`). Map styles + basemap
catalog mirror: `frontend/src/geo-agent/utils/mapStyles.js`. API base is
relative `/geo-api/v1` (`VITE_GEO_AGENT_API_URL`) so all calls ride the
embedding stack's own nginx. Cross-frame: the child posts
`{type:'geoagent.navigate', url}` and the parent shell react-router
navigates. A frontend change ships via a backend image rebuild
(multistage) — consumers need no rebuild.

## Consumer contract (the whole integration)

THE POINT OF THE UNIFICATION IS THAT THIS SURFACE IS EXTREMELY SMALL.
A consumer integrates with exactly three things:

1. nginx (or any HTTPS reverse proxy): `upstream geo_agent { server
   host.docker.internal:9845; }`, blocks for `/geo-app/`,
   `/geo-api/v1/ws`, `/geo-api/` (rewrite `/geo-api/*` → `/api/*` —
   optional since the backend also serves `/geo-api/*` natively), and
   `extra_hosts: ["host.docker.internal:host-gateway"]`.
2. Backend env: `GEO_API_URL=http://host.docker.internal:9845` — the ONE
   knob; consumers derive `/api/v1` and `/api/v1/render` from it.
3. Frontend: an IFRAME of `/geo-app/operations-map` + the two postMessage
   hooks. (`VITE_GEO_AGENT_API_URL=/geo-api/v1` is a build arg of THIS
   repo's frontend, not something consumers configure.)

Nothing else. EVERYTHING map-shaped lives inside the iframe — geo-agent's
own frontend fetches its own tiles, styles, glyphs, symbols, and map
state SAME-ORIGIN through the proxy. Consequences, spelled out because
they keep being missed:

- A consumer NEVER fetches tiles. No `/tiles/*` URLs, no basemap style
  objects, no MapLibre/Mapbox sources pointed at geo-agent, no tile
  proxy blocks in consumer nginx, no per-consumer tile caches. If
  consumer code contains a tile URL, it is a bug — rip it out.
- A consumer NEVER holds map UI. No vendored/forked copy of this
  frontend, no in-process `<GeoAgentMap>` mount, no map panels, no
  banners, no Done buttons. A vendored copy is not "integration", it is
  a fork that silently falls behind every doctrinal-paint, chrome,
  realtime, and render fix shipped here. Migrating a pre-unification
  consumer means DELETING its copy and replacing it with the iframe —
  never syncing the copy forward.
- A consumer's backend talks to the EXTERNAL API only (README "External
  API": /render, /render/latest, maps upsert/sync, /map/state,
  /basemaps). Everything else is the embedded UI's internal API.
- This applies to EVERY consumer identically — edge, cloud, V Corps,
  test stacks. "Cloud is different" is not a thing; the cloud consumer
  embeds the same iframe against its own geo-agent host.

Reference doc:
`scratch/docs/map-api/geo-agent-map-api.md` (parent-of-repos scratch).

## API surface (backend/app/api/v1/, all under /api/v1)

The EXTERNAL contract (README.md "External API") is deliberately tiny:
the iframe embed + two hooks, POST /render (+replay/persist),
GET /render/latest/{map_uuid}.jpg, PUT /maps/{id}, POST /maps/{id}/sync,
GET /map/state, GET /basemaps. EVERYTHING else below is the embedded
map UI's own internal API — never document it as integration surface or
make a consumer wire it. Keep README's external section in lockstep
when touching those routes. Agent quick reference (internal included):

- `map/state?map_id&bbox&kinds` — everything painted on a map, GeoJSON.
- `entities` / `overlays` — CRUD; create takes `?map_id&user_id` query
  params + `{kind, geom, attrs}` body.
- `geoops` — batched auditable mutations `{map_id, user_id, ops:[…]}`;
  ops: create/move/update/delete_entity, create/delete_overlay,
  create/delete_route. Each op broadcasts on the map's WS.
- `maps/{id}` — PUT upserts viewport + attrs. attrs IS the live session
  state (basemap + layer_visibility persist there; render replay reads
  them back). `maps/{id}/snapshots[...]` — history/restore.
- `routes` — plan (A*, on_road|off_road|mixed), analyze-edit, paths,
  discover-corridors, synthesize-mcoo.
- `nl/query|update|chat` — `{text, map_id, user_id, bbox?}`.
- `cop/generate`, `cop/{map_id}`. `artifacts` + `/{id}/ingest`.
- `ws?map_id` — frames `{type, data}`: entity_created/updated/deleted,
  overlay_created, ingest_complete. "ping"→"pong" keepalive.
- `render` — POST, `map_uuid` required; `replay: true` re-renders from
  the per-map stored spec (stashed on every non-replay render) with
  explicitly-set fields overriding; `persist: true` stores the JPG,
  served at `GET render/latest/{map_uuid}.jpg` (no-store). This
  replay+persist pair IS the edit-session Done flow.
  `GET render/spec/{map_uuid}` — INTERNAL: returns the stored spec so
  the live/edit surface inherits product render primitives (today the
  contour gate via OperationsMap's RenderSpecStash); 404 = no product
  presets.
- `events` — INTERNAL persistent telemetry (analyst_events table in the
  stack's PostGIS, survives container recreates). POST `/events` (one
  event or `{events:[...]}`, tolerant ingest), GET `/events` (filters:
  map_id / user_id / event_type incl. `prefix.*` / since_ms / limit),
  POST `/events/client-log` (browser log forwarding → the `geo.client`
  server logger, which ALSO lands in the data-volume file log, + a
  queryable row). Frontend capture: lib/analystEvent.ts (every
  utils/api.js mutation via the audit wrapper, layer prefs / weather /
  roll-up in GeoAgentProvider, map + edit-session opens and Done in
  OperationsMap, snapshots) and lib/clientLog.ts. Backend errors also
  persist to `{GEO_DATA_DIR}/logs/backend.log` (rotating, alongside
  stdout — set up in main.py).
- `terrain/peaks?bbox=w,s,e,n` — INTERNAL: spot-height source. Decodes
  the z11 planet tiles covering the bbox server-side (peaks only exist
  in tiles from z11, so the client can't read them at operational
  view zooms) and joins elevations from the Mapterhorn DEM (5x5
  local-max per peak). Feeds MapDoctrinalPaint's spot-height layer;
  headless renders with the contour primitive WAIT for the first
  publish (OperationsMapHeadless readiness gate) so exports carry the
  labels.
- `tiles/*`, `fonts/*` — INTERNAL: geo-agent's own frontend is the only
  caller (same-origin through the consumer's /geo-api forward). Never
  document or wire them as external API — external image needs go
  through `/render` / `/render/latest`. `basemaps` — catalog.

## Edit-session contract (frontend, pages/OperationsMap.tsx)

`/geo-app/operations-map` is THE map surface for every embed mode;
consumers assemble URLs and listen for hooks — they hold ZERO map UI
(no banners, no Done buttons, no mode logic; that was moved in-map
deliberately, do not re-add chrome to consumers):

- `?map_id&bbox` — read-only live map.
- `+ editEnabled=1&product_type=…` — edit session: edit affordances,
  16:9 exporter framing, in-map "Editing map for …" banner + Done
  editing button. Toggles persist onto the map record as the analyst
  works.
- `+ render=1` — product embeds a rendered figure: Done POSTs this
  service's OWN `/render {map_uuid, replay:true, persist:true,
  basemap:<session>}` (button shows "Rendering…"), then posts the hook.
- Hooks (child → parent postMessage):
  `{type:'geoagent.navigate', url}` and
  `{type:'geoagent.editDone', map_id, rendered, image_url?, error?}`.
  The parent's ONLY job on editDone is the document-side embed —
  download image_url, swap into the DOCX/PPTX. Consumers NEVER trigger
  renders.
- The rendered figure is DOCUMENT content (bytes in the DOCX/PPTX zip,
  swapped by the consumer's refresh handler via UNO) — never an iframe.

## The tool surface is the ONLY interaction surface

ALL interaction with a geo-agent deployment — reads, data repairs,
operational actions, by humans and agents alike — goes through the
tool surface: the MCP tools and the API that deployment serves.
NEVER ssh into the box, NEVER psql into its database, NEVER docker
exec for data work. The deployment behind the surface is not the
caller's business; that is the point of the surface. If the tools
cannot do something the work needs, that is a TOOL GAP: add the
capability to the surface (a batched tool with per-item echoes,
registered in tools.py + mcp_server.py, following the conventions
below), deploy, and do the work through it. Side-channel surgery is
banned because it diverges the deployment from what the surface —
and every agent using it — believes, and it bypasses the audited,
attributed write path.

## Key conventions

- ONE entity-type registry: `ENTITY_TYPE_SEED` in
  `backend/app/models/graph.py` is the single authority. Everything
  else DERIVES from it — the DB `entity_types` table (seeded by
  bootstrap), `GRAPHIC_TYPES` (seed keys with an overlay-catalog
  renderer contract in `constants/overlays.py`),
  `EXTRACTABLE_ENTITY_TYPES` (seed minus reference-only types), the
  extraction prompt enum, and the MCP `set_shapes` kind enum. NEVER
  hand-mirror a type list into a prompt, docstring, or frontend
  constant; the frontend takes overlay labels/categories from
  `/config` overlayTypes. Adding a kind = one seed row + one overlay
  catalog entry (which IS what makes it paint and gives it its
  overlay-selector chip). Same law for render styling: the catalog
  stamps THE primitive per kind + geometry class — a kind that does
  not paint gets a catalog entry (`primitive_polygon` etc.), never a
  geometry-conversion fallback in the paint layers.
- Multi-tenant scoping: GLOBAL, WORKSPACE, SESSION, USER.
- All geometry is GeoJSON. Pydantic v2 schemas in `schemas/`.
- SQLAlchemy 2.0 + asyncpg + GeoAlchemy2; PostGIS 16/3.4.
- WebSocket broadcasts entity/overlay changes; any sync/ingest frame
  bumps the frontend's refresh trigger.
- `backend/app` is bind-mounted in compose — backend code changes load
  on container restart, no image rebuild. Frontend changes need the
  image rebuild. nginx/tilecache conf changes need a FORCE-RECREATE
  (bind-mount inode decoupling: `git pull` writes a new inode; a running
  container keeps the old file until recreated).

## Deploy (spark)

`ssh spark-dev`, checkout at `~/geo-agent` (tracks whatever branch that
deployment rides — an event/deployment concern, never hardcoded in this
repo's docs or scripts). Push freely. The ONLY sanctioned paths are the
repo scripts — never hand-rolled compose chains (they don't touch git;
pull is a separate step):

- `git pull --ff-only && ./deploy.sh` — production deploy:
  full rebuild + deep verification battery (health, catalog, all four
  tile shapes, /geo-app, headless target, render/latest route).
- `./rebuild.sh api|frontend` — backend code / frontend change (both
  rebuild+recreate the backend container; frontend is baked into the
  same image).
- `./rebuild.sh tiles` — tilecache/tileserver conf, styles, sprites,
  pmtiles resolver (FORCE-recreate — bind-mount inode decoupling after
  git pull).
Every script run ends with verification against :9845.
