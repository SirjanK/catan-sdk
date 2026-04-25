"""
Stable helper exports for consumers that also define a top-level `catan` package.

TournamentEngine installs catan-sdk alongside its own `catan` package, which
would otherwise shadow `catan.approved_imports`. Re-export the approved import
helpers from a non-shadowed package name so downstream code can import them
directly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_approved_imports():
    module_path = Path(__file__).resolve().parent.parent / "catan" / "approved_imports.py"
    spec = importlib.util.spec_from_file_location("_catan_sdk_approved_imports", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_approved_imports = _load_approved_imports()
APPROVED_THIRD_PARTY = _approved_imports.APPROVED_THIRD_PARTY
check_bot_imports = _approved_imports.check_bot_imports

__all__ = ["APPROVED_THIRD_PARTY", "check_bot_imports"]
