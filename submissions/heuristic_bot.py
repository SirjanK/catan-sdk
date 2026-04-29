"""
HeuristicBot — a strong heuristic-based Catan bot for catan-sdk.

This is an advanced reference implementation showing how to go beyond the
BasicPlayer template.  It is a good starting point if you want to understand
strong heuristic play before moving to search or learning-based approaches.

Strategy overview
-----------------
Setup
  Place at the vertex with the highest sum of adjacent pip counts.  Break
  ties by resource diversity (prefer new resource types over already-owned
  ones) and port proximity.  Road points toward the most promising direction
  reachable from the settlement.

Pre-roll
  Play a Knight card when the robber is sitting on one of our productive
  hexes (pip ≥ 4), or when the VP-leading opponent has ≥ 2 VP lead and
  holds cards.

Discard
  Protect the resources needed for the current build goal first; discard
  the largest surpluses of non-goal resources.

Robber
  Target the VP-leading opponent who currently holds > 0 resource cards.
  Among their hexes, land on the one with the highest pip count.  Steal
  from that player.

Main turn (goal hierarchy: city > settlement > road > dev card)
  1. Always play any Victory Point dev cards (free VP).
  2. Accept a beneficial player-to-player trade we proposed earlier.
  3. Play Road Building card if ≥ 1 useful road target exists.
  4. Determine the current build goal.
  5. Build immediately if affordable.
  6. Play Year of Plenty to fill the resource deficit.
  7. Play Monopoly if it closes the deficit (≥ 1 card needed, opponents have cards).
  8. Propose a player-to-player trade (≤ 2 per turn).
  9. Bank / port trade (≤ 2 per turn, best available ratio).

  Roads are built whenever there is a useful target (empty settlement vertex
  or port within reach).  Dev cards are skipped when partially saving for a
  city (dev card costs ORE+WHEAT+SHEEP, overlapping with CITY_COST).
 10. Pass.

Respond to trade
  Accept proposals from other players when the offered resources help toward
  the current goal and we are not giving away goal-critical resources.
"""

from __future__ import annotations

from random import Random
from typing import Dict, List, Optional, Set, Tuple

from catan.engine.longest_road import compute_longest_road
from catan.engine.validator import (
    CITY_COST,
    DEV_CARD_COST,
    ROAD_COST,
    SETTLEMENT_COST,
    _distance_rule_ok,
    _road_connects_to_player,
    _settlement_connects_to_road,
    get_port_ratio,
)
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
    RespondToTrade,
    Road,
    RollDice,
    Settlement,
)
from catan.models.enums import BuildingType, DevCardType, PortType, ResourceType
from catan.models.state import GameState, TradeProposal
from catan.player import Player
from catan.players.helpers import (
    best_city_vertex,
    has_resources,
    owned_resource_types,
    valid_road_edges,
    valid_settlement_spots,
    vertex_pip_score,
    vertex_resource_types,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_PIPS: Dict[int, int] = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 8: 5, 9: 4, 10: 3, 11: 2, 12: 1}

# ---------------------------------------------------------------------------
# Internal board utilities
# ---------------------------------------------------------------------------


def _vertex_setup_score(board, vertex_id: int, owned: Set[ResourceType]) -> float:
    """Score a vertex for initial placement.  Higher is better."""
    pip = vertex_pip_score(board, vertex_id)
    new_types = vertex_resource_types(board, vertex_id) - owned
    diversity_bonus = len(new_types) * 5
    v = board.vertices[vertex_id]
    port_bonus = 5 if v.port == PortType.GENERIC_3_1 else (8 if v.port is not None else 0)
    return pip * 10 + diversity_bonus + port_bonus


def _resource_deficit(player, cost: Dict[ResourceType, int]) -> Dict[ResourceType, int]:
    """Resources still needed beyond what the player currently holds."""
    return {
        r: amt - player.resources.get(r, 0)
        for r, amt in cost.items()
        if player.resources.get(r, 0) < amt
    }


def _road_score(board, player_id: int, eid: int) -> int:
    """Score for building a road on edge eid (higher = better; 0 means not useful)."""
    score = 0
    for vid in board.edges[eid].vertex_ids:
        v = board.vertices[vid]
        if v.building is None:
            if _distance_rule_ok(board, vid):
                score += vertex_pip_score(board, vid) * 3
                if v.port is not None:
                    score += 15
    # Bonus if placing this road directly enables a new settlement spot
    for vid in board.edges[eid].vertex_ids:
        v = board.vertices[vid]
        if v.building is not None:
            continue
        if not _distance_rule_ok(board, vid):
            continue
        if eid in v.adjacent_edge_ids:
            score += 20
            break
    return score


def _best_road_target(board, player_id: int) -> Optional[int]:
    """Return the edge_id for the most useful road to build, or None."""
    candidates = [
        (eid, _road_score(board, player_id, eid))
        for eid in valid_road_edges(board, player_id)
    ]
    useful = [(eid, sc) for eid, sc in candidates if sc > 0]
    if not useful:
        return None
    return max(useful, key=lambda x: x[1])[0]


def _best_setup_road_edge(board, settlement_vertex_id: int) -> int:
    """Pick the road direction from a just-placed settlement that leads to the best future."""
    vertex = board.vertices[settlement_vertex_id]
    best_score, best_eid = -1, None
    for eid in vertex.adjacent_edge_ids:
        if board.edges[eid].road_owner is not None:
            continue
        far_vid = next(v for v in board.edges[eid].vertex_ids if v != settlement_vertex_id)
        far_v = board.vertices[far_vid]
        score = vertex_pip_score(board, far_vid) * 2
        if far_v.building is None and _distance_rule_ok(board, far_vid):
            score += 20
        if far_v.port is not None:
            score += 15
        # One step further: sum pip scores of open vertices reachable from far_vid
        for eid2 in far_v.adjacent_edge_ids:
            if eid2 == eid:
                continue
            for vid2 in board.edges[eid2].vertex_ids:
                if vid2 == far_vid:
                    continue
                v2 = board.vertices[vid2]
                if v2.building is None and _distance_rule_ok(board, vid2):
                    score += vertex_pip_score(board, vid2)
                    if v2.port is not None:
                        score += 8
        if score > best_score:
            best_score, best_eid = score, eid
    return best_eid if best_eid is not None else vertex.adjacent_edge_ids[0]


def _best_robber_placement(
    state: GameState, player_id: int
) -> Tuple[int, Optional[int]]:
    """Return (hex_id, steal_from_player_id) targeting the VP-leading opponent with cards."""
    board = state.board
    current = board.robber_hex_id

    # Rank opponents by (VP, resource_count) descending; require > 0 cards
    opponents_with_cards = [
        p for p in state.players
        if p.player_id != player_id and p.resource_count > 0
    ]
    opponents_with_cards.sort(
        key=lambda p: (p.public_vp, p.resource_count), reverse=True
    )

    target_player = opponents_with_cards[0] if opponents_with_cards else None

    if target_player is not None:
        # Find their highest-pip hex (not the current robber hex)
        best_pip, best_hid = -1, None
        for hid, hex_ in board.hexes.items():
            if hid == current or hex_.number is None:
                continue
            on_hex = {
                board.vertices[vid].building.player_id
                for vid in hex_.vertex_ids
                if board.vertices[vid].building is not None
                and board.vertices[vid].building.player_id != player_id
            }
            if target_player.player_id in on_hex:
                pip = _PIPS.get(hex_.number, 0)
                if pip > best_pip:
                    best_pip, best_hid = pip, hid
        if best_hid is not None:
            return best_hid, target_player.player_id

    # Fallback: any opponent-occupied hex ≠ current
    for hid, hex_ in board.hexes.items():
        if hid == current:
            continue
        opp_ids = [
            board.vertices[vid].building.player_id
            for vid in hex_.vertex_ids
            if board.vertices[vid].building is not None
            and board.vertices[vid].building.player_id != player_id
        ]
        if opp_ids:
            return hid, opp_ids[0]

    # Last resort
    for hid in board.hexes:
        if hid != current:
            return hid, None
    return current, None


def _is_saving_for_city(state: GameState, player_id: int) -> bool:
    """True if the player has partial city resources and a settlement to upgrade."""
    player = state.players[player_id]
    board = state.board
    if player.cities_remaining <= 0 or best_city_vertex(board, player_id) is None:
        return False
    return (
        player.resources.get(ResourceType.ORE, 0) >= 1
        or player.resources.get(ResourceType.WHEAT, 0) >= 1
    )



# ---------------------------------------------------------------------------
# HeuristicBot
# ---------------------------------------------------------------------------


class HeuristicBot(Player):
    """Strong heuristic-based Catan bot.  See module docstring for full strategy."""

    def __init__(self, player_id: int, seed: int = 0) -> None:
        self.player_id = player_id
        self._rng = Random(seed + player_id)
        # Per-turn state flags (reset in pre_roll_action)
        self._trades_proposed: int = 0
        self._bank_trades: int = 0
        self._played_dev_card: bool = False

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup_place_settlement(self, state: GameState) -> PlaceSettlement:
        board = state.board
        owned = owned_resource_types(board, self.player_id)
        best_score, best_vid = -1.0, -1
        for vid, v in board.vertices.items():
            if v.building is not None:
                continue
            if not _distance_rule_ok(board, vid):
                continue
            score = _vertex_setup_score(board, vid, owned)
            if score > best_score:
                best_score, best_vid = score, vid
        return PlaceSettlement(vertex_id=best_vid)

    def setup_place_road(
        self, state: GameState, settlement_vertex_id: int
    ) -> PlaceRoad:
        eid = _best_setup_road_edge(state.board, settlement_vertex_id)
        return PlaceRoad(edge_id=eid)

    # ------------------------------------------------------------------
    # Pre-roll
    # ------------------------------------------------------------------

    def pre_roll_action(self, state: GameState) -> PlayKnight | RollDice:
        # Reset per-turn counters at the start of each turn
        self._trades_proposed = 0
        self._bank_trades = 0
        self._played_dev_card = False

        player = state.players[self.player_id]
        if DevCardType.KNIGHT not in player.dev_cards:
            return RollDice()

        board = state.board
        robber_hex = board.hexes[board.robber_hex_id]

        # Play knight if robber is on one of our productive hexes (pip ≥ 4)
        robber_blocks_us = any(
            board.vertices[vid].building is not None
            and board.vertices[vid].building.player_id == self.player_id
            for vid in robber_hex.vertex_ids
        )
        if robber_blocks_us and _PIPS.get(robber_hex.number or 0, 0) >= 4:
            hex_id, steal_from = _best_robber_placement(state, self.player_id)
            return PlayKnight(target_hex_id=hex_id, steal_from_player_id=steal_from)

        # Play knight if the VP leader is ≥ 2 ahead and has cards
        leader = max(state.players, key=lambda p: p.public_vp)
        if (
            leader.player_id != self.player_id
            and leader.public_vp - player.public_vp >= 2
            and leader.resource_count > 0
        ):
            hex_id, steal_from = _best_robber_placement(state, self.player_id)
            return PlayKnight(target_hex_id=hex_id, steal_from_player_id=steal_from)

        return RollDice()

    # ------------------------------------------------------------------
    # Discard
    # ------------------------------------------------------------------

    def discard_cards(self, state: GameState, count: int) -> DiscardCards:
        player = state.players[self.player_id]
        _, goal_cost = self._pick_goal(state)

        # How many of each resource to protect for our goal
        protect: Dict[ResourceType, int] = {}
        if goal_cost:
            for r, need in goal_cost.items():
                protect[r] = min(player.resources.get(r, 0), need)

        # Compute discardable amounts: everything above what we're protecting
        discardable: List[Tuple[int, ResourceType]] = []
        for r, amt in player.resources.items():
            if r == ResourceType.DESERT or amt == 0:
                continue
            spare = amt - protect.get(r, 0)
            if spare > 0:
                discardable.append((spare, r))

        # Discard non-goal resources first (sorted by most excess), then goal surplus
        in_goal = set(goal_cost or {})
        discardable.sort(key=lambda x: (x[1] in in_goal, -x[0]))

        to_discard: Dict[ResourceType, int] = {}
        remaining = count
        for spare, r in discardable:
            if remaining <= 0:
                break
            take = min(spare, remaining)
            to_discard[r] = take
            remaining -= take

        # Safety net (should not trigger in a legal game)
        if remaining > 0:
            for r, amt in sorted(player.resources.items(), key=lambda x: -x[1]):
                if r == ResourceType.DESERT or amt == 0 or remaining <= 0:
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
        hex_id, steal_from = _best_robber_placement(state, self.player_id)
        return MoveRobber(hex_id=hex_id, steal_from_player_id=steal_from)

    # ------------------------------------------------------------------
    # Main turn
    # ------------------------------------------------------------------

    def take_turn(self, state: GameState):  # noqa: ANN201
        player = state.players[self.player_id]
        board = state.board
        pid = self.player_id

        # 1. Always reveal VP dev cards (free VP, no per-turn limit)
        if DevCardType.VICTORY_POINT in player.dev_cards:
            return PlayDevCard(card=DevCardType.VICTORY_POINT, params={})

        # 2. Accept a pending trade we proposed if a responder said yes
        accept = self._try_accept_pending_trade(state, player)
        if accept is not None:
            return accept

        # Cards bought this turn may not be played this turn (Catan rules).
        bought_this_turn = set(state.dev_cards_bought_this_turn)

        # 3. Play Road Building when there are useful road targets
        if (
            not self._played_dev_card
            and DevCardType.ROAD_BUILDING in player.dev_cards
            and DevCardType.ROAD_BUILDING not in bought_this_turn
        ):
            rb = self._try_road_building(board, pid)
            if rb is not None:
                self._played_dev_card = True
                return rb

        # 4. Determine build goal
        goal_name, goal_cost = self._pick_goal(state)

        # 5. Build immediately if we can afford the goal
        if goal_name and has_resources(player, goal_cost):
            action = self._execute_goal(goal_name, state, board, pid)
            if action is not None:
                return action

        # 6. Year of Plenty to fill the deficit (one dev card play per turn)
        if (
            goal_cost
            and not self._played_dev_card
            and DevCardType.YEAR_OF_PLENTY in player.dev_cards
            and DevCardType.YEAR_OF_PLENTY not in bought_this_turn
        ):
            yop = self._try_year_of_plenty(player, goal_cost)
            if yop is not None:
                self._played_dev_card = True
                return yop

        # 7. Monopoly when it would close the deficit
        if (
            goal_cost
            and not self._played_dev_card
            and DevCardType.MONOPOLY in player.dev_cards
            and DevCardType.MONOPOLY not in bought_this_turn
        ):
            mono = self._try_monopoly(state, player, goal_cost)
            if mono is not None:
                self._played_dev_card = True
                return mono

        # 8. Propose a player-to-player trade (≤ 2 per turn)
        if (
            goal_cost
            and self._trades_proposed < 2
            and state.trades_proposed_this_turn < 3
        ):
            trade = self._try_propose_trade(player, goal_cost)
            if trade is not None:
                self._trades_proposed += 1
                return trade

        # 9. Bank / port trade (≤ 2 per turn)
        if goal_cost and self._bank_trades < 2:
            bt = self._try_bank_trade(state, player, board, goal_cost)
            if bt is not None:
                self._bank_trades += 1
                return bt

        return Pass()

    # ------------------------------------------------------------------
    # Respond to player trade proposals
    # ------------------------------------------------------------------

    def respond_to_trade(
        self, state: GameState, proposal: TradeProposal
    ) -> RespondToTrade:
        player = state.players[self.player_id]

        # Verify we can give what's being requested
        for res, amt in proposal.requesting.items():
            if player.resources.get(res, 0) < amt:
                return RespondToTrade(proposal_id=proposal.proposal_id, accept=False)

        # Accept if the offered resources fill part of our goal deficit
        # without giving away goal-critical resources
        _, goal_cost = self._pick_goal(state)
        if goal_cost:
            deficit = _resource_deficit(player, goal_cost)
            # Don't give away anything we specifically need for the goal
            for res, amt in proposal.requesting.items():
                if deficit.get(res, 0) > 0:
                    return RespondToTrade(proposal_id=proposal.proposal_id, accept=False)
            # Accept if at least one offered resource closes part of the deficit
            for res in proposal.offering:
                if deficit.get(res, 0) > 0:
                    return RespondToTrade(proposal_id=proposal.proposal_id, accept=True)

        return RespondToTrade(proposal_id=proposal.proposal_id, accept=False)

    # ------------------------------------------------------------------
    # Goal selection
    # ------------------------------------------------------------------

    def _pick_goal(
        self, state: GameState
    ) -> Tuple[Optional[str], Optional[Dict[ResourceType, int]]]:
        """Return (goal_name, cost_dict) for the highest-priority build goal."""
        player = state.players[self.player_id]
        board = state.board
        pid = self.player_id

        # City: best VP-per-resource return; always prioritize if we have a settlement
        if player.cities_remaining > 0 and best_city_vertex(board, pid) is not None:
            return "city", CITY_COST

        # Settlement: expand to new production spots
        if player.settlements_remaining > 0 and valid_settlement_spots(board, pid):
            return "settlement", SETTLEMENT_COST

        # Road: only when it actually leads somewhere useful
        if (
            player.roads_remaining > 0
            and _best_road_target(board, pid) is not None
        ):
            return "road", ROAD_COST

        # Dev card: flexible; skip if partially saving for city
        if state.dev_cards_remaining > 0 and not _is_saving_for_city(state, pid):
            return "dev_card", DEV_CARD_COST

        # Fall back to city even if saving (might as well try)
        if player.cities_remaining > 0 and best_city_vertex(board, pid) is not None:
            return "city", CITY_COST

        return None, None

    # ------------------------------------------------------------------
    # Goal execution
    # ------------------------------------------------------------------

    def _execute_goal(
        self, goal_name: str, state: GameState, board, pid: int
    ):
        if goal_name == "city":
            vid = best_city_vertex(board, pid)
            if vid is not None:
                return Build(target=City(vertex_id=vid))
        elif goal_name == "settlement":
            spots = valid_settlement_spots(board, pid)
            if spots:
                best = max(spots, key=lambda v: vertex_pip_score(board, v))
                return Build(target=Settlement(vertex_id=best))
        elif goal_name == "road":
            eid = _best_road_target(board, pid)
            if eid is not None:
                return Build(target=Road(edge_id=eid))
        elif goal_name == "dev_card":
            if state.dev_cards_remaining > 0:
                return Build(target=DevCard())
        return None

    # ------------------------------------------------------------------
    # Dev card plays
    # ------------------------------------------------------------------

    def _try_road_building(self, board, pid: int) -> Optional[PlayDevCard]:
        candidates = sorted(
            valid_road_edges(board, pid),
            key=lambda e: _road_score(board, pid, e),
            reverse=True,
        )
        useful = [e for e in candidates if _road_score(board, pid, e) > 0]
        if not useful:
            return None
        return PlayDevCard(
            card=DevCardType.ROAD_BUILDING,
            params={"road_edge_ids": useful[:2]},
        )

    def _try_year_of_plenty(
        self, player, goal_cost: Dict[ResourceType, int]
    ) -> Optional[PlayDevCard]:
        deficit = _resource_deficit(player, goal_cost)
        if not deficit:
            return None
        # Pick the two most-needed resource types (can repeat if only 1 type missing)
        needed: List[ResourceType] = []
        for r, d in sorted(deficit.items(), key=lambda x: -x[1]):
            needed.extend([r] * min(d, 2))
        resources = needed[:2]
        if len(resources) < 2:
            resources.append(resources[0])
        return PlayDevCard(
            card=DevCardType.YEAR_OF_PLENTY,
            params={"resources": resources},
        )

    def _try_monopoly(
        self,
        state: GameState,
        player,
        goal_cost: Dict[ResourceType, int],
    ) -> Optional[PlayDevCard]:
        deficit = _resource_deficit(player, goal_cost)
        if not deficit:
            return None
        total_opponent_cards = sum(
            p.resource_count for p in state.players if p.player_id != self.player_id
        )
        if total_opponent_cards < 2:
            return None
        # Target the resource we need most
        best_res = max(deficit, key=lambda r: deficit[r])
        if deficit[best_res] >= 1:
            return PlayDevCard(
                card=DevCardType.MONOPOLY,
                params={"resource": best_res},
            )
        return None

    # ------------------------------------------------------------------
    # Player-to-player trades
    # ------------------------------------------------------------------

    def _try_accept_pending_trade(self, state: GameState, player) -> Optional[AcceptTrade]:
        """Finalize any trade we proposed that another player has accepted."""
        for proposal in state.pending_trades:
            if proposal.proposing_player_id != self.player_id:
                continue
            for other_pid, accepted in proposal.responses.items():
                if not accepted:
                    continue
                # Still have the resources to complete?
                if all(
                    player.resources.get(r, 0) >= amt
                    for r, amt in proposal.offering.items()
                ):
                    return AcceptTrade(
                        proposal_id=proposal.proposal_id,
                        from_player_id=other_pid,
                    )
        return None

    def _try_propose_trade(
        self,
        player,
        goal_cost: Dict[ResourceType, int],
    ) -> Optional[ProposeTrade]:
        """Propose 1-for-1 trade: offer surplus resource, request needed one."""
        deficit = _resource_deficit(player, goal_cost)
        if not deficit:
            return None

        # What can we spare? (have > what goal needs)
        excess: Dict[ResourceType, int] = {}
        for r in ResourceType:
            if r == ResourceType.DESERT:
                continue
            have = player.resources.get(r, 0)
            need_for_goal = goal_cost.get(r, 0)
            spare = have - need_for_goal
            if spare > 0:
                excess[r] = spare

        if not excess:
            return None

        offer_res = max(excess, key=lambda r: excess[r])
        want_res = max(deficit, key=lambda r: deficit[r])
        return ProposeTrade(offering={offer_res: 1}, requesting={want_res: 1})

    # ------------------------------------------------------------------
    # Bank / port trades
    # ------------------------------------------------------------------

    def _try_bank_trade(
        self,
        state: GameState,
        player,
        board,
        goal_cost: Dict[ResourceType, int],
    ) -> Optional[BankTrade]:
        """Trade surplus resources at best available ratio toward goal deficit."""
        deficit = _resource_deficit(player, goal_cost)
        if not deficit:
            return None

        want_res = max(deficit, key=lambda r: deficit[r])

        for give_res in ResourceType:
            if give_res == ResourceType.DESERT:
                continue
            if give_res in deficit:
                continue  # don't trade away goal resources
            ratio = get_port_ratio(board, self.player_id, give_res)
            if player.resources.get(give_res, 0) >= ratio:
                return BankTrade(
                    offering={give_res: ratio},
                    requesting={want_res: 1},
                )
        return None
