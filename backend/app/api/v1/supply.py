"""
Supply chain intelligence endpoints — queries BigQuery SAP mirror (MARA/MARC/MARD).

Endpoints:
  GET /supply/depot-status  → GeoJSON FeatureCollection (depots) + lane metadata with equipment
  GET /supply/anomalies     → anomalous items, optionally filtered by depot or NSN
"""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException

router = APIRouter()

# Real-world coordinates for each SAP plant code
DEPOT_LOCATIONS = {
    "DSCR": {"lng": -77.44, "lat": 37.52, "name": "Defense Supply Center Richmond", "role": "Primary CONUS Depot"},
    "CCAD": {"lng": -97.43, "lat": 27.71, "name": "Corpus Christi Army Depot",       "role": "Aviation MRO Depot"},
    "GUAM": {"lng": 144.79, "lat": 13.44, "name": "Guam Forward DC",                 "role": "Forward DC – PAC1"},
    "YOKS": {"lng": 139.67, "lat": 35.30, "name": "Yokosuka Forward DC",             "role": "Forward DC – PAC2"},
}

# Supply lanes derived from MARC.ZZFWD / MARC.ZZLANE
# Each tuple: (origin_depot, dest_depot, lane_name, hex_color)
SUPPLY_LANES = [
    ("DSCR", "GUAM", "PAC1", "#3b82f6"),   # blue   – heaviest lane
    ("DSCR", "YOKS", "PAC2", "#a855f7"),   # purple
    ("CCAD", "GUAM", "PAC1", "#06b6d4"),   # cyan
    ("CCAD", "YOKS", "PAC2", "#14b8a6"),   # teal
]

# Federal Supply Class → human-readable equipment category
FSC_NAMES = {
    "1615": "Rotor Systems",
    "2840": "T700 Engine",
    "3040": "Transmission",
    "1560": "Airframe",
    "1680": "Flight Controls",
    "2920": "Eng. Electrical",
    "6115": "Generator",
    "2610": "Tires",
    "5340": "Hardware",
}

SEVERITY_ORDER = {
    "CRITICAL – zero on-hand":          1,
    "HIGH – below ROP, single-source":  2,
    "MEDIUM – below ROP":               3,
    "OK":                               4,
}


# ---------------------------------------------------------------------------
# BigQuery helpers
# ---------------------------------------------------------------------------

def _get_bq_client():
    try:
        from google.cloud import bigquery          # noqa: PLC0415
        from google.oauth2 import service_account  # noqa: PLC0415
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="google-cloud-bigquery is not installed in this container. "
                   "Add it to requirements.txt and rebuild.",
        )

    try:
        from dotenv import load_dotenv  # noqa: PLC0415
        load_dotenv()
    except ImportError:
        pass

    project      = os.environ.get("GOOGLE_APPLICATION_PROJECT_ID")
    private_key  = os.environ.get("GOOGLE_APPLICATION_PRIVATE_KEY", "").replace("\\n", "\n")
    client_email = os.environ.get("GOOGLE_APPLICATION_CLIENT_EMAIL")
    dataset      = os.environ.get("BQ_DATASET", "sap_mirror")

    if not all([project, private_key, client_email]):
        raise HTTPException(
            status_code=503,
            detail="BigQuery credentials not configured. Set GOOGLE_APPLICATION_PROJECT_ID, "
                   "GOOGLE_APPLICATION_PRIVATE_KEY, and GOOGLE_APPLICATION_CLIENT_EMAIL.",
        )

    credentials = service_account.Credentials.from_service_account_info({
        "type":         "service_account",
        "project_id":   project,
        "private_key":  private_key,
        "client_email": client_email,
        "token_uri":    "https://oauth2.googleapis.com/token",
    })

    return bigquery.Client(project=project, credentials=credentials), project, dataset


def _query_all_items(client, project: str, dataset: str) -> list[dict]:
    """All depot-item rows with anomaly classification (demand class A/B only)."""
    sql = f"""
    SELECT
        a.BISMT                                                             AS nsn,
        a.MATKL                                                             AS fsc,
        c.WERKS                                                             AS depot,
        CAST(c.LABST  AS FLOAT64)                                           AS on_hand,
        CAST(c.UMLME  AS FLOAT64)                                           AS in_transit,
        CAST(c.LABST  AS FLOAT64) + CAST(c.UMLME AS FLOAT64)               AS available,
        CAST(b.MINBE  AS FLOAT64)                                           AS reorder_point,
        CAST(b.MABST  AS FLOAT64)                                           AS max_stock,
        b.PLIFZ                                                             AS lead_time_days,
        a.ZZDML                                                             AS demand_class,
        a.ZZSLC                                                             AS source_count,
        CASE
            WHEN CAST(c.LABST AS FLOAT64) = 0
                THEN 'CRITICAL – zero on-hand'
            WHEN CAST(c.LABST AS FLOAT64) < CAST(b.MINBE AS FLOAT64)
                 AND a.ZZSLC = '1'
                THEN 'HIGH – below ROP, single-source'
            WHEN CAST(c.LABST AS FLOAT64) < CAST(b.MINBE AS FLOAT64)
                THEN 'MEDIUM – below ROP'
            ELSE 'OK'
        END                                                                 AS anomaly
    FROM `{project}.{dataset}.mara` a
    JOIN `{project}.{dataset}.marc` b
        ON  a.MANDT = b.MANDT AND a.MATNR = b.MATNR
    JOIN `{project}.{dataset}.mard` c
        ON  b.MANDT = c.MANDT AND b.MATNR = c.MATNR AND b.WERKS = c.WERKS
    WHERE a.ZZDML IN ('A', 'B')
    ORDER BY
        CASE
            WHEN CAST(c.LABST AS FLOAT64) = 0                                         THEN 1
            WHEN CAST(c.LABST AS FLOAT64) < CAST(b.MINBE AS FLOAT64) AND a.ZZSLC='1' THEN 2
            WHEN CAST(c.LABST AS FLOAT64) < CAST(b.MINBE AS FLOAT64)                 THEN 3
            ELSE 4
        END,
        b.PLIFZ DESC
    """
    return [dict(row) for row in client.query(sql).result()]


def _query_lane_items(client, project: str, dataset: str) -> list[dict]:
    """
    Items scoped to each supply lane via MARC.ZZFWD (source depot) and MARC.ZZLANE.
    Returns one row per (item, dest_depot) combination that has a lane assignment.
    """
    sql = f"""
    SELECT
        a.BISMT                                                             AS nsn,
        a.MATKL                                                             AS fsc,
        b.WERKS                                                             AS dest_depot,
        b.ZZFWD                                                             AS source_depot,
        b.ZZLANE                                                            AS lane,
        CAST(c.LABST  AS FLOAT64)                                           AS on_hand,
        CAST(c.UMLME  AS FLOAT64)                                           AS in_transit,
        CAST(b.MINBE  AS FLOAT64)                                           AS reorder_point,
        b.PLIFZ                                                             AS lead_time_days,
        a.ZZDML                                                             AS demand_class,
        CASE
            WHEN CAST(c.LABST AS FLOAT64) = 0
                THEN 'CRITICAL – zero on-hand'
            WHEN CAST(c.LABST AS FLOAT64) < CAST(b.MINBE AS FLOAT64)
                 AND a.ZZSLC = '1'
                THEN 'HIGH – below ROP, single-source'
            WHEN CAST(c.LABST AS FLOAT64) < CAST(b.MINBE AS FLOAT64)
                THEN 'MEDIUM – below ROP'
            ELSE 'OK'
        END                                                                 AS anomaly
    FROM `{project}.{dataset}.mara` a
    JOIN `{project}.{dataset}.marc` b
        ON  a.MANDT = b.MANDT AND a.MATNR = b.MATNR
    JOIN `{project}.{dataset}.mard` c
        ON  b.MANDT = c.MANDT AND b.MATNR = c.MATNR AND b.WERKS = c.WERKS
    WHERE b.ZZLANE IS NOT NULL
      AND b.ZZFWD  IS NOT NULL
      AND a.ZZDML IN ('A', 'B')
    """
    return [dict(row) for row in client.query(sql).result()]


def _aggregate_by_depot(rows: list[dict]) -> dict:
    depot_data: dict = {}
    for row in rows:
        d = row["depot"]
        if d not in depot_data:
            depot_data[d] = {"worst_severity": "OK", "anomaly_count": 0, "items": []}
        sev = row["anomaly"]
        cur = depot_data[d]["worst_severity"]
        if SEVERITY_ORDER.get(sev, 99) < SEVERITY_ORDER.get(cur, 99):
            depot_data[d]["worst_severity"] = sev
        if sev != "OK":
            depot_data[d]["anomaly_count"] += 1
        depot_data[d]["items"].append(row)
    return depot_data


def _build_lane_metadata(lane_rows: list[dict]) -> list[dict]:
    """
    Build per-lane metadata: worst severity, equipment categories, item count,
    total in-transit quantity.
    """
    # Index by (source_depot, dest_depot)
    lane_index: dict = {}
    for row in lane_rows:
        key = (row["source_depot"], row["dest_depot"])
        if key not in lane_index:
            lane_index[key] = []
        lane_index[key].append(row)

    lanes = []
    for origin, dest, lane_name, color in SUPPLY_LANES:
        key = (origin, dest)
        items = lane_index.get(key, [])

        # Worst severity across items on this lane
        worst = "OK"
        for item in items:
            sev = item["anomaly"]
            if SEVERITY_ORDER.get(sev, 99) < SEVERITY_ORDER.get(worst, 99):
                worst = sev

        # Unique equipment categories (FSC → name), ordered by severity
        seen_fsc: set = set()
        equipment: list[str] = []
        for item in sorted(items, key=lambda i: SEVERITY_ORDER.get(i["anomaly"], 99)):
            fsc = item["fsc"]
            if fsc not in seen_fsc:
                seen_fsc.add(fsc)
                equipment.append(FSC_NAMES.get(fsc, f"FSC {fsc}"))

        # In-transit totals
        total_in_transit = sum(i["in_transit"] for i in items)

        lanes.append({
            "origin":           origin,
            "destination":      dest,
            "lane":             lane_name,
            "color":            color,
            "worst_severity":   worst,
            "item_count":       len(items),
            "total_in_transit": total_in_transit,
            "equipment":        equipment,          # ordered list of category names
            "items":            items,
            "origin_coords":    [DEPOT_LOCATIONS[origin]["lng"], DEPOT_LOCATIONS[origin]["lat"]],
            "dest_coords":      [DEPOT_LOCATIONS[dest]["lng"],   DEPOT_LOCATIONS[dest]["lat"]],
        })

    return lanes


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/depot-status")
async def get_depot_status():
    """
    GeoJSON FeatureCollection (one point per depot) + enriched lane metadata.
    Lane metadata includes equipment categories and per-lane anomaly severity.
    Credentials are read server-side only — never exposed to the browser.
    """
    client, project, dataset = _get_bq_client()

    # Run both queries in sequence (BigQuery client is synchronous)
    all_items  = _query_all_items(client, project, dataset)
    lane_items = _query_lane_items(client, project, dataset)

    depot_data = _aggregate_by_depot(all_items)
    lanes      = _build_lane_metadata(lane_items)

    features = []
    for code, loc in DEPOT_LOCATIONS.items():
        data = depot_data.get(code, {"worst_severity": "OK", "anomaly_count": 0, "items": []})
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [loc["lng"], loc["lat"]]},
            "properties": {
                "code":           code,
                "name":           loc["name"],
                "role":           loc["role"],
                "worst_severity": data["worst_severity"],
                "anomaly_count":  data["anomaly_count"],
                "items":          data["items"],
            },
        })

    return {
        "type":     "FeatureCollection",
        "features": features,
        "lanes":    lanes,
    }


@router.get("/anomalies")
async def get_anomalies(
    depot: Optional[str] = None,
    nsn:   Optional[str] = None,
):
    """Anomalous items (at/below reorder point), optionally filtered by depot or NSN."""
    client, project, dataset = _get_bq_client()
    rows = _query_all_items(client, project, dataset)
    rows = [r for r in rows if r["anomaly"] != "OK"]
    if depot:
        rows = [r for r in rows if r["depot"] == depot.upper()]
    if nsn:
        rows = [r for r in rows if nsn.lower() in r["nsn"].lower()]
    return {"anomalies": rows, "count": len(rows)}
