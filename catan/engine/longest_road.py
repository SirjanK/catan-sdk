"""
Longest-road computation for a single player.

Algorithm: for every vertex that is an endpoint of a player-owned road,
run a DFS over the player's road graph, tracking visited *edges* (not
vertices) so that loops are handled correctly.  An opponent's
settlement or city at a vertex breaks continuity through that vertex.
"""

from __future__ import annotations

from catan.models.board import Board


def compute_longest_road(board: Board, player_id: int) -> int:
    """Return the length of the longest continuous road for *player_id*.

    "Continuous" means a path through the player's roads where:
    - Each edge is traversed at most once.
    - Passing *through* a vertex is blocked if an opponent's building sits
      there (you can still count the incoming edge, but cannot continue).

    Returns 0 if the player has no roads.
    """

    def other_end(edge_id: int, vertex_id: int) -> int:
        va, vb = board.edges[edge_id].vertex_ids
        return vb if va == vertex_id else va

    def dfs(vertex: int, visited_edges: set) -> int:
        best = 0
        for eid in board.vertices[vertex].adjacent_edge_ids:
            if eid in visited_edges:
                continue
            if board.edges[eid].road_owner != player_id:
                continue
            nxt = other_end(eid, vertex)
            bldg = board.vertices[nxt].building
            visited_edges.add(eid)
            if bldg is None or bldg.player_id == player_id:
                # Can continue past this vertex
                best = max(best, 1 + dfs(nxt, visited_edges))
            else:
                # Opponent blocks passage; count this edge but stop
                best = max(best, 1)
            visited_edges.discard(eid)
        return best

    # Collect all vertices that touch at least one player road
    start_vertices: set[int] = set()
    for edge in board.edges.values():
        if edge.road_owner == player_id:
            start_vertices.add(edge.vertex_ids[0])
            start_vertices.add(edge.vertex_ids[1])

    max_length = 0
    for v in start_vertices:
        length = dfs(v, set())
        max_length = max(max_length, length)

    return max_length
