# CLAUDE.md

Guidance for Claude Code when working in `catan-sdk`.

## Commands

```bash
# Install
uv sync --extra dev

# Full engine tests
uv run pytest catan/tests/

# Single file
uv run pytest catan/tests/test_executor.py

# Bot validator harness
uv run pytest catan/tests/test_dev_validator.py --player=submissions.my_bot:MyBot -v

# Package a bot
uv run python -m catan.submit submissions.my_bot:MyBot

# Run a local game
uv run python -m catan.run catan/examples/four_basic_players.yaml
uv run python -m catan.run catan/examples/heuristic_vs_basic.yaml

# Simulate
uv run python -m catan.sim --bot submissions.my_bot:MyBot --bot basic:BasicPlayer --games 200 --workers 4
uv run python -m catan.sim --bot submissions.my_bot:MyBot --bot submissions.heuristic_bot:HeuristicBot --games 200 --workers 4

# Register to the hosted site (default server is https://catan.bot)
uv run python -m catan.register --token ctn_<token> --zip MyBot.zip
uv run python -m catan.register --username your_username --zip MyBot.zip
```

## Repo Shape

```
catan-sdk/
  submissions/
    README.md          ← bot-builder guide for humans and agents
    example_bot.py     ← minimal stub
    heuristic_bot.py   ← stronger reference bot
  catan/
    player.py          ← Player ABC
    models/            ← GameState, actions, enums, board
    engine/            ← game loop, validator, executor, logger
    board/             ← topology, board generation, viz_topology (interactive board viz)
    players/           ← built-in bots and helper utilities
    run.py             ← local game CLI
    sim.py             ← simulation CLI
    submit.py          ← packaging CLI
    register.py        ← tournament registration CLI
```

`catan/` has no `__init__.py` — it is a namespace package. TournamentEngine extends the same namespace with `catan/api/`, `catan/viz/` etc. from its own directory.

## Important Facts

- `test_dev_validator.py` reports 33 pytest tests; internally `DevValidator` performs 31 core checks
- `catan.register` defaults to `https://catan.bot`
- API tokens are created from the site UI under `Settings -> API Tokens`
- `httpx` ships as a standard dependency of the SDK
- approved bot runtime dependencies are defined in:
  - `pyproject.toml` (`bot-extras`)
  - `catan/approved_imports.py`

## Bot Author Workflow

When helping author a bot:

1. start from `submissions/example_bot.py`
2. use `catan/players/basic_player.py` for the simplest complete baseline
3. use `submissions/heuristic_bot.py` for stronger patterns
4. keep the bot validator-clean at every step
5. simulate against both `BasicPlayer` and `HeuristicBot`
6. package with `catan.submit`
7. register with `catan.register`

## Repo Boundaries

`catan-sdk` owns:

- public engine/model APIs
- public helper utilities for bots
- packaging / registration / simulation CLIs
- validator behavior that bot authors depend on

`TournamentEngine` owns:

- hosted backend/frontend behavior
- auth flows on the server
- tournament orchestration
- deployment and infrastructure
