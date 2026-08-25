# Geo-Agent Roadmap

Feature direction for the standalone map service. Rewritten July 2026
after the map API unification: a large share of the original roadmap
shipped on the `ibl` line, so this document now separates what EXISTS
from what remains open, and states each open item against the current
architecture (see README.md for that architecture; this document never
restates it).

---

## Shipped (on the unification line)

**Terrain & environment analysis**
- Mobility-corridor discovery: go/no-go trafficability grid from DEM
  slope + land cover, morphological cleanup, connected-component
  corridor extraction, corridor-width echelon classification with
  force-type modulation (`routes/discover-corridors`).
- Automatic Modified Combined Obstacle Overlay synthesis: generalized
  Voronoi diagram over the obstacle space, Kirchhoff-current corridor
  ranking, avenue-of-approach bundles with per-echelon tails,
  engagement-area and defensible-terrain derivation
  (`routes/synthesize-mcoo`).
- Route planning and hand-editing: A* over a dual road/tile graph
  (on-road, off-road, mixed), threat-aware costs, full terrain
  assessment per route, drag-handle editing with live re-analysis
  (`routes/plan`, `routes/analyze-edit`).
- Weather integration: forecast raster overlay (temperature, rain,
  snow, wind, clouds, pressure) with a 0–72 h scrub, server-side key
  custody, and weather-aware route scoring.
- Terrain readout on every basemap: global DEM contour lines with
  labeled index contours (client-side from the shared elevation
  source), spot heights, hillshade baked into the rendered rasters,
  topographic-sheet basemap flavor.

**Intelligence & fires overlays**
- The doctrinal overlay kind set is live end-to-end (drawn, synced,
  painted, rendered into products): named/target areas of interest,
  engagement areas, phase lines, boundaries, areas of operations,
  areas of interest, battle positions, assembly areas, fire-support
  coordination measures, restricted operations zones, obstacle points
  and belts, key terrain, choke points, strong points, decision
  points, air corridors, range fans, threat objectives,
  restricted/severely-restricted terrain, urban areas. The kind
  vocabulary has ONE authority (`ENTITY_TYPE_SEED` +
  the overlay catalog — see CLAUDE.md); the analyst overlay selector
  autopopulates a chip per kind present.
- Server-side shape primitives on the graph tool surface: closed
  control measures are generated from their defining parameters
  (circle center+radius, rectangle opposite corners, ellipse
  center+semi-axes+orientation), never hand-plotted vertex lists.
- Per-equipment range fans derived from unit composition against the
  doctrinal engagement-range table.
- Live order-of-battle feed with echelon roll-up, unit metadata
  (composition tree, linked equipment, activity), per-target product
  generation from the map (right-click), and pushed-status badges.

**Product pipeline integration**
- Server-side product-map rendering through the same MapLibre +
  tactical-paint pipeline the analyst edits with (one renderer, no
  drift), replay from stored per-map render specs, persisted current
  images, in-map edit sessions with a Done-render flow.

**Natural-language interface**
- The NL agent is wired (`nl/query`, `nl/update`, `nl/chat`) with
  spatial tools over live map state. Query breadth below remains open.

---

## Open

**Course-of-action planning & wargaming**
- Multiple named COAs with side-by-side synchronized comparison and
  branch plans. Per-COA overlay LAYERS exist today (the sidebar's
  Threat COA sets); COA authoring and comparison views do not.
- Time-phased force deployment: `valid_from`/`valid_to`/`phase` on
  entities, a timeline scrubber animating movement through phases, and
  a synchronization-matrix view linking phases to maneuver, fires,
  ISR, and aviation.
- What-if red-team mode: drag enemy units to test responses, generate
  likely enemy courses of action from terrain plus doctrine.

**Terrain analysis extensions**
- Line-of-sight between two clicked points, viewshed from an
  observation post, dead-ground visualization. The elevation service
  and the DEM tile plane both exist; this is analysis plus one
  overlay treatment per output.
- Illumination planning: BMNT/EENT and moon-phase overlays for night
  operations.

**Intelligence fusion**
- Collection management on the map: named areas of interest linked to
  collection requirements, last-observed staleness highlighting, a
  PIR/IR tracker anchored to locations.
- Pattern-of-life ingest: historical sighting import, activity
  heatmaps, movement-anomaly flags.
- Sensor coverage modeling: sensor fans with range rings exist as
  overlay kinds; coverage-gap computation and ISR tasking queries do
  not.

**Logistics & sustainment**
- Main/alternate supply route computation over the existing route
  planner, with chokepoint and bridge-classification annotations.
- Sustainment overlay set (support areas, supply points, forward
  arming and refueling points) with support-relationship tethers and
  days-of-supply visualization.

**Natural-language depth**
- Spatial-intelligence query breadth ("which units have line of sight
  to the objective", "what changed since 0600") and planning
  assistance ("recommend an assembly area for two battalions with
  good concealment") on top of the wired agent.

**Collaboration**
- Multi-user presence (cursors, per-feature edit locks), overlay
  version history beyond snapshots, comments anchored to features,
  and a briefing mode that steps through planning phases.

**Interoperability**
- MIL-STD-2525D overlay import/export as an exchange format, blue
  force tracker position feed ingestion.

---

## Sequencing guidance

Nearest-value items given what now exists: line-of-sight/viewshed
(pure analysis over the in-place elevation service), supply-route
computation (a scoring mode over the in-place route planner), and
COA authoring (the per-COA layer plumbing already carries product
overlays). The timeline/phase model is the largest schema change and
unlocks both wargaming and the synchronization matrix, so it should be
designed once, deliberately, rather than bolted onto any single
feature.
