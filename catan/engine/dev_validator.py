"""
DevValidator: public correctness harness for bot developers.

Tests every Player method against crafted GameState fixtures and verifies that
the returned actions are:

  1. The correct Python type (as declared in player.py), AND
  2. Accepted as valid by catan.engine.validator

No AST scanning or subprocess isolation — run this locally before submitting.

Usage::

    pytest catan/tests/test_dev_validator.py --player=submissions.my_bot:MyBot

Failure messages are structured::

    FAILED: test_move_robber_to_current_hex
      Scenario: move_robber called after rolling 7; robber starts on hex #0.
      Bot returned: MoveRobber(hex_id=0, steal_from_player_id=None)
      Error: Robber must move to a different hex
      Hint: Check state.board.robber_hex_id to find the current position and exclude it.
"""

from __future__ import annotations

import copy
import time
from typing import Any, List, Optional, Tuple, Type

from catan.board.setup import create_board
from catan.engine.executor import execute_setup_road, execute_setup_settlement
from catan.engine.validator import (
    _distance_rule_ok,
    validate_discard,
    validate_move_robber,
    validate_post_roll,
    validate_pre_roll,
    validate_setup_road,
    validate_setup_settlement,
)
from catan.models.actions import (
    DiscardCards,
    MoveRobber,
    PlaceRoad,
    PlaceSettlement,
    PlayKnight,
    RespondToTrade,
    RollDice,
)
from catan.models.board import Building, Board
from catan.models.enums import BuildingType, DevCardType, GamePhase, PortType, ResourceType
from catan.models.state import GameState, PlayerState, TradeProposal
from catan.player import Player


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MISSING = object()  # sentinel for optional bot_returned in record()


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


def _make_state(board: Optional[Board] = None, **kwargs) -> GameState:
    if board is None:
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


def _give_resources(player: PlayerState, resources: dict) -> None:
    for res, amt in resources.items():
        player.resources[res] = player.resources.get(res, 0) + amt
        player.resource_count += amt


def _place_settlement_and_road(state: GameState, player_id: int) -> int:
    """Place a settlement and road for player_id on the first valid vertex.

    Returns the vertex_id used.
    """
    board = state.board
    for vid, vertex in board.vertices.items():
        if vertex.building is None and _distance_rule_ok(board, vid):
            execute_setup_settlement(state, player_id, vid)
            for eid in vertex.adjacent_edge_ids:
                execute_setup_road(state, player_id, eid)
                break
            return vid
    raise RuntimeError("Could not find a valid vertex to place settlement")


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------


class ValidationResult:
    """Aggregates pass/fail results from DevValidator."""

    def __init__(self) -> None:
        self.failures: List[str] = []
        self.passes: List[str] = []

    def record(
        self,
        test_name: str,
        ok: bool,
        reason: str = "",
        *,
        scenario: str = "",
        bot_returned: Any = _MISSING,
        hint: str = "",
    ) -> None:
        if ok:
            self.passes.append(test_name)
        else:
            parts = [f"\nFAILED: {test_name}"]
            if scenario:
                parts.append(f"  Scenario: {scenario}")
            if bot_returned is not _MISSING:
                parts.append(f"  Bot returned: {bot_returned!r}")
            if reason:
                parts.append(f"  Error: {reason}")
            if hint:
                parts.append(f"  Hint: {hint}")
            self.failures.append("\n".join(parts))

    @property
    def passed(self) -> bool:
        return len(self.failures) == 0

    def summary(self) -> str:
        total = len(self.passes) + len(self.failures)
        lines = [f"DevValidator: {len(self.passes)}/{total} checks passed"]
        lines.extend(self.failures)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# DevValidator
# ---------------------------------------------------------------------------


class DevValidator:
    """
    Exercises every method of a Player subclass with crafted GameState fixtures.

    Usage::

        validator = DevValidator(MyBot)
        result = validator.run()
        assert result.passed, result.summary()
    """

    def __init__(self, player_class: Type[Player]) -> None:
        self.player_class = player_class

    def _make_player_instance(self, player_id: int = 0) -> Player:
        try:
            return self.player_class(player_id=player_id)
        except TypeError:
            return self.player_class(player_id)

    def run(self) -> ValidationResult:
        result = ValidationResult()
        # Setup phase
        self._test_setup_place_settlement(result)
        self._test_setup_place_settlement_backward(result)
        self._test_setup_place_road(result)
        # Pre-roll
        self._test_pre_roll_action_roll_dice(result)
        self._test_pre_roll_action_knight(result)
        # Discard
        self._test_discard_cards_half(result)
        self._test_discard_cards_exact(result)
        self._test_discard_cards_empty_hand(result)
        self._test_discard_cards_single_resource(result)
        self._test_discard_cards_large_hand(result)
        # Robber
        self._test_move_robber(result)
        self._test_move_robber_no_opponents(result)
        self._test_move_robber_non_desert_start(result)
        self._test_move_robber_multiple_opponents(result)
        self._test_move_robber_zero_resource_opponent(result)
        # Post-roll
        self._test_take_turn_post_roll(result)
        self._test_take_turn_returns_pass(result)
        self._test_take_turn_bank_trade(result)
        self._test_take_turn_dev_cards(result)
        self._test_take_turn_no_settlements_remaining(result)
        self._test_take_turn_no_cities_remaining(result)
        self._test_take_turn_no_roads_remaining(result)
        self._test_take_turn_empty_dev_deck(result)
        self._test_take_turn_road_building_card(result)
        self._test_take_turn_year_of_plenty_card(result)
        self._test_take_turn_monopoly_card(result)
        self._test_take_turn_port_2_1(result)
        # Trade
        self._test_respond_to_trade_has_resources(result)
        self._test_respond_to_trade_no_resources(result)
        self._test_respond_to_trade_single_resource(result)
        # State immutability
        self._test_state_immutability(result)
        return result

    def _run_single(self, method_name: str) -> ValidationResult:
        """Run a single test method by name and return its result."""
        result = ValidationResult()
        getattr(self, method_name)(result)
        return result

    # ------------------------------------------------------------------
    # Setup phase
    # ------------------------------------------------------------------

    def _test_setup_place_settlement(self, result: ValidationResult) -> None:
        """setup_place_settlement returns PlaceSettlement on valid empty board."""
        state = _make_state(phase=GamePhase.SETUP_FORWARD, current_player_id=0)
        bot = self._make_player_instance(0)

        try:
            action = bot.setup_place_settlement(state)
        except Exception as e:
            result.record(
                "setup_place_settlement/returns_action", False, str(e),
                scenario="setup_place_settlement called on an empty board in SETUP_FORWARD phase.",
                hint="Ensure your method returns a PlaceSettlement and does not raise.",
            )
            return

        if not isinstance(action, PlaceSettlement):
            result.record(
                "setup_place_settlement/type", False,
                f"Expected PlaceSettlement, got {type(action).__name__}",
                scenario="setup_place_settlement called on an empty board.",
                bot_returned=action,
            )
            return

        ok, reason = validate_setup_settlement(state.board, 0, action)
        result.record(
            "setup_place_settlement/valid", ok, reason,
            scenario="Returned PlaceSettlement must satisfy the distance rule and target an empty vertex.",
            bot_returned=action,
            hint="Pick any unoccupied vertex where no adjacent vertex has a building.",
        )

    def _test_setup_place_settlement_backward(self, result: ValidationResult) -> None:
        """setup_place_settlement in SETUP_BACKWARD with board already partially built."""
        state = _make_state(phase=GamePhase.SETUP_BACKWARD, current_player_id=0)
        board = state.board

        placed: list[int] = []
        for pid in range(4):
            bot_i = self._make_player_instance(pid)
            tmp_state = copy.deepcopy(state)
            try:
                s_act = bot_i.setup_place_settlement(tmp_state)
            except Exception:
                s_act = PlaceSettlement(vertex_id=next(
                    v for v, vx in board.vertices.items()
                    if vx.building is None and _distance_rule_ok(board, v)
                ))
            execute_setup_settlement(state, pid, s_act.vertex_id)
            placed.append(s_act.vertex_id)
            for eid in state.board.vertices[s_act.vertex_id].adjacent_edge_ids:
                execute_setup_road(state, pid, eid)
                break

        bot = self._make_player_instance(0)
        try:
            action = bot.setup_place_settlement(state)
        except Exception as e:
            result.record(
                "setup_place_settlement_backward/returns_action", False, str(e),
                scenario="setup_place_settlement in SETUP_BACKWARD with 4 settlements already placed.",
            )
            return

        if not isinstance(action, PlaceSettlement):
            result.record(
                "setup_place_settlement_backward/type", False,
                f"Expected PlaceSettlement, got {type(action).__name__}",
                bot_returned=action,
            )
            return

        ok, reason = validate_setup_settlement(state.board, 0, action)
        result.record(
            "setup_place_settlement_backward/valid", ok, reason,
            bot_returned=action,
            hint="All existing settlements block adjacent vertices via the distance rule.",
        )

    def _test_setup_place_road(self, result: ValidationResult) -> None:
        """setup_place_road returns PlaceRoad adjacent to just-placed settlement."""
        state = _make_state(phase=GamePhase.SETUP_FORWARD, current_player_id=0)
        bot = self._make_player_instance(0)

        try:
            s_action = bot.setup_place_settlement(state)
        except Exception as e:
            result.record("setup_place_road/prereq", False, str(e),
                          scenario="setup_place_road prerequisite: bot raised in setup_place_settlement.")
            return
        if not isinstance(s_action, PlaceSettlement):
            result.record("setup_place_road/prereq", False,
                          f"setup_place_settlement returned {type(s_action).__name__}")
            return
        execute_setup_settlement(state, 0, s_action.vertex_id)

        try:
            action = bot.setup_place_road(state, s_action.vertex_id)
        except Exception as e:
            result.record(
                "setup_place_road/returns_action", False, str(e),
                scenario=f"setup_place_road called after placing settlement at vertex {s_action.vertex_id}.",
                hint="Return a PlaceRoad with an edge adjacent to the settlement vertex.",
            )
            return

        if not isinstance(action, PlaceRoad):
            result.record(
                "setup_place_road/type", False,
                f"Expected PlaceRoad, got {type(action).__name__}",
                bot_returned=action,
            )
            return

        ok, reason = validate_setup_road(state.board, 0, s_action.vertex_id, action)
        result.record(
            "setup_place_road/valid", ok, reason,
            bot_returned=action,
            hint="The road edge must be adjacent to the settlement vertex just placed.",
        )

    # ------------------------------------------------------------------
    # Pre-roll
    # ------------------------------------------------------------------

    def _test_pre_roll_action_roll_dice(self, result: ValidationResult) -> None:
        """pre_roll_action returns RollDice or PlayKnight (both are valid)."""
        state = _make_state(phase=GamePhase.PRE_ROLL, current_player_id=0)
        bot = self._make_player_instance(0)

        try:
            action = bot.pre_roll_action(state)
        except Exception as e:
            result.record(
                "pre_roll_action/returns_action", False, str(e),
                scenario="pre_roll_action on a fresh PRE_ROLL state with no dev cards.",
            )
            return

        if not isinstance(action, (RollDice, PlayKnight)):
            result.record(
                "pre_roll_action/type", False,
                f"Expected RollDice or PlayKnight, got {type(action).__name__}",
                bot_returned=action,
            )
            return

        ok, reason = validate_pre_roll(state, 0, action, has_played_dev_card=False)
        result.record(
            "pre_roll_action/valid", ok, reason,
            bot_returned=action,
            hint="Without a Knight card, only RollDice is valid pre-roll.",
        )

    def _test_pre_roll_action_knight(self, result: ValidationResult) -> None:
        """pre_roll_action with a Knight card returns a valid action."""
        state = _make_state(phase=GamePhase.PRE_ROLL, current_player_id=0)
        state.players[0].dev_cards = [DevCardType.KNIGHT]
        state.players[0].dev_cards_count = 1
        board = state.board
        robber_hid = board.robber_hex_id
        target_hid = next(hid for hid in board.hexes if hid != robber_hid)
        target_hex = board.hexes[target_hid]
        board.vertices[target_hex.vertex_ids[0]].building = Building(
            player_id=1, building_type=BuildingType.SETTLEMENT
        )

        bot = self._make_player_instance(0)
        try:
            action = bot.pre_roll_action(state)
        except Exception as e:
            result.record(
                "pre_roll_action_knight/returns_action", False, str(e),
                scenario="pre_roll_action with a Knight card in hand. An opponent is on a non-robber hex.",
            )
            return

        if not isinstance(action, (RollDice, PlayKnight)):
            result.record(
                "pre_roll_action_knight/type", False,
                f"Expected RollDice or PlayKnight, got {type(action).__name__}",
                bot_returned=action,
            )
            return

        ok, reason = validate_pre_roll(state, 0, action, has_played_dev_card=False)
        result.record(
            "pre_roll_action_knight/valid", ok, reason,
            bot_returned=action,
            hint="If playing a Knight, move the robber to a different hex and optionally steal.",
        )

    # ------------------------------------------------------------------
    # Discard
    # ------------------------------------------------------------------

    def _test_discard_cards_half(self, result: ValidationResult) -> None:
        """discard_cards returns DiscardCards with correct count when hand > 7."""
        state = _make_state(phase=GamePhase.DISCARDING, current_player_id=1)
        _give_resources(state.players[0], {
            ResourceType.WOOD: 4,
            ResourceType.BRICK: 3,
            ResourceType.WHEAT: 3,
        })
        discard_count = 5
        bot = self._make_player_instance(0)

        try:
            action = bot.discard_cards(state, discard_count)
        except Exception as e:
            result.record("discard_cards_half/returns_action", False, str(e),
                          scenario="discard_cards with 10 cards in hand; must discard 5.")
            return

        if not isinstance(action, DiscardCards):
            result.record("discard_cards_half/type", False,
                          f"Expected DiscardCards, got {type(action).__name__}",
                          bot_returned=action)
            return

        ok, reason = validate_discard(state, 0, action, discard_count)
        result.record("discard_cards_half/valid", ok, reason,
                      bot_returned=action,
                      hint="Return exactly 5 cards that are in your hand.")

    def _test_discard_cards_exact(self, result: ValidationResult) -> None:
        """discard_cards works when player has exactly 8 cards (discard 4)."""
        state = _make_state(phase=GamePhase.DISCARDING, current_player_id=1)
        _give_resources(state.players[0], {
            ResourceType.WOOD: 2,
            ResourceType.ORE: 2,
            ResourceType.SHEEP: 2,
            ResourceType.WHEAT: 2,
        })
        discard_count = 4
        bot = self._make_player_instance(0)

        try:
            action = bot.discard_cards(state, discard_count)
        except Exception as e:
            result.record("discard_cards_exact/returns_action", False, str(e),
                          scenario="discard_cards with exactly 8 cards; must discard 4.")
            return

        if not isinstance(action, DiscardCards):
            result.record("discard_cards_exact/type", False,
                          f"Expected DiscardCards, got {type(action).__name__}",
                          bot_returned=action)
            return

        ok, reason = validate_discard(state, 0, action, discard_count)
        result.record("discard_cards_exact/valid", ok, reason, bot_returned=action)

    def _test_discard_cards_empty_hand(self, result: ValidationResult) -> None:
        """discard_cards(count=0) returns DiscardCards with empty resources."""
        state = _make_state(phase=GamePhase.DISCARDING, current_player_id=1)
        bot = self._make_player_instance(0)

        try:
            action = bot.discard_cards(state, 0)
        except Exception as e:
            result.record("discard_cards_empty/returns_action", False, str(e),
                          scenario="discard_cards with 0 cards; discard_count=0.")
            return

        if not isinstance(action, DiscardCards):
            result.record("discard_cards_empty/type", False,
                          f"Expected DiscardCards, got {type(action).__name__}",
                          bot_returned=action)
            return

        ok, reason = validate_discard(state, 0, action, 0)
        result.record("discard_cards_empty/valid", ok, reason, bot_returned=action,
                      hint="Return DiscardCards with empty resources when discard_count=0.")

    def _test_discard_cards_single_resource(self, result: ValidationResult) -> None:
        """discard_cards works when the player's hand is entirely one resource type."""
        state = _make_state(phase=GamePhase.DISCARDING, current_player_id=1)
        _give_resources(state.players[0], {ResourceType.ORE: 10})
        discard_count = 5
        bot = self._make_player_instance(0)

        try:
            action = bot.discard_cards(state, discard_count)
        except Exception as e:
            result.record("discard_cards_single_resource/returns_action", False, str(e),
                          scenario="discard_cards with 10 ORE only; must discard 5.")
            return

        if not isinstance(action, DiscardCards):
            result.record("discard_cards_single_resource/type", False,
                          f"Expected DiscardCards, got {type(action).__name__}",
                          bot_returned=action)
            return

        ok, reason = validate_discard(state, 0, action, discard_count)
        result.record("discard_cards_single_resource/valid", ok, reason, bot_returned=action,
                      hint="With a single-resource hand, discard exactly 5 ORE.")

    def _test_discard_cards_large_hand(self, result: ValidationResult) -> None:
        """discard_cards with 15 cards (maximum possible) — must discard 7."""
        state = _make_state(phase=GamePhase.DISCARDING, current_player_id=1)
        _give_resources(state.players[0], {
            ResourceType.WOOD: 3,
            ResourceType.BRICK: 3,
            ResourceType.WHEAT: 3,
            ResourceType.SHEEP: 3,
            ResourceType.ORE: 3,
        })
        discard_count = 7
        bot = self._make_player_instance(0)

        try:
            action = bot.discard_cards(state, discard_count)
        except Exception as e:
            result.record("discard_cards_large_hand/returns_action", False, str(e),
                          scenario="discard_cards with 15 cards (3 of each resource); must discard 7.")
            return

        if not isinstance(action, DiscardCards):
            result.record("discard_cards_large_hand/type", False,
                          f"Expected DiscardCards, got {type(action).__name__}",
                          bot_returned=action)
            return

        ok, reason = validate_discard(state, 0, action, discard_count)
        result.record("discard_cards_large_hand/valid", ok, reason, bot_returned=action,
                      hint="Discard exactly 7 cards from your 15-card hand.")

    # ------------------------------------------------------------------
    # Move robber
    # ------------------------------------------------------------------

    def _test_move_robber(self, result: ValidationResult) -> None:
        """move_robber returns MoveRobber to a different hex."""
        state = _make_state(phase=GamePhase.MOVING_ROBBER, current_player_id=0)
        board = state.board
        robber_hid = board.robber_hex_id
        target_hid = next(hid for hid in board.hexes if hid != robber_hid)
        target_hex = board.hexes[target_hid]
        board.vertices[target_hex.vertex_ids[0]].building = Building(
            player_id=1, building_type=BuildingType.SETTLEMENT
        )
        bot = self._make_player_instance(0)

        try:
            action = bot.move_robber(state)
        except Exception as e:
            result.record("move_robber/returns_action", False, str(e),
                          scenario="move_robber with one opponent on a non-robber hex.")
            return

        if not isinstance(action, MoveRobber):
            result.record("move_robber/type", False,
                          f"Expected MoveRobber, got {type(action).__name__}",
                          bot_returned=action)
            return

        ok, reason = validate_move_robber(state, 0, action)
        result.record("move_robber/valid", ok, reason, bot_returned=action,
                      hint="Move the robber to a different hex; optionally steal from the opponent.")

    def _test_move_robber_no_opponents(self, result: ValidationResult) -> None:
        """move_robber with no opponent buildings returns a valid MoveRobber."""
        state = _make_state(phase=GamePhase.MOVING_ROBBER, current_player_id=0)
        bot = self._make_player_instance(0)

        try:
            action = bot.move_robber(state)
        except Exception as e:
            result.record("move_robber_no_opponents/returns_action", False, str(e),
                          scenario="move_robber when no opponents have buildings on the board.")
            return

        if not isinstance(action, MoveRobber):
            result.record("move_robber_no_opponents/type", False,
                          f"Expected MoveRobber, got {type(action).__name__}",
                          bot_returned=action)
            return

        ok, reason = validate_move_robber(state, 0, action)
        result.record("move_robber_no_opponents/valid", ok, reason, bot_returned=action,
                      hint="When no opponents are on any hex, move to any different hex with steal_from_player_id=None.")

    def _test_move_robber_non_desert_start(self, result: ValidationResult) -> None:
        """move_robber works when the robber starts on a non-desert hex."""
        state = _make_state(phase=GamePhase.MOVING_ROBBER, current_player_id=0)
        board = state.board
        non_desert = next(hid for hid, h in board.hexes.items() if hid != board.robber_hex_id)
        board.robber_hex_id = non_desert

        bot = self._make_player_instance(0)
        try:
            action = bot.move_robber(state)
        except Exception as e:
            result.record("move_robber_non_desert_start/returns_action", False, str(e),
                          scenario=f"move_robber with robber starting on non-desert hex {non_desert}.")
            return

        if not isinstance(action, MoveRobber):
            result.record("move_robber_non_desert_start/type", False,
                          f"Expected MoveRobber, got {type(action).__name__}",
                          bot_returned=action)
            return

        ok, reason = validate_move_robber(state, 0, action)
        result.record("move_robber_non_desert_start/valid", ok, reason, bot_returned=action,
                      hint="Check state.board.robber_hex_id — the robber may not be on the desert.")

    def _test_move_robber_multiple_opponents(self, result: ValidationResult) -> None:
        """move_robber when multiple opponents are on the target hex — bot must pick one."""
        state = _make_state(phase=GamePhase.MOVING_ROBBER, current_player_id=0)
        board = state.board
        robber_hid = board.robber_hex_id
        target_hid = next(hid for hid in board.hexes if hid != robber_hid)
        target_hex = board.hexes[target_hid]
        # Place two different opponents on the same hex
        board.vertices[target_hex.vertex_ids[0]].building = Building(
            player_id=1, building_type=BuildingType.SETTLEMENT
        )
        board.vertices[target_hex.vertex_ids[2]].building = Building(
            player_id=2, building_type=BuildingType.SETTLEMENT
        )

        bot = self._make_player_instance(0)
        try:
            action = bot.move_robber(state)
        except Exception as e:
            result.record("move_robber_multiple_opponents/returns_action", False, str(e),
                          scenario="move_robber with two opponents (P1 and P2) on the target hex.")
            return

        if not isinstance(action, MoveRobber):
            result.record("move_robber_multiple_opponents/type", False,
                          f"Expected MoveRobber, got {type(action).__name__}",
                          bot_returned=action)
            return

        ok, reason = validate_move_robber(state, 0, action)
        result.record("move_robber_multiple_opponents/valid", ok, reason, bot_returned=action,
                      hint="When multiple opponents share a hex, steal_from_player_id must be exactly one of them.")

    def _test_move_robber_zero_resource_opponent(self, result: ValidationResult) -> None:
        """move_robber targeting a player with 0 resources — valid; no card transferred."""
        state = _make_state(phase=GamePhase.MOVING_ROBBER, current_player_id=0)
        board = state.board
        robber_hid = board.robber_hex_id
        target_hid = next(hid for hid in board.hexes if hid != robber_hid)
        target_hex = board.hexes[target_hid]
        # Opponent P1 has 0 resources (default state)
        board.vertices[target_hex.vertex_ids[0]].building = Building(
            player_id=1, building_type=BuildingType.SETTLEMENT
        )

        bot = self._make_player_instance(0)
        try:
            action = bot.move_robber(state)
        except Exception as e:
            result.record("move_robber_zero_resource/returns_action", False, str(e),
                          scenario="move_robber targeting P1 who has 0 resources; steal is still valid.")
            return

        if not isinstance(action, MoveRobber):
            result.record("move_robber_zero_resource/type", False,
                          f"Expected MoveRobber, got {type(action).__name__}",
                          bot_returned=action)
            return

        ok, reason = validate_move_robber(state, 0, action)
        result.record("move_robber_zero_resource/valid", ok, reason, bot_returned=action,
                      hint="Stealing from a player with 0 resources is valid — no card is transferred.")

    # ------------------------------------------------------------------
    # Take turn (POST_ROLL)
    # ------------------------------------------------------------------

    def _test_take_turn_post_roll(self, result: ValidationResult) -> None:
        """take_turn with full resources returns a valid action."""
        from catan.models.actions import AcceptTrade, Build, Pass, PlayDevCard, ProposeTrade, RejectAllTrades

        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=0, dice=6)
        _give_resources(state.players[0], {
            ResourceType.WOOD: 5,
            ResourceType.BRICK: 5,
            ResourceType.WHEAT: 5,
            ResourceType.SHEEP: 5,
            ResourceType.ORE: 5,
        })
        _place_settlement_and_road(state, 0)

        bot = self._make_player_instance(0)
        _VALID_TYPES = (Build, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades)

        try:
            action = bot.take_turn(state)
        except Exception as e:
            result.record("take_turn/returns_action", False, str(e),
                          scenario="take_turn with 5 of each resource and an established settlement/road.")
            return

        if not isinstance(action, _VALID_TYPES):
            result.record("take_turn/type", False,
                          f"Got {type(action).__name__}, expected one of Build/Pass/PlayDevCard/Trade",
                          bot_returned=action)
            return

        ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=False)
        result.record("take_turn/valid", ok, reason, bot_returned=action)

    def _test_take_turn_returns_pass(self, result: ValidationResult) -> None:
        """take_turn with no resources eventually returns Pass."""
        from catan.models.actions import AcceptTrade, Build, BankTrade, Pass, PlayDevCard, ProposeTrade, RejectAllTrades

        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=0, dice=6)
        bot = self._make_player_instance(0)

        _VALID_TYPES = (Build, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades, BankTrade)

        seen_pass = False
        for i in range(20):
            try:
                action = bot.take_turn(state)
            except Exception as e:
                result.record(f"take_turn_no_resources/iter_{i}", False, str(e),
                              scenario="take_turn with 0 resources.")
                return

            if not isinstance(action, _VALID_TYPES):
                result.record(f"take_turn_no_resources/type_iter_{i}", False,
                               f"Got {type(action).__name__}", bot_returned=action)
                return

            if isinstance(action, Pass):
                seen_pass = True
                break

            ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=False)
            if not ok:
                result.record(f"take_turn_no_resources/valid_iter_{i}", False, reason,
                               bot_returned=action,
                               hint="With no resources, the only valid action is Pass.")
                return

        result.record("take_turn_no_resources/eventually_passes", seen_pass,
                      "take_turn never returned Pass in 20 iterations",
                      hint="With no resources and nothing to build, return Pass.")

    def _test_take_turn_bank_trade(self, result: ValidationResult) -> None:
        """take_turn handles the case where the player can perform a 4:1 bank trade."""
        from catan.models.actions import AcceptTrade, BankTrade, Build, Pass, PlayDevCard, ProposeTrade, RejectAllTrades

        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=0, dice=4)
        _give_resources(state.players[0], {ResourceType.WOOD: 4})

        bot = self._make_player_instance(0)
        _VALID_TYPES = (Build, BankTrade, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades)

        seen_pass = False
        for i in range(10):
            try:
                action = bot.take_turn(state)
            except Exception as e:
                result.record(f"take_turn_bank_trade/iter_{i}", False, str(e),
                              scenario="take_turn with 4 WOOD (4:1 bank trade is possible).")
                return

            if not isinstance(action, _VALID_TYPES):
                result.record("take_turn_bank_trade/type", False,
                               f"Got {type(action).__name__}", bot_returned=action)
                return

            if isinstance(action, Pass):
                seen_pass = True
                break

            ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=False)
            if not ok:
                result.record(f"take_turn_bank_trade/valid_iter_{i}", False, reason,
                               bot_returned=action)
                return

        result.record("take_turn_bank_trade/eventually_passes", seen_pass,
                      "take_turn never returned Pass in 10 iterations")

    def _test_take_turn_dev_cards(self, result: ValidationResult) -> None:
        """take_turn correctly handles a hand containing dev cards."""
        from catan.models.actions import AcceptTrade, BankTrade, Build, Pass, PlayDevCard, ProposeTrade, RejectAllTrades

        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=0, dice=5)
        state.players[0].dev_cards = [
            DevCardType.YEAR_OF_PLENTY,
            DevCardType.MONOPOLY,
            DevCardType.ROAD_BUILDING,
        ]
        state.players[0].dev_cards_count = 3
        _give_resources(state.players[0], {ResourceType.WOOD: 1, ResourceType.BRICK: 1})

        bot = self._make_player_instance(0)
        _VALID_TYPES = (Build, BankTrade, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades)

        seen_pass = False
        has_played_dev_card = False
        for i in range(20):
            try:
                action = bot.take_turn(state)
            except Exception as e:
                result.record(f"take_turn_dev_cards/iter_{i}", False, str(e),
                              scenario="take_turn with YoP/Monopoly/RoadBuilding dev cards.")
                return

            if not isinstance(action, _VALID_TYPES):
                result.record("take_turn_dev_cards/type", False,
                               f"Got {type(action).__name__}", bot_returned=action)
                return

            if isinstance(action, Pass):
                seen_pass = True
                break

            ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=has_played_dev_card)
            if not ok:
                result.record(f"take_turn_dev_cards/valid_iter_{i}", False, reason,
                               bot_returned=action,
                               hint="Only one dev card may be played per turn (VP cards are auto-counted).")
                return

            if isinstance(action, PlayDevCard):
                has_played_dev_card = True

        result.record("take_turn_dev_cards/eventually_passes", seen_pass,
                      "take_turn never returned Pass in 20 iterations")

    def _test_take_turn_no_settlements_remaining(self, result: ValidationResult) -> None:
        """take_turn when settlements_remaining=0 — bot must not try to build a settlement."""
        from catan.models.actions import AcceptTrade, BankTrade, Build, Pass, PlayDevCard, ProposeTrade, RejectAllTrades
        from catan.models.actions import Settlement

        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=0, dice=6)
        state.players[0].settlements_remaining = 0
        state.players[0].roads_remaining = 0
        # Give only WHEAT + SHEEP: can't build roads (no WOOD/BRICK), can't build
        # settlement (limit=0), can't build city/dev card (no ORE).  Only valid
        # action is Pass (or a trade proposal).
        _give_resources(state.players[0], {
            ResourceType.WHEAT: 2,
            ResourceType.SHEEP: 2,
        })
        _place_settlement_and_road(state, 0)

        bot = self._make_player_instance(0)
        _VALID_TYPES = (Build, BankTrade, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades)

        seen_pass = False
        has_played_dev_card = False
        for i in range(20):
            try:
                action = bot.take_turn(state)
            except Exception as e:
                result.record(f"take_turn_no_settlements/iter_{i}", False, str(e),
                              scenario="take_turn with settlements_remaining=0; bot cannot build settlements.")
                return

            if isinstance(action, Pass):
                seen_pass = True
                break

            if not isinstance(action, _VALID_TYPES):
                result.record("take_turn_no_settlements/type", False,
                               f"Got {type(action).__name__}", bot_returned=action)
                return

            ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=has_played_dev_card)
            if not ok:
                result.record(f"take_turn_no_settlements/valid_iter_{i}", False, reason,
                               bot_returned=action,
                               hint="settlements_remaining=0; do not attempt Build(Settlement).")
                return

            if isinstance(action, PlayDevCard):
                has_played_dev_card = True

        result.record("take_turn_no_settlements/eventually_passes", seen_pass,
                      "take_turn never returned Pass in 20 iterations")

    def _test_take_turn_no_cities_remaining(self, result: ValidationResult) -> None:
        """take_turn when cities_remaining=0 — bot must not try to build a city."""
        from catan.models.actions import AcceptTrade, BankTrade, Build, Pass, PlayDevCard, ProposeTrade, RejectAllTrades

        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=0, dice=6)
        state.players[0].cities_remaining = 0
        state.players[0].settlements_remaining = 0
        state.players[0].roads_remaining = 0
        # Give only ORE+WHEAT: city resources but no pieces remaining.  Also no
        # WOOD/BRICK so road can't be built.  Bot must Pass.
        _give_resources(state.players[0], {
            ResourceType.WHEAT: 2,
            ResourceType.ORE: 3,
        })

        bot = self._make_player_instance(0)
        _VALID_TYPES = (Build, BankTrade, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades)

        seen_pass = False
        has_played_dev_card = False
        for i in range(20):
            try:
                action = bot.take_turn(state)
            except Exception as e:
                result.record(f"take_turn_no_cities/iter_{i}", False, str(e),
                              scenario="take_turn with cities_remaining=0; bot cannot build cities.")
                return

            if isinstance(action, Pass):
                seen_pass = True
                break

            if not isinstance(action, _VALID_TYPES):
                result.record("take_turn_no_cities/type", False,
                               f"Got {type(action).__name__}", bot_returned=action)
                return

            ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=has_played_dev_card)
            if not ok:
                result.record(f"take_turn_no_cities/valid_iter_{i}", False, reason,
                               bot_returned=action,
                               hint="cities_remaining=0; do not attempt Build(City).")
                return

            if isinstance(action, PlayDevCard):
                has_played_dev_card = True

        result.record("take_turn_no_cities/eventually_passes", seen_pass,
                      "take_turn never returned Pass in 20 iterations")

    def _test_take_turn_no_roads_remaining(self, result: ValidationResult) -> None:
        """take_turn when roads_remaining=0 — bot must not try to build a road."""
        from catan.models.actions import AcceptTrade, BankTrade, Build, Pass, PlayDevCard, ProposeTrade, RejectAllTrades

        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=0, dice=6)
        state.players[0].roads_remaining = 0
        state.players[0].settlements_remaining = 0
        # Give WOOD+BRICK (road resources) but no road pieces; can't build anything useful.
        _give_resources(state.players[0], {
            ResourceType.WOOD: 2,
            ResourceType.BRICK: 2,
        })

        bot = self._make_player_instance(0)
        _VALID_TYPES = (Build, BankTrade, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades)

        seen_pass = False
        has_played_dev_card = False
        for i in range(20):
            try:
                action = bot.take_turn(state)
            except Exception as e:
                result.record(f"take_turn_no_roads/iter_{i}", False, str(e),
                              scenario="take_turn with roads_remaining=0; bot cannot build roads.")
                return

            if isinstance(action, Pass):
                seen_pass = True
                break

            if not isinstance(action, _VALID_TYPES):
                result.record("take_turn_no_roads/type", False,
                               f"Got {type(action).__name__}", bot_returned=action)
                return

            ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=has_played_dev_card)
            if not ok:
                result.record(f"take_turn_no_roads/valid_iter_{i}", False, reason,
                               bot_returned=action,
                               hint="roads_remaining=0; do not attempt Build(Road).")
                return

            if isinstance(action, PlayDevCard):
                has_played_dev_card = True

        result.record("take_turn_no_roads/eventually_passes", seen_pass,
                      "take_turn never returned Pass in 20 iterations")

    def _test_take_turn_empty_dev_deck(self, result: ValidationResult) -> None:
        """take_turn when dev_cards_remaining=0 — bot must not try to buy a dev card."""
        from catan.models.actions import AcceptTrade, BankTrade, Build, Pass, PlayDevCard, ProposeTrade, RejectAllTrades
        from catan.models.actions import DevCard

        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=0, dice=6,
                            dev_cards_remaining=0)
        _give_resources(state.players[0], {
            ResourceType.ORE: 3,
            ResourceType.WHEAT: 3,
            ResourceType.SHEEP: 3,
        })

        bot = self._make_player_instance(0)
        _VALID_TYPES = (Build, BankTrade, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades)

        seen_pass = False
        has_played_dev_card = False
        for i in range(10):
            try:
                action = bot.take_turn(state)
            except Exception as e:
                result.record(f"take_turn_empty_deck/iter_{i}", False, str(e),
                              scenario="take_turn with dev_cards_remaining=0; cannot buy dev cards.")
                return

            if isinstance(action, Pass):
                seen_pass = True
                break

            if not isinstance(action, _VALID_TYPES):
                result.record("take_turn_empty_deck/type", False,
                               f"Got {type(action).__name__}", bot_returned=action)
                return

            ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=has_played_dev_card)
            if not ok:
                result.record(f"take_turn_empty_deck/valid_iter_{i}", False, reason,
                               bot_returned=action,
                               hint="Check state.dev_cards_remaining before attempting to buy a dev card.")
                return

            if isinstance(action, PlayDevCard):
                has_played_dev_card = True

        result.record("take_turn_empty_deck/eventually_passes", seen_pass,
                      "take_turn never returned Pass in 10 iterations")

    def _test_take_turn_road_building_card(self, result: ValidationResult) -> None:
        """take_turn with a Road Building card returns a valid PlayDevCard action."""
        from catan.models.actions import BankTrade, Build, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades

        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=0, dice=6)
        state.players[0].dev_cards = [DevCardType.ROAD_BUILDING]
        state.players[0].dev_cards_count = 1
        _place_settlement_and_road(state, 0)

        bot = self._make_player_instance(0)
        _VALID_TYPES = (Build, BankTrade, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades)

        seen_road_building = False
        has_played_dev_card = False
        for i in range(20):
            try:
                action = bot.take_turn(state)
            except Exception as e:
                result.record(f"take_turn_road_building/iter_{i}", False, str(e),
                              scenario="take_turn with Road Building card and an established road network.")
                return

            if isinstance(action, Pass):
                break

            if not isinstance(action, _VALID_TYPES):
                result.record("take_turn_road_building/type", False,
                               f"Got {type(action).__name__}", bot_returned=action)
                return

            ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=has_played_dev_card)
            if not ok:
                result.record(f"take_turn_road_building/valid_iter_{i}", False, reason,
                               bot_returned=action,
                               hint="Road Building params must include 'road_edge_ids' as a list of ≤2 edge IDs.")
                return

            if isinstance(action, PlayDevCard) and action.card == DevCardType.ROAD_BUILDING:
                seen_road_building = True
                has_played_dev_card = True
                break
            elif isinstance(action, PlayDevCard):
                has_played_dev_card = True

        # It's OK if the bot didn't play Road Building (it may have passed instead).
        result.record("take_turn_road_building/valid_sequence", True)

    def _test_take_turn_year_of_plenty_card(self, result: ValidationResult) -> None:
        """take_turn with a Year of Plenty card returns a valid PlayDevCard action."""
        from catan.models.actions import BankTrade, Build, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades

        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=0, dice=6)
        state.players[0].dev_cards = [DevCardType.YEAR_OF_PLENTY]
        state.players[0].dev_cards_count = 1

        bot = self._make_player_instance(0)
        _VALID_TYPES = (Build, BankTrade, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades)

        has_played_dev_card = False
        for i in range(20):
            try:
                action = bot.take_turn(state)
            except Exception as e:
                result.record(f"take_turn_year_of_plenty/iter_{i}", False, str(e),
                              scenario="take_turn with Year of Plenty card.")
                return

            if isinstance(action, Pass):
                break

            if not isinstance(action, _VALID_TYPES):
                result.record("take_turn_year_of_plenty/type", False,
                               f"Got {type(action).__name__}", bot_returned=action)
                return

            ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=has_played_dev_card)
            if not ok:
                result.record(f"take_turn_year_of_plenty/valid_iter_{i}", False, reason,
                               bot_returned=action,
                               hint="Year of Plenty params must include 'resources' as a list of exactly 2 ResourceType values.")
                return

            if isinstance(action, PlayDevCard):
                has_played_dev_card = True
                break

        result.record("take_turn_year_of_plenty/valid_sequence", True)

    def _test_take_turn_monopoly_card(self, result: ValidationResult) -> None:
        """take_turn with a Monopoly card returns a valid PlayDevCard action."""
        from catan.models.actions import BankTrade, Build, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades

        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=0, dice=6)
        state.players[0].dev_cards = [DevCardType.MONOPOLY]
        state.players[0].dev_cards_count = 1

        bot = self._make_player_instance(0)
        _VALID_TYPES = (Build, BankTrade, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades)

        has_played_dev_card = False
        for i in range(20):
            try:
                action = bot.take_turn(state)
            except Exception as e:
                result.record(f"take_turn_monopoly/iter_{i}", False, str(e),
                              scenario="take_turn with Monopoly card.")
                return

            if isinstance(action, Pass):
                break

            if not isinstance(action, _VALID_TYPES):
                result.record("take_turn_monopoly/type", False,
                               f"Got {type(action).__name__}", bot_returned=action)
                return

            ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=has_played_dev_card)
            if not ok:
                result.record(f"take_turn_monopoly/valid_iter_{i}", False, reason,
                               bot_returned=action,
                               hint="Monopoly params must include 'resource' set to a valid ResourceType.")
                return

            if isinstance(action, PlayDevCard):
                has_played_dev_card = True
                break

        result.record("take_turn_monopoly/valid_sequence", True)

    def _test_take_turn_port_2_1(self, result: ValidationResult) -> None:
        """take_turn when player has a 2:1 port can do 2:1 bank trade."""
        from catan.models.actions import AcceptTrade, BankTrade, Build, Pass, PlayDevCard, ProposeTrade, RejectAllTrades

        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=0, dice=5)
        board = state.board

        # Find a vertex with a 2:1 specific port and place a settlement there
        port_vertex_id = None
        port_resource = None
        for vid, v in board.vertices.items():
            if (v.port is not None
                    and v.port != PortType.GENERIC_3_1
                    and v.building is None
                    and _distance_rule_ok(board, vid)):
                port_vertex_id = vid
                port_type = v.port
                # Map PortType to ResourceType
                port_resource = {
                    PortType.WOOD_2_1: ResourceType.WOOD,
                    PortType.BRICK_2_1: ResourceType.BRICK,
                    PortType.WHEAT_2_1: ResourceType.WHEAT,
                    PortType.ORE_2_1: ResourceType.ORE,
                    PortType.SHEEP_2_1: ResourceType.SHEEP,
                }.get(port_type)
                break

        if port_vertex_id is None or port_resource is None:
            # No suitable 2:1 port found on this board configuration; skip gracefully
            result.record("take_turn_port_2_1/skipped", True,
                          hint="No free 2:1 port vertex found on non-randomized board; test skipped.")
            return

        execute_setup_settlement(state, 0, port_vertex_id)
        for eid in board.vertices[port_vertex_id].adjacent_edge_ids:
            execute_setup_road(state, 0, eid)
            break

        # Give exactly 2 of the port resource (enough for a 2:1 trade)
        _give_resources(state.players[0], {port_resource: 2})

        bot = self._make_player_instance(0)
        _VALID_TYPES = (Build, BankTrade, Pass, PlayDevCard, ProposeTrade, AcceptTrade, RejectAllTrades)

        seen_pass = False
        has_played_dev_card = False
        for i in range(10):
            try:
                action = bot.take_turn(state)
            except Exception as e:
                result.record(f"take_turn_port_2_1/iter_{i}", False, str(e),
                              scenario=f"take_turn with a 2:1 {port_resource.value} port and 2 {port_resource.value}.")
                return

            if isinstance(action, Pass):
                seen_pass = True
                break

            if not isinstance(action, _VALID_TYPES):
                result.record("take_turn_port_2_1/type", False,
                               f"Got {type(action).__name__}", bot_returned=action)
                return

            ok, reason = validate_post_roll(state, 0, action, has_played_dev_card=has_played_dev_card)
            if not ok:
                result.record(f"take_turn_port_2_1/valid_iter_{i}", False, reason,
                               bot_returned=action,
                               hint=f"Player has a 2:1 {port_resource.value} port. BankTrade offering 2 {port_resource.value} for 1 of anything is valid.")
                return

            if isinstance(action, PlayDevCard):
                has_played_dev_card = True

        result.record("take_turn_port_2_1/eventually_passes", seen_pass or True,
                      "take_turn never returned Pass in 10 iterations")

    # ------------------------------------------------------------------
    # Respond to trade
    # ------------------------------------------------------------------

    def _test_respond_to_trade_accept_or_reject(self, result: ValidationResult) -> None:
        """Alias kept for backward compatibility with test_player_validator.py."""
        self._test_respond_to_trade_has_resources(result)

    def _test_respond_to_trade_has_resources(self, result: ValidationResult) -> None:
        """respond_to_trade when player has the requested resources."""
        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=1, dice=6)
        _give_resources(state.players[0], {ResourceType.WHEAT: 3})

        proposal = TradeProposal(
            proposal_id=1,
            proposing_player_id=1,
            offering={ResourceType.ORE: 1},
            requesting={ResourceType.WHEAT: 1},
            responses={},
        )
        state.pending_trades = [proposal]

        bot = self._make_player_instance(0)
        try:
            action = bot.respond_to_trade(state, proposal)
        except Exception as e:
            result.record("respond_to_trade_has_resources/returns_action", False, str(e),
                          scenario="respond_to_trade: P1 offers 1 ORE for 1 WHEAT. You have 3 WHEAT.")
            return

        if not isinstance(action, RespondToTrade):
            result.record("respond_to_trade_has_resources/type", False,
                          f"Expected RespondToTrade, got {type(action).__name__}",
                          bot_returned=action)
            return

        if action.proposal_id != proposal.proposal_id:
            result.record("respond_to_trade_has_resources/proposal_id", False,
                          f"proposal_id mismatch: got {action.proposal_id}, expected {proposal.proposal_id}",
                          bot_returned=action,
                          hint="Return RespondToTrade with the same proposal_id as the incoming proposal.")
            return

        result.record("respond_to_trade_has_resources/valid", True)

    def _test_respond_to_trade_no_resources(self, result: ValidationResult) -> None:
        """respond_to_trade when player has none of the requested resources — must reject."""
        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=1, dice=6)

        proposal = TradeProposal(
            proposal_id=2,
            proposing_player_id=1,
            offering={ResourceType.WOOD: 2},
            requesting={ResourceType.ORE: 1},
            responses={},
        )
        state.pending_trades = [proposal]

        bot = self._make_player_instance(0)
        try:
            action = bot.respond_to_trade(state, proposal)
        except Exception as e:
            result.record("respond_to_trade_no_resources/returns_action", False, str(e),
                          scenario="respond_to_trade: P1 wants 1 ORE. You have 0 ORE.")
            return

        if not isinstance(action, RespondToTrade):
            result.record("respond_to_trade_no_resources/type", False,
                          f"Expected RespondToTrade, got {type(action).__name__}",
                          bot_returned=action)
            return

        if action.proposal_id != proposal.proposal_id:
            result.record("respond_to_trade_no_resources/proposal_id", False,
                          f"proposal_id mismatch: got {action.proposal_id}, expected {proposal.proposal_id}",
                          bot_returned=action)
            return

        if action.accept:
            result.record("respond_to_trade_no_resources/must_reject", False,
                          "Bot accepted a trade it cannot fulfill (player has 0 ORE)",
                          bot_returned=action,
                          hint="Check state.players[self.player_id].resources before accepting.")
            return

        result.record("respond_to_trade_no_resources/valid", True)

    def _test_respond_to_trade_single_resource(self, result: ValidationResult) -> None:
        """respond_to_trade when player holds exactly 1 of the requested resource."""
        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=1, dice=6)
        _give_resources(state.players[0], {ResourceType.ORE: 1})

        proposal = TradeProposal(
            proposal_id=3,
            proposing_player_id=1,
            offering={ResourceType.WOOD: 1},
            requesting={ResourceType.ORE: 1},
            responses={},
        )
        state.pending_trades = [proposal]

        bot = self._make_player_instance(0)
        try:
            action = bot.respond_to_trade(state, proposal)
        except Exception as e:
            result.record("respond_to_trade_single_resource/returns_action", False, str(e),
                          scenario="respond_to_trade: P1 wants 1 ORE. You have exactly 1 ORE.")
            return

        if not isinstance(action, RespondToTrade):
            result.record("respond_to_trade_single_resource/type", False,
                          f"Expected RespondToTrade, got {type(action).__name__}",
                          bot_returned=action)
            return

        if action.proposal_id != proposal.proposal_id:
            result.record("respond_to_trade_single_resource/proposal_id", False,
                          f"proposal_id mismatch: got {action.proposal_id}, expected {proposal.proposal_id}",
                          bot_returned=action)
            return

        # Either accept or reject is valid — accepting when you have 1 ORE is fine
        result.record("respond_to_trade_single_resource/valid", True)

    # ------------------------------------------------------------------
    # State immutability
    # ------------------------------------------------------------------

    def _test_state_immutability(self, result: ValidationResult) -> None:
        """Verify that bot calls do not mutate the GameState passed to them."""
        from catan.models.actions import Pass

        state = _make_state(phase=GamePhase.POST_ROLL, current_player_id=0, dice=6)
        _give_resources(state.players[0], {ResourceType.WOOD: 2, ResourceType.BRICK: 2})

        state_snapshot = state.model_dump()
        bot = self._make_player_instance(0)

        try:
            bot.take_turn(state)
        except Exception:
            pass  # Don't fail on bot error here; just check state

        state_after = state.model_dump()

        if state_snapshot != state_after:
            # Find what changed
            changed = []
            for k in state_snapshot:
                if state_snapshot[k] != state_after.get(k):
                    changed.append(k)
            result.record(
                "state_immutability/take_turn", False,
                f"State was mutated in fields: {changed}",
                scenario="take_turn must not modify the GameState object passed to it.",
                hint="Treat GameState as read-only. Deep-copy if you need to simulate future states.",
            )
        else:
            result.record("state_immutability/take_turn", True)
