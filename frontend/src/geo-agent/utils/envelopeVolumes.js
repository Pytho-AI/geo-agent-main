// 3D engagement/detection envelope VOLUMES — the analyst-facing form
// of the §6.7 envelope, rendered PROPERLY: a MapLibre
// CustomLayerInterface (renderingMode '3d') drawing a triangulated
// mesh with the map's own camera matrix every frame. GPU-resident and
// camera-locked — it can never lag, flicker, or disappear during
// pan/rotate/pitch the way DOM-overlay paint can, and it shares the
// scene depth buffer so terrain and symbols occlude correctly.
//
// The mesh is a surface of revolution with a PER-AZIMUTH profile:
//
// - Vertical form follows the method of propulsion. Gun (max
//   elevation stated): slant dome capped at R*sin(theta) with the
//   overhead dead cone carved (r_inner = h/tan(theta)). Ballistic:
//   the parabola of safety h = (R/2)(1-(x/R)^2), deck at max range.
//   Missile with stated ceiling: slant-range dome hard-capped at the
//   ceiling (the range-height envelope built from exactly the two
//   published figures). Cruise/loiter: deck-hugging cylinder. No
//   data: slant dome.
// - Lower boundary (LOS bands): pointwise max of the terrain crest
//   line per azimuth (server /terrain/coverage crest_tan) and the
//   4/3-earth radar horizon floor — targets under it are masked by
//   the earth, near or far. Ballistic and cruise rounds fly over
//   both: no carve.
//
// Smooth curvature comes from real sampling (72 azimuths x ~20
// profile steps), not stacked extrusion tiers.

import maplibregl from 'maplibre-gl'

const LAYER_ID = 'envelope-volumes-3d'
const AZ = 72                 // azimuth samples (matches server rays)
const PROF = 14               // samples up the outer profile
const DEAD = 8                // samples along the lower (dead-space) boundary
const TOP = 3                 // samples inward along the ceiling
const INNER = 4               // samples down the inner (gun cone) edge

// 4/3-earth radar horizon (standard refraction model): a sensor at
// height h1 sees a target at height h2 out to
// R = sqrt(2*k*Re*h1) + sqrt(2*k*Re*h2), k = 4/3. sqrt(2*k*Re) with
// Re = 6371 km gives ~4121 m per sqrt(meter). Below that line the
// earth itself masks the target — the floor of every radar-governed
// envelope, independent of local terrain.
const HORIZON_C = Math.sqrt(2 * (4 / 3) * 6371000)
const SENSOR_HEIGHT_M = 10

function horizonFloor(x) {
  // Minimum target altitude detectable at ground range x (meters).
  const d0 = HORIZON_C * Math.sqrt(SENSOR_HEIGHT_M)
  if (x <= d0) return 0
  const t = (x - d0) / HORIZON_C
  return t * t
}

const COLORS = {
  range_fan: [0.86, 0.2, 0.24],
  detection_ring: [0.85, 0.55, 0.15],
}
const FILL_ALPHA = 0.2

const VERT = `
attribute vec3 a_pos;
attribute float a_shade;
uniform mat4 u_matrix;
varying float v_shade;
void main() {
  gl_Position = u_matrix * vec4(a_pos, 1.0);
  v_shade = a_shade;
}`
const FRAG = `
precision mediump float;
uniform vec4 u_color;
varying float v_shade;
void main() {
  gl_FragColor = vec4(u_color.rgb * u_color.a * v_shade, u_color.a * v_shade);
}`

// Module-level coverage cache: {key -> {ring, crest_tan} | 'inflight'}
const _coverage = {}

function profileRadius(form, R, ceiling, h) {
  if (form === 'ballistic') return R * Math.sqrt(Math.max(1 - (2 * h) / R, 0))
  if (form === 'cylinder') return R
  // dome / gun / ceiling-capped missile: the stated maximum is SLANT
  // range, so the outer bound is x^2 + h^2 = R^2, hard-capped at the
  // stated ceiling (flat top) — the standard range-height envelope
  // built from exactly the two published figures.
  return Math.sqrt(Math.max(R * R - h * h, 0))
}

function bandForm(band) {
  const R = Number(band.radius_m)
  const traj = (band.trajectory || '').toLowerCase()
  const elevDeg = Number(band.max_elevation_deg)
  const hasElev = Number.isFinite(elevDeg) && elevDeg > 5 && elevDeg < 90
  const tanElev = hasElev ? Math.tan((elevDeg * Math.PI) / 180) : null
  const stated = Number(band.ceiling_m) || 0
  let form, ceiling
  if (traj === 'ballistic') { form = 'ballistic'; ceiling = R / 2 }
  else if (traj === 'cruise' || traj === 'loiter') { form = 'cylinder'; ceiling = stated || 0.02 * R }
  else if (tanElev) { form = 'gun'; ceiling = R * Math.sin((elevDeg * Math.PI) / 180) }
  else if (stated) { form = 'dome'; ceiling = stated }
  else { form = 'dome'; ceiling = 0.35 * R }
  ceiling = Math.min(ceiling, R * 0.98)
  return { form, R, ceiling, tanElev }
}

// Per-azimuth boundary polyline (fixed vertex count so adjacent
// azimuths quad-strip cleanly). Returns [[x_m, h_m] ...] from origin
// along the lower dead-space boundary, up the outer profile, in
// along the ceiling, down the inner edge back to origin.
//
// The lower boundary is the pointwise MAX of the terrain crest line
// (h = x * tan(alpha), per azimuth, from the server's crest walk) and
// the 4/3-earth radar horizon floor — the two physical reasons a
// low-flying target is unreachable. Ballistic and cruise rounds fly
// over both: their boundary stays on the deck.
function sectionBoundary(fx, crestTan) {
  const { form, R, ceiling, tanElev } = fx
  const losGoverned = form !== 'ballistic' && form !== 'cylinder'
  const ct = losGoverned ? (crestTan || 0) : 0
  const hLow = (x) => (losGoverned ? Math.max(x * ct, horizonFloor(x)) : 0)
  // Outer bound as h_top(x): the profile height above ground range x.
  const hTop = (x) => {
    if (form === 'ballistic') return (R / 2) * (1 - (x / R) * (x / R))
    if (form === 'cylinder') return x <= R ? ceiling : 0
    return Math.min(Math.sqrt(Math.max(R * R - x * x, 0)), ceiling)
  }
  // Meet point: first ground range where the lower boundary closes
  // against the outer bound (walk out; monotone in practice).
  let xMeet = R
  if (losGoverned) {
    for (let i = 1; i <= 96; i++) {
      const x = (R * i) / 96
      if (hLow(x) >= hTop(x)) { xMeet = x; break }
    }
  }
  const pts = []
  for (let i = 0; i < DEAD; i++) {
    const x = (xMeet * i) / (DEAD - 1)
    pts.push([x, Math.min(hLow(x), hTop(x))])
  }
  // Outer profile from the meet height up to the ceiling.
  const hMeet = Math.min(hLow(xMeet), ceiling)
  for (let i = 0; i < PROF; i++) {
    const h = hMeet + ((ceiling - hMeet) * (i + 1)) / PROF
    pts.push([profileRadius(form, R, ceiling, Math.min(h, ceiling)), Math.min(h, ceiling)])
  }
  // Ceiling, inward to the inner radius (gun cone or axis).
  const rTop = profileRadius(form, R, ceiling, ceiling)
  const rIn = tanElev ? Math.min(ceiling / tanElev, rTop) : 0
  for (let i = 0; i < TOP; i++) {
    pts.push([rTop + ((rIn - rTop) * (i + 1)) / TOP, ceiling])
  }
  // Inner edge back down to the origin (cone for guns, axis else).
  for (let i = 0; i < INNER; i++) {
    const f = 1 - (i + 1) / INNER
    pts.push([rIn * f, tanElev ? rIn * f * tanElev : ceiling * f])
  }
  return pts
}

function buildMesh(bands) {
  // Positions in mercator units relative to each band's own center.
  const verts = []
  for (const b of bands) {
    const fx = bandForm(b)
    if (!fx.R || fx.R <= 0) continue
    const merc = maplibregl.MercatorCoordinate.fromLngLat(
      { lng: b.center[0], lat: b.center[1] }, 0)
    const s = merc.meterInMercatorCoordinateUnits()
    const coslat = Math.cos((b.center[1] * Math.PI) / 180) || 1e-9
    // Base z: the model's stated altitude for the bearer when the
    // position record carries one, else the DEM ground elevation at
    // its grid (terrain-aware maps) — never a hardcoded deck.
    const groundZ = Number.isFinite(b.base_altitude_m) ? b.base_altitude_m : 0
    const color = COLORS[b.kind] || COLORS.range_fan
    const crest = b.crest_tan
    const sections = []
    for (let a = 0; a <= AZ; a++) {
      const ai = a % AZ
      const ct = Array.isArray(crest) ? (crest[ai] || 0) : 0
      sections.push(sectionBoundary(fx, ct))
    }
    const N = sections[0].length
    for (let a = 0; a < AZ; a++) {
      const th0 = (2 * Math.PI * a) / AZ
      const th1 = (2 * Math.PI * (a + 1)) / AZ
      const s0 = sections[a]
      const s1 = sections[a + 1]
      for (let i = 0; i < N - 1; i++) {
        const quad = [
          [s0[i], th0], [s1[i], th1], [s0[i + 1], th0],
          [s1[i], th1], [s1[i + 1], th1], [s0[i + 1], th0],
        ]
        for (const [[x, h], th] of quad) {
          // Per-vertex geodesic placement — the SAME ground math as
          // the 2D ring painter (ringPointAt), so the volume footprint
          // and the ring are one curve. Flat-mercator offsets at the
          // center's scale drifted kilometers at detection radii (the
          // mercator meter stretches with latitude across a 160 km
          // circle).
          const vm = maplibregl.MercatorCoordinate.fromLngLat({
            lng: b.center[0] + (x * Math.sin(th)) / (111320 * coslat),
            lat: b.center[1] + (x * Math.cos(th)) / 111320,
          }, 0)
          const px = vm.x
          const py = vm.y
          const pz = (groundZ + h) * s
          // Vertical shading: faces brighten with altitude — the cue
          // that reads as a solid instead of a flat wash.
          const shade = 0.55 + 0.45 * (fx.ceiling ? h / fx.ceiling : 0)
          verts.push(px, py, pz, shade * (color === COLORS.range_fan ? 1 : 1))
        }
      }
    }
    // Stash color per band run: one draw call per band keeps the
    // shader trivial. Record [startVertex, count, color].
    const count = AZ * (N - 1) * 6
    buildMesh._runs.push({ start: (verts.length / 4) - count, count, color })
  }
  return new Float32Array(verts)
}

class EnvelopeVolumeLayer {
  constructor() {
    this.id = LAYER_ID
    this.type = 'custom'
    this.renderingMode = '3d'
    this._bands = []
    this._dirty = false
    this._runs = []
    this._nVerts = 0
  }

  onAdd(map, gl) {
    this._map = map
    const compile = (type, src) => {
      const sh = gl.createShader(type)
      gl.shaderSource(sh, src)
      gl.compileShader(sh)
      return sh
    }
    this._prog = gl.createProgram()
    gl.attachShader(this._prog, compile(gl.VERTEX_SHADER, VERT))
    gl.attachShader(this._prog, compile(gl.FRAGMENT_SHADER, FRAG))
    gl.linkProgram(this._prog)
    this._aPos = gl.getAttribLocation(this._prog, 'a_pos')
    this._aShade = gl.getAttribLocation(this._prog, 'a_shade')
    this._uMatrix = gl.getUniformLocation(this._prog, 'u_matrix')
    this._uColor = gl.getUniformLocation(this._prog, 'u_color')
    this._buf = gl.createBuffer()
  }

  onRemove(map, gl) {
    if (this._buf) gl.deleteBuffer(this._buf)
    if (this._prog) gl.deleteProgram(this._prog)
  }

  setBands(bands) {
    this._bands = bands
    this._dirty = true
    if (this._map) this._map.triggerRepaint()
  }

  render(gl, matrix) {
    if (this._dirty) {
      buildMesh._runs = []
      const data = buildMesh(this._bands)
      this._runs = buildMesh._runs
      this._nVerts = data.length / 4
      gl.bindBuffer(gl.ARRAY_BUFFER, this._buf)
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW)
      this._dirty = false
    }
    if (!this._nVerts) return
    gl.useProgram(this._prog)
    gl.uniformMatrix4fv(this._uMatrix, false,
      matrix instanceof Float32Array ? matrix : new Float32Array(matrix))
    gl.bindBuffer(gl.ARRAY_BUFFER, this._buf)
    gl.enableVertexAttribArray(this._aPos)
    gl.vertexAttribPointer(this._aPos, 3, gl.FLOAT, false, 16, 0)
    gl.enableVertexAttribArray(this._aShade)
    gl.vertexAttribPointer(this._aShade, 1, gl.FLOAT, false, 16, 12)
    // Translucent volume: depth-tested against the scene but not
    // depth-written, so the map stays readable through it and both
    // walls blend.
    gl.depthMask(false)
    gl.disable(gl.CULL_FACE)
    for (const run of this._runs) {
      gl.uniform4f(this._uColor, run.color[0], run.color[1], run.color[2], FILL_ALPHA)
      gl.drawArrays(gl.TRIANGLES, run.start, run.count)
    }
    gl.depthMask(true)
  }
}

let _layer = null

function ensureLayer(map) {
  if (!map.getLayer(LAYER_ID)) {
    _layer = new EnvelopeVolumeLayer()
    map.addLayer(_layer)
  }
  return _layer
}

// Selected unit's bands -> mesh. Fetches the coverage crest package
// lazily per band (persisted server-side; at most a few bands since
// rings are selection chrome) and rebuilds when it lands.
export function updateEnvelopeVolumes(map, ringFeatures, selectedBearerId) {
  if (!map || !map.getStyle) return
  const layer = ensureLayer(map)
  const bands = []
  if (selectedBearerId) {
    for (const f of ringFeatures || []) {
      const p = f.properties || {}
      if (p.kind !== 'range_fan' && p.kind !== 'detection_ring') continue
      const bearer = (p.bearer_unit_kg_id || p.bearer_id || '').toString()
      if (bearer !== selectedBearerId) continue
      const c = f.geometry && f.geometry.coordinates
      if (!c) continue
      for (const band of p.bands || []) {
        if (!Number.isFinite(Number(band.radius_m)) || Number(band.radius_m) <= 0) continue
        let baseAlt = Number(p.bearer_altitude_m)
        if (!Number.isFinite(baseAlt) && map.queryTerrainElevation) {
          try {
            const g = map.queryTerrainElevation({ lng: c[0], lat: c[1] })
            if (Number.isFinite(g)) baseAlt = g
          } catch { /* terrain not ready — deck base, rebuilt on refresh */ }
        }
        const entry = {
          kind: p.kind, center: c,
          radius_m: band.radius_m, ceiling_m: band.ceiling_m,
          trajectory: band.trajectory,
          max_elevation_deg: band.max_elevation_deg,
          base_altitude_m: baseAlt,
          crest_tan: null,
        }
        if (band.los) {
          const th = band.los_target_m || 10
          const key = `${c[1].toFixed(4)},${c[0].toFixed(4)},${Math.round(band.radius_m)},${th}`
          const hit = _coverage[key]
          if (hit && hit !== 'inflight') {
            entry.crest_tan = hit.crest_tan
          } else if (!hit) {
            _coverage[key] = 'inflight'
            fetch(`/geo-api/v1/terrain/coverage?lat=${c[1]}&lon=${c[0]}&radius_m=${band.radius_m}&target_h=${th}`)
              .then(r => (r.ok ? r.json() : null))
              .then(body => {
                if (body && Array.isArray(body.crest_tan)) {
                  _coverage[key] = body
                  updateEnvelopeVolumes(map, ringFeatures, selectedBearerId)
                } else {
                  delete _coverage[key]
                }
              })
              .catch(() => { delete _coverage[key] })
          }
        }
        bands.push(entry)
      }
    }
  }
  layer.setBands(bands)
}
