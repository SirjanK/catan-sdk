"""
Game-level utilities called frequently during tournament play.

get_game_state(master, player_id) -> GameState
    Returns a player-scoped view of the master state with hidden information
    pruned.  Called by the engine before every player interaction.
"""

from __future__ import annotations

from catan.models.state import GameState


def get_game_state(master: GameState, player_id: int) -> GameState:
    """Return a player-scoped view of *master* with private info hidden.

    The engine calls this before passing state to any player method so that
    a player only sees their own hand, not opponents'.

    Hidden (zeroed/emptied for all players other than *player_id*):
        - ``PlayerState.resources``  → all counts set to 0
        - ``PlayerState.dev_cards``  → empty list

    Always public (unchanged for every player):
        - ``resource_count``, ``dev_cards_count``, ``knights_played``
        - ``public_vp``, ``has_longest_road``, ``has_largest_army``
        - Full board state (hex resources, numbers, buildings, roads, robber)

    Returns a deep copy; mutating the returned state has no effect on
    *master*.

    Parameters
    ----------
    master:
        The authoritative game state maintained by the engine.
    player_id:
        The player receiving this view.
    """
    state = master.model_copy(deep=True)

    for player in state.players:
        if player.player_id != player_id:
            player.resources = {r: 0 for r in player.resources}
            player.dev_cards = []

    return state
