# Contributing to catan-sdk

Thanks for helping improve the public SDK. This guide is for contributors to the engine, models, helpers, validator, and bot-author tooling. If you want to write a bot instead, start with [README.md](README.md) or [submissions/README.md](submissions/README.md).

---

## What Belongs Here

Use `catan-sdk` for:

- game engine behavior
- board/model/action definitions
- public helper utilities for bot authors
- `catan.submit`, `catan.register`, `catan.run`, and `catan.sim`
- `DevValidator` behavior and bot-author-facing validation UX
- approved bot runtime dependencies

Use `TournamentEngine` for:

- FastAPI backend routes and DB models
- hosted frontend behavior
- production deployment
- tournament orchestration and worker infrastructure

If a change spans both repos, it is usually best to land the public SDK contract here first.

---

## Development Setup

```bash
git clone https://github.com/SirjanK/catan-sdk.git
cd catan-sdk
uv sync --extra dev
```

Common commands:

```bash
# Full engine test suite
uv run pytest catan/tests/

# Single file
uv run pytest catan/tests/test_executor.py

# Bot validator harness
uv run pytest catan/tests/test_dev_validator.py --player=submissions.my_bot:MyBot -v

# Package a sample bot
uv run python -m catan.submit submissions.example_bot:ExampleBot

# Inspect CLI docs
uv run python -m catan.register --help
```

---

## Testing Expectations

Before opening a PR, run the narrowest relevant test slice and at least one of:

```bash
uv run pytest catan/tests/
```

or, for CLI / bot-author workflow changes:

```bash
uv run python -m catan.submit submissions.example_bot:ExampleBot
uv run python -m catan.register --help
```

Notes:

- `test_dev_validator.py` reports 33 pytest tests; internally that wraps 31 `DevValidator` checks plus harness coverage
- `test_viz_geometry.py` is intentionally not part of the default test path

---

## Dependency Changes for Bots

Bot submissions may only import approved dependencies. To add one:

1. update `pyproject.toml` under `[project.optional-dependencies.bot-extras]`
2. update `catan/approved_imports.py`
3. explain the use case in the PR
4. call out any tournament/runtime footprint concerns

If the dependency meaningfully changes the author workflow, update the docs too.

---

## PR Guide

Please include:

- what changed
- why it belongs in `catan-sdk`
- what you tested
- whether bot authors need to change anything

Good PRs here usually optimize for bot-author clarity as much as raw engine correctness.
