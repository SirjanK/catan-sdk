from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel
from catan.models.enums import ResourceType, PortType, BuildingType


class Building(BaseModel):
    """A settlement or city placed on a vertex.

    Attributes:
        player_id: The player who owns this building.
        building_type: Whether it is a SETTLEMENT or CITY.
    """

    player_id: int
    building_type: BuildingType


class Hex(BaseModel):
    """One of the 19 land tiles on the Catan board.

    Hexes are addressed with axial (q, r) coordinates — a standard two-axis
    system for hexagonal grids described in detail at:
    https://www.redblobgames.com/grids/hexagons/

    In this implementation we use the "pointy-top" orientation.  q increases
    going East; r increases going South-East.  The center hex sits at (0, 0)
    and the board spans radius 2.

    Attributes:
        hex_id: Stable integer ID (0–18), assigned in row-major order.
        q: Axial column coordinate.
        r: Axial row coordinate.
        resource: The resource this tile produces, or DESERT.
        number: The number token (2–12, excluding 7) placed on this tile.
            None for the desert, which never produces resources.
        vertex_ids: IDs of the 6 corner vertices, ordered clockwise starting
            from the top (north) vertex (corner 0).
        edge_ids: IDs of the 6 border edges, ordered clockwise starting from
            the top-right (NE) edge (edge 0, connecting corners 0 and 1).
    """

    hex_id: int
    q: int
    r: int
    resource: ResourceType
    number: Optional[int] = None
    vertex_ids: List[int]
    edge_ids: List[int]


class Vertex(BaseModel):
    """An intersection point where up to 3 hexes meet.

    Vertices are where settlements and cities are placed.  There are 54
    vertices on the standard board.

    Attributes:
        vertex_id: Stable integer ID (0–53).
        adjacent_hex_ids: IDs of the 1–3 hexes that share this vertex,
            sorted in ascending ID order.
        adjacent_edge_ids: IDs of the 2–3 edges that meet at this vertex,
            sorted in ascending ID order.
        adjacent_vertex_ids: IDs of the 2–3 directly connected neighbouring
            vertices (i.e. those reachable by a single road), sorted in
            ascending ID order.  Used to enforce the distance rule: no two
            settlements may be placed on adjacent vertices.
        port: The port type available at this vertex, or None.  Both vertices
            of a port edge carry the same PortType.
        building: The building currently on this vertex, or None.
    """

    vertex_id: int
    adjacent_hex_ids: List[int]
    adjacent_edge_ids: List[int]
    adjacent_vertex_ids: List[int]
    port: Optional[PortType] = None
    building: Optional[Building] = None


class Edge(BaseModel):
    """A border segment between two vertices where roads are placed.

    There are 72 edges on the standard board.

    Attributes:
        edge_id: Stable integer ID (0–71).
        vertex_ids: The two endpoint vertex IDs, stored as (min_id, max_id).
        adjacent_edge_ids: IDs of all edges that share at least one endpoint
            with this edge (i.e. edges reachable for continuous-road checks),
            sorted in ascending ID order.
        road_owner: The player_id of the player whose road occupies this edge,
            or None if unoccupied.
    """

    edge_id: int
    vertex_ids: Tuple[int, int]
    adjacent_edge_ids: List[int]
    road_owner: Optional[int] = None


class Board(BaseModel):
    """Full snapshot of the Catan board for one game.

    The board topology (adjacency) is fixed and pre-computed in
    ``catan.board.topology``; only the placement of resources, numbers,
    buildings, roads, and the robber changes per game.

    Attributes:
        hexes: Map from hex_id to Hex.
        vertices: Map from vertex_id to Vertex.
        edges: Map from edge_id to Edge.
        robber_hex_id: The hex currently occupied by the robber.
    """

    hexes: Dict[int, Hex]
    vertices: Dict[int, Vertex]
    edges: Dict[int, Edge]
    robber_hex_id: int
