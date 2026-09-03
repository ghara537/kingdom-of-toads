"""Kingdom of Toads — the rules, written out from a table's actual settings.

Everything here is derived. Change a tuning value and the text changes with
it, so a table can always be shown the rules it is really playing rather than
the ones the design document happens to describe.

No web dependencies: this builds plain data that the client renders.
"""

from __future__ import annotations

from typing import Any

import cards as card_lib
import config


def _p(text: str) -> dict:
    return {"kind": "p", "text": text}


def _ul(items: list[str]) -> dict:
    return {"kind": "ul", "items": items}


def _table(head: list[str], rows: list[list[Any]]) -> dict:
    return {"kind": "table", "head": head, "rows": [[str(c) for c in r] for r in rows]}


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one}" if n == 1 else f"{n} {many or one + 's'}"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _overview(t: dict, rounds: int, players: int, mode: str) -> dict:
    return {
        "heading": "The game",
        "blocks": [
            _p(
                f"A game for {config.MIN_PLAYERS}–{config.MAX_PLAYERS} players, "
                f"played over {rounds} rounds. Most victory points wins."
            ),
            _p(
                "Recruit toads, bid for property, put your toads to work, then "
                "feed them. Happiness sets what a toad costs to recruit, and the "
                "only way to raise it is to leave toads resting — that is, not "
                "producing. More toads also means more mouths."
            ),
            _ul([
                "Everything you own is public: toads, flies, gold, happiness and cards.",
                "What is hidden is intention. Recruitment, bidding and placement "
                "are committed in secret and revealed together.",
                "There is no turn order. The auction sequences cards, never players.",
            ]),
        ],
    }


def _setup(t: dict, players: int) -> dict:
    village = card_lib.deck_size(players, config.VILLAGE)
    city = card_lib.deck_size(players, config.CITY)
    return {
        "heading": "Setup",
        "blocks": [
            _p("Every player begins with:"),
            _table(
                ["Flies", "Gold", "Toads", "Happiness"],
                [[t["start_flies"], t["start_gold"], t["start_toads"],
                  t["start_happiness"]]],
            ),
            _p(
                f"The property deck holds {len(card_lib.CARDS)} types: "
                f"{village} village cards and {city} city cards at this player count."
            ),
        ],
    }


def _recruitment(t: dict) -> dict:
    mode = t["gold_mode"]
    head = ["Happiness", "Flies per toad"]
    rows = []
    for low, high, cost in sorted(config.RECRUIT_COST_BANDS, reverse=True):
        row = [f"{low}–{high}", cost]
        if mode == config.GOLD_RECRUITS:
            row.append(cost + t["recruit_gold_premium"])
        rows.append(row)
    if mode == config.GOLD_RECRUITS:
        head.append("Gold per toad")

    blocks = [
        _p(
            "Everyone secretly declares how many toads they are taking, then "
            f"reveals together. You may take up to {config.RECRUIT_CAP} a round."
        ),
        _p("What a toad costs depends on where you sit on the happiness track:"),
        _table(head, rows),
    ]

    if mode == config.GOLD_AUCTION_ONLY:
        blocks.append(_p(
            "Toads are paid for in flies only. Gold bids at auction and does "
            "nothing else."
        ))
    elif mode == config.GOLD_RECRUITS:
        blocks.append(_p(
            f"This table also lets you pay in gold, at {t['recruit_gold_premium']} "
            "more than the fly price for your band. One recruitment can be paid "
            "for both ways at once, and the cap still applies to the total."
        ))
    else:
        blocks.append(_p(
            f"This table trades gold for flies at {t['gold_per_fly']} gold each, "
            "when recruiting and again when feeding. Toads themselves are still "
            "bought with flies."
        ))
    blocks.append(_p(
        "New toads can work this round, and must be fed at the end of it. "
        "There is no limit on the toad supply."
    ))
    return {"heading": "Phase 1 — Recruitment", "blocks": blocks}


def _auction(t: dict, rounds: int, players: int, mode: str) -> dict:
    turn = config.city_from_round(rounds)
    blocks = [
        _p(
            f"{_plural(players * config.AUCTION_CARDS_PER_PLAYER, 'card')} come up "
            "each round, face-up together, auctioned one at a time in the order "
            "revealed."
        ),
        _p(
            f"Rounds 1–{turn - 1} deal from the village deck and rounds "
            f"{turn}–{rounds} from the city deck. Next round's slate is "
            "revealed as soon as this round's auction ends, so you place your "
            "toads already knowing what is coming up for sale."
        ),
        _ul([
            "Bids are paid in gold only.",
            f"Minimum bid {_plural(t['auction_min_bid'], 'gold', 'gold')}.",
            f"Hold fewer than {t['auction_eligibility']} gold and you cannot bid "
            "at all until you mine more.",
            "You may never bid more than you hold, and there is no limit on how "
            "many cards you may win.",
        ]),
    ]
    if mode == config.AUCTION_MODE_BLIND:
        blocks.append(_p(
            "Bids are sealed and revealed together. The highest bid takes the "
            "card and pays its own bid."
        ))
        blocks.append(_p(
            f"On a tie, those players get exactly {config.AUCTION_REBIDS} re-bid, "
            "which must be equal to or higher than the tied amount — so nobody is "
            "forced out by being unable to raise. Tie again and each pays "
            f"{_plural(t['auction_tie_penalty'], 'gold', 'gold')} and the card "
            "leaves the game."
        ))
    else:
        blocks.append(_p(
            "Open ascending bidding, starting with the first player marker and "
            f"raising by at least {config.AUCTION_LIVE_MIN_RAISE}, until all but "
            "one have passed. Ties cannot happen, so the tie rules never apply."
        ))
    blocks.append(_p("A card nobody bids on leaves the game."))
    return {"heading": "Phase 2 — Auction", "blocks": blocks}


def _placement(t: dict, rounds: int) -> dict:
    rows = []
    for r in range(1, rounds + 1):
        rows.append([
            f"Round {r}",
            "+" + str(config.majority_bonus(config.FIELDS, r, t)[1]),
            "+" + str(config.majority_bonus(config.MINE, r, t)[1]),
            "+" + str(config.majority_bonus(config.REST, r, t)[1]),
            str(config.war_token_vp(r, t)) + " VP",
        ])

    blocks = [
        _p(
            "Everyone assigns every toad they own across the four areas in "
            "secret, then reveals. Each toad produces:"
        ),
        _table(
            ["Area", "Per toad"],
            [
                ["Fields", f"+{config.PRODUCTION[config.FIELDS][config.FLIES]} flies"],
                ["Mine", f"+{config.PRODUCTION[config.MINE][config.GOLD]} gold"],
                ["Rest", f"+{config.PRODUCTION[config.REST][config.HAPPINESS]} happiness"],
                ["Military", "nothing — it fights the war"],
            ],
        ),
        _p(
            "Whoever has the most toads in Fields, Mine or Rest takes that area's "
            "bonus for the round — a flat amount, not per toad. A tie awards "
            "nothing to anyone, though everybody still collects their ordinary "
            "production. An area nobody staffs awards nothing."
        ),
        _table(["", "Fields", "Mine", "Rest", "War token"], rows),
    ]

    if t["rest_empty_penalty"]:
        blocks.append(_p(
            f"Put nobody in Rest and you lose {t['rest_empty_penalty']} happiness. "
            "A player with no toads at all is spared."
        ))

    war = [
        "Military strength is your toads in Military, plus any Barracks or War "
        f"College you own — but those cards only count with at least "
        f"{config.WAR_STRENGTH_CARD_MIN_TOADS} toad actually in Military.",
        "The most strength wins the war and takes that round's token.",
        f"Every other player loses {config.WAR_LOSS_PENALTY} happiness.",
    ]
    if t["war_tribute"]:
        war.append(
            f"Every other player also hands the winner {t['war_tribute']} gold or "
            "flies, their choice which, declared with their placement before the "
            "war resolves. Short on the resource you chose and the balance comes "
            "out of the other."
        )
    war.append(
        "A tied war awards no token and costs nobody anything — matching the "
        "leader exactly denies them the token and spares the whole table."
    )
    blocks.append(_p("The war:"))
    blocks.append(_ul(war))
    blocks.append(_p(
        f"Happiness runs {config.HAPPINESS_MIN}–{config.HAPPINESS_MAX} and stops "
        "at both ends; anything beyond is forfeited. It is applied once, after "
        "everything in this phase has been worked out."
    ))
    return {"heading": "Phase 3 — Placement", "blocks": blocks}


def _feeding(t: dict) -> dict:
    blocks = [
        _p(
            f"Every toad eats {_plural(config.FEED_COST, 'fly', 'flies')}. You "
            "choose how many to keep; the rest starve, return to the supply and "
            f"cost you {config.STARVE_HAPPINESS_COST} happiness each."
        ),
        _p("Feeding happens in the final round too, before scoring."),
    ]
    austerity = card_lib.get("austerity")
    if austerity.ability:
        blocks.append(_p(
            f"{austerity.name} (a property card) lets its owner skip feeding "
            f"entirely for {austerity.ability_cost} happiness — the whole kingdom "
            "or none of it."
        ))
    if t["gold_mode"] == config.GOLD_BUYS_FLIES:
        blocks.append(_p(
            f"Gold buys flies here too, at {t['gold_per_fly']} gold each, which is "
            "the only way a full purse can save a starving kingdom."
        ))
    return {"heading": "Phase 4 — Feeding", "blocks": blocks}


def _scoring(t: dict) -> dict:
    rows = [
        ["Each surviving toad", f"{t['vp_per_toad']} VP"],
        ["Each war token", "the round it was won in"],
        ["Property cards", "as printed"],
        ["Gold, flies, happiness", "nothing per unit"],
    ]
    majorities = [
        f"Most happiness — {t['vp_most_happiness']} VP",
        f"Most gold — {t['vp_most_gold']} VP",
        f"Most flies — {t['vp_most_flies']} VP",
    ]
    return {
        "heading": "Scoring",
        "blocks": [
            _p("Scored after the final round's feeding."),
            _table(["Source", "Value"], rows),
            _p("Three one-off awards, each to a single leader. A tie awards nothing:"),
            _ul(majorities),
            _p(
                "Tie-breakers, in order: most victory points, then most toads, "
                "then highest happiness. Still level is a shared win."
            ),
        ],
    }


def _deck(t: dict, players: int) -> dict:
    copies = config.card_copies(players)
    blocks = []
    for stage, label in ((config.VILLAGE, "Village — the early rounds"),
                         (config.CITY, "City — the late rounds")):
        rows = []
        for card in card_lib.by_development(stage):
            rows.append([
                card.name,
                card.group,
                card.describe(),
                f"{card.vp} VP" if card.vp else "—",
                copies[card.group],
            ])
        blocks.append(_p(label))
        blocks.append(_table(["Card", "Type", "Effect", "VP", "Copies"], rows))
    blocks.append(_p(
        "Every card you win is yours for the rest of the game and counts for "
        "victory points. Engine cards fire every placement phase while their "
        "toad threshold is met; instants fire once, when bought; activated "
        "cards are used at their owner's discretion."
    ))
    return {"heading": "The property deck", "blocks": blocks}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build(
    tuning: dict[str, int] | None = None,
    rounds: int = config.ROUNDS,
    players: int = 4,
    auction_mode: str = config.AUCTION_MODE_DEFAULT,
) -> dict[str, Any]:
    """The complete rules for one table's settings."""
    t = config.clean_tuning(tuning)
    changed = [
        {"label": label, "value": t[key], "default": default}
        for key, label, _help, default, _lo, _hi, _group in config.TUNING_FIELDS
        if t[key] != default
    ]
    return {
        "title": "Kingdom of Toads — the rules of this table",
        "summary": (
            f"{players} players · {rounds} rounds · "
            f"{auction_mode} auction · "
            + {
                config.GOLD_AUCTION_ONLY: "gold bids only",
                config.GOLD_RECRUITS: "gold may recruit",
                config.GOLD_BUYS_FLIES: "gold buys flies",
            }[t["gold_mode"]]
        ),
        "changed": changed,
        "sections": [
            _overview(t, rounds, players, auction_mode),
            _setup(t, players),
            _recruitment(t),
            _auction(t, rounds, players, auction_mode),
            _placement(t, rounds),
            _feeding(t),
            _scoring(t),
            _deck(t, players),
        ],
    }
