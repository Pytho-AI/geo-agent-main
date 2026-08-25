"""WEM — Weather Effects Matrix — the exemplar planning-weather slide.

2026-07-27 ruling: WEM looks like the best-practice exemplar, full stop
(one 16:9 slide: 5-day / 12-hour-period element grid, aviation-ground
impact codes, warfighting-function GO/M/N codes, legend, source footer).
The prior Fig 4-17 operations XLSX form is superseded.

Division of labor per the writer-involvement law: the element grid is
ENGINE data (Open-Meteo via the live weather branch — including the
direct cloud_base ceiling value); the writer's ONLY judgment is the
impact and warfighting-function codes, emitted one row per call against
the mechanical grid, enum-locked. See templates/__init__.py for the
assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PREPARED_BY,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "WEM",
    "output_format": "pptx",
    "output_formats": ["pptx"],
    "shape": "structured",
    "cadence_hours": 24,
    "doctrine": {
        "purpose": (
            "Step-2 IPOE planning-weather slide: the 5-day forecast "
            "element grid with per-period aviation/ground impact codes "
            "and warfighting-function mission-capability codes. "
            "WEATHER DATA PROVENANCE (mandatory): the element grid and "
            "every code trace to the live forecast snapshot captured at "
            "generation time — header.swo_attribution names the "
            "services and `_provenance` carries the snapshot mark."
        ),
        "ordering_rule": (
            "Fixed slide order: element grid, impact section, "
            "warfighting-functions section, legend, source footer."
        ),
    },
    "consumes_artifacts": [],
    "render": {
        "render_shape": "period_matrix_slide",
        # Cell fill by emitted code; blank code = clean white cell.
        "code_colors": {
            "GO": "70AD47", "M": "FFC000", "N": "FF0000",
            "W": "FFC000", "C": "FFC000", "C/V": "ED7D31",
            "TP": "FFC000",
        },
        "legend": [
            ("GO", "Fully Mission Capable"),
            ("M", "Marginal / PMC"),
            ("N", "NO-GO / NMC"),
            ("W", "Winds Limited"),
            ("C", "Ceiling Limited"),
            ("C/V", "Ceiling & Visibility Limited"),
            ("TP", "Temp / Precip"),
        ],
    },
    "header_fields": {
        "dtg":              HEADER_DTG,
        "area_of_interest": {"source": "session", "view": "header",
                             "required": True,
                             "default": "{area_of_operations}",
                             "render_label": "Area of Interest"},
        "swo_attribution":  {"source": "analytical", "view": "header",
                             "required": True,
                             "provenance_required": True,
                             "render_label": "SWO Source",
                             "depends_on": ["weather"],
                             "guidance": (
                                 "Name the live snapshot exactly — "
                                 "'Open-Meteo + OpenWeatherMap live "
                                 "forecast <DTG>' from the snapshot "
                                 "member's citation. `_provenance` "
                                 "lists the snapshot's ref mark. NEVER "
                                 "invent a product id."
                             )},
        "prepared_by":      HEADER_PREPARED_BY,
        "classification":   HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        {
            "name": "forecast_grid",
            "view": "published",
            "shape": "structured",
            "render_label": "5 Day Planning Weather",
            "required": True,
            "engine_grid": "wem_forecast",
            "depends_on": ["weather"],
            "guidance": (
                "LIVE branch: ENGINE-CONSTRUCTED. AUTHORED branch: "
                "climatology baseline (historical averages) + the "
                "writer's stated-weather overlay with clause marks; "
                "cells neither source covers render NOT STATED — "
                "nothing is ever invented. "
                "winds, min ceiling, min visibility, present weather, "
                "temperature, and wind chill / heat index, straight "
                "from the live forecast grid. No writer involvement."
            ),
        },
        {
            "name": "impact_assessment",
            "view": "published",
            "shape": "structured",
            "render_label": "Aviation / Ground Ops Impact",
            "required": True,
            "depends_on": ["weather", "forecast_grid"],
            "enum_grid": {
                "rows": ["rotary", "fixed_wing", "ground_ops", "uav",
                         "air_medevac"],
                "row_labels": {
                    "rotary": "ROTARY", "fixed_wing": "FIXED WING",
                    "ground_ops": "GROUND OPS", "uav": "UAV",
                    "air_medevac": "AIR MEDEVAC",
                },
                "codes": ["", "W", "C", "C/V", "TP"],
                "code_meanings": {
                    "": "no significant limitation this period",
                    "W": "winds limit the platform/operation",
                    "C": "ceiling limits it",
                    "C/V": "ceiling AND visibility limit it",
                    "TP": "temperature or precipitation limits it",
                },
            },
            "guidance": (
                "Code each period per platform: rotary aviation cares "
                "about ceilings under ~1500 FT, winds over ~30KTS "
                "(gusts count), and visibility under ~3 miles; fixed "
                "wing tolerates more wind but needs ceilings and "
                "visibility for terminal operations; ground ops care "
                "about heavy precipitation (soft ground) and "
                "temperature extremes; UAV (small tactical) is the "
                "most wind- and precipitation-sensitive platform and "
                "loses EO value under low ceilings; air MEDEVAC "
                "follows rotary but with lower risk tolerance — when "
                "rotary is limited, MEDEVAC is at least as limited. "
                "A period with no meaningful limitation gets the "
                "empty code."
            ),
        },
        {
            "name": "wff_assessment",
            "view": "published",
            "shape": "structured",
            "render_label": "Warfighting Functions Assessment",
            "required": True,
            "depends_on": ["weather", "forecast_grid"],
            "enum_grid": {
                "rows": ["c2", "movement_maneuver", "intelligence",
                         "fires", "sustainment", "protection"],
                "row_labels": {
                    "c2": "COMMAND AND CONTROL (C2)",
                    "movement_maneuver": "MOVEMENT AND MANEUVER (M2)",
                    "intelligence": "INTELLIGENCE (INT)",
                    "fires": "FIRES",
                    "sustainment": "SUSTAINMENT (SUST)",
                    "protection": "PROTECTION (PROT)",
                },
                "codes": ["GO", "M", "N"],
                "code_meanings": {
                    "GO": "fully mission capable this period",
                    "M": "marginal / partially mission capable",
                    "N": "not mission capable",
                },
            },
            "guidance": (
                "Code each warfighting function per period from the "
                "forecast: command and control degrades mainly under "
                "severe weather affecting antennas and retrans "
                "movement; movement and maneuver under soaked ground, "
                "fog, and violent weather; intelligence under low "
                "ceilings, fog, and winds that ground collection "
                "platforms; fires under high winds (ballistic "
                "dispersion, observation) and violent weather; "
                "sustainment under conditions that close routes or "
                "ground lift; protection under conditions that degrade "
                "sensors and observation. GO is the default for a "
                "benign period; M when a function is meaningfully "
                "degraded; N only when the forecast effectively "
                "removes the function for that period."
            ),
        },
    ],
    "subtleties": [
        "The element grid is engine data — never restate, never adjust "
        "its values; judge against it.",
        "Impact and warfighting-function codes are PER PERIOD: read "
        "each period's elements, code that period, move on. The same "
        "code repeated across all ten periods is almost always wrong "
        "when the forecast varies.",
    ],
    "hard_rules": [
        "Every emitted code is exactly one of the row's enum codes — "
        "never prose, never a compound outside the enum.",
        "Codes trace to the forecast grid's stated values — never to "
        "an assumed condition.",
        "swo_attribution names the live snapshot with its DTG and "
        "cites the snapshot's ref mark.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Live forecast grid + snapshot: the weather read (live branch)",
    ],
    "post_emit_summary": "artifact_id, worst period identified, "
                         "functions degraded",
}
