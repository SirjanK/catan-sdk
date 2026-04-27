# catan-sdk

Public Python SDK for building, testing, simulating, packaging, and registering Catan bots. This is the repo bot authors should start in.

The hosted tournament site is [catan.bot](https://catan.bot).

---

## Quick Start

If you want to build a bot from scratch, this is the shortest sensible path:

1. Clone the repo and install dependencies
2. Copy the example bot and describe the strategy you want
3. Use an agent like Codex or Claude to help implement and iterate
4. Run the validator harness until it is clean
5. Simulate against `BasicPlayer` and `HeuristicBot`
6. Package and register the bot
7. Browse [catan.bot](https://catan.bot) for open tournaments, uploaded bots, and replays

### Clone and install

```bash
git clone https://github.com/SirjanK/catan-sdk.git
cd catan-sdk
uv sync --extra dev
```

### Start a bot

```bash
cp submissions/example_bot.py submissions/my_bot.py
```

Good prompt for an agent:

> Help me build a Catan bot in `submissions/my_bot.py`. Keep it legal under the validator, start from `BasicPlayer`-level competence, and improve placement, bank trades, and robber targeting step by step.

Best references while iterating:

- `submissions/example_bot.py` — minimal starting stub
- `catan/players/basic_player.py` — simplest complete legal bot
- `submissions/heuristic_bot.py` — stronger strategic baseline
- `submissions/planner_bot.py` — cleaner goal-oriented strategy example

### Validate locally

```bash
uv run pytest catan/tests/test_dev_validator.py --player=submissions.my_bot:MyBot -v
```

That validator harness should pass cleanly before you upload.

### Simulate

```bash
uv run python -m catan.sim \
  --bot submissions.my_bot:MyBot \
  --bot basic:BasicPlayer \
  --games 200 \
  --workers 4

uv run python -m catan.sim \
  --bot submissions.my_bot:MyBot \
  --bot submissions.heuristic_bot:HeuristicBot \
  --games 200 \
  --workers 4
```

### Package and register

```bash
uv run python -m catan.submit submissions.my_bot:MyBot

uv run python -m catan.register \
  --username your_username \
  --zip MyBot.zip
```

`catan.register` defaults to `https://catan.bot`. Override it with `--url` or `CATAN_SERVER_URL` when targeting a local or private deployment.

After uploading, sign in at [catan.bot](https://catan.bot), browse tournaments, and join any open bracket you are eligible for.

---

## Installation

### Bot developers

Install from PyPI:

```bash
pip install catan-sdk
# or
uv pip install catan-sdk
```

### SDK contributors

Use an editable checkout:

```bash
git clone https://github.com/SirjanK/catan-sdk.git
cd catan-sdk
uv sync --extra dev
```

---

## Building a Bot

### 1. Implement the Player interface

```bash
cp submissions/example_bot.py submissions/my_bot.py
```

```python
from catan.player import Player
from catan.models.state import GameState
from catan.models.actions import PlaceSettlement, PlaceRoad


class MyBot(Player):
    def __init__(self, player_id: int, seed: int = 0):
        self.player_id = player_id

    def setup_place_settlement(self, state: GameState) -> PlaceSettlement: ...
    def setup_place_road(self, state: GameState, settlement_vertex_id: int) -> PlaceRoad: ...
    def pre_roll_action(self, state: GameState): ...
    def discard_cards(self, state: GameState, count: int): ...
    def move_robber(self, state: GameState): ...
    def take_turn(self, state: GameState): ...
    def respond_to_trade(self, state: GameState, proposal): ...
```

The `GameState` passed to your bot is a deep copy. Opponent hands are hidden, but board state, piece counts, public VP, `resource_count`, and `dev_cards_count` are visible.

### Player methods

| Method | Phase | Return type |
|--------|-------|-------------|
| `setup_place_settlement(state)` | Setup | `PlaceSettlement` |
| `setup_place_road(state, settlement_vertex_id)` | Setup | `PlaceRoad` |
| `pre_roll_action(state)` | Start of turn | `RollDice` or `PlayKnight` |
| `discard_cards(state, count)` | After 7 rolled | `DiscardCards` |
| `move_robber(state)` | After knight / 7 | `MoveRobber` |
| `take_turn(state)` | Main turn | Any valid action or `Pass` |
| `respond_to_trade(state, proposal)` | Any player's turn | `AcceptTrade` or `RejectTrade` |

---

### 2. Validate your bot

```bash
uv run pytest catan/tests/test_dev_validator.py --player=submissions.my_bot:MyBot -v
```

The local harness covers setup, robber movement, discards, dev card timing, trade responses, piece limits, and state immutability.

---

### 3. Run a game locally

```bash
uv run python -m catan.run catan/examples/four_basic_players.yaml
```

To mix your own bot into a YAML:

```yaml
players:
  - type: submissions.my_bot:MyBot
  - type: basic
  - type: basic
  - type: basic
```

---

### 4. Watch replays

Drag a `.jsonl` replay into the public viewer at [https://catan.bot/viewer](https://catan.bot/viewer).

Use:

- left/right arrow keys to step through frames
- End to jump to the final state
- Batch Results to inspect full simulation folders

---

### 5. Simulate many games

```bash
uv run python -m catan.sim \
  --bot submissions.my_bot:MyBot \
  --bot basic:BasicPlayer \
  --games 200 \
  --workers 4 \
  --save-logs
```

Example output:

```text
Results — 200 games, random boards
Bot                       Games   Wins  Win%    Avg VP   Avg Place   1st   2nd   3rd   4th
MyBot                       200     82  41.0%     7.6       1.8      41%   28%   21%   10%
BasicPlayer                 200     38  19.0%     6.0       2.6      19%   24%   27%   30%
```

Seating is shuffled each game by default so that no bot benefits from a fixed first-player position. Use `--fix-order` to keep seat 0 = first `--bot` arg.

Useful flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--games N` | 100 | Number of games |
| `--workers N` | 1 | Parallel processes |
| `--fix-order` | off | Keep seating fixed (seat 0 = first `--bot`); default shuffles each game |
| `--fixed-board` | off | Reuse one board across all games |
| `--board-seed N` | same as `--seed` | Seed for the fixed board |
| `--save-logs` | off | Write per-game `.jsonl` files |
| `--output FILE` | — | Write JSON summary to a file |

With `--save-logs`, upload the full `tmp/sim/<run>/` directory contents to [https://catan.bot/viewer](https://catan.bot/viewer). The viewer needs `index.json` plus the per-game `.jsonl` files.

---

### 6. Package and register for the tournament

```bash
uv run python -m catan.submit submissions.my_bot:MyBot

uv run python -m catan.register \
  --token ctn_<your_token> \
  --zip MyBot.zip \
  --name "My Bot v2"
```

You can also use username/password:

```bash
uv run python -m catan.register \
  --username your_username \
  --zip MyBot.zip
```

API tokens are created from the logged-in site at `Settings -> API Tokens`.

---

## Unsupported Dependencies

Bot submissions are only allowed to import from the approved runtime dependency set. If you need a package that is not currently supported:

1. open an issue or PR in `catan-sdk`
2. explain the use case and why the dependency is needed for bots
3. update both:
   - `pyproject.toml` under `[project.optional-dependencies.bot-extras]`
   - `catan/approved_imports.py`
4. include any validator or packaging adjustments if the new dependency changes the bot author workflow

That PR can then be reviewed for safety, footprint, and tournament compatibility before the dependency is made available to bot authors.

---

## What's in the SDK

```
catan-sdk/
  submissions/
    README.md              ← quick-start bot builder guide
    example_bot.py         ← minimal stub — copy this first
    heuristic_bot.py       ← advanced reference bot
    planner_bot.py         ← planning-style reference bot
  catan/
    player.py              ← Player ABC
    models/                ← Pydantic v2 models
    engine/
      engine.py            ← full game loop
      executor.py          ← state mutation functions
      validator.py         ← action validation + cost helpers
      dev_validator.py     ← bot validation harness
      logger.py            ← JSONL replay logger
    board/                 ← board generation + topology
    players/
      basic_player.py      ← baseline legal bot
      heuristic_bot.py     ← advanced reference implementation
      helpers.py           ← public utilities for bot authors
      registry.py          ← YAML short-name registry
    run.py                 ← local game CLI
    sim.py                 ← batch simulation CLI
    submit.py              ← bot packaging CLI
    register.py            ← tournament registration CLI
```

### Helper utilities

```python
from catan.players.helpers import (
    vertex_pip_score,
    valid_settlement_spots,
    valid_road_edges,
    best_city_vertex,
    has_resources,
    resource_deficit,
)
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) if you want to contribute to the SDK itself.
