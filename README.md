# catan-sdk

A Python game engine and bot development toolkit for Catan. Build a bot locally, test it against the engine, simulate thousands of games, watch replays on the hosted site, and register for the tournament — all from the command line.

---

## Installation

**Bot developers** — install from PyPI:

```bash
pip install catan-sdk
# or with uv:
uv pip install catan-sdk
```

**SDK contributors** — clone and install in editable mode:

```bash
git clone https://github.com/SirjanK/catan-sdk.git
cd catan-sdk
uv sync --extra dev   # installs all deps from uv.lock (reproducible)
# pip fallback: pip install -e ".[dev]"
```

---

## Building a Bot

### 1. Implement the Player interface

Copy the example template and implement all seven methods:

```bash
cp submissions/example_bot.py submissions/my_bot.py
```

```python
# submissions/my_bot.py
from catan.player import Player
from catan.models.state import GameState
from catan.models.actions import PlaceSettlement, PlaceRoad, RollDice, Pass

class MyBot(Player):
    def __init__(self, player_id: int, seed: int = 0):
        self.player_id = player_id

    def setup_place_settlement(self, state: GameState) -> PlaceSettlement: ...
    def setup_place_road(self, state, settlement_vid: int) -> PlaceRoad: ...
    def pre_roll_action(self, state: GameState): ...       # RollDice or PlayKnight
    def discard_cards(self, state, required: int): ...     # DiscardCards
    def move_robber(self, state: GameState): ...           # MoveRobber
    def take_turn(self, state: GameState): ...             # build / trade / Pass / …
    def respond_to_trade(self, state, offer): ...         # AcceptTrade or RejectTrade
```

The `GameState` you receive is a **deep copy** — mutate it freely. Opponent resource hands and dev cards are hidden (zeroed out); all board state, VP counts, piece counts, and `resource_count` / `dev_cards_count` are public.

See `catan/players/basic_player.py` for a complete reference implementation.

### The 7 Player methods

| Method | Phase | Return type |
|--------|-------|-------------|
| `setup_place_settlement(state)` | Setup | `PlaceSettlement` |
| `setup_place_road(state, settlement_vid)` | Setup | `PlaceRoad` |
| `pre_roll_action(state)` | Start of turn | `RollDice` or `PlayKnight` |
| `discard_cards(state, required)` | After 7 rolled | `DiscardCards` |
| `move_robber(state)` | After knight/7 | `MoveRobber` |
| `take_turn(state)` | Main turn | Any valid action or `Pass` |
| `respond_to_trade(state, offer)` | Any player's turn | `AcceptTrade` or `RejectTrade` |

---

### 2. Validate your bot

Run the fixture test suite against your bot (31 tests covering every method and edge case):

```bash
pytest catan/tests/test_dev_validator.py --player=submissions.my_bot:MyBot -v
```

Each failing test shows the scenario, what your bot returned, why it was rejected, and a hint to fix it.

---

### 3. Play a game

Run your bot against the built-in reference bot and watch what happens:

```bash
python -m catan.run catan/examples/four_basic_players.yaml
# → writes tmp/games/<timestamp>.jsonl
```

To mix your bot in, edit the YAML:

```yaml
players:
  - type: custom
    module: submissions.my_bot
    class: MyBot
  - type: basic
  - type: basic
  - type: basic
```

---

### 4. Watch the replay

Drag the `.jsonl` file into the hosted viewer at `https://catan.bot/viewer`.

- **Arrow keys** ← → step through actions frame by frame
- **End** key jumps to the final game state
- No login required

---

### 5. Simulate many games

```bash
python -m catan.sim \
  --bot submissions.my_bot:MyBot \
  --bot basic:BasicPlayer \
  --games 200 \
  --workers 4 \
  --save-logs
```

```
Results — 200 games, random boards
Bot                       Games   Wins  Win%    Avg VP   Avg Place   1st   2nd   3rd   4th
MyBot                       200     82  41.0%     7.6       1.8      41%   28%   21%   10%
BasicPlayer                 200     38  19.0%     6.0       2.6      19%   24%   27%   30%

Logs saved to: tmp/sim/run_20260419_120000/
  View results: upload tmp/sim/run_20260419_120000/index.json to https://catan.bot/viewer → Batch Results
```

**Key flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--games N` | 100 | Number of games |
| `--workers N` | 1 | Parallel processes |
| `--fixed-board` | off | Reuse one board across all games (isolates bot skill from board luck) |
| `--board-seed N` | same as `--seed` | Seed for the fixed board |
| `--save-logs` | off | Write per-game `.jsonl` files |
| `--output FILE` | — | Write JSON summary to a file |

---

### 6. Browse simulation results on the hosted viewer

Upload the `tmp/sim/<run>/` folder (or just `index.json`) to the **Batch Results** tab at `https://catan.bot/viewer`:

- Sortable/filterable table of all games with winner, VP, and turn count
- Click any game to step through it frame by frame inline

---

### 7. Package and register for the tournament

```bash
# Validate and package into a zip
python -m catan.submit submissions.my_bot:MyBot    # → MyBot.zip

# Upload to the tournament server
python -m catan.register \
  --username player1 \
  --zip MyBot.zip \
  --name "My Bot v2"      # optional; defaults to zip filename stem
```

`catan.register` defaults to `https://catan.bot`, caches your JWT at `~/.catan/tokens.json`, and only needs your password once per day. Override the server with `--url` or `CATAN_SERVER_URL` when testing locally.

---

## What's in the SDK

```
catan-sdk/
  submissions/
    README.md              ← read this first
    example_bot.py         ← minimal stub — copy and implement all 7 methods
    heuristic_bot.py       ← advanced reference: strategic heuristic bot (~2.5× BasicPlayer win rate)
  catan/
    player.py              ← Player ABC — implement this
    models/                ← Pydantic v2 models (GameState, actions, enums, board)
    engine/
      engine.py            ← CatanEngine — runs a full game
      executor.py          ← state mutation functions
      validator.py         ← action validation + resource cost constants
      logger.py            ← GameLogger — writes JSONL replay files
      dev_validator.py     ← 31 fixture tests for bot validation
    board/                 ← board generation and topology
    players/
      basic_player.py      ← simple reference bot (builds city > settlement > road > dev card)
      heuristic_bot.py     ← advanced reference (see submissions/heuristic_bot.py)
      helpers.py           ← public utilities: vertex_pip_score, valid_settlement_spots, etc.
      registry.py          ← local bot registry for YAML-driven games ("basic", "heuristic")
    config.py              ← GameConfig, PlayerConfig (YAML → Pydantic)
    run.py                 ← `python -m catan.run` CLI
    sim.py                 ← `python -m catan.sim` batch simulation CLI
    submit.py              ← `python -m catan.submit` bot packager
    register.py            ← `python -m catan.register` tournament registration
    tests/                 ← engine correctness tests
    examples/
      four_basic_players.yaml
      heuristic_vs_basic.yaml  ← 1 HeuristicBot vs 3 BasicPlayers
```

### Helper utilities

`catan.players.helpers` exposes common board-query functions so you don't have to reimplement them:

```python
from catan.players.helpers import (
    vertex_pip_score,       # sum of pip weights at a vertex (use for placement scoring)
    valid_settlement_spots, # vertices where you can build a settlement right now
    valid_road_edges,       # edges where you can build a road right now
    best_city_vertex,       # your most productive settlement to upgrade
    has_resources,          # bool: can the player afford this cost?
    resource_deficit,       # dict: resources still needed for a cost
)
```

---

## Contributing to the engine

See [CONTRIBUTING.md](CONTRIBUTING.md).
