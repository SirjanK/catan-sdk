"""
Tests for DevValidator.

By default, runs the validator against BasicPlayer (must pass 100%).

To run against a custom bot:
    pytest catan/tests/test_dev_validator.py --player=submissions.my_bot:MyBot -v
"""

from __future__ import annotations

import importlib

import pytest

from catan.engine.dev_validator import DevValidator
from catan.players.basic_player import BasicPlayer


def _load_player_class(spec: str):
    """Import and return a Player subclass from 'module.path:ClassName'."""
    if ":" not in spec:
        raise ValueError(f"--player must be in the form 'module:ClassName', got: {spec!r}")
    module_path, class_name = spec.rsplit(":", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls


@pytest.fixture
def player_class(request):
    spec = request.config.getoption("--player")
    if spec:
        return _load_player_class(spec)
    return BasicPlayer


# ---------------------------------------------------------------------------
# Setup phase
# ---------------------------------------------------------------------------

class TestDevValidator:
    def test_setup_place_settlement(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_setup_place_settlement")
        assert result.passed, result.summary()

    def test_setup_place_settlement_backward(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_setup_place_settlement_backward")
        assert result.passed, result.summary()

    def test_setup_place_road(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_setup_place_road")
        assert result.passed, result.summary()

    # ---------------------------------------------------------------------------
    # Pre-roll
    # ---------------------------------------------------------------------------

    def test_pre_roll_action_roll_dice(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_pre_roll_action_roll_dice")
        assert result.passed, result.summary()

    def test_pre_roll_action_knight(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_pre_roll_action_knight")
        assert result.passed, result.summary()

    # ---------------------------------------------------------------------------
    # Discard
    # ---------------------------------------------------------------------------

    def test_discard_cards_half(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_discard_cards_half")
        assert result.passed, result.summary()

    def test_discard_cards_exact(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_discard_cards_exact")
        assert result.passed, result.summary()

    def test_discard_cards_empty_hand(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_discard_cards_empty_hand")
        assert result.passed, result.summary()

    def test_discard_cards_single_resource(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_discard_cards_single_resource")
        assert result.passed, result.summary()

    def test_discard_cards_large_hand(self, player_class):
        """15-card hand; must discard exactly 7."""
        v = DevValidator(player_class)
        result = v._run_single("_test_discard_cards_large_hand")
        assert result.passed, result.summary()

    # ---------------------------------------------------------------------------
    # Robber
    # ---------------------------------------------------------------------------

    def test_move_robber(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_move_robber")
        assert result.passed, result.summary()

    def test_move_robber_no_opponents(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_move_robber_no_opponents")
        assert result.passed, result.summary()

    def test_move_robber_non_desert_start(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_move_robber_non_desert_start")
        assert result.passed, result.summary()

    def test_move_robber_multiple_opponents(self, player_class):
        """Two opponents on the target hex; bot must specify exactly one to steal from."""
        v = DevValidator(player_class)
        result = v._run_single("_test_move_robber_multiple_opponents")
        assert result.passed, result.summary()

    def test_move_robber_zero_resource_opponent(self, player_class):
        """Opponent has 0 resources; stealing is still a valid (no-op) action."""
        v = DevValidator(player_class)
        result = v._run_single("_test_move_robber_zero_resource_opponent")
        assert result.passed, result.summary()

    # ---------------------------------------------------------------------------
    # Post-roll (take_turn)
    # ---------------------------------------------------------------------------

    def test_take_turn_post_roll(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_take_turn_post_roll")
        assert result.passed, result.summary()

    def test_take_turn_returns_pass(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_take_turn_returns_pass")
        assert result.passed, result.summary()

    def test_take_turn_bank_trade(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_take_turn_bank_trade")
        assert result.passed, result.summary()

    def test_take_turn_dev_cards(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_take_turn_dev_cards")
        assert result.passed, result.summary()

    def test_take_turn_no_settlements_remaining(self, player_class):
        """settlements_remaining=0; bot must not attempt to place a settlement."""
        v = DevValidator(player_class)
        result = v._run_single("_test_take_turn_no_settlements_remaining")
        assert result.passed, result.summary()

    def test_take_turn_no_cities_remaining(self, player_class):
        """cities_remaining=0; bot must not attempt to build a city."""
        v = DevValidator(player_class)
        result = v._run_single("_test_take_turn_no_cities_remaining")
        assert result.passed, result.summary()

    def test_take_turn_no_roads_remaining(self, player_class):
        """roads_remaining=0; bot must not attempt to build a road."""
        v = DevValidator(player_class)
        result = v._run_single("_test_take_turn_no_roads_remaining")
        assert result.passed, result.summary()

    def test_take_turn_empty_dev_deck(self, player_class):
        """dev_cards_remaining=0; bot must not attempt to buy a dev card."""
        v = DevValidator(player_class)
        result = v._run_single("_test_take_turn_empty_dev_deck")
        assert result.passed, result.summary()

    def test_take_turn_road_building_card(self, player_class):
        """Road Building dev card: params must include road_edge_ids as a list of ≤2 IDs."""
        v = DevValidator(player_class)
        result = v._run_single("_test_take_turn_road_building_card")
        assert result.passed, result.summary()

    def test_take_turn_year_of_plenty_card(self, player_class):
        """Year of Plenty: params must include 'resources' as a list of exactly 2 ResourceTypes."""
        v = DevValidator(player_class)
        result = v._run_single("_test_take_turn_year_of_plenty_card")
        assert result.passed, result.summary()

    def test_take_turn_monopoly_card(self, player_class):
        """Monopoly: params must include 'resource' as a ResourceType."""
        v = DevValidator(player_class)
        result = v._run_single("_test_take_turn_monopoly_card")
        assert result.passed, result.summary()

    def test_take_turn_port_2_1(self, player_class):
        """Player has a 2:1 port; BankTrade with 2:1 ratio must be accepted."""
        v = DevValidator(player_class)
        result = v._run_single("_test_take_turn_port_2_1")
        assert result.passed, result.summary()

    # ---------------------------------------------------------------------------
    # Trade response
    # ---------------------------------------------------------------------------

    def test_respond_to_trade_has_resources(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_respond_to_trade_has_resources")
        assert result.passed, result.summary()

    def test_respond_to_trade_no_resources(self, player_class):
        v = DevValidator(player_class)
        result = v._run_single("_test_respond_to_trade_no_resources")
        assert result.passed, result.summary()

    def test_respond_to_trade_single_resource(self, player_class):
        """Player holds exactly 1 of the requested resource; accepting or rejecting is valid."""
        v = DevValidator(player_class)
        result = v._run_single("_test_respond_to_trade_single_resource")
        assert result.passed, result.summary()

    # ---------------------------------------------------------------------------
    # State immutability
    # ---------------------------------------------------------------------------

    def test_state_immutability(self, player_class):
        """Bot must not mutate the GameState passed to take_turn."""
        v = DevValidator(player_class)
        result = v._run_single("_test_state_immutability")
        assert result.passed, result.summary()

    # ---------------------------------------------------------------------------
    # Exception handling (harness-level, independent of user's bot)
    # ---------------------------------------------------------------------------

    def test_harness_catches_bot_exception(self):
        """DevValidator must catch exceptions raised by misbehaving bots."""
        from catan.player import Player
        from catan.models.state import GameState
        from catan.models.actions import PlaceSettlement, PlaceRoad, RollDice, DiscardCards, MoveRobber, RespondToTrade

        class CrashBot(Player):
            def __init__(self, player_id: int = 0):
                self.player_id = player_id

            def setup_place_settlement(self, state):
                raise RuntimeError("intentional crash")
            def setup_place_road(self, state, settlement_vertex_id):
                raise RuntimeError("intentional crash")
            def pre_roll_action(self, state):
                raise RuntimeError("intentional crash")
            def discard_cards(self, state, count):
                raise RuntimeError("intentional crash")
            def move_robber(self, state):
                raise RuntimeError("intentional crash")
            def take_turn(self, state):
                raise RuntimeError("intentional crash")
            def respond_to_trade(self, state, proposal):
                raise RuntimeError("intentional crash")

        v = DevValidator(CrashBot)
        # Should not raise; should collect failures
        try:
            result = v.run()
        except Exception as e:
            pytest.fail(f"DevValidator raised an exception instead of catching it: {e}")

        # The harness should have recorded failures (not crashes)
        assert not result.passed, "Expected failures for a crash bot"
        # All failures should mention the intentional crash in their error text
        for failure in result.failures:
            assert "intentional crash" in failure, (
                f"Expected 'intentional crash' in failure message, got: {failure}"
            )

    # ---------------------------------------------------------------------------
    # Full run
    # ---------------------------------------------------------------------------

    def test_full_run(self, player_class):
        """Run all checks in one pass and report all failures together."""
        v = DevValidator(player_class)
        result = v.run()
        assert result.passed, result.summary()
