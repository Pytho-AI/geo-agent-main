"""VLM document-reading stages of the ingest pipeline.

Two stages read the document with the vision model, in order:

  1. define_ao(pages)   — establish the AREA OF OPERATIONS first: the
     theater, countries, and key named locations that bound where the
     force operates. Those anchors are geocoded and become the bbox that
     scopes every later placement.
  2. extract_oob(pages) — extract the order of battle (units, fixed
     infrastructure, equipment holdings, typed relationships) as strict
     JSON. It NEVER invents coordinates; it emits a place name or grid
     and the geospatial stage (resolve.py) resolves it inside the AO.

A born-digital document reaches the model primarily as its LOSSLESS
TEXT — exact unit names, MGRS grids, and numbers that the vision encoder
blurs when it downscales a page to its ~280-token budget — with the page
images riding along for visual context in the SAME single call when they
fit under the request-body cap. Reading from the whole scenario's text in
one call is also what makes cross-document dedup and self-review work
(batched images cannot dedup across batches). A SCANNED document with no
text layer is read from page IMAGES alone — it is a vision model, so it
still SEES org charts, table layout, and unit symbols. PDFs
render/extract directly (PyMuPDF); DOCX/XLSX/PPTX/CSV convert to PDF via
the editor subprocess (in-container).

IMAGE ENCODING IS TUNED TO HOW GEMMA-4 IS ACTUALLY SERVED (verified,
not assumed):
  - Gemma-4 vision uses a variable-resolution token BUDGET
    (max_soft_tokens ∈ {70,140,280,560,1120}, default 280) — NOT
    Gemma-3's 896 pan-and-scan.
  - On Bedrock/mantle (cloud) the budget is FIXED at ~280 and the knob
    is inert (measured: prompt_tokens flat at 283 across max_soft_tokens
    70→1120 AND across 1148px→2400px renders; the AWS model card
    documents no control). So rendering above the ~280-token effective
    resolution buys nothing there, and Bedrock caps the request body at
    3.5 MB including images.
  - On vLLM (edge) the budget IS honored per request (config
    LLM_IMAGE_SOFT_TOKENS → mm_processor_kwargs), so higher-res renders
    can pay off there.
Pages therefore render as JPEG (far smaller than PNG — a 1148px page is
~160 KB, so batches stay well under 3.5 MB), mildly sharpened so small
table text survives the encoder's internal downscale, at a legible-but-
modest longest side. The AO map render (resolve.py) is a single modest
JPEG. Batches are capped by cumulative BYTES, not page count.
"""
import base64
import io
import json
import logging
from typing import Iterator, List, Optional

from app.services.llm import Message, get_llm_client
from app.models.graph import EXTRACTABLE_ENTITY_TYPES
from app.services.graph_ingest.schema import (
    AreaOfOperations, ExtractedOOB, ExtractedEntity, ExtractedEdge,
    ExtractedHolding, ExtractedPosition,
)

log = logging.getLogger(__name__)

# The model's real output ceiling (probed: 131072 accepted, 262144
# rejected on mantle). NEVER cap the answer below this — reasoning writes
# thousands of tokens before the JSON, so any arbitrary cap just
# truncates the answer. It is a safety limit, not a target: the model
# stops when the JSON is done, so a high value costs nothing.
_MAX_OUTPUT_TOKENS = 131072

# Longest page side in px — legible for prose/tables (verified by eye at
# 896–1148). Gemma-4 downsamples to ~280 tokens/image on Bedrock anyway,
# so compress HARD: the point is to fit a whole scenario's pages into ONE
# call so the model consolidates the order of battle in a single pass
# (splitting into batches re-introduces cross-batch duplicate units).
_PAGE_MAX_PX = 1000
_JPEG_QUALITY = 72
# Cumulative base64 budget per call. Bedrock caps the request body
# (images included) at 3.5 MB; ~3.2 MB leaves headroom for the prompt. At
# ~60-80 KB/page compressed that is ~40 pages in ONE call — enough for a
# multi-document scenario. Only a genuinely huge scenario spills to a
# second call (then the name-identity merge cleans any overlap).
_BATCH_MAX_B64_BYTES = 3_200_000
# High page ceiling so the BYTE budget governs, not an arbitrary count.
_MAX_PAGES_PER_CALL = 60
# Text char ceiling for a single consolidated extraction call. Kept below
# what the served model accepts in one request: ~400k chars of OOB text
# (many detailed equipment spreadsheets at once) drew a 400 from the
# mantle /responses endpoint, so cap lower. ~250k chars ≈ 60k tokens
# still holds a whole multi-document scenario's PROSE (the 3-doc 2CR set
# is ~65k chars); it truncates only a pathological all-spreadsheets dump,
# whose equipment rows are holdings, not OOB structure, anyway.
_TEXT_CHAR_LIMIT = 250_000


# ── document → page images ──────────────────────────────────────────

def _page_to_jpeg(page) -> bytes:
    """One PyMuPDF page → a JPEG, longest side _PAGE_MAX_PX, mildly
    sharpened (unsharp mask helps small table text survive the vision
    encoder's internal downscale to its token budget)."""
    import fitz  # PyMuPDF
    from PIL import Image, ImageFilter
    rect = page.rect
    longest = max(rect.width, rect.height) or 1.0
    zoom = min(3.0, _PAGE_MAX_PX / longest)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=140, threshold=2))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_JPEG_QUALITY)
    return buf.getvalue()


def _render_pdf_pages(pdf_bytes: bytes) -> List[bytes]:
    """PDF → JPEG page images."""
    import fitz  # PyMuPDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = [_page_to_jpeg(page) for page in doc]
    doc.close()
    return out


def _batch_pages(pages: List[bytes]) -> Iterator[List[bytes]]:
    """Group page images into VLM calls capped by cumulative base64 size
    (the Bedrock 3.5 MB body limit) and a page ceiling."""
    batch: List[bytes] = []
    acc = 0
    for p in pages:
        b64 = (len(p) * 4) // 3
        if batch and (acc + b64 > _BATCH_MAX_B64_BYTES or len(batch) >= _MAX_PAGES_PER_CALL):
            yield batch
            batch, acc = [], 0
        batch.append(p)
        acc += b64
    if batch:
        yield batch


async def _office_to_pdf(data: bytes, filename: str) -> bytes:
    """DOCX/XLSX/PPTX → PDF via the editor's convert-to API (cloud
    + edge both run it). The VLM then reads the rendered PAGES — never a
    text flattening."""
    import httpx
    from app.config import get_settings
    st = get_settings()
    base = (st.editor_url or "").rstrip("/")
    if not base:
        raise RuntimeError(
            "office-doc import needs EDITOR_URL set (the editor runs on "
            "cloud and edge) — PDF and plain text work without it")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{base}/cool/convert-to/pdf",
            files={"data": (filename, data, "application/octet-stream")})
        resp.raise_for_status()
        return resp.content


async def render_document_to_images(data: bytes, filename: str) -> List[bytes]:
    """Any supported document → a list of PNG page images (Gemma-sized).
    Plain text returns []. The caller feeds the pages to the VLM stages.
    """
    lower = (filename or "").lower()
    if lower.endswith(".pdf"):
        return _render_pdf_pages(data)
    if lower.endswith((".docx", ".doc", ".xlsx", ".xlsm", ".xls",
                       ".pptx", ".ppt", ".csv", ".odt", ".ods")):
        return _render_pdf_pages(await _office_to_pdf(data, filename))
    return []


async def read_document(data: bytes, filename: str):
    """Convert a document ONCE and return (text, page_images).

    For born-digital documents (Word / PDF with a real text layer) the
    extracted text is LOSSLESS: it carries every MGRS grid, exact place
    name, and unit designation that the vision encoder blurs when it
    downscales a page to its ~280-token budget. The extraction stages
    therefore PREFER the text and read a single consolidated call from it
    (so cross-document dedup and self-review actually work — batched
    images cannot dedup across batches). The page images ride along for
    visual context (org charts, overlays) and are the SOLE signal for a
    scanned document with no text layer. Plain text returns (text, [])."""
    import fitz  # PyMuPDF
    lower = (filename or "").lower()
    if lower.endswith(".pdf"):
        pdf_bytes = data
    elif lower.endswith((".docx", ".doc", ".xlsx", ".xlsm", ".xls",
                         ".pptx", ".ppt", ".csv", ".odt", ".ods")):
        pdf_bytes = await _office_to_pdf(data, filename)
    else:
        return data.decode("utf-8", "ignore"), []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    texts, images = [], []
    for page in doc:
        texts.append(page.get_text())
        images.append(_page_to_jpeg(page))
    doc.close()
    return "\n\n".join(texts), images


def _image_block(jpg: bytes) -> dict:
    return {"type": "image", "source": {
        "type": "base64", "media_type": "image/jpeg",
        "data": base64.b64encode(jpg).decode()}}


def _parse(content: str):
    """Pull the JSON object out of the model reply (tolerant of a stray
    code fence or trailing prose)."""
    s = (content or "").strip()
    if "```" in s:
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b < 0:
        return None
    try:
        return json.loads(s[a:b + 1])
    except ValueError:
        return None


async def _vlm_json(system: str, instruction: str, blocks: List[dict],
                    *, max_tokens: int = 4096,
                    reasoning_effort: str = "high") -> Optional[dict]:
    """One VLM call over a set of content blocks → parsed JSON or None.

    Reasoning is ON by default and high: reading an order of battle out
    of a document and consolidating a unit named several ways is a hard
    task, and this is one-time scenario setup — a few seconds of thinking
    beats hours of hand-fixing. The thinking is logged (app.llm.trace)."""
    client = get_llm_client()
    msg = Message(role="user", content=[{"type": "text", "text": instruction}] + blocks)
    resp = await client.chat([msg], system=system, max_tokens=max_tokens,
                             temperature=0.0, reasoning_effort=reasoning_effort)
    return _parse(resp.content)


# ── Stage 1: define the AO ──────────────────────────────────────────

_AO_SYSTEM = (
    "You are the geospatial framing stage of a military training-simulation "
    "ingest (synthetic exercise content). Before any unit is read, you fix "
    "WHERE the operation happens so later steps can resolve place names to "
    "coordinates. You report only what the pages state; you never invent "
    "geography."
)

_AO_INSTRUCTION = """From these planning-document pages, establish the AREA OF OPERATIONS. Output ONE JSON object:
{"theater":"<short region description, e.g. 'eastern Poland — Suwalki gap' or null>",
 "countries":["<country names the operation physically occurs in>"],
 "key_locations":["<real named places that anchor the geography: cities, towns, training areas, rivers, key terrain — REAL places only, NOT objective/phase-line codewords>"],
 "bbox_hint":[west,south,east,north] or null,
 "note":"<what fixed the area / any uncertainty>"}
RULES: countries and key_locations must be REAL places findable on a map (Grafenwoehr, Suwalki, the Vistula) — never exercise codewords (OBJ JACKSON, PL BLUE, NAI 7). If the document gives an explicit bounding box or grid zone, put it in bbox_hint. Output ONLY the JSON object."""


async def define_ao(pages: List[bytes], *, plain_text: Optional[str] = None,
                    source_label: str = "") -> AreaOfOperations:
    """Stage 1 — read the document, name the theater/countries/anchors,
    geocode them, and return the AO bbox that scopes all placement.
    The heavy lifting (geocoding the anchors → bbox) is in resolve.py so
    the geospatial logic stays in one place; this stage is the read.

    Prefers the lossless document TEXT when available (the situation /
    area-of-operations paragraph names the theater and real places
    exactly); falls back to the first page images for a scanned doc."""
    from app.services.graph_ingest.resolve import build_ao_from_anchors

    raw = None
    if plain_text and plain_text.strip():
        blocks = [{"type": "text", "text": "DOCUMENT TEXT:\n" + plain_text[:_TEXT_CHAR_LIMIT]}]
        raw = await _vlm_json(_AO_SYSTEM, _AO_INSTRUCTION, blocks, max_tokens=_MAX_OUTPUT_TOKENS)
    elif pages:
        # Scanned doc, no text layer: the theater is usually named on the
        # first pages (situation / area-of-operations paragraph); the
        # first size-capped batch is enough and keeps this stage cheap.
        first = next(_batch_pages(pages), [])
        blocks = [_image_block(p) for p in first]
        raw = await _vlm_json(_AO_SYSTEM, _AO_INSTRUCTION, blocks, max_tokens=_MAX_OUTPUT_TOKENS)
    raw = raw or {}
    return await build_ao_from_anchors(
        theater=raw.get("theater"),
        countries=[c for c in (raw.get("countries") or []) if c],
        key_locations=[k for k in (raw.get("key_locations") or []) if k],
        bbox_hint=raw.get("bbox_hint"),
        note=raw.get("note"),
        source_label=source_label,
    )


# ── Stage 2: extract the OOB ────────────────────────────────────────

_OOB_SYSTEM = (
    "You are the order-of-battle extraction stage of a military "
    "training-simulation ingest (synthetic exercise content — fictional "
    "OPFOR, no real-world effect). You read exercise planning documents "
    "(OPORDs, OOB annexes, road-to-war narratives, org charts) and output "
    "the force structure as strict JSON. You emit only what the pages state "
    "and null what they omit; you never invent units, counts, or positions."
)

_OOB_INSTRUCTION = """Extract the order of battle from these pages into ONE JSON object:
{"entities":[{"ref":"<stable local id>","name":"...","entity_type":"__ENTITY_TYPE_ENUM__","affiliation":"Friend|Hostile|Neutral|Unknown","echelon":"Team|Squad|Section|Platoon|Company|Troop|Battery|Squadron|Battalion|Regiment|Brigade|Division|Corps|Army|null","unit_type":"<free text or null>","category":"<snake_case or null>","parent_ref":"<ref of the parent UNIT or null>","mgrs":"<grid or null>","location_text":"<real place name or null>","line":["<MGRS vertex>","..."],"area":["<MGRS vertex>","..."],"positions":[{"dtg":"<date/time-group as written, e.g. '06 APR 26'>","mgrs":"<grid>","location_text":"<named place>","activity":"<what it is doing then>"}],"posture":"<or null>","template_key":"<best-matching force-template key from the catalog below, or null>","personnel_authorized":null,"personnel_current":null,"holdings":[{"nomenclature":"<equipment verbatim>","count_authorized":null,"count_current":null}]}],
 "edges":[{"from_ref":"...","to_ref":"...","relationship_type":"attached|opcon|tacon|direct_support|general_support|general_support_reinforcing|reinforcing|supplies","note":null}],
 "coverage_note":"<what these pages did and did not specify>"}

WHAT IS AN ENTITY — emit ONLY:
  - military UNITS (from team up to army) — the fighting/support organizations themselves, EACH as its own entity (never combine two units into one — "82nd and 87th Brigades" is TWO entities);
  - FIXED INFRASTRUCTURE that occupies ground: a garrison / base / training area / barracks is "garrison"; then fuel/POL depots, ammunition points, airfields (aviation only), rail hubs, pipelines, pump stations, C2 bunkers, bridges — but ONLY a SPECIFIC identified site, named with its PLACE: "Grajewo Fuel Depot" not "Fuel Depot", "Orzysz Communications Node" not "Comms Node", "Svencioneliai Railway" not "Rail Junctions". A bare generic noun ("Bridge", "Fuel Depot", "Pump Stations", "Rail Junctions") is NEVER a valid entity name. Do NOT manufacture an infrastructure entity from a generic or plural mention ("maps of rail junctions and fuel depots", "sever a bridge"); emit infrastructure only where the document points to a PARTICULAR site by proper name or by grid;
  - equipment holdings go INSIDE a unit's "holdings", never as their own entity.
DO NOT emit as entities (this is noise — leave it out entirely):
  - commander billets or positions ("2CR CDR", "V Corps CDR", "DIVARTY CDR");
  - named individuals or ranks ("LTG Richardson");
  - staff sections or cells ("V Corps Staff", "G-3", "the TAC"), AND the internal staff / service / support sections that a detailed headquarters listing breaks a command into — an Administrative / Personnel / Intelligence / Operations / Logistics / Signal / Medical / Maintenance / Mess / POL / Supply / Security Section, a headquarters company (HHC), a staff platoon. These are the INSIDE of a headquarters, not maneuver or fighting units; emit the HEADQUARTERS or the command itself, never its internal sections. If a spreadsheet enumerates a unit's own sub-sections, keep the unit, drop the sections;
  - events, actions, phases, or courses of action ("Massed Assault on OBJ JACKSON", "Phase II");
  - a UNIT'S POSITION as if it were its own place — an assembly area, tactical assembly area (TAA), attack position (ATK PSN), jump-off position, staging area, forward line, or final attack / assault position, or a unit's command post (CP). These state WHERE A UNIT IS: put that grid / place in the UNIT'S OWN "mgrs" / "location_text", NEVER as a separate entity. "72nd Motorized Rifle Division final attack positions (34UEB...)" means the 72nd Motorized Rifle Division sits at 34UEB... — one unit entity with that grid, not a unit plus a "Final Attack Positions" entity;
  - fires / EW EFFECT areas ("jamming impact zone", "kill box"), and any location named ONLY because an event happened there (an assassination target, a civilian ministry building) — unless it is genuine PERSISTENT military infrastructure in its own right (fuel depot, ammunition point, rail hub, garrison, airfield, comms node, water treatment).
ALLIANCES AND COALITIONS ARE ENTITIES: an opposing alliance or coalition command ("OCCASUS Alliance") IS a unit entity (command role, echelon null, usually unplaced) — it is the parent that keeps the enemy hierarchy connected. Same for a friendly coalition command the document names.
CONTROL MEASURES ARE ENTITIES: every objective, phase line, boundary, engagement area, named/targeted area of interest, battle position, attack position, tactical assembly area (as terrain graphics with their own grids — e.g. "TAA ALPHA (35UMA 21500 94200)"), air corridor, decision point, and fire support coordination measure the order states, WITH its stated grid(s). Decision points with only a contextual location ("IVO OBJ GRANT") place in the vicinity of the referenced feature and say so in position_source. Named routes (a TRM corridor, an MSR, an alternate LOC) with stated waypoints are line graphics through those waypoints; if the registry lacks a fitting line type, list them in coverage_note instead of forcing a wrong type. What stays banned is emitting a UNIT'S OWN position (its assembly area, staging grid, CP) as a separate entity — that grid belongs on the unit.

COMPLETENESS — be exhaustive. Enumerate EVERY named unit in the Task Organization / "principal subordinate units" paragraph and every named unit in the enemy order-of-battle paragraph — none may be dropped (e.g. a corps sustainment brigade, a field artillery / DIVARTY brigade, a combat aviation brigade, each named division and separate brigade on BOTH sides). Also emit every named task force (TF Eagle, TF Cougar), and every SPECIFIC named installation that has a grid or proper place name. Prefer including a clearly-named unit over omitting it.

AFFILIATION — the document describes TWO OPPOSING SIDES; keep them apart, do not default to Friend:
  - the reporting/friendly side and its allies (blue / US / NATO / the corps and its brigades, cavalry, artillery) = Friend;
  - the OPPOSING force — the threat / enemy / OPFOR / adversary, named by its own alliance or higher command (e.g. an opposing coalition) and ITS armies, divisions, and brigades (Combined Arms Army, Motorized Rifle Division, Mechanized or Motorized Infantry Division, Separate Brigade, Reconnaissance Brigade — whichever wording the document uses) = Hostile;
  - civilian / non-belligerent = Neutral; only truly indeterminate = Unknown.
  INFRASTRUCTURE affiliation = who OWNS / CONTROLS the site (whose territory it sits in, who operates it), NOT who attacked, targeted, or sabotaged it. A fuel depot, rail line, comms node, or training area in friendly or neutral territory is Friend or Neutral even when the enemy raids it; it is Hostile only if it is the enemy's own installation.
  Subordinates inherit their parent's side. A Hostile unit's higher headquarters is its OWN Hostile command, NEVER a friendly one — the enemy army is not part of the friendly corps.

RELATIONSHIPS — capture task organization, WITHIN A SIDE ONLY:
  - set parent_ref / emit an edge to connect a unit to its OWN higher headquarters on the SAME side (attached / OPCON / TACON / direct support / general support / reinforcing); infrastructure gets a (supplies) edge.
  - NEVER connect opposing sides. "the corps defeats / denies / destroys / is opposed by / attacks the enemy army" is a MISSION against the enemy, not a command relationship — emit NO edge and NO parent_ref for it. Enemy formations attach to their enemy army, friendly formations to the friendly corps.
  NAME NORMALIZATION — write every unit's "name" in ONE canonical form so the same unit is never spelled two ways. Apply these rules to EVERY name:
    - full ordinal: "173rd" not "173d"; "2nd" not "2d"; "850th" stays "850th";
    - echelon and role words SPELLED OUT in Title Case, never the bare acronym: "Brigade" not "BDE"; "Airborne Brigade" not "ABN"; "Combined Arms Army" not "CAA"; "Field Artillery Brigade" not "FA"; "Combat Aviation Brigade" not "CAB"; "Cavalry Regiment" not "CR"; "Reconnaissance Brigade" not "Recon Bde";
    - EXPAND EVERY ACRONYM EXACTLY AS THE DOCUMENT ITSELF SPELLS IT OUT. Scan the pages for the first spelled-out use of each acronym and reuse that exact wording: if the document writes "Mechanized Infantry Division (MID)" then MID expands to "Mechanized Infantry Division", NEVER "Motorized Infantry Division"; if it writes "Motorized Rifle Division (MRD)" use that. NEVER substitute an expansion from your own military knowledge when the document defines the term;
    - keep the unit's SPECIFIC numeric designation — "210th Field Artillery Brigade", never a generic role paraphrase like "V Corps Field Artillery Brigade"; if the document gives the unit a number, that number is part of its name;
    - a unit written with a SHORTER and a LONGER descriptor is ONE unit under the FULLEST name: "750th Brigade" and "750th Separate Brigade" are the same entity → emit once as "750th Separate Brigade"; squadrons of a regiment written "2-5 CAV" or "1-7 CAV" normalize consistently to "2nd Squadron, 5th Cavalry Regiment" / "1st Squadron, 7th Cavalry Regiment" (always with "Regiment");
    - NO trailing parenthetical acronym: "173rd Airborne Brigade", not "173rd Airborne Brigade (173d ABN)";
    - strip any objective / control-measure codeword from an installation's name: "Bemowo Piskie Training Area", not "Bemowo Piskie Training Area (OBJ JACKSON)";
    - reuse the SAME canonical name (and the same ref) everywhere the unit appears; a unit written several ways in the document is ONE entity, emitted once — never a second entity or edge for it.
  BEFORE YOU OUTPUT, re-read your own entity list and MERGE every pair that denotes the same real unit — not only exact-duplicate names, but any pair where one name is the other plus or minus a descriptor ("750th Brigade" vs "750th Separate Brigade"; "72nd MRD" vs "72nd Motorized Rifle Division"; "V Corps Field Artillery Brigade" vs "210th Field Artillery Brigade"). Keep the single fullest / most-specific-named entity, drop the other, and move its edges/holdings onto the one you keep. Two entities must never denote the same unit. NEVER move a unit under a DIFFERENT higher headquarters to avoid a duplicate — resolve a duplicate by MERGING the two names into one entity; each unit's parent is always the higher headquarters the document assigns it to (a brigade named as part of the 8th Army stays under the 8th Army, even if a similarly-numbered brigade exists under the 7th Army).
  If the project already lists a unit (EXISTING UNITS below), reuse that exact name.
  CRITICAL: every edge from_ref and to_ref MUST be exactly one of the "ref" values you assigned to an entity above — never name an edge endpoint that has no entity. If a relationship names a unit you did not list, add that unit as an entity first.

POSITION — never guess lat/lon. These documents are DENSE with MGRS grids like "32UPU 25000 75000" or "34UEA 56498 59601" — whenever the document ties a grid to an entity's position (assembly area, attack position, objective, staging area, home station, destination, or the site of a named installation), COPY THAT GRID VERBATIM into "mgrs". A unit's CURRENT position is where the document says it IS as of its latest dated statement — a destination, planned move, or "departure NLT" that has NOT happened yet is NEVER the position (it goes in the note text); a regiment staged at home station with orders to deploy sits at home station. A unit's assembly area / attack position / staging grid IS that unit's position — it belongs in the unit's mgrs, never as a separate "Assembly Area" or "Attack Position" entity. A ROAD TO WAR IS A CHRONOLOGICAL TIMELINE: the SAME unit is reported at DIFFERENT positions on DIFFERENT dates as it MOVES (tactical assembly area → forward staging → final attack position). Those are ONE unit's position TRACK — never separate units, never a contradiction, never "the grid must be wrong". Record EVERY dated position the document gives a unit in its "positions" array, oldest first, each with the dtg exactly as written, the grid, the named place, and the activity; and put the NEWEST (last-dated) position's grid in the top-level "mgrs" as the current laydown. WORKED EXAMPLE — a road to war that says "14 JAN 26: 72nd MRD tactical assembly area (34UEB 55000 68000)" and later "06 APR 26: 72nd MRD occupies final attack positions (34UEB 54000 70000)" is exactly ONE entity: {"name":"72nd Motorized Rifle Division","mgrs":"34UEB 54000 70000","positions":[{"dtg":"14 JAN 26","mgrs":"34UEB 55000 68000","activity":"tactical assembly area"},{"dtg":"06 APR 26","mgrs":"34UEB 54000 70000","activity":"final attack positions"}]} — NOT two units, NOT a "Final Attack Positions" entity, NOT an unplaced division. Every named division and separate brigade the document positions MUST carry its track and its current mgrs. If no grid is given, location_text must be a SPECIFIC settlement, installation, or feature (a city, town, base, garrison). It is NOT a region, theater, country, sector, corridor, or "area of operations" ("Baltic region", "Eastern Flank" are NOT locations). If a unit's specific location is not stated, leave both mgrs and location_text null. A later stage resolves the name to coordinates inside the area of operations. CONTROL MEASURES (phase lines, boundaries, engagement areas, objectives, assembly areas, named/targeted areas of interest, battle positions, air corridors) ARE entities: use the matching entity_type and put their grid vertices IN ORDER into "line" (linear) or "area" (closed shape; do not repeat the first vertex). A control measure with a single stated grid uses mgrs like any point entity. Equipment nomenclature VERBATIM — and systems a unit is described OPERATING (its UAV types, jammers, launchers, vehicles) are that unit's holdings even when named only in narrative.

PROVENANCE — every location answers "says who":
  - every entry in "positions" carries "source": the DOCUMENT and the ENTRY/PARAGRAPH that states it ("2CR Road to War, 06 APR 26 entry"), never a vague bundle reference;
  - every entity placed by its top-level mgrs / location_text carries "position_source" the same way; a placement you INFERRED (vicinity of a referenced feature, a formation's staging block, directional prose like "25 km from the border") says so explicitly in position_source;
  - when a stated grid and its own accompanying prose DISAGREE about where something is (the grid's area vs the named town), keep BOTH: named place in location_text, grid verbatim in mgrs, and state the conflict in position_source and coverage_note — never silently pick one or "fix" the grid;
  - EW/fires EFFECT locations are not emitter positions: the operating unit places at its own side's stated location and the effect rides its activity text.

STYLE — all output text is ASCII/romanized: "Elk" not "Ełk", "Svencioneliai" not "Švenčionėliai", straight quotes, no long dashes. Infrastructure named for a linear feature (a railway segment, a bridge, a pipeline) sits ON that feature — name the precise feature ("Svencioneliai railway station") in location_text, never just the town center. Output ONLY the JSON object."""
# The enum derives from THE entity-type registry (models/graph.py ENTITY_TYPE_SEED)
# minus reference-only types — never a hand-typed list.
_OOB_INSTRUCTION = _OOB_INSTRUCTION.replace(
    "__ENTITY_TYPE_ENUM__", "|".join(EXTRACTABLE_ENTITY_TYPES))



def _merge(dst: dict, src: dict):
    seen = {e["ref"] for e in dst["entities"]}
    for e in src.get("entities") or []:
        if e.get("ref") and e["ref"] not in seen:
            dst["entities"].append(e)
            seen.add(e["ref"])
    dst["edges"].extend(src.get("edges") or [])
    if src.get("coverage_note"):
        dst["notes"].append(src["coverage_note"])


async def extract_oob(pages: List[bytes], ao: AreaOfOperations, *,
                      plain_text: Optional[str] = None,
                      source_label: str = "", filename: str = "",
                      known_names: Optional[List[str]] = None,
                      templates_catalog: Optional[str] = None,
                      max_tokens: int = _MAX_OUTPUT_TOKENS) -> ExtractedOOB:
    """Stage 2 — VLM-extract the OOB from the page images (batched).

    known_names: units already in the project from earlier scenario docs.
    The model reuses these EXACT names so a later document merges into
    the existing unit instead of duplicating it under a variant spelling
    ("7th CAA" vs "7th Combined Arms Army (7th CAA)")."""
    acc = {"entities": [], "edges": [], "notes": []}
    ctx = ""
    if ao and ao.resolved:
        ctx = (f"\nCONTEXT — the operation is in {ao.theater or 'the named area'}"
               f" ({', '.join(ao.countries) or 'see pages'}); resolve place "
               f"names within that region.")
    if known_names:
        listed = ", ".join(sorted({n for n in known_names if n})[:150])
        ctx += ("\nEXISTING UNITS already in this project — if the document refers to "
                "any of these SAME units, reuse the EXACT name shown here (do not "
                "re-spell, abbreviate, or expand it differently). Add a new entity "
                "ONLY for a unit that is not already in this list:\n" + listed)
    if templates_catalog:
        ctx += (
            "\n\nFORCE TEMPLATE CATALOG — each row is `key | name | echelon | side`. "
            "A doctrinal template supplies a unit's standard equipment and subordinate "
            "structure (which the narrative rarely lists), so for EVERY unit set "
            "\"template_key\" to the SINGLE best-matching key below, or null if none fits. "
            "Match by MEANING, not exact words, and respect side + echelon: a Russia / "
            "OPFOR unit takes a rus_ or chn_ key, a US / NATO unit a us_ key. Examples: a "
            "Motorized or Mechanized Rifle / Motor Rifle Division -> rus_motorized_rifle_division; "
            "a Tank Division -> rus_tank_division; a Motor Rifle Brigade -> "
            "rus_motorized_rifle_brigade; an Armored Brigade Combat Team -> "
            "us_armored_brigade_combat_team; a Stryker unit -> us_stryker_brigade_combat_team; "
            "an Infantry Brigade Combat Team -> us_infantry_brigade_combat_team. A top-level "
            "army / corps HQ or a unit with no good match takes null.\n" + templates_catalog)

    async def _call(blocks):
        parsed = await _vlm_json(_OOB_SYSTEM, _OOB_INSTRUCTION + ctx, blocks,
                                 max_tokens=max_tokens)
        if parsed:
            _merge(acc, parsed)
        else:
            acc["notes"].append("a batch returned unparseable output")

    if plain_text and plain_text.strip():
        # Text-primary: ONE consolidated call from the lossless document
        # text, so names / MGRS grids / numbers are exact and the model's
        # self-review dedups across ALL documents in a single pass (batched
        # images cannot dedup across batches). Page images ride along for
        # visual context ONLY when the whole set fits in the same single
        # call — never split into batches here, which would defeat both.
        blocks = [{"type": "text", "text":
                   "DOCUMENT TEXT (verbatim — authoritative for unit names, "
                   "MGRS grids, and numbers):\n" + plain_text[:_TEXT_CHAR_LIMIT]}]
        if pages:
            b64 = sum((len(p) * 4) // 3 for p in pages)
            if b64 <= _BATCH_MAX_B64_BYTES:
                blocks += [_image_block(p) for p in pages]
        await _call(blocks)
    elif pages:
        # Scanned document, no text layer — vision is the only signal.
        for batch in _batch_pages(pages):
            await _call([_image_block(p) for p in batch])

    entities = []
    for e in acc["entities"]:
        holds = [ExtractedHolding(**{k: h.get(k) for k in
                 ("nomenclature", "count_authorized", "count_current") if k in h})
                 for h in (e.get("holdings") or []) if h.get("nomenclature")]
        track = [ExtractedPosition(**{k: p.get(k) for k in
                 ("dtg", "mgrs", "location_text", "activity") if k in p})
                 for p in (e.get("positions") or [])
                 if isinstance(p, dict) and (p.get("mgrs") or p.get("location_text"))]
        e2 = {k: e.get(k) for k in (
            "ref", "name", "entity_type", "affiliation", "echelon", "unit_type",
            "category", "parent_ref", "lon", "lat", "mgrs", "location_text",
            "posture", "personnel_authorized", "personnel_current",
            "significance", "significance_note", "notes", "template_key",
            "status") if e.get(k) is not None}
        e2.setdefault("ref", e.get("name") or "unnamed")
        e2.setdefault("name", e.get("ref") or "unnamed")
        entities.append(ExtractedEntity(**e2, holdings=holds, positions=track))
    edges = []
    seen_edges = set()
    for ed in acc["edges"]:
        if not (ed.get("from_ref") and ed.get("to_ref") and ed.get("relationship_type")):
            continue
        key = (ed["from_ref"], ed["to_ref"], ed["relationship_type"])
        if key in seen_edges:      # VLM restated the same relationship
            continue
        seen_edges.add(key)
        edges.append(ExtractedEdge(**{k: ed.get(k) for k in
                     ("from_ref", "to_ref", "relationship_type", "note")}))

    return ExtractedOOB(
        entities=entities, edges=edges,
        coverage_note="; ".join(acc["notes"]) or None,
        source_label=source_label or filename)
