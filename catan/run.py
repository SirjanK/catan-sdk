"""
CLI entrypoint for running a Catan game simulation from a config file.

Usage::

    python -m catan.run path/to/game.yaml
    python -m catan.run path/to/game.json

The config file specifies players, limits, timeouts, the log directory, and
an optional game ID.  See ``catan/examples/four_basic_players.yaml`` for a
fully-annotated example.

Output is written to stdout (summary) and to ``<log_dir>/<game_id>.jsonl``
(structured event log).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from catan.config import GameConfig
from catan.engine.engine import CatanEngine
from catan.engine.logger import GameLogger
from catan.players.registry import build_player


def run(config_path: str) -> None:
    config = GameConfig.load(config_path)

    if len(config.players) != 4:
        print(
            f"Error: config must specify exactly 4 players, got {len(config.players)}",
            file=sys.stderr,
        )
        sys.exit(1)

    players = [build_player(pc, i) for i, pc in enumerate(config.players)]
    engine = CatanEngine(config=config)
    logger = GameLogger(log_dir=config.log_dir)

    player_summary = ", ".join(
        f"P{i}:{pc.type}" for i, pc in enumerate(config.players)
    )

    print("Catan Simulation")
    print(f"  Game ID   : {config.game_id}")
    print(f"  Seed      : {config.seed}")
    print(f"  Players   : {player_summary}")
    print(f"  Max turns : {config.limits.max_turns}")
    print(f"  Timeouts  : setup={config.timeouts_ms.setup:.0f}ms"
          f"  pre_roll={config.timeouts_ms.pre_roll:.0f}ms"
          f"  post_roll={config.timeouts_ms.post_roll:.0f}ms"
          f"  respond_trade={config.timeouts_ms.respond_trade:.0f}ms")
    print(f"  Log dir   : {config.log_dir}")
    print()

    wall_t0 = time.perf_counter()
    result = engine.run_game(players, logger=logger)
    wall_ms = (time.perf_counter() - wall_t0) * 1000.0

    print("Result")
    if result.hit_turn_limit:
        print(f"  Outcome   : turn limit reached at turn {result.turn_number}")
    else:
        print(f"  Winner    : Player {result.winner_id}  ({result.winner_vp} VP)")
    vp_str = "  ".join(
        f"P{pid}={vp}" for pid, vp in sorted(result.final_vp.items())
    )
    print(f"  Final VP  : {vp_str}")
    print(f"  Turns     : {result.turn_number}")
    print(f"  Wall time : {wall_ms:.0f} ms")
    log_file = Path(config.log_dir) / f"{config.game_id}.jsonl"
    print(f"  Log file  : {log_file}")


def main() -> None:
    if len(sys.argv) != 2:
        print(
            "Usage: python -m catan.run <config.yaml|config.json>",
            file=sys.stderr,
        )
        sys.exit(1)
    run(sys.argv[1])


if __name__ == "__main__":
    main()
