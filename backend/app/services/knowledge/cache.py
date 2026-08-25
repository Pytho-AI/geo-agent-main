"""
Unified spatial data cache for map-scoped, bbox-keyed data.

Used by roads, terrain, land cover, route planner, and NL agent
to avoid re-fetching external data (OSM, AWS Terrain Tiles, ESA WorldCover)
when the map viewport hasn't changed significantly.

Usage:
    from app.services.knowledge.cache import spatial_cache

    # Store
    spatial_cache.put("viewport_roads", map_id, bbox, road_network)

    # Retrieve (returns None on miss)
    cached = spatial_cache.get("viewport_roads", map_id, bbox)

    # Clear a namespace for a map
    spatial_cache.clear("viewport_roads", map_id)

    # Clear everything for a map
    spatial_cache.clear_map(map_id)
"""

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SpatialCache:
    """
    Thread-safe, LRU-evicting cache keyed by (namespace, map_id, bbox).

    - **namespace**: data type — "viewport_roads", "viewport_elevation", "viewport_landcover", "location_context", etc.
    - **map_id**: scopes data to a specific map session
    - **bbox**: spatial extent — cache hit requires bbox similarity within tolerance

    Features:
    - TTL (time-to-live) per entry, default 10 minutes
    - Max total entries with LRU eviction
    - bbox fuzzy matching (rounds to configurable precision)
    - Per-map and per-namespace invalidation
    """

    def __init__(
        self,
        max_size: int = 500,
        default_ttl_seconds: float = 600,  # 10 minutes
        bbox_precision: int = 3,           # decimal places for bbox rounding (~111m)
    ):
        self._max_size = max_size
        self._default_ttl = default_ttl_seconds
        self._bbox_precision = bbox_precision
        self._store: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Key generation
    # ------------------------------------------------------------------

    def _bbox_hash(self, bbox: Optional[Tuple | List]) -> str:
        """Hash a bbox rounded to configured precision for fuzzy matching."""
        if bbox is None:
            return "no_bbox"
        rounded = tuple(round(float(v), self._bbox_precision) for v in bbox)
        return hashlib.md5(str(rounded).encode()).hexdigest()[:12]

    def _make_key(self, namespace: str, map_id: str, bbox: Optional[Tuple | List]) -> str:
        """Composite cache key."""
        return f"{namespace}:{map_id}:{self._bbox_hash(bbox)}"

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def get(
        self,
        namespace: str,
        map_id: str,
        bbox: Optional[Tuple | List] = None,
    ) -> Optional[Any]:
        """
        Retrieve cached data. Returns None on miss or expiry.
        Moves entry to end (most-recently-used) on hit.
        """
        key = self._make_key(namespace, str(map_id), bbox)

        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None

            # Check TTL
            if time.time() - entry["created_at"] > entry["ttl"]:
                del self._store[key]
                logger.debug(f"Cache expired: {key}")
                return None

            # Move to end (LRU)
            self._store.move_to_end(key)
            logger.debug(f"Cache hit: {namespace} for map {map_id}")
            return entry["data"]

    def put(
        self,
        namespace: str,
        map_id: str,
        bbox: Optional[Tuple | List],
        data: Any,
        ttl_seconds: Optional[float] = None,
    ) -> None:
        """
        Store data in the cache. Evicts LRU entries if full.
        """
        key = self._make_key(namespace, str(map_id), bbox)
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl

        with self._lock:
            # If key exists, update in place
            if key in self._store:
                self._store[key] = {
                    "data": data,
                    "created_at": time.time(),
                    "ttl": ttl,
                    "namespace": namespace,
                    "map_id": str(map_id),
                }
                self._store.move_to_end(key)
                logger.debug(f"Cache updated: {namespace} for map {map_id}")
                return

            # Evict LRU entries if at capacity
            while len(self._store) >= self._max_size:
                evicted_key, evicted = self._store.popitem(last=False)
                logger.debug(
                    f"Cache evicted (LRU): {evicted['namespace']} for map {evicted['map_id']}"
                )

            self._store[key] = {
                "data": data,
                "created_at": time.time(),
                "ttl": ttl,
                "namespace": namespace,
                "map_id": str(map_id),
            }
            logger.debug(f"Cache stored: {namespace} for map {map_id} (size={len(self._store)})")

    # ------------------------------------------------------------------
    # Invalidation
    # ------------------------------------------------------------------

    def clear(self, namespace: str, map_id: Optional[str] = None) -> int:
        """
        Clear cache entries for a namespace, optionally scoped to a map.
        Returns count of entries removed.
        """
        with self._lock:
            keys_to_remove = [
                k for k, v in self._store.items()
                if v["namespace"] == namespace
                and (map_id is None or v["map_id"] == str(map_id))
            ]
            for k in keys_to_remove:
                del self._store[k]

            if keys_to_remove:
                scope = f"map {map_id}" if map_id else "all maps"
                logger.info(f"Cache cleared: {len(keys_to_remove)} {namespace} entries for {scope}")
            return len(keys_to_remove)

    def clear_map(self, map_id: str) -> int:
        """Clear ALL cached data for a specific map."""
        with self._lock:
            keys_to_remove = [
                k for k, v in self._store.items()
                if v["map_id"] == str(map_id)
            ]
            for k in keys_to_remove:
                del self._store[k]

            if keys_to_remove:
                logger.info(f"Cache cleared: {len(keys_to_remove)} entries for map {map_id}")
            return len(keys_to_remove)

    def clear_all(self) -> int:
        """Clear the entire cache."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            if count:
                logger.info(f"Cache cleared: all {count} entries")
            return count

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Current number of entries."""
        return len(self._store)

    def stats(self) -> Dict[str, Any]:
        """Cache statistics."""
        with self._lock:
            namespaces: Dict[str, int] = {}
            maps: Dict[str, int] = {}
            expired = 0
            now = time.time()

            for entry in self._store.values():
                ns = entry["namespace"]
                mid = entry["map_id"]
                namespaces[ns] = namespaces.get(ns, 0) + 1
                maps[mid] = maps.get(mid, 0) + 1
                if now - entry["created_at"] > entry["ttl"]:
                    expired += 1

            return {
                "total_entries": len(self._store),
                "max_size": self._max_size,
                "expired_entries": expired,
                "by_namespace": namespaces,
                "by_map": maps,
            }


# ---------------------------------------------------------------------------
# Singleton instance — import this everywhere
# ---------------------------------------------------------------------------

spatial_cache = SpatialCache()
