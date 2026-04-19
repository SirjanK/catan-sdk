# Bot Submissions

Quick-start cheat sheet. For the full guide see [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Quickstart

```bash
# 1. Copy the example stub
cp submissions/example_bot.py submissions/my_bot.py

# 2. Rename the class and implement all 7 methods
#    Reference implementation: catan/players/basic_player.py

# 3. Run fixture tests (31 edge-case checks)
pytest catan/tests/test_dev_validator.py --player=submissions.my_bot:MyBot -v

# 4. Play a game and watch the replay
python -m catan.run catan/examples/four_basic_players.yaml
# → drag-drop the .jsonl from tmp/games/ onto <tournament-site>/viewer

# 5. Simulate win rates
python -m catan.sim \
  --bot submissions.my_bot:MyBot \
  --bot basic:BasicPlayer \
  --games 100 --workers 4

# 6. Package
python -m catan.submit submissions.my_bot:MyBot   # → MyBot.zip

# 7. Register
python -m catan.register \
  --url https://<tournament-site> \
  --username your_username \
  --zip MyBot.zip
```

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

---

## Validation

The local harness (`DevValidator`) covers 31 fixture tests — setup, discard, robber, post-roll builds, dev cards, piece limits, ports, trade responses, and state immutability. Run it against your bot before uploading:

```bash
pytest catan/tests/test_dev_validator.py --player=submissions.my_bot:MyBot -v
```

The server re-runs the same checks plus an AST security scan on upload.

---

## Simulation

`python -m catan.sim` runs N games and reports win rates, average VP, and placement histograms. Useful flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--bot MODULE:CLASS` | required | Add a bot (repeat for multiple; seats filled with duplicates) |
| `--games N` | 100 | Number of games |
| `--workers N` | 1 | Parallel worker processes |
| `--fixed-board` | off | Same board topology for all games |
| `--save-logs` | off | Write per-game JSONL + `index.json` to `--log-dir` |
| `--log-dir PATH` | `tmp/sim/` | Output directory when `--save-logs` is on |
| `--quiet` | off | Suppress progress bar |

With `--save-logs`, drag the output directory onto the **Batch Results** tab on the tournament site's `/viewer` page to browse all games.

---

## CLI registration

```bash
python -m catan.register \
  --url https://<tournament-site> \
  --username your_username \
  --zip MyBot.zip \
  --name "My Bot v2"    # optional display name (default: zip stem)
```

The CLI caches your session token in `~/.catan/tokens.json` (24 h expiry). You won't be prompted for a password on subsequent uploads.

---

## Restrictions

Your submitted files must not import or use:
`os`, `subprocess`, `socket`, `urllib`, `requests`, `sys`, `threading`, `multiprocessing`, `shutil`, `open`, `exec`, `eval`, `__import__`

These are detected by an AST scan on the server. Everything you need is available through the `GameState` object passed to each method.

---

## Tips

- `state` is a **deep copy** — mutate it freely to simulate future moves without affecting the real game.
- Opponent `resources` and `dev_cards` are **hidden** (zeroed in the state you receive).
- Call `Pass()` to end your turn — you can always pass, even with resources.
- Check `state.players[self.player_id].settlements_remaining` (and `.cities_remaining`, `.roads_remaining`) before attempting to build the corresponding piece.
- Check `state.dev_cards_remaining` before buying a dev card.
- `respond_to_trade` has a **200 ms** timeout — keep it simple and fast.
