"""
Board factory: create_board(randomize=True) -> Board

Produces a fully-wired Board with randomized hex resource/number placement
subject to standard Catan constraints (6 and 8 tiles not adjacent).
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional

from catan.models.enums import ResourceType, PortType
from catan.models.board import Hex, Vertex, Edge, Board
from catan.board.topology import (
    HEX_COORDS,
    HEX_VERTICES,
    HEX_EDGES,
    EDGE_VERTICES,
    VERTEX_ADJACENT_VERTICES,
    VERTEX_ADJACENT_EDGES,
    VERTEX_ADJACENT_HEXES,
    EDGE_ADJACENT_EDGES,
    HEX_ADJACENT_HEXES,
    PORT_ASSIGNMENTS,
    NUM_HEXES,
    NUM_VERTICES,
    NUM_EDGES,
)

# ---------------------------------------------------------------------------
# Resource and number tile pools (standard Catan)
# ---------------------------------------------------------------------------

_RESOURCE_POOL: List[ResourceType] = (
    [ResourceType.WHEAT] * 4
    + [ResourceType.SHEEP] * 4
    + [ResourceType.WOOD] * 4
    + [ResourceType.BRICK] * 3
    + [ResourceType.ORE] * 3
    + [ResourceType.DESERT] * 1
)

# 18 number tokens (one per non-desert hex), listed in ascending order.
_NUMBER_POOL: List[int] = [
    2,
    3, 3,
    4, 4,
    5, 5,
    6, 6,
    8, 8,
    9, 9,
    10, 10,
    11, 11,
    12,
]

# 6 and 8 are the "red" (high-probability) numbers.  Standard Catan rules
# forbid placing two of them on adjacent hexes to prevent any single
# intersection from being adjacent to two high-frequency tiles.
_HOT_NUMBERS: frozenset = frozenset({6, 8})


def _shuffle_resources(rng: random.Random) -> List[ResourceType]:
    """Return a shuffled resource list (DESERT always valid anywhere)."""
    pool = _RESOURCE_POOL.copy()
    rng.shuffle(pool)
    return pool


def _shuffle_numbers(
    resources: List[ResourceType],
    rng: random.Random,
    max_attempts: int = 10_000,
) -> Optional[List[Optional[int]]]:
    """
    Assign number tokens to non-desert hexes such that no two adjacent hexes
    both have 6 or 8.  Returns a list parallel to resources with None for the
    desert, or None if no valid assignment is found within max_attempts.
    """
    desert_idx = resources.index(ResourceType.DESERT)
    non_desert_indices = [i for i in range(NUM_HEXES) if i != desert_idx]

    numbers_pool = _NUMBER_POOL.copy()

    for _ in range(max_attempts):
        rng.shuffle(numbers_pool)
        assignment: List[Optional[int]] = [None] * NUM_HEXES
        for idx, num in zip(non_desert_indices, numbers_pool):
            assignment[idx] = num

        # Validate 6/8 adjacency constraint
        valid = True
        for hid in range(NUM_HEXES):
            if assignment[hid] in _HOT_NUMBERS:
                for neighbour in HEX_ADJACENT_HEXES[hid]:
                    if assignment[neighbour] in _HOT_NUMBERS:
                        valid = False
                        break
            if not valid:
                break

        if valid:
            return assignment

    return None  # pragma: no cover — extremely unlikely with standard pool


# ---------------------------------------------------------------------------
# create_board
# ---------------------------------------------------------------------------

def create_board(randomize: bool = True, seed: Optional[int] = None) -> Board:
    """
    Build and return a standard Catan Board.

    Parameters
    ----------
    randomize:
        If True (default), shuffle resources and numbers following standard
        rules (6/8 non-adjacent).  If False, use a fixed canonical layout
        (useful for deterministic tests).
    seed:
        Optional RNG seed for reproducible randomization.
    """
    rng = random.Random(seed)

    if randomize:
        resources = _shuffle_resources(rng)
        numbers = _shuffle_numbers(resources, rng)
        if numbers is None:
            raise RuntimeError("Failed to generate a valid board layout")  # pragma: no cover
    else:
        # Fixed canonical layout: resources in pool order, numbers in token order
        resources = _RESOURCE_POOL.copy()
        desert_idx = resources.index(ResourceType.DESERT)
        non_desert_indices = [i for i in range(NUM_HEXES) if i != desert_idx]
        numbers: List[Optional[int]] = [None] * NUM_HEXES
        for idx, num in zip(non_desert_indices, _NUMBER_POOL):
            numbers[idx] = num

    # Build Hex objects
    hexes: Dict[int, Hex] = {}
    desert_hex_id = -1
    for hid, (q, r) in enumerate(HEX_COORDS):
        resource = resources[hid]
        if resource == ResourceType.DESERT:
            desert_hex_id = hid
        hexes[hid] = Hex(
            hex_id=hid,
            q=q,
            r=r,
            resource=resource,
            number=numbers[hid],
            vertex_ids=HEX_VERTICES[hid],
            edge_ids=HEX_EDGES[hid],
        )

    # Build port lookup: vertex_id -> PortType
    # The 9 port slots (vertex pairs) are fixed by board topology, but the
    # port *types* are shuffled across those slots when randomize=True.
    port_types = [pt for pt, _, _ in PORT_ASSIGNMENTS]
    port_pairs = [(va, vb) for _, va, vb in PORT_ASSIGNMENTS]
    if randomize:
        rng.shuffle(port_types)
    vertex_port: Dict[int, PortType] = {}
    for port_type, (va, vb) in zip(port_types, port_pairs):
        vertex_port[va] = port_type
        vertex_port[vb] = port_type

    # Build Vertex objects
    vertices: Dict[int, Vertex] = {}
    for vid in range(NUM_VERTICES):
        vertices[vid] = Vertex(
            vertex_id=vid,
            adjacent_hex_ids=VERTEX_ADJACENT_HEXES[vid],
            adjacent_edge_ids=VERTEX_ADJACENT_EDGES[vid],
            adjacent_vertex_ids=VERTEX_ADJACENT_VERTICES[vid],
            port=vertex_port.get(vid),
            building=None,
        )

    # Build Edge objects
    edges: Dict[int, Edge] = {}
    for eid in range(NUM_EDGES):
        edges[eid] = Edge(
            edge_id=eid,
            vertex_ids=EDGE_VERTICES[eid],
            adjacent_edge_ids=EDGE_ADJACENT_EDGES[eid],
            road_owner=None,
        )

    return Board(
        hexes=hexes,
        vertices=vertices,
        edges=edges,
        robber_hex_id=desert_hex_id,
    )
