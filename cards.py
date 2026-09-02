"""Kingdom of Toads — the property deck.

Typed, read-only view over ``config.CARD_DEFS``. No rules logic and no
randomness: this module says what the cards ARE and how many of each go into
a deck, never what happens when one is played. The engine resolves effects and
does the shuffling (from its seed).

Game state stores card *ids* (strings), never Card objects, so state stays
trivially JSON-serialisable.
"""

from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass(frozen=True)
class Card:
    """One property card type."""

    id: str
    name: str
    group: str
    vp: int
    # Village cards fill the early rounds, city cards the late ones.
    development: str = config.VILLAGE
    # Engine cards only: (area, min_toads) that gates the effect. None = always.
    requirement: tuple[str, int] | None = None
    # Engine (every Phase 3) or instant (once, on purchase): (kind, amount).
    effect: tuple[str, int] | None = None
    # Conditional scorers only: (metric, per, vp) -> floor(metric/per) * vp.
    conditional: tuple[str, int, int] | None = None
    # Activated cards only: (ability, cost) the owner may choose to pay.
    ability: tuple[str, int] | None = None

    @property
    def is_engine(self) -> bool:
        return self.group == config.GROUP_ENGINE

    @property
    def is_instant(self) -> bool:
        return self.group == config.GROUP_INSTANT

    @property
    def is_conditional(self) -> bool:
        return self.group == config.GROUP_CONDITIONAL

    @property
    def is_activated(self) -> bool:
        return self.group == config.GROUP_ACTIVATED

    @property
    def ability_kind(self) -> str | None:
        return self.ability[0] if self.ability else None

    @property
    def ability_cost(self) -> int:
        return self.ability[1] if self.ability else 0

    @property
    def effect_kind(self) -> str | None:
        return self.effect[0] if self.effect else None

    @property
    def effect_amount(self) -> int:
        return self.effect[1] if self.effect else 0

    def requirement_met(self, placement: dict[str, int]) -> bool:
        """Does this round's placement satisfy the card's toad threshold?

        Cards with no requirement are always met. Placement maps area -> toads.
        """
        if self.requirement is None:
            return True
        area, minimum = self.requirement
        return placement.get(area, 0) >= minimum

    def describe(self) -> str:
        """One-line human summary, used by the UI and the simulator logs."""
        if self.is_engine:
            kind, amount = self.effect
            gate = ""
            if self.requirement:
                area, minimum = self.requirement
                gate = f"{minimum}+ in {area.title()}: "
            # Strength is a standing modifier, not a per-round payout.
            cadence = "" if kind == config.MILITARY_STRENGTH else " each round"
            return f"{gate}+{amount} {_amount_label(kind, amount)}{cadence}"
        if self.is_instant:
            kind, amount = self.effect
            return f"+{amount} {_amount_label(kind, amount)} immediately"
        if self.is_activated:
            kind, cost = self.ability
            if kind == "skip_feeding":
                return f"Any round: skip feeding for {cost} happiness"
            return f"{kind} for {cost} happiness"
        if self.is_conditional:
            metric, per, vp = self.conditional
            unit = _kind_label(metric)
            if per == 1:
                return f"{vp} VP per {_singular(unit)}"
            return f"{vp} VP per {per} {unit}"
        return f"{self.vp} VP"


def _kind_label(kind: str) -> str:
    return {
        config.MILITARY_STRENGTH: "military strength",
        config.WAR_TOKENS: "war tokens",
    }.get(kind, kind)


def _singular(word: str) -> str:
    return word[:-1] if word.endswith("s") else word


def _amount_label(kind: str, amount: int) -> str:
    """"1 toad" rather than "1 toads"."""
    label = _kind_label(kind)
    return _singular(label) if amount == 1 else label


def _build_cards() -> dict[str, Card]:
    built: dict[str, Card] = {}
    for card_id, spec in config.CARD_DEFS.items():
        built[card_id] = Card(
            id=card_id,
            name=spec["name"],
            group=spec["group"],
            vp=spec["vp"],
            development=spec.get("development", config.VILLAGE),
            requirement=spec.get("requirement"),
            effect=spec.get("effect"),
            conditional=spec.get("conditional"),
            ability=spec.get("ability"),
        )
    return built


CARDS: dict[str, Card] = _build_cards()

CARD_IDS: tuple[str, ...] = tuple(CARDS)


def get(card_id: str) -> Card:
    """Look up a card by id. Raises KeyError on an unknown id."""
    return CARDS[card_id]


def by_group(group: str) -> tuple[Card, ...]:
    return tuple(card for card in CARDS.values() if card.group == group)


def by_development(development: str) -> tuple[Card, ...]:
    return tuple(c for c in CARDS.values() if c.development == development)


def deck_composition(
    player_count: int, development: str | None = None
) -> list[str]:
    """The full multiset of card ids for a game of `player_count` players.

    Pass a development to get just that half of the deck; the game keeps the
    village and city decks separate and draws from whichever the round calls
    for. Unshuffled and in a stable order — the engine shuffles with the game
    seed so a given seed always produces the same deck.
    """
    copies = config.card_copies(player_count)
    deck: list[str] = []
    for card_id, card in CARDS.items():
        if development is not None and card.development != development:
            continue
        deck.extend([card_id] * copies[card.group])
    return deck


def deck_size(player_count: int, development: str | None = None) -> int:
    return len(deck_composition(player_count, development))
