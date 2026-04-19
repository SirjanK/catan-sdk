"""
Player registry: maps type-name strings to player classes.

To add a new player type, import its class and add an entry to
``PLAYER_REGISTRY``.  The key must match what appears in ``PlayerConfig.type``
inside a game config YAML/JSON.

Usage::

    from catan.players.registry import build_player
    from catan.config import PlayerConfig

    player = build_player(PlayerConfig(type="basic", seed=7), player_id=0)
"""

from __future__ import annotations

from typing import Dict, Type

from catan.player import Player
from catan.players.basic_player import BasicPlayer

PLAYER_REGISTRY: Dict[str, Type[Player]] = {
    "basic": BasicPlayer,
}


def build_player(config, player_id: int) -> Player:
    """Instantiate the player described by *config* and assign *player_id*.

    Parameters
    ----------
    config:
        A ``PlayerConfig`` (or any object with ``.type`` and ``.seed``).
    player_id:
        0-based index assigned by the engine; forwarded to the constructor.

    Raises
    ------
    ValueError
        If ``config.type`` is not in ``PLAYER_REGISTRY``.
    """
    cls = PLAYER_REGISTRY.get(config.type)
    if cls is None:
        available = sorted(PLAYER_REGISTRY)
        raise ValueError(
            f"Unknown player type {config.type!r}.  "
            f"Available types: {available}"
        )
    return cls(player_id=player_id, seed=config.seed)
