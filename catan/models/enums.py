from enum import Enum


class ResourceType(str, Enum):
    WOOD = "WOOD"
    BRICK = "BRICK"
    WHEAT = "WHEAT"
    ORE = "ORE"
    SHEEP = "SHEEP"
    DESERT = "DESERT"


class PortType(str, Enum):
    GENERIC_3_1 = "GENERIC_3_1"
    WOOD_2_1 = "WOOD_2_1"
    BRICK_2_1 = "BRICK_2_1"
    WHEAT_2_1 = "WHEAT_2_1"
    ORE_2_1 = "ORE_2_1"
    SHEEP_2_1 = "SHEEP_2_1"


class BuildingType(str, Enum):
    SETTLEMENT = "SETTLEMENT"
    CITY = "CITY"


class DevCardType(str, Enum):
    KNIGHT = "KNIGHT"
    VICTORY_POINT = "VICTORY_POINT"
    ROAD_BUILDING = "ROAD_BUILDING"
    YEAR_OF_PLENTY = "YEAR_OF_PLENTY"
    MONOPOLY = "MONOPOLY"


class GamePhase(str, Enum):
    SETUP_FORWARD = "SETUP_FORWARD"
    SETUP_BACKWARD = "SETUP_BACKWARD"
    PRE_ROLL = "PRE_ROLL"
    POST_ROLL = "POST_ROLL"
    MOVING_ROBBER = "MOVING_ROBBER"
    DISCARDING = "DISCARDING"
    GAME_OVER = "GAME_OVER"
