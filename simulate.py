"""Kingdom of Toads — headless simulation harness.

Plays bot-only games through the same engine the web app uses and reports on
what happened. Nothing here knows about HTTP; nothing in the engine knows about
this.

    python simulate.py                          # 200 games, 4 players
    python simulate.py -n 1000 -p 2,3,4,5,6     # sweep player counts
    python simulate.py -n 500 --mode live
    python simulate.py -n 500 --rounds 8 --csv out.csv
    python simulate.py --matchup farmer,farmer,miner,miner
    python simulate.py -n 1 --sample-log        # one game, narrated

Bots are rotated through seats between games, so a strategy's win rate is not
confounded with a seat position or with the first player marker.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import bots
import cards as card_lib
import config
import engine


# ---------------------------------------------------------------------------
# One game
# ---------------------------------------------------------------------------


@dataclass
class GameResult:
    seed: int
    players: int
    rounds: int
    mode: str
    seats: dict[str, str]                       # player_id -> strategy
    totals: dict[str, int] = field(default_factory=dict)
    winners: list[str] = field(default_factory=list)
    breakdown: dict[str, dict] = field(default_factory=dict)
    end_majorities: dict[str, str | None] = field(default_factory=dict)
    happiness_by_round: list[dict[str, int]] = field(default_factory=list)
    final: dict[str, dict[str, int]] = field(default_factory=dict)
    war_wins: Counter = field(default_factory=Counter)
    war_ties: int = 0
    majority_ties: Counter = field(default_factory=Counter)
    cards_burned_tie: int = 0
    cards_unsold: int = 0
    prices: list[int] = field(default_factory=list)
    cards_won: Counter = field(default_factory=Counter)
    starved: int = 0
    log: list[dict] = field(default_factory=list)


def play_game(
    strategies: list[str],
    players: int,
    rounds: int,
    mode: str,
    seed: int,
    keep_log: bool = False,
) -> GameResult:
    """Play one bot-only game and pull the numbers out of the finished state."""
    seats = {f"p{i + 1}": strategies[i] for i in range(players)}
    state = engine.new_game(
        [(pid, f"{seats[pid]}-{pid}") for pid in seats],
        engine.Settings(rounds=rounds, auction_mode=mode),
        seed=seed,
    )
    rng = random.Random(seed)
    result = GameResult(
        seed=seed, players=players, rounds=rounds, mode=mode, seats=dict(seats)
    )

    round_now = state.round
    guard = 0
    while not state.finished:
        guard += 1
        if guard > 20_000:  # pragma: no cover - the engine is a state machine
            raise RuntimeError("simulation failed to terminate")
        pid = engine.pending_players(state)[0]
        state = bots.take_turn(state, pid, seats[pid], rng)
        if state.round != round_now or state.finished:
            # Sample after feeding, which is where a round actually ends.
            result.happiness_by_round.append(
                {p.id: p.happiness for p in state.players}
            )
            round_now = state.round

    scores = state.scores
    result.totals = scores["totals"]
    result.winners = scores["winners"]
    result.breakdown = scores["breakdown"]
    result.end_majorities = scores["end_majorities"]
    result.final = {
        p.id: {
            "flies": p.flies,
            "gold": p.gold,
            "toads": p.toads,
            "happiness": p.happiness,
            "cards": len(p.cards),
            "war_tokens": len(p.war_tokens),
        }
        for p in state.players
    }

    for entry in state.log:
        kind = entry["type"]
        if kind == "war":
            result.war_wins[entry["player"]] += 1
        elif kind == "war_tie":
            result.war_ties += 1
        elif kind == "majority_tie":
            result.majority_ties[entry["area"]] += 1
        elif kind == "tie_burn":
            result.cards_burned_tie += 1
        elif kind == "no_bids":
            result.cards_unsold += 1
        elif kind == "card_won":
            result.prices.append(entry["price"])
            result.cards_won[entry["player"]] += 1
        elif kind == "starve":
            result.starved += entry["count"]

    if keep_log:
        result.log = list(state.log)
    return result


# ---------------------------------------------------------------------------
# Many games
# ---------------------------------------------------------------------------


def run(
    games: int,
    player_counts: list[int],
    rounds: int,
    mode: str,
    matchup: list[str] | None,
    seed: int,
    keep_log: bool = False,
) -> list[GameResult]:
    results = []
    for players in player_counts:
        pool = matchup or _default_matchup(players)
        for game in range(games):
            # Rotate the seating so strategy is not confounded with seat.
            order = [pool[(i + game) % len(pool)] for i in range(players)]
            results.append(
                play_game(
                    order, players, rounds, mode, seed + game,
                    keep_log=keep_log and game == 0,
                )
            )
    return results


def _default_matchup(players: int) -> list[str]:
    names = sorted(bots.STRATEGIES)
    return [names[i % len(names)] for i in range(players)]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    widths = [
        max(len(str(headers[i])), *(len(str(r[i])) for r in rows)) if rows
        else len(str(headers[i]))
        for i in range(len(headers))
    ]
    out = ["  " + "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))]
    out.append("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        out.append(
            "  " + "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row))
        )
    return "\n".join(out)


def _pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "—"


def report_win_rates(results: list[GameResult]) -> str:
    """Win rate by strategy, split by player count.

    A shared win counts as a fraction, so the rates in a column sum to 1.
    """
    played: Counter = Counter()
    won: defaultdict = defaultdict(float)
    vp: defaultdict = defaultdict(list)
    counts = sorted({r.players for r in results})

    for r in results:
        for pid, strategy in r.seats.items():
            played[(strategy, r.players)] += 1
            vp[(strategy, r.players)].append(r.totals[pid])
            if pid in r.winners:
                won[(strategy, r.players)] += 1 / len(r.winners)

    rows = []
    # Only strategies that actually took a seat — a custom matchup may leave
    # some of them out entirely.
    for strategy in sorted({s for r in results for s in r.seats.values()}):
        row = [strategy]
        for players in counts:
            n = played[(strategy, players)]
            if not n:
                row.append("—")
                continue
            mean = statistics.mean(vp[(strategy, players)])
            row.append(f"{_pct(won[(strategy, players)], n)} ({mean:.0f} VP)")
        every = sum((vp[(strategy, p)] for p in counts), [])
        row.append(f"{statistics.mean(every):.1f}")
        rows.append(row)

    headers = ["strategy"] + [f"{p}p" for p in counts] + ["mean VP"]
    return "WIN RATE BY STRATEGY AND PLAYER COUNT\n" + _table(headers, rows)


def report_vp_sources(results: list[GameResult]) -> str:
    """Where the points actually came from."""
    sources = ["toads", "war_tokens", "cards", "conditional", "majorities"]
    by_strategy: defaultdict = defaultdict(lambda: defaultdict(list))
    overall: defaultdict = defaultdict(list)

    for r in results:
        for pid, strategy in r.seats.items():
            b = r.breakdown[pid]
            for source in sources:
                by_strategy[strategy][source].append(b[source])
                overall[source].append(b[source])

    total = sum(statistics.mean(overall[s]) for s in sources) or 1
    rows = []
    for strategy in sorted(by_strategy):
        rows.append(
            [strategy] + [f"{statistics.mean(by_strategy[strategy][s]):.1f}" for s in sources]
        )
    rows.append(["ALL"] + [f"{statistics.mean(overall[s]):.1f}" for s in sources])
    rows.append(["share"] + [_pct(statistics.mean(overall[s]), total) for s in sources])

    headers = ["strategy", "toads", "war", "cards", "conditional", "majorities"]
    return "VP SOURCES (mean per player per game)\n" + _table(headers, rows)


def report_majorities(results: list[GameResult]) -> str:
    """How often the end-game majorities go unawarded because of a tie."""
    rows = []
    for metric in config.END_MAJORITIES:
        tied = sum(1 for r in results if r.end_majorities.get(metric) is None)
        rows.append([
            f"most {metric}",
            f"{config.END_MAJORITIES[metric]} VP",
            _pct(len(results) - tied, len(results)),
            _pct(tied, len(results)),
        ])
    out = ["END-GAME MAJORITIES (ties award nothing)",
           _table(["award", "worth", "awarded", "tied & forfeited"], rows)]

    in_round = Counter()
    for r in results:
        in_round.update(r.majority_ties)
    rows = [
        [area, f"{in_round[area] / len(results):.2f}"]
        for area in config.MAJORITY_AREAS
    ]
    war_ties = sum(r.war_ties for r in results) / len(results)
    rows.append(["war", f"{war_ties:.2f}"])
    out.append("")
    out.append("IN-ROUND TIES (per game, out of "
               f"{results[0].rounds} rounds)")
    out.append(_table(["area", "tied rounds"], rows))
    return "\n".join(out)


def report_deck(results: list[GameResult]) -> str:
    """Cards that never reach a player."""
    burned = sum(r.cards_burned_tie for r in results) / len(results)
    unsold = sum(r.cards_unsold for r in results) / len(results)
    prices = [p for r in results for p in r.prices]
    bought = len(prices) / len(results)
    deck = card_lib.deck_size(results[0].players)
    revealed = min(deck, results[0].players * results[0].rounds)
    rows = [
        ["cards revealed", f"{revealed} of {deck}"],
        ["bought", f"{bought:.1f}"],
        ["burned by a double tie", f"{burned:.2f}"],
        ["unsold (nobody could or would bid)", f"{unsold:.2f}"],
        ["mean winning bid", f"{statistics.mean(prices):.1f} gold" if prices else "—"],
        ["highest bid seen", f"{max(prices)} gold" if prices else "—"],
    ]
    return "DECK ATTRITION AND PRICES (per game)\n" + _table(["", "value"], rows)


def report_happiness(results: list[GameResult]) -> str:
    """Mean happiness at the end of each round, and the recruitment band."""
    rounds = results[0].rounds
    per_round: list[list[int]] = [[] for _ in range(rounds)]
    for r in results:
        for i, snapshot in enumerate(r.happiness_by_round[:rounds]):
            per_round[i].extend(snapshot.values())

    rows = []
    for i, values in enumerate(per_round):
        if not values:
            continue
        mean = statistics.mean(values)
        band = config.recruit_band(max(1, min(20, round(mean))))
        rows.append([
            f"R{i + 1}",
            f"{mean:.1f}",
            f"{min(values)}–{max(values)}",
            f"{band[2]} flies/toad",
        ])
    starved = sum(r.starved for r in results) / len(results)
    out = ["MEAN HAPPINESS BY ROUND (after feeding)",
           _table(["round", "mean", "range", "band at the mean"], rows),
           "",
           f"  toads starved: {starved:.2f} per game"]
    return "\n".join(out)


def report_finals(results: list[GameResult]) -> str:
    keys = ["toads", "gold", "flies", "happiness", "cards", "war_tokens"]
    values: defaultdict = defaultdict(list)
    for r in results:
        for stats in r.final.values():
            for key in keys:
                values[key].append(stats[key])
    rows = [[key, f"{statistics.mean(values[key]):.1f}", max(values[key])] for key in keys]
    return "FINAL POSITION (mean per player)\n" + _table(["", "mean", "max"], rows)


def full_report(results: list[GameResult], args: argparse.Namespace) -> str:
    counts = sorted({r.players for r in results})
    header = (
        f"Kingdom of Toads — {len(results)} games, "
        f"{'/'.join(str(c) for c in counts)} players, "
        f"{args.mode} auction, {args.rounds} rounds"
    )
    parts = [header, "=" * len(header), ""]
    for section in (
        report_win_rates(results),
        report_vp_sources(results),
        report_majorities(results),
        report_deck(results),
        report_happiness(results),
        report_finals(results),
    ):
        parts.append(section)
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Output files
# ---------------------------------------------------------------------------


def write_csv(results: list[GameResult], path: str) -> None:
    """One row per seat per game — the raw material for your own analysis."""
    columns = [
        "seed", "players", "rounds", "mode", "seat", "strategy", "won", "vp",
        "vp_toads", "vp_war", "vp_cards", "vp_conditional", "vp_majorities",
        "toads", "gold", "flies", "happiness", "cards", "war_tokens",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for r in results:
            for pid, strategy in r.seats.items():
                b = r.breakdown[pid]
                f = r.final[pid]
                writer.writerow([
                    r.seed, r.players, r.rounds, r.mode, pid, strategy,
                    int(pid in r.winners), r.totals[pid],
                    b["toads"], b["war_tokens"], b["cards"],
                    b["conditional"], b["majorities"],
                    f["toads"], f["gold"], f["flies"], f["happiness"],
                    f["cards"], f["war_tokens"],
                ])


def write_json(results: list[GameResult], path: str) -> None:
    payload = [
        {
            "seed": r.seed, "players": r.players, "rounds": r.rounds,
            "mode": r.mode, "seats": r.seats, "totals": r.totals,
            "winners": r.winners, "breakdown": r.breakdown,
            "end_majorities": r.end_majorities,
            "happiness_by_round": r.happiness_by_round,
            "final": r.final, "war_ties": r.war_ties,
            "majority_ties": dict(r.majority_ties),
            "cards_burned_tie": r.cards_burned_tie,
            "cards_unsold": r.cards_unsold, "prices": r.prices,
        }
        for r in results
    ]
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Play Kingdom of Toads headlessly and report on it.",
    )
    parser.add_argument("-n", "--games", type=int, default=200,
                        help="games per player count (default 200)")
    parser.add_argument("-p", "--players", default="4",
                        help="player count, or a comma-separated sweep (2,3,4)")
    parser.add_argument("-r", "--rounds", type=int, default=config.ROUNDS)
    parser.add_argument("--mode", default=config.AUCTION_MODE_DEFAULT,
                        choices=[config.AUCTION_MODE_BLIND, config.AUCTION_MODE_LIVE])
    parser.add_argument("--matchup",
                        help="comma-separated strategies to seat, e.g. farmer,miner")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--csv", help="write one row per seat per game")
    parser.add_argument("--json", dest="json_path", help="write the full results")
    parser.add_argument("--sample-log", action="store_true",
                        help="print the event log of the first game")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    counts = [int(p) for p in str(args.players).split(",")]
    for players in counts:
        if not config.MIN_PLAYERS <= players <= config.MAX_PLAYERS:
            print(f"player count {players} is out of range", file=sys.stderr)
            return 2

    matchup = None
    if args.matchup:
        matchup = [s.strip() for s in args.matchup.split(",")]
        unknown = [s for s in matchup if s not in bots.STRATEGIES]
        if unknown:
            print(f"unknown strategies: {', '.join(unknown)}", file=sys.stderr)
            return 2

    results = run(
        games=args.games,
        player_counts=counts,
        rounds=args.rounds,
        mode=args.mode,
        matchup=matchup,
        seed=args.seed,
        keep_log=args.sample_log,
    )

    if args.sample_log:
        print(f"SAMPLE GAME (seed {results[0].seed})")
        for entry in results[0].log:
            if entry.get("text"):
                print(f"  R{entry['round']:<2} {entry['type']:<14} {entry['text']}")
        print()

    print(full_report(results, args))

    if args.csv:
        write_csv(results, args.csv)
        print(f"wrote {args.csv}")
    if args.json_path:
        write_json(results, args.json_path)
        print(f"wrote {args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
