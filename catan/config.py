"""
Game configuration loaded from YAML or JSON.

The config drives the engine (limits, timeouts, player roster) and the
logger (log_dir, game_id).  All fields have sensible defaults so you only
need to override what you care about.

Usage::

    config = GameConfig.load("my_game.yaml")
    config = GameConfig.load("my_game.json")
    config = GameConfig.model_validate({...})   # from a plain dict
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field


class PlayerConfig(BaseModel):
    """Configuration for a single player slot.

    Attributes:
        type:  Player class name as registered in ``catan.players.registry``.
               Currently supported: ``"basic"``.
        seed:  RNG seed forwarded to the player constructor.  Different seeds
               give different in-game behaviour for randomised bots.
    """

    type: str
    seed: int = 0


class LimitsConfig(BaseModel):
    """Hard limits applied by the engine.

    Attributes:
        max_turns:           Safety-valve turn cap; game declared inconclusive
                             if nobody reaches 10 VP within this many turns.
        max_invalid_actions: How many invalid (or timed-out) actions a player
                             may return per opportunity before the engine
                             forces a default.
    """

    max_turns: int = 500
    max_invalid_actions: int = 3


class TimeoutsConfig(BaseModel):
    """Wall-clock limits (milliseconds) per player-action opportunity.

    Exceeding the limit counts as one invalid action attempt.  Set a field to
    0 to disable enforcement for that phase.

    Attributes:
        setup:         Settlement + road placement during setup phase.
        pre_roll:      RollDice or PlayKnight before the dice roll.
        post_roll:     Main-turn actions (Build, Trade, Pass, …).
        discard:       Discarding cards after a 7 is rolled.
        move_robber:   Placing the robber (after 7 or Knight).
        respond_trade: Responding to a trade proposal from another player.
    """

    setup: float = 500.0
    pre_roll: float = 500.0
    post_roll: float = 500.0
    discard: float = 500.0
    move_robber: float = 500.0
    respond_trade: float = 200.0


class GameConfig(BaseModel):
    """Top-level game configuration.

    Attributes:
        game_id:     16-character hex identifier.  Auto-generated from a
                     CSPRNG if omitted.
        seed:        Master RNG seed for board generation and dice rolls.
                     Omit (or set to null) for a non-deterministic game.
        players:     Ordered list of player configs (must be exactly 4).
        limits:      Turn and invalid-action caps.
        timeouts_ms: Per-phase wall-clock limits in milliseconds.
        log_dir:     Directory where JSONL game logs are written.
    """

    game_id: str = Field(default_factory=lambda: secrets.token_hex(8))
    seed: Optional[int] = None
    players: List[PlayerConfig]
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    timeouts_ms: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    log_dir: str = "tmp/games"

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str) -> "GameConfig":
        """Load from a YAML or JSON file (detected by extension)."""
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
        return cls.model_validate(data)
