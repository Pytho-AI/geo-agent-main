"""Contraction hierarchy over the corridor road graph.

Roads do not move, so a corridor's routing structure is PREPROCESSED
ONCE: nodes are contracted in importance order (lazy edge-difference),
witness searches decide which shortcuts preserve shortest paths, and
queries run as a bidirectional upward Dijkstra over the hierarchy —
milliseconds against graphs where a flat search grinds. The built
hierarchy persists to the data volume keyed by the corridor's tile-set
signature; the second request for the same corridor never preprocesses
again (same law as the peaks and road-tile stores).
"""
import heapq
import json
import logging
import os
import sqlite3
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("app.routing.ch")

Key = Tuple[int, int]

_CH_STORE = None


def _ch_store():
    global _CH_STORE
    if _CH_STORE is None:
        try:
            base = os.environ.get("GEO_DATA_DIR", "/app/data")
            os.makedirs(base, exist_ok=True)
            conn = sqlite3.connect(os.path.join(base, "ch_store.sqlite"),
                                   check_same_thread=False)
            conn.execute("CREATE TABLE IF NOT EXISTS hierarchies ("
                         "signature TEXT PRIMARY KEY, payload TEXT)")
            conn.commit()
            _CH_STORE = conn
        except Exception as exc:
            log.warning("CH store unavailable (%s)", exc)
            _CH_STORE = False
    return _CH_STORE or None


class ContractionHierarchy:
    """Preprocessed hierarchy. `up[u]` holds (v, cost, middle) edges to
    HIGHER-order nodes only; `middle` is the contracted node a shortcut
    bypasses (None for original edges) — unpacking recurses through it.
    """

    def __init__(self, nodes: Dict[Key, Tuple[float, float]],
                 order: Dict[Key, int],
                 up: Dict[Key, List[Tuple[Key, float, Optional[Key]]]]):
        self.nodes = nodes
        self.order = order
        self.up = up

    # ── preprocessing ────────────────────────────────────────────────

    @classmethod
    def build(cls, nodes: Dict[Key, Tuple[float, float]],
              adj: Dict[Key, List[Tuple[Key, float]]]
              ) -> "ContractionHierarchy":
        # Working graph as dict-of-dicts (min parallel edge wins).
        g: Dict[Key, Dict[Key, Tuple[float, Optional[Key]]]] = {}
        for u, edges in adj.items():
            gu = g.setdefault(u, {})
            for v, c in edges:
                if v not in gu or c < gu[v][0]:
                    gu[v] = (c, None)
                g.setdefault(v, {})
        for n in nodes:
            g.setdefault(n, {})

        def witness_limited(src: Key, targets: set, avoid: Key,
                            cutoff: float) -> Dict[Key, float]:
            """Dijkstra from src avoiding `avoid`, stopping past cutoff
            or once all targets are settled. Hop-limited for speed."""
            dist = {src: 0.0}
            q = [(0.0, 0, src)]
            found: Dict[Key, float] = {}
            while q:
                d, hops, u = heapq.heappop(q)
                if d > cutoff or hops > 60:
                    continue
                if u in targets:
                    found[u] = d
                    if len(found) == len(targets):
                        break
                if d > dist.get(u, float("inf")):
                    continue
                for v, (c, _m) in g.get(u, {}).items():
                    if v == avoid:
                        continue
                    nd = d + c
                    if nd < dist.get(v, float("inf")):
                        dist[v] = nd
                        heapq.heappush(q, (nd, hops + 1, v))
            return found

        def edge_difference(v: Key) -> int:
            neigh = list(g.get(v, {}).items())
            shortcuts = 0
            for i, (u, (cu, _)) in enumerate(neigh):
                targets = {w for w, _ in neigh[i + 1:]}
                if not targets:
                    continue
                cutoff = cu + max(cw for w, (cw, _) in neigh[i + 1:])
                wit = witness_limited(u, targets, v, cutoff)
                for w, (cw, _) in neigh[i + 1:]:
                    if wit.get(w, float("inf")) > cu + cw:
                        shortcuts += 1
            return shortcuts - len(neigh)

        # Lazy-order priority queue.
        pq = [(edge_difference(v), v) for v in g]
        heapq.heapify(pq)
        order: Dict[Key, int] = {}
        up: Dict[Key, List[Tuple[Key, float, Optional[Key]]]] = {
            n: [] for n in g}
        rank = 0
        while pq:
            prio, v = heapq.heappop(pq)
            if v in order:
                continue
            new_prio = edge_difference(v)
            if pq and new_prio > pq[0][0]:
                heapq.heappush(pq, (new_prio, v))
                continue
            order[v] = rank
            rank += 1
            neigh = [(u, cu) for u, (cu, _) in g.get(v, {}).items()
                     if u not in order]
            # Shortcuts among still-uncontracted neighbors.
            for i, (u, cu) in enumerate(neigh):
                targets = {w for w, _ in neigh[i + 1:]}
                if not targets:
                    continue
                cutoff = cu + max(cw for _, cw in neigh[i + 1:])
                wit = witness_limited(u, targets, v, cutoff)
                for w, cw in neigh[i + 1:]:
                    through = cu + cw
                    if wit.get(w, float("inf")) > through:
                        gu = g.setdefault(u, {})
                        gw = g.setdefault(w, {})
                        if w not in gu or through < gu[w][0]:
                            gu[w] = (through, v)
                            gw[u] = (through, v)
            # Freeze v's edges into the upward structure and remove v.
            for u, (cu, mid) in g.get(v, {}).items():
                if u in order:
                    continue
                up[v].append((u, cu, mid))
            for u in list(g.get(v, {})):
                g[u].pop(v, None)
            g.pop(v, None)
        # Edges from lower- to higher-order side only.
        final_up: Dict[Key, List[Tuple[Key, float, Optional[Key]]]] = {}
        for v, edges in up.items():
            keep = [(u, c, m) for u, c, m in edges
                    if order.get(u, -1) > order.get(v, -1)]
            if keep:
                final_up[v] = keep
        return cls(nodes, order, final_up)

    # ── query ────────────────────────────────────────────────────────

    def _upward_search(self, src: Key) -> Dict[Key, Tuple[float,
                                                          Optional[Key]]]:
        dist: Dict[Key, Tuple[float, Optional[Key]]] = {src: (0.0, None)}
        q = [(0.0, src)]
        while q:
            d, u = heapq.heappop(q)
            if d > dist.get(u, (float("inf"), None))[0]:
                continue
            for v, c, _m in self.up.get(u, []):
                nd = d + c
                if nd < dist.get(v, (float("inf"), None))[0]:
                    dist[v] = (nd, u)
                    heapq.heappush(q, (nd, v))
        return dist

    def _shortcut_middle(self, u: Key, v: Key) -> Optional[Key]:
        for w, _c, m in self.up.get(u, []):
            if w == v:
                return m
        for w, _c, m in self.up.get(v, []):
            if w == u:
                return m
        return None

    def _unpack(self, u: Key, v: Key, out: List[Key]) -> None:
        mid = self._shortcut_middle(u, v)
        if mid is None:
            out.append(v)
            return
        self._unpack(u, mid, out)
        self._unpack(mid, v, out)

    def query(self, s: Key, t: Key) -> Optional[List[Tuple[float, float]]]:
        if s not in self.order or t not in self.order:
            return None
        fwd = self._upward_search(s)
        bwd = self._upward_search(t)
        best, meet = float("inf"), None
        for n, (d, _p) in fwd.items():
            bd = bwd.get(n)
            if bd is not None and d + bd[0] < best:
                best, meet = d + bd[0], n
        if meet is None:
            return None

        def chain(dist, end):
            path = [end]
            while dist[path[-1]][1] is not None:
                path.append(dist[path[-1]][1])
            return list(reversed(path))

        up_path = chain(fwd, meet)            # s .. meet (rising)
        down_path = list(reversed(chain(bwd, meet)))  # meet .. t
        keys: List[Key] = [up_path[0]]
        for a, b in zip(up_path, up_path[1:]):
            self._unpack(a, b, keys)
        for a, b in zip(down_path, down_path[1:]):
            self._unpack(a, b, keys)
        return [self.nodes[k] for k in keys]

    # ── persistence ──────────────────────────────────────────────────

    def dump(self) -> str:
        return json.dumps({
            "nodes": [[k[0], k[1], p[0], p[1]]
                      for k, p in self.nodes.items()],
            "order": [[k[0], k[1], r] for k, r in self.order.items()],
            "up": [[k[0], k[1],
                    [[v[0], v[1], c, (m[0] if m else None),
                      (m[1] if m else None)] for v, c, m in edges]]
                   for k, edges in self.up.items()],
        })

    @classmethod
    def load(cls, payload: str) -> "ContractionHierarchy":
        d = json.loads(payload)
        nodes = {(a, b): (x, y) for a, b, x, y in d["nodes"]}
        order = {(a, b): r for a, b, r in d["order"]}
        up = {}
        for a, b, edges in d["up"]:
            up[(a, b)] = [((va, vb), c,
                           ((ma, mb) if ma is not None else None))
                          for va, vb, c, ma, mb in edges]
        return cls(nodes, order, up)


_LOADED: Dict[str, ContractionHierarchy] = {}
_LOADED_MAX = 16


def load_hierarchy(signature: str) -> Optional[ContractionHierarchy]:
    hit = _LOADED.get(signature)
    if hit is not None:
        return hit
    conn = _ch_store()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT payload FROM hierarchies WHERE signature=?",
            (signature,)).fetchone()
        if not row:
            return None
        ch = ContractionHierarchy.load(row[0])
        if len(_LOADED) >= _LOADED_MAX:
            _LOADED.clear()
        _LOADED[signature] = ch
        return ch
    except Exception:
        return None


def store_hierarchy(signature: str, ch: ContractionHierarchy) -> None:
    conn = _ch_store()
    if conn is None:
        return
    try:
        if len(_LOADED) >= _LOADED_MAX:
            _LOADED.clear()
        _LOADED[signature] = ch
        conn.execute(
            "INSERT OR REPLACE INTO hierarchies (signature, payload) "
            "VALUES (?, ?)", (signature, ch.dump()))
        conn.commit()
    except Exception as exc:
        log.debug("CH store write failed: %s", exc)
