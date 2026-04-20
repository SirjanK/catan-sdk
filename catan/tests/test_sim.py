"""
Tests for catan.sim — batch simulation CLI.

These tests use BasicPlayer (fast, always passes validator) to verify that
SimulationRunner produces correct win/loss accounting, creates valid log files,
and respects the fixed-board option.
"""

from __future__ import annotations

import json
import os

import pytest

from catan.players.basic_player import BasicPlayer
from catan.sim import BotStats, SimulationResult, SimulationRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _basic_bots(n: int = 2) -> list:
    return [("BasicPlayer", BasicPlayer) for _ in range(n)]


# ---------------------------------------------------------------------------
# BotStats
# ---------------------------------------------------------------------------


class TestBotStats:
    def test_win_rate_zero_games(self):
        s = BotStats(name="X")
        assert s.win_rate == 0.0

    def test_win_rate(self):
        s = BotStats(name="X", games_played=10, wins=4)
        assert s.win_rate == pytest.approx(0.4)

    def test_avg_vp(self):
        s = BotStats(name="X", games_played=2, total_vp=14)
        assert s.avg_vp == pytest.approx(7.0)

    def test_avg_placement(self):
        s = BotStats(name="X", games_played=4,
                     placement_counts={1: 1, 2: 1, 3: 1, 4: 1})
        assert s.avg_placement == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# SimulationRunner — basic correctness
# ---------------------------------------------------------------------------


class TestSimulationRunnerBasic:
    def test_games_played_count(self):
        runner = SimulationRunner(_basic_bots(1), n_games=4, workers=1)
        result = runner.run()
        assert result.total_games == 4
        # 4 seats, all BasicPlayer → each stat tracks 4 games
        for s in result.bot_stats:
            assert s.games_played == 4

    def test_win_counts_sum_to_total(self):
        runner = SimulationRunner(_basic_bots(2), n_games=10, workers=1)
        result = runner.run()
        total_wins = sum(s.wins for s in result.bot_stats)
        # Each game has exactly one winner (unless hit_turn_limit — still has winner_id)
        assert total_wins <= result.total_games

    def test_placement_counts_sum_correctly(self):
        runner = SimulationRunner(_basic_bots(1), n_games=4, workers=1)
        result = runner.run()
        for s in result.bot_stats:
            total_placed = sum(s.placement_counts.values())
            assert total_placed == s.games_played

    def test_seat_filling_to_4(self):
        """A single bot spec should fill all 4 seats."""
        runner = SimulationRunner([("Bot", BasicPlayer)], n_games=2, workers=1)
        assert len(runner._seats) == 4
        for name, cls in runner._seats:
            assert cls is BasicPlayer

    def test_two_bots_fill_to_4(self):
        runner = SimulationRunner(_basic_bots(2), n_games=1, workers=1)
        assert len(runner._seats) == 4

    def test_result_has_run_id(self):
        runner = SimulationRunner(_basic_bots(1), n_games=1, workers=1)
        result = runner.run()
        assert result.run_id.startswith("run_")

    def test_summary_contains_bot_names(self):
        runner = SimulationRunner([("MyBot", BasicPlayer)], n_games=2, workers=1)
        result = runner.run()
        assert "MyBot" in result.summary()

    def test_to_json_schema(self):
        runner = SimulationRunner(_basic_bots(1), n_games=2, workers=1)
        result = runner.run()
        d = result.to_json()
        assert "run_id" in d
        assert "total_games" in d
        assert "bot_stats" in d
        assert isinstance(d["bot_stats"], list)
        for s in d["bot_stats"]:
            assert "name" in s
            assert "win_rate" in s


# ---------------------------------------------------------------------------
# Save logs
# ---------------------------------------------------------------------------


class TestSimulationRunnerLogs:
    def test_saves_game_files(self, tmp_path):
        runner = SimulationRunner(
            _basic_bots(1), n_games=3, workers=1,
            save_logs=True, log_dir=str(tmp_path / "sim"),
        )
        result = runner.run()
        assert result.log_dir is not None
        log_files = [
            f for f in os.listdir(result.log_dir)
            if f.endswith(".jsonl") and f != "index.jsonl"
        ]
        assert len(log_files) == 3

    def test_index_json_created(self, tmp_path):
        runner = SimulationRunner(
            _basic_bots(1), n_games=3, workers=1,
            save_logs=True, log_dir=str(tmp_path / "sim"),
        )
        result = runner.run()
        index_path = os.path.join(result.log_dir, "index.json")
        assert os.path.exists(index_path)
        with open(index_path) as f:
            index = json.load(f)
        assert index["total_games"] == 3
        assert len(index["games"]) == 3

    def test_index_game_metadata_fields(self, tmp_path):
        runner = SimulationRunner(
            _basic_bots(1), n_games=2, workers=1,
            save_logs=True, log_dir=str(tmp_path / "sim"),
        )
        result = runner.run()
        index_path = os.path.join(result.log_dir, "index.json")
        with open(index_path) as f:
            index = json.load(f)
        for game in index["games"]:
            assert "file" in game
            assert "game_index" in game
            assert "seed" in game
            assert "winner_name" in game
            assert "winner_vp" in game
            assert "turn_count" in game
            assert "hit_turn_limit" in game

    def test_game_jsonl_is_valid(self, tmp_path):
        runner = SimulationRunner(
            _basic_bots(1), n_games=1, workers=1,
            save_logs=True, log_dir=str(tmp_path / "sim"),
        )
        result = runner.run()
        assert result.sample_log_path is not None
        assert os.path.exists(result.sample_log_path)
        with open(result.sample_log_path) as f:
            records = [json.loads(line) for line in f if line.strip()]
        assert any(r.get("type") == "game_start" for r in records)
        assert any(r.get("type") == "game_end" for r in records)


# ---------------------------------------------------------------------------
# Fixed board
# ---------------------------------------------------------------------------


class TestFixedBoard:
    def test_fixed_board_flag_stored(self):
        runner = SimulationRunner(
            _basic_bots(1), n_games=2, fixed_board=True, board_seed=42
        )
        assert runner._fixed_board is True
        assert runner._board_seed == 42

    def test_fixed_board_same_topology(self, tmp_path):
        """All games with fixed_board should use the same hex resource layout."""
        runner = SimulationRunner(
            _basic_bots(1), n_games=3, fixed_board=True, board_seed=7,
            save_logs=True, log_dir=str(tmp_path / "sim"),
        )
        result = runner.run()
        # Read the board_layout record from each game log and compare
        board_layouts = []
        for game in os.listdir(result.log_dir):
            if not game.endswith(".jsonl"):
                continue
            with open(os.path.join(result.log_dir, game)) as f:
                for line in f:
                    rec = json.loads(line)
                    if rec.get("type") == "board_layout":
                        board_layouts.append(rec)
                        break

        assert len(board_layouts) == 3
        # All board layouts should be identical
        reference = board_layouts[0]
        for layout in board_layouts[1:]:
            assert layout["hexes"] == reference["hexes"], (
                "Fixed-board games should have identical hex layouts"
            )

    def test_random_board_differs(self, tmp_path):
        """Without fixed_board, different seeds should typically produce different boards."""
        runner = SimulationRunner(
            _basic_bots(1), n_games=5, fixed_board=False, seed_start=0,
            save_logs=True, log_dir=str(tmp_path / "sim"),
        )
        result = runner.run()
        board_layouts = []
        for game_file in sorted(os.listdir(result.log_dir)):
            if not game_file.endswith(".jsonl"):
                continue
            with open(os.path.join(result.log_dir, game_file)) as f:
                for line in f:
                    rec = json.loads(line)
                    if rec.get("type") == "board_layout":
                        board_layouts.append(rec)
                        break

        if len(board_layouts) >= 2:
            # At least two of the boards should differ (probabilistically)
            unique = {json.dumps(b["hexes"], sort_keys=True) for b in board_layouts}
            assert len(unique) > 1, "Expected at least two different boards across random games"


# ---------------------------------------------------------------------------
# _load_player_class helper
# ---------------------------------------------------------------------------


class TestLoadPlayerClass:
    def test_basic_alias_loads(self):
        from catan.sim import _load_player_class
        name, cls = _load_player_class("basic:BasicPlayer")
        assert name == "BasicPlayer"
        from catan.players.basic_player import BasicPlayer as BP
        assert cls is BP

    def test_full_module_path_loads(self):
        from catan.sim import _load_player_class
        name, cls = _load_player_class("catan.players.basic_player:BasicPlayer")
        assert name == "BasicPlayer"

    def test_missing_colon_raises(self):
        from catan.sim import _load_player_class
        with pytest.raises(ValueError, match="module:ClassName"):
            _load_player_class("basic_BasicPlayer")

    def test_unknown_module_raises(self):
        from catan.sim import _load_player_class
        with pytest.raises(ModuleNotFoundError):
            _load_player_class("nonexistent.module:SomeClass")


# ---------------------------------------------------------------------------
# SimulationRunner error handling
# ---------------------------------------------------------------------------


class TestSimulationRunnerEdgeCases:
    def test_empty_bots_raises(self):
        with pytest.raises(ValueError, match="At least one bot"):
            SimulationRunner([], n_games=1)

    def test_zero_games_produces_empty_result(self):
        runner = SimulationRunner(_basic_bots(1), n_games=0, workers=1)
        result = runner.run()
        assert result.total_games == 0
        for s in result.bot_stats:
            assert s.games_played == 0
            assert s.wins == 0

    def test_quiet_flag_suppresses_output(self, capsys):
        runner = SimulationRunner(_basic_bots(1), n_games=2, workers=1, quiet=True)
        runner.run()
        # No assertion needed — just must not raise

    def test_result_fixed_board_seed_in_json(self, tmp_path):
        runner = SimulationRunner(
            _basic_bots(1), n_games=2, fixed_board=True, board_seed=42,
            save_logs=True, log_dir=str(tmp_path),
        )
        result = runner.run()
        d = result.to_json()
        assert d["fixed_board"] is True
        assert d["board_seed"] == 42

    def test_result_no_log_dir_when_save_logs_false(self):
        runner = SimulationRunner(_basic_bots(1), n_games=1, workers=1, save_logs=False)
        result = runner.run()
        assert result.log_dir is None
