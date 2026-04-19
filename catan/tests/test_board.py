"""
Topology correctness tests for the Catan board.

Checks:
- Exactly 19 hexes, 54 vertices, 72 edges
- Exactly 9 ports (4 generic 3:1, 5 special 2:1)
- All vertex/edge adjacency lists are symmetric
- No two adjacent hexes both have a 6 or 8 token after randomization
- get_game_state hides resources and dev_cards for other players
"""

import pytest

from catan.board.topology import (
    NUM_HEXES,
    NUM_VERTICES,
    NUM_EDGES,
    VERTEX_ADJACENT_VERTICES,
    VERTEX_ADJACENT_EDGES,
    VERTEX_ADJACENT_HEXES,
    EDGE_ADJACENT_EDGES,
    EDGE_VERTICES,
    HEX_VERTICES,
    HEX_EDGES,
    HEX_ADJACENT_HEXES,
    PORT_ASSIGNMENTS,
)
from catan.board.setup import create_board
from catan.game import get_game_state
from catan.models.enums import (
    ResourceType,
    PortType,
    DevCardType,
    GamePhase,
)
from catan.models.state import GameState, PlayerState, TradeProposal
from catan.models.board import Board


# ---------------------------------------------------------------------------
# Topology constants
# ---------------------------------------------------------------------------

class TestTopologyConstants:
    def test_hex_count(self):
        assert NUM_HEXES == 19

    def test_vertex_count(self):
        assert NUM_VERTICES == 54

    def test_edge_count(self):
        assert NUM_EDGES == 72

    def test_each_hex_has_six_vertices(self):
        for hid, verts in HEX_VERTICES.items():
            assert len(verts) == 6, f"Hex {hid} has {len(verts)} vertices"
            assert len(set(verts)) == 6, f"Hex {hid} has duplicate vertices"

    def test_each_hex_has_six_edges(self):
        for hid, edges in HEX_EDGES.items():
            assert len(edges) == 6, f"Hex {hid} has {len(edges)} edges"
            assert len(set(edges)) == 6, f"Hex {hid} has duplicate edges"

    def test_vertex_ids_in_range(self):
        for hid, verts in HEX_VERTICES.items():
            for v in verts:
                assert 0 <= v < NUM_VERTICES, f"Hex {hid} vertex {v} out of range"

    def test_edge_ids_in_range(self):
        for hid, edges in HEX_EDGES.items():
            for e in edges:
                assert 0 <= e < NUM_EDGES, f"Hex {hid} edge {e} out of range"


# ---------------------------------------------------------------------------
# Vertex adjacency symmetry
# ---------------------------------------------------------------------------

class TestVertexAdjacency:
    def test_adjacent_vertices_symmetric(self):
        for v, neighbors in VERTEX_ADJACENT_VERTICES.items():
            for u in neighbors:
                assert v in VERTEX_ADJACENT_VERTICES[u], (
                    f"Vertex {v} lists {u} as neighbor but not vice versa"
                )

    def test_adjacent_edges_consistent_with_edge_vertices(self):
        """Every edge listed for a vertex should have that vertex as an endpoint."""
        for v, edge_list in VERTEX_ADJACENT_EDGES.items():
            for e in edge_list:
                va, vb = EDGE_VERTICES[e]
                assert v in (va, vb), (
                    f"Vertex {v} lists edge {e} but edge endpoints are ({va},{vb})"
                )

    def test_vertex_degree_bounds(self):
        """Each vertex should have 2 or 3 adjacent edges (perimeter vs interior)."""
        for v, edges in VERTEX_ADJACENT_EDGES.items():
            assert 2 <= len(edges) <= 3, (
                f"Vertex {v} has {len(edges)} adjacent edges (expected 2 or 3)"
            )

    def test_vertex_hex_count_bounds(self):
        """Each vertex is adjacent to 1, 2, or 3 hexes."""
        for v, hexes in VERTEX_ADJACENT_HEXES.items():
            assert 1 <= len(hexes) <= 3, (
                f"Vertex {v} is adjacent to {len(hexes)} hexes"
            )

    def test_all_vertices_covered(self):
        assert set(VERTEX_ADJACENT_VERTICES.keys()) == set(range(NUM_VERTICES))
        assert set(VERTEX_ADJACENT_EDGES.keys()) == set(range(NUM_VERTICES))
        assert set(VERTEX_ADJACENT_HEXES.keys()) == set(range(NUM_VERTICES))


# ---------------------------------------------------------------------------
# Edge adjacency symmetry
# ---------------------------------------------------------------------------

class TestEdgeAdjacency:
    def test_adjacent_edges_symmetric(self):
        for e, neighbors in EDGE_ADJACENT_EDGES.items():
            for f in neighbors:
                assert e in EDGE_ADJACENT_EDGES[f], (
                    f"Edge {e} lists {f} as adjacent but not vice versa"
                )

    def test_edge_vertices_endpoints_valid(self):
        for e, (va, vb) in EDGE_VERTICES.items():
            assert 0 <= va < NUM_VERTICES
            assert 0 <= vb < NUM_VERTICES
            assert va != vb

    def test_edge_degree_bounds(self):
        """Each edge is adjacent to 2–4 other edges."""
        for e, adj in EDGE_ADJACENT_EDGES.items():
            assert 2 <= len(adj) <= 4, (
                f"Edge {e} has {len(adj)} adjacent edges"
            )

    def test_all_edges_covered(self):
        assert set(EDGE_ADJACENT_EDGES.keys()) == set(range(NUM_EDGES))
        assert set(EDGE_VERTICES.keys()) == set(range(NUM_EDGES))


# ---------------------------------------------------------------------------
# Hex adjacency
# ---------------------------------------------------------------------------

class TestHexAdjacency:
    def test_hex_adjacency_symmetric(self):
        for h, neighbors in HEX_ADJACENT_HEXES.items():
            for n in neighbors:
                assert h in HEX_ADJACENT_HEXES[n], (
                    f"Hex {h} lists {n} as neighbor but not vice versa"
                )

    def test_hex_neighbor_count(self):
        """Corner hexes have 3 neighbours, edge hexes 4, center hex 6."""
        for h, neighbors in HEX_ADJACENT_HEXES.items():
            assert 2 <= len(neighbors) <= 6, (
                f"Hex {h} has unexpected neighbor count {len(neighbors)}"
            )


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------

class TestPorts:
    def test_port_count(self):
        assert len(PORT_ASSIGNMENTS) == 9

    def test_generic_port_count(self):
        generic = [p for p, *_ in PORT_ASSIGNMENTS if p == PortType.GENERIC_3_1]
        assert len(generic) == 4

    def test_special_port_count(self):
        special = [p for p, *_ in PORT_ASSIGNMENTS if p != PortType.GENERIC_3_1]
        assert len(special) == 5

    def test_one_port_per_resource(self):
        resource_ports = {
            PortType.WOOD_2_1,
            PortType.BRICK_2_1,
            PortType.WHEAT_2_1,
            PortType.ORE_2_1,
            PortType.SHEEP_2_1,
        }
        found = {p for p, *_ in PORT_ASSIGNMENTS if p in resource_ports}
        assert found == resource_ports

    def test_port_vertices_on_perimeter(self):
        """Port vertices should each be adjacent to fewer than 3 hexes (perimeter)."""
        for _, va, vb in PORT_ASSIGNMENTS:
            assert len(VERTEX_ADJACENT_HEXES[va]) < 3, (
                f"Port vertex {va} is not on the perimeter"
            )
            assert len(VERTEX_ADJACENT_HEXES[vb]) < 3, (
                f"Port vertex {vb} is not on the perimeter"
            )

    def test_port_vertices_are_adjacent(self):
        """The two vertices of a port must be connected by an edge."""
        for _, va, vb in PORT_ASSIGNMENTS:
            assert vb in VERTEX_ADJACENT_VERTICES[va], (
                f"Port vertices {va} and {vb} are not adjacent"
            )


# ---------------------------------------------------------------------------
# create_board — structure
# ---------------------------------------------------------------------------

class TestCreateBoardStructure:
    @pytest.fixture(scope="class")
    def board(self) -> Board:
        return create_board(randomize=False)

    def test_hex_count(self, board):
        assert len(board.hexes) == 19

    def test_vertex_count(self, board):
        assert len(board.vertices) == 54

    def test_edge_count(self, board):
        assert len(board.edges) == 72

    def test_resource_counts(self, board):
        counts: dict[ResourceType, int] = {}
        for h in board.hexes.values():
            counts[h.resource] = counts.get(h.resource, 0) + 1
        assert counts[ResourceType.WHEAT] == 4
        assert counts[ResourceType.SHEEP] == 4
        assert counts[ResourceType.WOOD] == 4
        assert counts[ResourceType.BRICK] == 3
        assert counts[ResourceType.ORE] == 3
        assert counts[ResourceType.DESERT] == 1

    def test_number_token_counts(self, board):
        from collections import Counter
        expected = Counter([2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12])
        actual: list[int] = [
            h.number for h in board.hexes.values() if h.number is not None
        ]
        assert Counter(actual) == expected

    def test_desert_has_no_number(self, board):
        for h in board.hexes.values():
            if h.resource == ResourceType.DESERT:
                assert h.number is None

    def test_non_desert_has_number(self, board):
        for h in board.hexes.values():
            if h.resource != ResourceType.DESERT:
                assert h.number is not None

    def test_robber_starts_on_desert(self, board):
        desert_id = next(
            hid for hid, h in board.hexes.items()
            if h.resource == ResourceType.DESERT
        )
        assert board.robber_hex_id == desert_id

    def test_port_vertices_assigned(self, board):
        port_vertices = {
            vid for vid, v in board.vertices.items() if v.port is not None
        }
        # 9 ports × 2 vertices each = 18 port-vertex assignments
        assert len(port_vertices) == 18

    def test_no_buildings_or_roads_at_start(self, board):
        for v in board.vertices.values():
            assert v.building is None
        for e in board.edges.values():
            assert e.road_owner is None


# ---------------------------------------------------------------------------
# create_board — randomization constraints
# ---------------------------------------------------------------------------

class TestRandomization:
    def test_6_8_not_adjacent(self):
        for _ in range(20):
            board = create_board(randomize=True)
            hot = {hid for hid, h in board.hexes.items() if h.number in {6, 8}}
            for hid in hot:
                for neighbour in HEX_ADJACENT_HEXES[hid]:
                    assert neighbour not in hot, (
                        f"Hexes {hid} and {neighbour} are both 6/8 and adjacent"
                    )

    def test_randomization_differs(self):
        boards = [create_board(randomize=True) for _ in range(5)]
        resource_seqs = [
            tuple(boards[i].hexes[h].resource for h in range(19))
            for i in range(5)
        ]
        assert len(set(resource_seqs)) > 1, "All boards have identical resource layouts"

    def test_seed_reproducible(self):
        b1 = create_board(randomize=True, seed=42)
        b2 = create_board(randomize=True, seed=42)
        for hid in range(19):
            assert b1.hexes[hid].resource == b2.hexes[hid].resource
            assert b1.hexes[hid].number == b2.hexes[hid].number


# ---------------------------------------------------------------------------
# get_game_state — information hiding
# ---------------------------------------------------------------------------

def _make_minimal_game_state() -> GameState:
    board = create_board(randomize=False)
    players = [
        PlayerState(
            player_id=i,
            resources={r: (i + 1) for r in ResourceType if r != ResourceType.DESERT},
            dev_cards=[DevCardType.KNIGHT, DevCardType.VICTORY_POINT],
            dev_cards_count=2,
            resource_count=5 * (i + 1),
            knights_played=i,
            roads_remaining=15,
            settlements_remaining=5,
            cities_remaining=4,
            public_vp=2,
            has_longest_road=False,
            has_largest_army=False,
        )
        for i in range(4)
    ]
    return GameState(
        board=board,
        players=players,
        current_player_id=0,
        phase=GamePhase.PRE_ROLL,
        turn_number=1,
        dice=None,
        pending_trades=[],
        trades_proposed_this_turn=0,
        dev_cards_remaining=25,
        longest_road_player=None,
        largest_army_player=None,
    )


class TestGetGameState:
    @pytest.fixture(scope="class")
    def master(self) -> GameState:
        return _make_minimal_game_state()

    def test_own_resources_visible(self, master):
        for pid in range(4):
            view = get_game_state(master, pid)
            own = view.players[pid]
            expected = {r: (pid + 1) for r in ResourceType if r != ResourceType.DESERT}
            assert own.resources == expected

    def test_other_resources_hidden(self, master):
        for viewer in range(4):
            view = get_game_state(master, viewer)
            for pid, player in enumerate(view.players):
                if pid != viewer:
                    assert all(v == 0 for v in player.resources.values()), (
                        f"Viewer {viewer}: player {pid} resources not zeroed"
                    )

    def test_own_dev_cards_visible(self, master):
        for pid in range(4):
            view = get_game_state(master, pid)
            assert view.players[pid].dev_cards == [DevCardType.KNIGHT, DevCardType.VICTORY_POINT]

    def test_other_dev_cards_hidden(self, master):
        for viewer in range(4):
            view = get_game_state(master, viewer)
            for pid, player in enumerate(view.players):
                if pid != viewer:
                    assert player.dev_cards == [], (
                        f"Viewer {viewer}: player {pid} dev_cards not hidden"
                    )

    def test_public_counts_preserved(self, master):
        for viewer in range(4):
            view = get_game_state(master, viewer)
            for pid, player in enumerate(view.players):
                expected_rc = 5 * (pid + 1)
                assert player.resource_count == expected_rc, (
                    f"Viewer {viewer}: player {pid} resource_count wrong"
                )
                assert player.dev_cards_count == 2

    def test_master_state_unchanged(self, master):
        original_resources = [
            dict(p.resources) for p in master.players
        ]
        original_dev_cards = [list(p.dev_cards) for p in master.players]

        for viewer in range(4):
            get_game_state(master, viewer)

        for pid, player in enumerate(master.players):
            assert dict(player.resources) == original_resources[pid]
            assert list(player.dev_cards) == original_dev_cards[pid]

    def test_board_fully_public(self, master):
        """All players see the same board data."""
        boards = [get_game_state(master, pid).board for pid in range(4)]
        hex_resources = [
            [b.hexes[h].resource for h in range(19)] for b in boards
        ]
        assert all(hr == hex_resources[0] for hr in hex_resources)

    def test_returns_deep_copy(self, master):
        view = get_game_state(master, 0)
        view.players[0].resources[ResourceType.WOOD] = 999
        assert master.players[0].resources[ResourceType.WOOD] != 999
