"""
End-to-end integration test for the Catan game engine.

Runs a complete 4-player game with a fixed seed (42) using BasicPlayer
instances.  The game must reach GAME_OVER, the winner must have >= 10 true VP,
and the game must finish within the engine's 500-turn safety limit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from catan.engine.engine import CatanEngine, GameResult
from catan.engine.executor import true_vp
from catan.engine.logger import GameLogger
from catan.models.enums import GamePhase
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
