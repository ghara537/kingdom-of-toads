"""Kingdom of Toads — bot seats.

Four readable strategies. Every one of them decides from a ``player_view``
dict and nothing else: the strategy functions never receive a GameState, so a
bot physically cannot read an opponent's unrevealed commitment. ``take_turn``
is the single place that touches state, and all it does is build the view.

The tuning knobs live at the top of each class. Game rules and balance
constants come from config.py; the numbers here are *opinions about play*, not
rules, which is why they live with the strategies.
"""

from __future__ import annotations

import math
import random
from typing import Any

import cards as card_lib
import config
import engine

# Rough gold each card is worth to a neutral player, before strategy taste and
# before the time-value adjustment below. Edit freely — this is the main dial.
BASE_CARD_VALUE = {
    "fly_farm": 5,
    "great_marsh": 7,
    "gold_seam": 6,
    "deep_vein": 8,
    "lily_gardens": 5,
    "barracks": 4,
    "war_college": 6,
    "festival": 5,
    "public_park": 3,
    "granary": 6,
    "larder": 4,
    "spawning_pool": 9,
    "tadpole_pond": 6,
    "monument": 6,
    "grand_monument": 11,
    "census": 4,
    "treasury": 4,
    "hall_of_victories": 3,
}


class Bot:
    """Base strategy. Subclasses mostly just change the constants."""

    name = "bot"

    # Share of toads sent to each area, before threshold and war corrections.
    weights = {config.FIELDS: 0.4, config.MINE: 0.3, config.MILITARY: 0.2, config.REST: 0.1}
    # Multipliers on BASE_CARD_VALUE, by card id.
    card_taste: dict[str, float] = {}
    # Recruit up to this many toads a round, gold permitting.
    recruit_appetite = config.RECRUIT_CAP
    # Stop recruiting once happiness costs this much per toad or more.
    recruit_cost_ceiling = 4
    # Happiness below this pulls toads into Rest.
    happiness_floor = 8
    # How many toads we will divert to switch on an owned engine card.
    threshold_stretch = 2
    # How many toads we will divert into Mine for next round's slate.
    mine_stretch = 2
    # Willingness to keep fighting a tie-off: 0 folds, 1 always matches.
    tie_off_nerve = 0.5

    def __init__(self, player_id: str, rng: random.Random | None = None):
        self.player_id = player_id
        self.rng = rng or random.Random()

    # -- entry point --------------------------------------------------------

    def act(self, view: dict) -> dict:
        """Choose an action from the player view alone."""
        phase = view["phase"]
        if phase == engine.PHASE_RECRUIT:
            return {"type": "recruit", "count": self.recruit(view)}
        if phase == engine.PHASE_AUCTION:
            return self.auction(view)
        if phase == engine.PHASE_PLACEMENT:
            return {"type": "place", "placement": self.place(view)}
        if phase == engine.PHASE_FEED:
            return {"type": "feed", "keep": self.feed(view)}
        raise ValueError(f"no bot decision for phase {phase}")

    # -- phase 1 ------------------------------------------------------------

    def recruit(self, view: dict) -> int:
        me = _me(view)
        cost = me["recruit_cost"]
        if cost > self.recruit_cost_ceiling:
            return 0
        spendable = max(0, me["flies"] - self._feed_reserve(view))
        return max(0, min(self.recruit_appetite, config.RECRUIT_CAP, spendable // cost))

    def _feed_reserve(self, view: dict) -> int:
        """Flies to hold back so this round's toads do not starve.

        Fields toads pay for themselves and one other, so only the toads beyond
        twice the Fields share need covering out of pocket.
        """
        me = _me(view)
        expected_income = 2 * round(me["toads"] * self.weights[config.FIELDS])
        return max(0, me["toads"] - expected_income)

    # -- phase 2 ------------------------------------------------------------

    def auction(self, view: dict) -> dict:
        auction = view["auction"]
        me = _me(view)
        card_id = auction["slate"][auction["index"]]["card"]
        value = self.value_card(view, card_id)

        if auction["stage"] == engine.STAGE_REBID:
            return {"type": "bid", "amount": self.rebid(view, value)}

        budget = min(value, me["gold"], self._auction_budget(view, value))
        if auction["stage"] == engine.STAGE_LIVE:
            floor = max(
                config.AUCTION_MIN_BID,
                auction["high_bid"] + config.AUCTION_LIVE_MIN_RAISE,
            )
            if floor <= budget:
                return {"type": "bid", "amount": floor}
            return {"type": "pass"}

        if budget < config.AUCTION_MIN_BID:
            return {"type": "bid", "amount": 0}
        # Blind: bid a shade under our valuation, jittered so that bots do not
        # tie every single time (though ties are a real and wanted outcome).
        bid = budget - self.rng.randint(0, 1)
        return {"type": "bid", "amount": max(config.AUCTION_MIN_BID, bid)}

    def _auction_budget(self, view: dict, value: int) -> int:
        """Hold gold back if a card we like more is still to come this round."""
        auction = view["auction"]
        me = _me(view)
        later = [
            self.value_card(view, entry["card"])
            for entry in auction["slate"][auction["index"] + 1:]
            if entry["status"] == engine.PENDING
        ]
        best_later = max(later, default=0)
        if best_later > value and me["gold"] < value + best_later:
            # Cannot have both; save up for the better one.
            return 0
        return me["gold"]

    def rebid(self, view: dict, value: int) -> int:
        """Equal-or-higher. Raising costs gold; matching risks burning the card."""
        auction = view["auction"]
        me = _me(view)
        tied = auction["tied_amount"]
        if value > tied and me["gold"] >= tied + 1:
            return tied + 1
        if self.rng.random() < self.tie_off_nerve:
            return tied  # chicken: I would rather burn it than let you have it
        return tied

    def value_card(self, view: dict, card_id: str) -> int:
        """What this card is worth to us in gold, affordability aside.

        Used both for bidding and for planning ahead against next round's
        slate, so it deliberately does not care what we can pay today.
        """
        card = card_lib.get(card_id)
        value = BASE_CARD_VALUE.get(card_id, 4) * self.card_taste.get(card_id, 1.0)
        rounds_left = view["rounds"] - view["round"] + 1

        # An engine card is only worth the rounds it still has left to fire.
        if card.is_engine and card.effect_kind != config.MILITARY_STRENGTH:
            value *= min(1.0, rounds_left / 3)
        # Toad instants are pure points late on; everything material is dead
        # weight in the final round.
        if card.is_instant and card.effect_kind == config.TOADS:
            value *= 1.4 if rounds_left <= 2 else 1.0
        elif card.is_instant and rounds_left == 1:
            value *= 0.4
        return max(0, int(round(value)))

    # -- phase 3 ------------------------------------------------------------

    def place(self, view: dict) -> dict:
        me = _me(view)
        toads = me["toads"]
        placement = _allocate(toads, self.weights)
        placement = self._military_correction(view, placement)
        placement = self._happiness_correction(view, placement)
        placement = self._upcoming_correction(view, placement)
        # Thresholds go last so an owned engine card always gets its staff:
        # a card that fires every round beats one round of extra mining.
        placement = self._threshold_correction(view, placement)
        return placement

    def _upcoming_correction(self, view: dict, placement: dict) -> dict:
        """Mine ahead of next round's slate, which is already face-up.

        Gold spent next round has to be dug this round, so a card worth having
        is worth a toad or two in the Mine now.
        """
        upcoming = view.get("upcoming") or []
        if not upcoming:
            return placement
        me = _me(view)
        want = max(self.value_card(view, card_id) for card_id in upcoming)
        shortfall = want - me["gold"]
        if shortfall <= 0:
            return placement
        per_toad = config.PRODUCTION[config.MINE][config.GOLD]
        extra = min(self.mine_stretch, math.ceil(shortfall / per_toad))
        return _move_to(
            placement,
            config.MINE,
            placement[config.MINE] + extra,
            donor_order=[a for a in self._donors() if a != config.MINE],
        )

    def military_target(self, view: dict) -> int:
        """How many toads to send to war. Read from public last-round data."""
        me = _me(view)
        if me["toads"] <= 2:
            return 0
        return 1 if self.weights[config.MILITARY] > 0 else 0

    def _military_correction(self, view: dict, placement: dict) -> dict:
        target = self.military_target(view)
        return _move_to(placement, config.MILITARY, target, donor_order=self._donors())

    def _happiness_correction(self, view: dict, placement: dict) -> dict:
        """Buy happiness back when the recruitment band is getting expensive."""
        me = _me(view)
        if me["happiness"] >= self.happiness_floor or me["toads"] < 2:
            return placement
        wanted = min(2, me["toads"] // 2)
        if placement[config.REST] >= wanted:
            return placement
        return _move_to(placement, config.REST, wanted, donor_order=self._donors())

    def _threshold_correction(self, view: dict, placement: dict) -> dict:
        """Staff an area up to the threshold of an owned engine card.

        A card that never fires is 2 VP of wasted gold, so it is worth moving a
        toad or two — but not worth gutting the rest of the mat, hence the
        stretch limit.
        """
        me = _me(view)
        for card_id in sorted(set(me["cards"])):
            card = card_lib.get(card_id)
            if not card.is_engine or card.requirement is None:
                continue
            area, needed = card.requirement
            short = needed - placement[area]
            if 0 < short <= self.threshold_stretch and needed <= me["toads"]:
                placement = _move_to(
                    placement,
                    area,
                    needed,
                    donor_order=[a for a in self._donors() if a != area],
                )
        return placement

    def _donors(self) -> list[str]:
        """Areas to take toads from, least valued first."""
        return sorted(config.AREAS, key=lambda a: self.weights.get(a, 0))

    # -- phase 4 ------------------------------------------------------------

    def feed(self, view: dict) -> int:
        me = _me(view)
        affordable = min(me["toads"], me["flies"] // config.FEED_COST)
        if view["round"] < view["rounds"]:
            return affordable
        # Final round: a toad is 2 VP but the fly majority is 5, so starving one
        # or two to top the fly count can pay. Assume rivals feed everything.
        rivals = [
            p["flies"] - min(p["toads"], p["flies"])
            for p in view["players"]
            if p["id"] != self.player_id
        ]
        best, best_score = affordable, -1
        for keep in range(max(0, affordable - 2), affordable + 1):
            flies_left = me["flies"] - keep * config.FEED_COST
            score = keep * config.VP_PER_TOAD
            if rivals and all(flies_left > r for r in rivals):
                score += config.END_MAJORITIES[config.FLIES]
            if score > best_score:
                best, best_score = keep, score
        return best


# ---------------------------------------------------------------------------
# The four strategies
# ---------------------------------------------------------------------------


class Farmer(Bot):
    """Fields first, and grow the toad count hard."""

    name = "farmer"
    weights = {config.FIELDS: 0.65, config.MINE: 0.1, config.MILITARY: 0.15, config.REST: 0.1}
    card_taste = {
        "fly_farm": 1.6,
        "great_marsh": 1.7,
        "granary": 1.4,
        "larder": 1.3,
        "spawning_pool": 1.5,
        "tadpole_pond": 1.4,
        "census": 1.5,
        "gold_seam": 0.6,
        "deep_vein": 0.6,
    }
    recruit_appetite = config.RECRUIT_CAP
    recruit_cost_ceiling = 4
    happiness_floor = 9
    tie_off_nerve = 0.4
    mine_stretch = 1


class Miner(Bot):
    """Mine first, then buy the slate out from under everyone."""

    name = "miner"
    weights = {config.FIELDS: 0.3, config.MINE: 0.5, config.MILITARY: 0.1, config.REST: 0.1}
    card_taste = {
        "gold_seam": 1.7,
        "deep_vein": 1.8,
        "treasury": 1.6,
        "grand_monument": 1.4,
        "monument": 1.3,
        "fly_farm": 0.7,
        "great_marsh": 0.7,
    }
    recruit_appetite = 2
    recruit_cost_ceiling = 3
    happiness_floor = 7
    tie_off_nerve = 0.7   # deep purse, happy to play chicken
    mine_stretch = 3

    def value_card(self, view: dict, card_id: str) -> int:
        # A miner outbids the table by design.
        return int(super().value_card(view, card_id) * 1.25)


class Warlord(Bot):
    """Contest the war every round; tie it to deny when outright victory is out."""

    name = "warlord"
    weights = {config.FIELDS: 0.35, config.MINE: 0.15, config.MILITARY: 0.4, config.REST: 0.1}
    card_taste = {
        "barracks": 2.0,
        "war_college": 2.2,
        "hall_of_victories": 2.0,
        "spawning_pool": 1.3,
        "lily_gardens": 0.7,
    }
    recruit_appetite = 3
    recruit_cost_ceiling = 4
    happiness_floor = 6
    tie_off_nerve = 0.8
    mine_stretch = 1

    def military_target(self, view: dict) -> int:
        me = _me(view)
        rival = _rival_military_estimate(view, self.player_id)
        strength_cards = _card_strength(me["cards"])

        # Beat the likely leader outright if we can spare the toads.
        to_beat = rival + 1 - strength_cards
        if 0 < to_beat <= max(1, me["toads"] - 2):
            return max(1, to_beat)
        # Otherwise match exactly: a tied war denies the token AND spares the
        # whole table the happiness loss, which costs the leader far more.
        to_match = rival - strength_cards
        if 0 < to_match <= max(1, me["toads"] - 1):
            return max(1, to_match)
        return 1 if me["toads"] >= 2 else 0


class Balanced(Bot):
    """Spread out, then lean into whichever majority looks cheapest this round."""

    name = "balanced"
    weights = {config.FIELDS: 0.35, config.MINE: 0.3, config.MILITARY: 0.2, config.REST: 0.15}
    card_taste = {"monument": 1.2, "grand_monument": 1.2}
    recruit_appetite = 3
    recruit_cost_ceiling = 3
    happiness_floor = 9
    tie_off_nerve = 0.5
    mine_stretch = 2

    def place(self, view: dict) -> dict:
        placement = super().place(view)
        me = _me(view)
        if me["toads"] < 3:
            return placement
        # Cheapest majority = biggest bonus for the fewest toads needed to lead,
        # judged on what everyone did last round (public information).
        best_area, best_needed, best_ratio = None, 0, 0.0
        for area in config.MAJORITY_AREAS:
            needed = _rival_area_estimate(view, self.player_id, area) + 1
            if needed > me["toads"]:
                continue
            ratio = view["bonuses"][area] / needed
            if ratio > best_ratio:
                best_area, best_needed, best_ratio = area, needed, ratio
        if best_area is None:
            return placement
        needed = best_needed
        if placement[best_area] >= needed:
            return placement
        return _move_to(
            placement,
            best_area,
            needed,
            donor_order=[a for a in self._donors() if a != best_area],
        )


STRATEGIES: dict[str, type[Bot]] = {
    Farmer.name: Farmer,
    Miner.name: Miner,
    Warlord.name: Warlord,
    Balanced.name: Balanced,
}

DEFAULT_STRATEGY = Balanced.name


# ---------------------------------------------------------------------------
# Driving a bot
# ---------------------------------------------------------------------------


def make(strategy: str, player_id: str, rng: random.Random | None = None) -> Bot:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown bot strategy: {strategy}")
    return STRATEGIES[strategy](player_id, rng)


def decide(view: dict, strategy: str, rng: random.Random | None = None) -> dict:
    """Pure: a view in, an action out. No state, no I/O."""
    return make(strategy, view["you"], rng).act(view)


def take_turn(
    state: engine.GameState,
    player_id: str,
    strategy: str,
    rng: random.Random | None = None,
) -> engine.GameState:
    """Have a bot act once. The ONLY function here that sees a GameState.

    The strategy is handed a per-player view and never the state itself, so a
    bot has exactly the information a human in that seat would have.
    """
    view = engine.player_view(state, player_id)
    action = decide(view, strategy, rng)
    try:
        return engine.submit_action(state, player_id, action)
    except engine.InvalidAction:
        # A strategy must never be able to wedge a table: fall back to the
        # engine's conservative timeout move.
        return engine.submit_action(state, player_id, engine.default_action(state, player_id))


def play_out(
    state: engine.GameState,
    strategies: dict[str, str],
    rng: random.Random | None = None,
) -> engine.GameState:
    """Run every bot seat until the game needs a human, or ends."""
    rng = rng or random.Random()
    while not state.finished:
        waiting = engine.pending_players(state)
        actionable = [pid for pid in waiting if pid in strategies]
        if not actionable:
            return state
        for pid in actionable:
            if pid in engine.pending_players(state):
                state = take_turn(state, pid, strategies[pid], rng)
    return state


# ---------------------------------------------------------------------------
# View helpers — everything below reads a view dict, never a GameState
# ---------------------------------------------------------------------------


def _me(view: dict) -> dict:
    return next(p for p in view["players"] if p["id"] == view["you"])


def _rivals(view: dict, player_id: str) -> list[dict]:
    return [p for p in view["players"] if p["id"] != player_id]


def _rival_area_estimate(view: dict, player_id: str, area: str) -> int:
    """Best guess at the toads a rival will field in an area this round.

    Last round's placements are public, so this is legitimate information.
    """
    return max(
        (p["last_placement"].get(area, 0) for p in _rivals(view, player_id)),
        default=0,
    )


def _rival_military_estimate(view: dict, player_id: str) -> int:
    best = 0
    for p in _rivals(view, player_id):
        toads = p["last_placement"].get(config.MILITARY, 0)
        if toads:
            toads += _card_strength(p["cards"])
        best = max(best, toads)
    return best


def _card_strength(card_ids: list[str]) -> int:
    total = 0
    for card_id in card_ids:
        card = card_lib.get(card_id)
        if card.is_engine and card.effect_kind == config.MILITARY_STRENGTH:
            total += card.effect_amount
    return total


def _allocate(toads: int, weights: dict[str, float]) -> dict[str, int]:
    """Split toads across areas by weight, largest remainder first."""
    placement = {area: 0 for area in config.AREAS}
    if toads <= 0:
        return placement
    total_weight = sum(weights.get(a, 0) for a in config.AREAS) or 1
    exact = {a: toads * weights.get(a, 0) / total_weight for a in config.AREAS}
    for area in config.AREAS:
        placement[area] = int(exact[area])
    left = toads - sum(placement.values())
    for area in sorted(config.AREAS, key=lambda a: exact[a] - int(exact[a]), reverse=True):
        if left <= 0:
            break
        placement[area] += 1
        left -= 1
    return placement


def _move_to(
    placement: dict[str, int], area: str, target: int, donor_order: list[str]
) -> dict[str, int]:
    """Shift toads into ``area`` until it holds ``target``, robbing donors."""
    placement = dict(placement)
    target = max(0, target)
    while placement[area] < target:
        donor = next(
            (a for a in donor_order if a != area and placement.get(a, 0) > 0), None
        )
        if donor is None:
            break
        placement[donor] -= 1
        placement[area] += 1
    while placement[area] > target:
        receiver = next((a for a in reversed(donor_order) if a != area), None)
        if receiver is None:
            break
        placement[area] -= 1
        placement[receiver] += 1
    return placement
