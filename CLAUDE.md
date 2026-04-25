# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (from repo root)
uv sync --extra dev

# Run all engine tests
pytest catan/tests/

# Run a single test file
pytest catan/tests/test_executor.py

# Run a single test by name
pytest catan/tests/test_validator.py -k "test_name"

# Validate a bot implementation (AST scan + 33 fixture tests + package)
python -m catan.submit submissions.my_bot:MyBot

# Run bot-specific validator tests (33 fixture tests)
pytest catan/tests/test_dev_validator.py --player=submissions.my_bot:MyBot -v

# Run a game from a YAML config (output goes to tmp/games/)
python -m catan.run catan/examples/four_basic_players.yaml
python -m catan.run catan/examples/heuristic_vs_basic.yaml

# Simulate many games
python -m catan.sim --bot submissions.my_bot:MyBot --bot basic:BasicPlayer --games 200 --workers 4

# Compare against HeuristicBot (a harder benchmark)
python -m catan.sim --bot submissions.my_bot:MyBot --bot submissions.heuristic_bot:HeuristicBot --games 200 --workers 4

# Upload bot to tournament server (API token — preferred for agents/CI)
python -m catan.register \
  --url http://localhost:8000 \
  --token ctn_<api_token> \
  --zip MyBot.zip \
  --name "My Bot v1"

# Upload bot (username/password flow — prompts once, caches JWT 24 h in ~/.catan/tokens.json)
python -m catan.register \
  --url http://localhost:8000 \
  --username your_username \
  --zip MyBot.zip \
  --name "My Bot v1"
```

## Architecture

```
catan-sdk/
  submissions/
    README.md              ← bot-builder guide + helpers reference (for both humans and agents)
    example_bot.py         ← minimal stub — copy this to start
    heuristic_bot.py       ← advanced reference bot (~37–41% win rate in 4-player)
    planner_bot.py         ← planning-style reference (~33% win rate in 4-player)
  catan/
    player.py              ← Player ABC — 7 abstract methods bots must implement
    models/                ← Pydantic v2 models (GameState, actions, enums, board)
    engine/
      engine.py            ← CatanEngine.run_game(players, logger)
      executor.py          ← pure state mutation functions
      validator.py         ← action validation + ROAD_COST / SETTLEMENT_COST / CITY_COST / DEV_CARD_COST
      dev_validator.py     ← 33 fixture tests for bot validation
      logger.py            ← GameLogger writes JSONL replay files
      longest_road.py      ← DFS-based longest road computation
    board/                 ← board generation and topology
    players/
      basic_player.py      ← simple reference bot (~17% win rate in 4-player)
      helpers.py           ← PUBLIC utilities (vertex_pip_score, valid_settlement_spots, …)
      registry.py          ← PLAYER_REGISTRY: "basic" → BasicPlayer, "heuristic" → HeuristicBot
    config.py              ← GameConfig, PlayerConfig (YAML → Pydantic)
    run.py / sim.py / submit.py / register.py  ← CLI entry points
    tests/                 ← engine correctness tests
```

### Key components

- **`catan/player.py`** — `Player` ABC. Bots implement: `setup_place_settlement`, `setup_place_road`, `pre_roll_action`, `discard_cards`, `move_robber`, `take_turn`, `respond_to_trade`.
- **`catan/engine/engine.py`** — `CatanEngine` orchestrates a full game. Entry: `CatanEngine(seed=42).run_game(players, logger=logger)`.
- **`catan/engine/validator.py`** — Pure action validation, called before execution. Exports `ROAD_COST`, `SETTLEMENT_COST`, `CITY_COST`, `DEV_CARD_COST`, `get_port_ratio`.
- **`catan/players/helpers.py`** — Public utilities for bot authors. Import instead of reimplementing.
- **`catan/models/`** — Pydantic v2: `state.py` (GameState, PlayerState), `actions.py` (all action types), `enums.py`.
- **`catan/board/`** — Board topology, hex setup, port placement.

**Game loop**: setup phase (snake draft) → main turns (pre-roll → roll → distribute → actions until Pass) → game over at 10 VP.

**Player timeouts**: 2s for most methods; 200ms for `respond_to_trade`.

**GameState visibility**: opponent resources/dev_cards are zeroed. Board, VP counts, piece counts, resource_count, dev_cards_count are public.

## Key Conventions

- Python 3.11+, Pydantic v2.
- Hex coords: pointy-top axial. Corner 0 = N, clockwise: N, NE, SE, S, SW, NW.
- Game replays are JSONL: records `game_start`, `board_layout`, `action`, `turn_state`, `dice_roll`, `game_end`.
- `submissions/` is unignored for `example_bot.py`, `heuristic_bot.py`, `planner_bot.py`, and `README.md`.
- `uv.lock` is committed for reproducible installs; run `uv lock` after changing `pyproject.toml`.

## Bot Development Workflow (for agents)

The full loop an agent should follow when writing and submitting a new bot:

1. **Write** the bot in `submissions/my_bot.py` — subclass `Player`, implement all 7 methods.  Use `submissions/example_bot.py` as the stub; reference `submissions/heuristic_bot.py` or `submissions/planner_bot.py` for patterns.

2. **Test** with the 33 fixture tests:
   ```bash
   pytest catan/tests/test_dev_validator.py --player=submissions.my_bot:MyBot -v
   ```
   All 33 must pass before uploading.

3. **Run a game** to spot obvious bugs:
   ```bash
   python -m catan.run catan/examples/four_basic_players.yaml
   ```

4. **Simulate** win rates (200 games, 4 workers is a good default):
   ```bash
   python -m catan.sim --bot submissions.my_bot:MyBot --bot basic:BasicPlayer --games 200 --workers 4
   python -m catan.sim --bot submissions.my_bot:MyBot --bot submissions.heuristic_bot:HeuristicBot --games 200 --workers 4
   ```

5. **Package**:
   ```bash
   python -m catan.submit submissions.my_bot:MyBot   # → MyBot.zip in cwd
   ```

6. **Upload** (`httpx` is a standard dependency — no separate install needed):
   ```bash
   # --name defaults to the class name read from the zip manifest if omitted
   python -m catan.register --url http://localhost:8000 --token ctn_<token> --zip MyBot.zip
   # Override the display name:
   python -m catan.register --url http://localhost:8000 --token ctn_<token> --zip MyBot.zip --name "My Bot"
   ```
   The same zip can be uploaded under multiple names by repeating with `--name "..."`.

7. **Dry-run** to verify the zip is accepted without consuming a bot slot:
   ```bash
   python -m catan.register --url http://localhost:8000 --token ctn_<token> --zip MyBot.zip --dry-run
   ```

## Tournament Server

- **Local URL**: `http://localhost:8000/`
- **API token format**: `ctn_` prefix followed by a hex string — generate at `http://localhost:8000/tokens`.
- **Endpoints used by the CLI**: `POST /bots` (upload), `POST /auth/login` (JWT flow).
- **Viewer**: drag a `.jsonl` from `tmp/games/` onto `http://localhost:8000/viewer` to watch a replay.
- The server runs the same 33 fixture tests + an AST import scan on upload.  A bot that passes local tests should pass server-side.

## Win Rate Benchmarks (4-player, 200 games)

| Bot | Typical Win% |
|-----|-------------|
| BasicPlayer | ~17% |
| PlannerBot | ~33% |
| HeuristicBot | ~37–41% |

A new bot should aim to beat BasicPlayer before considering it tournament-ready.

## Common Pitfalls

- **`httpx` is a main dependency** — it ships with the SDK. If you see an ImportError, run `uv sync` to realign the environment.
- **`--name` defaults to the class name** from the zip's `manifest.json` — you only need `--name` to override the display name.
- **`uv run` prefix**: Always use `uv run python -m ...` or `uv run pytest` if not inside the activated venv. The `VIRTUAL_ENV=venv does not match .venv` warning is benign.
- **`take_turn` is called in a loop**: Return `Pass()` to end the turn. Each call is one action. Use `state.turn_actions` to see what you've already done this turn (e.g., check `"bank_trade" in state.turn_actions`), or maintain per-turn flags reset in `pre_roll_action`.
- **Sim output**: each bot appears twice when fewer than 4 bots are given (seats filled with duplicates). Stats are now automatically aggregated by bot name.
- **Opponent hands are hidden**: `state.players[other_pid].resources` is zeroed; use `resource_count` for the count only.
- **Piece supply limits**: Always check `settlements_remaining`, `cities_remaining`, `roads_remaining` before building. Attempting to build with 0 pieces fails validation.
- **Dev card draw timing**: A dev card bought this turn cannot be played this turn (engine enforces this for all card types except VP).
- **Submission restrictions**: Do not import `os`, `subprocess`, `socket`, `urllib`, `requests`, `sys`, `threading`, `multiprocessing`, `shutil`, `open`, `exec`, `eval`, or `__import__`. The server AST-scans for these.
