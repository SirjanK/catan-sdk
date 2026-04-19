"""
Unit tests for catan.engine.executor.

Each test class covers one or two closely related executor functions.
Tests use a deterministic board (randomize=False) for reproducibility.
"""

from __future__ import annotations

from random import Random

import pytest

from catan.board.setup import create_board
from catan.engine.executor import (
    distribute_resources,
    execute_bank_trade,
    execute_build_city,
    execute_build_road,
    execute_build_settlement,
    execute_buy_dev_card,
    execute_discard,
    execute_knight,
    execute_move_robber,
    execute_play_dev_card,
    execute_player_trade,
    execute_setup_road,
    execute_setup_settlement,
    give_setup_resources,
    true_vp,
    update_largest_army,
    update_longest_road,
)
from catan.models.actions import PlayDevCard
from catan.models.board import Building
from catan.models.enums import BuildingType, DevCardType, GamePhase, ResourceType
from catan.models.state import GameState, PlayerState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_player(pid: int, **kwargs) -> PlayerState:
    defaults = dict(
        player_id=pid,
        resources={r: 0 for r in ResourceType if r != ResourceType.DESERT},
        dev_cards=[],
        dev_cards_count=0,
        resource_count=0,
        knights_played=0,
        roads_remaining=15,
        settlements_remaining=5,
        cities_remaining=4,
        public_vp=0,
        has_longest_road=False,
        has_largest_army=False,
    )
    defaults.update(kwargs)
    return PlayerState(**defaults)


def _make_state(**kwargs) -> GameState:
    board = create_board(randomize=False)
    players = [_make_player(i) for i in range(4)]
    defaults = dict(
        board=board,
        players=players,
        current_player_id=0,
        phase=GamePhase.PRE_ROLL,
        turn_number=1,
        dice=None,
        pending_trades=[],
        trades_proposed_this_turn=0,
        dev_cards_remaining=25,
        longest_road_player=None,
        largest_army_player=None,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


# ---------------------------------------------------------------------------
# distribute_resources
# ---------------------------------------------------------------------------

class TestDistributeResources:
    def _state_with_settlement(self, vertex_id: int, pid: int = 0) -> GameState:
        state = _make_state()
        state.board.vertices[vertex_id].building = Building(
            player_id=pid, building_type=BuildingType.SETTLEMENT
        )
        return state

    def test_settlement_gets_one_card(self):
        state = _make_state()
        # Find a non-desert hex with a number token
        target_hex = next(
            h for h in state.board.hexes.values()
            if h.number is not None and h.hex_id != state.board.robber_hex_id
        )
        vid = target_hex.vertex_ids[0]
        state.board.vertices[vid].building = Building(
            player_id=0, building_type=BuildingType.SETTLEMENT
        )
        before = state.players[0].resources.get(target_hex.resource, 0)
        distribute_resources(state, target_hex.number)
        assert state.players[0].resources[target_hex.resource] == before + 1
        assert state.players[0].resource_count == 1

    def test_city_gets_two_cards(self):
        state = _make_state()
        target_hex = next(
            h for h in state.board.hexes.values()
            if h.number is not None and h.hex_id != state.board.robber_hex_id
        )
        vid = target_hex.vertex_ids[0]
        state.board.vertices[vid].building = Building(
            player_id=0, building_type=BuildingType.CITY
        )
        distribute_resources(state, target_hex.number)
        assert state.players[0].resources[target_hex.resource] == 2
        assert state.players[0].resource_count == 2

    def test_robber_hex_blocked(self):
        state = _make_state()
        robber_hex = state.board.hexes[state.board.robber_hex_id]
        # Give robber hex a number so it would produce if unblocked.
        # (On canonical board the desert has no number; use a different hex.)
        # Find any numbered hex and move robber there.
        numbered_hex = next(
            h for h in state.board.hexes.values() if h.number is not None
        )
        state.board.robber_hex_id = numbered_hex.hex_id
        vid = numbered_hex.vertex_ids[0]
        state.board.vertices[vid].building = Building(
            player_id=0, building_type=BuildingType.SETTLEMENT
        )
        distribute_resources(state, numbered_hex.number)
        assert state.players[0].resource_count == 0

    def test_no_matching_number_gives_nothing(self):
        state = _make_state()
        distribute_resources(state, 7)   # 7 never appears as a token
        for p in state.players:
            assert p.resource_count == 0


# ---------------------------------------------------------------------------
# execute_setup_settlement / road / give_setup_resources
# ---------------------------------------------------------------------------

class TestSetupExecutors:
    def test_setup_settlement_places_building(self):
        state = _make_state()
        execute_setup_settlement(state, 0, 5)
        assert state.board.vertices[5].building.player_id == 0
        assert state.board.vertices[5].building.building_type == BuildingType.SETTLEMENT
        assert state.players[0].settlements_remaining == 4
        assert state.players[0].public_vp == 1

    def test_setup_road_places_road(self):
        state = _make_state()
        execute_setup_settlement(state, 0, 0)
        eid = state.board.vertices[0].adjacent_edge_ids[0]
        execute_setup_road(state, 0, eid)
        assert state.board.edges[eid].road_owner == 0
        assert state.players[0].roads_remaining == 14

    def test_give_setup_resources_grants_adjacent(self):
        state = _make_state()
        vid = 0
        execute_setup_settlement(state, 0, vid)
        before = state.players[0].resource_count
        give_setup_resources(state, 0, vid)
        # Should receive one card per adjacent non-desert hex
        vertex = state.board.vertices[vid]
        expected = sum(
            1 for hid in vertex.adjacent_hex_ids
            if state.board.hexes[hid].resource != ResourceType.DESERT
        )
        assert state.players[0].resource_count == before + expected


# ---------------------------------------------------------------------------
# execute_move_robber
# ---------------------------------------------------------------------------

class TestExecuteMoveRobber:
    def test_robber_moves(self):
        state = _make_state()
        old_hex = state.board.robber_hex_id
        new_hex = next(h for h in state.board.hexes if h != old_hex)
        execute_move_robber(state, 0, new_hex, None, Random(0))
        assert state.board.robber_hex_id == new_hex

    def test_steal_removes_card_from_victim(self):
        state = _make_state()
        state.players[1].resources[ResourceType.WOOD] = 3
        state.players[1].resource_count = 3
        new_hex = next(h for h in state.board.hexes if h != state.board.robber_hex_id)
        execute_move_robber(state, 0, new_hex, 1, Random(0))
        assert state.players[1].resource_count == 2
        assert state.players[0].resource_count == 1

    def test_steal_from_empty_hand_no_change(self):
        state = _make_state()
        # Victim has no resources
        new_hex = next(h for h in state.board.hexes if h != state.board.robber_hex_id)
        execute_move_robber(state, 0, new_hex, 1, Random(0))
        assert state.players[0].resource_count == 0
        assert state.players[1].resource_count == 0


# ---------------------------------------------------------------------------
# execute_discard
# ---------------------------------------------------------------------------

class TestExecuteDiscard:
    def test_removes_resources(self):
        state = _make_state()
        state.players[0].resources[ResourceType.WOOD] = 5
        state.players[0].resource_count = 5
        execute_discard(state, 0, {ResourceType.WOOD: 3})
        assert state.players[0].resources[ResourceType.WOOD] == 2
        assert state.players[0].resource_count == 2


# ---------------------------------------------------------------------------
# execute_build_road / settlement / city
# ---------------------------------------------------------------------------

class TestBuildExecutors:
    def _state_with_road_resources(self) -> GameState:
        state = _make_state()
        state.players[0].resources[ResourceType.WOOD] = 1
        state.players[0].resources[ResourceType.BRICK] = 1
        state.players[0].resource_count = 2
        # Place a settlement to anchor the road
        state.board.vertices[0].building = Building(
            player_id=0, building_type=BuildingType.SETTLEMENT
        )
        return state

    def test_build_road_deducts_resources(self):
        state = self._state_with_road_resources()
        eid = state.board.vertices[0].adjacent_edge_ids[0]
        execute_build_road(state, 0, eid)
        assert state.players[0].resources[ResourceType.WOOD] == 0
        assert state.players[0].resources[ResourceType.BRICK] == 0
        assert state.board.edges[eid].road_owner == 0
        assert state.players[0].roads_remaining == 14

    def test_build_road_free(self):
        state = _make_state()
        state.board.vertices[0].building = Building(
            player_id=0, building_type=BuildingType.SETTLEMENT
        )
        eid = state.board.vertices[0].adjacent_edge_ids[0]
        execute_build_road(state, 0, eid, free=True)
        assert state.players[0].resource_count == 0  # no resources deducted
        assert state.board.edges[eid].road_owner == 0

    def test_build_settlement_deducts_and_grants_vp(self):
        state = _make_state()
        state.players[0].resources.update(
            {ResourceType.WOOD: 1, ResourceType.BRICK: 1,
             ResourceType.WHEAT: 1, ResourceType.SHEEP: 1}
        )
        state.players[0].resource_count = 4
        # Place a road so the settlement can connect
        v0 = state.board.vertices[0]
        eid = v0.adjacent_edge_ids[0]
        state.board.edges[eid].road_owner = 0
        # Target vertex = the other end of that edge
        edge = state.board.edges[eid]
        target_vid = edge.vertex_ids[0] if edge.vertex_ids[1] == 0 else edge.vertex_ids[1]
        execute_build_settlement(state, 0, target_vid)
        assert state.players[0].resource_count == 0
        assert state.players[0].public_vp == 1
        assert state.players[0].settlements_remaining == 4

    def test_build_city_replaces_settlement(self):
        state = _make_state()
        state.players[0].resources.update({ResourceType.WHEAT: 2, ResourceType.ORE: 3})
        state.players[0].resource_count = 5
        state.board.vertices[0].building = Building(
            player_id=0, building_type=BuildingType.SETTLEMENT
        )
        state.players[0].public_vp = 1  # settlement was already placed
        execute_build_city(state, 0, 0)
        assert state.board.vertices[0].building.building_type == BuildingType.CITY
        assert state.players[0].public_vp == 2
        assert state.players[0].cities_remaining == 3
        assert state.players[0].settlements_remaining == 6  # piece returned


# ---------------------------------------------------------------------------
# execute_buy_dev_card
# ---------------------------------------------------------------------------

class TestExecuteBuyDevCard:
    def test_draws_card_and_deducts_resources(self):
        state = _make_state()
        state.players[0].resources.update(
            {ResourceType.ORE: 1, ResourceType.WHEAT: 1, ResourceType.SHEEP: 1}
        )
        state.players[0].resource_count = 3
        deck = [DevCardType.KNIGHT]
        execute_buy_dev_card(state, 0, deck)
        assert len(deck) == 0
        assert DevCardType.KNIGHT in state.players[0].dev_cards
        assert state.players[0].dev_cards_count == 1
        assert state.dev_cards_remaining == 24
        assert state.players[0].resource_count == 0


# ---------------------------------------------------------------------------
# execute_play_dev_card
# ---------------------------------------------------------------------------

class TestExecutePlayDevCard:
    def _state_with_card(self, card: DevCardType) -> GameState:
        state = _make_state()
        state.players[0].dev_cards = [card]
        state.players[0].dev_cards_count = 1
        return state

    def test_year_of_plenty(self):
        state = self._state_with_card(DevCardType.YEAR_OF_PLENTY)
        action = PlayDevCard(
            card=DevCardType.YEAR_OF_PLENTY,
            params={"resources": [ResourceType.WOOD, ResourceType.BRICK]},
        )
        execute_play_dev_card(state, 0, action, Random(0))
        assert state.players[0].resources[ResourceType.WOOD] == 1
        assert state.players[0].resources[ResourceType.BRICK] == 1
        assert state.players[0].resource_count == 2
        assert state.players[0].dev_cards_count == 0

    def test_monopoly(self):
        state = self._state_with_card(DevCardType.MONOPOLY)
        for i in range(1, 4):
            state.players[i].resources[ResourceType.WOOD] = 3
            state.players[i].resource_count = 3
        action = PlayDevCard(
            card=DevCardType.MONOPOLY,
            params={"resource": ResourceType.WOOD},
        )
        execute_play_dev_card(state, 0, action, Random(0))
        assert state.players[0].resources[ResourceType.WOOD] == 9
        assert state.players[0].resource_count == 9
        for i in range(1, 4):
            assert state.players[i].resources[ResourceType.WOOD] == 0

    def test_victory_point_adds_public_vp(self):
        state = self._state_with_card(DevCardType.VICTORY_POINT)
        action = PlayDevCard(card=DevCardType.VICTORY_POINT)
        execute_play_dev_card(state, 0, action, Random(0))
        assert state.players[0].public_vp == 1
        assert state.players[0].dev_cards_count == 0

    def test_road_building_places_roads(self):
        state = self._state_with_card(DevCardType.ROAD_BUILDING)
        state.board.vertices[0].building = Building(
            player_id=0, building_type=BuildingType.SETTLEMENT
        )
        v0 = state.board.vertices[0]
        e0, e1 = v0.adjacent_edge_ids[0], v0.adjacent_edge_ids[1]
        action = PlayDevCard(
            card=DevCardType.ROAD_BUILDING,
            params={"road_edge_ids": [e0, e1]},
        )
        execute_play_dev_card(state, 0, action, Random(0))
        assert state.board.edges[e0].road_owner == 0
        assert state.board.edges[e1].road_owner == 0
        assert state.players[0].roads_remaining == 13


# ---------------------------------------------------------------------------
# execute_knight
# ---------------------------------------------------------------------------

class TestExecuteKnight:
    def test_increments_knights_and_removes_card(self):
        state = _make_state()
        state.players[0].dev_cards = [DevCardType.KNIGHT]
        state.players[0].dev_cards_count = 1
        execute_knight(state, 0)
        assert state.players[0].knights_played == 1
        assert state.players[0].dev_cards_count == 0

    def test_largest_army_awarded_at_3(self):
        state = _make_state()
        for _ in range(3):
            state.players[0].dev_cards.append(DevCardType.KNIGHT)
            state.players[0].dev_cards_count += 1
            execute_knight(state, 0)
        assert state.largest_army_player == 0
        assert state.players[0].has_largest_army
        assert state.players[0].public_vp == 2


# ---------------------------------------------------------------------------
# execute_bank_trade / execute_player_trade
# ---------------------------------------------------------------------------

class TestTradeExecutors:
    def test_bank_trade_swaps_resources(self):
        state = _make_state()
        state.players[0].resources[ResourceType.WOOD] = 4
        state.players[0].resource_count = 4
        execute_bank_trade(state, 0, {ResourceType.WOOD: 4}, {ResourceType.BRICK: 1})
        assert state.players[0].resources[ResourceType.WOOD] == 0
        assert state.players[0].resources[ResourceType.BRICK] == 1
        assert state.players[0].resource_count == 1

    def test_player_trade_exchanges_resources(self):
        state = _make_state()
        state.players[0].resources[ResourceType.WOOD] = 3
        state.players[0].resource_count = 3
        state.players[1].resources[ResourceType.BRICK] = 2
        state.players[1].resource_count = 2
        execute_player_trade(
            state, 0, 1,
            offering={ResourceType.WOOD: 3},
            requesting={ResourceType.BRICK: 2},
        )
        assert state.players[0].resources[ResourceType.WOOD] == 0
        assert state.players[0].resources[ResourceType.BRICK] == 2
        assert state.players[1].resources[ResourceType.BRICK] == 0
        assert state.players[1].resources[ResourceType.WOOD] == 3


# ---------------------------------------------------------------------------
# update_longest_road
# ---------------------------------------------------------------------------

class TestUpdateLongestRoad:
    def _build_chain(self, state: GameState, pid: int, start_vid: int, n_roads: int) -> int:
        """Build n_roads of roads for pid starting from start_vid; return final vid."""
        # Place a settlement anchor
        state.board.vertices[start_vid].building = Building(
            player_id=pid, building_type=BuildingType.SETTLEMENT
        )
        current_vid = start_vid
        for _ in range(n_roads):
            vertex = state.board.vertices[current_vid]
            for eid in vertex.adjacent_edge_ids:
                edge = state.board.edges[eid]
                if edge.road_owner is None:
                    edge.road_owner = pid
                    state.players[pid].roads_remaining -= 1
                    va, vb = edge.vertex_ids
                    current_vid = vb if va == current_vid else va
                    break
        return current_vid

    def test_no_award_below_5(self):
        state = _make_state()
        self._build_chain(state, 0, 0, 4)
        update_longest_road(state)
        assert state.longest_road_player is None

    def test_award_at_5(self):
        state = _make_state()
        self._build_chain(state, 0, 0, 5)
        update_longest_road(state)
        assert state.longest_road_player == 0
        assert state.players[0].has_longest_road
        assert state.players[0].public_vp == 2

    def test_transfer_when_beaten(self):
        state = _make_state()
        self._build_chain(state, 0, 0, 5)
        update_longest_road(state)
        assert state.longest_road_player == 0
        # Player 1 builds a longer road
        self._build_chain(state, 1, 10, 6)
        update_longest_road(state)
        assert state.longest_road_player == 1
        assert state.players[0].has_longest_road is False
        assert state.players[0].public_vp == 0
        assert state.players[1].public_vp == 2


# ---------------------------------------------------------------------------
# true_vp
# ---------------------------------------------------------------------------

class TestTrueVp:
    def test_counts_hidden_vp_cards(self):
        state = _make_state()
        state.players[0].public_vp = 3
        state.players[0].dev_cards = [DevCardType.VICTORY_POINT, DevCardType.VICTORY_POINT]
        state.players[0].dev_cards_count = 2
        assert true_vp(state, 0) == 5

    def test_no_hidden_cards(self):
        state = _make_state()
        state.players[0].public_vp = 7
        assert true_vp(state, 0) == 7
