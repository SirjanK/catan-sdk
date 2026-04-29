"""
Pure validation functions.  Every function returns (is_valid: bool, reason: str).
Validators never mutate state.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from catan.models.actions import (
    AcceptTrade,
    BankTrade,
    Build,
    City,
    DevCard,
    DiscardCards,
    MoveRobber,
    Pass,
    PlayDevCard,
    PlayKnight,
    PlaceRoad,
    PlaceSettlement,
    ProposeTrade,
    RejectAllTrades,
    RespondToTrade,
    Road,
    RollDice,
    Settlement,
)
from catan.models.board import Board
from catan.models.enums import BuildingType, DevCardType, GamePhase, PortType, ResourceType
from catan.models.state import GameState

# ---------------------------------------------------------------------------
# Building costs
# ---------------------------------------------------------------------------

ROAD_COST: Dict[ResourceType, int] = {
    ResourceType.WOOD: 1,
    ResourceType.BRICK: 1,
}
SETTLEMENT_COST: Dict[ResourceType, int] = {
    ResourceType.WOOD: 1,
    ResourceType.BRICK: 1,
    ResourceType.WHEAT: 1,
    ResourceType.SHEEP: 1,
}
CITY_COST: Dict[ResourceType, int] = {
    ResourceType.WHEAT: 2,
    ResourceType.ORE: 3,
}
DEV_CARD_COST: Dict[ResourceType, int] = {
    ResourceType.ORE: 1,
    ResourceType.WHEAT: 1,
    ResourceType.SHEEP: 1,
}

# ---------------------------------------------------------------------------
# Port trade ratio lookup
# ---------------------------------------------------------------------------

_RESOURCE_TO_PORT: Dict[ResourceType, PortType] = {
    ResourceType.WOOD: PortType.WOOD_2_1,
    ResourceType.BRICK: PortType.BRICK_2_1,
    ResourceType.WHEAT: PortType.WHEAT_2_1,
    ResourceType.ORE: PortType.ORE_2_1,
    ResourceType.SHEEP: PortType.SHEEP_2_1,
}


def get_port_ratio(board: Board, player_id: int, resource: ResourceType) -> int:
    """Return the best available bank-trade ratio for *resource* for *player_id*.

    Returns 2 if the player has a matching 2:1 port, 3 for a generic 3:1
    port, or 4 (the default) if they have no applicable port.
    """
    specific = _RESOURCE_TO_PORT.get(resource)
    best = 4
    for v in board.vertices.values():
        if v.building and v.building.player_id == player_id and v.port:
            if v.port == specific:
                return 2
            if v.port == PortType.GENERIC_3_1:
                best = min(best, 3)
    return best


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_turn(
    state: GameState, player_id: int, expected_phase: GamePhase
) -> Tuple[bool, str]:
    """Check that it is the expected phase and the correct player's turn."""
    if state.phase != expected_phase:
        return False, f"Phase is {state.phase}, expected {expected_phase.name}"
    if player_id != state.current_player_id:
        return False, "Not your turn"
    return True, ""


def _check_exists(mapping: Any, id_: int, label: str) -> Tuple[bool, str]:
    """Return (False, error) if *id_* is absent from *mapping*, else (True, '')."""
    if id_ not in mapping:
        return False, f"{label} {id_} does not exist"
    return True, ""


def _has_resources(player_resources: Dict[ResourceType, int],
                   cost: Dict[ResourceType, int]) -> bool:
    return all(player_resources.get(r, 0) >= amt for r, amt in cost.items())


def _road_connects_to_player(
    board: Board,
    player_id: int,
    edge_id: int,
    extra_owned_edges: frozenset = frozenset(),
) -> bool:
    """True if placing a road on edge_id would be connected to player's network.

    *extra_owned_edges* may include edge IDs not yet written to the board that
    should be treated as if owned by *player_id* (used when validating the
    second road of a Road Building card, where the first road is logically
    placed but the board has not been mutated yet).
    """
    edge = board.edges[edge_id]
    for vid in edge.vertex_ids:
        v = board.vertices[vid]
        # A building owned by the player at this vertex is a valid anchor
        if v.building and v.building.player_id == player_id:
            return True
        # An adjacent road owned by the player (at this vertex, different edge)
        for adj_eid in v.adjacent_edge_ids:
            if adj_eid == edge_id:
                continue
            is_player_road = (
                board.edges[adj_eid].road_owner == player_id
                or adj_eid in extra_owned_edges
            )
            if is_player_road:
                # Only valid if no opponent building blocks the connection
                if v.building is None or v.building.player_id == player_id:
                    return True
    return False


def _settlement_connects_to_road(board: Board, player_id: int, vertex_id: int) -> bool:
    """True if vertex_id is adjacent to at least one road owned by player_id."""
    v = board.vertices[vertex_id]
    return any(board.edges[eid].road_owner == player_id
               for eid in v.adjacent_edge_ids)


def _distance_rule_ok(board: Board, vertex_id: int) -> bool:
    """True if no adjacent vertex has a building (distance rule)."""
    return all(board.vertices[adj].building is None
               for adj in board.vertices[vertex_id].adjacent_vertex_ids)

# ---------------------------------------------------------------------------
# Setup-phase validators
# ---------------------------------------------------------------------------

def validate_setup_settlement(
    board: Board, player_id: int, action: PlaceSettlement
) -> Tuple[bool, str]:
    vid = action.vertex_id
    ok, reason = _check_exists(board.vertices, vid, "Vertex")
    if not ok:
        return ok, reason
    if board.vertices[vid].building is not None:
        return False, "Vertex is already occupied"
    if not _distance_rule_ok(board, vid):
        return False, "Distance rule: adjacent vertex already has a building"
    return True, ""


def validate_setup_road(
    board: Board, player_id: int, settlement_vertex_id: int, action: PlaceRoad
) -> Tuple[bool, str]:
    eid = action.edge_id
    ok, reason = _check_exists(board.edges, eid, "Edge")
    if not ok:
        return ok, reason
    if board.edges[eid].road_owner is not None:
        return False, "Edge already has a road"
    if settlement_vertex_id not in board.edges[eid].vertex_ids:
        return False, "Road must be adjacent to the settlement just placed"
    return True, ""

# ---------------------------------------------------------------------------
# Pre-roll validator
# ---------------------------------------------------------------------------

def validate_pre_roll(
    state: GameState,
    player_id: int,
    action: Any,
    has_played_dev_card: bool,
) -> Tuple[bool, str]:
    ok, reason = _validate_turn(state, player_id, GamePhase.PRE_ROLL)
    if not ok:
        return ok, reason

    if isinstance(action, RollDice):
        return True, ""

    if isinstance(action, PlayKnight):
        if has_played_dev_card:
            return False, "Already played a dev card this turn"
        if DevCardType.KNIGHT not in state.players[player_id].dev_cards:
            return False, "No Knight card in hand"
        # Validate the robber move embedded in the action
        return _validate_robber_move(state, player_id, action.target_hex_id,
                                     action.steal_from_player_id)

    return False, f"Invalid action type for PRE_ROLL: {type(action).__name__}"

# ---------------------------------------------------------------------------
# Move-robber validator (standalone; also used for PlayKnight)
# ---------------------------------------------------------------------------

def validate_move_robber(
    state: GameState, player_id: int, action: MoveRobber
) -> Tuple[bool, str]:
    ok, reason = _validate_turn(state, player_id, GamePhase.MOVING_ROBBER)
    if not ok:
        return ok, reason
    return _validate_robber_move(state, player_id, action.hex_id,
                                 action.steal_from_player_id)


def _validate_robber_move(
    state: GameState, player_id: int, hex_id: int,
    steal_from: int | None
) -> Tuple[bool, str]:
    ok, reason = _check_exists(state.board.hexes, hex_id, "Hex")
    if not ok:
        return ok, reason
    if hex_id == state.board.robber_hex_id:
        return False, "Robber must move to a different hex"
    if steal_from is not None:
        if steal_from == player_id:
            return False, "Cannot steal from yourself"
        # steal_from must have a building on the target hex
        target_hex = state.board.hexes[hex_id]
        players_on_hex = {
            state.board.vertices[vid].building.player_id
            for vid in target_hex.vertex_ids
            if state.board.vertices[vid].building is not None
            and state.board.vertices[vid].building.player_id != player_id
        }
        if steal_from not in players_on_hex:
            return False, "steal_from player has no building on that hex"
    return True, ""

# ---------------------------------------------------------------------------
# Discard validator
# ---------------------------------------------------------------------------

def validate_discard(
    state: GameState, player_id: int, action: DiscardCards, required_count: int
) -> Tuple[bool, str]:
    total = sum(action.resources.values())
    if total != required_count:
        return False, f"Must discard exactly {required_count} cards, got {total}"
    player = state.players[player_id]
    for res, amt in action.resources.items():
        if amt < 0:
            return False, f"Negative amount for {res}"
        if player.resources.get(res, 0) < amt:
            return False, f"Not enough {res} to discard"
    return True, ""

# ---------------------------------------------------------------------------
# Post-roll validator
# ---------------------------------------------------------------------------

def validate_post_roll(
    state: GameState,
    player_id: int,
    action: Any,
    has_played_dev_card: bool,
) -> Tuple[bool, str]:
    ok, reason = _validate_turn(state, player_id, GamePhase.POST_ROLL)
    if not ok:
        return ok, reason

    player = state.players[player_id]
    board = state.board

    # --- Pass ---
    if isinstance(action, Pass):
        return True, ""

    # --- Build ---
    if isinstance(action, Build):
        return _validate_build(board, player, player_id, action, state)

    # --- Play dev card ---
    if isinstance(action, PlayDevCard):
        return _validate_play_dev_card(player, action, has_played_dev_card, state)

    # --- Trade ---
    if isinstance(action, ProposeTrade):
        return _validate_propose_trade(state, player_id, action)

    if isinstance(action, AcceptTrade):
        return _validate_accept_trade(state, player_id, action)

    if isinstance(action, RejectAllTrades):
        return True, ""

    # --- Bank trade ---
    if isinstance(action, BankTrade):
        return _validate_bank_trade(state, player_id, action)

    return False, f"Invalid action type for POST_ROLL: {type(action).__name__}"


def _validate_build(
    board: Board, player, player_id: int, action: Build, state: GameState
) -> Tuple[bool, str]:
    target = action.target

    if isinstance(target, Road):
        if not _has_resources(player.resources, ROAD_COST):
            return False, "Not enough resources for road (need 1 WOOD + 1 BRICK)"
        if player.roads_remaining <= 0:
            return False, "No road pieces remaining"
        eid = target.edge_id
        ok, reason = _check_exists(board.edges, eid, "Edge")
        if not ok:
            return ok, reason
        if board.edges[eid].road_owner is not None:
            return False, "Edge already has a road"
        if not _road_connects_to_player(board, player_id, eid):
            return False, "Road must connect to your existing roads or buildings"
        return True, ""

    if isinstance(target, Settlement):
        if not _has_resources(player.resources, SETTLEMENT_COST):
            return False, "Not enough resources for settlement (need 1 each WOOD/BRICK/WHEAT/SHEEP)"
        if player.settlements_remaining <= 0:
            return False, "No settlement pieces remaining"
        vid = target.vertex_id
        ok, reason = _check_exists(board.vertices, vid, "Vertex")
        if not ok:
            return ok, reason
        if board.vertices[vid].building is not None:
            return False, "Vertex is already occupied"
        if not _distance_rule_ok(board, vid):
            return False, "Distance rule: adjacent vertex already has a building"
        if not _settlement_connects_to_road(board, player_id, vid):
            return False, "Settlement must be adjacent to your road"
        return True, ""

    if isinstance(target, City):
        if not _has_resources(player.resources, CITY_COST):
            return False, "Not enough resources for city (need 2 WHEAT + 3 ORE)"
        if player.cities_remaining <= 0:
            return False, "No city pieces remaining"
        vid = target.vertex_id
        ok, reason = _check_exists(board.vertices, vid, "Vertex")
        if not ok:
            return ok, reason
        v = board.vertices[vid]
        if (v.building is None
                or v.building.player_id != player_id
                or v.building.building_type != BuildingType.SETTLEMENT):
            return False, "Must upgrade your own settlement to a city"
        return True, ""

    if isinstance(target, DevCard):
        if not _has_resources(player.resources, DEV_CARD_COST):
            return False, "Not enough resources for dev card (need 1 ORE/WHEAT/SHEEP)"
        if state.dev_cards_remaining <= 0:
            return False, "Dev card deck is empty"
        return True, ""

    return False, "Unknown build target"


def _validate_play_dev_card(
    player, action: PlayDevCard, has_played_dev_card: bool, state: GameState
) -> Tuple[bool, str]:
    card = action.card
    # VP cards can be revealed at any time; all others: one per turn
    if card != DevCardType.VICTORY_POINT and has_played_dev_card:
        return False, "Already played a dev card this turn"
    if card not in player.dev_cards:
        return False, f"You do not have a {card} card"
    if card == DevCardType.KNIGHT:
        return False, "Knight must be played before rolling (use pre-roll action)"

    # Cannot play a dev card purchased this turn (VP cards are exempt — they
    # are revealed as points and carry no active effect).
    if card != DevCardType.VICTORY_POINT:
        bought_this_turn = state.dev_cards_bought_this_turn
        bought_of_type = bought_this_turn.count(card)
        in_hand = player.dev_cards.count(card)
        # pre_existing = copies held before any purchase this turn
        pre_existing = in_hand - bought_of_type
        if pre_existing <= 0:
            return False, "Cannot play a development card purchased this turn"

    if card == DevCardType.ROAD_BUILDING:
        road_ids = action.params.get("road_edge_ids", [])
        if not isinstance(road_ids, list) or len(road_ids) > 2:
            return False, "road_edge_ids must be a list of at most 2 edge IDs"
        if len(road_ids) != len(set(road_ids)):
            return False, "road_edge_ids contains duplicate edge IDs"
        if len(road_ids) > player.roads_remaining:
            return False, "Not enough road pieces remaining"
        # Validate each road: exists, unoccupied, connected to player's network.
        # The second road may connect to the first (not yet on the board).
        extra: frozenset = frozenset()
        for eid in road_ids:
            ok, reason = _check_exists(state.board.edges, eid, "Edge")
            if not ok:
                return ok, reason
            if state.board.edges[eid].road_owner is not None:
                return False, f"Edge {eid} already has a road"
            if not _road_connects_to_player(state.board, player.player_id, eid, extra):
                return False, (
                    f"Road on edge {eid} must connect to your existing roads or buildings"
                )
            extra = extra | {eid}
        return True, ""

    if card == DevCardType.YEAR_OF_PLENTY:
        resources = action.params.get("resources", [])
        if not isinstance(resources, list) or len(resources) != 2:
            return False, "Year of Plenty requires exactly 2 resources in params['resources']"
        return True, ""
    if card == DevCardType.MONOPOLY:
        resource = action.params.get("resource")
        if resource is None:
            return False, "Monopoly requires params['resource']"
        return True, ""
    if card == DevCardType.VICTORY_POINT:
        return True, ""
    return False, f"Unknown dev card: {card}"


def _validate_propose_trade(
    state: GameState, player_id: int, action: ProposeTrade
) -> Tuple[bool, str]:
    if state.trades_proposed_this_turn >= 3:
        return False, "Trade limit reached (max 3 per turn)"
    if not action.offering:
        return False, "Trade offering is empty"
    if not action.requesting:
        return False, "Trade requesting is empty"
    player = state.players[player_id]
    for res, amt in action.offering.items():
        if amt <= 0:
            return False, f"Offering amount for {res} must be positive"
        if player.resources.get(res, 0) < amt:
            return False, f"Not enough {res} to offer"
    for amt in action.requesting.values():
        if amt <= 0:
            return False, "Requesting amount must be positive"
    return True, ""


def _validate_bank_trade(
    state: GameState, player_id: int, action: BankTrade
) -> Tuple[bool, str]:
    if len(action.offering) != 1 or len(action.requesting) != 1:
        return False, "Bank trade must offer exactly one resource type and request exactly one"
    offered_res, offered_amt = next(iter(action.offering.items()))
    requested_res, requested_amt = next(iter(action.requesting.items()))
    if offered_res == ResourceType.DESERT or requested_res == ResourceType.DESERT:
        return False, "Cannot trade the desert pseudo-resource"
    if offered_res == requested_res:
        return False, "Cannot trade a resource for itself"
    if offered_amt <= 0:
        return False, "Offering amount must be positive"
    if requested_amt != 1:
        return False, "Must request exactly 1 resource per bank trade"
    player = state.players[player_id]
    if player.resources.get(offered_res, 0) < offered_amt:
        return False, f"Not enough {offered_res} to offer"
    required = get_port_ratio(state.board, player_id, offered_res)
    if offered_amt != required:
        return False, f"Trade ratio for {offered_res} is {required}:1, not {offered_amt}:1"
    return True, ""


def _validate_accept_trade(
    state: GameState, player_id: int, action: AcceptTrade
) -> Tuple[bool, str]:
    proposal = next(
        (p for p in state.pending_trades if p.proposal_id == action.proposal_id),
        None,
    )
    if proposal is None:
        return False, f"No pending trade with proposal_id={action.proposal_id}"
    if proposal.proposing_player_id != player_id:
        return False, "You are not the proposer of this trade"
    if not proposal.responses.get(action.from_player_id, False):
        return False, "That player has not accepted the trade"
    # Verify both parties still have the resources
    from_player = state.players[action.from_player_id]
    for res, amt in proposal.requesting.items():
        if from_player.resources.get(res, 0) < amt:
            return False, f"Accepting player no longer has enough {res}"
    proposer = state.players[player_id]
    for res, amt in proposal.offering.items():
        if proposer.resources.get(res, 0) < amt:
            return False, f"Proposer no longer has enough {res}"
    return True, ""
