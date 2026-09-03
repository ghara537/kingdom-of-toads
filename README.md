# Kingdom of Toads — playable prototype

A browser implementation of the board game specified in `DESIGN.md`, built for
playtesting: play solo against bots, or with other people over the internet.

`DESIGN.md` is the source of truth for the rules. Every balance number lives in
`config.py`.

## Run it locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn server:app --reload --port 8000
```

Open <http://localhost:8000>, set the other seats to bots, and start.

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Deploy to Render

1. Push this repo to GitHub.
2. In Render: **New → Blueprint**, point it at the repo. It reads `render.yaml`.
3. Wait for the build, then open the service URL.

The exact start command, already set in `render.yaml`:

```
uvicorn server:app --host 0.0.0.0 --port $PORT --workers 1
```

**One worker, always.** Tables live in the server's memory. A second worker
process would hold its own separate copy of every game, and players would land
on whichever copy the load balancer picked.

**Free plan caveat.** A free instance spins down after ~15 minutes of
inactivity and comes back with a fresh, empty filesystem, so saved games do not
survive a spin-down or a redeploy. If you want games in progress to survive,
move to the Starter plan, uncomment the `disk:` block in `render.yaml`, and set
`KOT_DATA_DIR` to `/var/data`.

### Keeping the server awake

The header shows `awake · next ping 9:12` and a **Keep awake** button. While a
tab is open, the page calls `GET /api/keepalive` every 10 minutes; the request
arriving is the entire mechanism, since any inbound traffic resets Render's
idle timer. The button forces a ping immediately.

Auto-pinging stops after 30 minutes with no mouse or keyboard activity, so a
tab left open overnight will not hold the instance up by itself — that matters
because a free Render account only gets 750 instance-hours a month, and one
service held awake around the clock uses about 730 of them.

**This cannot help when nobody has the page open.** Nothing in the browser can.
If the table empties for 15 minutes, the instance sleeps. Tunables live in
`config.py`: `KEEPALIVE_INTERVAL_SECONDS`, `KEEPALIVE_IDLE_LIMIT_SECONDS`.

## Playing with other people

Create a table, set some seats to **Human (join by link)**, and send the
`/t/CODE` URL. Everything below is per-table and needs no configuration.

**Rejoining.** Each seat gets a token stored in `localStorage`, so returning to
the URL puts you back in your own seat with whatever you had already committed
this phase. A seat is reserved for its player: nobody else can take it, whether
or not they are connected. Each seat shows a connection dot so the table can
see who has actually dropped.

**Phase timers put it to a vote — nobody is replaced automatically.** Every
simultaneous phase has a countdown, default 120 seconds, set by the host at
table creation and shown in the header. When it runs out, the table is *asked*
about whoever is holding it up:

- One question per late player, so two people going quiet produce two
  independent decisions rather than one muddled one.
- **Any single yes** replaces that seat with a bot for the rest of the game.
- **Everyone saying no** restarts the clock, in full.
- A vote nobody answers lapses after 120 seconds and the clock restarts, so an
  inattentive table never accidentally kicks anyone.
- The player under the vote can cancel it simply by committing their move. The
  vote card is deliberately not a blocking modal for exactly that reason.
- A vote is tied to the phase that opened it. Once the phase resolves, the
  question is dropped even if the same player owes a decision again.
- **A solo game against bots is never voted on** — there is nobody to ask, so
  the table just keeps waiting. Walking away from a solo game costs nothing.

Deadlines are wall-clock values stored on the table, so a restart does not lose
or double-fire a timer, and downtime does not count against anybody.

**Pause.** Any seated player can stop the clock from the header. While paused
no timer runs and nobody can be voted out; pausing also cancels any vote in
flight. It survives a restart.

A kicked seat keeps its token, so if the player comes back the host can hand
the seat straight back with `→ human` and their original link still works.

**Host controls.** The host can flip any seat to permanent bot control (`→ bot`
on the seat) if someone leaves for good, and flip it back — the seat token is
kept, so their link still works if they return.

**Persistence.** Every state transition is written through to
`$KOT_DATA_DIR/CODE.json` (atomically), and unfinished games are reloaded at
startup. Memory stays the read path; disk is only a backup. Finished games keep
their scoreboard at the same URL. Tables idle for 24 hours are dropped from
memory and disk.

Read the Render caveat above before relying on this in production: on the free
plan the filesystem does not survive a spin-down.

## Tuning scoring and bonuses per table

Open **Scoring & bonus values** on the new-table screen. You can set:

- **Starting resources** — flies, gold, toads and happiness. Starting happiness
  is clamped to the 1–20 track, and the recruitment band follows it
  immediately, so starting at 16 means 1 fly a toad from round 1.
- **The auction floor** — minimum bid, the eligibility threshold that puts you
  out of the auction entirely, and the tie-off penalty. Keep the penalty at or
  below the minimum bid: the design leans on the floor to guarantee a tied
  player can always pay it. (If you set it higher anyway, the engine takes what
  they hold rather than pushing a purse negative.)
- **VP per toad**, and the three end-game majorities (most happiness / gold /
  flies) individually — set one to 0 to switch that award off entirely.
- The **bonus curve for each area**, as `(base + step x round) / divisor`,
  rounded up. Fields and Mine default to `round + 1`; Rest to `ceil(round / 2)`.
  Set the Rest divisor to 1 and it escalates as fast as the others; set a step
  to 0 and the bonus stays flat all game.
- The **war token curve**, on the same shape.

A live table under the form shows what those numbers actually produce round by
round, because the curve formula is not something anyone should have to
evaluate in their head.

**These are per table, not global.** They are stored in the game state, so a
finished table keeps the numbers it was played with and two tables can run
different values at the same time. They lock when the game starts, and the
lobby line shows what a table is using. Your last-used values are remembered in
the browser, so the next table starts from them rather than the defaults.

To add a knob, add a row to `config.TUNING_FIELDS`; the form, the API and the
validation all build themselves from it.

Headless, the simulator takes the same overrides:

```bash
.venv/bin/python simulate.py -n 500 --tune vp_per_toad=2 --tune vp_most_gold=10
```

## The rules page

A **Rules** link in the header opens `/rules` in a new tab. From a table it
carries the code (`/rules?code=ABCDE`) and the text is generated from *that
table's* settings — the recruitment band table gains a gold column if gold
recruits, the auction section describes blind or live as appropriate, the
bonus curve is tabulated round by round for the rounds you are actually
playing, and anything you changed from the defaults is listed at the top.

It is built by `rules.py` from `config` and the table's tuning, so there is no
second copy of the rules to drift out of date.

## The simulator

Bot-only games through the same engine, with no web layer involved.

```bash
.venv/bin/python simulate.py                        # 200 games, 4 players
.venv/bin/python simulate.py -n 1000 -p 2,3,4,5,6   # sweep player counts
.venv/bin/python simulate.py -n 500 --mode live
.venv/bin/python simulate.py --matchup farmer,farmer,miner,miner
.venv/bin/python simulate.py -n 500 --csv out.csv   # a row per seat per game
.venv/bin/python simulate.py -n 1 --sample-log      # one game, narrated
```

It reports win rate by strategy and player count, where the VP came from, how
often the end-game majorities are tied and forfeited, in-round majority and war
ties, how many cards leave the deck via tie penalties or going unsold, mean
happiness by round with the recruitment band it lands in, and the mean final
position. Seats rotate between games, so a strategy's win rate is not
confounded with a seat or with the first player marker.

`--csv` gives you the raw rows if you would rather do your own analysis.

## The card spreadsheet

```bash
.venv/bin/python export_cards.py     # writes cards.csv from config.CARD_DEFS
```

One row per card type, with the copy counts, requirements, effects and the
bots' base valuation. Re-run it after a tuning pass to refresh the sheet. The
`notes` column is yours and nothing reads it back.

## Layout

| File | What it is |
| --- | --- |
| `config.py` | Every tunable number: resources, curves, VP, deck, timeouts |
| `cards.py` | The 18 card types and deck composition. No logic |
| `engine.py` | Pure rules engine. No I/O, no web dependencies, deterministic |
| `bots.py` | Four strategies. They read a player view, never game state |
| `tables.py` | Seats, join codes, tokens, phase timers, bot driving |
| `storage.py` | Atomic JSON write-through, one file per table |
| `server.py` | FastAPI: HTTP, WebSockets, per-seat views, timer sweeper |
| `static/` | The UI: plain HTML, CSS and JS, no build step |
| `rules.py` | The rules, written out from a table's own settings |
| `simulate.py` | Headless harness: bot-only games and the balance report |
| `export_cards.py` | Writes `cards.csv` from `config.CARD_DEFS` |
| `test_*.py` | pytest suites for every layer |

### Architecture

**Server-authoritative.** The client sends intents (`recruit 3`, `bid 7`,
`place 2/1/0/2`) and receives only what its seat is entitled to see. Three
phases involve secret commitments — recruitment, blind bidding and placement —
and those never leave the server before the reveal. Hidden commitments live in
`GameState.commitments`; `engine.player_view` builds each player's view from
scratch and copies exactly one entry out of it, their own.

**One engine, two consumers.** `engine.py` is a pure state machine: state plus
actions in, next state out. The web server and (later) the simulator both
import it. It has no `import fastapi` anywhere and never touches disk.

**Bots and humans are interchangeable seats.** A seat is human or bot, decided
at table creation. Bots decide from the same `player_view` a human sees — the
strategy functions do not accept a `GameState`, which is asserted by a test.

## Rules rulings

`DESIGN.md` is complete but silent on a few points that code cannot dodge.
These are recorded in `engine.RULINGS` and each is a named constant in
`config.py`, so they can be flipped:

| | Ruling | Constant |
| --- | --- | --- |
| 8 | Barracks/War College strength needs ≥1 toad in Military | `WAR_STRENGTH_CARD_MIN_TOADS` |
| 10 | A majority needs a unique holder of ≥1 toad | `MAJORITY_MIN_TOADS` |
| 12 | A card nobody bids on is removed from the game | `AUCTION_BURN_UNSOLD` |
| 14 | Live-mode raises are at least 1 gold | `AUCTION_LIVE_MIN_RAISE` |

Duplicate engine cards stack; conditional scorers round down; happiness is
clamped once at the end of Phase 3; a dead-even game is a shared win.

The **first player marker** rotates one seat per round. It sets the bidding
order in a live auction. Every other phase is simultaneous, so there it is a
display token only.
