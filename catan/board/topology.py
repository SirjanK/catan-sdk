"""
Pre-computed topology for the standard Catan board.

Hex coordinate system
---------------------
We use **axial (q, r) coordinates** with the "pointy-top" orientation —
the same system described at https://www.redblobgames.com/grids/hexagons/
(see the "Axial coordinates" and "Pointy-top" sections there for diagrams
and derivations; that page is the canonical reference for this codebase).

Key facts about our choice:
- q increases going East; r increases going South-East.
- The center hex is at (0, 0); the board spans radius 2 (19 hexes total).
- Cube coordinates (x, y, z) with x + y + z = 0 underlie the math;
  axial simply drops z = -x - y.
- The 6 axial neighbor offsets (clockwise from NE):
    NE (+1,-1), E (+1,0), SE (0,+1), SW (-1,+1), W (-1,0), NW (0,-1)

Vertex and edge numbering within a hex
---------------------------------------
For a pointy-top hex the 6 corners are numbered **clockwise from the top**:
    corner 0: top        (N)
    corner 1: top-right  (NE)
    corner 2: bottom-right (SE)
    corner 3: bottom     (S)
    corner 4: bottom-left (SW)
    corner 5: top-left   (NW)

Edge k connects corner k to corner (k+1) % 6 and faces the hex neighbor
in the corresponding direction:
    edge 0 (c0–c1): NE face → neighbor (q+1, r-1)
    edge 1 (c1–c2): E  face → neighbor (q+1, r)
    edge 2 (c2–c3): SE face → neighbor (q,   r+1)
    edge 3 (c3–c4): SW face → neighbor (q-1, r+1)
    edge 4 (c4–c5): W  face → neighbor (q-1, r)
    edge 5 (c5–c0): NW face → neighbor (q,   r-1)

Canonical IDs
-------------
Vertex IDs (0–53): assigned by iterating hexes in HEX_COORDS order, then
corners 0–5, allocating a new ID only when the corner hasn't been seen.

Edge IDs (0–71): assigned in encounter order from (min_vertex_id,
max_vertex_id) pairs; each edge is stored exactly once.

All constants are built once at import time and treated as read-only.
"""

from __future__ import annotations
from typing import Dict, List, Set, Tuple
from catan.models.enums import PortType

# ---------------------------------------------------------------------------
# Hex layout
# ---------------------------------------------------------------------------

# (q, r) pairs for all 19 hexes, in stable row-major order.
HEX_COORDS: list[tuple[int, int]] = [
    # r = -2
    (0, -2), (1, -2), (2, -2),
    # r = -1
    (-1, -1), (0, -1), (1, -1), (2, -1),
    # r = 0
    (-2, 0), (-1, 0), (0, 0), (1, 0), (2, 0),
    # r = 1
    (-2, 1), (-1, 1), (0, 1), (1, 1),
    # r = 2
    (-2, 2), (-1, 2), (0, 2),
]

QR_TO_HEX_ID: dict[tuple[int, int], int] = {
    qr: i for i, qr in enumerate(HEX_COORDS)
}
HEX_ID_TO_QR: dict[int, tuple[int, int]] = {
    i: qr for i, qr in enumerate(HEX_COORDS)
}

NUM_HEXES = len(HEX_COORDS)  # 19

# ---------------------------------------------------------------------------
# Vertex computation
#
# Each corner of a hex is shared by at most 3 hexes.  We derive sharing rules
# from the edge→neighbor table above:
#
#   corner 0 of (q,r) == corner 4 of (q+1, r-1)  [NE neighbor]
#                     == corner 2 of (q,   r-1)   [NW neighbor]
#   corner 1 of (q,r) == corner 3 of (q+1, r-1)  [NE neighbor]
#                     == corner 5 of (q+1, r)     [E  neighbor]
#   corner 2 of (q,r) == corner 4 of (q+1, r)    [E  neighbor]
#                     == corner 0 of (q,   r+1)   [SE neighbor]
#   corner 3 of (q,r) == corner 5 of (q,   r+1)  [SE neighbor]
#                     == corner 1 of (q-1, r+1)   [SW neighbor]
#   corner 4 of (q,r) == corner 0 of (q-1, r+1)  [SW neighbor]
#                     == corner 2 of (q-1, r)     [W  neighbor]
#   corner 5 of (q,r) == corner 1 of (q-1, r)    [W  neighbor]
#                     == corner 3 of (q,   r-1)   [NW neighbor]
# ---------------------------------------------------------------------------

# For each corner index: list of (dq, dr, shared_corner) for neighbour hexes
# that share this corner.  Order within each list doesn't matter for
# correctness, but listing the more-likely-to-be-visited hex first is faster.
_CORNER_SHARING: dict[int, list[tuple[int, int, int]]] = {
    0: [(1, -1, 4), (0, -1, 2)],   # NE neighbor c4, NW neighbor c2
    1: [(1, -1, 3), (1,  0, 5)],   # NE neighbor c3, E  neighbor c5
    2: [(1,  0, 4), (0,  1, 0)],   # E  neighbor c4, SE neighbor c0
    3: [(0,  1, 5), (-1, 1, 1)],   # SE neighbor c5, SW neighbor c1
    4: [(-1, 1, 0), (-1, 0, 2)],   # SW neighbor c0, W  neighbor c2
    5: [(-1, 0, 1), (0, -1, 3)],   # W  neighbor c1, NW neighbor c3
}

# (hex_id, corner) -> vertex_id
_hc_to_vid: dict[tuple[int, int], int] = {}
_next_vid = 0


def _get_vertex_id(hex_id: int, corner: int) -> int:
    """Return the canonical vertex ID for (hex_id, corner), creating one if needed."""
    global _next_vid
    key = (hex_id, corner)
    if key in _hc_to_vid:
        return _hc_to_vid[key]

    q, r = HEX_ID_TO_QR[hex_id]
    for dq, dr, shared_corner in _CORNER_SHARING[corner]:
        neighbour_qr = (q + dq, r + dr)
        if neighbour_qr in QR_TO_HEX_ID:
            neighbour_id = QR_TO_HEX_ID[neighbour_qr]
            neighbour_key = (neighbour_id, shared_corner)
            if neighbour_key in _hc_to_vid:
                vid = _hc_to_vid[neighbour_key]
                _hc_to_vid[key] = vid
                return vid

    vid = _next_vid
    _next_vid += 1
    _hc_to_vid[key] = vid
    return vid


# Populate the full mapping in stable order.
for _hid in range(NUM_HEXES):
    for _c in range(6):
        _get_vertex_id(_hid, _c)

NUM_VERTICES: int = _next_vid  # expected: 54

# ---------------------------------------------------------------------------
# Per-hex vertex list (6 vertices clockwise from top)
# ---------------------------------------------------------------------------

HEX_VERTICES: dict[int, list[int]] = {
    hid: [_get_vertex_id(hid, c) for c in range(6)]
    for hid in range(NUM_HEXES)
}

# ---------------------------------------------------------------------------
# Edge computation
# Edge k of a hex connects corner k to corner (k+1) % 6.
# ---------------------------------------------------------------------------

_edge_pair_to_eid: dict[tuple[int, int], int] = {}
_next_eid = 0


def _get_edge_id(vid_a: int, vid_b: int) -> int:
    global _next_eid
    key = (min(vid_a, vid_b), max(vid_a, vid_b))
    if key in _edge_pair_to_eid:
        return _edge_pair_to_eid[key]
    eid = _next_eid
    _next_eid += 1
    _edge_pair_to_eid[key] = eid
    return eid


for _hid in range(NUM_HEXES):
    _verts = HEX_VERTICES[_hid]
    for _k in range(6):
        _get_edge_id(_verts[_k], _verts[(_k + 1) % 6])

NUM_EDGES: int = _next_eid  # expected: 72

HEX_EDGES: dict[int, list[int]] = {
    hid: [
        _get_edge_id(HEX_VERTICES[hid][k], HEX_VERTICES[hid][(k + 1) % 6])
        for k in range(6)
    ]
    for hid in range(NUM_HEXES)
}

# Edge endpoints (canonical: va < vb)
EDGE_VERTICES: dict[int, tuple[int, int]] = {
    eid: pair for pair, eid in _edge_pair_to_eid.items()
}

# ---------------------------------------------------------------------------
# Vertex adjacency
# ---------------------------------------------------------------------------

_vertex_adj_verts: dict[int, set[int]] = {v: set() for v in range(NUM_VERTICES)}
for (va, vb) in _edge_pair_to_eid:
    _vertex_adj_verts[va].add(vb)
    _vertex_adj_verts[vb].add(va)

VERTEX_ADJACENT_VERTICES: dict[int, list[int]] = {
    v: sorted(s) for v, s in _vertex_adj_verts.items()
}

_vertex_adj_edges: dict[int, set[int]] = {v: set() for v in range(NUM_VERTICES)}
for (va, vb), eid in _edge_pair_to_eid.items():
    _vertex_adj_edges[va].add(eid)
    _vertex_adj_edges[vb].add(eid)

VERTEX_ADJACENT_EDGES: dict[int, list[int]] = {
    v: sorted(s) for v, s in _vertex_adj_edges.items()
}

_vertex_adj_hexes: dict[int, set[int]] = {v: set() for v in range(NUM_VERTICES)}
for hid, verts in HEX_VERTICES.items():
    for v in verts:
        _vertex_adj_hexes[v].add(hid)

VERTEX_ADJACENT_HEXES: dict[int, list[int]] = {
    v: sorted(s) for v, s in _vertex_adj_hexes.items()
}

# ---------------------------------------------------------------------------
# Edge adjacency
# ---------------------------------------------------------------------------

_edge_adj_edges: dict[int, set[int]] = {e: set() for e in range(NUM_EDGES)}
for v in range(NUM_VERTICES):
    incident = VERTEX_ADJACENT_EDGES[v]
    for ea in incident:
        for eb in incident:
            if ea != eb:
                _edge_adj_edges[ea].add(eb)

EDGE_ADJACENT_EDGES: dict[int, list[int]] = {
    e: sorted(s) for e, s in _edge_adj_edges.items()
}

# ---------------------------------------------------------------------------
# Hex adjacency
# ---------------------------------------------------------------------------

_hex_adj_hexes: dict[int, set[int]] = {h: set() for h in range(NUM_HEXES)}
for h1 in range(NUM_HEXES):
    for h2 in range(h1 + 1, NUM_HEXES):
        if len(set(HEX_VERTICES[h1]) & set(HEX_VERTICES[h2])) == 2:
            _hex_adj_hexes[h1].add(h2)
            _hex_adj_hexes[h2].add(h1)

HEX_ADJACENT_HEXES: dict[int, list[int]] = {
    h: sorted(s) for h, s in _hex_adj_hexes.items()
}

# ---------------------------------------------------------------------------
# Perimeter detection
# ---------------------------------------------------------------------------

_edge_hex_count: dict[int, int] = {e: 0 for e in range(NUM_EDGES)}
for hid, edges in HEX_EDGES.items():
    for e in edges:
        _edge_hex_count[e] += 1

PERIMETER_EDGES: set[int] = {e for e, cnt in _edge_hex_count.items() if cnt == 1}

PERIMETER_VERTICES: set[int] = {
    v for v, hexes in VERTEX_ADJACENT_HEXES.items() if len(hexes) < 3
}

# ---------------------------------------------------------------------------
# Port positions
#
# 9 ports: 4 generic 3:1, 5 special 2:1 (one per resource).
# Each port occupies one outward-facing (perimeter) edge of a border hex.
# We hard-code the 9 positions as (qr, edge_index) pairs so the vertex IDs
# are derived from the topology rather than hard-coded.
# ---------------------------------------------------------------------------

_PORT_SPEC: list[tuple[tuple[int, int], int, PortType]] = [
    ((-2, 2), 3, PortType.BRICK_2_1),    # Hex 1,  NW face
    ((-1, 2), 2, PortType.GENERIC_3_1),  # Hex 2,  NE face
    ((1, 1), 2, PortType.ORE_2_1),      # Hex 4,  NE face
    ((2, 0), 1, PortType.GENERIC_3_1),  # Hex 5,  E  face
    ((2,  -1), 0, PortType.WHEAT_2_1),    # Hex 6,  SE face
    ((1,  -2), 0, PortType.GENERIC_3_1),  # Hex 8,  SE face
    ((0, -2), 5, PortType.SHEEP_2_1),    # Hex 9,  SW face
    ((-1, -1), 4, PortType.GENERIC_3_1),  # Hex 10, W  face
    ((-2, 1), 4, PortType.WOOD_2_1),     # Hex 12, W  face
]


def _build_port_assignments() -> List[Tuple[PortType, int, int]]:
    assignments: List[Tuple[PortType, int, int]] = []
    for (q, r), edge_idx, port_type in _PORT_SPEC:
        hex_id = QR_TO_HEX_ID[(q, r)]
        va = HEX_VERTICES[hex_id][edge_idx]
        vb = HEX_VERTICES[hex_id][(edge_idx + 1) % 6]
        # Sanity: both vertices must be on the perimeter.
        assert va in PERIMETER_VERTICES, f"Port vertex {va} not on perimeter"
        assert vb in PERIMETER_VERTICES, f"Port vertex {vb} not on perimeter"
        assignments.append((port_type, va, vb))
    return assignments


PORT_ASSIGNMENTS: List[Tuple[PortType, int, int]] = _build_port_assignments()
PORT_VERTEX_PAIRS: List[Tuple[int, int]] = [(va, vb) for _, va, vb in PORT_ASSIGNMENTS]
PORT_TYPES_CLOCKWISE: List[PortType] = [pt for pt, _, _ in PORT_ASSIGNMENTS]
