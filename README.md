# catan-sdk

A Python game engine and bot development toolkit for Catan. Build, test, and simulate bots locally, then register them for tournament play on the hosted site.

---

## Installation

**For bot developers** (install directly from GitHub):

```bash
pip install "git+https://github.com/SirjanK/catan-sdk.git"
# or with uv (faster):
uv pip install "git+https://github.com/SirjanK/catan-sdk.git"
```

**For local development of the SDK itself:**

```bash
git clone https://github.com/SirjanK/catan-sdk.git
cd catan-sdk
uv sync --extra dev   # installs all deps from uv.lock (reproducible)
# pip fallback: pip install -e ".[dev]"
```

---

## Quick Start

### 1. Implement your bot

Copy `submissions/example_bot.py` as your starting template:

```python
# submissions/my_bot.py
from catan.player import Player
from catan.models.state import GameState
from catan.models.actions import PlaceSettlement, PlaceRoad, RollDice, Pass

class MyBot(Player):
    def __init__(self, player_id: int, seed: int = 0):
        self.player_id = player_id

    def setup_place_settlement(self, state: GameState) -> PlaceSettlement:
        ...

    # implement all 7 methods
```

### 2. Run the validator tests

```bash
pytest catan/tests/test_dev_validator.py --player=submissions.my_bot:MyBot -v
```

### 3. Play a game against the example bot

```bash
python -m catan.run catan/examples/four_basic_players.yaml
# → writes a replay to tmp/games/<timestamp>.jsonl
```

### 4. Watch the replay

Drag the `.jsonl` file into the hosted viewer at `https://<tournament-site>/viewer`. Step through every action with ← / → arrow keys.

### 5. Simulate many games

```bash
python -m catan.sim \
  --bot submissions.my_bot:MyBot \
  --bot basic:BasicPlayer \
  --games 200 \
  --workers 4 \
  --save-logs
# → writes per-game JSONLs to tmp/sim/<run>/
```

Upload the `tmp/sim/<run>/` folder to the hosted viewer's **Batch Results** tab to browse and step through individual games.

### 6. Package and register for the tournament

```bash
python -m catan.submit submissions.my_bot:MyBot    # → MyBot.zip
python -m catan.register \
  --url https://<tournament-site> \
  --username player1 \
  --zip MyBot.zip
```

---

## The 7 Player Methods

All bots must subclass `catan.player.Player` and implement these methods:

| Method | Phase | Return Type |
|--------|-------|-------------|
| `setup_place_settlement(state)` | Setup | `PlaceSettlement` |
| `setup_place_road(state)` | Setup | `PlaceRoad` |
| `pre_roll_action(state)` | Start of turn | `RollDice` or `PlayKnight` |
| `discard_cards(state)` | After 7 rolled | `DiscardCards` |
| `move_robber(state)` | After knight/7 | `MoveRobber` |
| `take_turn(state)` | Main turn | Any valid action (or `Pass`) |
| `respond_to_trade(state, offer)` | Any player's turn | `AcceptTrade` or `RejectTrade` |

---

## What's in the SDK

```
catan-sdk/
  catan/
    player.py           ← Player ABC (implement this)
    models/             ← Pydantic v2 models: enums, actions, GameState, board
    engine/
      engine.py         ← CatanEngine: runs a full game
      executor.py       ← Pure state mutation functions
      validator.py      ← Pure action validation + cost constants
      logger.py         ← GameLogger: writes JSONL replay files
      dev_validator.py  ← 31 fixture tests for validating your bot
    board/              ← Board generation and topology
    players/
      basic_player.py   ← Reference bot implementation
      registry.py       ← Local bot registry for YAML-driven games
    config.py           ← GameConfig, PlayerConfig (YAML-to-Pydantic)
    run.py              ← `python -m catan.run` CLI
    sim.py              ← `python -m catan.sim` batch simulation CLI
    submit.py           ← `python -m catan.submit` bot packager CLI
    register.py         ← `python -m catan.register` tournament registration CLI
    tests/              ← Engine tests (run these to check your bot)
    examples/
      four_basic_players.yaml
  submissions/
    README.md           ← Read this first
    example_bot.py      ← Copy this as your template
```

---

## CLI Reference

### `python -m catan.run <config.yaml>`

Run a single game from a YAML config. Writes a `.jsonl` replay to `tmp/games/`.

### `python -m catan.sim`

```
Required:
  --bot MODULE:CLASS      Bot to include (repeat for multiple bots)

Optional:
  --games N               Number of games (default: 100)
  --seed N                Starting game seed (default: 0)
  --workers N             Parallel worker processes (default: 1)
  --fixed-board           Randomize board once, reuse across all games
  --save-logs             Write per-game JSONL to --log-dir
  --log-dir PATH          Where to save logs (default: tmp/sim/)
  --output FILE           Write JSON summary to file
  --quiet                 Suppress progress bar
```

### `python -m catan.submit MODULE:CLASS`

Validates your bot and packages it as a `.zip` for upload.

### `python -m catan.register`

```
Required:
  --url URL               Tournament site URL
  --username USERNAME     Your tournament account username
  --zip FILE              Bot zip file from catan.submit

Optional:
  --name "Bot Name"       Display name (defaults to zip stem)
```

Caches your JWT so you don't need to re-enter your password on each run.

---

## Hex Coordinate System

The board uses **pointy-top axial coordinates**. Corner indices are clockwise from the top: 0=N, 1=NE, 2=SE, 3=S, 4=SW, 5=NW.

---

## License

See [LICENSE](LICENSE).
