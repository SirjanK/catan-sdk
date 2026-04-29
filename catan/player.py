from __future__ import annotations
from abc import ABC, abstractmethod
from catan.models.state import GameState, TradeProposal
from catan.models.actions import (
    PlaceSettlement,
    PlaceRoad,
    PlayKnight,
    RollDice,
    DiscardCards,
    MoveRobber,
    ProposeTrade,
    AcceptTrade,
    RejectAllTrades,
    Build,
    PlayDevCard,
    Pass,
    RespondToTrade,
)


class Player(ABC):
    """Abstract base class that all Catan bot agents must implement."""

    # ------------------------------------------------------------------
    # Setup phase — called twice each (forward then backward snake draft)
    # ------------------------------------------------------------------

    @abstractmethod
    def setup_place_settlement(self, state: GameState) -> PlaceSettlement:
        """Choose where to place an initial settlement."""
        ...

    @abstractmethod
    def setup_place_road(
        self, state: GameState, settlement_vertex_id: int
    ) -> PlaceRoad:
        """Choose where to place the road adjacent to the just-placed settlement."""
        ...

    # ------------------------------------------------------------------
    # Pre-roll phase
    # ------------------------------------------------------------------

    @abstractmethod
    def pre_roll_action(self, state: GameState) -> PlayKnight | RollDice:
        """Optionally play a Knight card before rolling the dice, or just roll."""
        ...

    # ------------------------------------------------------------------
    # Reactive — discard when >7 cards after a 7-roll
    # ------------------------------------------------------------------

    @abstractmethod
    def discard_cards(self, state: GameState, count: int) -> DiscardCards:
        """Discard *count* cards (called when this player has >7 after a 7-roll)."""
        ...

    # ------------------------------------------------------------------
    # Reactive — move the robber (after rolling 7 or playing a Knight)
    # ------------------------------------------------------------------

    @abstractmethod
    def move_robber(self, state: GameState) -> MoveRobber:
        """Choose a hex to move the robber to, and optionally whom to steal from."""
        ...

    # ------------------------------------------------------------------
    # Main turn — called repeatedly until Pass() is returned
    # ------------------------------------------------------------------

    @abstractmethod
    def take_turn(
        self, state: GameState
    ) -> ProposeTrade | AcceptTrade | RejectAllTrades | Build | PlayDevCard | Pass:
        """
        Execute one action on the player's turn.

        The game loop calls this repeatedly until the player returns Pass().
        A player may build, trade, or play dev cards in any order, subject
        to game rules enforced by the engine.

        ``state.dev_cards_bought_this_turn`` lists any dev cards purchased
        earlier this same turn.  The rules forbid playing a dev card on the
        same turn it was bought, so bots should skip card types that appear
        in that list when deciding whether to play a dev card.
        """
        ...

    # ------------------------------------------------------------------
    # Outside turn — called when another player proposes a trade
    # (engine enforces a ≤0.2s response time limit)
    # ------------------------------------------------------------------

    @abstractmethod
    def respond_to_trade(
        self, state: GameState, proposal: TradeProposal
    ) -> RespondToTrade:
        """
        Accept or decline a trade proposal from another player.

        Must respond within 200 ms; the engine will auto-decline on timeout.
        """
        ...
