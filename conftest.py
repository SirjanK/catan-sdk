"""Root conftest.py — shared pytest fixtures and options."""

from __future__ import annotations


def pytest_addoption(parser):
    parser.addoption(
        "--player",
        action="store",
        default=None,
        help=(
            "Module path and class name of a Player to validate, "
            "e.g. submissions.my_bot:MyBot"
        ),
    )
