"""Rules-engine tests, with emphasis on the ties and edge cases in DESIGN.md."""

from __future__ import annotations

import json
import random

import pytest

import cards as card_lib
import config
import engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_game(n: int = 3, seed: int = 1, **settings) -> engine.GameState:
    seats = [(f"p{i}", f"Player {i}") for i in range(1, n + 1)]
    return engine.new_game(seats, engine.Settings(**settings), seed=seed)


def commit_all(state: engine.GameState, actions: dict[str, dict]) -> engine.GameState:
    """Submit one action per pending seat, in the order given."""
    for pid, action in actions.items():
        state = engine.submit_action(state, pid, action)
    return state


def stack_deck(state: engine.GameState, card_ids: list[str]) -> None:
    """Force the next slate to be exactly ``card_ids``, in that order."""
    filler = ["monument"] * 30
    state.deck = filler + list(reversed(card_ids))


def to_auction(
    state: engine.GameState, slate: list[str], gold: int | None = None
) -> engine.GameState:
    """Skip recruitment and land on the first card of a chosen slate.

    Pass ``gold`` to pin every purse: auction scenarios turn on exactly how
    much money is on the table, and that must not drift when START_GOLD is
    retuned.
    """
    stack_deck(state, slate)
    state = commit_all(
        state, {p.id: {"type": "recruit", "count": 0} for p in state.players}
    )
    if gold is not None:
        for player in state.players:
            player.gold = gold
        engine._prepare_card(state)
    return state


def set_phase(state: engine.GameState, phase: str) -> None:
    state.phase = phase
    state.commitments = {}
    state.auction = None


def place(**areas: int) -> dict:
    return {"type": "place", "placement": dict(areas)}


def happiness(state: engine.GameState) -> dict[str, int]:
    return {p.id: p.happiness for p in state.players}


# ---------------------------------------------------------------------------
# Setup and structure
# ---------------------------------------------------------------------------


def test_starting_setup_matches_design():
    state = make_game(4)
    for p in state.players:
        assert (p.flies, p.gold, p.toads, p.happiness) == (
            config.START_FLIES, config.START_GOLD,
            config.START_TOADS, config.START_HAPPINESS,
        )
    assert state.round == 1
    assert state.phase == engine.PHASE_RECRUIT
    assert len(state.deck) == 51


def test_low_player_count_uses_the_small_deck():
    assert len(make_game(2).deck) == 36
    assert len(make_game(3).deck) == 36
    assert len(make_game(4).deck) == 51


def test_deck_is_deterministic_for_a_seed():
    assert make_game(4, seed=99).deck == make_game(4, seed=99).deck
    assert make_game(4, seed=99).deck != make_game(4, seed=100).deck


def test_player_count_bounds():
    with pytest.raises(ValueError):
        make_game(1)
    with pytest.raises(ValueError):
        make_game(7)


def test_there_is_no_player_order_in_simultaneous_phases():
    """Committing in a different order must not change the outcome."""
    forward = make_game(3, seed=7)
    backward = make_game(3, seed=7)
    actions = {
        "p1": {"type": "recruit", "count": 1},
        "p2": {"type": "recruit", "count": 2},
        "p3": {"type": "recruit", "count": 3},
    }
    forward = commit_all(forward, actions)
    backward = commit_all(backward, dict(reversed(list(actions.items()))))
    assert [p.toads for p in forward.players] == [p.toads for p in backward.players]
    assert [p.flies for p in forward.players] == [p.flies for p in backward.players]


# ---------------------------------------------------------------------------
# Phase 1 — recruitment
# ---------------------------------------------------------------------------


def test_recruitment_costs_the_happiness_band_rate():
    state = make_game(2)
    state.players[0].happiness = 17  # 1 fly per toad
    state.players[1].happiness = 3   # 4 flies per toad
    state = commit_all(
        state,
        {
            "p1": {"type": "recruit", "count": 4},
            "p2": {"type": "recruit", "count": 2},
        },
    )
    assert (state.players[0].toads, state.players[0].flies) == (6, 6)
    assert (state.players[1].toads, state.players[1].flies) == (4, 2)


def test_recruitment_cap_and_affordability_are_enforced():
    state = make_game(2)
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "p1", {"type": "recruit", "count": 5})
    with pytest.raises(engine.InvalidAction):
        # 4 toads at 3 flies each = 12, but they only hold 10.
        engine.submit_action(state, "p1", {"type": "recruit", "count": 4})
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "p1", {"type": "recruit", "count": -1})


def test_recruitment_is_never_blocked_by_low_happiness():
    """The floor at 1 exists so the worst position is expensive, not paralysing."""
    state = make_game(2)
    state.players[0].happiness = 1
    state.players[0].flies = 4
    state = commit_all(
        state,
        {"p1": {"type": "recruit", "count": 1}, "p2": {"type": "recruit", "count": 0}},
    )
    assert state.players[0].toads == 3
    assert state.players[0].flies == 0   # 4 flies a toad in the bottom band


def test_double_commit_is_rejected():
    state = make_game(2)
    state = engine.submit_action(state, "p1", {"type": "recruit", "count": 0})
    with pytest.raises(engine.InvalidAction) as exc:
        engine.submit_action(state, "p1", {"type": "recruit", "count": 1})
    assert "already committed" in str(exc.value)


def test_unknown_seat_and_malformed_payloads_are_rejected():
    state = make_game(2)
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "nobody", {"type": "recruit", "count": 0})
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "p1", {"type": "recruit", "count": "3"})
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "p1", {"type": "place", "placement": {}})
    # A rejected action leaves the state completely untouched.
    assert state.commitments == {}


# ---------------------------------------------------------------------------
# Phase 2 — auction
# ---------------------------------------------------------------------------


def test_highest_blind_bid_wins_and_pays_its_own_bid():
    state = to_auction(make_game(3), ["monument", "granary", "festival"], gold=5)
    state = commit_all(
        state,
        {
            "p1": {"type": "bid", "amount": 5},
            "p2": {"type": "bid", "amount": 3},
            "p3": {"type": "bid", "amount": 0},
        },
    )
    assert state.player("p1").cards == ["monument"]
    assert state.player("p1").gold == 0
    assert state.player("p2").gold == 5
    assert state.auction.results[0]["price"] == 5
    assert state.auction.index == 1


def test_a_player_below_the_eligibility_floor_cannot_bid_at_all():
    state = to_auction(make_game(3), ["monument", "monument", "monument"])
    state.player("p2").gold = 2
    engine._prepare_card(state)  # re-read eligibility after the change
    assert "p2" not in engine.pending_players(state)
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "p2", {"type": "bid", "amount": 2})


def test_a_card_nobody_can_bid_on_leaves_the_game():
    state = to_auction(make_game(2), ["grand_monument", "monument"])
    for p in state.players:
        p.gold = 1
    engine._prepare_card(state)
    state = engine._advance(state)
    assert state.phase == engine.PHASE_PLACEMENT
    assert state.removed == ["grand_monument", "monument"]


def test_an_unbid_card_leaves_the_game():
    state = to_auction(make_game(2), ["monument", "festival"])
    state = commit_all(
        state,
        {"p1": {"type": "bid", "amount": 0}, "p2": {"type": "bid", "amount": 0}},
    )
    assert state.removed == ["monument"]
    assert state.auction.results[0]["status"] == engine.BURNED_UNSOLD


def test_bid_may_not_exceed_gold_held_and_must_clear_the_minimum():
    state = to_auction(make_game(2), ["monument", "monument"], gold=5)
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "p1", {"type": "bid", "amount": 6})
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "p1", {"type": "bid", "amount": 2})
    state = engine.submit_action(state, "p1", {"type": "bid", "amount": 0})  # a pass
    assert state.commitments["p1"] == {"type": "bid", "amount": 0}


def test_tie_goes_to_one_rebid_that_may_be_equal_or_higher():
    state = to_auction(make_game(2), ["grand_monument", "monument"], gold=5)
    state = commit_all(
        state,
        {"p1": {"type": "bid", "amount": 4}, "p2": {"type": "bid", "amount": 4}},
    )
    assert state.auction.stage == engine.STAGE_REBID
    assert state.auction.tied_amount == 4
    assert sorted(state.auction.tied_players) == ["p1", "p2"]

    # Equal to the tied amount is legal; below it is not.
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "p1", {"type": "bid", "amount": 3})
    state = commit_all(
        state,
        {"p1": {"type": "bid", "amount": 4}, "p2": {"type": "bid", "amount": 5}},
    )
    assert state.player("p2").cards == ["grand_monument"]
    assert state.player("p2").gold == 0
    assert state.player("p1").gold == 5


def test_only_tied_players_take_part_in_the_rebid():
    state = to_auction(make_game(3), ["monument", "monument", "monument"])
    state = commit_all(
        state,
        {
            "p1": {"type": "bid", "amount": 4},
            "p2": {"type": "bid", "amount": 4},
            "p3": {"type": "bid", "amount": 3},
        },
    )
    assert sorted(engine.pending_players(state)) == ["p1", "p2"]
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "p3", {"type": "bid", "amount": 9})


def test_a_second_tie_burns_the_card_and_fines_every_tied_player():
    state = to_auction(make_game(3), ["grand_monument", "monument", "monument"], gold=5)
    tie = {
        "p1": {"type": "bid", "amount": 4},
        "p2": {"type": "bid", "amount": 4},
        "p3": {"type": "bid", "amount": 0},
    }
    state = commit_all(state, tie)
    state = commit_all(
        state,
        {"p1": {"type": "bid", "amount": 4}, "p2": {"type": "bid", "amount": 4}},
    )
    assert state.player("p1").gold == 2   # 5 - 3 penalty
    assert state.player("p2").gold == 2
    assert state.player("p3").gold == 5   # untied players pay nothing
    assert state.player("p1").cards == []
    assert "grand_monument" in state.removed
    assert state.auction.results[0]["status"] == engine.BURNED_TIE


def test_the_tie_penalty_is_always_payable():
    """The 3-gold eligibility floor guarantees a tied player can pay the fine."""
    state = to_auction(make_game(2), ["monument", "monument"])
    for p in state.players:
        p.gold = 3
    engine._prepare_card(state)
    state = commit_all(
        state,
        {"p1": {"type": "bid", "amount": 3}, "p2": {"type": "bid", "amount": 3}},
    )
    state = commit_all(
        state,
        {"p1": {"type": "bid", "amount": 3}, "p2": {"type": "bid", "amount": 3}},
    )
    assert state.player("p1").gold == 0
    assert state.player("p2").gold == 0


def test_one_player_may_sweep_the_whole_slate():
    state = to_auction(make_game(2), ["monument", "monument"])
    state.player("p1").gold = 20
    engine._prepare_card(state)
    for _ in range(2):
        state = commit_all(
            state,
            {"p1": {"type": "bid", "amount": 3}, "p2": {"type": "bid", "amount": 0}},
        )
    assert state.player("p1").cards == ["monument", "monument"]
    assert state.player("p1").gold == 14


def test_eligibility_is_rechecked_after_each_card():
    state = to_auction(make_game(2), ["monument", "monument"], gold=5)
    state = commit_all(
        state,
        {"p1": {"type": "bid", "amount": 3}, "p2": {"type": "bid", "amount": 0}},
    )
    assert state.player("p1").gold == 2
    assert engine.pending_players(state) == ["p2"]  # p1 is now priced out


def test_instant_cards_resolve_on_purchase():
    state = to_auction(make_game(2), ["granary", "festival"], gold=5)
    state.player("p1").happiness = 18
    state = commit_all(
        state,
        {"p1": {"type": "bid", "amount": 3}, "p2": {"type": "bid", "amount": 0}},
    )
    assert state.player("p1").flies == 18  # 10 + 8
    # p1 is down to 2 gold and out of the auction, so p2 bids alone.
    assert engine.pending_players(state) == ["p2"]
    state = engine.submit_action(state, "p2", {"type": "bid", "amount": 3})
    assert state.player("p2").happiness == 15  # 10 + 5


def test_toads_from_an_instant_are_placeable_the_same_round():
    state = to_auction(make_game(2), ["spawning_pool", "monument"], gold=5)
    state = commit_all(
        state,
        {"p1": {"type": "bid", "amount": 3}, "p2": {"type": "bid", "amount": 0}},
    )
    assert state.player("p1").toads == 5  # bypasses the recruitment cap
    state = engine.submit_action(state, "p2", {"type": "bid", "amount": 0})
    assert state.phase == engine.PHASE_PLACEMENT
    # All five must be placed, and all five must then be fed.
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "p1", place(fields=2))
    state = commit_all(state, {"p1": place(fields=5), "p2": place(fields=2)})
    assert state.phase == engine.PHASE_FEED
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "p1", {"type": "feed", "keep": 6})


def test_live_auction_runs_ascending_until_all_but_one_pass():
    state = to_auction(
        make_game(3, auction_mode=config.AUCTION_MODE_LIVE),
        ["grand_monument", "monument", "monument"],
        gold=5,
    )
    assert state.auction.stage == engine.STAGE_LIVE
    assert engine.pending_players(state) == ["p1"]
    state = engine.submit_action(state, "p1", {"type": "bid", "amount": 3})
    assert state.auction.high_bid == 3
    state = engine.submit_action(state, "p2", {"type": "bid", "amount": 4})
    state = engine.submit_action(state, "p3", {"type": "pass"})
    state = engine.submit_action(state, "p1", {"type": "pass"})
    assert state.player("p2").cards == ["grand_monument"]
    assert state.player("p2").gold == 1


def test_live_auction_raises_must_actually_raise():
    state = to_auction(
        make_game(2, auction_mode=config.AUCTION_MODE_LIVE), ["monument", "monument"]
    )
    state = engine.submit_action(state, "p1", {"type": "bid", "amount": 3})
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "p2", {"type": "bid", "amount": 3})
    state = engine.submit_action(state, "p2", {"type": "bid", "amount": 4})
    assert state.auction.high_bidder == "p2"


def test_next_rounds_slate_is_revealed_when_this_auction_ends():
    """You place your toads already knowing what is coming up for sale."""
    state = to_auction(make_game(2), ["monument", "festival"])
    assert state.upcoming == []          # not while this auction is running
    state = commit_all(
        state,
        {"p1": {"type": "bid", "amount": 0}, "p2": {"type": "bid", "amount": 0}},
    )
    state = commit_all(
        state,
        {"p1": {"type": "bid", "amount": 0}, "p2": {"type": "bid", "amount": 0}},
    )
    assert state.phase == engine.PHASE_PLACEMENT
    assert len(state.upcoming) == 2      # one card per player
    preview = list(state.upcoming)
    assert any(e["type"] == "upcoming" for e in state.log)

    # It is public: everyone sees the same cards at the same moment.
    for pid in ("p1", "p2"):
        assert engine.player_view(state, pid)["upcoming"] == preview

    # And it is exactly what comes up for auction next round.
    state = commit_all(state, {"p1": place(fields=2), "p2": place(fields=2)})
    state = commit_all(
        state,
        {"p1": {"type": "feed", "keep": 2}, "p2": {"type": "feed", "keep": 2}},
    )
    assert state.round == 2
    assert engine.player_view(state, "p1")["upcoming"] == preview  # still visible
    state = commit_all(
        state, {p.id: {"type": "recruit", "count": 0} for p in state.players}
    )
    assert [r["card"] for r in state.auction.results] == preview
    assert state.upcoming == []


def test_the_final_round_has_no_slate_to_preview():
    state = make_game(2, rounds=1)
    state = to_auction(state, ["monument", "festival"])
    state = commit_all(
        state,
        {"p1": {"type": "bid", "amount": 0}, "p2": {"type": "bid", "amount": 0}},
    )
    state = commit_all(
        state,
        {"p1": {"type": "bid", "amount": 0}, "p2": {"type": "bid", "amount": 0}},
    )
    assert state.phase == engine.PHASE_PLACEMENT
    assert state.upcoming == []          # nothing comes after the last round


def test_previewed_cards_are_still_accounted_for():
    state = make_game(3)   # a real deck, not a stacked one
    state = commit_all(
        state, {p.id: {"type": "recruit", "count": 0} for p in state.players}
    )
    for _ in range(3):
        state = commit_all(
            state,
            {pid: {"type": "bid", "amount": 0} for pid in engine.pending_players(state)},
        )
    owned = sum(len(p.cards) for p in state.players)
    total = owned + len(state.deck) + len(state.removed) + len(state.upcoming)
    assert total == card_lib.deck_size(3)


def test_a_preview_survives_a_serialise_reload():
    state = to_auction(make_game(2), ["monument", "festival"])
    for _ in range(2):
        state = commit_all(
            state,
            {pid: {"type": "bid", "amount": 0} for pid in engine.pending_players(state)},
        )
    assert state.upcoming
    restored = engine.deserialize(json.loads(json.dumps(engine.serialize(state))))
    assert restored.upcoming == state.upcoming


def test_deck_exhaustion_shortens_or_skips_the_auction():
    state = make_game(3)
    state.deck = ["monument"]
    state = commit_all(
        state, {p.id: {"type": "recruit", "count": 0} for p in state.players}
    )
    assert len(state.auction.slate) == 1
    state = commit_all(
        state, {pid: {"type": "bid", "amount": 0} for pid in engine.pending_players(state)}
    )
    assert state.phase == engine.PHASE_PLACEMENT

    state = make_game(3)
    state.deck = []
    state = commit_all(
        state, {p.id: {"type": "recruit", "count": 0} for p in state.players}
    )
    assert state.phase == engine.PHASE_PLACEMENT


# ---------------------------------------------------------------------------
# Phase 3 — production, majorities, war
# ---------------------------------------------------------------------------


def test_production_rates():
    state = make_game(2)
    set_phase(state, engine.PHASE_PLACEMENT)
    for p in state.players:
        p.toads = 4
    state = commit_all(
        state,
        {
            "p1": place(fields=2, mine=1, rest=1),
            "p2": place(military=4),
        },
    )
    p1 = state.player("p1")
    assert p1.flies == 16          # 10 + 2*2 production + 2 Fields majority
    assert p1.gold == config.START_GOLD + 4   # 2*1 production + 2 Mine majority
    # 10 + 1 rest + 1 Rest majority (round 1) - 1 war loss = 11
    assert p1.happiness == 11
    assert state.player("p2").flies == 10   # Military produces nothing


def test_majority_tie_pays_production_but_no_bonus():
    state = make_game(2)
    set_phase(state, engine.PHASE_PLACEMENT)
    for p in state.players:
        p.toads = 3
    state = commit_all(state, {"p1": place(fields=3), "p2": place(fields=3)})
    for p in state.players:
        assert p.flies == 16       # 10 + 3*2, and no +2 majority bonus
    assert any(e["type"] == "majority_tie" for e in state.log)


def test_majority_bonus_goes_to_a_unique_leader():
    state = make_game(3)
    set_phase(state, engine.PHASE_PLACEMENT)
    for p in state.players:
        p.toads = 3
    state = commit_all(
        state,
        {"p1": place(mine=3), "p2": place(mine=2, fields=1), "p3": place(fields=3)},
    )
    assert state.player("p1").gold == config.START_GOLD + 8   # 3*2 + 2 majority
    assert state.player("p2").gold == config.START_GOLD + 4   # 2*2, no bonus
    assert state.player("p3").flies == 18  # 10 + 3*2 + 2 majority


def test_an_empty_area_awards_no_majority():
    state = make_game(2)
    set_phase(state, engine.PHASE_PLACEMENT)
    for p in state.players:
        p.toads = 2
    state = commit_all(state, {"p1": place(fields=2), "p2": place(fields=2)})
    # Nobody was in Mine or Rest, so no gold or happiness bonus was handed out.
    assert [p.gold for p in state.players] == [config.START_GOLD] * 2
    assert [p.happiness for p in state.players] == [10, 10]


def test_majority_bonuses_escalate_with_the_round():
    state = make_game(2)
    state.round = 4
    set_phase(state, engine.PHASE_PLACEMENT)
    for p in state.players:
        p.toads = 2
    state = commit_all(state, {"p1": place(fields=2), "p2": place(mine=2)})
    assert state.player("p1").flies == 19   # 10 + 4 + 5 (round 4 bonus)
    assert state.player("p2").gold == config.START_GOLD + 9   # 2*2 + round-4 bonus


def test_war_winner_takes_the_token_and_everyone_else_loses_happiness():
    state = make_game(3)
    state.round = 3
    set_phase(state, engine.PHASE_PLACEMENT)
    for p in state.players:
        p.toads = 2
    state = commit_all(
        state,
        {"p1": place(military=2), "p2": place(military=1, fields=1), "p3": place(fields=2)},
    )
    assert state.player("p1").war_tokens == [4]     # round + 1
    assert happiness(state) == {"p1": 10, "p2": 9, "p3": 9}


def test_war_tie_awards_no_token_and_costs_nobody_happiness():
    """The denial play: matching the leader spares the whole table."""
    state = make_game(3)
    set_phase(state, engine.PHASE_PLACEMENT)
    for p in state.players:
        p.toads = 2
    state = commit_all(
        state,
        {
            "p1": place(military=2),
            "p2": place(military=2),
            "p3": place(fields=2),   # stayed out entirely, still pays nothing
        },
    )
    assert all(p.war_tokens == [] for p in state.players)
    assert happiness(state) == {"p1": 10, "p2": 10, "p3": 10}
    assert any(e["type"] == "war_tie" for e in state.log)


def test_no_military_at_all_is_a_tie_not_a_win():
    state = make_game(2)
    set_phase(state, engine.PHASE_PLACEMENT)
    for p in state.players:
        p.toads = 2
    state = commit_all(state, {"p1": place(fields=2), "p2": place(rest=2)})
    assert all(p.war_tokens == [] for p in state.players)
    assert state.player("p1").happiness == 10


def test_strength_cards_need_a_toad_in_military():
    """Ruling 8: Barracks and War College only count with >=1 Military toad."""
    state = make_game(2)
    set_phase(state, engine.PHASE_PLACEMENT)
    for p in state.players:
        p.toads = 2
    state.player("p1").cards = ["war_college"]
    state = commit_all(state, {"p1": place(fields=2), "p2": place(military=1, fields=1)})
    assert state.player("p2").war_tokens == [2]   # p1 fielded nobody: strength 0

    state = make_game(2)
    set_phase(state, engine.PHASE_PLACEMENT)
    for p in state.players:
        p.toads = 2
    state.player("p1").cards = ["war_college"]
    state = commit_all(state, {"p1": place(military=1, fields=1), "p2": place(military=2)})
    assert state.player("p1").war_tokens == [2]   # 1 toad + 2 strength beats 2


def test_engine_cards_fire_only_when_the_threshold_is_met_and_they_stack():
    state = make_game(2)
    set_phase(state, engine.PHASE_PLACEMENT)
    for p in state.players:
        p.toads = 3
    state.player("p1").cards = ["fly_farm", "fly_farm", "great_marsh"]
    state.player("p2").cards = ["great_marsh"]
    state = commit_all(state, {"p1": place(fields=3), "p2": place(fields=2, rest=1)})
    # p1: 10 + 6 production + (2 + 2 + 4) cards + 2 majority = 26
    assert state.player("p1").flies == 26
    # p2: 10 + 4 production; Great Marsh needs 3 in Fields and stays silent.
    assert state.player("p2").flies == 14


def test_happiness_is_clamped_to_the_ceiling_once_per_phase():
    state = make_game(2)
    set_phase(state, engine.PHASE_PLACEMENT)
    for p in state.players:
        p.toads = 3
    state.player("p1").happiness = 19
    state.player("p1").cards = ["lily_gardens", "lily_gardens"]
    state = commit_all(state, {"p1": place(rest=3), "p2": place(fields=3)})
    assert state.player("p1").happiness == 20   # 19 + 3 + 4 + 1 capped


def test_happiness_is_clamped_to_the_floor():
    state = make_game(3)
    set_phase(state, engine.PHASE_PLACEMENT)
    for p in state.players:
        p.toads = 2
    state.player("p2").happiness = 1
    state = commit_all(
        state,
        {"p1": place(military=2), "p2": place(fields=2), "p3": place(fields=2)},
    )
    assert state.player("p2").happiness == 1    # loses the war, cannot go to 0


# ---------------------------------------------------------------------------
# Phase 4 — feeding
# ---------------------------------------------------------------------------


def test_feeding_costs_one_fly_per_toad():
    state = make_game(2)
    set_phase(state, engine.PHASE_FEED)
    for p in state.players:
        p.toads = 4
    state = commit_all(
        state, {"p1": {"type": "feed", "keep": 4}, "p2": {"type": "feed", "keep": 4}}
    )
    assert state.player("p1").flies == 6
    assert state.player("p1").toads == 4
    assert state.player("p1").happiness == 10


def test_starvation_is_a_free_choice_and_costs_happiness():
    state = make_game(2)
    set_phase(state, engine.PHASE_FEED)
    for p in state.players:
        p.toads = 4
    # p1 could feed all four but chooses to downsize.
    state = commit_all(
        state, {"p1": {"type": "feed", "keep": 1}, "p2": {"type": "feed", "keep": 4}}
    )
    assert state.player("p1").toads == 1
    assert state.player("p1").flies == 9        # only paid for the one kept
    assert state.player("p1").happiness == 7    # 3 starved, 1 happiness each


def test_you_cannot_feed_more_toads_than_you_have_flies_for():
    state = make_game(2)
    set_phase(state, engine.PHASE_FEED)
    state.player("p1").toads = 6
    state.player("p1").flies = 3
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "p1", {"type": "feed", "keep": 4})
    with pytest.raises(engine.InvalidAction):
        engine.submit_action(state, "p1", {"type": "feed", "keep": 7})
    state = engine.submit_action(state, "p1", {"type": "feed", "keep": 3})
    assert state.commitments["p1"]["keep"] == 3


def test_feeding_happens_in_the_final_round_before_scoring():
    state = make_game(2, rounds=1)
    set_phase(state, engine.PHASE_FEED)
    for p in state.players:
        p.toads = 3
    state = commit_all(
        state, {"p1": {"type": "feed", "keep": 3}, "p2": {"type": "feed", "keep": 0}}
    )
    assert state.phase == engine.PHASE_FINISHED
    assert state.player("p2").toads == 0
    assert state.scores["breakdown"]["p2"]["toads"] == 0
    # p2 starved into the fly majority; the toads are already gone when counted.
    assert state.scores["end_majorities"]["flies"] == "p2"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_scoring_counts_toads_tokens_and_cards():
    state = make_game(2)
    p1 = state.player("p1")
    p1.toads = 5
    p1.war_tokens = [2, 5]
    p1.cards = ["monument", "grand_monument", "fly_farm"]
    result = engine.score(state)
    b = result["breakdown"]["p1"]
    assert b["toads"] == 10
    assert b["war_tokens"] == 7
    assert b["cards"] == 17     # 5 + 10 + 2
    assert b["resources"] == 0  # gold, flies and happiness score nothing per unit


def test_conditional_cards_round_down():
    state = make_game(2)
    p1 = state.player("p1")
    p1.toads = 7
    p1.gold = 8
    p1.war_tokens = [2, 3, 4]
    p1.cards = ["census", "treasury", "hall_of_victories"]
    b = engine.score(state)["breakdown"]["p1"]
    assert b["conditional"] == 3 + 2 + 6   # 7//2, 8//3, 3 tokens * 2


def test_end_game_majorities_award_five_or_nothing():
    state = make_game(3)
    state.player("p1").gold = 20
    state.player("p2").gold = 1
    state.player("p3").gold = 1
    state.player("p1").flies = 5
    state.player("p2").flies = 5      # tied for flies: nobody scores
    state.player("p3").flies = 1
    state.player("p3").happiness = 15
    result = engine.score(state)
    assert result["end_majorities"] == {"gold": "p1", "flies": None, "happiness": "p3"}
    assert result["breakdown"]["p1"]["majorities"] == 5
    assert result["breakdown"]["p3"]["majorities"] == 5
    assert result["breakdown"]["p2"]["majorities"] == 0


def test_tiebreakers_are_vp_then_toads_then_happiness():
    state = make_game(3)
    for p in state.players:
        p.gold = p.flies = 0
        p.happiness = 5
    state.player("p1").toads = 5
    state.player("p2").toads = 5
    state.player("p3").toads = 4
    state.player("p2").happiness = 9   # also takes the 5 VP happiness majority
    state.player("p3").cards = ["monument", "monument", "monument"]
    result = engine.score(state)
    assert result["totals"]["p2"] > result["totals"]["p1"]
    assert result["winners"] == ["p3"]  # 8 + 15 VP beats both

    # A dead-even table is a shared win.
    even = make_game(2)
    assert sorted(engine.score(even)["winners"]) == ["p1", "p2"]


# ---------------------------------------------------------------------------
# Views — hidden information
# ---------------------------------------------------------------------------


def _walk(node):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def test_a_view_never_contains_another_players_commitment():
    state = make_game(3)
    set_phase(state, engine.PHASE_PLACEMENT)
    for p in state.players:
        p.toads = 4
    secret = place(mine=3, military=1)
    state = engine.submit_action(state, "p1", secret)

    mine = engine.player_view(state, "p1")
    theirs = engine.player_view(state, "p2")
    spectator = engine.player_view(state, None)

    assert mine["your_commitment"] == secret
    assert theirs["your_commitment"] is None
    assert spectator["your_commitment"] is None
    for view in (theirs, spectator):
        assert not any(node == secret["placement"] for node in _walk(view))
        json.dumps(view)  # the view must be JSON-safe for the socket layer


def test_a_view_shows_who_has_committed_but_not_what():
    state = make_game(2)
    state = engine.submit_action(state, "p1", {"type": "recruit", "count": 3})
    view = engine.player_view(state, "p2")
    committed = {p["id"]: p["committed"] for p in view["players"]}
    assert committed == {"p1": True, "p2": False}
    assert view["waiting_on"] == ["p2"]


def test_blind_bids_stay_hidden_until_they_are_revealed():
    state = to_auction(make_game(3), ["monument", "monument", "monument"])
    state = engine.submit_action(state, "p1", {"type": "bid", "amount": 5})
    view = engine.player_view(state, "p2")
    assert view["auction"]["slate"][0]["bids"] == {}
    assert not any(node == 5 for node in _walk(view["auction"]))
    state = commit_all(
        state,
        {"p2": {"type": "bid", "amount": 3}, "p3": {"type": "bid", "amount": 0}},
    )
    revealed = engine.player_view(state, "p2")["auction"]["slate"][0]
    assert revealed["bids"] == {"p1": 5, "p2": 3}
    assert revealed["winner"] == "p1"


def test_public_material_is_visible_to_everyone():
    state = make_game(2)
    state.player("p1").cards = ["monument"]
    state.player("p1").war_tokens = [3]
    seen = engine.player_view(state, "p2")["players"][0]
    assert seen["flies"] == config.START_FLIES
    assert seen["gold"] == config.START_GOLD
    assert seen["toads"] == 2 and seen["happiness"] == 10
    assert seen["cards"] == ["monument"] and seen["war_tokens"] == [3]
    assert seen["recruit_cost"] == 3


def test_view_reports_this_rounds_bonus_values():
    state = make_game(2)
    state.round = 5
    view = engine.player_view(state, "p1")
    assert view["bonuses"] == {
        "fields": 6,
        "mine": 6,
        "rest": 3,
        "war_token_vp": 6,
    }


# ---------------------------------------------------------------------------
# Timeouts and serialisation
# ---------------------------------------------------------------------------


def test_timeout_defaults_are_conservative():
    state = make_game(3)
    state = engine.submit_action(state, "p1", {"type": "recruit", "count": 2})
    state = engine.force_resolve(state)
    assert state.player("p1").toads == 4    # the player who acted keeps their move
    assert state.player("p2").toads == 2    # recruit nothing
    assert state.player("p3").toads == 2
    assert state.phase == engine.PHASE_AUCTION

    # Each card on the slate is its own commitment round with its own timer.
    cards_timed_out = 0
    while state.phase == engine.PHASE_AUCTION:
        state = engine.force_resolve(state)  # bid nothing
        cards_timed_out += 1
    assert cards_timed_out == 3             # one per card at three players
    assert state.phase == engine.PHASE_PLACEMENT
    assert all(p.cards == [] for p in state.players)
    assert len(state.removed) == 3          # unbid cards leave the game

    state = engine.force_resolve(state)     # everything into Fields
    assert state.player("p2").last_placement[config.FIELDS] == 2
    assert state.phase == engine.PHASE_FEED

    state = engine.force_resolve(state)     # feed as many as possible
    assert all(p.toads > 0 for p in state.players)
    assert state.round == 2


def test_a_timeout_can_target_one_seat_only():
    state = make_game(3)
    state = engine.force_resolve(state, ["p2"])
    assert state.commitments["p2"] == {"type": "recruit", "count": 0}
    assert sorted(engine.pending_players(state)) == ["p1", "p3"]


def test_a_rebid_timeout_matches_the_tie_rather_than_folding():
    state = to_auction(make_game(2), ["monument", "monument"], gold=5)
    state = commit_all(
        state,
        {"p1": {"type": "bid", "amount": 4}, "p2": {"type": "bid", "amount": 4}},
    )
    state = engine.force_resolve(state)
    assert "monument" in state.removed      # both matched, so the card burns
    assert state.player("p1").gold == 2


def test_state_survives_a_serialise_reload_round_trip():
    state = make_game(3, seed=42)
    state = commit_all(
        state, {"p1": {"type": "recruit", "count": 1}, "p2": {"type": "recruit", "count": 2}}
    )
    state = engine.submit_action(state, "p3", {"type": "recruit", "count": 0})
    state = engine.submit_action(state, "p1", {"type": "bid", "amount": 4})

    blob = json.dumps(engine.serialize(state))
    restored = engine.deserialize(json.loads(blob))

    assert engine.serialize(restored) == engine.serialize(state)
    assert engine.pending_players(restored) == engine.pending_players(state)
    # An in-flight commitment survives, and still belongs to the right seat.
    assert restored.commitments["p1"] == {"type": "bid", "amount": 4}
    assert engine.player_view(restored, "p1")["your_commitment"] is not None
    assert engine.player_view(restored, "p2")["your_commitment"] is None

    # And play continues identically from either copy.
    rest = {pid: {"type": "bid", "amount": 0} for pid in engine.pending_players(state)}
    assert engine.serialize(commit_all(state, rest)) == engine.serialize(
        commit_all(restored, rest)
    )


# ---------------------------------------------------------------------------
# Full game
# ---------------------------------------------------------------------------


def random_action(view: dict, rng: random.Random) -> dict:
    """A legal move chosen from the player view alone — no state access."""
    me = next(p for p in view["players"] if p["id"] == view["you"])
    phase = view["phase"]
    if phase == engine.PHASE_RECRUIT:
        affordable = me["flies"] // me["recruit_cost"]
        return {"type": "recruit", "count": rng.randint(0, min(config.RECRUIT_CAP, affordable))}
    if phase == engine.PHASE_AUCTION:
        auction = view["auction"]
        if auction["stage"] == engine.STAGE_LIVE:
            floor = max(config.AUCTION_MIN_BID, auction["high_bid"] + config.AUCTION_LIVE_MIN_RAISE)
            if me["gold"] >= floor and rng.random() < 0.4:
                return {"type": "bid", "amount": rng.randint(floor, me["gold"])}
            return {"type": "pass"}
        if auction["stage"] == engine.STAGE_REBID:
            return {"type": "bid", "amount": rng.randint(auction["tied_amount"], me["gold"])}
        if rng.random() < 0.5:
            return {"type": "bid", "amount": 0}
        return {"type": "bid", "amount": rng.randint(config.AUCTION_MIN_BID, me["gold"])}
    if phase == engine.PHASE_PLACEMENT:
        placement = {area: 0 for area in config.AREAS}
        for _ in range(me["toads"]):
            placement[rng.choice(config.AREAS)] += 1
        return {"type": "place", "placement": placement}
    if phase == engine.PHASE_FEED:
        return {"type": "feed", "keep": min(me["toads"], me["flies"] // config.FEED_COST)}
    raise AssertionError(phase)


@pytest.mark.parametrize("players", [2, 3, 4, 5, 6])
@pytest.mark.parametrize("mode", [config.AUCTION_MODE_BLIND, config.AUCTION_MODE_LIVE])
def test_a_full_game_plays_to_a_score_without_breaking_an_invariant(players, mode):
    rng = random.Random(players * 100 + len(mode))
    state = make_game(players, seed=players, auction_mode=mode)
    steps = 0
    while not state.finished:
        steps += 1
        assert steps < 5000, "game failed to terminate"
        pid = engine.pending_players(state)[0]
        action = random_action(engine.player_view(state, pid), rng)
        state = engine.submit_action(state, pid, action)
        for p in state.players:
            assert p.flies >= 0 and p.gold >= 0 and p.toads >= 0
            assert config.HAPPINESS_MIN <= p.happiness <= config.HAPPINESS_MAX
    assert state.round == config.ROUNDS
    assert state.scores is not None
    assert state.scores["winners"]
    # Every card is accounted for: still in the deck, owned, or removed.
    owned = sum(len(p.cards) for p in state.players)
    accounted = owned + len(state.deck) + len(state.removed) + len(state.upcoming)
    assert accounted == card_lib.deck_size(players)


def test_a_seed_reproduces_a_whole_game():
    def play(seed):
        rng = random.Random(seed)
        state = make_game(4, seed=seed)
        while not state.finished:
            pid = engine.pending_players(state)[0]
            state = engine.submit_action(
                state, pid, random_action(engine.player_view(state, pid), rng)
            )
        return engine.score(state)["totals"]

    assert play(2024) == play(2024)
