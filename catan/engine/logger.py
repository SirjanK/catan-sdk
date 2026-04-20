"""
GameLogger: writes structured JSONL event records during a Catan game.

File layout::

    <log_dir>/
        <game_id>.jsonl   — full event stream for one game
        index.jsonl       — one summary line appended per completed game

Record ``type`` values:

* ``game_start``     — metadata written when a game begins
* ``board_layout``   — full board topology written once after setup (hex geometry,
                       vertex/edge adjacency, port assignments, initial robber hex)
* ``turn_state``     — compact per-player snapshot at the start of each main turn
* ``dice_roll``      — dice sum for the current turn
* ``action``         — a valid player action with elapsed time and optional spatial details
* ``invalid_action`` — an invalid player action with the rejection reason
* ``game_end``       — final result written when the game finishes
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from catan.board.topology import PORT_VERTEX_PAIRS
from catan.models.board import Board
from catan.models.enums import ResourceType
from catan.models.state import GameState


class GameLogger:
    """Append-only JSONL logger for a single Catan game."""

    def __init__(self, log_dir: str = "tmp/games") -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._game_id: Optional[str] = None
        self._seed: Optional[int] = None
        self._file = None
        self._start_time: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_game(
        self,
        seed: Optional[int],
        n_players: int,
        game_id: Optional[str] = None,
        player_names: Optional[List[str]] = None,
    ) -> str:
        """Open a new game log file and write the ``game_start`` record.

        Returns the game_id (auto-generated UUID4 if not provided).
        """
        self._game_id = game_id or str(uuid.uuid4())
        self._seed = seed
        self._start_time = time.perf_counter()
        path = self._log_dir / f"{self._game_id}.jsonl"
        self._file = open(path, "w", encoding="utf-8")  # noqa: SIM115
        record: Dict[str, Any] = {
            "type": "game_start",
            "game_id": self._game_id,
            "seed": seed,
            "n_players": n_players,
            "ts": time.time(),
        }
        if player_names is not None:
            record["player_names"] = player_names
        self._write(record)
        return self._game_id

    def end_game(
        self,
        winner_id: Optional[int],
        winner_vp: Optional[int],
        final_vp: Dict[int, int],
        turn_number: int,
        hit_turn_limit: bool,
    ) -> None:
        """Write the ``game_end`` record, close the file, and update the index."""
        duration_ms = (time.perf_counter() - self._start_time) * 1000.0
        record: Dict[str, Any] = {
            "type": "game_end",
            "game_id": self._game_id,
            "seed": self._seed,
            "winner_id": winner_id,
            "winner_vp": winner_vp,
            "final_vp": {str(k): v for k, v in final_vp.items()},
            "turn_number": turn_number,
            "hit_turn_limit": hit_turn_limit,
            "duration_ms": round(duration_ms, 2),
            "ts": time.time(),
        }
        self._write(record)
        if self._file is not None:
            self._file.close()
            self._file = None

        # Append a summary row to the shared index (without the "type" key).
        summary = {k: v for k, v in record.items() if k != "type"}
        index_path = self._log_dir / "index.jsonl"
        with open(index_path, "a", encoding="utf-8") as idx:
            idx.write(json.dumps(summary) + "\n")

    def log_board_snapshot(self, board: Board) -> None:
        """Write a ``board_layout`` record capturing the full board topology.

        This is emitted once per game, immediately after the board is created
        (before setup placements).  Visualization code reads this record to
        reconstruct hex positions, port locations, and the initial robber hex
        without importing any engine modules.
        """
        hexes = []
        for h in board.hexes.values():
            hexes.append({
                "hex_id": h.hex_id,
                "q": h.q,
                "r": h.r,
                "resource": h.resource.value,
                "number": h.number,
                "vertex_ids": h.vertex_ids,
                "edge_ids": h.edge_ids,
            })

        vertices = []
        for v in board.vertices.values():
            vertices.append({
                "vertex_id": v.vertex_id,
                "adjacent_hex_ids": v.adjacent_hex_ids,
                "adjacent_edge_ids": v.adjacent_edge_ids,
                "adjacent_vertex_ids": v.adjacent_vertex_ids,
                "port": v.port.value if v.port is not None else None,
            })

        edges = []
        for e in board.edges.values():
            edges.append({
                "edge_id": e.edge_id,
                "vertex_ids": list(e.vertex_ids),
            })

        self._write({
            "type": "board_layout",
            "game_id": self._game_id,
            "hexes": hexes,
            "vertices": vertices,
            "edges": edges,
            "port_edges": [[va, vb] for va, vb in PORT_VERTEX_PAIRS],
            "robber_hex_id": board.robber_hex_id,
        })

    # ------------------------------------------------------------------
    # Per-event logging
    # ------------------------------------------------------------------

    def log_turn_state(self, state: GameState) -> None:
        """Compact per-player snapshot logged at the start of each main turn.

        Includes the full dev card hand for every player (hidden from
        opponents during play, but recorded in the log for post-game analysis
        and visualization).
        """
        self._write({
            "type": "turn_state",
            "game_id": self._game_id,
            "turn": state.turn_number,
            "current_player_id": state.current_player_id,
            "players": [
                {
                    "id": p.player_id,
                    "public_vp": p.public_vp,
                    "resource_count": p.resource_count,
                    "resources": {r.value: cnt for r, cnt in p.resources.items()},
                    "dev_cards_count": p.dev_cards_count,
                    "dev_cards": [c.value for c in p.dev_cards],
                    "roads_remaining": p.roads_remaining,
                    "settlements_remaining": p.settlements_remaining,
                    "cities_remaining": p.cities_remaining,
                    "knights_played": p.knights_played,
                    "has_longest_road": p.has_longest_road,
                    "has_largest_army": p.has_largest_army,
                }
                for p in state.players
            ],
        })

    def log_dice(self, turn: int, player_id: int, roll: int) -> None:
        """Record the dice sum for the current turn."""
        self._write({
            "type": "dice_roll",
            "game_id": self._game_id,
            "turn": turn,
            "player_id": player_id,
            "roll": roll,
        })

    def log_action(
        self,
        turn: int,
        player_id: int,
        phase: str,
        action_type: str,
        elapsed_ms: float,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a valid player action and how long it took.

        *details* carries spatial context used by the visualizer:
        ``vertex_id``, ``edge_id``, or ``hex_id`` depending on the action type.
        """
        record: Dict[str, Any] = {
            "type": "action",
            "game_id": self._game_id,
            "turn": turn,
            "player_id": player_id,
            "phase": phase,
            "action": action_type,
            "elapsed_ms": round(elapsed_ms, 3),
        }
        if details:
            record["details"] = details
        self._write(record)

    def log_invalid_action(
        self,
        turn: int,
        player_id: int,
        phase: str,
        action_type: str,
        reason: str,
        attempt: int,
    ) -> None:
        """Record a rejected player action."""
        self._write({
            "type": "invalid_action",
            "game_id": self._game_id,
            "turn": turn,
            "player_id": player_id,
            "phase": phase,
            "action": action_type,
            "reason": reason,
            "attempt": attempt,
        })

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def game_id(self) -> Optional[str]:
        """Return the current game ID, or None if no game has started."""
        return self._game_id

    def close(self) -> None:
        """Close the underlying log file if it is still open.

        Safe to call multiple times.  The engine calls ``end_game()`` which
        already closes the file; this method is provided so external callers
        (e.g. the simulation runner) can clean up without relying on
        ``end_game()`` having been called.
        """
        if self._file is not None:
            self._file.close()
            self._file = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(self, record: Dict[str, Any]) -> None:
        if self._file is not None:
            self._file.write(json.dumps(record) + "\n")
