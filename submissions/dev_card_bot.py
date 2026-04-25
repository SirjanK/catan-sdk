"""
DevCardBot — a phase-aware Catan bot that treats dev cards as a primary win condition.

The standard deck has 14 Knights + 5 VP + 2 Road Building + 2 YoP + 2 Monopoly.
DevCardBot exploits two facts:
  1. 5/25 draws are free VP — rushing dev cards early pays off.
  2. Largest Army (3+ knights, beating all opponents) = 2 VP — worth racing for.

Phases
------
Phase 1  (effective VP < 5)   — Rush
  city > dev_card > settlement > road
  Buy dev cards aggressively. Roads are deferred; if there are no open
  settlement spots, prefer a dev card purchase over road-building.

Phase 2  (effective VP 5–7)   — Consolidate
  city > settlement > dev_card > road
  Buildings take priority but dev cards still beat roads.

Phase 3  (effective VP >= 8)  — Sprint
  city > settlement > road > dev_card
  Fastest path to 10 VP.

Effective VP = public_vp + (VP dev cards currently in hand).

Knight play  — proactive, not just defensive
  Play a Knight when the robber blocks one of our hexes (pip >= 3), OR when
  we are within 1 knight of claiming/keeping Largest Army, OR when the VP
  leader is 2+ points ahead and is holding cards.

Dev card plays
  Victory Point : always reveal immediately.
  Year of Plenty: fill the resource deficit for the current goal.
  Monopoly      : grab the most-needed resource when opponents have cards.
  Road Building : when at least one useful road target exists.

Setup scoring  — biased toward ORE, WHEAT, SHEEP vertices.
  These three resources fuel both dev cards and cities, so settling on
  them early pays a compound dividend.

Trading
  Bank/port trades toward the current goal (up to 2 per turn).
  Accept player trades that close a deficit without giving away goal resources.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from random import Random

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

_DEV_RESOURCES = {ResourceType.ORE, ResourceType.WHEAT, ResourceType.SHEEP}


class DevCardBot(Player):
    """Phase-aware bot that rushes dev cards early and races for Largest Army."""

    def __init__(self, player_id: int, seed: int = 0) -> None:
        self.player_id = player_id
        self._rng = Random(seed + player_id)
        self._played_dev_card: bool = False
        self._bank_trades: int = 0

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup_place_settlement(self, state: GameState) -> PlaceSettlement:
        board = state.board
        pid = self.player_id
        owned = owned_resource_types(board, pid)
        best_score, best_vid = -1.0, -1
        for vid, v in board.vertices.items():
            if v.building is not None or not _distance_rule_ok(board, vid):
                continue
            score = self._setup_score(board, vid, owned)
            if score > best_score:
                best_score, best_vid = score, vid
        return PlaceSettlement(vertex_id=best_vid)

    def setup_place_road(self, state: GameState, settlement_vertex_id: int) -> PlaceRoad:
        board = state.board
        vertex = board.vertices[settlement_vertex_id]
        best_score, best_eid = -1, None
        for eid in vertex.adjacent_edge_ids:
            if board.edges[eid].road_owner is not None:
                continue
            far_vid = next(v for v in board.edges[eid].vertex_ids if v != settlement_vertex_id)
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
        self._played_dev_card = False
        self._bank_trades = 0
        player = state.players[self.player_id]
        if DevCardType.KNIGHT in player.dev_cards and self._should_play_knight(state):
            hex_id, steal_from = self._best_robber_target(state)
            return PlayKnight(target_hex_id=hex_id, steal_from_player_id=steal_from)
        return RollDice()

    # ------------------------------------------------------------------
    # Discard
    # ------------------------------------------------------------------

    def discard_cards(self, state: GameState, count: int) -> DiscardCards:
        player = state.players[self.player_id]
        goal = self._pick_goal(state)
        goal_cost = _COSTS.get(goal or "", {})

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
        # Discard non-goal resources first, then by largest surplus
        candidates.sort(key=lambda x: (x[1], -x[0]))

        to_discard: Dict[ResourceType, int] = {}
        remaining = count
        for spare, _, r in candidates:
            if remaining <= 0:
                break
            take = min(spare, remaining)
            to_discard[r] = take
            remaining -= take

        # Safety net — should never be needed in a valid game state
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
    # Robber
    # ------------------------------------------------------------------

    def move_robber(self, state: GameState) -> MoveRobber:
        hex_id, steal_from = self._best_robber_target(state)
        return MoveRobber(hex_id=hex_id, steal_from_player_id=steal_from)

    # ------------------------------------------------------------------
    # Main turn
    # ------------------------------------------------------------------

    def take_turn(self, state: GameState):  # noqa: ANN201
        player = state.players[self.player_id]

        # Always reveal VP dev cards — free VP, no per-turn limit
        if DevCardType.VICTORY_POINT in player.dev_cards:
            return PlayDevCard(card=DevCardType.VICTORY_POINT, params={})

        goal = self._pick_goal(state)
        if goal is None:
            return Pass()
        goal_cost = _COSTS[goal]

        # Year of Plenty: fill the resource deficit toward the goal
        if not self._played_dev_card and DevCardType.YEAR_OF_PLENTY in player.dev_cards:
            yop = self._try_year_of_plenty(player, goal_cost)
            if yop is not None:
                self._played_dev_card = True
                return yop

        # Monopoly: grab the most-needed resource
        if not self._played_dev_card and DevCardType.MONOPOLY in player.dev_cards:
            mono = self._try_monopoly(state, player, goal_cost)
            if mono is not None:
                self._played_dev_card = True
                return mono

        # Road Building: when useful targets exist
        if not self._played_dev_card and DevCardType.ROAD_BUILDING in player.dev_cards:
            rb = self._try_road_building(state)
            if rb is not None:
                self._played_dev_card = True
                return rb

        # Build if we can afford the goal
        if has_resources(player, goal_cost):
            action = self._execute_goal(goal, state)
            if action is not None:
                return action

        # Bank / port trade toward goal (up to 2 per turn)
        if self._bank_trades < 2:
            trade = self._trade_toward_goal(state, player, goal_cost)
            if trade is not None:
                self._bank_trades += 1
                return trade

        return Pass()

    # ------------------------------------------------------------------
    # Respond to trade
    # ------------------------------------------------------------------

    def respond_to_trade(self, state: GameState, proposal: TradeProposal) -> RespondToTrade:
        player = state.players[self.player_id]
        for res, amt in proposal.requesting.items():
            if player.resources.get(res, 0) < amt:
                return RespondToTrade(proposal_id=proposal.proposal_id, accept=False)
        goal = self._pick_goal(state)
        goal_cost = _COSTS.get(goal or "", {})
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
    # Phase and effective VP
    # ------------------------------------------------------------------

    def _effective_vp(self, state: GameState) -> int:
        """Public VP plus hidden VP dev cards in hand."""
        player = state.players[self.player_id]
        vp_cards = player.dev_cards.count(DevCardType.VICTORY_POINT)
        return player.public_vp + vp_cards

    def _phase(self, state: GameState) -> int:
        evp = self._effective_vp(state)
        if evp < 5:
            return 1
        if evp < 8:
            return 2
        return 3

    # ------------------------------------------------------------------
    # Goal selection
    # ------------------------------------------------------------------

    def _pick_goal(self, state: GameState) -> Optional[str]:
        player = state.players[self.player_id]
        board = state.board
        pid = self.player_id
        phase = self._phase(state)

        can_city = player.cities_remaining > 0 and best_city_vertex(board, pid) is not None
        can_settle = player.settlements_remaining > 0 and bool(valid_settlement_spots(board, pid))
        can_road = player.roads_remaining > 0 and bool(valid_road_edges(board, pid))
        can_dev = state.dev_cards_remaining > 0

        # Cities always first — best VP/resource ratio in any phase
        if can_city:
            return "city"

        if phase == 1:
            # Rush dev cards; build settlements when spots exist, defer roads
            if can_settle:
                return "settlement"
            if can_dev:
                return "dev_card"
            if can_road:
                return "road"

        elif phase == 2:
            # Consolidate: buildings first, but dev cards beat roads
            if can_settle:
                return "settlement"
            if can_dev:
                return "dev_card"
            if can_road:
                return "road"

        else:
            # Sprint: fastest path to 10 VP — roads help with Longest Road
            if can_settle:
                return "settlement"
            if can_road:
                return "road"
            if can_dev:
                return "dev_card"

        return None

    # ------------------------------------------------------------------
    # Knight strategy
    # ------------------------------------------------------------------

    def _knights_to_largest_army(self, state: GameState) -> int:
        """Knights still needed to claim or keep Largest Army."""
        player = state.players[self.player_id]
        my_knights = player.knights_played
        if state.largest_army_player is None:
            return max(0, 3 - my_knights)
        if state.largest_army_player == self.player_id:
            return 0
        holder_knights = state.players[state.largest_army_player].knights_played
        return max(0, holder_knights + 1 - my_knights)

    def _should_play_knight(self, state: GameState) -> bool:
        """Play knight proactively — not just when the robber blocks us."""
        pid = self.player_id
        board = state.board
        player = state.players[pid]
        robber_hex = board.hexes[board.robber_hex_id]

        # Robber is sitting on one of our productive hexes
        robber_blocks = any(
            board.vertices[vid].building is not None
            and board.vertices[vid].building.player_id == pid
            for vid in robber_hex.vertex_ids
        )
        if robber_blocks and PIPS.get(robber_hex.number or 0, 0) >= 3:
            return True

        # One knight away from claiming or keeping Largest Army
        if self._knights_to_largest_army(state) <= 1:
            return True

        # VP leader is 2+ ahead and is holding cards — harass them
        leader = max(state.players, key=lambda p: p.public_vp)
        if (
            leader.player_id != pid
            and leader.public_vp - player.public_vp >= 2
            and leader.resource_count > 0
        ):
            return True

        return False

    # ------------------------------------------------------------------
    # Dev card plays
    # ------------------------------------------------------------------

    def _try_year_of_plenty(
        self, player: PlayerState, goal_cost: Dict[ResourceType, int]
    ) -> Optional[PlayDevCard]:
        deficit = resource_deficit(player, goal_cost)
        if not deficit:
            return None
        needed: List[ResourceType] = []
        for r, d in sorted(deficit.items(), key=lambda x: -x[1]):
            needed.extend([r] * min(d, 2))
        resources = needed[:2]
        if len(resources) < 2:
            resources.append(resources[0])
        return PlayDevCard(card=DevCardType.YEAR_OF_PLENTY, params={"resources": resources})

    def _try_monopoly(
        self, state: GameState, player: PlayerState, goal_cost: Dict[ResourceType, int]
    ) -> Optional[PlayDevCard]:
        deficit = resource_deficit(player, goal_cost)
        if not deficit:
            return None
        total_opponent = sum(
            p.resource_count for p in state.players if p.player_id != self.player_id
        )
        if total_opponent < 2:
            return None
        best_res = max(deficit, key=lambda r: deficit[r])
        return PlayDevCard(card=DevCardType.MONOPOLY, params={"resource": best_res})

    def _try_road_building(self, state: GameState) -> Optional[PlayDevCard]:
        pid = self.player_id
        board = state.board
        useful = sorted(
            (eid for eid in valid_road_edges(board, pid) if self._road_score(board, pid, eid) > 0),
            key=lambda e: self._road_score(board, pid, e),
            reverse=True,
        )
        if not useful:
            return None
        return PlayDevCard(card=DevCardType.ROAD_BUILDING, params={"road_edge_ids": useful[:2]})

    # ------------------------------------------------------------------
    # Goal execution
    # ------------------------------------------------------------------

    def _execute_goal(self, goal: str, state: GameState):
        board = state.board
        pid = self.player_id
        if goal == "city":
            vid = best_city_vertex(board, pid)
            if vid is not None:
                return Build(target=City(vertex_id=vid))
        elif goal == "settlement":
            spots = valid_settlement_spots(board, pid)
            if spots:
                best = max(spots, key=lambda v: vertex_pip_score(board, v))
                return Build(target=Settlement(vertex_id=best))
        elif goal == "road":
            edges = valid_road_edges(board, pid)
            if edges:
                best = max(edges, key=lambda e: self._road_score(board, pid, e))
                return Build(target=Road(edge_id=best))
        elif goal == "dev_card":
            if state.dev_cards_remaining > 0:
                return Build(target=DevCard())
        return None

    # ------------------------------------------------------------------
    # Bank / port trading
    # ------------------------------------------------------------------

    def _trade_toward_goal(
        self, state: GameState, player: PlayerState, goal_cost: Dict[ResourceType, int]
    ) -> Optional[BankTrade]:
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
    # Robber targeting
    # ------------------------------------------------------------------

    def _best_robber_target(self, state: GameState) -> Tuple[int, Optional[int]]:
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

    # ------------------------------------------------------------------
    # Board scoring helpers
    # ------------------------------------------------------------------

    def _setup_score(self, board, vertex_id: int, owned) -> float:
        """Score a vertex for initial settlement placement.

        Biased toward ORE/WHEAT/SHEEP because those resources fuel both dev
        cards and cities — the two highest-value purchases in this strategy.
        """
        pip = vertex_pip_score(board, vertex_id)
        new_types = vertex_resource_types(board, vertex_id) - owned
        diversity_bonus = len(new_types) * 4

        # Extra weight on dev-card-friendly resources (ORE, WHEAT, SHEEP)
        dev_pip = sum(
            PIPS.get(board.hexes[hid].number or 0, 0)
            for hid in board.vertices[vertex_id].adjacent_hex_ids
            if board.hexes[hid].resource in _DEV_RESOURCES
        )

        v = board.vertices[vertex_id]
        port_bonus = 5 if v.port is not None else 0
        return pip * 10 + diversity_bonus + port_bonus + dev_pip * 2

    def _road_score(self, board, player_id: int, eid: int) -> int:
        score = 0
        for vid in board.edges[eid].vertex_ids:
            v = board.vertices[vid]
            if v.building is None and _distance_rule_ok(board, vid):
                score += vertex_pip_score(board, v.vertex_id) * 2
                if v.port is not None:
                    score += 10
        return score
