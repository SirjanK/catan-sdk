"""
catan.submit — package and validate a bot before uploading.

Usage:
    python -m catan.submit submissions.my_bot:MyBot

What it does:
  1. Imports and instantiates your Player subclass.
  2. Runs PlayerValidator against it — exits with a clear error if anything fails.
  3. Creates <BotName>.zip containing:
       player.py       — the source file of your bot class (or __init__.py for packages)
       <helpers>.py    — any other .py files in your bot package (if it's a package)
       manifest.json   — class name, module, created_at timestamp

Multi-file bots
---------------
If your bot is a Python *package* (a directory with __init__.py), the entire
package directory is zipped so that helper modules are available at runtime.

    submissions/
        my_bot/
            __init__.py   # contains class MyBot(Player): ...
            utils.py      # imported by __init__.py

    python -m catan.submit submissions.my_bot:MyBot

Single-file bots (the original format) continue to work as before.
"""

from __future__ import annotations

import importlib
import inspect
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def _load_class(spec: str):
    """Import and return the Player subclass from 'module.path:ClassName'."""
    if ":" not in spec:
        print(f"ERROR: --player spec must be 'module:ClassName', got: {spec!r}")
        sys.exit(1)
    module_path, class_name = spec.rsplit(":", 1)
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        print(f"ERROR: Cannot import module '{module_path}': {e}")
        sys.exit(1)
    if not hasattr(module, class_name):
        print(f"ERROR: Module '{module_path}' has no class '{class_name}'")
        sys.exit(1)
    return getattr(module, class_name), module


def _check_imports(cls, module) -> None:
    """Verify every import in the bot's source files is from an approved package."""
    from catan.approved_imports import APPROVED_THIRD_PARTY, check_bot_imports

    source_file = Path(inspect.getfile(module))
    is_package = hasattr(module, "__path__")
    files = list(source_file.parent.rglob("*.py")) if is_package else [source_file]

    sources = []
    for f in files:
        try:
            sources.append((str(f), f.read_text(encoding="utf-8")))
        except OSError as e:
            print(f"WARNING: could not read {f}: {e}")

    print(f"Checking imports in {len(sources)} file(s) ...")
    ok, violations = check_bot_imports(sources)
    if ok:
        print(f"  Import check passed.")
    else:
        print("\nIMPORT CHECK FAILED — unapproved dependencies detected:")
        for v in violations:
            print(f"  {v}")
        approved = ", ".join(sorted(APPROVED_THIRD_PARTY))
        print(f"\nApproved third-party packages: {approved}")
        print("To request a new package, open a PR to catan-sdk and add it to:")
        print("  pyproject.toml  [project.optional-dependencies.bot-extras]")
        print("  catan/approved_imports.py  APPROVED_THIRD_PARTY")
        sys.exit(1)


def _validate(cls) -> None:
    """Run PlayerValidator; exit with failure details on any check failure."""
    from catan.engine.dev_validator import DevValidator as PlayerValidator

    print(f"Running DevValidator against {cls.__name__} ...")
    validator = PlayerValidator(cls)
    result = validator.run()
    if result.passed:
        print(
            f"  All {len(result.passes)} validator checks passed."
            "  (pytest test_dev_validator.py runs 2 additional harness tests.)"
        )
    else:
        print(result.summary())
        sys.exit(1)


def _create_zip(cls, module, out_dir: Path) -> Path:
    """Build <BotName>.zip and return its path."""
    bot_name = cls.__name__
    zip_path = out_dir / f"{bot_name}.zip"

    source_file = Path(inspect.getfile(module))
    is_package = hasattr(module, "__path__")  # packages have __path__, modules don't

    manifest = {
        "class_name": bot_name,
        "module": module.__name__,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "is_package": is_package,
    }

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if is_package:
            # Zip all .py files from the package directory.
            # The primary class file (__init__.py) is archived as player.py;
            # all other .py files keep their original names so they remain importable.
            pkg_dir = source_file.parent
            for py_file in sorted(pkg_dir.rglob("*.py")):
                arcname = py_file.relative_to(pkg_dir)
                dest_name = "player.py" if py_file.name == "__init__.py" else str(arcname)
                zf.write(py_file, arcname=dest_name)
            print(f"  Packaged {bot_name} (package with {len(list(pkg_dir.rglob('*.py')))} .py files)")
        else:
            # Single-file bot: archive as player.py
            zf.write(source_file, arcname="player.py")

        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    return zip_path


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m catan.submit <module>:<ClassName>")
        print("Example: python -m catan.submit submissions.my_bot:MyBot")
        sys.exit(1)

    spec = sys.argv[1]
    cls, module = _load_class(spec)
    _check_imports(cls, module)
    _validate(cls)

    out_dir = Path(".")
    zip_path = _create_zip(cls, module, out_dir)
    print(f"\nPackaged: {zip_path.resolve()}")
    print("Upload options:")
    print(f"  CLI (recommended): python -m catan.register --url <tournament-url> --token ctn_<token> --zip {zip_path.name} --name \"<display name>\"")
    print(f"  Web UI: drag-and-drop at <tournament-site>/bots → Add Bot")


if __name__ == "__main__":
    main()
