"""Reference-store derivation pass (design weg-catalog-schema-design.md S6).

A repeatable, importable, DB-free transform: it takes the assembled WEG master
rows (datasheet v2 shape with sheet{}, narrative v2 shape with stated{}+
prior_curation{}) plus the datasheet curation sidecar, and returns the
reference store as plain-dict lists — reference_nodes, reference_links,
reference_specs, fact_clauses. The bootstrap loader bulk-inserts them; a
standalone script can call derive_catalog() and inspect the result without a
database.

Invariants honored:
- F8 no-loss: every catalog root keeps its verbatim captured row in sheet_data;
  promotion is purely additive, so a failed promotion can never drop content.
- F4 conservative minting: one weapon/munition/component object per distinct
  captured designation (exact normalized string); never a similarity merge.
- F1 spec scope: per-pairing weapon-round performance rides the fires link
  (owner_kind='link'); equipment envelopes ride the object (owner_kind='object').
- F2 paint authority: equipment-scoped engagement-range envelope specs carry
  the is_default flag from extraction, so the ground-plane slice paint reads
  today is unchanged.
- F6: clauses are entity-indexed only; no embeddings are produced.
"""
import re
import uuid

# ---- weapon-station keys (dict-valued sheet key -> a mounts link; also the
# closed station vocabulary the unified catalogue stamps on its tuples).
# Matches the controlled vocabulary's 23 station keys (weg-controlled-
# vocabulary.md), including the ten flagged extends_derivation, plus the
# legacy sheet spellings the old masters carried. The legacy `aa_weapon`
# spelling is renamed: the canonical key is `antiaircraft_weapon`.
STATION_KEYS = {
    "main_gun", "main_armament", "coax_weapon", "coaxial_weapon",
    "turret_coax_to_main_gun", "aux_weapon", "auxiliary_weapon",
    "atgm_launcher", "roof_weapon", "grenade_launcher", "agl",
    "antiaircraft_weapon", "antiaircraft_mg", "hull_weapon",
    "bow_weapon", "secondary_weapon", "tc_weapon", "commander_weapon",
    "cupola_weapon", "remote_weapon_station",
    # Vocabulary extension (extends_derivation: true).
    "missile_launcher", "rocket_launcher", "gun_weapon_station",
    "weapon_station", "loader_weapon", "chin_gun", "wing_station",
    "bomb_station", "torpedo_tube", "mine_dispenser",
    # Catalogue-synthesized key for stations titled by their weapon's name.
    "named_weapon_station",
}
# ---- ammunition sheet keys (round -> a fires link) ------------------------
AMMO_KEYS = {
    "ammunition", "main_armament_ammunition", "other_ammunition",
    "ammunition_types", "main_gun_ammunition", "gun_ammunition",
}
# ---- assembly / associated-system sheet keys ------------------------------
ASSOC_KEYS = {
    "associated_radars", "associated_systems", "radars", "radar",
    "command_and_control", "command and control", "launcher_loaders",
    "launcher_loader", "missile", "missiles", "host_aircraft",
    "host_aircraft_type", "system_components", "sensors_components",
    "other_assets",
}
# ---- component sheet keys (equipped_with) ---------------------------------
COMPONENT_KEYS = {
    "fire_control", "sights", "sight", "avionics_sensor_optics",
    "eo_sensors", "optics", "fire_control_system",
}
PAYLOAD_KEYS = {"payload_types", "payloads", "payload"}
# ---- variant sheet keys ---------------------------------------------------
VARIANT_KEYS = {"variants", "variant", "variants_left", "variants_right"}

IDENTITY_FIELDS = {"name", "nato_designator", "nato_designation",
                   "system_designation", "designation", "model"}
NAME_FIELDS = ("caliber_type_name", "caliber_type", "missile_name_nomenclature",
               "missile_name", "name", "designation", "model", "type_name",
               "fcs_name", "sight_name", "caliber", "weapon", "system_designation",
               "nato_designator", "nato_designation")
MISSILE_MARKERS = {"warhead_type", "warhead_weight_kg", "guidance", "fuze_type",
                   "launch_mode", "warhead", "fuze", "seeker"}
RADAR_MARKERS = {"frequency_band", "detection_range_km", "azimuth_coverage",
                 "number_of_targets_tracked", "sweep_rate_rpm", "eccm"}

_EMITTER_FIELDS = ("emitter_type", "frequency_band", "frequency_ghz",
                   "sweep_rate_rpm", "effective_range_km", "tracking_range_km",
                   "effective_altitude_km", "max_tracks", "emplacement_min",
                   "displacement_min")


def _slug(text):
    text = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower())
    return text.strip("_")[:120] or "x"


def _base_label(key):
    """Strip a verbatim '(2nd occurrence)' / '(3rd occurrence)' suffix and
    normalize to a comparable snake token."""
    key = re.sub(r"\s*\(\d+(?:st|nd|rd|th)\s+occurrence\)\s*$", "", str(key))
    return _slug(key)


def _first(d, fields):
    for f in fields:
        for k, v in d.items():
            if _base_label(k) == f and str(v).strip():
                return str(v).strip()
    return None


def _norm_key(k):
    return _base_label(k)


def split_flat_dict(items):
    """Split a verbatim flat dict that interleaves several sub-entities (the
    WEG '(Nth occurrence)' pattern) into an ordered list of sub-dicts, breaking
    at each new non-empty identity field once the current entity has body
    content. Leading body-only content (a platform block with no name) returns
    as the first sub-dict with no identity field."""
    entities = []
    current = {}
    has_body = False
    for key, val in items:
        base = _base_label(key)
        is_id = base in IDENTITY_FIELDS
        nonempty = str(val).strip() != ""
        if is_id and nonempty and has_body:
            entities.append(current)
            current = {}
            has_body = False
        current[key] = val
        if not is_id and nonempty:
            has_body = True
    if current:
        entities.append(current)
    return entities


class Deriver:
    def __init__(self):
        self.nodes = {}          # key -> node dict
        self.links = []          # link dicts (id pre-assigned)
        self.specs = []          # spec dicts
        self.clauses = []        # clause dicts
        self._link_seen = set()  # (from,type,to,station,role) exact-dup guard

    # ---- node/link/spec/clause emitters ---------------------------------
    def _node(self, key, object_type, name, **extra):
        if key not in self.nodes:
            node = dict(key=key, object_type=object_type, name=name,
                        country_of_origin=None, date_of_introduction=None,
                        source_page=None, sheet_data=None, image_path=None,
                        is_catalog_root=False, source="weg_import")
            node.update(extra)
            self.nodes[key] = node
        return self.nodes[key]

    def _link(self, from_key, link_type, to_key=None, to_name_raw=None,
              station=None, role=None, count=None, is_primary=False,
              is_default=False, props=None):
        sig = (from_key, link_type, to_key, station, role, to_name_raw)
        if to_key is not None and sig in self._link_seen:
            return None
        self._link_seen.add(sig)
        link = dict(id=uuid.uuid4(), from_key=from_key, to_key=to_key,
                    to_name_raw=to_name_raw, link_type=link_type,
                    station=station, role=role, count=count,
                    is_primary=is_primary, is_default=is_default, props=props)
        self.links.append(link)
        return link

    def _spec(self, owner_kind, owner_id, attribute, value_num=None,
              value_text=None, unit=None, condition=None, min_altitude_m=None,
              max_altitude_m=None, trajectory=None, is_default=False):
        self.specs.append(dict(
            id=uuid.uuid4(),
            owner_kind=owner_kind, owner_id=str(owner_id), attribute=attribute,
            value_num=value_num, value_text=value_text, unit=unit,
            condition=condition, min_altitude_m=min_altitude_m,
            max_altitude_m=max_altitude_m, trajectory=trajectory,
            is_default=is_default))

    def _clause(self, text, about, source_locus, register="gnomic",
                source_kind="weg_catalog", speaker="WEG"):
        text = str(text).strip()
        if not text:
            return
        self.clauses.append(dict(
            id=uuid.uuid4(), text=text, register=register, speaker=speaker,
            source_kind=source_kind, source_locus=source_locus,
            about=list(about), valid_from=None, valid_to=None,
            observed_at=None, embedding=None))

    # ---- weapons / mounts ------------------------------------------------
    def _mount(self, eq_key, station_key, wdict):
        name = _first(wdict, NAME_FIELDS)
        if not name:
            return
        wkey = "weapon:" + _slug(name)
        self._node(wkey, "weapon", name, sheet_data=wdict)
        count = None
        rof = _first(wdict, ("rate_of_fire_rd_min", "rate_of_fire"))
        self._link(eq_key, "mounts", to_key=wkey, station=_base_label(station_key),
                   is_primary=_base_label(station_key) in ("main_gun", "main_armament"),
                   count=count, props={"rate_of_fire": rof} if rof else wdict)
        return wkey

    # ---- munitions / fires ----------------------------------------------
    def _fire(self, from_key, mdict, role=None):
        name = _first(mdict, NAME_FIELDS)
        if not name:
            return
        mkey = "munition:" + _slug(name)
        self._node(mkey, "munition", name, sheet_data=mdict)
        link = self._link(from_key, "fires", to_key=mkey, role=role, props=mdict)
        if link is None:
            return mkey
        # Per-pairing performance on the fires link (F1).
        rng = _first(mdict, ("range_km", "range", "effective_range_m",
                             "max_eff_range_day_m", "aimed_range_m"))
        pen = _first(mdict, ("penetration_mm", "penetration"))
        if rng:
            self._spec("link", link["id"], "range", value_text=rng)
        if pen:
            self._spec("link", link["id"], "penetration", value_text=pen, unit="mm")
        # Altitude band on the pairing, when the round states one.
        self._altitude_specs("link", link["id"], mdict)
        return mkey

    # ---- assemblies / associated systems / armament ---------------------
    def _classify_and_add(self, eq_key, source_key, sub):
        """Route one sub-entity of an armament / associated-systems block to
        the right link: a missile -> fires, a radar -> associated_with(radar),
        a gun with a caliber -> mounts, a command post / launcher-loader ->
        associated_with, a leading no-name platform block -> equipment specs."""
        base = _base_label(source_key)
        markers = {_base_label(k) for k, v in sub.items() if str(v).strip()}
        name = _first(sub, NAME_FIELDS)
        is_missile = base in ("missile", "missiles") or bool(markers & MISSILE_MARKERS)
        is_radar = base in ("associated_radars", "radars", "radar") or bool(markers & RADAR_MARKERS)
        has_weapon = any(_base_label(k) in ("caliber_type_name", "caliber_type")
                         and str(v).strip() for k, v in sub.items())
        if not name:
            self._platform_specs(eq_key, sub)
            self._altitude_specs("object", eq_key, sub)
            return
        if is_missile:
            self._fire(eq_key, sub, role="associated")
            self._altitude_specs("object", eq_key, sub)
            return
        if is_radar:
            ckey = "component:" + _slug(name)
            self._node(ckey, "component", name, sheet_data=sub)
            self._link(eq_key, "associated_with", to_key=ckey, role="radar", props=sub)
            self._emitter_specs_from_sub(ckey, sub)
            return
        if has_weapon and base in ("armament", "armaments"):
            self._mount(eq_key, source_key, sub)
            return
        role = ("command" if base in ("command_and_control", "command and control") else
                "reload" if base in ("launcher_loaders", "launcher_loader") else
                "host" if base.startswith("host_aircraft") else
                "associated")
        ckey = "component:" + _slug(name)
        self._node(ckey, "component", name, sheet_data=sub)
        self._link(eq_key, "associated_with", to_key=ckey, role=role, props=sub)

    # ---- components / equipped_with -------------------------------------
    def _component(self, eq_key, source_key, cdict, role=None):
        base = _base_label(source_key)
        role = role or ("fire_control" if base.startswith("fire_control") else
                        "sight" if base in ("sights", "sight") else
                        "sensor" if base in ("avionics_sensor_optics", "eo_sensors", "optics") else
                        "component")
        name = _first(cdict, NAME_FIELDS) or base.replace("_", " ").title()
        ckey = "component:" + _slug(name)
        self._node(ckey, "component", name, sheet_data=cdict)
        self._link(eq_key, "equipped_with", to_key=ckey, role=role, props=cdict)

    def _emitter_specs_from_sub(self, ckey, sub):
        band = _first(sub, ("frequency_band",))
        det = _first(sub, ("detection_range_km", "detection_range"))
        if band:
            self._spec("object", ckey, "frequency_band", value_text=band)
        if det:
            self._spec("object", ckey, "detection_range", value_text=det, unit="km")

    # ---- canonical emitters (from curation sidecar / prior_curation) ----
    def _canonical_emitters(self, eq_key, emitters):
        """Mint an emitter-bearing component per canonical emitter and store
        the verbatim emitter dict on the equipped_with link, so the projection
        reproduces weg_equipment_emitters exactly (F3 zero-regression). Also
        record its numeric fields as component specs (the store's query surface)."""
        for idx, em in enumerate(emitters or []):
            if not isinstance(em, dict):
                continue
            etype = em.get("emitter_type") or f"emitter {idx + 1}"
            ckey = f"component:emitter:{eq_key}:{idx}"
            self._node(ckey, "component", str(etype)[:500], sheet_data=em)
            self._link(eq_key, "equipped_with", to_key=ckey, role="emitter",
                       props={k: em.get(k) for k in _EMITTER_FIELDS})
            for field in _EMITTER_FIELDS:
                val = em.get(field)
                if val in (None, ""):
                    continue
                if isinstance(val, (int, float)):
                    self._spec("object", ckey, field, value_num=float(val))
                else:
                    self._spec("object", ckey, field, value_text=str(val))

    # ---- variants --------------------------------------------------------
    def _variant(self, eq_key, vobj):
        if isinstance(vobj, str):
            name, delta = vobj, None
        elif isinstance(vobj, dict):
            name = (vobj.get("variant") or vobj.get("name") or vobj.get("label")
                    or _first(vobj, NAME_FIELDS))
            delta = vobj.get("description") or vobj.get("value") or _summarize(vobj)
        else:
            return
        if not name:
            return
        vkey = f"{eq_key}:variant:{_slug(name)}"
        self._node(vkey, "equipment", str(name), sheet_data=vobj if isinstance(vobj, dict) else {"variant": name})
        self._link(vkey, "variant_of", to_key=eq_key,
                   props={"delta": delta} if delta else None)
        if delta:
            self._clause(f"{name}: {delta}", about=[eq_key, vkey],
                         source_locus="variants", register="gnomic")

    def _collect_variants(self, eq_key, sheet, row):
        found = []
        for key in list(sheet.keys()):
            if _base_label(key) in VARIANT_KEYS:
                found.append(sheet[key])
        # sheet.notes.variants (T-90 pattern) and top-level notes/variants.
        notes = sheet.get("notes")
        if isinstance(notes, dict) and isinstance(notes.get("variants"), list):
            found.append(notes["variants"])
        for extra in ("variants", "notes"):
            v = row.get(extra)
            if v is not None:
                found.append(v)
        for block in found:
            if isinstance(block, list):
                for item in block:
                    self._variant(eq_key, item)
            elif isinstance(block, dict):
                # {variant_name: delta} or a single {variant,description}
                if _base_label_any(block, ("variant", "name", "description")):
                    self._variant(eq_key, block)
                else:
                    for vname, delta in block.items():
                        self._variant(eq_key, {"variant": vname, "description": delta})
            elif isinstance(block, str):
                self._variant(eq_key, block)

    # ---- altitude / envelope specs --------------------------------------
    def _altitude_specs(self, owner_kind, owner_id, src):
        """Parse captured altitude bands (SA-12 missile blocks, UAV ceilings)
        into envelope specs with min/max altitude in metres."""
        for key, val in src.items():
            base = _base_label(key)
            if "altitude" not in base and "ceiling" not in base:
                continue
            text = str(val).strip()
            if not text:
                continue
            lo, hi = _parse_altitude_km(text)
            if lo is None and hi is None:
                continue
            self._spec(owner_kind, owner_id, "engagement_altitude",
                       value_text=text, unit="m",
                       min_altitude_m=lo, max_altitude_m=hi,
                       condition=key)

    def _envelope_specs(self, eq_key, range_candidates):
        for rc in range_candidates or []:
            rm = rc.get("range_m")
            if rm is None:
                continue
            self._spec("object", eq_key, "engagement_range", value_num=float(rm),
                       unit="m", condition=rc.get("condition") or rc.get("label"),
                       is_default=bool(rc.get("is_default")))

    # ---- the main per-row pass ------------------------------------------
    def add_equipment(self, row, curation):
        eq_key = row["weg_id"]
        pc = row.get("prior_curation") or {}
        node = self._node(
            eq_key, "equipment", row.get("name") or eq_key,
            country_of_origin=(row.get("country_of_origin") or pc.get("country_of_origin")),
            date_of_introduction=(row.get("date_of_introduction")
                                  or pc.get("date_of_introduction")
                                  or (row.get("sheet") or {}).get("date_of_introduction")),
            source_page=str(row.get("source_page") or pc.get("source_page") or ""),
            sheet_data=row, is_catalog_root=True)

        sheet = row.get("sheet") or {}
        # Weapons, ammunition, associations, components, payloads, variants.
        primary_weapon = None
        for key, val in sheet.items():
            base = _base_label(key)
            if base in STATION_KEYS and isinstance(val, dict):
                wk = self._mount(eq_key, key, val)
                if base in ("main_gun", "main_armament") and wk:
                    primary_weapon = wk
        # ammunition -> fires (attach to primary weapon if present, else eq).
        for key, val in sheet.items():
            if _base_label(key) not in AMMO_KEYS:
                continue
            frm = primary_weapon or eq_key
            for rnd in _iter_rounds(val):
                self._fire(frm, rnd)
        # associations + armament (flat interleaved dicts, SA-12 pattern).
        for key, val in sheet.items():
            base = _base_label(key)
            if base not in ASSOC_KEYS and base not in ("armament", "armaments"):
                continue
            if isinstance(val, dict):
                for sub in split_flat_dict(list(val.items())):
                    self._classify_and_add(eq_key, key, sub)
            elif isinstance(val, list):
                for sub in val:
                    if isinstance(sub, dict):
                        self._classify_and_add(eq_key, key, sub)
        # components (equipped_with).
        for key, val in sheet.items():
            base = _base_label(key)
            if base in COMPONENT_KEYS and isinstance(val, dict):
                self._component(eq_key, key, val)
            if base in PAYLOAD_KEYS and isinstance(val, dict):
                for pname, pval in val.items():
                    self._component(eq_key, key,
                                    pval if isinstance(pval, dict) else {"name": pname, "value": pval},
                                    role="payload")
        # variants.
        self._collect_variants(eq_key, sheet, row)
        # envelope + altitude specs (F2 paint authority).
        rcs = row.get("range_candidates") or pc.get("range_candidates") or []
        self._envelope_specs(eq_key, rcs)
        self._altitude_specs("object", eq_key, sheet)
        # canonical emitters (curation sidecar for datasheet; prior_curation for narrative).
        emitters = (curation.get("emitters") if curation else None) or pc.get("emitters")
        self._canonical_emitters(eq_key, emitters)
        # clauses: sheet_notes, stated{}, top-level notes.
        for locus in ("sheet_notes",):
            note = row.get(locus)
            if isinstance(note, str) and note.strip():
                self._clause(note, about=[eq_key], source_locus=locus)
        for label, value in (row.get("stated") or {}).items():
            if isinstance(value, (str, int, float)) and str(value).strip():
                self._clause(f"{label.replace('_', ' ')}: {value}",
                             about=[eq_key], source_locus=f"stated.{label}",
                             speaker="OSINT")

    def _platform_specs(self, eq_key, sub):
        """A leading no-name block inside an armament/assembly dict carries the
        platform's own performance figures (reaction time, emplacement,
        endurance). Land the reachability-relevant ones as spec tuples."""
        wanted = {
            "reaction_time_sec": ("reaction_time", "sec"),
            "reaction_time": ("reaction_time", "sec"),
            "emplacement_displacement_time_min": ("emplacement_displacement", "min"),
            "emplacement_min": ("emplacement", "min"),
            "displacement_min": ("displacement", "min"),
            "endurance_min": ("endurance", "min"),
            "endurance_hr": ("endurance", "hr"),
        }
        for key, val in sub.items():
            base = _base_label(key)
            if base in wanted and str(val).strip():
                attr, unit = wanted[base]
                self._spec("object", eq_key, attr, value_text=str(val).strip(), unit=unit)

    def result(self):
        return {"nodes": list(self.nodes.values()), "links": self.links,
                "specs": self.specs, "clauses": self.clauses}


def _base_label_any(d, fields):
    return any(_base_label(k) in fields for k in d)


def _summarize(d):
    parts = [f"{k}: {v}" for k, v in d.items() if str(v).strip()]
    return "; ".join(parts)[:1000] or None


def _iter_rounds(val):
    if isinstance(val, list):
        for item in val:
            if isinstance(item, dict):
                yield item
    elif isinstance(val, dict):
        # {round_name: {specs}} OR a single flat round.
        if all(isinstance(v, dict) for v in val.values()) and val:
            for rname, rspec in val.items():
                rec = dict(rspec)
                rec.setdefault("name", rname)
                yield rec
        else:
            yield val


_ALT_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)")


def _parse_altitude_km(text):
    """Extract a (min_m, max_m) altitude band from a verbatim string such as
    '0.025 - 25' or 'Max Altitude: 25 TBMs, 30 aircraft' (values in km)."""
    nums = [float(x) for x in _ALT_RE.findall(text)]
    if not nums:
        return None, None
    lo = min(nums) * 1000.0
    hi = max(nums) * 1000.0
    return lo, hi


def derive_catalog(rows, curation_map):
    """rows: iterable of assembled master rows (any source). curation_map:
    {weg_id: {domain,class,category,tier,caliber,...,emitters}}. Returns the
    reference store as plain-dict lists."""
    d = Deriver()
    for row in rows:
        if not row.get("weg_id"):
            continue
        d.add_equipment(row, curation_map.get(row["weg_id"]) or {})
    return d.result()


# ===========================================================================
# Unified-catalogue adapter (the ODIN-shape input): derives the reference
# store from the merged WEG catalogue (odin_weg_work/catalog/*.jsonl shape —
# per-record typed spec tuples in section-role buckets, station-stamped
# armament, promoted variants, value conflicts, verbatim capture).
#
# The same invariants hold: F8 no-loss (the ENTIRE record rides sheet_data on
# the catalog root), F4 conservative minting (one weapon/munition object per
# distinct normalized designation), F1 spec scope (per-pairing round
# performance on the fires link; platform envelopes on the object), F2 paint
# authority (the is_default engagement candidate is the paint default).
# Escaped tuples (property x_unmapped / x_unnamed) are never typed specs —
# they stay verbatim in sheet_data.
# ===========================================================================

_NEGATIVE_VALUES = {"no", "none", "n/a", "na", "ina", "nil", "-", "unknown"}

# "2 x PKT 7.62mm machine gun" — the source states quantity x designation.
# The count rides the mounts/fires link; the node keys on the designation
# (F4: one object per distinct designation, and "1 x PKT" and "PKT" are the
# same designation).
_COUNT_PREFIX = re.compile(r"^\s*(\d+)\s*[x×]\s+(?=\S)", re.I)


def _split_count_prefix(name):
    m = _COUNT_PREFIX.match(name)
    if not m:
        return None, name
    return int(m.group(1)), name[m.end():].strip()


def _is_escaped(prop):
    return not prop or (isinstance(prop, str) and prop.startswith("x_"))


def _scalar_text(value):
    """Merged records occasionally carry a single-valued field as a list
    (multi-source fold residue). Text columns take the joined verbatim."""
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v not in (None, "")) or None
    return str(value)


def _tuple_condition(t):
    cond = t.get("condition") or ""
    return cond or None


def _group_station_tuples(tuples):
    """Group a bucket's tuples by their station instance: (station, ordinal,
    option). Preserves source order inside each group."""
    groups = {}
    for t in sorted(tuples or [], key=lambda x: (x.get("source_order") or 0)):
        key = (t.get("station"), t.get("ordinal"), t.get("option"))
        groups.setdefault(key, []).append(t)
    return groups


def _split_rounds(tuples):
    """Split one station's ammunition/munition tuples into rounds at each
    `name` tuple (ODIN's option blocks each open with Name). A leading
    nameless run returns with name None."""
    rounds = []
    current_name, current = None, []
    for t in tuples:
        if t.get("property") == "name" and str(t.get("value_text") or "").strip():
            if current or current_name:
                rounds.append((current_name, current))
            current_name, current = str(t["value_text"]).strip(), []
        else:
            current.append(t)
    rounds.append((current_name, current))
    return [(n, ts) for n, ts in rounds if n or ts]


def _flat_props(tuples):
    """A JSONB-safe flat {label: value} view of one group's tuples (the
    mounts/fires link props surface, mirroring the old sheet-dict props)."""
    out = {}
    for t in tuples:
        label = t.get("label") or t.get("raw_name") or t.get("property") or "value"
        val = t.get("raw_value") if t.get("raw_value") not in (None, "") else t.get("value_text")
        if val in (None, ""):
            continue
        if label in out and out[label] != val:
            n = 2
            while f"{label} ({n})" in out:
                n += 1
            label = f"{label} ({n})"
        out[label] = val
    return out


_ALTITUDE_PROPS = ("altitude_envelope", "service_ceiling",
                   "engagement_altitude")


def _fold(s):
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


# Cross-root resolution: when a mounted weapon, fired round, assembly member
# or host platform is ITSELF a catalogue record, the link points at that
# equipment root (design S6.2: "some associated systems are themselves
# catalog rows... either way the link between them is the data"). Binding is
# deliberately conservative — an exact normalized designation form that maps
# to exactly ONE root, gated by kind/type compatibility, never containment
# or similarity (name matching measured ~17% wrong on this corpus; the gate
# exists because "M53" uniquely folding to a mortar record does not make the
# AH-1J's M53 gun subsystem that mortar).
_ROUND_TARGET_TYPES = ("missile", "rocket", "bomb", "torpedo", "munition",
                       "grenade", "atgm", "loitering")
_STATION_TARGET_TYPES = ("gun", "cannon", "rifle", "atgm", "launcher",
                         "rocket_pod", "missile", "shotgun", "flamethrower",
                         "hmg", "gpmg", "lmg", "mmg", "mortar", "turret")


def build_root_index(records):
    """fold(designation form) -> root id, unambiguous forms only, plus the
    root equipment types for the kind gate."""
    from collections import defaultdict
    forms_index = defaultdict(set)
    types = {}
    for r in records:
        rid = r.get("id")
        if not rid:
            continue
        types[rid] = str(r.get("equipment_type") or "")
        forms = set(r.get("aliases") or [])
        forms.add(r.get("name") or "")
        forms.add(r.get("full_name") or "")
        if r.get("designation"):
            forms.add(str(r["designation"]))
        for form in forms:
            fo = _fold(form)
            if len(fo) >= 3:
                forms_index[fo].add(rid)
    unique = {k: next(iter(v)) for k, v in forms_index.items() if len(v) == 1}
    return unique, types


def _alt_meters(value, unit):
    if value is None:
        return None
    unit = (unit or "m").lower()
    if unit in ("km",):
        return float(value) * 1000.0
    if unit in ("ft", "feet"):
        return float(value) * 0.3048
    return float(value)


class UnifiedDeriver(Deriver):

    def __init__(self):
        super().__init__()
        self.root_index = {}
        self.root_types = {}

    def _resolve_root(self, name, kind, eq_key):
        """A designation resolving to exactly one catalogue root, kind-gated.
        Returns the root id (possibly eq_key itself — the caller decides what
        a self-reference means) or None."""
        target = self.root_index.get(_fold(name))
        if not target:
            return None
        if target == eq_key:
            return target
        t = self.root_types.get(target, "")
        if kind == "round" and not any(x in t for x in _ROUND_TARGET_TYPES):
            return None
        if kind == "station" and not any(x in t for x in _STATION_TARGET_TYPES):
            return None
        return target

    def _emit_tuple_spec(self, owner_kind, owner_id, t, is_default=False,
                         clause_about=None):
        prop = t.get("property")
        if _is_escaped(prop):
            return
        num = t.get("value_num")
        text = t.get("value_text")
        if num is None and (text is None or not str(text).strip()):
            return
        # Prose is a clause, never a spec — the allocation rule (design
        # S4.3/S10): structure where computation reads, language elsewhere.
        if prop == "note":
            locus = " > ".join(t.get("raw_section_path") or []) or "note"
            self._clause(str(text or num), about=clause_about or [str(owner_id)],
                         source_locus=f"note:{locus}")
            return
        # The S6.7 envelope package: altitude-band properties carry their
        # band on the spec's min/max altitude columns (metres MSL).
        min_alt = max_alt = None
        if prop in _ALTITUDE_PROPS and num is not None:
            unit = t.get("unit") or t.get("canonical_unit")
            high = t.get("value_num_high")
            if high is not None:
                min_alt = _alt_meters(num, unit)
                max_alt = _alt_meters(high, unit)
            else:
                max_alt = _alt_meters(num, unit)
        self._spec(owner_kind, owner_id, str(prop),
                   value_num=float(num) if num is not None else None,
                   value_text=None if text is None else str(text),
                   unit=t.get("unit") or t.get("canonical_unit"),
                   condition=_tuple_condition(t),
                   min_altitude_m=min_alt, max_altitude_m=max_alt,
                   is_default=is_default)

    def _station_weapons(self, eq_key, sp):
        """Weapon-station groups -> weapon nodes + mounts links (or a bare
        mounts link when the station names no weapon). Returns
        {station: weapon_key} for ammunition attachment."""
        weapon_by_station = {}
        for (station, ordinal, option), tuples in _group_station_tuples(
                sp.get("weapon_station")).items():
            name = None
            for t in tuples:
                if t.get("property") in ("name", "designation") and str(
                        t.get("value_text") or "").strip():
                    name = str(t["value_text"]).strip()
                    break
            body = [t for t in tuples
                    if not (t.get("property") == "name"
                            and t.get("value_text") == name)]
            if name:
                count, name = _split_count_prefix(name)
                root = self._resolve_root(name, "station", eq_key)
                if root == eq_key:
                    # The station names the record itself (a rifle's own
                    # main-armament block): its figures ARE the record's.
                    for t in body:
                        self._emit_tuple_spec("object", eq_key, t,
                                              clause_about=[eq_key])
                    continue
                if root:
                    link = self._link(
                        eq_key, "mounts", to_key=root, station=station,
                        is_primary=station in ("main_gun", "main_armament"),
                        count=count, props=_flat_props(tuples))
                    weapon_by_station.setdefault(station, root)
                    if link:
                        for t in body:
                            self._emit_tuple_spec("link", link["id"], t,
                                                  clause_about=[eq_key, root])
                    continue
                wkey = "weapon:" + _slug(name)
                self._node(wkey, "weapon", name, sheet_data=_flat_props(tuples))
                self._link(eq_key, "mounts", to_key=wkey, station=station,
                           is_primary=station in ("main_gun", "main_armament"),
                           count=count, props=_flat_props(tuples))
                weapon_by_station.setdefault(station, wkey)
                for t in body:
                    self._emit_tuple_spec("object", wkey, t,
                                          clause_about=[eq_key, wkey])
            else:
                link = self._link(eq_key, "mounts", to_key=None,
                                  station=station, props=_flat_props(tuples))
                owner = ("link", link["id"]) if link else ("object", eq_key)
                for t in body:
                    self._emit_tuple_spec(owner[0], owner[1], t,
                                          clause_about=[eq_key])
        return weapon_by_station

    def _rounds(self, eq_key, sp, weapon_by_station):
        """ammunition_option + munition tuples -> munition nodes + fires
        links from the round's station weapon (equipment root when the
        station minted no weapon), per-pairing specs on the link (F1)."""
        for bucket in ("ammunition_option", "munition"):
            for (station, ordinal, option), tuples in _group_station_tuples(
                    sp.get(bucket)).items():
                frm = weapon_by_station.get(station) or eq_key
                for rname, rtuples in _split_rounds(tuples):
                    if not rname:
                        for t in rtuples:
                            self._emit_tuple_spec("object", frm, t)
                        continue
                    count, rname = _split_count_prefix(rname)
                    root = self._resolve_root(rname, "round", eq_key)
                    if root and root not in (eq_key, frm):
                        link = self._link(frm, "fires", to_key=root,
                                          role="option %s" % option if option else None,
                                          count=count, props=_flat_props(rtuples))
                        if link:
                            for t in rtuples:
                                self._emit_tuple_spec(
                                    "link", link["id"], t,
                                    clause_about=[frm, root])
                        continue
                    mkey = "munition:" + _slug(rname)
                    self._node(mkey, "munition", rname,
                               sheet_data=_flat_props(rtuples))
                    link = self._link(frm, "fires", to_key=mkey,
                                      role="option %s" % option if option else None,
                                      count=count, props=_flat_props(rtuples))
                    if link is None:
                        continue
                    for t in rtuples:
                        self._emit_tuple_spec("link", link["id"], t,
                                              clause_about=[frm, mkey])

    def _components_and_emitters(self, eq_key, rec, sp):
        """component-bucket tuples and the record's reconciled emitters ->
        equipped_with links (descriptive value as to_name_raw) + object
        specs; a bare yes/no presence value stays a spec only."""
        for t in sp.get("component") or []:
            self._emit_tuple_spec("object", eq_key, t)
            val = str(t.get("value_text") or "").strip()
            if val and val.lower() not in _NEGATIVE_VALUES and len(val) > 3:
                self._link(eq_key, "equipped_with", to_key=None,
                           to_name_raw=val[:500],
                           role=str(t.get("property") or "component")[:64],
                           props={k: t.get(k) for k in
                                  ("property", "raw_name", "raw_value",
                                   "source", "source_identifier")})
        for em in rec.get("emitters") or []:
            val = str(em.get("value_text") or "").strip()
            if not val or val.lower() in _NEGATIVE_VALUES:
                continue
            self._link(eq_key, "equipped_with", to_key=None,
                       to_name_raw=val[:500], role="emitter", props=em)

    def _assemblies(self, eq_key, sp):
        """Assembly blocks are cross-system composition (design S6.2: the
        link between an assembly and its members IS the data — the SA-12
        pattern). Groups key on the sub-block heading; a named group mints
        a component object + associated_with link with the group's figures
        as specs on the component; a nameless group's figures stay on the
        equipment (the bare-prose escape rides to_name_raw only where a
        name exists)."""
        groups = {}
        for t in sorted(sp.get("assembly") or [],
                        key=lambda x: (x.get("source_order") or 0)):
            key = tuple(t.get("raw_section_path") or [])
            groups.setdefault(key, []).append(t)
        for path, tuples in groups.items():
            name = None
            for t in tuples:
                if t.get("property") == "name" and str(
                        t.get("value_text") or "").strip():
                    name = str(t["value_text"]).strip()
                    break
            if not name:
                for t in tuples:
                    self._emit_tuple_spec("object", eq_key, t,
                                          clause_about=[eq_key])
                continue
            count, name = _split_count_prefix(name)
            root = self._resolve_root(name, "assembly", eq_key)
            if root and root != eq_key:
                link = self._link(eq_key, "associated_with", to_key=root,
                                  role="assembly", count=count,
                                  props=_flat_props(tuples))
                if link:
                    for t in tuples:
                        if t.get("property") == "name":
                            continue
                        self._emit_tuple_spec("link", link["id"], t,
                                              clause_about=[eq_key, root])
                continue
            ckey = "component:" + _slug(name)
            self._node(ckey, "component", name, sheet_data=_flat_props(tuples))
            self._link(eq_key, "associated_with", to_key=ckey,
                       role="assembly", count=count,
                       props=_flat_props(tuples))
            for t in tuples:
                if t.get("property") == "name" and t.get("value_text") and \
                        str(t["value_text"]).strip().endswith(name):
                    continue
                self._emit_tuple_spec("object", ckey, t,
                                      clause_about=[eq_key, ckey])

    def _object_specs(self, eq_key, sp):
        """Descriptive, payload and candidate buckets -> typed object
        specs. Engagement candidates carry the F2 is_default flag;
        narrative tuples land unless adjudication suppressed them."""
        for bucket in ("descriptive_block", "payload_block",
                       "dimension_candidate", "detection_range_candidate",
                       "mobility_range_candidate", "variant_block"):
            for t in sp.get(bucket) or []:
                self._emit_tuple_spec("object", eq_key, t,
                                      clause_about=[eq_key])
        for t in sp.get("engagement_range_candidate") or []:
            self._emit_tuple_spec("object", eq_key, t,
                                  is_default=bool(t.get("is_default")))
        for t in sp.get("narrative") or []:
            if t.get("suppressed"):
                continue
            self._emit_tuple_spec("object", eq_key, t, clause_about=[eq_key])

    def _record_clauses(self, eq_key, rec):
        for text in rec.get("classification_clauses") or []:
            self._clause(text, about=[eq_key], source_locus="classification")
        for entry in rec.get("provenance_clauses") or []:
            if isinstance(entry, dict) and entry.get("text"):
                self._clause(entry["text"], about=[eq_key],
                             source_locus="provenance:%s" % (entry.get("raw_name") or ""),
                             speaker=str(entry.get("source") or "WEG").upper())
        if isinstance(rec.get("odin_notes"), str):
            self._clause(rec["odin_notes"], about=[eq_key],
                         source_locus="odin_notes", speaker="ODIN")
        for note in rec.get("notes") or []:
            if isinstance(note, str):
                self._clause(note, about=[eq_key], source_locus="notes")

    def _catalogue_variants(self, eq_key, rec):
        for v in rec.get("variants") or []:
            if not isinstance(v, dict):
                continue
            name = v.get("designation") or v.get("name")
            if not name or not str(name).strip():
                continue
            name = str(name).strip()
            vkey = f"{eq_key}:variant:{_slug(name)}"
            self._node(vkey, "equipment", name, sheet_data=v)
            self._link(vkey, "variant_of", to_key=eq_key,
                       props={"delta": v.get("description")}
                       if v.get("description") else None)
            if v.get("description"):
                self._clause(f"{name}: {v['description']}",
                             about=[eq_key, vkey], source_locus="variants")

    def add_unified_record(self, rec):
        eq_key = rec["id"]
        origin = rec.get("origin") or []
        date = _scalar_text(rec.get("date_of_introduction"))
        if not date and rec.get("year"):
            date = str(rec["year"])
        source_page = rec.get("odin_identifier")
        if not source_page and rec.get("odin_identifiers"):
            source_page = rec["odin_identifiers"][0]
        self._node(eq_key, "equipment", rec.get("name") or eq_key,
                   country_of_origin=", ".join(origin) or None,
                   date_of_introduction=date, source_page=source_page,
                   sheet_data=rec, is_catalog_root=True)
        sp = rec.get("specs") or {}
        weapon_by_station = self._station_weapons(eq_key, sp)
        self._rounds(eq_key, sp, weapon_by_station)
        self._components_and_emitters(eq_key, rec, sp)
        self._assemblies(eq_key, sp)
        self._object_specs(eq_key, sp)
        self._record_clauses(eq_key, rec)
        self._catalogue_variants(eq_key, rec)

    def add_root_relations(self, rec, root_keys):
        """Root-to-root relations, applied after every root exists so to_key
        resolution is exact: catalogue variant_of, derived_from lineage, and
        carried-by host platforms (name-raw; the platform record lives in
        another bin under its own id)."""
        eq_key = rec["id"]
        vof = rec.get("variant_of")
        if isinstance(vof, dict) and vof.get("id"):
            target = vof["id"]
            self._link(eq_key, "variant_of",
                       to_key=target if target in root_keys else None,
                       to_name_raw=None if target in root_keys else target,
                       props={"basis": vof.get("basis")} if vof.get("basis") else None)
            if vof.get("basis"):
                self._clause(vof["basis"], about=[eq_key, target],
                             source_locus="variant_of")
        # derived_from is a single lineage statement: a target record id
        # (str), or a dict naming an ODIN identifier / record key with a
        # basis sentence.
        dfrom = rec.get("derived_from")
        targets = []
        if isinstance(dfrom, str):
            targets.append((dfrom, None))
        elif isinstance(dfrom, dict):
            targets.append((dfrom.get("id") or dfrom.get("record_key")
                            or dfrom.get("odin_identifier"),
                            dfrom.get("basis")))
        elif isinstance(dfrom, list):
            for item in dfrom:
                if isinstance(item, str):
                    targets.append((item, None))
                elif isinstance(item, dict):
                    targets.append((item.get("id") or item.get("record_key"),
                                    item.get("basis")))
        for target, basis in targets:
            if not target:
                continue
            self._link(eq_key, "derived_from",
                       to_key=target if target in root_keys else None,
                       to_name_raw=None if target in root_keys else str(target),
                       props={"basis": basis} if basis else None)
            if basis:
                self._clause(basis, about=[eq_key], source_locus="derived_from")
        carried = rec.get("carried_by_platforms")
        if isinstance(carried, dict):
            for pname in carried.get("platforms") or []:
                host = self.root_index.get(_fold(pname))
                self._link(eq_key, "associated_with",
                           to_key=host if host and host != eq_key else None,
                           to_name_raw=None if host and host != eq_key
                           else str(pname)[:500],
                           role="host", props={"note": carried.get("note")})


def derive_unified_catalog(records):
    """records: iterable of unified-catalogue records (the merged catalog/
    *.jsonl shape). Returns the reference store as plain-dict lists."""
    d = UnifiedDeriver()
    records = list(records)
    root_keys = {r["id"] for r in records if r.get("id")}
    d.root_index, d.root_types = build_root_index(records)
    for rec in records:
        if rec.get("id"):
            d.add_unified_record(rec)
    for rec in records:
        if rec.get("id"):
            d.add_root_relations(rec, root_keys)
    return d.result()
