"""
State-mutation functions (executors).

Every executor takes the *master* GameState and mutates it in-place.
Executors trust that the caller (the engine) has already validated the action;
they do not re-validate beyond what is needed to execute safely.
"""

from __future__ import annotations

from random import Random
from typing import Dict, List, Optional

from catan.engine.longest_road import compute_longest_road
from catan.engine.validator import DEV_CARD_COST, ROAD_COST, SETTLEMENT_COST, CITY_COST
from catan.models.actions import PlayDevCard
from catan.models.board import Building
from catan.models.enums import BuildingType, DevCardType, ResourceType
from catan.models.state import GameState


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _deduct_resources(player, cost: Dict[ResourceType, int]) -> None:
    for res, amt in cost.items():
        player.resources[res] -= amt
        player.resource_count -= amt


def _add_resources(player, gain: Dict[ResourceType, int]) -> None:
    for res, amt in gain.items():
        player.resources[res] = player.resources.get(res, 0) + amt
        player.resource_count += amt


# ---------------------------------------------------------------------------
# Resource distribution
# ---------------------------------------------------------------------------

def distribute_resources(state: GameState, roll: int) -> None:
    """Give resources to all players whose settlements/cities border a hex
    that matches *roll*, excluding the hex occupied by the robber."""
    for hex_ in state.board.hexes.values():
        if hex_.number != roll:
            continue
        if hex_.hex_id == state.board.robber_hex_id:
            continue
        for vid in hex_.vertex_ids:
            vertex = state.board.vertices[vid]
            if vertex.building is None:
                continue
            player = state.players[vertex.building.player_id]
            amount = 1 if vertex.building.building_type == BuildingType.SETTLEMENT else 2
            player.resources[hex_.resource] = player.resources.get(hex_.resource, 0) + amount
            player.resource_count += amount


# ---------------------------------------------------------------------------
# Setup phase
# ---------------------------------------------------------------------------

def execute_setup_settlement(state: GameState, player_id: int, vertex_id: int) -> None:
    """Place an initial settlement (no resource cost; does not trigger VP bonuses)."""
    state.board.vertices[vertex_id].building = Building(
        player_id=player_id, building_type=BuildingType.SETTLEMENT
    )
    player = state.players[player_id]
    player.settlements_remaining -= 1
    player.public_vp += 1


def execute_setup_road(state: GameState, player_id: int, edge_id: int) -> None:
    """Place an initial road (no resource cost)."""
    state.board.edges[edge_id].road_owner = player_id
    state.players[player_id].roads_remaining -= 1


def give_setup_resources(state: GameState, player_id: int, vertex_id: int) -> None:
    """Grant one resource card per adjacent non-desert hex (second placement only)."""
    vertex = state.board.vertices[vertex_id]
    player = state.players[player_id]
    for hid in vertex.adjacent_hex_ids:
        hex_ = state.board.hexes[hid]
        if hex_.resource != ResourceType.DESERT:
            player.resources[hex_.resource] = player.resources.get(hex_.resource, 0) + 1
            player.resource_count += 1


# ---------------------------------------------------------------------------
# Robber
# ---------------------------------------------------------------------------

def execute_move_robber(
    state: GameState,
    player_id: int,
    hex_id: int,
    steal_from: Optional[int],
    rng: Random,
) -> None:
    """Move the robber and optionally steal one random card from *steal_from*."""
    state.board.robber_hex_id = hex_id
    if steal_from is not None:
        victim = state.players[steal_from]
        if victim.resource_count > 0:
            pool: List[ResourceType] = [
                r for r, amt in victim.resources.items() for _ in range(amt)
            ]
            stolen = rng.choice(pool)
            victim.resources[stolen] -= 1
            victim.resource_count -= 1
            thief = state.players[player_id]
            thief.resources[stolen] = thief.resources.get(stolen, 0) + 1
            thief.resource_count += 1


# ---------------------------------------------------------------------------
# Discard
# ---------------------------------------------------------------------------

def execute_discard(
    state: GameState, player_id: int, resources: Dict[ResourceType, int]
) -> None:
    """Remove discarded resources from the player's hand."""
    player = state.players[player_id]
    for res, amt in resources.items():
        player.resources[res] -= amt
        player.resource_count -= amt


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def execute_build_road(
    state: GameState, player_id: int, edge_id: int, free: bool = False
) -> None:
    """Place a road.  If *free* is True, do not deduct resources (Road Building card)."""
    player = state.players[player_id]
    if not free:
        _deduct_resources(player, ROAD_COST)
    state.board.edges[edge_id].road_owner = player_id
    player.roads_remaining -= 1
    update_longest_road(state)


def execute_build_settlement(state: GameState, player_id: int, vertex_id: int) -> None:
    """Build a settlement, deducting resources and updating VP."""
    player = state.players[player_id]
    _deduct_resources(player, SETTLEMENT_COST)
    state.board.vertices[vertex_id].building = Building(
        player_id=player_id, building_type=BuildingType.SETTLEMENT
    )
    player.settlements_remaining -= 1
    player.public_vp += 1
    update_longest_road(state)  # new settlement may block an opponent's road


def execute_build_city(state: GameState, player_id: int, vertex_id: int) -> None:
    """Upgrade a settlement to a city, deducting resources and updating VP."""
    player = state.players[player_id]
    _deduct_resources(player, CITY_COST)
    state.board.vertices[vertex_id].building = Building(
        player_id=player_id, building_type=BuildingType.CITY
    )
    player.cities_remaining -= 1
    player.settlements_remaining += 1  # piece returns to supply
    player.public_vp += 1             # settlement was 1 VP, city is 2 VP → net +1
    update_longest_road(state)        # vertex ownership change may affect road continuity


def execute_buy_dev_card(
    state: GameState, player_id: int, dev_deck: List[DevCardType]
) -> None:
    """Draw a dev card from the top of the (engine-private) deck."""
    player = state.players[player_id]
    _deduct_resources(player, DEV_CARD_COST)
    card = dev_deck.pop()
    player.dev_cards.append(card)
    player.dev_cards_count += 1
    state.dev_cards_remaining -= 1
    state.dev_cards_bought_this_turn.append(card)


# ---------------------------------------------------------------------------
# Dev card execution
# ---------------------------------------------------------------------------

def execute_knight(state: GameState, player_id: int) -> None:
    """Remove the Knight card from hand and increment knights_played.

    Robber movement (and the associated steal) must be executed separately
    via ``execute_move_robber``.
    """
    player = state.players[player_id]
    player.dev_cards.remove(DevCardType.KNIGHT)
    player.dev_cards_count -= 1
    player.knights_played += 1
    update_largest_army(state)


def execute_play_dev_card(
    state: GameState, player_id: int, action: PlayDevCard, rng: Random
) -> None:
    """Apply post-roll dev card effects (not Knight, which is pre-roll)."""
    player = state.players[player_id]
    card = action.card
    player.dev_cards.remove(card)
    player.dev_cards_count -= 1

    if card == DevCardType.ROAD_BUILDING:
        road_ids = action.params.get("road_edge_ids", [])
        for eid in road_ids:
            edge = state.board.edges.get(eid)
            if edge and edge.road_owner is None and player.roads_remaining > 0:
                execute_build_road(state, player_id, eid, free=True)

    elif card == DevCardType.YEAR_OF_PLENTY:
        resources = action.params.get("resources", [])
        for res in resources:
            player.resources[res] = player.resources.get(res, 0) + 1
            player.resource_count += 1

    elif card == DevCardType.MONOPOLY:
        resource = action.params.get("resource")
        if resource is not None:
            total = 0
            for other in state.players:
                if other.player_id != player_id:
                    amt = other.resources.get(resource, 0)
                    other.resources[resource] = 0
                    other.resource_count -= amt
                    total += amt
            player.resources[resource] = player.resources.get(resource, 0) + total
            player.resource_count += total

    elif card == DevCardType.VICTORY_POINT:
        # Card is now revealed — counts as public VP
        player.public_vp += 1


# ---------------------------------------------------------------------------
# Trade execution
# ---------------------------------------------------------------------------

def execute_bank_trade(
    state: GameState,
    player_id: int,
    offering: Dict[ResourceType, int],
    requesting: Dict[ResourceType, int],
) -> None:
    """Exchange resources with the (infinite) bank."""
    player = state.players[player_id]
    _deduct_resources(player, offering)
    _add_resources(player, requesting)


def execute_player_trade(
    state: GameState,
    proposer_id: int,
    from_player_id: int,
    offering: Dict[ResourceType, int],
    requesting: Dict[ResourceType, int],
) -> None:
    """Swap resources between two players to complete an accepted trade."""
    proposer = state.players[proposer_id]
    other = state.players[from_player_id]
    _deduct_resources(proposer, offering)
    _add_resources(other, offering)
    _deduct_resources(other, requesting)
    _add_resources(proposer, requesting)


# ---------------------------------------------------------------------------
# Longest road / largest army
# ---------------------------------------------------------------------------

def update_longest_road(state: GameState) -> None:
    """Recompute and (if necessary) transfer the Longest Road marker."""
    lengths = {
        p.player_id: compute_longest_road(state.board, p.player_id)
        for p in state.players
    }
    current = state.longest_road_player

    # Release marker if holder dropped below 5
    if current is not None and lengths[current] < 5:
        state.players[current].has_longest_road = False
        state.players[current].public_vp -= 2
        state.longest_road_player = None
        current = None

    # Threshold that a challenger must strictly exceed
    threshold = lengths[current] if current is not None else 4

    # Find challengers who strictly exceed the threshold (exclude current holder)
    challengers = {
        pid: l for pid, l in lengths.items()
        if pid != current and l > threshold
    }
    if not challengers:
        return

    max_len = max(challengers.values())
    winners = [pid for pid, l in challengers.items() if l == max_len]

    if len(winners) > 1:
        # Tied challengers both exceed current holder — no one claims it;
        # holder (if any) already lost the marker above or will lose it here.
        if current is not None:
            state.players[current].has_longest_road = False
            state.players[current].public_vp -= 2
            state.longest_road_player = None
        return

    new_holder = winners[0]
    if current is not None:
        state.players[current].has_longest_road = False
        state.players[current].public_vp -= 2
    state.players[new_holder].has_longest_road = True
    state.players[new_holder].public_vp += 2
    state.longest_road_player = new_holder


def update_largest_army(state: GameState) -> None:
    """Recompute and (if necessary) transfer the Largest Army marker."""
    current = state.largest_army_player

    # Release marker if holder dropped below 3 (only possible via hypothetical card removal)
    if current is not None and state.players[current].knights_played < 3:
        state.players[current].has_largest_army = False
        state.players[current].public_vp -= 2
        state.largest_army_player = None
        current = None

    threshold = state.players[current].knights_played if current is not None else 2

    challengers = {
        p.player_id: p.knights_played
        for p in state.players
        if p.player_id != current and p.knights_played > threshold
    }
    if not challengers:
        return

    max_knights = max(challengers.values())
    winners = [pid for pid, k in challengers.items() if k == max_knights]

    if len(winners) > 1:
        if current is not None:
            state.players[current].has_largest_army = False
            state.players[current].public_vp -= 2
            state.largest_army_player = None
        return

    new_holder = winners[0]
    if current is not None:
        state.players[current].has_largest_army = False
        state.players[current].public_vp -= 2
    state.players[new_holder].has_largest_army = True
    state.players[new_holder].public_vp += 2
    state.largest_army_player = new_holder


# ---------------------------------------------------------------------------
# Victory points
# ---------------------------------------------------------------------------

def true_vp(state: GameState, player_id: int) -> int:
    """Return the player's total VP, including hidden VP dev cards."""
    player = state.players[player_id]
    hidden_vp = player.dev_cards.count(DevCardType.VICTORY_POINT)
    return player.public_vp + hidden_vp
