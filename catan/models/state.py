from __future__ import annotations
from typing import Dict, List, Optional
from pydantic import BaseModel
from catan.models.enums import ResourceType, DevCardType, GamePhase
from catan.models.board import Board


class TradeProposal(BaseModel):
    """A player-to-player trade offer awaiting responses.

    Attributes:
        proposal_id: Monotonically increasing ID within the current turn.
        proposing_player_id: The player who made the offer.
        offering: Resources the proposing player is willing to give.
        requesting: Resources the proposing player wants in return.
        responses: Map of player_id → True (accepted) / False (declined).
            Players who have not yet responded are absent from this dict.
    """

    proposal_id: int
    proposing_player_id: int
    offering: Dict[ResourceType, int]
    requesting: Dict[ResourceType, int]
    responses: Dict[int, bool]


class PlayerState(BaseModel):
    """Public and (for self) private state for one player.

    When retrieved via ``get_game_state(master, player_id)``, the fields
    marked HIDDEN are zeroed/emptied for all players other than the
    requesting player.

    Piece counts (roads_remaining, settlements_remaining, cities_remaining)
    start at their maximums and decrease as pieces are placed.  The number
    of pieces already on the board can be inferred from these values:
      - roads built       = 15 - roads_remaining
      - settlements built = 5  - settlements_remaining
      - cities built      = 4  - cities_remaining
    Note: placing a city replaces a settlement, so cities_remaining
    decreases by 1 and settlements_remaining increases by 1.

    Longest road is computed by the engine from the road graph on the board;
    ``has_longest_road`` reflects the current bonus holder.

    Attributes:
        player_id: Stable 0-based index.
        resources: Per-resource card counts. HIDDEN: zeroed for non-self.
        dev_cards: Ordered list of dev cards in hand. HIDDEN: emptied for non-self.
        dev_cards_count: Total dev cards in hand (always public).
        resource_count: Total resource cards in hand (always public).
        knights_played: Cumulative Knights played (used for Largest Army).
        roads_remaining: Unplaced road pieces remaining (starts at 15).
        settlements_remaining: Unplaced settlement pieces remaining (starts at 5).
        cities_remaining: Unplaced city pieces remaining (starts at 4).
        public_vp: Visible victory points: 1 per settlement + 2 per city
            + 2 for Longest Road + 2 for Largest Army.
            Does NOT include VP dev cards (those are hidden until revealed).
        has_longest_road: Whether this player holds the Longest Road bonus (2 VP).
        has_largest_army: Whether this player holds the Largest Army bonus (2 VP).
    """

    player_id: int
    resources: Dict[ResourceType, int]
    dev_cards: List[DevCardType]
    dev_cards_count: int
    resource_count: int
    knights_played: int
    roads_remaining: int
    settlements_remaining: int
    cities_remaining: int
    public_vp: int
    has_longest_road: bool
    has_largest_army: bool


class GameState(BaseModel):
    """Complete state of a Catan game at a single point in time.

    This is the master record maintained by the engine.  Players receive
    a pruned copy via ``get_game_state(master, player_id)`` that hides
    other players' hands.

    The shared development card deck starts with 25 cards:
      14 Knights + 5 Victory Points + 2 Road Building
      + 2 Year of Plenty + 2 Monopoly
    ``dev_cards_remaining`` tracks how many are left to draw; the ordering
    and composition of the remaining deck are NOT exposed in GameState
    (the engine holds that privately).

    Attributes:
        board: Full board snapshot (always public).
        players: PlayerState list ordered by player_id (index == player_id).
        current_player_id: Whose turn it currently is.
        phase: Current game phase.
        turn_number: Number of completed turns (increments after each player's turn).
        dice: The sum of the two dice rolled this turn, or None before the roll.
        pending_trades: Trade proposals still open for response this turn.
        trades_proposed_this_turn: Count toward the per-turn limit of 3.
        dev_cards_remaining: Cards left in the shared deck (always public).
        longest_road_player: player_id holding the Longest Road bonus, or None.
        largest_army_player: player_id holding the Largest Army bonus, or None.
    """

    board: Board
    players: List[PlayerState]
    current_player_id: int
    phase: GamePhase
    turn_number: int
    dice: Optional[int] = None
    pending_trades: List[TradeProposal]
    trades_proposed_this_turn: int
    dev_cards_remaining: int
    longest_road_player: Optional[int] = None
    largest_army_player: Optional[int] = None
