# Contributing to catan-sdk

Thanks for your interest in contributing to the Catan engine. This guide is for contributors to the SDK itself — if you're building a bot, see `submissions/README.md` instead.

---

## Reporting Bugs

File an issue on [GitHub Issues](https://github.com/SirjanK/catan-sdk/issues). Include:

- A minimal reproduction (YAML config + bot code, or a failing test)
- What you expected vs. what happened
- Python version and OS

---

## What belongs where

| Change | Repo |
|--------|------|
| Engine logic, models, board, validator, executor | `catan-sdk` (this repo) |
| New Player methods or changes to the Player ABC | `catan-sdk` |
| Test fixtures for bot validation (`dev_validator.py`) | `catan-sdk` |
| Tournament orchestration, seeding rounds, Baranyai partition | `TournamentEngine` (private) |
| FastAPI backend, auth, bot storage | `TournamentEngine` (private) |
| React frontend, viz | `TournamentEngine` (private) |

If you're unsure, open an issue first.

---

## Development Setup

```bash
git clone https://github.com/SirjanK/catan-sdk.git
cd catan-sdk
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest catan/tests/
```

The `test_viz_geometry.py` file is intentionally excluded from the default run (it tests frontend topology only). Skip it explicitly if needed:

```bash
pytest catan/tests/ --ignore=catan/tests/test_viz_geometry.py
```

---

## Code Style

- **Python 3.11+**
- **Pydantic v2** for all models
- No external dependencies in the core engine (`catan/engine/`, `catan/models/`, `catan/board/`) beyond `pydantic` and `pyyaml`
- Type annotations on all public functions
- No `print()` in engine code — use `GameLogger` or return values

## PR Guide

1. Fork the repo and create a branch: `git checkout -b fix/my-fix`
2. Make your change with tests
3. Ensure `pytest catan/tests/` passes fully
4. Open a PR against `main` with a clear description of what changed and why
