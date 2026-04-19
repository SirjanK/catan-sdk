"""
BasicPlayer: a simple but legal Catan bot for testing the engine.

Strategy (deterministic priority order):
  Setup:   place at the highest-pip-score vertex available; road toward
           the best adjacent vertex.
  Turn:    Build city > settlement > road > dev card, in that order.
           If nothing is affordable, attempt one 4:1 bank trade toward
           the cheapest missing resource for the highest-priority goal.
           Otherwise, Pass.
  Robber:  move to any opponent-occupied hex; steal from a random opponent.
  Discard: discard from the resources held in greatest quantity first.
  Trade:   never propose trades; always decline incoming proposals.
"""

from __future__ import annotations

from random import Random
from typing import Dict, Optional

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
    RejectAllTrades,
    RespondToTrade,
    Road,
    RollDice,
    Settlement,
)
from catan.models.enums import ResourceType
from catan.models.state import GameState, TradeProposal
from catan.player import Player

# Number-token pip counts (probability weight).
_PIPS: Dict[int, int] = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 8: 5, 9: 4, 10: 3, 11: 2, 12: 1}

# Priority order for build goals (used for bank-trade targeting).
_GOAL_COSTS = [CITY_COST, SETTLEMENT_COST, ROAD_COST, DEV_CARD_COST]


class BasicPlayer(Player):
    """Simple deterministic bot — legal moves, not game-theoretically optimal."""

    def __init__(self, player_id: int, seed: int = 0) -> None:
        self.player_id = player_id
        self._rng = Random(seed + player_id)
        # Tracks whether this player has already done a bank trade this turn.
        self._bank_traded_this_turn: bool = False

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup_place_settlement(self, state: GameState) -> PlaceSettlement:
        best_vid = self._best_setup_vertex(state)
        return PlaceSettlement(vertex_id=best_vid)

    def setup_place_road(
        self, state: GameState, settlement_vertex_id: int
    ) -> PlaceRoad:
        vertex = state.board.vertices[settlement_vertex_id]
        for eid in vertex.adjacent_edge_ids:
            if state.board.edges[eid].road_owner is None:
                return PlaceRoad(edge_id=eid)
        # Fallback (should not happen on a valid board)
        return PlaceRoad(edge_id=vertex.adjacent_edge_ids[0])

    # ------------------------------------------------------------------
    # Pre-roll
    # ------------------------------------------------------------------

    def pre_roll_action(self, state: GameState) -> PlayKnight | RollDice:
        # Reset the bank-trade flag at the start of each turn.
        self._bank_traded_this_turn = False
        return RollDice()

    # ------------------------------------------------------------------
    # Discard
    # ------------------------------------------------------------------

    def discard_cards(self, state: GameState, count: int) -> DiscardCards:
        player = state.players[self.player_id]
        # Discard from whichever resources we hold the most of.
        pairs = sorted(
            [(r, amt) for r, amt in player.resources.items() if amt > 0],
            key=lambda x: -x[1],
        )
        to_discard: Dict[ResourceType, int] = {}
        remaining = count
        for res, amt in pairs:
            if remaining <= 0:
                break
            take = min(amt, remaining)
            to_discard[res] = take
            remaining -= take
        return DiscardCards(resources=to_discard)

    # ------------------------------------------------------------------
    # Move robber
    # ------------------------------------------------------------------

    def move_robber(self, state: GameState) -> MoveRobber:
        board = state.board
        current = board.robber_hex_id
        pid = self.player_id

        # Prefer hexes that have opponent buildings.
        for hid, hex_ in board.hexes.items():
            if hid == current:
                continue
            opponents = [
                board.vertices[vid].building.player_id
                for vid in hex_.vertex_ids
                if board.vertices[vid].building is not None
                and board.vertices[vid].building.player_id != pid
            ]
            if opponents:
                steal_from = self._rng.choice(opponents)
                return MoveRobber(hex_id=hid, steal_from_player_id=steal_from)

        # No opponent-occupied hex — move to any other hex.
        for hid in board.hexes:
            if hid != current:
                return MoveRobber(hex_id=hid, steal_from_player_id=None)

        # Should never happen on a standard board.
        return MoveRobber(hex_id=current, steal_from_player_id=None)

    # ------------------------------------------------------------------
    # Main turn
    # ------------------------------------------------------------------

    def take_turn(
        self, state: GameState
    ) -> ProposeTrade | AcceptTrade | RejectAllTrades | Build | PlayDevCard | Pass:
        player = state.players[self.player_id]
        board = state.board

        # --- Attempt to build in priority order ---
        build_action = self._try_build(state, player, board)
        if build_action is not None:
            return build_action

        # --- Attempt one bank trade per turn ---
        if not self._bank_traded_this_turn:
            trade = self._try_bank_trade(state, player, board)
            if trade is not None:
                self._bank_traded_this_turn = True
                return trade

        return Pass()

    # ------------------------------------------------------------------
    # Respond to trade (always decline)
    # ------------------------------------------------------------------

    def respond_to_trade(
        self, state: GameState, proposal: TradeProposal
    ) -> RespondToTrade:
        return RespondToTrade(proposal_id=proposal.proposal_id, accept=False)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _best_setup_vertex(self, state: GameState) -> int:
        """Return the vertex ID with the best pip-score among valid setup locations."""
        board = state.board
        pid = self.player_id
        best_score = -1
        best_vid = -1

        # Find existing resource types from already-placed own settlements
        # (prefer diversity on the second setup settlement).
        owned_resources: set = set()
        for v in board.vertices.values():
            if v.building and v.building.player_id == pid:
                for hid in v.adjacent_hex_ids:
                    owned_resources.add(board.hexes[hid].resource)

        for vid, vertex in board.vertices.items():
            if vertex.building is not None:
                continue
            if not _distance_rule_ok(board, vid):
                continue
            score = self._vertex_score(board, vid, owned_resources)
            if score > best_score:
                best_score = score
                best_vid = vid

        return best_vid

    @staticmethod
    def _vertex_score(board, vertex_id: int, owned_resources: set) -> int:
        vertex = board.vertices[vertex_id]
        score = 0
        new_resources: set = set()
        for hid in vertex.adjacent_hex_ids:
            h = board.hexes[hid]
            if h.number is not None:
                score += _PIPS.get(h.number, 0)
            if h.resource not in owned_resources:
                new_resources.add(h.resource)
        # Diversity bonus
        score += len(new_resources) * 2
        return score

    def _try_build(self, state: GameState, player, board) -> Optional[Build]:
        pid = self.player_id

        # 1. City (highest VP gain)
        if _has(player, CITY_COST) and player.cities_remaining > 0:
            vid = self._find_city_target(board, pid)
            if vid is not None:
                return Build(target=City(vertex_id=vid))

        # 2. Settlement
        if _has(player, SETTLEMENT_COST) and player.settlements_remaining > 0:
            vid = self._find_settlement_target(board, pid)
            if vid is not None:
                return Build(target=Settlement(vertex_id=vid))

        # 3. Road
        if _has(player, ROAD_COST) and player.roads_remaining > 0:
            eid = self._find_road_target(board, pid)
            if eid is not None:
                return Build(target=Road(edge_id=eid))

        # 4. Dev card
        if _has(player, DEV_CARD_COST) and state.dev_cards_remaining > 0:
            return Build(target=DevCard())

        return None

    def _try_bank_trade(self, state: GameState, player, board) -> Optional[BankTrade]:
        """Return a BankTrade that moves us closer to affording a build goal, or None."""
        pid = self.player_id

        for goal_cost in _GOAL_COSTS:
            deficit = {
                r: max(0, need - player.resources.get(r, 0))
                for r, need in goal_cost.items()
            }
            if sum(deficit.values()) == 0:
                continue   # already affordable

            needed = [r for r, d in deficit.items() if d > 0]

            # Find a resource we have plenty of and don't need for this goal
            for give_res in ResourceType:
                if give_res == ResourceType.DESERT:
                    continue
                if give_res in needed:
                    continue
                ratio = get_port_ratio(board, pid, give_res)
                if player.resources.get(give_res, 0) >= ratio:
                    want_res = needed[0]
                    return BankTrade(
                        offering={give_res: ratio},
                        requesting={want_res: 1},
                    )

        return None

    @staticmethod
    def _find_city_target(board, pid: int) -> Optional[int]:
        from catan.models.enums import BuildingType
        for vid, v in board.vertices.items():
            if (
                v.building
                and v.building.player_id == pid
                and v.building.building_type == BuildingType.SETTLEMENT
            ):
                return vid
        return None

    @staticmethod
    def _find_settlement_target(board, pid: int) -> Optional[int]:
        for vid, vertex in board.vertices.items():
            if vertex.building is not None:
                continue
            if not _distance_rule_ok(board, vid):
                continue
            if _settlement_connects_to_road(board, pid, vid):
                return vid
        return None

    @staticmethod
    def _find_road_target(board, pid: int) -> Optional[int]:
        for eid, edge in board.edges.items():
            if edge.road_owner is not None:
                continue
            if _road_connects_to_player(board, pid, eid):
                return eid
        return None


def _has(player, cost: Dict[ResourceType, int]) -> bool:
    return all(player.resources.get(r, 0) >= amt for r, amt in cost.items())
