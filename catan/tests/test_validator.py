"""
Unit tests for catan.engine.validator.

Each test class covers one validator function.  Tests use a minimal
GameState built from a deterministic board (randomize=False) to keep
behaviour reproducible.
"""

from __future__ import annotations

import pytest

from catan.board.setup import create_board
from catan.engine.validator import (
    validate_discard,
    validate_move_robber,
    validate_post_roll,
    validate_pre_roll,
    validate_setup_road,
    validate_setup_settlement,
)
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
    Road,
    RollDice,
    Settlement,
)
from catan.models.board import Building
from catan.models.enums import BuildingType, DevCardType, GamePhase, ResourceType
from catan.models.state import GameState, PlayerState, TradeProposal


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
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
# validate_setup_settlement
# ---------------------------------------------------------------------------

class TestValidateSetupSettlement:
    def test_valid_empty_vertex(self):
        board = create_board(randomize=False)
        action = PlaceSettlement(vertex_id=0)
        ok, _ = validate_setup_settlement(board, 0, action)
        assert ok

    def test_occupied_vertex_rejected(self):
        board = create_board(randomize=False)
        board.vertices[0].building = Building(player_id=1, building_type=BuildingType.SETTLEMENT)
        action = PlaceSettlement(vertex_id=0)
        ok, reason = validate_setup_settlement(board, 0, action)
        assert not ok
        assert "occupied" in reason

    def test_distance_rule_enforced(self):
        board = create_board(randomize=False)
        # Place at vertex 0; its neighbours should be forbidden
        board.vertices[0].building = Building(player_id=0, building_type=BuildingType.SETTLEMENT)
        neighbour = board.vertices[0].adjacent_vertex_ids[0]
        action = PlaceSettlement(vertex_id=neighbour)
        ok, reason = validate_setup_settlement(board, 0, action)
        assert not ok
        assert "Distance" in reason

    def test_nonexistent_vertex_rejected(self):
        board = create_board(randomize=False)
        action = PlaceSettlement(vertex_id=9999)
        ok, reason = validate_setup_settlement(board, 0, action)
        assert not ok
        assert "does not exist" in reason


# ---------------------------------------------------------------------------
# validate_setup_road
# ---------------------------------------------------------------------------

class TestValidateSetupRoad:
    def _board_with_settlement(self, vid: int):
        board = create_board(randomize=False)
        board.vertices[vid].building = Building(player_id=0, building_type=BuildingType.SETTLEMENT)
        return board

    def test_valid_adjacent_road(self):
        board = self._board_with_settlement(0)
        adj_eid = board.vertices[0].adjacent_edge_ids[0]
        ok, _ = validate_setup_road(board, 0, 0, PlaceRoad(edge_id=adj_eid))
        assert ok

    def test_non_adjacent_edge_rejected(self):
        board = self._board_with_settlement(0)
        # Find an edge not adjacent to vertex 0
        adj_eids = set(board.vertices[0].adjacent_edge_ids)
        for eid in board.edges:
            if eid not in adj_eids:
                ok, reason = validate_setup_road(board, 0, 0, PlaceRoad(edge_id=eid))
                assert not ok
                assert "adjacent" in reason
                break

    def test_occupied_edge_rejected(self):
        board = self._board_with_settlement(0)
        adj_eid = board.vertices[0].adjacent_edge_ids[0]
        board.edges[adj_eid].road_owner = 1
        ok, reason = validate_setup_road(board, 0, 0, PlaceRoad(edge_id=adj_eid))
        assert not ok
        assert "road" in reason


# ---------------------------------------------------------------------------
# validate_pre_roll
# ---------------------------------------------------------------------------

class TestValidatePreRoll:
    def test_roll_dice_always_valid(self):
        state = _make_state()
        ok, _ = validate_pre_roll(state, 0, RollDice(), False)
        assert ok

    def test_wrong_phase_rejected(self):
        state = _make_state(phase=GamePhase.POST_ROLL)
        ok, reason = validate_pre_roll(state, 0, RollDice(), False)
        assert not ok
        assert "PRE_ROLL" in reason

    def test_wrong_player_rejected(self):
        state = _make_state()
        ok, reason = validate_pre_roll(state, 1, RollDice(), False)
        assert not ok
        assert "turn" in reason.lower()

    def test_play_knight_with_card_valid(self):
        state = _make_state()
        state.players[0].dev_cards = [DevCardType.KNIGHT]
        state.players[0].dev_cards_count = 1
        # Get any non-robber hex
        robber_hex = state.board.robber_hex_id
        target_hex = next(h for h in state.board.hexes if h != robber_hex)
        action = PlayKnight(target_hex_id=target_hex, steal_from_player_id=None)
        ok, _ = validate_pre_roll(state, 0, action, False)
        assert ok

    def test_play_knight_without_card_rejected(self):
        state = _make_state()
        robber_hex = state.board.robber_hex_id
        target_hex = next(h for h in state.board.hexes if h != robber_hex)
        action = PlayKnight(target_hex_id=target_hex, steal_from_player_id=None)
        ok, reason = validate_pre_roll(state, 0, action, False)
        assert not ok
        assert "Knight" in reason

    def test_play_knight_twice_rejected(self):
        state = _make_state()
        state.players[0].dev_cards = [DevCardType.KNIGHT]
        target_hex = next(h for h in state.board.hexes if h != state.board.robber_hex_id)
        action = PlayKnight(target_hex_id=target_hex, steal_from_player_id=None)
        ok, reason = validate_pre_roll(state, 0, action, has_played_dev_card=True)
        assert not ok
        assert "dev card" in reason.lower()


# ---------------------------------------------------------------------------
# validate_move_robber
# ---------------------------------------------------------------------------

class TestValidateMoveRobber:
    def test_valid_move(self):
        state = _make_state(phase=GamePhase.MOVING_ROBBER)
        robber = state.board.robber_hex_id
        target = next(h for h in state.board.hexes if h != robber)
        ok, _ = validate_move_robber(state, 0, MoveRobber(hex_id=target))
        assert ok

    def test_same_hex_rejected(self):
        state = _make_state(phase=GamePhase.MOVING_ROBBER)
        robber = state.board.robber_hex_id
        ok, reason = validate_move_robber(state, 0, MoveRobber(hex_id=robber))
        assert not ok
        assert "different" in reason

    def test_wrong_phase_rejected(self):
        state = _make_state(phase=GamePhase.POST_ROLL)
        target = next(h for h in state.board.hexes if h != state.board.robber_hex_id)
        ok, _ = validate_move_robber(state, 0, MoveRobber(hex_id=target))
        assert not ok

    def test_steal_from_self_rejected(self):
        state = _make_state(phase=GamePhase.MOVING_ROBBER)
        target = next(h for h in state.board.hexes if h != state.board.robber_hex_id)
        ok, reason = validate_move_robber(
            state, 0, MoveRobber(hex_id=target, steal_from_player_id=0)
        )
        assert not ok
        assert "yourself" in reason


# ---------------------------------------------------------------------------
# validate_discard
# ---------------------------------------------------------------------------

class TestValidateDiscard:
    def _state_with_hand(self, resources: dict, phase=GamePhase.DISCARDING) -> GameState:
        state = _make_state(phase=phase)
        state.players[0].resources.update(resources)
        state.players[0].resource_count = sum(resources.values())
        return state

    def test_exact_discard_valid(self):
        state = self._state_with_hand({ResourceType.WOOD: 5, ResourceType.BRICK: 5})
        action = DiscardCards(resources={ResourceType.WOOD: 5})
        ok, _ = validate_discard(state, 0, action, 5)
        assert ok

    def test_wrong_count_rejected(self):
        state = self._state_with_hand({ResourceType.WOOD: 10})
        action = DiscardCards(resources={ResourceType.WOOD: 4})
        ok, reason = validate_discard(state, 0, action, 5)
        assert not ok
        assert "5" in reason

    def test_insufficient_resource_rejected(self):
        state = self._state_with_hand({ResourceType.WOOD: 2})
        action = DiscardCards(resources={ResourceType.WOOD: 5})
        ok, reason = validate_discard(state, 0, action, 5)
        assert not ok
        assert "Not enough" in reason

    def test_negative_amount_rejected(self):
        state = self._state_with_hand({ResourceType.WOOD: 5, ResourceType.BRICK: 5})
        action = DiscardCards(resources={ResourceType.WOOD: 6, ResourceType.BRICK: -1})
        ok, reason = validate_discard(state, 0, action, 5)
        assert not ok


# ---------------------------------------------------------------------------
# validate_post_roll — Build
# ---------------------------------------------------------------------------

class TestValidatePostRollBuild:
    def _state_with_resources(self, resources: dict) -> GameState:
        state = _make_state(phase=GamePhase.POST_ROLL)
        state.players[0].resources.update(resources)
        state.players[0].resource_count = sum(resources.values())
        return state

    def test_pass_always_valid(self):
        state = _make_state(phase=GamePhase.POST_ROLL)
        ok, _ = validate_post_roll(state, 0, Pass(), False)
        assert ok

    def test_build_road_valid(self):
        state = self._state_with_resources(
            {ResourceType.WOOD: 1, ResourceType.BRICK: 1}
        )
        # Place a settlement at vertex 0 so a road can connect
        state.board.vertices[0].building = Building(
            player_id=0, building_type=BuildingType.SETTLEMENT
        )
        eid = state.board.vertices[0].adjacent_edge_ids[0]
        ok, _ = validate_post_roll(state, 0, Build(target=Road(edge_id=eid)), False)
        assert ok

    def test_build_road_insufficient_resources(self):
        state = _make_state(phase=GamePhase.POST_ROLL)
        state.board.vertices[0].building = Building(
            player_id=0, building_type=BuildingType.SETTLEMENT
        )
        eid = state.board.vertices[0].adjacent_edge_ids[0]
        ok, reason = validate_post_roll(state, 0, Build(target=Road(edge_id=eid)), False)
        assert not ok
        assert "road" in reason.lower()

    def test_build_settlement_valid(self):
        state = self._state_with_resources(
            {ResourceType.WOOD: 1, ResourceType.BRICK: 1,
             ResourceType.WHEAT: 1, ResourceType.SHEEP: 1}
        )
        # Set up a road from vertex 0 → find a vertex reachable
        v0 = state.board.vertices[0]
        eid = v0.adjacent_edge_ids[0]
        edge = state.board.edges[eid]
        state.board.edges[eid].road_owner = 0
        # Find the other endpoint
        target_vid = edge.vertex_ids[0] if edge.vertex_ids[1] == 0 else edge.vertex_ids[1]
        ok, _ = validate_post_roll(
            state, 0, Build(target=Settlement(vertex_id=target_vid)), False
        )
        assert ok

    def test_build_city_valid(self):
        state = self._state_with_resources(
            {ResourceType.WHEAT: 2, ResourceType.ORE: 3}
        )
        state.board.vertices[0].building = Building(
            player_id=0, building_type=BuildingType.SETTLEMENT
        )
        ok, _ = validate_post_roll(state, 0, Build(target=City(vertex_id=0)), False)
        assert ok

    def test_build_city_on_opponents_settlement_rejected(self):
        state = self._state_with_resources(
            {ResourceType.WHEAT: 2, ResourceType.ORE: 3}
        )
        state.board.vertices[0].building = Building(
            player_id=1, building_type=BuildingType.SETTLEMENT
        )
        ok, reason = validate_post_roll(state, 0, Build(target=City(vertex_id=0)), False)
        assert not ok
        assert "own settlement" in reason.lower()

    def test_build_dev_card_valid(self):
        state = self._state_with_resources(
            {ResourceType.ORE: 1, ResourceType.WHEAT: 1, ResourceType.SHEEP: 1}
        )
        ok, _ = validate_post_roll(state, 0, Build(target=DevCard()), False)
        assert ok

    def test_build_dev_card_deck_empty(self):
        state = self._state_with_resources(
            {ResourceType.ORE: 1, ResourceType.WHEAT: 1, ResourceType.SHEEP: 1}
        )
        state.dev_cards_remaining = 0
        ok, reason = validate_post_roll(state, 0, Build(target=DevCard()), False)
        assert not ok
        assert "empty" in reason.lower()

    def test_wrong_phase_rejected(self):
        state = _make_state(phase=GamePhase.PRE_ROLL)
        ok, _ = validate_post_roll(state, 0, Pass(), False)
        assert not ok


# ---------------------------------------------------------------------------
# validate_post_roll — PlayDevCard
# ---------------------------------------------------------------------------

class TestValidatePostRollDevCard:
    def _state_with_card(self, card: DevCardType) -> GameState:
        state = _make_state(phase=GamePhase.POST_ROLL)
        state.players[0].dev_cards = [card]
        state.players[0].dev_cards_count = 1
        return state

    def test_knight_blocked_post_roll(self):
        state = self._state_with_card(DevCardType.KNIGHT)
        ok, reason = validate_post_roll(
            state, 0, PlayDevCard(card=DevCardType.KNIGHT), False
        )
        assert not ok
        assert "pre-roll" in reason.lower()

    def test_road_building_valid(self):
        state = self._state_with_card(DevCardType.ROAD_BUILDING)
        action = PlayDevCard(card=DevCardType.ROAD_BUILDING, params={"road_edge_ids": []})
        ok, _ = validate_post_roll(state, 0, action, False)
        assert ok

    def test_year_of_plenty_valid(self):
        state = self._state_with_card(DevCardType.YEAR_OF_PLENTY)
        action = PlayDevCard(
            card=DevCardType.YEAR_OF_PLENTY,
            params={"resources": [ResourceType.WOOD, ResourceType.BRICK]},
        )
        ok, _ = validate_post_roll(state, 0, action, False)
        assert ok

    def test_monopoly_valid(self):
        state = self._state_with_card(DevCardType.MONOPOLY)
        action = PlayDevCard(card=DevCardType.MONOPOLY, params={"resource": ResourceType.WOOD})
        ok, _ = validate_post_roll(state, 0, action, False)
        assert ok

    def test_victory_point_valid_even_if_played_card(self):
        state = self._state_with_card(DevCardType.VICTORY_POINT)
        action = PlayDevCard(card=DevCardType.VICTORY_POINT)
        ok, _ = validate_post_roll(state, 0, action, has_played_dev_card=True)
        assert ok

    def test_second_non_vp_card_rejected(self):
        state = self._state_with_card(DevCardType.MONOPOLY)
        action = PlayDevCard(card=DevCardType.MONOPOLY, params={"resource": ResourceType.WOOD})
        ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=True)
        assert not ok
        assert "already played" in reason.lower()

    def test_card_not_in_hand_rejected(self):
        state = _make_state(phase=GamePhase.POST_ROLL)
        action = PlayDevCard(card=DevCardType.MONOPOLY, params={"resource": ResourceType.WOOD})
        ok, reason = validate_post_roll(state, 0, action, False)
        assert not ok
        assert "do not have" in reason.lower()


# ---------------------------------------------------------------------------
# validate_post_roll — Trade
# ---------------------------------------------------------------------------

class TestValidatePostRollTrade:
    def test_propose_trade_valid(self):
        state = _make_state(phase=GamePhase.POST_ROLL)
        state.players[0].resources[ResourceType.WOOD] = 2
        state.players[0].resource_count = 2
        action = ProposeTrade(
            offering={ResourceType.WOOD: 2},
            requesting={ResourceType.BRICK: 1},
        )
        ok, _ = validate_post_roll(state, 0, action, False)
        assert ok

    def test_propose_trade_limit_exceeded(self):
        state = _make_state(phase=GamePhase.POST_ROLL, trades_proposed_this_turn=3)
        state.players[0].resources[ResourceType.WOOD] = 2
        action = ProposeTrade(
            offering={ResourceType.WOOD: 2},
            requesting={ResourceType.BRICK: 1},
        )
        ok, reason = validate_post_roll(state, 0, action, False)
        assert not ok
        assert "limit" in reason.lower()

    def test_reject_all_trades_valid(self):
        state = _make_state(phase=GamePhase.POST_ROLL)
        ok, _ = validate_post_roll(state, 0, RejectAllTrades(), False)
        assert ok


# ---------------------------------------------------------------------------
# validate_post_roll — BankTrade
# ---------------------------------------------------------------------------

class TestValidateBankTrade:
    def test_valid_4_to_1_trade(self):
        state = _make_state(phase=GamePhase.POST_ROLL)
        state.players[0].resources[ResourceType.WOOD] = 4
        state.players[0].resource_count = 4
        action = BankTrade(
            offering={ResourceType.WOOD: 4},
            requesting={ResourceType.BRICK: 1},
        )
        ok, _ = validate_post_roll(state, 0, action, False)
        assert ok

    def test_wrong_ratio_rejected(self):
        state = _make_state(phase=GamePhase.POST_ROLL)
        state.players[0].resources[ResourceType.WOOD] = 5
        state.players[0].resource_count = 5
        action = BankTrade(
            offering={ResourceType.WOOD: 3},   # 3:1 not available without port
            requesting={ResourceType.BRICK: 1},
        )
        ok, reason = validate_post_roll(state, 0, action, False)
        assert not ok
        assert "ratio" in reason.lower()

    def test_trade_for_self_rejected(self):
        state = _make_state(phase=GamePhase.POST_ROLL)
        state.players[0].resources[ResourceType.WOOD] = 4
        action = BankTrade(
            offering={ResourceType.WOOD: 4},
            requesting={ResourceType.WOOD: 1},
        )
        ok, reason = validate_post_roll(state, 0, action, False)
        assert not ok

    def test_insufficient_resources_rejected(self):
        state = _make_state(phase=GamePhase.POST_ROLL)
        state.players[0].resources[ResourceType.WOOD] = 2
        action = BankTrade(
            offering={ResourceType.WOOD: 4},
            requesting={ResourceType.BRICK: 1},
        )
        ok, reason = validate_post_roll(state, 0, action, False)
        assert not ok
        assert "enough" in reason.lower()
