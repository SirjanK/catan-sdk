"""
PlannerBot — a goal-committed Catan bot.

Strategy:
  Pick one build goal at the start of each plan cycle and commit to it:
    city > settlement > road > dev_card

  Within the plan, use bank/port trades each turn to close the resource
  deficit.  Re-evaluate the plan only when:
    1. The current goal is achieved (naturally advances to the next goal).
    2. The current goal is no longer achievable (e.g. no settlement spots).
    3. We hold > 7 cards — in that case we may shift plan and trade down.

  This committed style avoids the resource dilution that happens when a bot
  greedily re-targets every turn.
"""

from __future__ import annotations

from random import Random
from typing import Dict, Optional, Tuple

from catan.engine.validator import (
    CITY_COST,
    DEV_CARD_COST,
    ROAD_COST,
    SETTLEMENT_COST,
    _distance_rule_ok,
    get_port_ratio,
)
from catan.models.actions import (
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
    RespondToTrade,
    Road,
    RollDice,
    Settlement,
)
from catan.models.enums import DevCardType, ResourceType
from catan.models.state import GameState, PlayerState, TradeProposal
from catan.player import Player
from catan.players.helpers import (
    PIPS,
    best_city_vertex,
    has_resources,
    owned_resource_types,
    resource_deficit,
    valid_road_edges,
    valid_settlement_spots,
    vertex_pip_score,
    vertex_resource_types,
)

_COSTS: Dict[str, Dict[ResourceType, int]] = {
    "city": CITY_COST,
    "settlement": SETTLEMENT_COST,
    "road": ROAD_COST,
    "dev_card": DEV_CARD_COST,
}


class PlannerBot(Player):
    """Commits to one build goal at a time and single-mindedly works toward it."""

    def __init__(self, player_id: int, seed: int = 0) -> None:
        self.player_id = player_id
        self._rng = Random(seed + player_id)
        self._current_plan: Optional[str] = None
        self._bank_trades_this_turn: int = 0

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup_place_settlement(self, state: GameState) -> PlaceSettlement:
        board = state.board
        pid = self.player_id
        owned = owned_resource_types(board, pid)
        best_score, best_vid = -1.0, -1
        for vid, v in board.vertices.items():
            if v.building is not None:
                continue
            if not _distance_rule_ok(board, vid):
                continue
            score = self._vertex_setup_score(board, vid, owned)
            if score > best_score:
                best_score, best_vid = score, vid
        return PlaceSettlement(vertex_id=best_vid)

    def setup_place_road(
        self, state: GameState, settlement_vertex_id: int
    ) -> PlaceRoad:
        board = state.board
        vertex = board.vertices[settlement_vertex_id]
        best_score, best_eid = -1, None
        for eid in vertex.adjacent_edge_ids:
            if board.edges[eid].road_owner is not None:
                continue
            far_vid = next(
                v for v in board.edges[eid].vertex_ids if v != settlement_vertex_id
            )
            far_v = board.vertices[far_vid]
            score = vertex_pip_score(board, far_vid)
            if far_v.building is None and _distance_rule_ok(board, far_vid):
                score += 15
            if far_v.port is not None:
                score += 10
            if score > best_score:
                best_score, best_eid = score, eid
        if best_eid is None:
            best_eid = vertex.adjacent_edge_ids[0]
        return PlaceRoad(edge_id=best_eid)

    # ------------------------------------------------------------------
    # Pre-roll
    # ------------------------------------------------------------------

    def pre_roll_action(self, state: GameState) -> PlayKnight | RollDice:
        self._bank_trades_this_turn = 0
        player = state.players[self.player_id]
        if DevCardType.KNIGHT in player.dev_cards:
            board = state.board
            robber_hex = board.hexes[board.robber_hex_id]
            blocks_us = any(
                board.vertices[vid].building is not None
                and board.vertices[vid].building.player_id == self.player_id
                for vid in robber_hex.vertex_ids
            )
            if blocks_us and PIPS.get(robber_hex.number or 0, 0) >= 4:
                hex_id, steal_from = self._best_robber_target(state)
                return PlayKnight(
                    target_hex_id=hex_id, steal_from_player_id=steal_from
                )
        return RollDice()

    # ------------------------------------------------------------------
    # Discard
    # ------------------------------------------------------------------

    def discard_cards(self, state: GameState, count: int) -> DiscardCards:
        player = state.players[self.player_id]
        goal_cost = _COSTS.get(self._current_plan or "", {})

        # Protect what's needed for the current plan; discard everything else first
        protect: Dict[ResourceType, int] = {}
        for r, need in goal_cost.items():
            protect[r] = min(player.resources.get(r, 0), need)

        candidates = []
        for r, amt in player.resources.items():
            if r == ResourceType.DESERT or amt == 0:
                continue
            spare = amt - protect.get(r, 0)
            if spare > 0:
                candidates.append((spare, r in goal_cost, r))
        # Non-goal resources first, then largest surplus first
        candidates.sort(key=lambda x: (x[1], -x[0]))

        to_discard: Dict[ResourceType, int] = {}
        remaining = count
        for spare, _, r in candidates:
            if remaining <= 0:
                break
            take = min(spare, remaining)
            to_discard[r] = take
            remaining -= take

        # Safety net
        if remaining > 0:
            for r, amt in sorted(player.resources.items(), key=lambda x: -x[1]):
                if r == ResourceType.DESERT or remaining <= 0:
                    continue
                already = to_discard.get(r, 0)
                take = min(amt - already, remaining)
                if take > 0:
                    to_discard[r] = already + take
                    remaining -= take

        return DiscardCards(resources=to_discard)

    # ------------------------------------------------------------------
    # Move robber
    # ------------------------------------------------------------------

    def move_robber(self, state: GameState) -> MoveRobber:
        hex_id, steal_from = self._best_robber_target(state)
        return MoveRobber(hex_id=hex_id, steal_from_player_id=steal_from)

    # ------------------------------------------------------------------
    # Main turn
    # ------------------------------------------------------------------

    def take_turn(self, state: GameState):  # noqa: ANN201
        player = state.players[self.player_id]

        # VP dev cards are always free — reveal immediately
        if DevCardType.VICTORY_POINT in player.dev_cards:
            return PlayDevCard(card=DevCardType.VICTORY_POINT, params={})

        # Establish / reconfirm current plan
        if self._current_plan is None or not self._plan_still_valid(state):
            self._current_plan = self._choose_plan(state)

        plan = self._current_plan
        if plan is None:
            return Pass()

        cost = _COSTS[plan]

        # If we can afford the goal, execute it
        if has_resources(player, cost):
            action = self._execute_plan(plan, state)
            if action is not None:
                self._current_plan = None  # goal achieved; re-evaluate next call
                return action

        # Over-7 safety valve: trade down excess before it forces a discard.
        # At this point we can't build yet, so we shift to the plan closest to
        # affordable given our current hand (may be the same plan).
        if player.resource_count > 7 and self._bank_trades_this_turn < 2:
            shifted = self._choose_plan_for_hand(state, player)
            if shifted is not None:
                self._current_plan = shifted
                plan = shifted
                cost = _COSTS[plan]
            trade = self._trade_toward_goal(state, player, cost)
            if trade is not None:
                self._bank_trades_this_turn += 1
                return trade

        # Normal case: bank-trade toward goal (up to 2 per turn)
        if self._bank_trades_this_turn < 2:
            trade = self._trade_toward_goal(state, player, cost)
            if trade is not None:
                self._bank_trades_this_turn += 1
                return trade

        return Pass()

    # ------------------------------------------------------------------
    # Respond to trade
    # ------------------------------------------------------------------

    def respond_to_trade(
        self, state: GameState, proposal: TradeProposal
    ) -> RespondToTrade:
        player = state.players[self.player_id]
        for res, amt in proposal.requesting.items():
            if player.resources.get(res, 0) < amt:
                return RespondToTrade(proposal_id=proposal.proposal_id, accept=False)

        goal_cost = _COSTS.get(self._current_plan or "", {})
        if goal_cost:
            deficit = resource_deficit(player, goal_cost)
            for res in proposal.requesting:
                if deficit.get(res, 0) > 0:
                    return RespondToTrade(proposal_id=proposal.proposal_id, accept=False)
            for res in proposal.offering:
                if deficit.get(res, 0) > 0:
                    return RespondToTrade(proposal_id=proposal.proposal_id, accept=True)

        return RespondToTrade(proposal_id=proposal.proposal_id, accept=False)

    # ------------------------------------------------------------------
    # Plan selection
    # ------------------------------------------------------------------

    def _choose_plan(self, state: GameState) -> Optional[str]:
        """Pick the highest-priority build goal that is currently reachable."""
        player = state.players[self.player_id]
        board = state.board
        pid = self.player_id

        if player.cities_remaining > 0 and best_city_vertex(board, pid) is not None:
            return "city"
        if player.settlements_remaining > 0 and valid_settlement_spots(board, pid):
            return "settlement"
        if player.roads_remaining > 0 and valid_road_edges(board, pid):
            return "road"
        if state.dev_cards_remaining > 0:
            return "dev_card"
        return None

    def _choose_plan_for_hand(
        self, state: GameState, player: PlayerState
    ) -> Optional[str]:
        """When holding > 7 cards, pick the plan closest to affordable right now."""
        board = state.board
        pid = self.player_id

        def _closeness(plan: str) -> int:
            cost = _COSTS[plan]
            return sum(resource_deficit(player, cost).values())

        candidates = []
        if player.cities_remaining > 0 and best_city_vertex(board, pid) is not None:
            candidates.append("city")
        if player.settlements_remaining > 0 and valid_settlement_spots(board, pid):
            candidates.append("settlement")
        if player.roads_remaining > 0 and valid_road_edges(board, pid):
            candidates.append("road")
        if state.dev_cards_remaining > 0:
            candidates.append("dev_card")

        if not candidates:
            return None
        return min(candidates, key=_closeness)

    def _plan_still_valid(self, state: GameState) -> bool:
        plan = self._current_plan
        player = state.players[self.player_id]
        board = state.board
        pid = self.player_id
        if plan == "city":
            return player.cities_remaining > 0 and best_city_vertex(board, pid) is not None
        if plan == "settlement":
            return player.settlements_remaining > 0 and bool(
                valid_settlement_spots(board, pid)
            )
        if plan == "road":
            return player.roads_remaining > 0 and bool(valid_road_edges(board, pid))
        if plan == "dev_card":
            return state.dev_cards_remaining > 0
        return False

    # ------------------------------------------------------------------
    # Plan execution
    # ------------------------------------------------------------------

    def _execute_plan(self, plan: str, state: GameState):
        board = state.board
        pid = self.player_id
        if plan == "city":
            vid = best_city_vertex(board, pid)
            if vid is not None:
                return Build(target=City(vertex_id=vid))
        elif plan == "settlement":
            spots = valid_settlement_spots(board, pid)
            if spots:
                best = max(spots, key=lambda v: vertex_pip_score(board, v))
                return Build(target=Settlement(vertex_id=best))
        elif plan == "road":
            edges = valid_road_edges(board, pid)
            if edges:
                best = max(edges, key=lambda e: self._road_score(board, pid, e))
                return Build(target=Road(edge_id=best))
        elif plan == "dev_card":
            if state.dev_cards_remaining > 0:
                return Build(target=DevCard())
        return None

    # ------------------------------------------------------------------
    # Trading
    # ------------------------------------------------------------------

    def _trade_toward_goal(
        self,
        state: GameState,
        player: PlayerState,
        goal_cost: Dict[ResourceType, int],
    ) -> Optional[BankTrade]:
        """Trade the biggest tradeable surplus toward the goal's resource deficit."""
        deficit = resource_deficit(player, goal_cost)
        if not deficit:
            return None
        want_res = max(deficit, key=lambda r: deficit[r])

        best_give: Optional[Tuple[ResourceType, int]] = None
        best_spare = 0
        for r, amt in player.resources.items():
            if r == ResourceType.DESERT or r in deficit:
                continue
            ratio = get_port_ratio(state.board, self.player_id, r)
            spare = amt - goal_cost.get(r, 0)
            if spare >= ratio and spare > best_spare:
                best_spare = spare
                best_give = (r, ratio)

        if best_give is None:
            return None
        give_res, ratio = best_give
        return BankTrade(offering={give_res: ratio}, requesting={want_res: 1})

    # ------------------------------------------------------------------
    # Setup scoring
    # ------------------------------------------------------------------

    def _vertex_setup_score(self, board, vertex_id: int, owned) -> float:
        pip = vertex_pip_score(board, vertex_id)
        new_types = vertex_resource_types(board, vertex_id) - owned
        diversity_bonus = len(new_types) * 4
        v = board.vertices[vertex_id]
        port_bonus = 4 if v.port is not None else 0
        return pip * 10 + diversity_bonus + port_bonus

    # ------------------------------------------------------------------
    # Road scoring
    # ------------------------------------------------------------------

    def _road_score(self, board, player_id: int, eid: int) -> int:
        score = 0
        for vid in board.edges[eid].vertex_ids:
            v = board.vertices[vid]
            if v.building is None and _distance_rule_ok(board, vid):
                score += vertex_pip_score(board, vid) * 2
                if v.port is not None:
                    score += 10
        return score

    # ------------------------------------------------------------------
    # Robber targeting
    # ------------------------------------------------------------------

    def _best_robber_target(
        self, state: GameState
    ) -> Tuple[int, Optional[int]]:
        board = state.board
        current = board.robber_hex_id
        pid = self.player_id

        opponents_with_cards = sorted(
            [p for p in state.players if p.player_id != pid and p.resource_count > 0],
            key=lambda p: (p.public_vp, p.resource_count),
            reverse=True,
        )
        target = opponents_with_cards[0] if opponents_with_cards else None

        if target is not None:
            best_pip, best_hid = -1, None
            for hid, hex_ in board.hexes.items():
                if hid == current or hex_.number is None:
                    continue
                on_hex = {
                    board.vertices[vid].building.player_id
                    for vid in hex_.vertex_ids
                    if board.vertices[vid].building is not None
                    and board.vertices[vid].building.player_id != pid
                }
                if target.player_id in on_hex:
                    pip = PIPS.get(hex_.number, 0)
                    if pip > best_pip:
                        best_pip, best_hid = pip, hid
            if best_hid is not None:
                return best_hid, target.player_id

        for hid, hex_ in board.hexes.items():
            if hid == current:
                continue
            opp_ids = [
                board.vertices[vid].building.player_id
                for vid in hex_.vertex_ids
                if board.vertices[vid].building is not None
                and board.vertices[vid].building.player_id != pid
            ]
            if opp_ids:
                return hid, opp_ids[0]

        for hid in board.hexes:
            if hid != current:
                return hid, None
        return current, None
