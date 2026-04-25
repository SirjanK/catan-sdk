"""
catan.diff — compare two JSONL replay files side-by-side.

Usage::

    python -m catan.diff replay_a.jsonl replay_b.jsonl

    # Diff only turns 1-10
    python -m catan.diff replay_a.jsonl replay_b.jsonl --turns 1-10

    # Show context lines around each difference
    python -m catan.diff replay_a.jsonl replay_b.jsonl --context 2

    # Suppress identical turns (show only turns that differ)
    python -m catan.diff replay_a.jsonl replay_b.jsonl --diff-only

The tool reads the ``action`` records from each replay and compares them turn
by turn.  A turn is considered different when the sequence of actions taken
by any player differs between the two files (ignoring wall-clock timing).

Exit code: 0 if identical, 1 if differences found, 2 on error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_replay(path: str) -> Tuple[dict, dict, List[dict]]:
    """Return (game_start_record, game_end_record, action_records).

    ``action_records`` are only those with type == "action", in file order.
    """
    game_start: dict = {}
    game_end: dict = {}
    actions: List[dict] = []

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = rec.get("type", "")
                if t == "game_start":
                    game_start = rec
                elif t == "game_end":
                    game_end = rec
                elif t == "action":
                    actions.append(rec)
    except OSError as e:
        print(f"Error reading {path!r}: {e}", file=sys.stderr)
        sys.exit(2)

    return game_start, game_end, actions


def _group_by_turn(actions: List[dict]) -> Dict[int, List[dict]]:
    """Group action records by turn number."""
    by_turn: Dict[int, List[dict]] = defaultdict(list)
    for rec in actions:
        turn = rec.get("turn", 0)
        by_turn[turn].append(rec)
    return dict(by_turn)


def _action_sig(rec: dict) -> str:
    """Compact signature for an action record (for comparison)."""
    parts = [
        f"p{rec.get('player_id', '?')}",
        rec.get("action_type", rec.get("action", "?")),
    ]
    details = rec.get("details") or {}
    for key in ("vertex_id", "edge_id", "hex_id", "card", "resource"):
        if key in details:
            parts.append(f"{key}={details[key]}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_DIM = "\033[2m"


def _colour(text: str, code: str) -> str:
    if sys.stdout.isatty():
        return f"{code}{text}{_RESET}"
    return text


def _fmt_action(rec: dict, prefix: str = "  ") -> str:
    sig = _action_sig(rec)
    phase = rec.get("phase", "")
    return f"{prefix}[{phase}] {sig}"


# ---------------------------------------------------------------------------
# Main diff logic
# ---------------------------------------------------------------------------


def diff_replays(
    path_a: str,
    path_b: str,
    turn_range: Optional[Tuple[int, int]] = None,
    context: int = 0,
    diff_only: bool = False,
) -> int:
    """Print a human-readable diff between two JSONL replays.

    Returns 0 if identical, 1 if different.
    """
    gs_a, ge_a, actions_a = _parse_replay(path_a)
    gs_b, ge_b, actions_b = _parse_replay(path_b)

    by_turn_a = _group_by_turn(actions_a)
    by_turn_b = _group_by_turn(actions_b)

    all_turns = sorted(set(by_turn_a) | set(by_turn_b))
    if turn_range:
        lo, hi = turn_range
        all_turns = [t for t in all_turns if lo <= t <= hi]

    # Header
    label_a = Path(path_a).name
    label_b = Path(path_b).name
    print(_colour(f"--- {label_a}", _RED))
    print(_colour(f"+++ {label_b}", _GREEN))

    # Game-level summary
    def _winner(ge: dict) -> str:
        wid = ge.get("winner_id")
        vp = ge.get("winner_vp")
        if wid is None:
            return "no winner (turn limit)"
        return f"player {wid} ({vp} VP)"

    winner_a = _winner(ge_a)
    winner_b = _winner(ge_b)
    seed_a = gs_a.get("seed", "?")
    seed_b = gs_b.get("seed", "?")

    if seed_a != seed_b:
        print(_colour(f"  Seeds differ: {seed_a} vs {seed_b}", _YELLOW))
    if winner_a != winner_b:
        print(_colour(f"  Winner differs: {winner_a}  vs  {winner_b}", _YELLOW))
    else:
        print(_colour(f"  Same winner: {winner_a}", _DIM))

    turns_with_diffs = 0
    context_buffer: List[Tuple[int, str]] = []  # (turn, text) for context lines

    def _flush_context():
        for turn, text in context_buffer:
            print(_colour(f"  (turn {turn})", _DIM))
            print(text)
        context_buffer.clear()

    for turn in all_turns:
        acts_a = by_turn_a.get(turn, [])
        acts_b = by_turn_b.get(turn, [])
        sigs_a = [_action_sig(r) for r in acts_a]
        sigs_b = [_action_sig(r) for r in acts_b]

        if sigs_a == sigs_b:
            if not diff_only and context > 0:
                context_buffer.append((turn, _colour(
                    f"  turn {turn}: " + ", ".join(sigs_a[:3]) +
                    ("…" if len(sigs_a) > 3 else ""),
                    _DIM,
                )))
                if len(context_buffer) > context:
                    context_buffer.pop(0)
            continue

        # Turn differs
        turns_with_diffs += 1
        if context > 0:
            _flush_context()

        print(f"\n{_colour(f'@@ Turn {turn} @@', _CYAN)}")
        for rec in acts_a:
            sig = _action_sig(rec)
            if sig not in sigs_b:
                print(_colour(_fmt_action(rec, prefix="- "), _RED))
            else:
                print(_fmt_action(rec, prefix="  "))
        for rec in acts_b:
            sig = _action_sig(rec)
            if sig not in sigs_a:
                print(_colour(_fmt_action(rec, prefix="+ "), _GREEN))

    if turns_with_diffs == 0:
        print(_colour("\nNo action differences found.", _DIM))
        return 0
    else:
        total = len(all_turns)
        print(
            _colour(
                f"\n{turns_with_diffs}/{total} turn(s) differ.",
                _YELLOW,
            )
        )
        return 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_turn_range(s: str) -> Tuple[int, int]:
    if "-" in s:
        parts = s.split("-", 1)
        return int(parts[0]), int(parts[1])
    n = int(s)
    return n, n


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m catan.diff",
        description="Compare two Catan JSONL replay files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("replay_a", help="First replay (.jsonl)")
    parser.add_argument("replay_b", help="Second replay (.jsonl)")
    parser.add_argument(
        "--turns", metavar="N or N-M", default=None,
        help="Only compare turns in this range (e.g. 5 or 3-10).",
    )
    parser.add_argument(
        "--context", type=int, default=0, metavar="N",
        help="Show N identical turns around each difference (default: 0).",
    )
    parser.add_argument(
        "--diff-only", action="store_true",
        help="Suppress identical turns entirely.",
    )

    args = parser.parse_args(argv)

    turn_range = None
    if args.turns:
        try:
            turn_range = _parse_turn_range(args.turns)
        except ValueError:
            parser.error(f"--turns must be N or N-M, got: {args.turns!r}")

    rc = diff_replays(
        args.replay_a,
        args.replay_b,
        turn_range=turn_range,
        context=args.context,
        diff_only=args.diff_only,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
