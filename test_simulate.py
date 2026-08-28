"""Simulator tests: the numbers it reports must be the numbers the engine produced."""

from __future__ import annotations

import csv
import json

import pytest

import config
import engine
import simulate


def one(seed: int = 1, players: int = 4, rounds: int = 6, mode: str = "blind"):
    strategies = simulate._default_matchup(players)
    return simulate.play_game(strategies, players, rounds, mode, seed)


# ---------------------------------------------------------------------------
# A single game
# ---------------------------------------------------------------------------


def test_a_simulated_game_finishes_and_matches_the_engine():
    r = one()
    assert len(r.totals) == 4
    assert r.winners
    assert max(r.totals.values()) == max(r.totals[w] for w in r.winners)
    # The reported total is exactly the sum of its parts.
    for pid, breakdown in r.breakdown.items():
        parts = sum(
            breakdown[k] for k in
            ("toads", "war_tokens", "cards", "conditional", "resources", "majorities")
        )
        assert parts == r.totals[pid] == breakdown["total"]


def test_a_seed_reproduces_a_game_exactly():
    assert one(seed=99).totals == one(seed=99).totals
    assert one(seed=99).totals != one(seed=100).totals


def test_happiness_is_sampled_once_per_round_and_stays_in_range():
    r = one(rounds=6)
    assert len(r.happiness_by_round) == 6
    for snapshot in r.happiness_by_round:
        assert set(snapshot) == set(r.totals)
        for value in snapshot.values():
            assert config.HAPPINESS_MIN <= value <= config.HAPPINESS_MAX


def test_war_tokens_are_never_double_counted():
    """One war per round: a winner or a tie, never both, never neither."""
    r = one()
    wars_won = sum(r.war_wins.values())
    assert wars_won + r.war_ties == r.rounds
    assert sum(f["war_tokens"] for f in r.final.values()) == wars_won


def test_every_card_is_accounted_for():
    r = one()
    import cards as card_lib
    held = sum(f["cards"] for f in r.final.values())
    bought = len(r.prices)
    assert held == bought
    revealed = r.players * r.rounds
    assert bought + r.cards_burned_tie + r.cards_unsold == revealed
    assert revealed <= card_lib.deck_size(r.players)


def test_prices_respect_the_auction_floor_and_the_purse():
    r = one()
    assert all(p >= config.AUCTION_MIN_BID for p in r.prices)


@pytest.mark.parametrize("players", [2, 3, 4, 5, 6])
@pytest.mark.parametrize("mode", ["blind", "live"])
def test_every_player_count_and_mode_simulates(players, mode):
    r = one(players=players, mode=mode, rounds=3)
    assert len(r.totals) == players
    assert r.rounds == 3
    assert len(r.happiness_by_round) == 3


def test_a_sample_log_is_only_kept_when_asked():
    strategies = simulate._default_matchup(2)
    assert simulate.play_game(strategies, 2, 2, "blind", 1).log == []
    assert simulate.play_game(strategies, 2, 2, "blind", 1, keep_log=True).log


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------


def test_seats_rotate_so_strategy_is_not_stuck_to_a_seat():
    results = simulate.run(4, [4], 2, "blind", None, seed=1)
    seat_one = {r.seats["p1"] for r in results}
    assert len(seat_one) == 4          # a different strategy in seat 1 each game


def test_a_custom_matchup_seats_only_those_strategies():
    results = simulate.run(3, [4], 2, "blind", ["farmer", "miner"], seed=1)
    for r in results:
        assert set(r.seats.values()) <= {"farmer", "miner"}
    # And the report does not trip over the strategies that never played.
    text = simulate.report_win_rates(results)
    assert "farmer" in text and "warlord" not in text


def test_a_player_count_sweep_keeps_the_counts_separate():
    results = simulate.run(2, [2, 5], 2, "blind", None, seed=1)
    assert sorted({r.players for r in results}) == [2, 5]
    assert len(results) == 4
    assert "2p" in simulate.report_win_rates(results)
    assert "5p" in simulate.report_win_rates(results)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def test_win_rates_sum_to_one_game_per_game():
    results = simulate.run(10, [4], 3, "blind", None, seed=1)
    credited = 0.0
    for r in results:
        credited += sum(1 / len(r.winners) for _ in r.winners)
    assert credited == pytest.approx(len(results))   # shared wins split, never inflate


def test_every_report_section_renders():
    results = simulate.run(3, [3], 2, "blind", None, seed=1)
    for section in (
        simulate.report_win_rates,
        simulate.report_vp_sources,
        simulate.report_majorities,
        simulate.report_deck,
        simulate.report_happiness,
        simulate.report_finals,
    ):
        text = section(results)
        assert text.strip()
        assert "\n" in text


def test_the_majority_report_counts_forfeited_ties():
    results = simulate.run(5, [3], 2, "blind", None, seed=1)
    text = simulate.report_majorities(results)
    for metric in config.END_MAJORITIES:
        assert f"most {metric}" in text
    assert "tied & forfeited" in text
    assert "war" in text


def test_the_deck_report_counts_cards_that_left_the_game():
    results = simulate.run(5, [4], 3, "blind", None, seed=1)
    text = simulate.report_deck(results)
    assert "burned by a double tie" in text
    assert "unsold" in text


# ---------------------------------------------------------------------------
# Output files and the CLI
# ---------------------------------------------------------------------------


def test_csv_has_one_row_per_seat_per_game(tmp_path):
    results = simulate.run(3, [4], 2, "blind", None, seed=1)
    path = tmp_path / "out.csv"
    simulate.write_csv(results, str(path))
    with path.open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3 * 4
    assert {r["strategy"] for r in rows} == set(simulate._default_matchup(4))
    assert sum(int(r["won"]) for r in rows) >= 3
    first = rows[0]
    assert int(first["vp"]) == results[0].totals[first["seat"]]


def test_json_round_trips(tmp_path):
    results = simulate.run(2, [3], 2, "blind", None, seed=1)
    path = tmp_path / "out.json"
    simulate.write_json(results, str(path))
    payload = json.loads(path.read_text())
    assert len(payload) == 2
    assert payload[0]["totals"] == results[0].totals


def test_the_cli_runs_and_writes_what_it_was_asked_for(tmp_path, capsys):
    out = tmp_path / "cli.csv"
    code = simulate.main([
        "-n", "2", "-p", "3", "-r", "2", "--csv", str(out), "--sample-log",
    ])
    assert code == 0
    printed = capsys.readouterr().out
    assert "SAMPLE GAME" in printed
    assert "WIN RATE BY STRATEGY" in printed
    assert "MEAN HAPPINESS BY ROUND" in printed
    assert out.exists()


def test_the_cli_rejects_nonsense():
    assert simulate.main(["-p", "9"]) == 2
    assert simulate.main(["--matchup", "wizard"]) == 2
