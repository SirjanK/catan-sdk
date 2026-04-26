# Bot Submissions

Quick-start cheat sheet for humans and agents.  For the full guide see [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Quickstart

```bash
# 1. Copy the example stub
cp submissions/example_bot.py submissions/my_bot.py

# 2. Rename the class and implement all 7 methods
#    Reference implementation: catan/players/basic_player.py
#    Advanced reference:       submissions/heuristic_bot.py
#    Planning-style reference: submissions/planner_bot.py

# 3. Run fixture tests (33 edge-case checks)
pytest catan/tests/test_dev_validator.py --player=submissions.my_bot:MyBot -v

# 4. Play a game and watch the replay
python -m catan.run catan/examples/four_basic_players.yaml
# → drag-drop the .jsonl from tmp/games/ onto https://catan.bot/viewer

# 5. Simulate win rates vs BasicPlayer
python -m catan.sim \
  --bot submissions.my_bot:MyBot \
  --bot basic:BasicPlayer \
  --games 200 --workers 4

# 6. Simulate vs HeuristicBot (tougher benchmark)
python -m catan.sim \
  --bot submissions.my_bot:MyBot \
  --bot submissions.heuristic_bot:HeuristicBot \
  --games 200 --workers 4

# 7. Package
python -m catan.submit submissions.my_bot:MyBot   # → MyBot.zip

# 8. Register (API token — preferred for automation)
python -m catan.register \
  --token ctn_<your_token> \
  --zip MyBot.zip \
  --name "My Bot v1"

# 8b. Register (username/password — prompts once, caches JWT for 24h)
python -m catan.register \
  --username your_username \
  --zip MyBot.zip \
  --name "My Bot v1"
```

---

## Agent / Automation Notes

When an agent (e.g., Claude Code or Codex) is running this workflow end-to-end, keep the following in mind:

- **`httpx` is a standard SDK dependency**. If `catan.register` throws an import error, run `uv sync` to realign the environment.
- **Token-based auth is reliable for CI/agents** — use `--token ctn_...` to avoid interactive password prompts.  Generate tokens at `https://catan.bot/settings` → API Tokens.
- **Default server**: `catan.register` uploads to `https://catan.bot` unless you pass `--url` or set `CATAN_SERVER_URL`.
- **Two uploads under different names** use the same zip:

  ```bash
  python -m catan.register --token ctn_... --zip MyBot.zip --name "MyBot A"
  python -m catan.register --token ctn_... --zip MyBot.zip --name "MyBot B"
  ```

- **Manual upload**: `python -m catan.submit` writes `<ClassName>.zip` in the current working directory.  Hand that file to the user to drag into the web UI.
- **Hosted workflow**: after uploading, browse `https://catan.bot` for tournament status, registered bots, and replays.
- **`uv run` vs direct python**: The project uses `uv`; always prefix commands with `uv run` (or `uv run pytest`, `uv run python -m ...`) unless you are inside the activated venv.
- **VIRTUAL_ENV warning**: If you see `VIRTUAL_ENV=venv does not match ... .venv`, it is benign — uv resolves the right environment automatically.
- **Fixture test count**: The test suite now has 33 checks (not 31 as some older docs say).

---

## Player API

Your bot must subclass `catan.player.Player` and implement these methods:

| Method | Phase | Return type |
|--------|-------|-------------|
| `setup_place_settlement(state)` | Setup | `PlaceSettlement` |
| `setup_place_road(state, settlement_vertex_id)` | Setup | `PlaceRoad` |
| `pre_roll_action(state)` | Pre-roll | `RollDice` or `PlayKnight` |
| `discard_cards(state, count)` | Discard (7-roll) | `DiscardCards` |
| `move_robber(state)` | Robber | `MoveRobber` |
| `take_turn(state)` | Post-roll | `Build` / `BankTrade` / `ProposeTrade` / `AcceptTrade` / `RejectAllTrades` / `PlayDevCard` / `Pass` |
| `respond_to_trade(state, proposal)` | Out-of-turn | `RespondToTrade` |

Full docstrings: [`catan/player.py`](../catan/player.py)

### Key GameState fields

```python
state.board                         # Board — hexes, vertices, edges, ports, robber position
state.players[pid].resources        # Dict[ResourceType, int] — your hand only (opponent hand = zeroed)
state.players[pid].dev_cards        # List[DevCardType] — your dev cards only
state.players[pid].resource_count   # int — always public (total cards held)
state.players[pid].public_vp        # int — visible VP (does NOT include VP dev cards)
state.players[pid].settlements_remaining  # pieces still in supply
state.players[pid].cities_remaining
state.players[pid].roads_remaining
state.dev_cards_remaining           # cards left in shared deck
state.trades_proposed_this_turn     # toward the per-turn limit of 3
state.pending_trades                # open proposals (List[TradeProposal])
```

---

## Validation

The local harness (`DevValidator`) covers 33 fixture tests — setup, discard, robber, post-roll builds, dev cards, piece limits, ports, trade responses, and state immutability.  Run it before uploading:

```bash
pytest catan/tests/test_dev_validator.py --player=submissions.my_bot:MyBot -v
```

The server re-runs the same checks plus an AST security scan on upload.

---

## Simulation

`python -m catan.sim` runs N games and reports win rates, average VP, and placement histograms.  Useful flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--bot MODULE:CLASS` | required | Add a bot (repeat for multiple; seats filled with duplicates) |
| `--games N` | 100 | Number of games |
| `--workers N` | 1 | Parallel worker processes |
| `--fixed-board` | off | Same board topology for all games |
| `--save-logs` | off | Write per-game JSONL + `index.json` to `--log-dir` |
| `--log-dir PATH` | `tmp/sim/` | Output directory when `--save-logs` is on |
| `--quiet` | off | Suppress progress bar |

With `--save-logs`, drag the output directory onto the **Batch Results** tab on `https://catan.bot/viewer` to browse all games.

### Interpreting results

The sim outputs two rows per bot because it fills empty seats with duplicates.  Focus on the `Win%` and `Avg VP` columns.  A rough benchmark:

| Bot | Typical Win% (4-player) |
|-----|------------------------|
| BasicPlayer | ~17 % |
| PlannerBot | ~33 % |
| HeuristicBot | ~37–41 % |

---

## CLI registration

```bash
# API token (recommended — no prompts, works in CI/agents)
python -m catan.register \
  --token ctn_<your_token> \
  --zip MyBot.zip \
  --name "My Bot v2"

# Username/password (interactive, JWT cached 24 h in ~/.catan/tokens.json)
python -m catan.register \
  --username your_username \
  --zip MyBot.zip \
  --name "My Bot v2"
```

Tokens are generated at `https://catan.bot/settings` → API Tokens.  They do not expire and can be revoked.  `catan.register` defaults to `https://catan.bot`; override it with `--url` or `CATAN_SERVER_URL` when targeting another server. The JWT cache lives at `~/.catan/tokens.json`.

---

## Restrictions

Your submitted files must not import or use:
`os`, `subprocess`, `socket`, `urllib`, `requests`, `sys`, `threading`, `multiprocessing`, `shutil`, `open`, `exec`, `eval`, `__import__`

These are detected by an AST scan on the server.  Everything you need is available through the `GameState` object passed to each method.

---

## Reference implementations

| File | Description |
|------|-------------|
| `submissions/example_bot.py` | Minimal stub — copy this and fill in every method |
| `catan/players/basic_player.py` | Simple legal bot (city > settlement > road > dev card); ~17% win rate |
| `submissions/heuristic_bot.py` | **Advanced reference** — dev-card play, strategic trading, smart robber targeting; ~37–41% win rate |
| `submissions/planner_bot.py` | **Planning reference** — commits to one goal and bank-trades toward it; ~33% win rate |

---

## Helpers (`catan.players.helpers`)

Common board-query utilities to import instead of reimplementing:

```python
from catan.players.helpers import (
    vertex_pip_score,       # sum of pip counts at a vertex
    vertex_resource_types,  # set of resource types produced at a vertex
    owned_resource_types,   # resource types a player already produces
    valid_settlement_spots, # vertices where a player can legally build now
    valid_road_edges,       # edges where a player can legally build a road
    best_city_vertex,       # most productive settlement to upgrade to city
    has_resources,          # bool: can the player afford a cost dict?
    resource_deficit,       # dict: resources still needed for a cost
    PIPS,                   # {number: pip_count} lookup table
)
```

Full docstrings: [`catan/players/helpers.py`](../catan/players/helpers.py)

### Validator cost constants

```python
from catan.engine.validator import (
    ROAD_COST,        # {WOOD: 1, BRICK: 1}
    SETTLEMENT_COST,  # {WOOD: 1, BRICK: 1, WHEAT: 1, SHEEP: 1}
    CITY_COST,        # {ORE: 3, WHEAT: 2}
    DEV_CARD_COST,    # {ORE: 1, WHEAT: 1, SHEEP: 1}
    get_port_ratio,   # get_port_ratio(board, player_id, resource) → int (2/3/4)
)
```

---

## Tips

- `state` is a **deep copy** — mutate it freely to simulate future moves without affecting the real game.
- Opponent `resources` and `dev_cards` are **hidden** (zeroed in the state you receive).
- Call `Pass()` to end your turn — you can always pass, even with resources.
- Check `state.players[self.player_id].settlements_remaining` (and `.cities_remaining`, `.roads_remaining`) before attempting to build the corresponding piece.
- Check `state.dev_cards_remaining` before buying a dev card.
- `respond_to_trade` has a **200 ms** timeout — keep it simple and fast.
- `pre_roll_action` is a good place to reset per-turn counters (e.g., bank trade count).
- `take_turn` is called **repeatedly** until you return `Pass()` — each call is one action.
- VP dev cards (`DevCardType.VICTORY_POINT`) should be played immediately; they reveal a hidden VP.
