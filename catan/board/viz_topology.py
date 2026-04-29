"""
Topology visualizer for the Catan board.

Renders:
  - Hex outlines with (q,r) coords and hex_id label
  - Vertex IDs at each corner
  - Edge IDs at each edge midpoint
  - Port positions highlighted with port type

Usage:
    python -m catan.board.viz_topology                   # show interactively
    python -m catan.board.viz_topology --out board.png   # save to file
"""

from __future__ import annotations

import argparse
import math
from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch, Polygon
from matplotlib.collections import LineCollection
import numpy as np

from catan.board.topology import (
    HEX_COORDS,
    HEX_VERTICES,
    HEX_EDGES,
    EDGE_VERTICES,
    PORT_ASSIGNMENTS,
    NUM_HEXES,
    QR_TO_HEX_ID,
    HEX_ID_TO_QR,
)
from catan.models.enums import PortType

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

HEX_SIZE = 1.0  # distance from center to corner


def hex_center(q: int, r: int) -> tuple[float, float]:
    """Pixel center of hex (q, r) — pointy-top axial layout."""
    x = HEX_SIZE * (math.sqrt(3) * q + math.sqrt(3) / 2 * r)
    y = HEX_SIZE * (3 / 2 * r)
    return x, y


def corner_xy(q: int, r: int, corner: int) -> tuple[float, float]:
    """Absolute (x, y) of a specific corner (0=N, clockwise) of hex (q,r)."""
    cx, cy = hex_center(q, r)
    angle = math.radians(-90 + 60 * corner)
    return cx + HEX_SIZE * math.cos(angle), cy + HEX_SIZE * math.sin(angle)


def _build_vertex_positions() -> dict[int, tuple[float, float]]:
    """Map each vertex_id to its (x, y) position."""
    pos: dict[int, tuple[float, float]] = {}
    for hid in range(NUM_HEXES):
        q, r = HEX_ID_TO_QR[hid]
        for c, vid in enumerate(HEX_VERTICES[hid]):
            if vid not in pos:
                pos[vid] = corner_xy(q, r, c)
    return pos


# ---------------------------------------------------------------------------
# Port display helpers
# ---------------------------------------------------------------------------

PORT_LABELS: dict[PortType, str] = {
    PortType.GENERIC_3_1: "3:1",
    PortType.WOOD_2_1:    "2:1\nWOOD",
    PortType.BRICK_2_1:   "2:1\nBRICK",
    PortType.WHEAT_2_1:   "2:1\nWHEAT",
    PortType.ORE_2_1:     "2:1\nORE",
    PortType.SHEEP_2_1:   "2:1\nSHEEP",
}

PORT_COLORS: dict[PortType, str] = {
    PortType.GENERIC_3_1: "#cccccc",
    PortType.WOOD_2_1:    "#2d6a2d",
    PortType.BRICK_2_1:   "#b5451b",
    PortType.WHEAT_2_1:   "#d4a017",
    PortType.ORE_2_1:     "#607d8b",
    PortType.SHEEP_2_1:   "#80c080",
}


# ---------------------------------------------------------------------------
# Main draw function
# ---------------------------------------------------------------------------

def draw_topology(out: Optional[str] = None) -> None:
    vertex_pos = _build_vertex_positions()

    fig, ax = plt.subplots(figsize=(18, 16))
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("Catan Board Topology", fontsize=16, fontweight="bold", pad=14)

    # --- Draw hex outlines and center labels ---
    for hid in range(NUM_HEXES):
        q, r = HEX_ID_TO_QR[hid]
        vids = HEX_VERTICES[hid]
        pts = np.array([vertex_pos[v] for v in vids])
        poly = Polygon(pts, closed=True, fill=True,
                       facecolor="#f9f4e8", edgecolor="#888888", linewidth=1.2, zorder=1)
        ax.add_patch(poly)

        cx, cy = hex_center(q, r)
        # hex_id (large) and (q,r) (small) stacked
        ax.text(cx, cy + 0.18, f"hex {hid}", ha="center", va="center",
                fontsize=7.5, fontweight="bold", color="#444444", zorder=3)
        ax.text(cx, cy - 0.15, f"({q},{r})", ha="center", va="center",
                fontsize=7, color="#777777", zorder=3)

    # --- Draw edge IDs at midpoints ---
    for eid, (va, vb) in EDGE_VERTICES.items():
        x0, y0 = vertex_pos[va]
        x1, y1 = vertex_pos[vb]
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2

        # Tiny white backing box for readability
        ax.text(mx, my, str(eid), ha="center", va="center",
                fontsize=5.5, color="#1a5276",
                bbox=dict(boxstyle="round,pad=0.1", facecolor="white",
                          edgecolor="#aaaaaa", linewidth=0.5, alpha=0.85),
                zorder=5)

    # --- Draw vertex IDs ---
    for vid, (x, y) in vertex_pos.items():
        ax.plot(x, y, "o", markersize=11, color="#e8f4f8",
                markeredgecolor="#2c3e50", markeredgewidth=0.8, zorder=6)
        ax.text(x, y, str(vid), ha="center", va="center",
                fontsize=5.5, fontweight="bold", color="#2c3e50", zorder=7)

    # --- Draw ports ---
    port_handles = {}
    for port_type, va, vb in PORT_ASSIGNMENTS:
        x0, y0 = vertex_pos[va]
        x1, y1 = vertex_pos[vb]
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2

        # Direction pointing outward (perpendicular to edge, away from board center)
        dx, dy = x1 - x0, y1 - y0
        perp_x, perp_y = -dy, dx  # rotate 90°
        # Normalise and flip toward the exterior (away from origin)
        length = math.hypot(perp_x, perp_y)
        perp_x /= length
        perp_y /= length
        # The board centre is at (0,0); push outward if dot product with
        # midpoint vector is positive, inward otherwise.
        if perp_x * mx + perp_y * my < 0:
            perp_x, perp_y = -perp_x, -perp_y

        offset = 0.45
        lx, ly = mx + perp_x * offset, my + perp_y * offset

        color = PORT_COLORS[port_type]
        label = PORT_LABELS[port_type]

        # Highlight the port edge
        ax.plot([x0, x1], [y0, y1], color=color, linewidth=4, zorder=4, solid_capstyle="round")
        # Port label box
        ax.text(lx, ly, label, ha="center", va="center",
                fontsize=6.5, fontweight="bold", color="white",
                bbox=dict(boxstyle="round,pad=0.3", facecolor=color,
                          edgecolor="white", linewidth=0.8, alpha=0.93),
                zorder=8)

        if port_type not in port_handles:
            port_handles[port_type] = mpatches.Patch(
                facecolor=color, edgecolor="white", label=PORT_LABELS[port_type].replace("\n", " ")
            )

    # --- Legend for ports ---
    ax.legend(
        handles=list(port_handles.values()),
        title="Ports",
        loc="lower right",
        fontsize=7,
        title_fontsize=8,
        framealpha=0.9,
    )

    fig.tight_layout()

    if out:
        fig.savefig(out, dpi=180, bbox_inches="tight")
        print(f"Saved to {out}")
    else:
        plt.show()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visualize Catan board topology")
    parser.add_argument("--out", metavar="FILE", default=None,
                        help="Save to file instead of showing interactively (e.g. board.png)")
    args = parser.parse_args()
    draw_topology(out=args.out)
