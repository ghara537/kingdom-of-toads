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


# Settings whose value is a choice, not a quantity: shown by name rather than
# as a bare number in the "changed from the defaults" list.
ENUM_LABELS = {
    "bonus_mode": {
        config.BONUS_MODE_LADDER: "ladder",
        config.BONUS_MODE_TWO_PHASE: "two-phase",
    },
    "gold_mode": {
        config.GOLD_AUCTION_ONLY: "bids at auction only",
        config.GOLD_RECRUITS: "also recruits toads",
        config.GOLD_BUYS_FLIES: "also buys flies",
    },
}


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
    awards = [vp for vp in config.end_majorities(t).values() if vp]
    scores = ["the property you own", "the wars you win"]
    if t["vp_per_toad"]:
        scores.insert(0, f"every toad still alive at the end ({t['vp_per_toad']} VP each)")
    if awards:
        scores.append(
            f"{_plural(len(awards), 'one-off award')} for topping the table in "
            "toads, happiness, gold, flies and property"
        )

    order = (
        "There is no turn order in any simultaneous phase. The first player "
        "marker only sets who opens the bidding."
        if mode == config.AUCTION_MODE_LIVE else
        "There is no turn order at all. The auction sequences cards, never "
        "players."
    )
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
                "way to raise it is to leave toads resting — that is, not "
                "producing. More toads also means more mouths."
            ),
            _p(
                "Points come from " + ", ".join(scores[:-1])
                + f" and {scores[-1]}. "
                + (
                    "A toad is not itself worth points, so a big kingdom pays "
                    "through what it produces and the most-toads award rather "
                    "than by the head."
                    if not t["vp_per_toad"] else
                    "Toads are worth points by the head at this table as well."
                )
            ),
            _ul([
                "Everything you own is public: toads, flies, gold, happiness and cards.",
                "What is hidden is intention. Recruitment, bidding and placement "
                "are committed in secret and revealed together.",
                order,
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
                f"Happiness sits on a track from {config.HAPPINESS_MIN} to "
                f"{config.HAPPINESS_MAX}, so "
                f"{t['start_happiness']} starts you in the "
                f"{config.recruit_band(t['start_happiness'])[0]}–"
                f"{config.recruit_band(t['start_happiness'])[1]} recruitment "
                f"band at {_plural(config.recruit_cost(t['start_happiness']), 'fly', 'flies')} "
                "a toad."
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
            f"reveals together. You may take up to "
            f"{_plural(config.recruit_cap(t), 'toad')} a round, however they "
            "are paid for. The cap is on recruiting only: toads that arrive "
            "from a card or from the Rest majority are on top of it."
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
            f"This table trades gold for flies at {t['gold_per_fly']} gold each. "
            "Buying flies is its own action, taken whenever you like and settled "
            "immediately — it is not part of your secret commitment, and the "
            "flies are yours to spend on toads or to save for feeding. Toads "
            "themselves are still bought with flies."
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


def _rest_award(t: dict, rnd: int, rounds: int) -> str:
    """The Rest majority pays in happiness and toads together."""
    awards = config.majority_awards(config.REST, rnd, rounds, t)
    bits = [f"+{awards[config.HAPPINESS]} happy"]
    toads = awards.get(config.TOADS, 0)
    if toads:
        bits.append(f"+{_plural(toads, 'toad')}")
    return " ".join(bits)


def _placement(t: dict, rounds: int) -> dict:
    rows = []
    two_phase = t["bonus_mode"] == config.BONUS_MODE_TWO_PHASE
    for r in range(1, rounds + 1):
        war = config.war_award(r, rounds, t)
        label = f"Round {r}"
        if two_phase:
            phase = config.bonus_phase(r, rounds, t)
            label += f" ({phase})"
        rows.append([
            label,
            "+" + str(config.majority_awards(config.FIELDS, r, rounds, t)[config.FLIES]),
            "+" + str(config.majority_awards(config.MINE, r, rounds, t)[config.GOLD]),
            _rest_award(t, r, rounds),
            str(war["vp"]) + " VP",
            str(war["tribute"]) or "0",
        ])

    rates = config.production(t)
    blocks = [
        _p(
            "Everyone assigns every toad they own across the four areas in "
            "secret, then reveals. Each toad produces:"
        ),
        _table(
            ["Area", "Per toad"],
            [
                ["Fields", f"+{rates[config.FIELDS][config.FLIES]} flies"],
                ["Mine", f"+{rates[config.MINE][config.GOLD]} gold"],
                ["Rest", f"+{rates[config.REST][config.HAPPINESS]} happiness"],
                ["Military", "nothing — it fights the war"],
            ],
        ),
        _p(
            "Whoever has the most toads in Fields, Mine or Rest takes that area's "
            "bonus for the round — a flat amount, not per toad. A tie awards "
            "nothing to anyone, though everybody still collects their ordinary "
            "production. An area nobody staffs awards nothing."
        ),
        _p(
            "The Rest majority is the one that pays in two things: happiness "
            "and a free toad. The toad arrives after placement, so it works "
            "next round — but it eats at the end of this one."
        ),
        _p(
            "This table pays two-phase bonuses: one flat rate through the "
            "village rounds and a bigger one from the first city round on, "
            "turning on the same round the deck does."
            if two_phase else
            "This table pays ladder bonuses: every round is worth a little "
            "more than the last."
        ),
        _table(
            ["", "Fields", "Mine", "Rest", "War token", "Tribute"], rows),
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
    tributes = sorted({
        config.war_award(r, rounds, t)["tribute"]
        for r in range(1, rounds + 1)
    })
    if any(tributes):
        if len(tributes) == 1:
            lead = (f"Every other player also hands the winner {tributes[0]} "
                    "gold or flies")
        else:
            spread = (
                f"{tributes[0]} in the village rounds and {tributes[-1]} in "
                "the city rounds" if two_phase
                else f"{tributes[0]}–{tributes[-1]}, by the round"
            )
            lead = ("Every other player also hands the winner gold or flies — "
                    + spread)
        war.append(
            lead + ", their choice which, made after the war is decided and "
            "the round's income is in. Short on the resource you chose and the "
            "balance comes out of the other."
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
            "or none of it. It may be played in any round, but only once: using "
            "it consumes the card. The card itself stays on the table, keeping "
            "its victory points and still counting as property for anything "
            "that scores off cards held."
        ))
    if t["gold_mode"] == config.GOLD_BUYS_FLIES:
        blocks.append(_p(
            f"Gold buys flies here too, at {t['gold_per_fly']} gold each — the "
            "only way a full purse can save a starving kingdom. As in "
            "recruitment it is its own action, settled before you commit how "
            "many toads to keep."
        ))

    # What a cull actually costs depends on how the table scores.
    awards = config.end_majorities(t)
    costs = []
    if t["vp_per_toad"]:
        costs.append(f"{t['vp_per_toad']} VP a head")
    if awards.get(config.TOADS):
        costs.append(
            f"your claim on the {awards[config.TOADS]} VP most-toads award"
        )
    if costs:
        text = (
            "Starving toads is a real decision in the last round. It costs "
            + " and ".join(costs) + ", on top of the happiness."
        )
        if awards.get(config.FLIES):
            text += (
                " What it buys is the flies they would have eaten, which count "
                f"toward the {awards[config.FLIES]} VP most-flies award — so the "
                "cull is a straight trade between two awards."
            )
        blocks.append(_p(text))
    return {"heading": "Phase 4 — Feeding", "blocks": blocks}


def _war_token_value(t: dict, rounds: int) -> str:
    """What a war token is worth, however this table shapes its bonuses."""
    values = [config.war_award(r, rounds, t)["vp"] for r in range(1, rounds + 1)]
    low, high = min(values), max(values)
    if low == high:
        return f"{low} VP, whichever round it was won in"
    if t["bonus_mode"] == config.BONUS_MODE_TWO_PHASE:
        return f"{low} VP from a village round, {high} VP from a city round"
    return f"{low}–{high} VP, by the round it was won in"


def _scoring(t: dict, rounds: int) -> dict:
    rows = [
        ["Each surviving toad",
         f"{t['vp_per_toad']} VP" if t["vp_per_toad"]
         else "nothing per head — see the most-toads award"],
        ["Each war token", _war_token_value(t, rounds)],
        ["Property cards", "as printed"],
        ["Gold, flies, happiness", "nothing per unit"],
    ]
    labels = {
        config.TOADS: "Most toads",
        config.HAPPINESS: "Most happiness",
        config.GOLD: "Most gold",
        config.FLIES: "Most flies",
        config.CARDS: "Most property cards",
    }
    awards = config.end_majorities(t)
    majorities = [
        f"{labels[metric]} — {vp} VP"
        for metric, vp in awards.items() if vp
    ]
    switched_off = [labels[m] for m, vp in awards.items() if not vp]
    blocks = [
        _p("Scored after the final round's feeding."),
        _table(["Source", "Value"], rows),
        _p(
            f"{_plural(len(majorities), 'one-off award')}, each to a single "
            "leader. A tie awards nothing, and none of them is counted before "
            "the final feeding — they are not part of the running score you "
            "see during the game:"
        ),
        _ul(majorities),
    ]
    if switched_off:
        blocks.append(_p(
            "Switched off at this table: " + ", ".join(switched_off) + "."
        ))
    blocks.append(_p(
        "Tie-breakers, in order: most victory points, then most toads, "
        "then highest happiness. Still level is a shared win."
    ))
    return {"heading": "Scoring", "blocks": blocks}


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
        "victory points — including a card whose effect has already been used "
        "up, which still scores and still counts as property. Engine cards "
        "fire every placement phase while their toad threshold is met; "
        "instants fire once, when bought; activated cards are used when their "
        "owner chooses, once per copy for the whole game."
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
    changed = []
    for key, label, _help, default, _lo, _hi, _group in config.TUNING_FIELDS:
        if t[key] == default:
            continue
        names = ENUM_LABELS.get(key, {})
        changed.append({
            "label": label,
            "value": t[key],
            "default": default,
            # Present only for the settings that name a choice.
            "value_label": names.get(t[key]),
            "default_label": names.get(default),
        })
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
            _scoring(t, rounds),
            _deck(t, players),
        ],
    }
