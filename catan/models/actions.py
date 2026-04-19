from __future__ import annotations
from typing import Annotated, Dict, Literal, Optional, Union
from pydantic import BaseModel, Field
from catan.models.enums import ResourceType, DevCardType


# ---------------------------------------------------------------------------
# Setup phase
# ---------------------------------------------------------------------------

class PlaceSettlement(BaseModel):
    action: Literal["place_settlement"] = "place_settlement"
    vertex_id: int


class PlaceRoad(BaseModel):
    action: Literal["place_road"] = "place_road"
    edge_id: int


# ---------------------------------------------------------------------------
# Pre-roll
# ---------------------------------------------------------------------------

class PlayKnight(BaseModel):
    action: Literal["play_knight"] = "play_knight"
    target_hex_id: int
    steal_from_player_id: Optional[int] = None


class RollDice(BaseModel):
    action: Literal["roll_dice"] = "roll_dice"


# ---------------------------------------------------------------------------
# Post-roll / main turn
# ---------------------------------------------------------------------------

class ProposeTrade(BaseModel):
    action: Literal["propose_trade"] = "propose_trade"
    offering: dict[ResourceType, int]
    requesting: dict[ResourceType, int]


class AcceptTrade(BaseModel):
    action: Literal["accept_trade"] = "accept_trade"
    proposal_id: int
    from_player_id: int


class RejectAllTrades(BaseModel):
    action: Literal["reject_all_trades"] = "reject_all_trades"


# BuildTarget variants
class Road(BaseModel):
    target: Literal["road"] = "road"
    edge_id: int


class Settlement(BaseModel):
    target: Literal["settlement"] = "settlement"
    vertex_id: int


class City(BaseModel):
    target: Literal["city"] = "city"
    vertex_id: int


class DevCard(BaseModel):
    target: Literal["dev_card"] = "dev_card"


BuildTarget = Annotated[
    Union[Road, Settlement, City, DevCard],
    Field(discriminator="target"),
]


class Build(BaseModel):
    action: Literal["build"] = "build"
    target: BuildTarget


class PlayDevCard(BaseModel):
    action: Literal["play_dev_card"] = "play_dev_card"
    card: DevCardType
    # Extra kwargs encoded as a flat dict to keep the model simple;
    # callers populate card-specific fields (e.g. monopoly_resource,
    # year_of_plenty_resources, road_edge_ids).
    params: dict[str, object] = {}


class Pass(BaseModel):
    action: Literal["pass"] = "pass"


# ---------------------------------------------------------------------------
# Reactive (outside turn)
# ---------------------------------------------------------------------------

class RespondToTrade(BaseModel):
    action: Literal["respond_to_trade"] = "respond_to_trade"
    proposal_id: int
    accept: bool


# ---------------------------------------------------------------------------
# Robber / discard
# ---------------------------------------------------------------------------

class MoveRobber(BaseModel):
    action: Literal["move_robber"] = "move_robber"
    hex_id: int
    steal_from_player_id: Optional[int] = None


class DiscardCards(BaseModel):
    action: Literal["discard_cards"] = "discard_cards"
    resources: dict[ResourceType, int]


# ---------------------------------------------------------------------------
# Bank trade (4:1, 3:1 generic port, or 2:1 resource port)
# ---------------------------------------------------------------------------

class BankTrade(BaseModel):
    """Exchange resources with the bank at the applicable port ratio.

    ``offering`` must contain exactly one resource type; ``requesting`` must
    contain exactly one resource type (different from offering).  The amount
    offered must equal the player's best available trade ratio for that
    resource (4:1 without a port, 3:1 with a generic port, 2:1 with a
    matching 2:1 port).  The amount requested must be exactly 1.
    """

    action: Literal["bank_trade"] = "bank_trade"
    offering: Dict[ResourceType, int]
    requesting: Dict[ResourceType, int]
