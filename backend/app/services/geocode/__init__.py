"""Geocoding from geo-agent's OWN planet data — no external gazetteer.

A geospatial agent already carries the whole planet: the basemap vector
tiles have a `places` layer (countries, cities, towns, villages) with
`name`, `name:en`, `population`, and `min_zoom` (a built-in importance
rank). This module decodes that layer server-side to resolve a place
NAME to coordinates, exactly the way api/v1/terrain.py decodes the
`pois` layer for spot-height peaks.

The caller almost always passes an AREA OF OPERATIONS bbox. That bbox is
a HARD geographic prior: we decode only the tiles inside it, so a name
that matches nothing in the AO simply does not resolve (stays unplaced)
and a same-named place on another continent never appears. No model call
is needed to reject out-of-AO candidates — geography does it.
"""

from app.services.geocode.service import (
    GeocodeCandidate,
    geocode,
    haversine_km,
    reverse_geocode,
)

__all__ = ["geocode", "reverse_geocode", "haversine_km", "GeocodeCandidate"]
