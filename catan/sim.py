"""
catan.sim — batch simulation CLI.

Run N games between specified bots and report win rates, average VP, and
placement histograms.  Supports parallel execution and optional fixed-board
mode for controlled A/B testing.

Usage::

    # Basic: 100 games, BasicPlayer vs itself
    python -m catan.sim --bot basic:BasicPlayer --games 100

    # Compare two bots, 4 workers
    python -m catan.sim \\
      --bot submissions.my_bot:MyBot \\
      --bot basic:BasicPlayer \\
      --games 200 --workers 4

    # Fixed board, save logs, write JSON results
    python -m catan.sim \\
      --bot submissions.my_bot:MyBot \\
      --bot basic:BasicPlayer \\
      --games 200 --fixed-board --board-seed 7 \\
      --save-logs --output results.json

    # View results: https://<tournament-site>/viewer → Batch Results tab
    #   → upload tmp/sim/<run_id>/index.json
"""

from __future__ import annotations

import argparse
import copy
import importlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Type

from catan.board.setup import create_board
from catan.engine.engine import CatanEngine, GameResult
from catan.engine.logger import GameLogger
from catan.models.board import Board
from catan.player import Player


# ---------------------------------------------------------------------------
# Stats dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BotStats:
    name: str
    games_played: int = 0
    wins: int = 0
    total_vp: int = 0
    placement_counts: Dict[int, int] = field(
        default_factory=lambda: {1: 0, 2: 0, 3: 0, 4: 0}
    )

    @property
    def win_rate(self) -> float:
        return self.wins / self.games_played if self.games_played else 0.0

    @property
    def avg_vp(self) -> float:
        return self.total_vp / self.games_played if self.games_played else 0.0

    @property
    def avg_placement(self) -> float:
        if not self.games_played:
            return 0.0
        total = sum(place * count for place, count in self.placement_counts.items())
        return total / self.games_played


@dataclass
class SimulationResult:
    total_games: int
    bot_stats: List[BotStats]
    log_dir: Optional[str]
    sample_log_path: Optional[str]
    fixed_board: bool
    board_seed: Optional[int]
    run_id: str

    def _merged_stats(self) -> List[BotStats]:
        """Return bot_stats with duplicate-name rows merged into one."""
        merged: dict[str, BotStats] = {}
        for s in self.bot_stats:
            if s.name not in merged:
                merged[s.name] = BotStats(
                    name=s.name,
                    games_played=s.games_played,
                    wins=s.wins,
                    total_vp=s.total_vp,
                    placement_counts=dict(s.placement_counts),
                )
            else:
                m = merged[s.name]
                m.games_played += s.games_played
                m.wins += s.wins
                m.total_vp += s.total_vp
                for place, count in s.placement_counts.items():
                    m.placement_counts[place] = m.placement_counts.get(place, 0) + count
        # Preserve insertion order (first occurrence)
        seen: list[str] = []
        for s in self.bot_stats:
            if s.name not in seen:
                seen.append(s.name)
        return [merged[n] for n in seen]

    def summary(self) -> str:
        board_info = (
            f"fixed board seed={self.board_seed}"
            if self.fixed_board
            else "random boards"
        )
        lines = [
            f"\nResults — {self.total_games} games, {board_info}",
            f"{'Bot':<24} {'Games':>6} {'Wins':>5} {'Win%':>6}  {'Avg VP':>6}  "
            f"{'Avg Place':>9}  {'1st':>5}{'2nd':>5}{'3rd':>5}{'4th':>5}",
            "-" * 78,
        ]
        for s in self._merged_stats():
            pc = s.placement_counts
            pcts = " ".join(
                f"{(pc.get(i, 0) / s.games_played * 100):.0f}%".rjust(5)
                if s.games_played
                else "  0%"
                for i in range(1, 5)
            )
            lines.append(
                f"{s.name:<24} {s.games_played:>6} {s.wins:>5} {s.win_rate*100:>5.1f}%  "
                f"{s.avg_vp:>6.1f}  {s.avg_placement:>9.1f}  {pcts}"
            )
        if self.log_dir:
            lines.append(f"\nLogs saved to: {self.log_dir}")
            lines.append(
                f"  View results: upload {self.log_dir}/index.json to the "
                f"tournament site's Viewer → Batch Results tab"
            )
        return "\n".join(lines)

    def to_json(self) -> dict:
        return {
            "run_id": self.run_id,
            "total_games": self.total_games,
            "fixed_board": self.fixed_board,
            "board_seed": self.board_seed,
            "bot_stats": [
                {
                    "name": s.name,
                    "games_played": s.games_played,
                    "wins": s.wins,
                    "win_rate": s.win_rate,
                    "avg_vp": s.avg_vp,
                    "avg_placement": s.avg_placement,
                    "placement_counts": {str(k): v for k, v in s.placement_counts.items()},
                }
                for s in self._merged_stats()
            ],
            "log_dir": self.log_dir,
        }


# ---------------------------------------------------------------------------
# Single-game worker (must be picklable for ProcessPoolExecutor)
# ---------------------------------------------------------------------------


def _run_single_game(
    bot_specs: List[Tuple[str, str, str]],  # [(name, module, classname), ...]
    game_index: int,
    seed: int,
    log_dir: Optional[str],
    board_state: Optional[bytes],  # pickled board JSON, or None
) -> dict:
    """Run one game and return a metadata dict.

    Runs in a subprocess worker — everything must be re-imported here.
    """
    import importlib
    import json
    import os
    from catan.engine.engine import CatanEngine
    from catan.engine.logger import GameLogger
    from catan.models.board import Board

    players = []
    names = []
    for name, module_path, class_name in bot_specs:
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        try:
            p = cls(player_id=0)
        except TypeError:
            try:
                p = cls(0)
            except Exception as exc:
                raise RuntimeError(
                    f"Could not instantiate {class_name} from {module_path}. "
                    f"Expected __init__(self, player_id, seed=0) signature. Error: {exc}"
                ) from exc
        players.append(p)
        names.append(name)

    board = None
    if board_state is not None:
        board = Board.model_validate_json(board_state)

    log_path = None
    logger = None
    game_id = f"game_{game_index:04d}" if log_dir else None
    if log_dir is not None:
        os.makedirs(log_dir, exist_ok=True)
        logger = GameLogger(log_dir=log_dir)

    # Use a SimpleNamespace config shim so the engine uses game_id as the log filename
    import types as _types
    cfg = _types.SimpleNamespace(
        seed=seed,
        game_id=game_id,
        limits=_types.SimpleNamespace(max_turns=500, max_invalid_actions=3),
        timeouts_ms=None,
    )
    engine = CatanEngine(config=cfg)
    result = engine.run_game(players, logger=logger, player_names=names, board=board)

    if logger:
        log_path = os.path.join(log_dir, f"{logger.game_id}.jsonl") if logger.game_id else None
        logger.close()

    # Compute placements from final VP (standard competition ranking: ties share rank,
    # next rank skips — e.g. two players tied for 2nd → both get rank 2, next is rank 4).
    final_vp = result.final_vp
    sorted_players = sorted(final_vp.keys(), key=lambda pid: -final_vp[pid])
    placements = {}
    prev_vp = None
    for i, pid in enumerate(sorted_players):
        vp = final_vp[pid]
        if vp != prev_vp:
            rank = i + 1
            prev_vp = vp
        placements[pid] = rank

    return {
        "game_index": game_index,
        "seed": seed,
        "winner_id": result.winner_id,
        "winner_name": names[result.winner_id] if result.winner_id is not None else None,
        "winner_vp": result.winner_vp,
        "turn_count": result.turn_number,
        "hit_turn_limit": result.hit_turn_limit,
        "final_vp": {str(k): v for k, v in final_vp.items()},
        "placements": [names[pid] for pid in range(len(names))],
        "placement_ranks": {str(pid): placements.get(pid, 4) for pid in range(len(names))},
        "log_path": log_path,
    }


# ---------------------------------------------------------------------------
# SimulationRunner
# ---------------------------------------------------------------------------


class SimulationRunner:
    """
    Runs N Catan games between specified bots and aggregates statistics.

    Parameters
    ----------
    bots:
        List of ``(display_name, PlayerClass)`` tuples.  If fewer than 4 are
        provided the list is extended with duplicates to fill 4 seats.
    n_games:
        Total number of games to simulate.
    seed_start:
        Seed for game 0; subsequent games use ``seed_start + game_index``.
    workers:
        Number of parallel worker processes (``ProcessPoolExecutor``).
        Use ``workers=1`` for sequential execution (easier to debug).
    save_logs:
        Write per-game JSONL files to *log_dir*.
    log_dir:
        Directory for game logs when *save_logs* is True (default ``tmp/sim``).
    fixed_board:
        If True, generate one board (using *board_seed*) and reuse it for all
        games.  Bot seeds and seating positions still vary.
    board_seed:
        Seed for the fixed board.  Defaults to *seed_start* when not set.
    quiet:
        Suppress the tqdm progress bar.
    """

    def __init__(
        self,
        bots: List[Tuple[str, Type[Player]]],
        n_games: int,
        seed_start: int = 0,
        workers: int = 1,
        save_logs: bool = False,
        log_dir: str = "tmp/sim",
        fixed_board: bool = False,
        board_seed: Optional[int] = None,
        quiet: bool = False,
    ) -> None:
        if not bots:
            raise ValueError("At least one bot must be provided")
        # Fill to 4 seats by repeating
        seats: List[Tuple[str, Type[Player]]] = list(bots)
        while len(seats) < 4:
            seats.append(bots[len(seats) % len(bots)])
        self._seats = seats[:4]
        self._n_games = n_games
        self._seed_start = seed_start
        self._workers = workers
        self._save_logs = save_logs
        self._log_dir = log_dir
        self._fixed_board = fixed_board
        self._board_seed = board_seed if board_seed is not None else seed_start
        self._quiet = quiet

    def run(self) -> SimulationResult:
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        run_log_dir: Optional[str] = None
        if self._save_logs:
            run_log_dir = os.path.join(self._log_dir, run_id)
            os.makedirs(run_log_dir, exist_ok=True)

        # Serialize bot specs for subprocess workers
        bot_specs: List[Tuple[str, str, str]] = []
        for name, cls in self._seats:
            bot_specs.append((name, cls.__module__, cls.__name__))

        # Pre-build fixed board (serialize to JSON bytes for pickling)
        board_state: Optional[bytes] = None
        if self._fixed_board:
            fixed = create_board(randomize=True, seed=self._board_seed)
            board_state = fixed.model_dump_json().encode()

        # Build tasks
        tasks = [
            (bot_specs, i, self._seed_start + i, run_log_dir, board_state)
            for i in range(self._n_games)
        ]

        game_records = []
        progress = None
        if not self._quiet:
            try:
                from tqdm import tqdm
                progress = tqdm(total=self._n_games, unit="game")
            except ImportError:
                pass

        try:
            if self._workers > 1:
                with ProcessPoolExecutor(max_workers=self._workers) as pool:
                    futures = {pool.submit(_run_single_game, *t): t[1] for t in tasks}
                    for fut in as_completed(futures):
                        game_records.append(fut.result())
                        if progress:
                            progress.update(1)
            else:
                for t in tasks:
                    game_records.append(_run_single_game(*t))
                    if progress:
                        progress.update(1)
        finally:
            if progress:
                progress.close()

        # Sort by game index for consistent output
        game_records.sort(key=lambda r: r["game_index"])

        # Aggregate stats per bot (by seat index → display name)
        seat_names = [name for name, _ in self._seats]
        # Use seat index as key since names may repeat
        seat_stats: List[BotStats] = [BotStats(name=name) for name in seat_names]

        for rec in game_records:
            ranks = rec["placement_ranks"]
            final_vp = {int(k): v for k, v in rec["final_vp"].items()}
            for seat_idx in range(4):
                stat = seat_stats[seat_idx]
                stat.games_played += 1
                vp = final_vp.get(seat_idx, 0)
                stat.total_vp += vp
                rank = int(ranks.get(str(seat_idx), 4))
                stat.placement_counts[rank] = stat.placement_counts.get(rank, 0) + 1
                if rec["winner_id"] == seat_idx:
                    stat.wins += 1

        sample_log: Optional[str] = None
        if run_log_dir and game_records:
            sample_log = game_records[0].get("log_path")

        # Write index.json
        if run_log_dir:
            index = {
                "run_id": run_id,
                "total_games": self._n_games,
                "bots": seat_names,
                "fixed_board": self._fixed_board,
                "board_seed": self._board_seed if self._fixed_board else None,
                "games": [
                    {
                        "file": os.path.basename(r["log_path"]) if r.get("log_path") else None,
                        "game_index": r["game_index"],
                        "seed": r["seed"],
                        "winner_name": r["winner_name"],
                        "winner_vp": r["winner_vp"],
                        "turn_count": r["turn_count"],
                        "hit_turn_limit": r["hit_turn_limit"],
                        "placements": r["placements"],
                    }
                    for r in game_records
                ],
            }
            index_path = os.path.join(run_log_dir, "index.json")
            with open(index_path, "w") as f:
                json.dump(index, f, indent=2)

        return SimulationResult(
            total_games=self._n_games,
            bot_stats=seat_stats,
            log_dir=run_log_dir,
            sample_log_path=sample_log,
            fixed_board=self._fixed_board,
            board_seed=self._board_seed if self._fixed_board else None,
            run_id=run_id,
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _load_player_class(spec: str) -> Tuple[str, Type[Player]]:
    """Load a bot from 'module:ClassName' or 'alias:ClassName'.

    Special aliases:
      - ``basic`` → ``catan.players.basic_player``
    """
    if ":" not in spec:
        raise ValueError(f"--bot must be in the form 'module:ClassName', got: {spec!r}")
    module_path, class_name = spec.rsplit(":", 1)
    if module_path == "basic":
        module_path = "catan.players.basic_player"
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return class_name, cls


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m catan.sim",
        description="Batch Catan simulation. Run --bot multiple times to add bots.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--bot", metavar="MODULE:CLASS", action="append", dest="bots", default=[],
        help="Bot to include (repeat for multiple; seats filled with duplicates if < 4).",
    )
    parser.add_argument("--games", type=int, default=100, metavar="N",
                        help="Number of games to simulate (default: 100).")
    parser.add_argument("--seed", type=int, default=0, metavar="N",
                        help="Starting game seed (default: 0).")
    parser.add_argument("--workers", type=int, default=1, metavar="N",
                        help="Parallel worker processes (default: 1).")
    parser.add_argument("--fixed-board", action="store_true",
                        help="Generate the board once and reuse it for all games.")
    parser.add_argument("--board-seed", type=int, default=None, metavar="N",
                        help="Seed for the fixed board (default: same as --seed).")
    parser.add_argument("--save-logs", action="store_true",
                        help="Write per-game JSONL files to --log-dir.")
    parser.add_argument("--log-dir", default="tmp/sim", metavar="PATH",
                        help="Directory for game logs (default: tmp/sim/).")
    parser.add_argument("--output", default=None, metavar="FILE",
                        help="Write JSON results summary to this file.")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress progress bar.")

    args = parser.parse_args(argv)

    if not args.bots:
        parser.error("At least one --bot is required.")

    bots: List[Tuple[str, Type[Player]]] = []
    for spec in args.bots:
        try:
            bots.append(_load_player_class(spec))
        except Exception as e:
            parser.error(f"Could not load bot {spec!r}: {e}")

    board_info = ""
    if args.fixed_board:
        bseed = args.board_seed if args.board_seed is not None else args.seed
        board_info = f", fixed board seed={bseed}"

    seat_names = []
    while len(seat_names) < 4:
        seat_names.append(bots[len(seat_names) % len(bots)][0])

    print(
        f"Running {args.games} games across {len(bots)} bot(s)"
        f" ({args.workers} worker{'s' if args.workers > 1 else ''}{board_info})..."
    )

    runner = SimulationRunner(
        bots=bots,
        n_games=args.games,
        seed_start=args.seed,
        workers=args.workers,
        save_logs=args.save_logs,
        log_dir=args.log_dir,
        fixed_board=args.fixed_board,
        board_seed=args.board_seed,
        quiet=args.quiet,
    )

    result = runner.run()
    print(result.summary())

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result.to_json(), f, indent=2)
        print(f"\nJSON results written to: {args.output}")


if __name__ == "__main__":
    main()
