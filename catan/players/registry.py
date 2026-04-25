"""
Player registry: maps type-name strings to player classes.

Two ways to specify a player type in a game config YAML:

1. Registry shortname (built-in bots)::

       type: basic        # → BasicPlayer
       type: heuristic    # → HeuristicBot

2. Module:class path (any importable bot, no registry edit needed)::

       type: submissions.my_bot:MyBot
       type: submissions.dev_card_bot:DevCardBot

   The ``module:ClassName`` form is resolved via importlib at runtime.

Usage::

    from catan.players.registry import build_player
    from catan.config import PlayerConfig

    player = build_player(PlayerConfig(type="basic", seed=7), player_id=0)
    player = build_player(PlayerConfig(type="submissions.my_bot:MyBot", seed=0), player_id=0)
"""

from __future__ import annotations

import importlib
from typing import Dict, Type

from catan.player import Player
from catan.players.basic_player import BasicPlayer
from submissions.heuristic_bot import HeuristicBot

PLAYER_REGISTRY: Dict[str, Type[Player]] = {
    "basic": BasicPlayer,
    "heuristic": HeuristicBot,
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
        If ``config.type`` is neither a registry key nor a valid ``module:Class`` spec.
    """
    type_str = config.type

    # Fast path: known registry shortname
    cls = PLAYER_REGISTRY.get(type_str)
    if cls is not None:
        return cls(player_id=player_id, seed=config.seed)

    # Fallback: treat as "module.path:ClassName"
    if ":" in type_str:
        module_path, class_name = type_str.rsplit(":", 1)
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            raise ValueError(
                f"Cannot import module {module_path!r} (from type={type_str!r}): {e}"
            ) from e
        if not hasattr(module, class_name):
            raise ValueError(
                f"Module {module_path!r} has no class {class_name!r} (from type={type_str!r})"
            )
        cls = getattr(module, class_name)
        return cls(player_id=player_id, seed=config.seed)

    available = sorted(PLAYER_REGISTRY)
    raise ValueError(
        f"Unknown player type {type_str!r}.  "
        f"Available registry names: {available}.  "
        f"Or use 'module.path:ClassName' to load any importable bot."
    )
