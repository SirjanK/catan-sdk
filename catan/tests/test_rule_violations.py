"""
Tests for two engine rule violations found during the gameplay audit:

  1. Dev card played same turn purchased
     - Official rule: a development card bought this turn may not be played
       until the following turn.
     - Fix: validator checks state.dev_cards_bought_this_turn.

  2. Road Building card does not validate road connectivity
     - Official rule: roads placed via Road Building must obey the same
       connectivity rules as normally built roads.
     - Fix: validator checks each road edge for existence, occupancy, and
       connectivity (the second road may connect to the first).
"""

from __future__ import annotations

import pytest

from catan.board.setup import create_board
from catan.engine.executor import execute_buy_dev_card, execute_setup_road, execute_setup_settlement
from catan.engine.validator import validate_post_roll
from catan.models.actions import Build, DevCard, PlayDevCard, Road, Settlement
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
        phase=GamePhase.POST_ROLL,
        turn_number=1,
        dice=6,
        pending_trades=[],
        trades_proposed_this_turn=0,
        dev_cards_remaining=25,
        longest_road_player=None,
        largest_army_player=None,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


def _give(player: PlayerState, resource: ResourceType, amount: int) -> None:
    player.resources[resource] = player.resources.get(resource, 0) + amount
    player.resource_count += amount


# ---------------------------------------------------------------------------
# Violation 1: dev card played same turn purchased
# ---------------------------------------------------------------------------

class TestDevCardSameTurnBought:
    """Buying and immediately playing a dev card must be rejected."""

    def _state_with_bought_card(self, card: DevCardType) -> GameState:
        """Return a state where P0 has just bought *card* this turn."""
        state = _make_state()
        # Give resources so buy is valid (already deducted after execute)
        state.dev_cards_bought_this_turn = [card]
        state.players[0].dev_cards = [card]
        state.players[0].dev_cards_count = 1
        return state

    # --- YEAR_OF_PLENTY ---

    def test_yop_bought_this_turn_is_rejected(self):
        state = self._state_with_bought_card(DevCardType.YEAR_OF_PLENTY)
        action = PlayDevCard(
            card=DevCardType.YEAR_OF_PLENTY,
            params={"resources": [ResourceType.ORE, ResourceType.WHEAT]},
        )
        ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=False)
        assert not ok
        assert "purchased this turn" in reason

    def test_yop_held_before_turn_is_allowed(self):
        """Player had YoP before this turn; bought another this turn → can still play."""
        state = _make_state()
        # Player had 1 YoP before turn start; bought 1 more this turn
        state.players[0].dev_cards = [DevCardType.YEAR_OF_PLENTY, DevCardType.YEAR_OF_PLENTY]
        state.players[0].dev_cards_count = 2
        state.dev_cards_bought_this_turn = [DevCardType.YEAR_OF_PLENTY]
        action = PlayDevCard(
            card=DevCardType.YEAR_OF_PLENTY,
            params={"resources": [ResourceType.ORE, ResourceType.WHEAT]},
        )
        ok, _ = validate_post_roll(state, 0, action, has_played_dev_card=False)
        assert ok

    def test_yop_not_bought_this_turn_is_allowed(self):
        """Player has a YoP from a previous turn and hasn't bought this turn."""
        state = _make_state()
        state.players[0].dev_cards = [DevCardType.YEAR_OF_PLENTY]
        state.players[0].dev_cards_count = 1
        state.dev_cards_bought_this_turn = []
        action = PlayDevCard(
            card=DevCardType.YEAR_OF_PLENTY,
            params={"resources": [ResourceType.ORE, ResourceType.WHEAT]},
        )
        ok, _ = validate_post_roll(state, 0, action, has_played_dev_card=False)
        assert ok

    # --- MONOPOLY ---

    def test_monopoly_bought_this_turn_is_rejected(self):
        state = self._state_with_bought_card(DevCardType.MONOPOLY)
        action = PlayDevCard(
            card=DevCardType.MONOPOLY,
            params={"resource": ResourceType.ORE},
        )
        ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=False)
        assert not ok
        assert "purchased this turn" in reason

    def test_monopoly_held_before_turn_is_allowed(self):
        state = _make_state()
        state.players[0].dev_cards = [DevCardType.MONOPOLY, DevCardType.KNIGHT]
        state.players[0].dev_cards_count = 2
        # Bought a Knight this turn, not the Monopoly
        state.dev_cards_bought_this_turn = [DevCardType.KNIGHT]
        action = PlayDevCard(
            card=DevCardType.MONOPOLY,
            params={"resource": ResourceType.ORE},
        )
        ok, _ = validate_post_roll(state, 0, action, has_played_dev_card=False)
        assert ok

    # --- ROAD_BUILDING ---

    def test_road_building_bought_this_turn_is_rejected(self):
        state = _make_state()
        # Player has a settlement and a road so Road Building roads have
        # valid placements — the rejection must be the same-turn rule.
        state.board.vertices[0].building = Building(
            player_id=0, building_type=BuildingType.SETTLEMENT
        )
        state.board.edges[0].road_owner = 0
        state.players[0].roads_remaining = 13
        state.players[0].dev_cards = [DevCardType.ROAD_BUILDING]
        state.players[0].dev_cards_count = 1
        state.dev_cards_bought_this_turn = [DevCardType.ROAD_BUILDING]
        action = PlayDevCard(
            card=DevCardType.ROAD_BUILDING,
            params={"road_edge_ids": [1, 5]},
        )
        ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=False)
        assert not ok
        assert "purchased this turn" in reason

    # --- VICTORY_POINT (exempt from same-turn restriction) ---

    def test_vp_card_bought_this_turn_is_allowed(self):
        """VP cards may be revealed immediately after purchase."""
        state = self._state_with_bought_card(DevCardType.VICTORY_POINT)
        action = PlayDevCard(card=DevCardType.VICTORY_POINT, params={})
        ok, _ = validate_post_roll(state, 0, action, has_played_dev_card=False)
        assert ok

    # --- Integration: buy then play within the same engine turn ---

    def test_execute_buy_then_play_rejected_via_engine(self):
        """execute_buy_dev_card populates dev_cards_bought_this_turn; the
        subsequent play_dev_card validation uses that list to reject the play."""
        import random

        state = _make_state()
        # Give player enough resources to buy a dev card
        for r, amt in {
            ResourceType.ORE: 1,
            ResourceType.WHEAT: 1,
            ResourceType.SHEEP: 1,
        }.items():
            _give(state.players[0], r, amt)

        # Build a deck with a single known card
        deck = [DevCardType.YEAR_OF_PLENTY]
        execute_buy_dev_card(state, 0, deck)

        assert state.dev_cards_bought_this_turn == [DevCardType.YEAR_OF_PLENTY]
        assert DevCardType.YEAR_OF_PLENTY in state.players[0].dev_cards

        action = PlayDevCard(
            card=DevCardType.YEAR_OF_PLENTY,
            params={"resources": [ResourceType.ORE, ResourceType.WHEAT]},
        )
        ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=False)
        assert not ok
        assert "purchased this turn" in reason


# ---------------------------------------------------------------------------
# Violation 2: Road Building connectivity validation
# ---------------------------------------------------------------------------

# Board topology used throughout (deterministic board, randomize=False):
#   vertex 0 — adj edges [0, 5]
#   edge 0   — vertices (0, 1)
#   edge 1   — vertices (1, 2)   ← chain from edge 0
#   edge 5   — vertices (0, 5)
#   edge 6   — vertices (6, 7)   ← fully disconnected from vertex 0


class TestRoadBuildingConnectivity:
    """Road Building roads must obey the same connectivity rules as normal roads."""

    def _base_state(self) -> GameState:
        """State with P0 having a settlement at vertex 0, a road on edge 0,
        and a pre-existing Road Building card (bought last turn)."""
        state = _make_state()
        state.board.vertices[0].building = Building(
            player_id=0, building_type=BuildingType.SETTLEMENT
        )
        state.board.edges[0].road_owner = 0
        state.players[0].roads_remaining = 13
        state.players[0].dev_cards = [DevCardType.ROAD_BUILDING]
        state.players[0].dev_cards_count = 1
        state.dev_cards_bought_this_turn = []   # bought last turn → can play
        return state

    def _play_rb(self, road_edge_ids):
        return PlayDevCard(
            card=DevCardType.ROAD_BUILDING,
            params={"road_edge_ids": road_edge_ids},
        )

    # --- valid placements ---

    def test_two_connected_roads_accepted(self):
        """Both roads connect to the player's existing network."""
        state = self._base_state()
        # edge 1 (1,2) connects through vertex 1 to edge 0; edge 5 (0,5) anchors at vertex 0
        ok, reason = validate_post_roll(state, 0, self._play_rb([1, 5]), has_played_dev_card=False)
        assert ok, reason

    def test_one_road_accepted(self):
        state = self._base_state()
        ok, reason = validate_post_roll(state, 0, self._play_rb([1]), has_played_dev_card=False)
        assert ok, reason

    def test_zero_roads_accepted(self):
        state = self._base_state()
        ok, reason = validate_post_roll(state, 0, self._play_rb([]), has_played_dev_card=False)
        assert ok, reason

    def test_second_road_connects_to_first(self):
        """Second road in the params connects to the first (not yet on board)."""
        state = self._base_state()
        # Remove edge 0 road so the only anchor is the settlement at vertex 0
        state.board.edges[0].road_owner = None
        state.players[0].roads_remaining = 15
        # edge 0 (0,1) anchors at vertex 0; edge 1 (1,2) chains off edge 0
        ok, reason = validate_post_roll(state, 0, self._play_rb([0, 1]), has_played_dev_card=False)
        assert ok, reason

    # --- invalid placements ---

    def test_disconnected_road_rejected(self):
        """A road not touching the player's network must be rejected."""
        state = self._base_state()
        # edge 6 is (6,7) — completely disconnected
        ok, reason = validate_post_roll(state, 0, self._play_rb([6]), has_played_dev_card=False)
        assert not ok
        assert "connect" in reason.lower()

    def test_two_roads_first_disconnected_rejected(self):
        """First road disconnected, second connected — both rejected."""
        state = self._base_state()
        ok, reason = validate_post_roll(state, 0, self._play_rb([6, 1]), has_played_dev_card=False)
        assert not ok

    def test_occupied_edge_rejected(self):
        """An edge already occupied must be rejected."""
        state = self._base_state()
        # Mark edge 1 as occupied by player 2
        state.board.edges[1].road_owner = 2
        ok, reason = validate_post_roll(state, 0, self._play_rb([1]), has_played_dev_card=False)
        assert not ok
        assert "already has a road" in reason

    def test_nonexistent_edge_rejected(self):
        """A non-existent edge ID must be rejected."""
        state = self._base_state()
        ok, reason = validate_post_roll(state, 0, self._play_rb([9999]), has_played_dev_card=False)
        assert not ok
        assert "does not exist" in reason

    def test_duplicate_edge_ids_rejected(self):
        """The same edge ID listed twice must be rejected."""
        state = self._base_state()
        ok, reason = validate_post_roll(state, 0, self._play_rb([1, 1]), has_played_dev_card=False)
        assert not ok
        assert "duplicate" in reason.lower()

    def test_more_than_two_roads_rejected(self):
        state = self._base_state()
        ok, reason = validate_post_roll(state, 0, self._play_rb([1, 5, 0]), has_played_dev_card=False)
        assert not ok
        assert "at most 2" in reason

    def test_exceeds_roads_remaining_rejected(self):
        state = self._base_state()
        state.players[0].roads_remaining = 1
        # Trying to place 2 roads when only 1 piece remains
        ok, reason = validate_post_roll(state, 0, self._play_rb([1, 5]), has_played_dev_card=False)
        assert not ok
        assert "road pieces" in reason
