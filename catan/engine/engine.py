"""
CatanEngine: orchestrates a full game from board setup through GAME_OVER.

Usage (minimal)::

    from catan.engine import CatanEngine
    from catan.players.basic_player import BasicPlayer

    players = [BasicPlayer(i) for i in range(4)]
    result = CatanEngine(seed=42).run_game(players)

Usage (from config)::

    from catan.config import GameConfig
    from catan.engine import CatanEngine
    from catan.engine.logger import GameLogger
    from catan.players.registry import build_player

    config = GameConfig.load("my_game.yaml")
    players = [build_player(pc, i) for i, pc in enumerate(config.players)]
    engine = CatanEngine(config=config)
    logger = GameLogger(log_dir=config.log_dir)
    result = engine.run_game(players, logger=logger)
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from random import Random
from typing import Callable, Dict, List, Optional, TypeVar

from catan.board.setup import create_board
from catan.engine.executor import (
    distribute_resources,
    execute_bank_trade,
    execute_build_city,
    execute_build_road,
    execute_build_settlement,
    execute_buy_dev_card,
    execute_discard,
    execute_knight,
    execute_move_robber,
    execute_play_dev_card,
    execute_player_trade,
    execute_setup_road,
    execute_setup_settlement,
    give_setup_resources,
    true_vp,
    update_longest_road,
)
from catan.engine.logger import GameLogger
from catan.engine.validator import (
    _distance_rule_ok,
    validate_discard,
    validate_move_robber,
    validate_post_roll,
    validate_pre_roll,
    validate_setup_road,
    validate_setup_settlement,
)
from catan.game import get_game_state
from catan.models.actions import (
    AcceptTrade,
    BankTrade,
    Build,
    City,
    DevCard,
    DiscardCards,
    MoveRobber,
    Pass,
    PlaceRoad,
    PlaceSettlement,
    PlayDevCard,
    PlayKnight,
    ProposeTrade,
    RejectAllTrades,
    RespondToTrade,
    Road,
    RollDice,
    Settlement,
)
from catan.models.enums import DevCardType, GamePhase, ResourceType
from catan.models.state import GameState, PlayerState, TradeProposal
from catan.player import Player

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Dev card deck composition (25 cards total)
# ---------------------------------------------------------------------------

_DEV_DECK: List[DevCardType] = (
    [DevCardType.KNIGHT] * 14
    + [DevCardType.VICTORY_POINT] * 5
    + [DevCardType.ROAD_BUILDING] * 2
    + [DevCardType.YEAR_OF_PLENTY] * 2
    + [DevCardType.MONOPOLY] * 2
)

# Maps phase_name strings to field names on TimeoutsConfig.
# Phases absent from this dict receive no timeout enforcement.
_PHASE_TIMEOUT_FIELD: Dict[str, str] = {
    "SETUP_FORWARD": "setup",
    "SETUP_BACKWARD": "setup",
    "PRE_ROLL": "pre_roll",
    "POST_ROLL": "post_roll",
    "DISCARD": "discard",
    "MOVE_ROBBER": "move_robber",
    "RESPOND_TRADE": "respond_trade",
}

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _action_type(action) -> str:
    """Return a loggable string name for *action*.

    For ``Build`` actions the target variant is included, e.g. ``"build.road"``.
    """
    name = getattr(action, "action", type(action).__name__)
    target = getattr(action, "target", None)
    if target is not None:
        sub = getattr(target, "target", None)
        if sub is not None:
            return f"{name}.{sub}"
    return name


def _extract_action_details(action) -> Optional[Dict]:
    """Return spatial details dict for *action*, or None if not applicable.

    The visualizer uses these to animate placements on the board:
    - ``vertex_id``  for settlement/city placements
    - ``edge_id``    for road placements
    - ``hex_id``     for robber moves and knight plays
    """
    if isinstance(action, (PlaceSettlement,)):
        return {"vertex_id": action.vertex_id}
    if isinstance(action, (PlaceRoad,)):
        return {"edge_id": action.edge_id}
    if isinstance(action, MoveRobber):
        d: Dict = {"hex_id": action.hex_id}
        if action.steal_from_player_id is not None:
            d["steal_from_player_id"] = action.steal_from_player_id
        return d
    if isinstance(action, PlayKnight):
        d = {"hex_id": action.target_hex_id}
        if action.steal_from_player_id is not None:
            d["steal_from_player_id"] = action.steal_from_player_id
        return d
    if isinstance(action, Build):
        target = action.target
        if isinstance(target, Road):
            return {"edge_id": target.edge_id}
        if isinstance(target, (Settlement, City)):
            return {"vertex_id": target.vertex_id}
    if isinstance(action, PlayDevCard):
        d: Dict = {"card": action.card.value}
        if action.params:
            d["params"] = {str(k): v for k, v in action.params.items()}
        return d
    if isinstance(action, BankTrade):
        return {
            "offering": {r.value: n for r, n in action.offering.items() if n > 0},
            "requesting": {r.value: n for r, n in action.requesting.items() if n > 0},
        }
    if isinstance(action, DiscardCards):
        return {
            "resources": {r.value: n for r, n in action.resources.items() if n > 0},
        }
    return None


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class GameResult:
    """Summary of a completed Catan game.

    Attributes:
        winner_id: The player_id of the winner, or None if the game ended
            by hitting the turn limit rather than a natural win condition.
        winner_vp: True VP of the winner at game end, or None if hit_turn_limit.
        final_vp: True VP for every player at game end.
        turn_number: Turn number on which the game ended.
        hit_turn_limit: True when the engine's safety-valve turn cap fired
            before any player reached 10 VP.  Tournament scoring may penalise
            games that trigger this flag.
    """

    winner_id: Optional[int]
    winner_vp: Optional[int]
    final_vp: Dict[int, int]
    turn_number: int
    hit_turn_limit: bool = field(default=False)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class CatanEngine:
    """Runs a complete 4-player Catan game and returns a GameResult.

    Can be constructed with just a seed (backward-compatible)::

        CatanEngine(seed=42)

    Or from a ``GameConfig`` for full control over limits, timeouts, and the
    game ID::

        CatanEngine(config=GameConfig.load("game.yaml"))

    When *config* is provided it takes precedence over *seed*.
    """

    # Class-level defaults used when no config is provided.
    _DEFAULT_MAX_TURNS: int = 500
    _DEFAULT_MAX_INVALID_ACTIONS: int = 3

    def __init__(
        self,
        seed: Optional[int] = None,
        config=None,  # Optional[GameConfig] — typed as Any to avoid circular import
    ) -> None:
        if config is not None:
            self._seed = config.seed
            self._max_turns = config.limits.max_turns
            self._max_invalid_actions = config.limits.max_invalid_actions
            self._timeouts = config.timeouts_ms   # TimeoutsConfig | None
            self._game_id: Optional[str] = config.game_id
        else:
            self._seed = seed
            self._max_turns = self._DEFAULT_MAX_TURNS
            self._max_invalid_actions = self._DEFAULT_MAX_INVALID_ACTIONS
            self._timeouts = None   # no timeout enforcement
            self._game_id = None

        self._executor: Optional[ThreadPoolExecutor] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_game(
        self,
        players: List[Player],
        logger: Optional[GameLogger] = None,
        player_names: Optional[List[str]] = None,
        board=None,  # Optional[Board] — pre-built board for fixed-board simulation
    ) -> GameResult:
        """Play a full game with *players* (must be 4) and return the result.

        If *logger* is provided it will receive structured event records.
        If a ``GameConfig`` was passed to ``__init__``, the config's
        ``game_id`` is forwarded to the logger so log files use a predictable
        name.
        If *player_names* is provided it will be written into the game_start
        record so the visualizer can display names instead of P0/P1/etc.
        If *board* is provided it is used directly (no random generation).
        This enables fixed-board simulation across multiple games.
        """
        if len(players) != 4:
            raise ValueError(f"Expected 4 players, got {len(players)}")

        rng = Random(self._seed)
        self._rng = rng
        self._logger = logger

        # Assign player IDs
        for i, p in enumerate(players):
            p.player_id = i

        if logger:
            logger.start_game(
                seed=self._seed,
                n_players=len(players),
                game_id=self._game_id,
                player_names=player_names,
            )

        # Create executor only when timeouts are configured.
        if self._timeouts is not None:
            self._executor = ThreadPoolExecutor(max_workers=1)
        else:
            self._executor = None

        try:
            if board is None:
                board = create_board(randomize=True, seed=rng.randint(0, 2**31))
            else:
                # Consume the RNG call to keep downstream seeds consistent
                rng.randint(0, 2**31)
            state = self._init_state(board)

            if logger:
                logger.log_board_snapshot(board)

            dev_deck: List[DevCardType] = _DEV_DECK.copy()
            rng.shuffle(dev_deck)
            self._dev_deck = dev_deck

            self._run_setup(state, players)

            while state.phase != GamePhase.GAME_OVER and state.turn_number <= self._max_turns:
                self._run_turn(state, players)

        finally:
            if self._executor is not None:
                self._executor.shutdown(wait=False)
                self._executor = None

        final_vp = {p.player_id: true_vp(state, p.player_id) for p in state.players}

        hit_limit = state.phase != GamePhase.GAME_OVER
        if hit_limit:
            winner_id, winner_vp = None, None
        else:
            winner_id = max(final_vp, key=lambda pid: final_vp[pid])
            winner_vp = final_vp[winner_id]

        if logger:
            logger.end_game(
                winner_id=winner_id,
                winner_vp=winner_vp,
                final_vp=final_vp,
                turn_number=state.turn_number,
                hit_turn_limit=hit_limit,
            )

        return GameResult(
            winner_id=winner_id,
            winner_vp=winner_vp,
            final_vp=final_vp,
            turn_number=state.turn_number,
            hit_turn_limit=hit_limit,
        )

    # ------------------------------------------------------------------
    # Timeout helpers
    # ------------------------------------------------------------------

    def _get_timeout_s(self, phase_name: str) -> Optional[float]:
        """Return timeout in seconds for *phase_name*, or None if unconfigured."""
        if self._timeouts is None:
            return None
        field_name = _PHASE_TIMEOUT_FIELD.get(phase_name)
        if field_name is None:
            return None
        ms = getattr(self._timeouts, field_name, 0.0)
        return ms / 1000.0 if ms > 0 else None

    def _call_timed(self, thunk: Callable[[], T], timeout_s: Optional[float]):
        """Call *thunk()* with an optional wall-clock timeout.

        Returns ``(result, timed_out: bool)``.  When *timed_out* is True,
        *result* is None; the timed-out thread continues running in the
        background until it completes naturally.
        """
        if timeout_s is None or self._executor is None:
            return thunk(), False
        future = self._executor.submit(thunk)
        try:
            return future.result(timeout=timeout_s), False
        except FuturesTimeoutError:
            return None, True

    # ------------------------------------------------------------------
    # Core dispatch helper
    # ------------------------------------------------------------------

    def _player_action(
        self,
        state: GameState,
        pid: int,
        get_action_fn: Callable,
        validate_fn: Callable,
        execute_fn: Callable,
        fallback_fn: Callable,
        phase_name: str = "",
    ) -> bool:
        """Ask the player for a valid action up to ``_max_invalid_actions`` times.

        Both timeout violations and invalid actions count toward the per-turn
        invalid-action limit.  Timing is measured around the player call only.
        """
        timeout_s = self._get_timeout_s(phase_name)

        for attempt in range(self._max_invalid_actions):
            view = get_game_state(state, pid)
            t0 = time.perf_counter()
            action, timed_out = self._call_timed(
                lambda v=view: get_action_fn(v), timeout_s
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            if timed_out:
                if self._logger:
                    self._logger.log_invalid_action(
                        state.turn_number, pid, phase_name,
                        "timeout",
                        f"exceeded {timeout_s * 1000:.0f} ms limit",
                        attempt + 1,
                    )
                continue

            valid, reason = validate_fn(action)
            if valid:
                execute_fn(action)
                state.turn_actions.append(_action_type(action))
                if self._logger:
                    self._logger.log_action(
                        state.turn_number, pid, phase_name,
                        _action_type(action), elapsed_ms,
                        details=_extract_action_details(action),
                    )
                return True

            if self._logger:
                self._logger.log_invalid_action(
                    state.turn_number, pid, phase_name,
                    _action_type(action), reason, attempt + 1,
                )

        fallback_fn()
        return False

    # ------------------------------------------------------------------
    # State initialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _init_state(board) -> GameState:
        players = [
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
                public_vp=0,
                has_longest_road=False,
                has_largest_army=False,
            )
            for i in range(4)
        ]
        return GameState(
            board=board,
            players=players,
            current_player_id=0,
            phase=GamePhase.SETUP_FORWARD,
            turn_number=0,
            dice=None,
            pending_trades=[],
            trades_proposed_this_turn=0,
            dev_cards_remaining=len(_DEV_DECK),
            longest_road_player=None,
            largest_army_player=None,
        )

    # ------------------------------------------------------------------
    # Setup phase
    # ------------------------------------------------------------------

    def _run_setup(self, state: GameState, players: List[Player]) -> None:
        n = len(players)
        # Snake draft: 0,1,2,3,3,2,1,0
        forward = list(range(n))
        backward = list(range(n - 1, -1, -1))

        state.phase = GamePhase.SETUP_FORWARD
        for pid in forward:
            state.current_player_id = pid
            vid = self._do_setup_settlement(state, players[pid], pid)
            self._do_setup_road(state, players[pid], pid, vid)

        state.phase = GamePhase.SETUP_BACKWARD
        for pid in backward:
            state.current_player_id = pid
            vid = self._do_setup_settlement(state, players[pid], pid)
            self._do_setup_road(state, players[pid], pid, vid)
            give_setup_resources(state, pid, vid)

        state.phase = GamePhase.PRE_ROLL
        state.current_player_id = 0
        state.turn_number = 1

    def _do_setup_settlement(
        self, state: GameState, player: Player, pid: int
    ) -> int:
        """Place a setup settlement; return the vertex_id chosen."""
        placed = [None]  # mutable container for closure

        def execute(a):
            execute_setup_settlement(state, pid, a.vertex_id)
            placed[0] = a.vertex_id

        def fallback():
            vid = self._auto_settlement_vid(state)
            execute_setup_settlement(state, pid, vid)
            placed[0] = vid

        phase_name = (
            "SETUP_FORWARD"
            if state.phase == GamePhase.SETUP_FORWARD
            else "SETUP_BACKWARD"
        )
        self._player_action(
            state, pid,
            get_action_fn=lambda view: player.setup_place_settlement(view),
            validate_fn=lambda a: validate_setup_settlement(state.board, pid, a),
            execute_fn=execute,
            fallback_fn=fallback,
            phase_name=phase_name,
        )
        return placed[0]

    def _auto_settlement_vid(self, state: GameState) -> int:
        for vid, vertex in state.board.vertices.items():
            if vertex.building is None and _distance_rule_ok(state.board, vid):
                return vid
        raise RuntimeError("No valid vertex for auto settlement placement")

    def _do_setup_road(
        self, state: GameState, player: Player, pid: int, settlement_vid: int
    ) -> None:
        phase_name = (
            "SETUP_FORWARD"
            if state.phase == GamePhase.SETUP_FORWARD
            else "SETUP_BACKWARD"
        )
        self._player_action(
            state, pid,
            get_action_fn=lambda view: player.setup_place_road(view, settlement_vid),
            validate_fn=lambda a: validate_setup_road(state.board, pid, settlement_vid, a),
            execute_fn=lambda a: execute_setup_road(state, pid, a.edge_id),
            fallback_fn=lambda: self._auto_setup_road(state, pid, settlement_vid),
            phase_name=phase_name,
        )

    def _auto_setup_road(
        self, state: GameState, pid: int, settlement_vid: int
    ) -> None:
        vertex = state.board.vertices[settlement_vid]
        for eid in vertex.adjacent_edge_ids:
            if state.board.edges[eid].road_owner is None:
                execute_setup_road(state, pid, eid)
                return

    # ------------------------------------------------------------------
    # Main turn
    # ------------------------------------------------------------------

    def _run_turn(self, state: GameState, players: List[Player]) -> None:
        pid = state.current_player_id
        player = players[pid]
        state.turn_actions = []   # reset at the start of each turn

        if self._logger:
            self._logger.log_turn_state(state)

        # --- PRE-ROLL ---
        roll, has_played_dev_card = self._do_pre_roll(state, player, pid)

        if self._logger:
            self._logger.log_dice(state.turn_number, pid, roll)

        # --- DICE RESOLUTION ---
        if roll == 7:
            self._handle_seven(state, players, pid)
        else:
            distribute_resources(state, roll)

        state.phase = GamePhase.POST_ROLL

        # --- POST-ROLL ---
        self._do_post_roll(state, players, player, pid, has_played_dev_card)

        if state.phase == GamePhase.GAME_OVER:
            return

        # VP gained during pre-roll (e.g. knight → largest army) is not caught by
        # the post-roll win check when the player simply passes.  Check here so the
        # turn ends immediately rather than advancing to the next player.
        if true_vp(state, pid) >= 10:
            state.phase = GamePhase.GAME_OVER
            return

        # --- ADVANCE TURN ---
        state.current_player_id = (pid + 1) % len(players)
        state.turn_number += 1
        state.dice = None
        state.pending_trades = []
        state.trades_proposed_this_turn = 0
        state.turn_actions = []
        state.phase = GamePhase.PRE_ROLL

    # ------------------------------------------------------------------
    # Pre-roll
    # ------------------------------------------------------------------

    def _do_pre_roll(self, state: GameState, player: Player, pid: int):
        """Handle pre-roll actions; returns (roll_total, has_played_dev_card)."""
        has_played_dev_card = False
        invalid_count = 0
        timeout_s = self._get_timeout_s("PRE_ROLL")

        while True:
            view = get_game_state(state, pid)
            t0 = time.perf_counter()
            action, timed_out = self._call_timed(
                lambda v=view: player.pre_roll_action(v), timeout_s
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            if timed_out:
                invalid_count += 1
                if self._logger:
                    self._logger.log_invalid_action(
                        state.turn_number, pid, "PRE_ROLL",
                        "timeout",
                        f"exceeded {timeout_s * 1000:.0f} ms limit",
                        invalid_count,
                    )
                if invalid_count >= self._max_invalid_actions:
                    break
                continue

            valid, reason = validate_pre_roll(state, pid, action, has_played_dev_card)

            if not valid:
                invalid_count += 1
                if self._logger:
                    self._logger.log_invalid_action(
                        state.turn_number, pid, "PRE_ROLL",
                        _action_type(action), reason, invalid_count,
                    )
                if invalid_count >= self._max_invalid_actions:
                    break
                continue

            invalid_count = 0
            state.turn_actions.append(_action_type(action))
            if self._logger:
                self._logger.log_action(
                    state.turn_number, pid, "PRE_ROLL",
                    _action_type(action), elapsed_ms,
                    details=_extract_action_details(action),
                )

            if isinstance(action, PlayKnight):
                execute_knight(state, pid)
                execute_move_robber(
                    state, pid,
                    action.target_hex_id,
                    action.steal_from_player_id,
                    self._rng,
                )
                has_played_dev_card = True
                # Loop back; next valid action must be RollDice
            else:
                # RollDice
                break

        roll = self._rng.randint(1, 6) + self._rng.randint(1, 6)
        state.dice = roll
        return roll, has_played_dev_card

    # ------------------------------------------------------------------
    # Discard and robber (7-roll)
    # ------------------------------------------------------------------

    def _handle_seven(
        self, state: GameState, players: List[Player], pid: int
    ) -> None:
        state.phase = GamePhase.DISCARDING
        for p in players:
            p_state = state.players[p.player_id]
            if p_state.resource_count > 7:
                required = p_state.resource_count // 2
                self._do_discard(state, p, p.player_id, required)

        state.phase = GamePhase.MOVING_ROBBER
        self._do_move_robber(state, players[pid], pid)

    def _do_discard(
        self, state: GameState, player: Player, pid: int, required: int
    ) -> None:
        self._player_action(
            state, pid,
            get_action_fn=lambda view: player.discard_cards(view, required),
            validate_fn=lambda a: validate_discard(state, pid, a, required),
            execute_fn=lambda a: execute_discard(state, pid, a.resources),
            fallback_fn=lambda: self._auto_discard(state, pid, required),
            phase_name="DISCARD",
        )

    def _auto_discard(self, state: GameState, pid: int, required: int) -> None:
        player = state.players[pid]
        remaining = required
        for res in list(player.resources.keys()):
            if remaining <= 0:
                break
            available = player.resources.get(res, 0)
            if available > 0:
                remove = min(available, remaining)
                player.resources[res] -= remove
                player.resource_count -= remove
                remaining -= remove

    def _do_move_robber(
        self, state: GameState, player: Player, pid: int
    ) -> None:
        self._player_action(
            state, pid,
            get_action_fn=lambda view: player.move_robber(view),
            validate_fn=lambda a: validate_move_robber(state, pid, a),
            execute_fn=lambda a: execute_move_robber(
                state, pid, a.hex_id, a.steal_from_player_id, self._rng
            ),
            fallback_fn=lambda: self._auto_move_robber(state, pid),
            phase_name="MOVE_ROBBER",
        )

    def _auto_move_robber(self, state: GameState, pid: int) -> None:
        for hid in state.board.hexes:
            if hid != state.board.robber_hex_id:
                execute_move_robber(state, pid, hid, None, self._rng)
                return

    # ------------------------------------------------------------------
    # Post-roll
    # ------------------------------------------------------------------

    def _do_post_roll(
        self,
        state: GameState,
        players: List[Player],
        player: Player,
        pid: int,
        has_played_dev_card: bool,
    ) -> None:
        invalid_count = 0
        timeout_s = self._get_timeout_s("POST_ROLL")

        while True:
            view = get_game_state(state, pid)
            t0 = time.perf_counter()
            action, timed_out = self._call_timed(
                lambda v=view: player.take_turn(v), timeout_s
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            if timed_out:
                invalid_count += 1
                if self._logger:
                    self._logger.log_invalid_action(
                        state.turn_number, pid, "POST_ROLL",
                        "timeout",
                        f"exceeded {timeout_s * 1000:.0f} ms limit",
                        invalid_count,
                    )
                if invalid_count >= self._max_invalid_actions:
                    break
                continue

            valid, reason = validate_post_roll(state, pid, action, has_played_dev_card)

            if not valid:
                invalid_count += 1
                if self._logger:
                    self._logger.log_invalid_action(
                        state.turn_number, pid, "POST_ROLL",
                        _action_type(action), reason, invalid_count,
                    )
                if invalid_count >= self._max_invalid_actions:
                    break   # Force pass
                continue

            invalid_count = 0
            state.turn_actions.append(_action_type(action))
            if self._logger:
                self._logger.log_action(
                    state.turn_number, pid, "POST_ROLL",
                    _action_type(action), elapsed_ms,
                    details=_extract_action_details(action),
                )

            if isinstance(action, Pass):
                break
            elif isinstance(action, Build):
                self._execute_build(state, action, pid)
            elif isinstance(action, PlayDevCard):
                execute_play_dev_card(state, pid, action, self._rng)
                has_played_dev_card = True
            elif isinstance(action, ProposeTrade):
                self._handle_propose_trade(state, players, pid, action)
            elif isinstance(action, AcceptTrade):
                self._handle_accept_trade(state, pid, action)
            elif isinstance(action, RejectAllTrades):
                state.pending_trades = [
                    p for p in state.pending_trades
                    if p.proposing_player_id != pid
                ]
            elif isinstance(action, BankTrade):
                execute_bank_trade(state, pid, action.offering, action.requesting)

            # Win check after every valid non-Pass action
            if true_vp(state, pid) >= 10:
                state.phase = GamePhase.GAME_OVER
                return

    def _execute_build(self, state: GameState, action: Build, pid: int) -> None:
        target = action.target
        if isinstance(target, Road):
            execute_build_road(state, pid, target.edge_id)
        elif isinstance(target, Settlement):
            execute_build_settlement(state, pid, target.vertex_id)
        elif isinstance(target, City):
            execute_build_city(state, pid, target.vertex_id)
        elif isinstance(target, DevCard):
            execute_buy_dev_card(state, pid, self._dev_deck)

    # ------------------------------------------------------------------
    # Trade helpers
    # ------------------------------------------------------------------

    def _handle_propose_trade(
        self,
        state: GameState,
        players: List[Player],
        pid: int,
        action: ProposeTrade,
    ) -> None:
        state.trades_proposed_this_turn += 1
        proposal = TradeProposal(
            proposal_id=state.trades_proposed_this_turn,
            proposing_player_id=pid,
            offering=dict(action.offering),
            requesting=dict(action.requesting),
            responses={},
        )
        state.pending_trades.append(proposal)

        timeout_s = self._get_timeout_s("RESPOND_TRADE")

        # Solicit responses from all other players
        for other in players:
            if other.player_id == pid:
                continue
            view = get_game_state(state, other.player_id)
            t0 = time.perf_counter()
            response, timed_out = self._call_timed(
                lambda v=view, p=proposal: other.respond_to_trade(v, p), timeout_s
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            if timed_out:
                proposal.responses[other.player_id] = False
                if self._logger:
                    self._logger.log_invalid_action(
                        state.turn_number, other.player_id, "RESPOND_TRADE",
                        "timeout",
                        f"exceeded {timeout_s * 1000:.0f} ms limit",
                        1,
                    )
            else:
                if (
                    isinstance(response, RespondToTrade)
                    and response.proposal_id == proposal.proposal_id
                ):
                    proposal.responses[other.player_id] = response.accept
                else:
                    proposal.responses[other.player_id] = False

                if self._logger:
                    self._logger.log_action(
                        state.turn_number, other.player_id, "RESPOND_TRADE",
                        "respond_to_trade", elapsed_ms,
                    )

    def _handle_accept_trade(
        self, state: GameState, pid: int, action: AcceptTrade
    ) -> None:
        proposal = next(
            (p for p in state.pending_trades if p.proposal_id == action.proposal_id),
            None,
        )
        if proposal is None:
            return
        execute_player_trade(
            state, pid, action.from_player_id,
            proposal.offering, proposal.requesting,
        )
        state.pending_trades = [
            p for p in state.pending_trades if p.proposal_id != action.proposal_id
        ]
