"""
catan.players.helpers — public board utilities for bot development.

These functions are thin, read-only wrappers around common board queries that
come up repeatedly when writing Catan bots.  Import them directly in your
submission to avoid duplicating the same logic.

Example usage::

    from catan.players.helpers import (
        vertex_pip_score,
        owned_resource_types,
        valid_settlement_spots,
        has_resources,
    )
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from catan.engine.validator import (
    _distance_rule_ok,
    _road_connects_to_player,
    _settlement_connects_to_road,
)
from catan.models.board import Board
from catan.models.enums import BuildingType, ResourceType
from catan.models.state import PlayerState

# Probability-weight (pip count) for each number token
PIPS: Dict[int, int] = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 8: 5, 9: 4, 10: 3, 11: 2, 12: 1}


# ---------------------------------------------------------------------------
# Vertex queries
# ---------------------------------------------------------------------------


def vertex_pip_score(board: Board, vertex_id: int) -> int:
    """Return the total pip count of all non-desert hexes adjacent to *vertex_id*.

    This is the standard setup-placement metric: higher means more rolls produce
    resources at this vertex.

    Example::

        score = vertex_pip_score(state.board, vid)
    """
    total = 0
    for hid in board.vertices[vertex_id].adjacent_hex_ids:
        h = board.hexes[hid]
        if h.number is not None:
            total += PIPS.get(h.number, 0)
    return total


def vertex_resource_types(board: Board, vertex_id: int) -> Set[ResourceType]:
    """Return the set of non-DESERT resource types produced at *vertex_id*.

    Useful for diversity calculations during setup placement.
    """
    return {
        board.hexes[hid].resource
        for hid in board.vertices[vertex_id].adjacent_hex_ids
        if board.hexes[hid].resource != ResourceType.DESERT
    }


def owned_resource_types(board: Board, player_id: int) -> Set[ResourceType]:
    """Return all resource types currently produced by *player_id*'s buildings."""
    result: Set[ResourceType] = set()
    for v in board.vertices.values():
        if v.building and v.building.player_id == player_id:
            result |= vertex_resource_types(board, v.vertex_id)
    return result


# ---------------------------------------------------------------------------
# Reachability / placement checks
# ---------------------------------------------------------------------------


def valid_settlement_spots(board: Board, player_id: int) -> List[int]:
    """Return vertex IDs where *player_id* can legally place a settlement now.

    A valid spot is: empty, passes the distance rule, and is adjacent to at
    least one of the player's roads.

    Performance note: this function scans the full board on every call
    (O(|vertices|)).  If you call it multiple times in a single ``take_turn``
    invocation, cache the result in a local variable::

        spots = valid_settlement_spots(state.board, self.player_id)
        if spots:
            best = max(spots, key=lambda v: vertex_pip_score(state.board, v))
    """
    return [
        vid
        for vid, v in board.vertices.items()
        if v.building is None
        and _distance_rule_ok(board, vid)
        and _settlement_connects_to_road(board, player_id, vid)
    ]


def valid_road_edges(board: Board, player_id: int) -> List[int]:
    """Return edge IDs where *player_id* can legally place a road now.

    Performance note: scans the full board on every call (O(|edges|)).
    Cache the result locally if calling multiple times in one turn.
    """
    return [
        eid
        for eid, e in board.edges.items()
        if e.road_owner is None and _road_connects_to_player(board, player_id, eid)
    ]


def best_city_vertex(board: Board, player_id: int) -> Optional[int]:
    """Return the vertex_id of the most productive settlement to upgrade to a city.

    Picks the settlement with the highest pip score.  Returns None if the
    player has no settlements to upgrade.
    """
    best_score, best_vid = -1, None
    for vid, v in board.vertices.items():
        if (
            v.building
            and v.building.player_id == player_id
            and v.building.building_type == BuildingType.SETTLEMENT
        ):
            score = vertex_pip_score(board, vid)
            if score > best_score:
                best_score, best_vid = score, vid
    return best_vid


# ---------------------------------------------------------------------------
# Resource checks
# ---------------------------------------------------------------------------


def has_resources(player: PlayerState, cost: Dict[ResourceType, int]) -> bool:
    """Return True if *player* holds at least the resources specified in *cost*."""
    return all(player.resources.get(r, 0) >= amt for r, amt in cost.items())


def resource_deficit(
    player: PlayerState, cost: Dict[ResourceType, int]
) -> Dict[ResourceType, int]:
    """Return the resources the player still needs to afford *cost*.

    Keys with a deficit of 0 are omitted.  Example::

        deficit = resource_deficit(player, CITY_COST)
        # → {ResourceType.ORE: 2}  if player has 1 ore out of the 3 needed
    """
    return {
        r: amt - player.resources.get(r, 0)
        for r, amt in cost.items()
        if player.resources.get(r, 0) < amt
    }
