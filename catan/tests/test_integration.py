"""
End-to-end integration test for the Catan game engine.

Runs a complete 4-player game with a fixed seed (42) using BasicPlayer
instances.  The game must reach GAME_OVER, the winner must have >= 10 true VP,
and the game must finish within the engine's 500-turn safety limit.
"""

from __future__ import annotations

import json
from pathlib import Path
from random import Random
from typing import List

import pytest

from catan.board.setup import create_board
from catan.engine.engine import CatanEngine, GameResult, _DEV_DECK
from catan.engine.executor import true_vp
from catan.engine.logger import GameLogger
from catan.models.actions import (
    DiscardCards,
    MoveRobber,
    Pass,
    PlaceRoad,
    PlaceSettlement,
    PlayKnight,
    RespondToTrade,
    RollDice,
)
from catan.models.enums import DevCardType, GamePhase, ResourceType
from catan.models.state import GameState, PlayerState
from catan.player import Player
from catan.players.basic_player import BasicPlayer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> List[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _records_of(records: List[dict], type_: str) -> List[dict]:
    return [r for r in records if r.get("type") == type_]


class TestFullGameSeed42:
    @pytest.fixture(scope="class")
    def result(self) -> GameResult:
        players = [BasicPlayer(i) for i in range(4)]
        engine = CatanEngine(seed=42)
        return engine.run_game(players)

    def test_game_completes_naturally(self, result: GameResult):
        """Seed-42 must reach GAME_OVER without hitting the turn limit."""
        assert not result.hit_turn_limit, (
            f"Game hit the turn limit at turn {result.turn_number}"
        )

    def test_winner_is_set(self, result: GameResult):
        assert result.winner_id is not None
        assert result.winner_vp is not None

    def test_winner_has_ten_vp(self, result: GameResult):
        """The declared winner must have reached at least 10 VP."""
        assert result.winner_vp >= 10

    def test_all_players_have_nonnegative_vp(self, result: GameResult):
        for pid, vp in result.final_vp.items():
            assert vp >= 0, f"Player {pid} has negative VP: {vp}"

    def test_winner_has_highest_vp(self, result: GameResult):
        """winner_id must be the player with the highest (or tied-highest) VP."""
        max_vp = max(result.final_vp.values())
        assert result.final_vp[result.winner_id] == max_vp

    def test_game_finishes_within_limit(self, result: GameResult):
        """Game must end before the 500-turn safety valve fires."""
        assert result.turn_number <= 500

    def test_game_finishes_in_reasonable_turns(self, result: GameResult):
        """Sanity check: a well-functioning game shouldn't drag on forever."""
        assert result.turn_number <= 400


class TestMultipleSeedsDifferentOutcomes:
    """Smoke test: different seeds should produce valid (possibly different) results."""

    @pytest.mark.parametrize("seed", [0, 1, 7, 13, 99])
    def test_seed_completes(self, seed: int):
        players = [BasicPlayer(i, seed=seed) for i in range(4)]
        result = CatanEngine(seed=seed).run_game(players)
        assert not result.hit_turn_limit
        assert result.winner_vp >= 10
        assert result.turn_number <= 500


class TestEngineInvariants:
    """Additional checks on a fresh game run."""

    @pytest.fixture(scope="class")
    def result(self) -> GameResult:
        players = [BasicPlayer(i) for i in range(4)]
        return CatanEngine(seed=0).run_game(players)

    def test_final_vp_has_four_entries(self, result: GameResult):
        assert len(result.final_vp) == 4

    def test_winner_id_in_range(self, result: GameResult):
        assert result.winner_id is not None
        assert 0 <= result.winner_id <= 3

    def test_turn_number_positive(self, result: GameResult):
        assert result.turn_number > 0

    def test_hit_turn_limit_false(self, result: GameResult):
        assert not result.hit_turn_limit


# ---------------------------------------------------------------------------
# Logging tests
# ---------------------------------------------------------------------------


class TestGameLogging:
    """Verify that GameLogger produces correct, queryable JSONL records."""

    @pytest.fixture(scope="class")
    def logged_game(self, tmp_path_factory):
        """Run seed-42 game with a logger; return (result, records, log_dir)."""
        log_dir = tmp_path_factory.mktemp("catan_logs")
        logger = GameLogger(log_dir=str(log_dir))
        players = [BasicPlayer(i) for i in range(4)]
        result = CatanEngine(seed=42).run_game(players, logger=logger)
        game_file = next(
            f for f in log_dir.glob("*.jsonl") if f.name != "index.jsonl"
        )
        records = _read_jsonl(game_file)
        return result, records, log_dir

    # --- file-level structure ---

    def test_game_file_exists(self, logged_game):
        _, _, log_dir = logged_game
        files = list(log_dir.glob("*.jsonl"))
        # one game file + index.jsonl
        assert len(files) == 2

    def test_index_file_has_one_entry(self, logged_game):
        _, _, log_dir = logged_game
        index_path = log_dir / "index.jsonl"
        assert index_path.exists()
        rows = _read_jsonl(index_path)
        assert len(rows) == 1

    # --- game_start record ---

    def test_game_start_record_present(self, logged_game):
        _, records, _ = logged_game
        starts = _records_of(records, "game_start")
        assert len(starts) == 1

    def test_game_start_seed(self, logged_game):
        _, records, _ = logged_game
        start = _records_of(records, "game_start")[0]
        assert start["seed"] == 42
        assert start["n_players"] == 4

    # --- game_end record matches GameResult ---

    def test_game_end_record_present(self, logged_game):
        _, records, _ = logged_game
        ends = _records_of(records, "game_end")
        assert len(ends) == 1

    def test_game_end_matches_result(self, logged_game):
        result, records, _ = logged_game
        end = _records_of(records, "game_end")[0]
        assert end["winner_id"] == result.winner_id
        assert end["winner_vp"] == result.winner_vp
        assert end["turn_number"] == result.turn_number
        assert end["hit_turn_limit"] == result.hit_turn_limit
        # final_vp keys are stringified in JSON
        for pid, vp in result.final_vp.items():
            assert end["final_vp"][str(pid)] == vp

    def test_game_end_duration_nonnegative(self, logged_game):
        _, records, _ = logged_game
        end = _records_of(records, "game_end")[0]
        assert end["duration_ms"] >= 0.0

    # --- index summary matches game_end ---

    def test_index_matches_game_end(self, logged_game):
        _, records, log_dir = logged_game
        end = _records_of(records, "game_end")[0]
        index_row = _read_jsonl(log_dir / "index.jsonl")[0]
        assert index_row["winner_id"] == end["winner_id"]
        assert index_row["turn_number"] == end["turn_number"]
        assert "type" not in index_row

    # --- turn_state records ---

    def test_turn_states_logged(self, logged_game):
        result, records, _ = logged_game
        states = _records_of(records, "turn_state")
        # One turn_state per main turn; turn_number goes 1..N
        assert len(states) == result.turn_number

    def test_turn_state_has_four_players(self, logged_game):
        _, records, _ = logged_game
        first_state = _records_of(records, "turn_state")[0]
        assert len(first_state["players"]) == 4

    def test_turn_state_player_fields(self, logged_game):
        _, records, _ = logged_game
        state = _records_of(records, "turn_state")[0]
        required_keys = {
            "id", "public_vp", "resource_count", "dev_cards_count",
            "roads_remaining", "settlements_remaining", "cities_remaining",
            "knights_played", "has_longest_road", "has_largest_army",
        }
        for p in state["players"]:
            assert required_keys <= p.keys()

    # --- dice_roll records ---

    def test_dice_rolls_logged(self, logged_game):
        result, records, _ = logged_game
        rolls = _records_of(records, "dice_roll")
        assert len(rolls) == result.turn_number

    def test_dice_roll_values_in_range(self, logged_game):
        _, records, _ = logged_game
        for roll_rec in _records_of(records, "dice_roll"):
            assert 2 <= roll_rec["roll"] <= 12

    # --- action records ---

    def test_action_records_have_elapsed_ms(self, logged_game):
        _, records, _ = logged_game
        actions = _records_of(records, "action")
        assert len(actions) > 0
        for a in actions:
            assert a["elapsed_ms"] >= 0.0

    def test_no_invalid_actions_for_basic_player(self, logged_game):
        """BasicPlayer should never return an invalid action."""
        _, records, _ = logged_game
        invalids = _records_of(records, "invalid_action")
        assert invalids == [], (
            f"Unexpected invalid actions: {invalids}"
        )

    # --- record ordering ---

    def test_game_start_is_first(self, logged_game):
        _, records, _ = logged_game
        assert records[0]["type"] == "game_start"

    def test_game_end_is_last(self, logged_game):
        _, records, _ = logged_game
        assert records[-1]["type"] == "game_end"

    # --- determinism: same seed → identical log content ---

    def test_consecutive_runs_same_seed_same_outcome(self, tmp_path_factory):
        """Two runs with the same seed must produce identical game outcomes."""
        results = []
        for _ in range(2):
            log_dir = tmp_path_factory.mktemp("det_logs")
            logger = GameLogger(log_dir=str(log_dir))
            players = [BasicPlayer(i) for i in range(4)]
            r = CatanEngine(seed=42).run_game(players, logger=logger)
            results.append(r)

        r1, r2 = results
        assert r1.winner_id == r2.winner_id
        assert r1.winner_vp == r2.winner_vp
        assert r1.turn_number == r2.turn_number
        assert r1.final_vp == r2.final_vp

    def test_consecutive_runs_same_seed_same_dice(self, tmp_path_factory):
        """Dice rolls must be identical across deterministic runs."""
        roll_sequences = []
        for _ in range(2):
            log_dir = tmp_path_factory.mktemp("dice_logs")
            logger = GameLogger(log_dir=str(log_dir))
            players = [BasicPlayer(i) for i in range(4)]
            CatanEngine(seed=42).run_game(players, logger=logger)
            game_file = next(
                f for f in log_dir.glob("*.jsonl") if f.name != "index.jsonl"
            )
            records = _read_jsonl(game_file)
            rolls = [r["roll"] for r in _records_of(records, "dice_roll")]
            roll_sequences.append(rolls)

        assert roll_sequences[0] == roll_sequences[1]


# ---------------------------------------------------------------------------
# Turn limit
# ---------------------------------------------------------------------------


class TestTurnLimit:
    """Verify engine behaviour when max_turns is hit before any player wins."""

    def test_hit_turn_limit_flag_set(self):
        import types
        cfg = types.SimpleNamespace(
            seed=0,
            game_id=None,
            limits=types.SimpleNamespace(max_turns=1, max_invalid_actions=3),
            timeouts_ms=None,
        )
        players = [BasicPlayer(i) for i in range(4)]
        result = CatanEngine(config=cfg).run_game(players)
        assert result.hit_turn_limit is True

    def test_hit_turn_limit_winner_is_none(self):
        import types
        cfg = types.SimpleNamespace(
            seed=0,
            game_id=None,
            limits=types.SimpleNamespace(max_turns=1, max_invalid_actions=3),
            timeouts_ms=None,
        )
        players = [BasicPlayer(i) for i in range(4)]
        result = CatanEngine(config=cfg).run_game(players)
        assert result.winner_id is None
        assert result.winner_vp is None

    def test_hit_turn_limit_final_vp_present(self):
        """final_vp must still have 4 entries when the turn limit fires."""
        import types
        cfg = types.SimpleNamespace(
            seed=0,
            game_id=None,
            limits=types.SimpleNamespace(max_turns=1, max_invalid_actions=3),
            timeouts_ms=None,
        )
        players = [BasicPlayer(i) for i in range(4)]
        result = CatanEngine(config=cfg).run_game(players)
        assert len(result.final_vp) == 4

    def test_hit_turn_limit_logged_correctly(self, tmp_path):
        """game_end record should reflect hit_turn_limit=True."""
        import types
        cfg = types.SimpleNamespace(
            seed=0,
            game_id=None,
            limits=types.SimpleNamespace(max_turns=1, max_invalid_actions=3),
            timeouts_ms=None,
        )
        logger = GameLogger(log_dir=str(tmp_path))
        players = [BasicPlayer(i) for i in range(4)]
        CatanEngine(config=cfg).run_game(players, logger=logger)
        game_file = next(f for f in tmp_path.glob("*.jsonl") if f.name != "index.jsonl")
        records = _read_jsonl(game_file)
        end = _records_of(records, "game_end")[0]
        assert end["hit_turn_limit"] is True
        assert end["winner_id"] is None


# ---------------------------------------------------------------------------
# Player names in logs
# ---------------------------------------------------------------------------


class TestPlayerNamesLogging:
    """player_names kwarg should appear in the game_start record."""

    def test_player_names_in_game_start(self, tmp_path):
        names = ["Alice", "Bob", "Carol", "Dave"]
        logger = GameLogger(log_dir=str(tmp_path))
        players = [BasicPlayer(i) for i in range(4)]
        CatanEngine(seed=1).run_game(players, logger=logger, player_names=names)
        game_file = next(f for f in tmp_path.glob("*.jsonl") if f.name != "index.jsonl")
        records = _read_jsonl(game_file)
        start = _records_of(records, "game_start")[0]
        assert start.get("player_names") == names

    def test_no_player_names_key_when_omitted(self, tmp_path):
        logger = GameLogger(log_dir=str(tmp_path))
        players = [BasicPlayer(i) for i in range(4)]
        CatanEngine(seed=1).run_game(players, logger=logger)
        game_file = next(f for f in tmp_path.glob("*.jsonl") if f.name != "index.jsonl")
        records = _read_jsonl(game_file)
        start = _records_of(records, "game_start")[0]
        assert "player_names" not in start


# ---------------------------------------------------------------------------
# Logger close() method
# ---------------------------------------------------------------------------


class TestLoggerClose:
    """GameLogger.close() must be idempotent and release the file handle."""

    def test_close_after_end_game_is_safe(self, tmp_path):
        logger = GameLogger(log_dir=str(tmp_path))
        players = [BasicPlayer(i) for i in range(4)]
        CatanEngine(seed=5).run_game(players, logger=logger)
        # end_game already closed; calling close() again should not raise
        logger.close()
        logger.close()  # idempotent

    def test_close_before_start_is_safe(self, tmp_path):
        logger = GameLogger(log_dir=str(tmp_path))
        logger.close()  # should not raise even though no game was started

    def test_game_id_accessible_after_start(self, tmp_path):
        logger = GameLogger(log_dir=str(tmp_path))
        gid = logger.start_game(seed=3, n_players=4, game_id="test-id")
        assert logger.game_id == "test-id"
        assert gid == "test-id"

    def test_game_id_none_before_start(self, tmp_path):
        logger = GameLogger(log_dir=str(tmp_path))
        assert logger.game_id is None


# ---------------------------------------------------------------------------
# Regression: pre-roll knight → Largest Army → 10 VP without post-roll win check
# ---------------------------------------------------------------------------
#
# Bug: a player who plays a knight in PRE_ROLL that tips them to 10 VP (via
# Largest Army) and then simply Passes in POST_ROLL was not declared the
# winner.  The Pass branch in _do_post_roll broke out of the loop before the
# win check, and _run_turn had no fallback check after _do_post_roll returned.
# The result was that the game continued to the next player's turn.
# ---------------------------------------------------------------------------


class _MinimalPlayer(Player):
    """No-op player whose actions are configured per-instance."""

    def setup_place_settlement(self, state: GameState) -> PlaceSettlement:
        return PlaceSettlement(vertex_id=0)  # fallback; unused in direct _run_turn tests

    def setup_place_road(self, state: GameState, settlement_vid: int) -> PlaceRoad:
        return PlaceRoad(edge_id=0)

    def discard_cards(self, state: GameState, count: int) -> DiscardCards:
        return DiscardCards(resources={})

    def move_robber(self, state: GameState) -> MoveRobber:
        return MoveRobber(hex_id=0, steal_from_player_id=None)

    def pre_roll_action(self, state: GameState) -> PlayKnight | RollDice:
        return RollDice()

    def take_turn(self, state: GameState) -> Pass:
        return Pass()

    def respond_to_trade(self, state: GameState, proposal) -> RespondToTrade:
        return RespondToTrade(proposal_id=proposal.proposal_id, accept=False)


class _KnightThenPassPlayer(_MinimalPlayer):
    """Plays one Knight in pre-roll (to claim Largest Army), then Passes."""

    def __init__(self, target_hex_id: int) -> None:
        self._target_hex_id = target_hex_id
        self._knight_played = False

    def pre_roll_action(self, state: GameState) -> PlayKnight | RollDice:
        if not self._knight_played:
            self._knight_played = True
            return PlayKnight(
                target_hex_id=self._target_hex_id,
                steal_from_player_id=None,
            )
        return RollDice()


def _make_knight_win_fixtures():
    """Build an engine + state for the pre-roll knight win regression scenario.

    Player 0 has 8 public VP and has played 2 knights.  No one holds Largest
    Army yet, so playing a 3rd knight gives the title (+2 VP → 10 VP total).
    """
    board = create_board(randomize=False)
    robber_start = board.robber_hex_id
    non_robber_hex = next(h for h in board.hexes if h != robber_start)

    p0 = PlayerState(
        player_id=0,
        resources={r: 0 for r in ResourceType if r != ResourceType.DESERT},
        dev_cards=[DevCardType.KNIGHT],
        dev_cards_count=1,
        resource_count=0,
        knights_played=2,
        roads_remaining=15,
        settlements_remaining=5,
        cities_remaining=4,
        public_vp=8,
        has_longest_road=False,
        has_largest_army=False,
    )
    others = [
        PlayerState(
            player_id=i,
            resources={r: 0 for r in ResourceType if r != ResourceType.DESERT},
            dev_cards=[],
            dev_cards_count=0,
            resource_count=0,
            knights_played=0,
            roads_remaining=15,
            settlements_remaining=5,
            cities_remaining=4,
            public_vp=2,
            has_longest_road=False,
            has_largest_army=False,
        )
        for i in range(1, 4)
    ]
    state = GameState(
        board=board,
        players=[p0] + others,
        current_player_id=0,
        phase=GamePhase.PRE_ROLL,
        turn_number=1,
        dice=None,
        pending_trades=[],
        trades_proposed_this_turn=0,
        dev_cards_remaining=20,
        longest_road_player=None,
        largest_army_player=None,
    )

    engine = CatanEngine(seed=0)
    engine._rng = Random(0)
    engine._logger = None
    engine._executor = None
    dev_deck = _DEV_DECK.copy()
    Random(0).shuffle(dev_deck)
    engine._dev_deck = dev_deck

    players: List[Player] = [_KnightThenPassPlayer(non_robber_hex)] + [
        _MinimalPlayer() for _ in range(1, 4)
    ]
    # Engine assigns player_id in run_game; replicate that for direct _run_turn use.
    for i, p in enumerate(players):
        p.player_id = i

    return engine, state, players


class TestPreRollKnightWinRegression:
    """Regression tests for the pre-roll knight → Largest Army win bug."""

    def test_phase_is_game_over_after_winning_knight(self):
        """Phase must be GAME_OVER immediately after player 0's winning knight play."""
        engine, state, players = _make_knight_win_fixtures()
        engine._run_turn(state, players)
        assert state.phase == GamePhase.GAME_OVER, (
            f"Expected GAME_OVER; got {state.phase}. "
            f"Player 0 true VP: {true_vp(state, 0)}"
        )

    def test_current_player_not_advanced_after_winning_turn(self):
        """current_player_id must remain 0 (not advance to 1) after the win."""
        engine, state, players = _make_knight_win_fixtures()
        engine._run_turn(state, players)
        assert state.current_player_id == 0, (
            f"Turn advanced to player {state.current_player_id} after player 0 won"
        )

    def test_player_0_has_ten_vp_after_knight(self):
        """Player 0 must have exactly 10 true VP after the knight triggers Largest Army."""
        engine, state, players = _make_knight_win_fixtures()
        engine._run_turn(state, players)
        assert true_vp(state, 0) == 10

    def test_main_loop_stops_after_winning_turn(self):
        """run_game must declare player 0 the winner without playing a next turn."""
        # Wire up real run_game by wrapping engine so we can count how many
        # times _run_turn is called.
        engine, state, players = _make_knight_win_fixtures()
        calls: List[int] = []
        original = engine._run_turn

        def counting_run_turn(s, p):
            calls.append(s.current_player_id)
            original(s, p)

        engine._run_turn = counting_run_turn  # type: ignore[method-assign]

        # Manually run the main loop (mirrors engine.run_game's while loop)
        while state.phase != GamePhase.GAME_OVER and state.turn_number <= 500:
            engine._run_turn(state, players)

        assert state.phase == GamePhase.GAME_OVER
        # Only one turn should have run (player 0's), not two (player 0 then player 1)
        assert len(calls) == 1, (
            f"Expected 1 turn (player 0 wins), but {len(calls)} turns ran: {calls}"
        )
