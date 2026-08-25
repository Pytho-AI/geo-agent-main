"""WEM exemplar forecast grid — the mechanical 5-day / 12-hour-period
element grid behind the planning-weather slide (2026-07-27 ruling: WEM
looks like the exemplar, full stop).

Source: Open-Meteo (open-meteo.com) — keyless, both a direct cloud_base
variable (the ceiling value OpenWeatherMap's free tier lacks) and every
other exemplar element (winds in knots, visibility, precipitation, WMO
weather codes, temperatures) in one call, with AO-local timestamps via
timezone=auto. The fetch is part of the LIVE weather branch and fails
VISIBLY like the rest of it — never a silent degrade.

Everything here is engine-mechanical: the writer never sees or copies
these values; its only judgment downstream is the impact/WFF codes.
"""
from datetime import datetime
from typing import Any, Optional

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

_HOURLY_VARS = (
    "temperature_2m,dew_point_2m,cloud_cover,cloud_base,visibility,"
    "wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation,"
    "weather_code")

_COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")

# WMO weather codes -> (severity rank, short slide text). Higher rank =
# worse; each period displays its worst hour's text.
_WMO = {
    0: (0, "CLR"), 1: (1, "MSTLY SUNNY"), 2: (2, "PTLY CLOUDY"),
    3: (3, "MSTLY CLOUDY"), 45: (6, "FOG"), 48: (6, "FRZ FOG"),
    51: (4, "DRIZZLE"), 53: (4, "DRIZZLE"), 55: (5, "DRIZZLE"),
    56: (7, "FRZ DRIZZLE"), 57: (7, "FRZ DRIZZLE"),
    61: (5, "LGT RAIN"), 63: (6, "RAIN"), 65: (7, "HVY RAIN"),
    66: (8, "FRZ RAIN"), 67: (8, "FRZ RAIN"),
    71: (6, "LGT SNOW"), 73: (7, "SNOW"), 75: (8, "HVY SNOW"),
    77: (6, "SNOW GRAINS"),
    80: (5, "ISOLD SHWRS"), 81: (6, "SCTD SHWRS"), 82: (7, "HVY SHWRS"),
    85: (6, "SNOW SHWRS"), 86: (7, "SNOW SHWRS"),
    95: (9, "TSTMS"), 96: (10, "TSTMS/HAIL"), 99: (10, "TSTMS/HAIL"),
}


async def fetch_open_meteo(lat: float, lon: float) -> dict:
    import httpx
    params = {
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "hourly": _HOURLY_VARS, "forecast_days": 6,
        "timezone": "auto", "wind_speed_unit": "kn",
    }
    async with httpx.AsyncClient(timeout=25) as client:
        resp = await client.get(OPEN_METEO_URL, params=params)
        resp.raise_for_status()
        return resp.json()


def _compass(deg: float) -> str:
    return _COMPASS[int(((deg % 360) + 11.25) // 22.5) % 16]


def _mode_compass(degs: list) -> str:
    counts: dict[str, int] = {}
    for d in degs:
        c = _compass(d)
        counts[c] = counts.get(c, 0) + 1
    return max(counts, key=lambda k: counts[k])


def _f(c: float) -> int:
    return round(c * 9 / 5 + 32)


def _heat_index_f(t_c: float, rh_estimate: float = 60.0) -> int:
    # Rothfusz regression on the period max; RH approximated when the
    # fetch carries no humidity series (dew point spread would serve,
    # kept simple: the slide cell is advisory).
    t = t_c * 9 / 5 + 32
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh_estimate
          - 0.22475541 * t * rh_estimate - 0.00683783 * t * t
          - 0.05481717 * rh_estimate * rh_estimate
          + 0.00122874 * t * t * rh_estimate
          + 0.00085282 * t * rh_estimate * rh_estimate
          - 0.00000199 * t * t * rh_estimate * rh_estimate)
    return round(hi)


def build_forecast_grid(raw: dict) -> dict:
    """Ten 12-hour local periods (00L-12L night/morning, 12L-00L
    afternoon/evening) from the hourly series, starting at the current
    local period. Element cells match the exemplar's vocabulary."""
    hourly = raw.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        raise RuntimeError("Open-Meteo returned no hourly series")

    def col(name):
        return hourly.get(name) or []

    rows = list(zip(
        times, col("temperature_2m"), col("dew_point_2m"),
        col("cloud_cover"), col("cloud_base"), col("visibility"),
        col("wind_speed_10m"), col("wind_direction_10m"),
        col("wind_gusts_10m"), col("precipitation"),
        col("weather_code")))

    # Group into (date, half) buckets in LOCAL time (the API already
    # returns local timestamps under timezone=auto).
    buckets: dict[tuple, list] = {}
    for r in rows:
        ts = datetime.fromisoformat(r[0])
        half = "a" if ts.hour < 12 else "b"
        buckets.setdefault((ts.date(), half), []).append(r)

    ordered = sorted(buckets.items())
    # Start at the bucket containing the series' first FUTURE-inclusive
    # hour: Open-Meteo's series starts at local midnight today; skip
    # buckets that already fully elapsed relative to the newest stamp
    # we can trust — the caller generates "now", so keep from the
    # current local period onward.
    now_local = datetime.fromisoformat(times[-1]).replace(
        hour=0, minute=0)  # fallback anchor
    try:
        import zoneinfo
        tz = raw.get("timezone")
        if tz:
            now_local = datetime.now(zoneinfo.ZoneInfo(tz)).replace(
                tzinfo=None)
    except Exception:
        pass
    cur_key = (now_local.date(), "a" if now_local.hour < 12 else "b")
    ordered = [x for x in ordered if x[0] >= cur_key][:10]
    if len(ordered) < 10:
        raise RuntimeError(
            f"Open-Meteo series yielded only {len(ordered)} of 10 "
            "forecast periods")

    periods = []
    for (day, half), rs in ordered:
        temps = [r[1] for r in rs if r[1] is not None]
        clouds = [r[3] for r in rs if r[3] is not None]
        bases = [r[4] for r, c in zip(rs, [x[3] for x in rs])
                 if r[4] is not None and (c or 0) >= 50]
        vises = [r[5] for r in rs if r[5] is not None]
        winds = [r[6] for r in rs if r[6] is not None]
        dirs = [r[7] for r in rs if r[7] is not None]
        gusts = [r[8] for r in rs if r[8] is not None]
        codes = [int(r[10]) for r in rs if r[10] is not None]

        sustained = round(max(winds)) if winds else 0
        gust = round(max(gusts)) if gusts else 0
        wind_txt = (f"{_mode_compass(dirs) if dirs else ''} "
                    f"{sustained:02d}"
                    + (f"G{gust:02d}" if gust >= sustained + 5 else "")
                    + "KTS").strip()

        # cloud_base 0 is a no-base sentinel in parts of the series —
        # a real surface-level ceiling reports as a small positive
        # height and displays as BLW 100 FT.
        real_bases = [b for b in bases if b and b > 0]
        if real_bases:
            ceil_ft = int(round(min(real_bases) * 3.28084 / 100.0) * 100)
            ceil_txt = f"{ceil_ft} FT" if ceil_ft >= 100 else "BLW 100 FT"
        else:
            ceil_txt = "NO CIG"

        vis_txt = ""
        if vises:
            vis_mi = min(vises) / 1609.34
            whole = max(1, round(vis_mi))
            if vis_mi >= 0.95:
                vis_txt = f"{whole} MILE" + ("S" if whole != 1 else "")
            else:
                vis_txt = f"{round(vis_mi, 1)} MILES"

        worst = max((_WMO.get(c, (5, f"WX {c}")) for c in codes),
                    default=(0, "CLR"))
        wx_txt = worst[1]

        if half == "b":
            hi_c = max(temps) if temps else None
            temp_txt = (f"HI: {_f(hi_c)}F/{round(hi_c)}C"
                        if hi_c is not None else "")
        else:
            lo_c = min(temps) if temps else None
            temp_txt = (f"LO: {_f(lo_c)}F/{round(lo_c)}C"
                        if lo_c is not None else "")

        index_txt = ""
        if temps and max(temps) >= 27:
            index_txt = f"HI {_heat_index_f(max(temps))}F"
        elif temps and min(temps) <= 5 and sustained >= 5:
            wc = (13.12 + 0.6215 * min(temps)
                  - 11.37 * (sustained * 1.852) ** 0.16
                  + 0.3965 * min(temps) * (sustained * 1.852) ** 0.16)
            index_txt = f"WC {_f(wc)}F"

        periods.append({
            "key": f"{day.isoformat()}-{half}",
            "day_label": day.strftime("%a %d %b %y").upper(),
            "period_label": "00L-12L" if half == "a" else "12L-00L",
            "winds": wind_txt,
            "min_ceiling": ceil_txt,
            "min_visibility": vis_txt,
            "present_weather": wx_txt,
            "temperature": temp_txt,
            "wind_chill_heat_index": index_txt,
            "cloud_cover_max_pct": round(max(clouds)) if clouds else None,
        })

    return {
        "source": "Open-Meteo (open-meteo.com) forecast",
        "timezone": raw.get("timezone"),
        "as_of_local": now_local.strftime("%d%H%ML %b %y").upper(),
        "periods": periods,
    }


ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

_ARCHIVE_VARS = ("temperature_2m,wind_speed_10m,wind_direction_10m,"
                 "wind_gusts_10m,precipitation,cloud_cover")


async def fetch_historical_periods(lat: float, lon: float, anchor,
                                   years: int = 10) -> dict:
    """HISTORICAL AVERAGES per 12-hour period for the anchor's 5-day
    calendar window (2026-07-27 ruling: the authored branch invents
    nothing — what the stated weather doesn't cover comes from
    climatology, and what climatology can't provide says so). Returns
    {(day_offset, half): {winds, temperature, present_weather}} plus a
    source label. The archive carries no visibility or cloud-base
    series — those cells stay for the stated overlay or NOT STATED."""
    import httpx
    from datetime import date, timedelta
    per_year: list[dict] = []
    async with httpx.AsyncClient(timeout=25) as client:
        for back in range(1, years + 1):
            y = anchor.year - back
            try:
                start = anchor.replace(year=y)
            except ValueError:
                continue  # 29 Feb windows skip non-leap years
            end = start + timedelta(days=4)
            resp = await client.get(ARCHIVE_URL, params={
                "latitude": round(lat, 4), "longitude": round(lon, 4),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "hourly": _ARCHIVE_VARS, "timezone": "auto",
                "wind_speed_unit": "kn",
            })
            resp.raise_for_status()
            per_year.append(resp.json())
    if not per_year:
        raise RuntimeError("no archive years returned")

    # bucket[(day_offset, half)] -> accumulators across years
    acc: dict[tuple, dict] = {}
    for raw in per_year:
        hourly = raw.get("hourly") or {}
        times = hourly.get("time") or []
        cols = {v: hourly.get(v) or [] for v in (
            "temperature_2m", "wind_speed_10m", "wind_direction_10m",
            "wind_gusts_10m", "precipitation")}
        if not times:
            continue
        base_day = datetime.fromisoformat(times[0]).date()
        year_buckets: dict[tuple, dict] = {}
        for i, t in enumerate(times):
            ts = datetime.fromisoformat(t)
            key = ((ts.date() - base_day).days,
                   "a" if ts.hour < 12 else "b")
            b = year_buckets.setdefault(key, {
                "temps": [], "winds": [], "gusts": [], "dirs": [],
                "precip": 0.0})
            if cols["temperature_2m"][i] is not None:
                b["temps"].append(cols["temperature_2m"][i])
            if cols["wind_speed_10m"][i] is not None:
                b["winds"].append(cols["wind_speed_10m"][i])
            if cols["wind_gusts_10m"][i] is not None:
                b["gusts"].append(cols["wind_gusts_10m"][i])
            if cols["wind_direction_10m"][i] is not None:
                b["dirs"].append(cols["wind_direction_10m"][i])
            if cols["precipitation"][i] is not None:
                b["precip"] += cols["precipitation"][i]
        for key, b in year_buckets.items():
            a = acc.setdefault(key, {
                "hi": [], "lo": [], "wind_max": [], "gust_max": [],
                "dirs": [], "wet_years": 0, "n_years": 0})
            if b["temps"]:
                a["hi"].append(max(b["temps"]))
                a["lo"].append(min(b["temps"]))
            if b["winds"]:
                a["wind_max"].append(max(b["winds"]))
            if b["gusts"]:
                a["gust_max"].append(max(b["gusts"]))
            a["dirs"].extend(b["dirs"])
            a["n_years"] += 1
            if b["precip"] >= 1.0:
                a["wet_years"] += 1

    out: dict[tuple, dict] = {}
    for key, a in acc.items():
        cell: dict = {}
        if a["wind_max"]:
            spd = round(sum(a["wind_max"]) / len(a["wind_max"]))
            gst = (round(sum(a["gust_max"]) / len(a["gust_max"]))
                   if a["gust_max"] else 0)
            d = _mode_compass(a["dirs"]) if a["dirs"] else ""
            cell["winds"] = (f"{d} {spd:02d}"
                             + (f"G{gst:02d}" if gst >= spd + 5 else "")
                             + "KTS AVG").strip()
        if key[1] == "b" and a["hi"]:
            hi = sum(a["hi"]) / len(a["hi"])
            cell["temperature"] = f"HI: {_f(hi)}F/{round(hi)}C AVG"
        if key[1] == "a" and a["lo"]:
            lo = sum(a["lo"]) / len(a["lo"])
            cell["temperature"] = f"LO: {_f(lo)}F/{round(lo)}C AVG"
        if a["n_years"]:
            frac = a["wet_years"] / a["n_years"]
            if frac >= 0.5:
                cell["present_weather"] = "SHWRS TYPICAL"
            elif frac >= 0.3:
                cell["present_weather"] = "ISOLD SHWRS TYPICAL"
        out[key] = cell
    y0 = anchor.year - years
    y1 = anchor.year - 1
    return {"cells": out,
            "label": f"historical averages {y0}-{y1} "
                     "(Open-Meteo archive)"}


def parse_anchor_date(h_hour: Optional[str]):
    """The exercise anchor date: map attrs store temporal anchors in
    ISO form ("2026-08-11T00:00:00"); stated DTGs also accepted.
    Generation day is the documented fallback when nothing is stated
    (the as_of label carries whichever was used)."""
    from datetime import date
    if h_hour:
        try:
            return datetime.fromisoformat(
                str(h_hour).replace("Z", "+00:00")).date()
        except ValueError:
            pass
        try:
            from app.services.graph_ingest.track import parse_dtg
            parsed = parse_dtg(str(h_hour))
            if parsed is not None:
                return parsed.date()
        except Exception:
            pass
    return date.today()


def build_authored_skeleton(h_hour_dtg: Optional[str],
                            baseline: Optional[dict] = None) -> dict:
    """The AUTHORED-branch grid (2026-07-27 ruling): ten 12-hour
    periods anchored on the exercise H-hour date the project STATES
    (generation day otherwise), pre-filled with the climatology
    baseline where it speaks; every other cell starts empty and, if
    the stated-weather overlay doesn't cover it either, renders
    NOT STATED — nothing is ever invented."""
    from datetime import date, timedelta
    anchor = parse_anchor_date(h_hour_dtg)
    base_cells = (baseline or {}).get("cells") or {}
    periods = []
    for d in range(5):
        day = anchor + timedelta(days=d)
        for half in ("a", "b"):
            cell = base_cells.get((d, half)) or {}
            periods.append({
                "key": f"{day.isoformat()}-{half}",
                "day_label": day.strftime("%a %d %b %y").upper(),
                "period_label": "00L-12L" if half == "a" else "12L-00L",
                "winds": cell.get("winds", ""),
                "min_ceiling": "",
                "min_visibility": "",
                "present_weather": cell.get("present_weather", ""),
                "temperature": cell.get("temperature", ""),
                "wind_chill_heat_index": "",
            })
    return {
        "source": ("stated exercise weather + "
                   + ((baseline or {}).get("label")
                      or "no historical averages available")),
        "timezone": None,
        "as_of_local": anchor.strftime("%d0001L %b %y").upper(),
        "anchor_date": anchor.isoformat(),
        "periods": periods,
    }
