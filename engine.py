"""Kingdom of Toads — the rules engine.

Pure, framework-free, no I/O. Given a game state and player actions it returns
the next state. Deterministic for a given seed: the only randomness is the
initial deck shuffle.

State is plain dataclasses of ints, strs, lists and dicts — no lambdas, no
objects that cannot be round-tripped through JSON. ``serialize`` and
``deserialize`` are exact inverses.

The engine never decides what a player is allowed to *see*. ``player_view``
does that, and it is the only way the web layer or a bot may read state.

Rules reference: DESIGN.md v1.0, plus the rulings recorded in RULINGS below.
"""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field, asdict
from typing import Any

import cards as card_lib
import config

# Rulings taken where DESIGN.md was silent (see the spec review):
RULINGS = """
8.  Barracks/War College strength counts only with >=1 toad in Military.
9.  Duplicate engine cards stack.
10. A majority needs a unique holder of at least 1 toad; ties award nothing.
11. Phase 3 order: production -> engine cards -> majorities -> war -> war
    penalty, with happiness clamped once at the end of the phase.
12. A card nobody bids on is removed from the game.
13. A bid of 0 is a pass; any real bid is >= AUCTION_MIN_BID.
14. Live mode raises by at least AUCTION_LIVE_MIN_RAISE.
15. If the deck runs dry the slate is short, or the auction is skipped.
16. Every toad must be placed; Rest is the idle area.
17. Conditional scorers round down.
18. A dead-even game after all tiebreakers is a shared win.
"""

# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

PHASE_RECRUIT = "recruit"
PHASE_AUCTION = "auction"
PHASE_PLACEMENT = "placement"
PHASE_FEED = "feed"
PHASE_FINISHED = "finished"

# Blind-auction sub-stages.
STAGE_BID = "bid"
STAGE_REBID = "rebid"
STAGE_LIVE = "live"

# Outcome markers for a card on the slate.
SOLD = "sold"
BURNED_TIE = "burned_tie"       # double tie: penalties paid, card destroyed
BURNED_UNSOLD = "burned_unsold"  # nobody bid
PENDING = "pending"


class InvalidAction(Exception):
    """A player action that must be rejected without touching state."""


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass
class Settings:
    rounds: int = config.ROUNDS
    auction_mode: str = config.AUCTION_MODE_DEFAULT


@dataclass
class PlayerState:
    id: str
    name: str
    flies: int = config.START_FLIES
    gold: int = config.START_GOLD
    toads: int = config.START_TOADS
    happiness: int = config.START_HAPPINESS
    cards: list[str] = field(default_factory=list)      # owned card ids
    war_tokens: list[int] = field(default_factory=list)  # VP value of each
    # Last *revealed* placement. Public: the current round's hidden placement
    # lives in GameState.commitments until the phase resolves.
    last_placement: dict[str, int] = field(default_factory=dict)


@dataclass
class AuctionState:
    slate: list[str] = field(default_factory=list)        # card ids, in order
    results: list[dict] = field(default_factory=list)     # one per slate entry
    index: int = 0
    stage: str = STAGE_BID
    # Blind tie-off bookkeeping.
    tied_players: list[str] = field(default_factory=list)
    tied_amount: int = 0
    rebids_used: int = 0
    # Live-mode bookkeeping.
    high_bid: int = 0
    high_bidder: str | None = None
    passed: list[str] = field(default_factory=list)
    turn: str | None = None


@dataclass
class GameState:
    players: list[PlayerState]
    settings: Settings
    seed: int
    round: int = 1
    phase: str = PHASE_RECRUIT
    # Seat index of the first player marker. Rotates one seat per round. It
    # sets the bidding order in a live auction; every other phase is
    # simultaneous, where it is a display token only.
    first_player: int = 0
    deck: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)     # left the game
    auction: AuctionState | None = None
    # Hidden commitments for the phase in progress, keyed by player id.
    commitments: dict[str, Any] = field(default_factory=dict)
    log: list[dict] = field(default_factory=list)
    scores: dict[str, Any] | None = None

    def player(self, player_id: str) -> PlayerState:
        for p in self.players:
            if p.id == player_id:
                return p
        raise InvalidAction(f"no such seat: {player_id}")

    @property
    def player_ids(self) -> list[str]:
        return [p.id for p in self.players]

    @property
    def finished(self) -> bool:
        return self.phase == PHASE_FINISHED


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def new_game(
    seats: list[tuple[str, str]],
    settings: Settings | None = None,
    seed: int | None = None,
) -> GameState:
    """Start a game. ``seats`` is a list of (player_id, display name)."""
    if not config.MIN_PLAYERS <= len(seats) <= config.MAX_PLAYERS:
        raise ValueError(
            f"player count must be {config.MIN_PLAYERS}-{config.MAX_PLAYERS}"
        )
    ids = [s[0] for s in seats]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate seat ids")

    settings = settings or Settings()
    if settings.auction_mode not in (
        config.AUCTION_MODE_BLIND,
        config.AUCTION_MODE_LIVE,
    ):
        raise ValueError(f"unknown auction mode: {settings.auction_mode}")

    seed = random.randrange(2**31) if seed is None else seed
    deck = card_lib.deck_composition(len(seats))
    random.Random(seed).shuffle(deck)

    state = GameState(
        players=[PlayerState(id=pid, name=name) for pid, name in seats],
        settings=settings,
        seed=seed,
        deck=deck,
    )
    _log(state, "game_start", text=f"Round 1 — recruitment. {len(seats)} players.")
    return state


# ---------------------------------------------------------------------------
# Who are we waiting on
# ---------------------------------------------------------------------------


def pending_players(state: GameState) -> list[str]:
    """Seats that still owe a decision before the phase can resolve."""
    if state.finished:
        return []
    if state.phase in (PHASE_RECRUIT, PHASE_PLACEMENT, PHASE_FEED):
        return [p.id for p in state.players if p.id not in state.commitments]
    if state.phase == PHASE_AUCTION:
        auction = state.auction
        if auction is None or auction.index >= len(auction.slate):
            return []
        if auction.stage == STAGE_LIVE:
            return [auction.turn] if auction.turn else []
        if auction.stage == STAGE_REBID:
            return [p for p in auction.tied_players if p not in state.commitments]
        return [
            p.id
            for p in state.players
            if _eligible_to_bid(p) and p.id not in state.commitments
        ]
    return []


def _eligible_to_bid(player: PlayerState) -> bool:
    return player.gold >= config.AUCTION_ELIGIBILITY


def seat_order(state: GameState) -> list[str]:
    """Seat ids starting from the first player marker."""
    ids = state.player_ids
    start = state.first_player % len(ids)
    return ids[start:] + ids[:start]


# ---------------------------------------------------------------------------
# Action entry point
# ---------------------------------------------------------------------------


def submit_action(state: GameState, player_id: str, action: dict) -> GameState:
    """Validate and apply one action, returning a NEW state.

    Raises InvalidAction — leaving the caller's state untouched — if the action
    is not legal right now. Resolves phases as soon as everyone has committed.
    """
    validate_action(state, player_id, action)
    nxt = copy.deepcopy(state)
    _record(nxt, player_id, action)
    return _advance(nxt)


def validate_action(state: GameState, player_id: str, action: dict) -> None:
    """Raise InvalidAction unless ``action`` is legal for this seat right now."""
    if state.finished:
        raise InvalidAction("the game is over")
    player = state.player(player_id)  # raises on an unknown seat
    if player_id not in pending_players(state):
        if player_id in state.commitments:
            raise InvalidAction("you have already committed for this phase")
        raise InvalidAction("it is not your decision to make right now")

    kind = action.get("type")

    if state.phase == PHASE_RECRUIT:
        if kind != "recruit":
            raise InvalidAction("expected a recruit action")
        count = _as_int(action.get("count"), "count")
        if count < 0:
            raise InvalidAction("cannot recruit a negative number of toads")
        if count > config.RECRUIT_CAP:
            raise InvalidAction(f"recruitment is capped at {config.RECRUIT_CAP}")
        cost = count * config.recruit_cost(player.happiness)
        if cost > player.flies:
            raise InvalidAction(
                f"{count} toads costs {cost} flies; you hold {player.flies}"
            )
        return

    if state.phase == PHASE_AUCTION:
        _validate_auction_action(state, player, action, kind)
        return

    if state.phase == PHASE_PLACEMENT:
        if kind != "place":
            raise InvalidAction("expected a place action")
        placement = action.get("placement")
        if not isinstance(placement, dict):
            raise InvalidAction("placement must be a mapping of area to toads")
        total = 0
        for area, count in placement.items():
            if area not in config.AREAS:
                raise InvalidAction(f"unknown area: {area}")
            count = _as_int(count, f"{area} count")
            if count < 0:
                raise InvalidAction("cannot place a negative number of toads")
            total += count
        if total != player.toads:
            raise InvalidAction(
                f"you must place exactly {player.toads} toads, not {total}"
            )
        return

    if state.phase == PHASE_FEED:
        if kind != "feed":
            raise InvalidAction("expected a feed action")
        keep = _as_int(action.get("keep"), "keep")
        if keep < 0:
            raise InvalidAction("cannot keep a negative number of toads")
        if keep > player.toads:
            raise InvalidAction(f"you only have {player.toads} toads")
        if keep * config.FEED_COST > player.flies:
            raise InvalidAction(
                f"feeding {keep} toads costs {keep * config.FEED_COST} flies; "
                f"you hold {player.flies}"
            )
        return

    raise InvalidAction(f"nothing to do in phase {state.phase}")


def _validate_auction_action(
    state: GameState, player: PlayerState, action: dict, kind: str | None
) -> None:
    auction = state.auction
    assert auction is not None

    if auction.stage == STAGE_LIVE:
        if kind == "pass":
            return
        if kind != "bid":
            raise InvalidAction("expected a bid or a pass")
        amount = _as_int(action.get("amount"), "amount")
        floor = max(config.AUCTION_MIN_BID, auction.high_bid + config.AUCTION_LIVE_MIN_RAISE)
        if amount < floor:
            raise InvalidAction(f"a raise must be at least {floor} gold")
        if amount > player.gold:
            raise InvalidAction(f"you only hold {player.gold} gold")
        return

    if kind != "bid":
        raise InvalidAction("expected a bid action")
    amount = _as_int(action.get("amount"), "amount")
    if amount > player.gold:
        raise InvalidAction(f"you cannot bid more than the {player.gold} gold you hold")

    if auction.stage == STAGE_REBID:
        if amount < auction.tied_amount:
            raise InvalidAction(
                f"a re-bid must be at least the tied {auction.tied_amount} gold"
            )
        return

    if amount == 0:
        return  # a pass
    if amount < config.AUCTION_MIN_BID:
        raise InvalidAction(f"the minimum bid is {config.AUCTION_MIN_BID} gold")


def _as_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidAction(f"{label} must be a whole number")
    return value


def _record(state: GameState, player_id: str, action: dict) -> None:
    """Store a validated commitment. Live bids apply immediately instead."""
    auction = state.auction
    if state.phase == PHASE_AUCTION and auction and auction.stage == STAGE_LIVE:
        _apply_live_action(state, player_id, action)
        return
    state.commitments[player_id] = copy.deepcopy(action)


# ---------------------------------------------------------------------------
# Timeouts — a bot-quality default so one absent player cannot freeze a table
# ---------------------------------------------------------------------------


def default_action(state: GameState, player_id: str) -> dict:
    """A deliberately conservative move for a player who ran out of time."""
    player = state.player(player_id)
    if state.phase == PHASE_RECRUIT:
        return {"type": "recruit", "count": 0}
    if state.phase == PHASE_AUCTION:
        auction = state.auction
        if auction and auction.stage == STAGE_REBID:
            # A re-bid cannot be passed; match the tie and take the chicken.
            return {"type": "bid", "amount": auction.tied_amount}
        if auction and auction.stage == STAGE_LIVE:
            return {"type": "pass"}
        return {"type": "bid", "amount": 0}
    if state.phase == PHASE_PLACEMENT:
        return {"type": "place", "placement": {config.FIELDS: player.toads}}
    if state.phase == PHASE_FEED:
        return {"type": "feed", "keep": min(player.toads, player.flies // config.FEED_COST)}
    raise InvalidAction(f"no default action in phase {state.phase}")


def force_resolve(state: GameState, player_ids: list[str] | None = None) -> GameState:
    """Fill in defaults for players who have not committed, then resolve.

    ``player_ids`` limits the substitution to specific seats; by default every
    outstanding seat is covered.
    """
    nxt = copy.deepcopy(state)
    outstanding = pending_players(nxt)
    targets = outstanding if player_ids is None else [
        p for p in outstanding if p in player_ids
    ]
    for pid in targets:
        action = default_action(nxt, pid)
        _log(nxt, "timeout", player=pid, text=f"{_name(nxt, pid)} timed out.")
        _record(nxt, pid, action)
    return _advance(nxt)


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------


def _advance(state: GameState) -> GameState:
    """Resolve phases until someone owes a decision, or the game ends."""
    guard = 0
    while not state.finished and not pending_players(state):
        guard += 1
        if guard > 10_000:  # pragma: no cover - structural safety net
            raise RuntimeError("engine failed to make progress")
        if state.phase == PHASE_RECRUIT:
            _resolve_recruit(state)
        elif state.phase == PHASE_AUCTION:
            _resolve_auction_step(state)
        elif state.phase == PHASE_PLACEMENT:
            _resolve_placement(state)
        elif state.phase == PHASE_FEED:
            _resolve_feed(state)
        else:  # pragma: no cover - unreachable
            break
    return state


# --- Phase 1 ---------------------------------------------------------------


def _resolve_recruit(state: GameState) -> None:
    for player in state.players:
        count = state.commitments[player.id]["count"]
        cost = count * config.recruit_cost(player.happiness)
        player.flies -= cost
        player.toads += count
        if count:
            _log(
                state,
                "recruit",
                player=player.id,
                count=count,
                cost=cost,
                text=f"{player.name} recruited {count} for {cost} flies.",
            )
    state.commitments = {}
    _begin_auction(state)


# --- Phase 2 ---------------------------------------------------------------


def _begin_auction(state: GameState) -> None:
    wanted = len(state.players) * config.AUCTION_CARDS_PER_PLAYER
    slate = [state.deck.pop() for _ in range(min(wanted, len(state.deck)))]
    state.auction = AuctionState(
        slate=slate,
        results=[
            {"card": cid, "status": PENDING, "winner": None, "price": None, "bids": {}}
            for cid in slate
        ],
    )
    state.phase = PHASE_AUCTION
    state.commitments = {}
    if not slate:
        _log(state, "auction_skipped", text="The deck is empty — no auction.")
        _begin_placement(state)
        return
    names = ", ".join(card_lib.get(cid).name for cid in slate)
    _log(state, "slate", slate=list(slate), text=f"Slate: {names}.")
    _prepare_card(state)


def _prepare_card(state: GameState) -> None:
    """Set up bidding for the current card, or move on if nobody can bid."""
    auction = state.auction
    assert auction is not None
    if auction.index >= len(auction.slate):
        _begin_placement(state)
        return

    state.commitments = {}
    auction.tied_players = []
    auction.tied_amount = 0
    auction.rebids_used = 0
    auction.high_bid = 0
    auction.high_bidder = None
    auction.passed = []
    auction.turn = None

    eligible = [p.id for p in state.players if _eligible_to_bid(p)]
    if not eligible:
        _finish_card(state, status=BURNED_UNSOLD)
        return

    if state.settings.auction_mode == config.AUCTION_MODE_LIVE:
        auction.stage = STAGE_LIVE
        auction.passed = [p.id for p in state.players if p.id not in eligible]
        # Bidding on every card opens with the first player marker.
        auction.turn = next(pid for pid in seat_order(state) if pid in eligible)
    else:
        auction.stage = STAGE_BID


def _resolve_auction_step(state: GameState) -> None:
    """Called when nobody owes a decision: score the current bidding round."""
    auction = state.auction
    assert auction is not None
    if auction.index >= len(auction.slate):
        _begin_placement(state)
        return
    if auction.stage == STAGE_LIVE:
        _resolve_live_card(state)
        return

    bids = {pid: act["amount"] for pid, act in state.commitments.items()}
    auction.results[auction.index]["bids"].update(
        {pid: amt for pid, amt in bids.items() if amt > 0}
    )
    real = {pid: amt for pid, amt in bids.items() if amt > 0}

    if not real:
        _log(state, "no_bids", text=f"{_card_name(state)} drew no bids.")
        _finish_card(state, status=BURNED_UNSOLD)
        return

    top = max(real.values())
    leaders = sorted(pid for pid, amt in real.items() if amt == top)

    if len(leaders) == 1:
        _award_card(state, leaders[0], top)
        return

    if auction.rebids_used < config.AUCTION_REBIDS:
        auction.stage = STAGE_REBID
        auction.tied_players = leaders
        auction.tied_amount = top
        auction.rebids_used += 1
        state.commitments = {}
        names = ", ".join(_name(state, pid) for pid in leaders)
        _log(
            state,
            "tie",
            players=leaders,
            amount=top,
            text=f"{names} tied at {top} gold — one re-bid.",
        )
        return

    # Tied again: everyone pays the penalty and the card leaves the game.
    for pid in leaders:
        state.player(pid).gold -= config.AUCTION_TIE_PENALTY
    names = ", ".join(_name(state, pid) for pid in leaders)
    _log(
        state,
        "tie_burn",
        players=leaders,
        amount=top,
        text=(
            f"{names} tied again at {top} — each pays "
            f"{config.AUCTION_TIE_PENALTY} gold and {_card_name(state)} "
            "is removed from the game."
        ),
    )
    _finish_card(state, status=BURNED_TIE, tied=leaders)


def _apply_live_action(state: GameState, player_id: str, action: dict) -> None:
    auction = state.auction
    assert auction is not None
    if action.get("type") == "pass":
        auction.passed.append(player_id)
        _log(
            state,
            "live_pass",
            player=player_id,
            text=f"{_name(state, player_id)} passed.",
        )
    else:
        amount = action["amount"]
        auction.high_bid = amount
        auction.high_bidder = player_id
        auction.results[auction.index]["bids"][player_id] = amount
        _log(
            state,
            "live_bid",
            player=player_id,
            amount=amount,
            text=f"{_name(state, player_id)} bids {amount} gold.",
        )
    auction.turn = _next_live_actor(state)


def _next_live_actor(state: GameState) -> str | None:
    """The next seat that may raise, or None when the card is settled."""
    auction = state.auction
    assert auction is not None
    active = [
        p.id
        for p in state.players
        if p.id not in auction.passed and _eligible_to_bid(p)
    ]
    contenders = [pid for pid in active if pid != auction.high_bidder]
    if not contenders:
        return None
    # A player can only raise if they can actually afford one.
    floor = max(config.AUCTION_MIN_BID, auction.high_bid + config.AUCTION_LIVE_MIN_RAISE)
    affordable = [pid for pid in contenders if state.player(pid).gold >= floor]
    if not affordable:
        return None
    order = seat_order(state)
    if auction.turn in order:
        start = (order.index(auction.turn) + 1) % len(order)
        order = order[start:] + order[:start]
    for pid in order:
        if pid in affordable:
            return pid
    return affordable[0]  # pragma: no cover - unreachable


def _resolve_live_card(state: GameState) -> None:
    auction = state.auction
    assert auction is not None
    if auction.high_bidder is None:
        _log(state, "no_bids", text=f"{_card_name(state)} drew no bids.")
        _finish_card(state, status=BURNED_UNSOLD)
        return
    _award_card(state, auction.high_bidder, auction.high_bid)


def _award_card(state: GameState, winner_id: str, price: int) -> None:
    auction = state.auction
    assert auction is not None
    card_id = auction.slate[auction.index]
    winner = state.player(winner_id)
    winner.gold -= price
    winner.cards.append(card_id)
    _log(
        state,
        "card_won",
        player=winner_id,
        card=card_id,
        price=price,
        text=f"{winner.name} won {card_lib.get(card_id).name} for {price} gold.",
    )
    _resolve_instant(state, winner, card_id)
    _finish_card(state, status=SOLD, winner=winner_id, price=price)


def _resolve_instant(state: GameState, player: PlayerState, card_id: str) -> None:
    card = card_lib.get(card_id)
    if not card.is_instant:
        return
    kind, amount = card.effect
    if kind == config.FLIES:
        player.flies += amount
    elif kind == config.GOLD:
        player.gold += amount
    elif kind == config.TOADS:
        player.toads += amount
    elif kind == config.HAPPINESS:
        player.happiness = config.clamp_happiness(player.happiness + amount)
    _log(
        state,
        "instant",
        player=player.id,
        card=card_id,
        text=f"{player.name}: {card.name} — {card.describe()}.",
    )


def _finish_card(
    state: GameState,
    status: str,
    winner: str | None = None,
    price: int | None = None,
    tied: list[str] | None = None,
) -> None:
    auction = state.auction
    assert auction is not None
    result = auction.results[auction.index]
    result["status"] = status
    result["winner"] = winner
    result["price"] = price
    if tied:
        result["tied"] = list(tied)
    if status in (BURNED_TIE, BURNED_UNSOLD):
        state.removed.append(auction.slate[auction.index])
        if status == BURNED_UNSOLD and not config.AUCTION_BURN_UNSOLD:
            state.removed.pop()
            state.deck.insert(0, auction.slate[auction.index])
    auction.index += 1
    _prepare_card(state)


# --- Phase 3 ---------------------------------------------------------------


def _begin_placement(state: GameState) -> None:
    state.phase = PHASE_PLACEMENT
    state.commitments = {}


def _resolve_placement(state: GameState) -> None:
    rnd = state.round
    placements = {
        p.id: _normalise_placement(state.commitments[p.id]["placement"])
        for p in state.players
    }
    # Happiness accumulates raw and is clamped once, at the end of the phase.
    happiness = {p.id: p.happiness for p in state.players}

    for player in state.players:
        placement = placements[player.id]
        player.last_placement = placement

        # (b) per-toad production
        for area, per_toad in config.PRODUCTION.items():
            count = placement.get(area, 0)
            if not count:
                continue
            for resource, rate in per_toad.items():
                gain = rate * count
                if resource == config.FLIES:
                    player.flies += gain
                elif resource == config.GOLD:
                    player.gold += gain
                elif resource == config.HAPPINESS:
                    happiness[player.id] += gain

        # (c) engine cards, stacking, gated on this round's placement
        for card_id in player.cards:
            card = card_lib.get(card_id)
            if not card.is_engine or not card.requirement_met(placement):
                continue
            kind, amount = card.effect
            if kind == config.FLIES:
                player.flies += amount
            elif kind == config.GOLD:
                player.gold += amount
            elif kind == config.HAPPINESS:
                happiness[player.id] += amount
            # MILITARY_STRENGTH is handled in the war step.

    # (d) area majorities — unique holder of at least MAJORITY_MIN_TOADS
    for area in config.MAJORITY_AREAS:
        counts = {pid: placements[pid].get(area, 0) for pid in placements}
        winner = _unique_leader(counts, minimum=config.MAJORITY_MIN_TOADS)
        resource, amount = config.majority_bonus(area, rnd)
        if winner is None:
            _log(
                state,
                "majority_tie",
                area=area,
                text=f"{area.title()} majority tied — no bonus.",
            )
            continue
        player = state.player(winner)
        if resource == config.FLIES:
            player.flies += amount
        elif resource == config.GOLD:
            player.gold += amount
        elif resource == config.HAPPINESS:
            happiness[winner] += amount
        _log(
            state,
            "majority",
            area=area,
            player=winner,
            amount=amount,
            text=f"{player.name} takes the {area.title()} majority (+{amount}).",
        )

    # (e) war
    strengths = {
        pid: military_strength(state.player(pid), placements[pid])
        for pid in placements
    }
    war_winner = _unique_leader(strengths, minimum=config.WAR_MIN_STRENGTH)
    if war_winner is None:
        _log(
            state,
            "war_tie",
            strengths=strengths,
            text="The war is tied — no token, and nobody loses happiness.",
        )
    else:
        vp = config.war_token_vp(rnd)
        state.player(war_winner).war_tokens.append(vp)
        # (f) every other player pays, but only because there was a winner
        for player in state.players:
            if player.id != war_winner:
                happiness[player.id] -= config.WAR_LOSS_PENALTY
        _log(
            state,
            "war",
            player=war_winner,
            vp=vp,
            strengths=strengths,
            text=(
                f"{_name(state, war_winner)} wins the war ({vp} VP); "
                "everyone else loses 1 happiness."
            ),
        )

    for player in state.players:
        player.happiness = config.clamp_happiness(happiness[player.id])

    state.commitments = {}
    state.phase = PHASE_FEED


def _normalise_placement(placement: dict[str, int]) -> dict[str, int]:
    return {area: int(placement.get(area, 0)) for area in config.AREAS}


def military_strength(player: PlayerState, placement: dict[str, int]) -> int:
    """Toads in Military, plus card strength if the gate is met (ruling 8)."""
    toads = placement.get(config.MILITARY, 0)
    if toads < config.WAR_STRENGTH_CARD_MIN_TOADS:
        return toads
    bonus = 0
    for card_id in player.cards:
        card = card_lib.get(card_id)
        if card.is_engine and card.effect_kind == config.MILITARY_STRENGTH:
            bonus += card.effect_amount
    return toads + bonus


def _unique_leader(counts: dict[str, int], minimum: int) -> str | None:
    """The single highest scorer, or None on a tie or if nobody clears ``minimum``."""
    if not counts:
        return None
    top = max(counts.values())
    if top < minimum:
        return None
    leaders = [pid for pid, value in counts.items() if value == top]
    return leaders[0] if len(leaders) == 1 else None


# --- Phase 4 ---------------------------------------------------------------


def _resolve_feed(state: GameState) -> None:
    for player in state.players:
        keep = state.commitments[player.id]["keep"]
        starved = player.toads - keep
        player.flies -= keep * config.FEED_COST
        player.toads = keep
        if starved:
            player.happiness = config.clamp_happiness(
                player.happiness - starved * config.STARVE_HAPPINESS_COST
            )
            _log(
                state,
                "starve",
                player=player.id,
                count=starved,
                text=f"{player.name} lost {starved} toads to starvation.",
            )
    state.commitments = {}

    if state.round >= state.settings.rounds:
        state.scores = score(state)
        state.phase = PHASE_FINISHED
        winners = ", ".join(_name(state, pid) for pid in state.scores["winners"])
        _log(state, "game_end", text=f"Game over. Winner: {winners}.")
        return

    state.round += 1
    state.first_player = (state.first_player + 1) % len(state.players)
    state.phase = PHASE_RECRUIT
    _log(
        state,
        "round_start",
        first_player=state.players[state.first_player].id,
        text=(
            f"Round {state.round} — recruitment. "
            f"{state.players[state.first_player].name} has the first player marker."
        ),
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score(state: GameState) -> dict[str, Any]:
    """Final scoring. Safe to call at any time for a projected score."""
    breakdown: dict[str, dict[str, Any]] = {}

    for player in state.players:
        flat = 0
        conditional = 0
        conditional_detail: dict[str, int] = {}
        for card_id in player.cards:
            card = card_lib.get(card_id)
            flat += card.vp
            if card.is_conditional:
                metric, per, vp = card.conditional
                value = {
                    config.TOADS: player.toads,
                    config.GOLD: player.gold,
                    config.WAR_TOKENS: len(player.war_tokens),
                    config.FLIES: player.flies,
                    config.HAPPINESS: player.happiness,
                }[metric]
                earned = (value // per) * vp
                conditional += earned
                conditional_detail[card_id] = (
                    conditional_detail.get(card_id, 0) + earned
                )
        breakdown[player.id] = {
            "toads": player.toads * config.VP_PER_TOAD,
            "war_tokens": sum(player.war_tokens),
            "cards": flat,
            "conditional": conditional,
            "conditional_detail": conditional_detail,
            "resources": (
                player.gold * config.VP_PER_GOLD
                + player.flies * config.VP_PER_FLY
                + player.happiness * config.VP_PER_HAPPINESS
            ),
            "majorities": 0,
            "majority_detail": {},
        }

    # End-game majorities: unique leader only, ties award nothing.
    majority_results: dict[str, str | None] = {}
    for metric, vp in config.END_MAJORITIES.items():
        values = {p.id: getattr(p, metric) for p in state.players}
        winner = _unique_leader(values, minimum=1)
        majority_results[metric] = winner
        if winner is not None:
            breakdown[winner]["majorities"] += vp
            breakdown[winner]["majority_detail"][metric] = vp

    totals = {
        pid: sum(v for k, v in b.items() if isinstance(v, int))
        for pid, b in breakdown.items()
    }
    for pid, total in totals.items():
        breakdown[pid]["total"] = total

    ranking = sorted(
        state.players,
        key=lambda p: (totals[p.id], p.toads, p.happiness),
        reverse=True,
    )
    best = (
        totals[ranking[0].id],
        ranking[0].toads,
        ranking[0].happiness,
    )
    winners = [
        p.id
        for p in state.players
        if (totals[p.id], p.toads, p.happiness) == best
    ]

    return {
        "breakdown": breakdown,
        "totals": totals,
        "ranking": [p.id for p in ranking],
        "winners": winners,
        "end_majorities": majority_results,
    }


# ---------------------------------------------------------------------------
# Views — the ONLY way a client or a bot may read state
# ---------------------------------------------------------------------------


def player_view(state: GameState, viewer_id: str | None) -> dict[str, Any]:
    """Everything ``viewer_id`` is entitled to see, and nothing else.

    Built additively from scratch: no other player's unrevealed commitment is
    ever copied into the result, in any field. ``viewer_id`` of None gives a
    pure spectator view.
    """
    waiting = pending_players(state)
    rnd = state.round

    players = []
    for p in state.players:
        players.append(
            {
                "id": p.id,
                "name": p.name,
                "flies": p.flies,
                "gold": p.gold,
                "toads": p.toads,
                "happiness": p.happiness,
                "recruit_cost": config.recruit_cost(p.happiness),
                "recruit_band": list(config.recruit_band(p.happiness)),
                "cards": list(p.cards),
                "war_tokens": list(p.war_tokens),
                "last_placement": dict(p.last_placement),
                "committed": p.id in state.commitments,
                "waiting_on": p.id in waiting,
                "can_bid": _eligible_to_bid(p),
            }
        )

    view: dict[str, Any] = {
        "round": rnd,
        "rounds": state.settings.rounds,
        "phase": state.phase,
        "auction_mode": state.settings.auction_mode,
        "you": viewer_id,
        "first_player": state.players[state.first_player].id,
        "seat_order": seat_order(state),
        "players": players,
        "waiting_on": list(waiting),
        "deck_remaining": len(state.deck),
        "removed": list(state.removed),
        "bonuses": {
            "fields": config.majority_bonus(config.FIELDS, rnd)[1],
            "mine": config.majority_bonus(config.MINE, rnd)[1],
            "rest": config.majority_bonus(config.REST, rnd)[1],
            "war_token_vp": config.war_token_vp(rnd),
        },
        "log": list(state.log),
        "projected_scores": score(state)["totals"],
        "scores": copy.deepcopy(state.scores),
    }

    if state.auction is not None and state.phase == PHASE_AUCTION:
        a = state.auction
        view["auction"] = {
            "index": a.index,
            "stage": a.stage,
            "slate": [
                {
                    "card": r["card"],
                    "status": r["status"],
                    "winner": r["winner"],
                    "price": r["price"],
                    # Safe to publish: results["bids"] is only ever written at
                    # reveal time (blind) or by an open live bid. Unrevealed
                    # commitments live in state.commitments and never land here.
                    "bids": dict(r["bids"]),
                }
                for r in a.results
            ],
            "tied_players": list(a.tied_players),
            "tied_amount": a.tied_amount,
            # Live mode is open by definition — the standing bid is public.
            "high_bid": a.high_bid if a.stage == STAGE_LIVE else None,
            "high_bidder": a.high_bidder if a.stage == STAGE_LIVE else None,
            "passed": list(a.passed) if a.stage == STAGE_LIVE else [],
            "turn": a.turn,
        }

    if viewer_id is not None and viewer_id in state.commitments:
        view["your_commitment"] = copy.deepcopy(state.commitments[viewer_id])
    else:
        view["your_commitment"] = None

    return view


# ---------------------------------------------------------------------------
# Serialisation — exact round trip, JSON-safe
# ---------------------------------------------------------------------------


def serialize(state: GameState) -> dict[str, Any]:
    return asdict(state)


def deserialize(data: dict[str, Any]) -> GameState:
    auction = data.get("auction")
    return GameState(
        players=[PlayerState(**p) for p in data["players"]],
        settings=Settings(**data["settings"]),
        seed=data["seed"],
        round=data["round"],
        phase=data["phase"],
        first_player=data.get("first_player", 0),
        deck=list(data["deck"]),
        removed=list(data["removed"]),
        auction=AuctionState(**auction) if auction else None,
        commitments=copy.deepcopy(data["commitments"]),
        log=copy.deepcopy(data["log"]),
        scores=copy.deepcopy(data.get("scores")),
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def note(state: GameState, kind: str, text: str, **fields: Any) -> None:
    """Record a table event (a pause, a vote) in the game log.

    The session layer uses this so that everything a player sees in the log
    lives in one place, and survives serialisation with the rest of the state.
    """
    _log(state, kind, text, **fields)


def _log(state: GameState, kind: str, text: str = "", **fields: Any) -> None:
    entry = {"round": state.round, "phase": state.phase, "type": kind, "text": text}
    entry.update(fields)
    state.log.append(entry)


def _name(state: GameState, player_id: str) -> str:
    for p in state.players:
        if p.id == player_id:
            return p.name
    return player_id


def _card_name(state: GameState) -> str:
    auction = state.auction
    assert auction is not None
    return card_lib.get(auction.slate[auction.index]).name
