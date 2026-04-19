"""
example_bot.py — minimal Player stub with comments.

Copy this file, rename the class, and implement every method.
Run the validator before submitting:

    python -m catan.submit submissions.example_bot:ExampleBot

The full reference implementation is catan/players/basic_player.py.
"""

from __future__ import annotations

from catan.models.actions import (
    DiscardCards,
    MoveRobber,
    Pass,
    PlaceRoad,
    PlaceSettlement,
    PlayKnight,
    RespondToTrade,
    RollDice,
)
from catan.models.state import GameState, TradeProposal
from catan.player import Player


class ExampleBot(Player):
    """Replace this with your bot's name and strategy description."""

    def __init__(self, player_id: int) -> None:
        self.player_id = player_id

    # ------------------------------------------------------------------
    # Setup phase — called twice per player (forward then backward)
    # ------------------------------------------------------------------

    def setup_place_settlement(self, state: GameState) -> PlaceSettlement:
        """Pick any empty vertex that respects the distance rule."""
        from catan.engine.validator import _distance_rule_ok
        for vid, vertex in state.board.vertices.items():
            if vertex.building is None and _distance_rule_ok(state.board, vid):
                return PlaceSettlement(vertex_id=vid)
        raise RuntimeError("No valid vertex found")

    def setup_place_road(
        self, state: GameState, settlement_vertex_id: int
    ) -> PlaceRoad:
        """Place a road adjacent to the just-placed settlement."""
        vertex = state.board.vertices[settlement_vertex_id]
        for eid in vertex.adjacent_edge_ids:
            if state.board.edges[eid].road_owner is None:
                return PlaceRoad(edge_id=eid)
        raise RuntimeError("No valid edge found")

    # ------------------------------------------------------------------
    # Pre-roll phase
    # ------------------------------------------------------------------

    def pre_roll_action(self, state: GameState) -> PlayKnight | RollDice:
        """Just roll the dice (no knight play)."""
        return RollDice()

    # ------------------------------------------------------------------
    # Discard when holding more than 7 cards after a 7-roll
    # ------------------------------------------------------------------

    def discard_cards(self, state: GameState, count: int) -> DiscardCards:
        """Discard *count* cards from your hand."""
        player = state.players[self.player_id]
        to_discard: dict = {}
        remaining = count
        for res, amt in player.resources.items():
            if remaining <= 0:
                break
            take = min(amt, remaining)
            if take > 0:
                to_discard[res] = take
                remaining -= take
        return DiscardCards(resources=to_discard)

    # ------------------------------------------------------------------
    # Move the robber (after rolling 7 or playing Knight)
    # ------------------------------------------------------------------

    def move_robber(self, state: GameState) -> MoveRobber:
        """Move the robber to any hex other than its current position."""
        current = state.board.robber_hex_id
        for hid in state.board.hexes:
            if hid != current:
                return MoveRobber(hex_id=hid, steal_from_player_id=None)
        return MoveRobber(hex_id=current, steal_from_player_id=None)

    # ------------------------------------------------------------------
    # Main turn loop — return Pass() to end your turn
    # ------------------------------------------------------------------

    def take_turn(self, state: GameState) -> Pass:
        """Do nothing and pass."""
        return Pass()

    # ------------------------------------------------------------------
    # React to trade proposals from other players (200 ms timeout)
    # ------------------------------------------------------------------

    def respond_to_trade(
        self, state: GameState, proposal: TradeProposal
    ) -> RespondToTrade:
        """Always decline trade proposals."""
        return RespondToTrade(proposal_id=proposal.proposal_id, accept=False)
