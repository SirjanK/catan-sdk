"""
Approved third-party packages for bot submissions.

Bot source files may only import from:
  - The Python standard library
  - The catan-sdk package itself (``catan.*``)
  - Packages listed in APPROVED_THIRD_PARTY below

To add a new package, open a PR to catan-sdk adding the importable name here
and the corresponding pip package to pyproject.toml [project.optional-dependencies.bot-extras].
"""

from __future__ import annotations

import ast
import sys
from typing import List, Tuple

# Importable root names of approved third-party packages.
# NOTE: pip name != import name for some packages (e.g. scikit-learn -> sklearn, pyyaml -> yaml).
APPROVED_THIRD_PARTY: frozenset[str] = frozenset({
    # catan-sdk core deps — bots may use these directly
    "pydantic",
    "yaml",             # pyyaml
    # bot-extras — common numerics / ML stack
    "numpy",
    "scipy",
    "pandas",
    "sklearn",          # scikit-learn
    "typing_extensions",
})

_ALWAYS_ALLOWED: frozenset[str] = frozenset({
    "catan",        # the SDK itself
    "__future__",
})


def _stdlib_roots() -> frozenset[str]:
    return frozenset(sys.stdlib_module_names)  # available since Python 3.10


def check_bot_imports(sources: List[Tuple[str, str]]) -> Tuple[bool, List[str]]:
    """
    Check that every import in the given source files is from an approved package.

    Args:
        sources: list of (filename, source_code) pairs

    Returns:
        (ok, violations) where violations are human-readable strings.
        Relative imports (``from . import X``) are always allowed.
    """
    stdlib = _stdlib_roots()
    allowed = stdlib | APPROVED_THIRD_PARTY | _ALWAYS_ALLOWED
    violations: List[str] = []

    for filename, source in sources:
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError as e:
            violations.append(f"{filename}: SyntaxError: {e}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in allowed:
                        violations.append(
                            f"{filename}:{node.lineno}: unapproved import '{alias.name}' "
                            f"— '{root}' is not in the approved package list"
                        )

            elif isinstance(node, ast.ImportFrom):
                if (node.level or 0) > 0:
                    continue  # relative import — always ok
                module = node.module or ""
                root = module.split(".")[0]
                if root and root not in allowed:
                    violations.append(
                        f"{filename}:{node.lineno}: unapproved import 'from {module} import ...' "
                        f"— '{root}' is not in the approved package list"
                    )

    return len(violations) == 0, violations
