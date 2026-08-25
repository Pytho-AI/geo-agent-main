Geo-Agent Release Notes

Version 2.0 — July 2026 — The Map API Unification

────────────────────────────────────────────────────────────────────────────────

ONE MAP SERVICE, EVERY DEPLOYMENT

Geo-Agent is now the standalone map subsystem for the whole ecosystem.
Edge stacks, cloud stacks, and event deployments all embed the same
analyst map and call the same API through one public surface (port
9845). A consumer integrates with exactly three things — two nginx
forwards, one backend URL knob, and an iframe with two postMessage
hooks. Everything map-shaped lives inside this service.

	•	Consumer contract — /geo-app/* (the analyst UI) and /geo-api/*
		(the API) forwarded to :9845; GEO_API_URL on the consumer
		backend; an iframe of /geo-app/operations-map with the
		geoagent.navigate and geoagent.editDone hooks. Consumers hold
		zero map UI and never touch tiles.
	•	External API — POST /render (product-map images through the
		exact pipeline the analyst edits with), GET /render/latest
		(current image of any map), PUT /maps/{id} + POST /maps/{id}/sync
		(feed data on), GET /map/state (read everything back),
		GET /basemaps. Everything else is the embedded UI's own API.

────────────────────────────────────────────────────────────────────────────────

THE TILE PLANE

Zero local tile archives, global coverage, air-gap-friendly caching.

	•	Server-rendered basemaps — Default (bland tactical), Terrain
		(obstacle-overlay hatching), Topo (military topographic sheet
		look), rendered by tileserver-gl from Protomaps planet vector
		data + Mapterhorn elevation, fronted by an internal disk cache
		with a 365-day TTL. Satellite imagery proxied and cached the
		same way.
	•	Self-resolving planet archive — upstream dated builds rotate
		off the CDN; the cache resolves the newest live build at
		request time and re-locks transparently when one is pruned.
		No pinned dates, no manual bumps.
	•	Client-side vector labels — place names stay upright under
		rotation, decluttered by prominence, with an analyst Detail
		slider from major cities down to every village.
	•	Global contour lines — computed client-side from the shared
		elevation source through a server-side DEM proxy; labeled index
		contours; the same linework serves the topographic basemap, the
		analyst toggle, and exported product maps.
	•	Weather overlay — six forecast layers with a 0–72 hour scrub,
		proxied server-side so the upstream key never reaches a browser.

────────────────────────────────────────────────────────────────────────────────

ANALYST MAP

	•	Four basemaps, Map Features toggles (MGRS grid, labels + detail,
		contours, spot heights), all persisted per map.
	•	Live order of battle with MIL-STD-2525D symbology, an echelon
		roll-up slider, a unit metadata panel (composition tree, linked
		equipment, activity), and doctrinal overlay painting that
		reprojects with the camera.
	•	Right-click per-target product generation with pushed-status
		badges on the units already handed off.
	•	In-map edit sessions: click-select and drag-move entities, edit
		chrome and Done button in-frame, 16:9 exporter framing, and a
		Done-render that replays the product's stored render spec with
		the analyst's session state.

────────────────────────────────────────────────────────────────────────────────

TERRAIN ANALYSIS & SYNTHESIS

	•	Automatic Modified Combined Obstacle Overlay synthesis from the
		obstacle space (corridor discovery, avenue-of-approach bundles,
		engagement areas, defensible terrain).
	•	Route planning over a dual road/terrain graph (on-road,
		off-road, mixed) with threat-aware costs, full terrain
		assessment, and drag-handle editing with live re-analysis.

────────────────────────────────────────────────────────────────────────────────

RENDERING & OPERATIONS

	•	One renderer: exported product maps drive a headless browser
		against this service's own frontend — what the analyst edits is
		what the product ships. GPU host rendering over CDP where
		available; fully in-container software rendering everywhere
		else.
	•	Stored render specs per map: generation presets replay on every
		edit-session Done without callers re-supplying them.
	•	Sanctioned operations scripts: rebuild.sh (targeted rebuilds
		with baked-in verification) and deploy.sh (full stack plus a
		deep verification battery over every consumer-facing surface).
	•	Full API reference generated into the repo (docs/API.md).

────────────────────────────────────────────────────────────────────────────────

Version 1.0 — February 2026

────────────────────────────────────────────────────────────────────────────────

INTRODUCING GEO-AGENT

We're excited to announce the release of Geo-Agent, an AI-powered geospatial intelligence platform that transforms how you interact with map data. Simply describe what you need in plain English, and Geo-Agent handles the rest.

────────────────────────────────────────────────────────────────────────────────

MAP CONTROLS

Interactive Map Interface

Navigate your operational environment with intuitive controls:

	•	Zoom & Pan — Explore any region with smooth, responsive navigation
	•	Reset View — Instantly return to your default area of interest
	•	Screenshot Capture — Export the current map view for briefings and reports


Military Symbol Placement

Create and position military units directly on the map:

	•	MIL-STD-2525D Compliant — Standard NATO military symbology
	•	All Affiliations — Friendly, hostile, neutral, and unknown forces
	•	Full Echelon Range — From team level to army group
	•	Unit Types — Infantry, armor, artillery, aviation, logistics, and more


Tactical Overlay Drawing

Draw operational graphics with precision:

	•	Phase Lines — Define movement and coordination measures
	•	Boundaries — Establish unit sectors and areas of responsibility
	•	Assembly Areas — Mark staging and consolidation zones
	•	Engagement Areas — Designate target reference points and kill zones
	•	Custom Naming — Label overlays for clear communication

────────────────────────────────────────────────────────────────────────────────

DATA SOURCES

Real-Time Terrain Intelligence

Access detailed terrain information on-demand:

	Elevation Data
	Source: AWS Terrain Tiles
	Coverage: Global, ~30 meter resolution
	Link: https://registry.opendata.aws/terrain-tiles/

	Land Cover Classification
	Source: ESA WorldCover
	Coverage: Global, 10 meter resolution
	Link: https://esa-worldcover.org/en

Terrain capabilities include:
	•	Elevation — Heights in meters above sea level
	•	Land Cover — Tree cover, shrubland, grassland, cropland, built-up areas, water, wetlands
	•	Tactical Properties — Concealment, cover, and trafficability ratings per terrain type


────────────────────────────────────────────────────────────────────────────────

AI-POWERED INTERACTION

Natural Language Commands

Describe what you need, and Geo-Agent executes:

	"Place a friendly mechanized infantry battalion at the crossroads north of the river"

	"Draw a phase line called PL ALPHA from the hilltop to the bridge"

	"Create an assembly area for 2nd Brigade in the forest east of the city"


Intelligent Queries

Ask questions about your operational environment:

	"What is the terrain like between my forward units and the objective?"

	"How far is it from the assembly area to the phase line?"


Contextual Awareness

The AI assistant understands:

	•	Current map view and visible entities
	•	Terrain elevation and land cover
	•	Spatial relationships between features
	•	Military terminology and doctrine

────────────────────────────────────────────────────────────────────────────────

ROUTE PLANNING & EDITING

Plan routes across any terrain, then reshape them by hand — analysis updates
automatically.

Route Planning

Select two points on the map and choose a routing mode:

	•	On Road — Follow existing roads and highways sourced from OpenStreetMap
	•	Off Road — Cross-country pathfinding through open terrain
	•	Mixed — Use roads when available, cut across terrain when needed

The planner runs A* search over a dual graph:

	Road graph — Built from OSM ways fetched via the Overpass API. Nodes are
	intersections and road endpoints; edges carry distance cost adjusted for
	threats and no-go zones.

	Tile graph — The area is divided into ~1 mi macro-tiles. Each tile is
	scored for trafficability, slope, concealment, and threat exposure using
	elevation data (AWS Terrain Tiles) and land cover (ESA WorldCover 10 m).

	In mixed mode the two graphs are bridged so the planner can transition
	between roads and open terrain seamlessly.

Data Sources

	Road Network
	Source: OpenStreetMap via Overpass API (4 server rotation, instant retry)
	Coverage: Global — motorway, trunk, primary, secondary, tertiary, residential
	Large bounding boxes are split into chunks and fetched in parallel.

	Elevation
	Source: AWS Terrain Tiles (~30 m resolution)
	Used for: slope analysis, elevation profiles, gain/loss calculation

	Land Cover
	Source: ESA WorldCover (10 m resolution)
	Used for: trafficability scoring, concealment percentages, terrain breakdown

	Threats & No-Go Zones
	Source: Map entities (hostile affiliations) and polygon overlays
	Effect: hostile entities create radial threat zones with linear cost falloff;
	no-go polygons block traversal entirely.

Route Analysis

Every planned or edited route produces a full terrain assessment:

	•	Distance — Total route length in miles
	•	Max Slope — Steepest grade along the route
	•	Elevation Gain / Loss — Cumulative climb and descent in feet
	•	Concealment — Average vegetation cover percentage
	•	Threat Exposure — Miles of route within hostile threat radii
	•	Terrain Breakdown — Percentage split by land cover type
	•	Elevation Profile — Visual chart of altitude along the route

Route Editing

Click any route on the map to enter edit mode:

	•	Control-point handles appear along the route, spaced at equal
	  geographic distance intervals
	•	Drag any handle to reshape the route — the section between
	  neighbouring handles deforms smoothly using linear delta interpolation
	  (no spiky single-vertex pulls)
	•	Click on the route to add new handles for finer control
	•	An amber preview line shows the edited shape on top of the original
	  green route
	•	Analysis updates live as you drag — terrain-dependent fields show
	  loading spinners while the backend re-analyzes via the off-road code
	  path; distance updates instantly on the client
	•	Save persists the new geometry and analysis to the database; the map
	  refreshes to show the updated route
	•	Cancel discards all edits — the original route is untouched
	•	Other routes on the map are never affected during editing

────────────────────────────────────────────────────────────────────────────────

WHAT'S NEXT

We're continuously improving Geo-Agent with planned enhancements:

	•	Offline map support
	
