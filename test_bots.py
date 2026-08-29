"""Bot tests. Bots must play legally, from public information only."""

from __future__ import annotations

import inspect
import random

import pytest

import bots
import config
import engine
from test_engine import commit_all, make_game, place, to_auction


ALL_STRATEGIES = sorted(bots.STRATEGIES)


def view_for(state: engine.GameState, pid: str) -> dict:
    return engine.player_view(state, pid)


# ---------------------------------------------------------------------------
# The information barrier
# ---------------------------------------------------------------------------


def test_a_strategy_only_ever_receives_a_view():
    """Enforced by signature: no strategy method takes a GameState."""
    for cls in bots.STRATEGIES.values():
        for name, method in inspect.getmembers(cls, inspect.isfunction):
            params = inspect.signature(method).parameters
            assert "state" not in params, f"{cls.__name__}.{name} takes state"


def test_a_bot_cannot_see_an_opponents_commitment():
    state = make_game(2)
    set_up = engine.submit_action(state, "p1", {"type": "recruit", "count": 3})
    view = view_for(set_up, "p2")
    assert view["your_commitment"] is None
    # The bot decides from this view; there is simply nothing in it to leak.
    action = bots.decide(view, "farmer")
    assert action["type"] == "recruit"


def test_take_turn_hands_the_strategy_a_view_not_the_state(monkeypatch):
    state = make_game(2)
    seen = {}

    class Spy(bots.Balanced):
        def act(self, view):
            seen["arg"] = view
            return {"type": "recruit", "count": 0}

    monkeypatch.setitem(bots.STRATEGIES, "spy", Spy)
    bots.take_turn(state, "p1", "spy")
    assert isinstance(seen["arg"], dict)
    assert seen["arg"]["you"] == "p1"
    assert "commitments" not in seen["arg"]


# ---------------------------------------------------------------------------
# Legality
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", ALL_STRATEGIES)
@pytest.mark.parametrize("mode", [config.AUCTION_MODE_BLIND, config.AUCTION_MODE_LIVE])
def test_a_table_of_one_strategy_plays_a_legal_game(strategy, mode):
    seats = {f"p{i}": strategy for i in range(1, 5)}
    state = make_game(4, seed=hash((strategy, mode)) % 1000, auction_mode=mode)
    rng = random.Random(1)
    steps = 0
    while not state.finished:
        steps += 1
        assert steps < 5000
        pid = engine.pending_players(state)[0]
        view = view_for(state, pid)
        action = bots.decide(view, seats[pid], rng)
        # Validate directly: the fallback in take_turn must never be needed.
        engine.validate_action(state, pid, action)
        state = engine.submit_action(state, pid, action)
    assert state.scores is not None


@pytest.mark.parametrize("players", [2, 3, 4, 5, 6])
def test_mixed_tables_finish_at_every_player_count(players):
    order = ALL_STRATEGIES * 2
    seats = {f"p{i}": order[i - 1] for i in range(1, players + 1)}
    state = bots.play_out(make_game(players, seed=players), seats, random.Random(players))
    assert state.finished
    assert sum(len(p.war_tokens) for p in state.players) <= config.ROUNDS
    for p in state.players:
        assert p.flies >= 0 and p.gold >= 0 and p.toads >= 0
        assert config.HAPPINESS_MIN <= p.happiness <= config.HAPPINESS_MAX


def test_play_out_stops_when_a_human_seat_is_pending():
    state = make_game(3)
    state = bots.play_out(state, {"p1": "farmer", "p2": "miner"}, random.Random(0))
    assert engine.pending_players(state) == ["p3"]
    assert state.phase == engine.PHASE_RECRUIT


def test_a_broken_strategy_cannot_wedge_a_table(monkeypatch):
    class Saboteur(bots.Bot):
        def act(self, view):
            return {"type": "recruit", "count": 999}

    monkeypatch.setitem(bots.STRATEGIES, "saboteur", Saboteur)
    state = make_game(2)
    state = bots.take_turn(state, "p1", "saboteur")
    assert state.commitments["p1"] == {"type": "recruit", "count": 0}


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError):
        bots.make("hedgehog", "p1")


# ---------------------------------------------------------------------------
# Character — each strategy should actually behave like its name
# ---------------------------------------------------------------------------


def _placement_for(strategy: str, toads: int = 8, **player_overrides) -> dict:
    state = make_game(3)
    state.phase = engine.PHASE_PLACEMENT
    state.commitments = {}
    state.auction = None
    for p in state.players:
        p.toads = toads
    for key, value in player_overrides.items():
        setattr(state.player("p1"), key, value)
    return bots.make(strategy, "p1", random.Random(0)).place(view_for(state, "p1"))


def test_farmer_favours_fields_and_miner_favours_mine():
    farmer = _placement_for("farmer")
    miner = _placement_for("miner")
    assert farmer[config.FIELDS] == max(farmer.values())
    assert miner[config.MINE] == max(miner.values())
    assert farmer[config.FIELDS] > miner[config.FIELDS]
    assert miner[config.MINE] > farmer[config.MINE]


def test_warlord_contests_the_war_every_round():
    assert _placement_for("warlord")[config.MILITARY] >= 1


def test_warlord_matches_exactly_to_deny_when_it_cannot_win():
    """The denial play: tie the war so nobody takes the token or the penalty."""
    state = make_game(2)
    state.phase = engine.PHASE_PLACEMENT
    state.commitments = {}
    state.auction = None
    state.player("p1").toads = 5      # cannot field 5 in Military and still work
    state.player("p2").toads = 9
    state.player("p2").last_placement = {config.MILITARY: 4, config.FIELDS: 5}
    placement = bots.make("warlord", "p1", random.Random(0)).place(view_for(state, "p1"))
    assert placement[config.MILITARY] == 4       # match, do not exceed
    assert sum(placement.values()) == 5


def test_warlord_counts_its_own_strength_cards():
    state = make_game(2)
    state.phase = engine.PHASE_PLACEMENT
    state.commitments = {}
    state.auction = None
    state.player("p1").toads = 6
    state.player("p1").cards = ["war_college"]   # +2 strength
    state.player("p2").toads = 6
    state.player("p2").last_placement = {config.MILITARY: 3, config.FIELDS: 3}
    placement = bots.make("warlord", "p1", random.Random(0)).place(view_for(state, "p1"))
    assert placement[config.MILITARY] == 2       # 2 toads + 2 cards beats 3


def test_bots_rest_when_happiness_gets_expensive():
    unhappy = _placement_for("farmer", toads=8, happiness=4)
    content = _placement_for("farmer", toads=8, happiness=15)
    assert unhappy[config.REST] > content[config.REST]


def test_bots_top_up_an_area_to_switch_on_an_owned_engine_card():
    state = make_game(2)
    state.phase = engine.PHASE_PLACEMENT
    state.commitments = {}
    state.auction = None
    state.player("p1").toads = 5
    state.player("p1").cards = ["deep_vein"]     # needs 3 in Mine
    placement = bots.make("farmer", "p1", random.Random(0)).place(view_for(state, "p1"))
    assert placement[config.MINE] >= 3
    assert sum(placement.values()) == 5


def test_miner_outbids_a_farmer_on_a_gold_engine():
    state = to_auction(make_game(2), ["deep_vein", "monument"])
    miner_bid = bots.decide(view_for(state, "p1"), "miner", random.Random(0))
    farmer_bid = bots.decide(view_for(state, "p2"), "farmer", random.Random(0))
    assert miner_bid["amount"] > farmer_bid["amount"]


def test_bots_never_bid_without_the_eligibility_minimum():
    state = to_auction(make_game(3), ["grand_monument", "monument", "monument"])
    state.player("p1").gold = 2
    engine._prepare_card(state)
    # An ineligible seat is never even asked...
    assert "p1" not in engine.pending_players(state)
    # ...and on the eligibility floor exactly, a bot bids within its purse.
    state.player("p1").gold = config.AUCTION_ELIGIBILITY
    engine._prepare_card(state)
    for strategy in ALL_STRATEGIES:
        action = bots.decide(view_for(state, "p1"), strategy, random.Random(0))
        assert action["amount"] in (0, config.AUCTION_ELIGIBILITY)


def test_bots_mine_ahead_of_next_rounds_slate():
    """The slate is face-up a round early, so gold can be dug in time for it."""
    state = make_game(2)
    state.phase = engine.PHASE_PLACEMENT
    state.commitments = {}
    state.auction = None
    for p in state.players:
        p.toads = 6
        p.gold = 0
    without = bots.make("balanced", "p1", random.Random(0)).place(view_for(state, "p1"))

    state.upcoming = ["grand_monument", "monument"]
    with_preview = bots.make("balanced", "p1", random.Random(0)).place(view_for(state, "p1"))

    assert with_preview[config.MINE] > without[config.MINE]
    assert sum(with_preview.values()) == 6


def test_a_bot_does_not_over_mine_for_a_card_it_can_already_afford():
    state = make_game(2)
    state.phase = engine.PHASE_PLACEMENT
    state.commitments = {}
    state.auction = None
    for p in state.players:
        p.toads = 6
    state.player("p1").gold = 40          # can buy anything on the slate already
    state.upcoming = ["grand_monument", "monument"]
    rich = bots.make("balanced", "p1", random.Random(0)).place(view_for(state, "p1"))

    state.player("p1").gold = 0
    poor = bots.make("balanced", "p1", random.Random(0)).place(view_for(state, "p1"))
    assert poor[config.MINE] > rich[config.MINE]


def test_bots_save_up_for_a_better_card_later_in_the_slate():
    state = to_auction(make_game(2), ["public_park", "grand_monument"])
    for p in state.players:
        p.gold = 8            # enough for one good card, not both
    engine._prepare_card(state)
    action = bots.decide(view_for(state, "p1"), "balanced", random.Random(0))
    assert action["amount"] == 0    # pass, and keep the purse for the Monument


def test_bots_will_not_starve_toads_before_the_final_round():
    state = make_game(2, rounds=6)
    state.round = 3
    state.phase = engine.PHASE_FEED
    state.commitments = {}
    state.auction = None
    state.player("p1").toads = 5
    state.player("p1").flies = 20
    keep = bots.make("balanced", "p1", random.Random(0)).feed(view_for(state, "p1"))
    assert keep == 5


def test_a_bot_will_starve_a_toad_in_the_final_round_to_take_the_fly_majority():
    state = make_game(2, rounds=6)
    state.round = 6
    state.phase = engine.PHASE_FEED
    state.commitments = {}
    state.auction = None
    state.player("p1").toads = 4
    state.player("p1").flies = 9
    state.player("p2").toads = 0
    state.player("p2").flies = 6    # p1 must end above 6 flies to take the 5 VP
    keep = bots.make("balanced", "p1", random.Random(0)).feed(view_for(state, "p1"))
    assert keep == 2                # 9 - 2 = 7 flies beats 6; 2 toads sacrificed


# ---------------------------------------------------------------------------
# First player marker
# ---------------------------------------------------------------------------


def test_the_first_player_marker_rotates_each_round():
    state = make_game(3, rounds=5)
    assert state.first_player == 0
    state = bots.play_out(
        state, {p.id: "balanced" for p in state.players}, random.Random(2)
    )
    holders = [e["first_player"] for e in state.log if e["type"] == "round_start"]
    assert holders == ["p2", "p3", "p1", "p2"]   # rounds 2-5, wrapping round


def test_the_marker_does_not_change_a_simultaneous_phase():
    """Recruitment, placement and feeding have no order for it to affect."""
    early = make_game(3, seed=8)
    late = make_game(3, seed=8)
    late.first_player = 2
    actions = {
        "p1": {"type": "recruit", "count": 1},
        "p2": {"type": "recruit", "count": 3},
        "p3": {"type": "recruit", "count": 2},
    }
    early = commit_all(early, actions)
    late = commit_all(late, actions)
    assert [p.toads for p in early.players] == [p.toads for p in late.players]
    assert [p.flies for p in early.players] == [p.flies for p in late.players]


def test_live_bidding_opens_with_the_first_player_marker():
    state = make_game(3, auction_mode=config.AUCTION_MODE_LIVE)
    state.first_player = 2
    state = to_auction(state, ["monument", "monument", "monument"])
    assert engine.pending_players(state) == ["p3"]
    assert engine.player_view(state, "p1")["seat_order"] == ["p3", "p1", "p2"]
    state = engine.submit_action(state, "p3", {"type": "bid", "amount": 3})
    assert engine.pending_players(state) == ["p1"]   # rotates on from the marker


def test_the_marker_skips_seats_that_cannot_afford_to_open():
    state = make_game(3, auction_mode=config.AUCTION_MODE_LIVE)
    state = to_auction(state, ["monument", "monument", "monument"])
    state.player("p1").gold = 1
    engine._prepare_card(state)
    assert engine.pending_players(state) == ["p2"]
