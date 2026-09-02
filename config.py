"""Kingdom of Toads — every tunable number in the game.

Single source of balance truth. No game logic lives here beyond the small pure
lookup helpers at the bottom, which exist so that retuning a band or a curve
never requires touching engine.py.

Rules reference: DESIGN.md v1.0.
"""

from __future__ import annotations

import math
import os

# ---------------------------------------------------------------------------
# Areas and resources — string keys used throughout the codebase
# ---------------------------------------------------------------------------

FIELDS = "fields"
MINE = "mine"
MILITARY = "military"
REST = "rest"

AREAS = (FIELDS, MINE, MILITARY, REST)

# Areas that award a majority bonus (Military awards the war token instead).
MAJORITY_AREAS = (FIELDS, MINE, REST)

FLIES = "flies"
GOLD = "gold"
HAPPINESS = "happiness"
TOADS = "toads"
MILITARY_STRENGTH = "military_strength"
WAR_TOKENS = "war_tokens"
CARDS = "cards"            # conditional-scoring metric: property held

# ---------------------------------------------------------------------------
# Game structure
# ---------------------------------------------------------------------------

ROUNDS = 6                      # DESIGN §8: 6 to start, expect to test 6-10
MIN_PLAYERS = 2
MAX_PLAYERS = 6

# ---------------------------------------------------------------------------
# Starting setup — DESIGN §2
# ---------------------------------------------------------------------------

START_FLIES = 10
START_GOLD = 10
START_TOADS = 2
START_HAPPINESS = 10

# ---------------------------------------------------------------------------
# Happiness track — DESIGN §4
# ---------------------------------------------------------------------------

HAPPINESS_MIN = 1               # floors at 1; zero is unreachable
HAPPINESS_MAX = 20              # excess is forfeited

# (low, high, flies per toad) — inclusive bounds, must cover HAPPINESS_MIN..MAX
RECRUIT_COST_BANDS = (
    (16, 20, 1),
    (11, 15, 2),
    (6, 10, 3),
    (1, 5, 4),
)

# ---------------------------------------------------------------------------
# Phase 1 — recruitment
# ---------------------------------------------------------------------------

RECRUIT_CAP = 4                 # per player per round; toad instants bypass it

# Off by default. When switched on, a toad may be bought with gold instead of
# flies at a flat price that ignores the happiness band — which deliberately
# breaks the resource separation in DESIGN.md §3, so it is opt-in.
RECRUIT_WITH_GOLD = 0
RECRUIT_GOLD_COST = 3

# ---------------------------------------------------------------------------
# Phase 2 — auction
# ---------------------------------------------------------------------------

AUCTION_MODE_BLIND = "blind"
AUCTION_MODE_LIVE = "live"
AUCTION_MODE_DEFAULT = AUCTION_MODE_BLIND

AUCTION_MIN_BID = 3             # any bid above a pass must be at least this
AUCTION_ELIGIBILITY = 3         # gold you must hold to bid at all
AUCTION_TIE_PENALTY = 3         # gold paid by each player in a double tie
AUCTION_REBIDS = 1              # blind-mode re-bids before the card burns
AUCTION_LIVE_MIN_RAISE = 1      # live mode only

# Cards revealed per round = player count * this.
AUCTION_CARDS_PER_PLAYER = 1

# A card nobody bids on is removed from the game (ruling 12), same as a card
# burned by a double tie. Set False to return it to the bottom of the deck.
AUCTION_BURN_UNSOLD = True

# ---------------------------------------------------------------------------
# Phase 3 — production, majorities, war
# ---------------------------------------------------------------------------

# Per toad placed, per round. Military produces nothing.
PRODUCTION = {
    FIELDS: {FLIES: 2},
    MINE: {GOLD: 2},
    REST: {HAPPINESS: 1},
    MILITARY: {},
}

# Majority bonus = ceil((BASE + PER_ROUND * round) / DIVISOR). Flat for the
# round, not per toad. Fields/Mine: round + 1. Rest: ceil(round / 2).
MAJORITY_BONUS_CURVES = {
    FIELDS: {"resource": FLIES, "base": 1, "per_round": 1, "divisor": 1},
    MINE: {"resource": GOLD, "base": 1, "per_round": 1, "divisor": 1},
    REST: {"resource": HAPPINESS, "base": 0, "per_round": 1, "divisor": 2},
}

# A majority needs at least this many toads to be awarded at all (ruling 10):
# an all-zero area awards nothing. Ties award nothing either way.
MAJORITY_MIN_TOADS = 1

# War token VP = WAR_TOKEN_VP_BASE + WAR_TOKEN_VP_PER_ROUND * round
WAR_TOKEN_VP_BASE = 1
WAR_TOKEN_VP_PER_ROUND = 1

# Happiness lost by every non-winner — but only if the war HAS a winner.
WAR_LOSS_PENALTY = 1

# Gold or flies each non-winner hands to the war's winner, again only if the
# war had a winner. The payer chooses which resource; see engine._pay_tribute.
WAR_TRIBUTE = 1

# Happiness lost by a player who put nobody in Rest this round. A standing
# pressure on the track, so holding station costs something.
REST_EMPTY_PENALTY = 1

# Minimum military strength needed to win the war (ruling 10).
WAR_MIN_STRENGTH = 1

# Barracks / War College strength only counts if the owner has at least this
# many toads in Military (ruling 8). Set to 0 to let cards fight alone.
WAR_STRENGTH_CARD_MIN_TOADS = 1

# ---------------------------------------------------------------------------
# Phase 4 — feeding
# ---------------------------------------------------------------------------

FEED_COST = 1                   # flies per toad kept alive
STARVE_HAPPINESS_COST = 1       # happiness per toad returned to supply

# ---------------------------------------------------------------------------
# Scoring — DESIGN §7
# ---------------------------------------------------------------------------

VP_PER_TOAD = 1
VP_PER_GOLD = 0
VP_PER_HAPPINESS = 0
VP_PER_FLY = 0

# War token VP is per the round it was won in; see war_token_vp().

# One-off 5 VP awards checked after the final feeding. Ties award nothing.
END_MAJORITIES = {
    HAPPINESS: 5,
    GOLD: 5,
    FLIES: 5,
}

# Applied in order; first difference wins. Higher is better for all three.
TIEBREAK_ORDER = ("victory_points", TOADS, HAPPINESS)

# ---------------------------------------------------------------------------
# Deck composition — DESIGN §6
# ---------------------------------------------------------------------------

# Development stage. Village cards fill the early rounds, city cards the late
# ones, so the deck escalates with the game instead of shuffling flat.
VILLAGE = "village"
CITY = "city"
DEVELOPMENTS = (VILLAGE, CITY)

GROUP_ENGINE = "engine"
GROUP_ACTIVATED = "activated"   # permanent, but its ability is a choice
GROUP_INSTANT = "instant"
GROUP_FLAT = "flat"
GROUP_CONDITIONAL = "conditional"

# Player counts at or below this use the low-count deck (2 copies of all).
LOW_COUNT_MAX_PLAYERS = 3

CARD_COPIES_HIGH_COUNT = {      # 4-6 players
    GROUP_ENGINE: 3,
    GROUP_ACTIVATED: 3,
    GROUP_INSTANT: 3,
    GROUP_FLAT: 3,
    GROUP_CONDITIONAL: 2,
}

CARD_COPIES_LOW_COUNT = {       # 2-3 players
    GROUP_ENGINE: 2,
    GROUP_ACTIVATED: 2,
    GROUP_INSTANT: 2,
    GROUP_FLAT: 2,
    GROUP_CONDITIONAL: 2,
}

# ---------------------------------------------------------------------------
# Card definitions — DESIGN §6
#
# group        one of GROUP_*
# vp           printed victory points (conditional cards score 0 flat)
# requirement  (area, min_toads) gate on engine effects, or None
# effect       (kind, amount) — engine cards fire it every Phase 3 while the
#              requirement holds; instant cards fire it once on purchase
# conditional  (metric, per, vp) — floor(metric / per) * vp at final scoring
# ---------------------------------------------------------------------------

CARD_DEFS = {
    # --- Engine: fires every Phase 3 while the threshold is met -------------
    "fly_farm": {
        "name": "Fly Farm",
        "development": VILLAGE,
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": (FIELDS, 2),
        "effect": (FLIES, 2),
    },
    "great_marsh": {
        "name": "Great Marsh",
        "development": CITY,
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": (FIELDS, 3),
        "effect": (FLIES, 4),
    },
    "gold_seam": {
        "name": "Gold Seam",
        "development": VILLAGE,
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": (MINE, 2),
        "effect": (GOLD, 3),
    },
    "deep_vein": {
        "name": "Deep Vein",
        "development": CITY,
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": (MINE, 3),
        "effect": (GOLD, 5),
    },
    "lily_gardens": {
        "name": "Lily Gardens",
        "development": VILLAGE,
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": (REST, 1),
        "effect": (HAPPINESS, 2),
    },
    "barracks": {
        "name": "Barracks",
        "development": VILLAGE,
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": None,
        "effect": (MILITARY_STRENGTH, 1),
    },
    "war_college": {
        "name": "War College",
        "development": CITY,
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": None,
        "effect": (MILITARY_STRENGTH, 2),
    },

    # --- Instant: fires once, on purchase ----------------------------------
    "festival": {
        "name": "Festival",
        "development": CITY,
        "group": GROUP_INSTANT,
        "vp": 2,
        "effect": (HAPPINESS, 5),
    },
    "public_park": {
        "name": "Public Park",
        "development": VILLAGE,
        "group": GROUP_INSTANT,
        "vp": 2,
        "effect": (HAPPINESS, 3),
    },
    "granary": {
        "name": "Granary",
        "development": CITY,
        "group": GROUP_INSTANT,
        "vp": 2,
        "effect": (FLIES, 8),
    },
    "larder": {
        "name": "Larder",
        "development": VILLAGE,
        "group": GROUP_INSTANT,
        "vp": 2,
        "effect": (FLIES, 4),
    },
    "spawning_pool": {
        "name": "Spawning Pool",
        "development": CITY,
        "group": GROUP_INSTANT,
        "vp": 2,
        "effect": (TOADS, 3),
    },
    "tadpole_pond": {
        "name": "Tadpole Pond",
        "development": VILLAGE,
        "group": GROUP_INSTANT,
        "vp": 2,
        "effect": (TOADS, 1),
    },

    # --- Flat scoring: no effect -------------------------------------------
    "monument": {
        "name": "Monument",
        "development": VILLAGE,
        "group": GROUP_FLAT,
        "vp": 5,
    },
    "grand_monument": {
        "name": "Grand Monument",
        "development": CITY,
        "group": GROUP_FLAT,
        "vp": 10,
    },

    # --- Conditional scoring: evaluated once at final scoring ---------------
    "census": {
        "name": "Census",
        "development": CITY,
        "group": GROUP_CONDITIONAL,
        "vp": 0,
        "conditional": (TOADS, 2, 1),          # 1 VP per 2 toads
    },
    "treasury": {
        "name": "Treasury",
        "development": CITY,
        "group": GROUP_CONDITIONAL,
        "vp": 0,
        "conditional": (GOLD, 3, 1),           # 1 VP per 3 gold
    },
    "hall_of_victories": {
        "name": "Hall of Victories",
        "development": CITY,
        "group": GROUP_CONDITIONAL,
        "vp": 0,
        "conditional": (WAR_TOKENS, 1, 2),     # 2 VP per war token
    },
    "militia_post": {
        "name": "Militia Post",
        "development": VILLAGE,
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": (MILITARY, 1),
        "effect": (GOLD, 2),
    },
    "tadpole_nursery": {
        "name": "Tadpole Nursery",
        "development": VILLAGE,
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": (REST, 2),
        "effect": (TOADS, 1),
    },
    "mercenary_camp": {
        "name": "Mercenary Camp",
        "development": CITY,
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": (MILITARY, 2),
        "effect": (GOLD, 4),
    },

    # --- Activated: permanent, but the ability is a choice -----------------
    "austerity": {
        "name": "Austerity",
        "development": VILLAGE,
        "group": GROUP_ACTIVATED,
        "vp": 2,
        # (ability, cost): skip feeding this round for 5 happiness. Usable
        # every round, but the happiness floor makes it self-limiting.
        "ability": ("skip_feeding", 5),
    },

    "almshouse": {
        "name": "Almshouse",
        "development": VILLAGE,
        "group": GROUP_CONDITIONAL,
        "vp": 0,
        "conditional": (HAPPINESS, 3, 1),      # 1 VP per 3 happiness
    },
    "guildhall": {
        "name": "Guildhall",
        "development": CITY,
        "group": GROUP_CONDITIONAL,
        "vp": 0,
        "conditional": (CARDS, 2, 1),          # 1 VP per 2 property cards
    },
}

# ---------------------------------------------------------------------------
# Table / session tunables (used by the web layer, not by the engine)
# ---------------------------------------------------------------------------

# How long a phase waits before the table is asked whether to replace whoever
# is holding it up. Nobody is ever replaced automatically: this opens a vote.
PHASE_TIMEOUT_SECONDS = 120
# How long that vote stays open. If it lapses with no yes, the phase timer
# simply restarts and the table keeps waiting.
KICK_VOTE_SECONDS = 120
TABLE_IDLE_CLEANUP_HOURS = 24
JOIN_CODE_LENGTH = 5

# Where saved games are written. Override with KOT_DATA_DIR — on Render this
# should point at a mounted persistent disk (see render.yaml).
DATA_DIR = os.environ.get("KOT_DATA_DIR", "./data")

# Keep-alive. Render's free plan spins an instance down after roughly 15
# minutes without inbound traffic, so an open tab pings the server on a timer
# to hold it awake. Pinging stops once the player has been idle a while, so a
# tab left open overnight does not hold the instance up on its own.
KEEPALIVE_INTERVAL_SECONDS = 600        # ping this often while someone is here
KEEPALIVE_IDLE_LIMIT_SECONDS = 1800     # stop pinging after this much idleness
SPINDOWN_ESTIMATE_SECONDS = 900         # Render's idle window, for the UI clock

# ---------------------------------------------------------------------------
# Derived helpers — pure functions over the constants above.
# Kept here so that changing a curve or a band never touches engine.py.
# ---------------------------------------------------------------------------


def recruit_cost(happiness: int) -> int:
    """Flies per toad at the given happiness."""
    for low, high, cost in RECRUIT_COST_BANDS:
        if low <= happiness <= high:
            return cost
    raise ValueError(f"happiness {happiness} falls outside every cost band")


def recruit_band(happiness: int) -> tuple[int, int, int]:
    """The (low, high, cost) band containing the given happiness."""
    for band in RECRUIT_COST_BANDS:
        if band[0] <= happiness <= band[1]:
            return band
    raise ValueError(f"happiness {happiness} falls outside every cost band")


def majority_bonus(
    area: str, round_number: int, tuning: dict[str, int] | None = None
) -> tuple[str, int]:
    """(resource, amount) awarded for the majority in `area` this round."""
    t = tuning or TUNING_DEFAULTS
    raw = t[f"{area}_bonus_base"] + t[f"{area}_bonus_per_round"] * round_number
    divisor = max(1, t[f"{area}_bonus_divisor"])
    return MAJORITY_BONUS_CURVES[area]["resource"], math.ceil(raw / divisor)


def war_token_vp(round_number: int, tuning: dict[str, int] | None = None) -> int:
    """VP value of the war token won in `round_number`."""
    t = tuning or TUNING_DEFAULTS
    return t["war_token_base"] + t["war_token_per_round"] * round_number


# ---------------------------------------------------------------------------
# Per-table tuning
#
# These are the balance numbers a table can override at creation, so that two
# tables can run different values and a saved game keeps the values it was
# actually played with. Everything else in this file is a global default.
#
# Each field is (key, label, help, default, min, max, group).
# ---------------------------------------------------------------------------

TUNING_FIELDS = (
    ("start_flies", "Starting flies", "Flies every player begins with.",
     START_FLIES, 0, 60, "start"),
    ("start_gold", "Starting gold", "Gold every player begins with.",
     START_GOLD, 0, 60, "start"),
    ("start_toads", "Starting toads", "Toads every player begins with.",
     START_TOADS, 0, 20, "start"),
    ("start_happiness", "Starting happiness",
     f"Where the track starts, {HAPPINESS_MIN}-{HAPPINESS_MAX}.",
     START_HAPPINESS, HAPPINESS_MIN, HAPPINESS_MAX, "start"),

    ("recruit_with_gold", "Pay in gold",
     "1 allows toads to be bought with gold as well as flies; 0 is flies only. "
     "Off by default: it bypasses the happiness band entirely.",
     RECRUIT_WITH_GOLD, 0, 1, "recruit"),
    ("recruit_gold_cost", "Gold per toad",
     "Flat price, the same in every happiness band. Does nothing unless "
     "'Pay in gold' is on.",
     RECRUIT_GOLD_COST, 1, 30, "recruit"),

    ("auction_min_bid", "Minimum bid", "The smallest bid that is not a pass.",
     AUCTION_MIN_BID, 1, 30, "auction"),
    ("auction_eligibility", "Bid eligibility",
     "Gold you must hold to bid at all. Below this you are out of the auction.",
     AUCTION_ELIGIBILITY, 0, 30, "auction"),
    ("auction_tie_penalty", "Tie-off penalty",
     "Gold each player pays when a re-bid ties again and the card burns. "
     "Keep this at or below the minimum bid, or a tied player may not be able "
     "to cover it.",
     AUCTION_TIE_PENALTY, 0, 30, "auction"),

    ("vp_per_toad", "VP per toad", "Each toad alive after the final feeding.",
     VP_PER_TOAD, 0, 20, "scoring"),
    ("vp_most_happiness", "Most happiness", "One-off award. Ties give nobody anything.",
     END_MAJORITIES[HAPPINESS], 0, 50, "scoring"),
    ("vp_most_gold", "Most gold", "One-off award. Ties give nobody anything.",
     END_MAJORITIES[GOLD], 0, 50, "scoring"),
    ("vp_most_flies", "Most flies", "One-off award. Ties give nobody anything.",
     END_MAJORITIES[FLIES], 0, 50, "scoring"),

    ("fields_bonus_base", "Fields base", "Bonus = (base + step x round) / divisor, rounded up.",
     MAJORITY_BONUS_CURVES[FIELDS]["base"], 0, 20, "fields"),
    ("fields_bonus_per_round", "Fields step", "How much the bonus grows each round.",
     MAJORITY_BONUS_CURVES[FIELDS]["per_round"], 0, 10, "fields"),
    ("fields_bonus_divisor", "Fields divisor", "Divide by this to slow the curve down.",
     MAJORITY_BONUS_CURVES[FIELDS]["divisor"], 1, 10, "fields"),

    ("mine_bonus_base", "Mine base", "Bonus = (base + step x round) / divisor, rounded up.",
     MAJORITY_BONUS_CURVES[MINE]["base"], 0, 20, "mine"),
    ("mine_bonus_per_round", "Mine step", "How much the bonus grows each round.",
     MAJORITY_BONUS_CURVES[MINE]["per_round"], 0, 10, "mine"),
    ("mine_bonus_divisor", "Mine divisor", "Divide by this to slow the curve down.",
     MAJORITY_BONUS_CURVES[MINE]["divisor"], 1, 10, "mine"),

    ("rest_bonus_base", "Rest base", "Bonus = (base + step x round) / divisor, rounded up.",
     MAJORITY_BONUS_CURVES[REST]["base"], 0, 20, "rest"),
    ("rest_bonus_per_round", "Rest step", "How much the bonus grows each round.",
     MAJORITY_BONUS_CURVES[REST]["per_round"], 0, 10, "rest"),
    ("rest_bonus_divisor", "Rest divisor", "Divide by this to slow the curve down.",
     MAJORITY_BONUS_CURVES[REST]["divisor"], 1, 10, "rest"),
    ("rest_empty_penalty", "Empty Rest penalty",
     "Happiness lost by a player who puts nobody in Rest this round. 0 to switch off.",
     REST_EMPTY_PENALTY, 0, 10, "rest"),

    ("war_token_base", "War token base", "War token VP = base + step x round.",
     WAR_TOKEN_VP_BASE, 0, 20, "war"),
    ("war_token_per_round", "War token step", "How much the token grows each round.",
     WAR_TOKEN_VP_PER_ROUND, 0, 10, "war"),
    ("war_tribute", "Tribute per loser",
     "Gold or flies each non-winner pays the winner, their choice which. "
     "Only when the war has a winner. 0 to switch off.",
     WAR_TRIBUTE, 0, 10, "war"),
)

TUNING_DEFAULTS: dict[str, int] = {f[0]: f[3] for f in TUNING_FIELDS}
TUNING_BOUNDS: dict[str, tuple[int, int]] = {f[0]: (f[4], f[5]) for f in TUNING_FIELDS}


def tuning_defaults() -> dict[str, int]:
    return dict(TUNING_DEFAULTS)


def clean_tuning(raw: dict | None) -> dict[str, int]:
    """A complete, in-range tuning dict. Unknown keys and junk are dropped."""
    tuning = tuning_defaults()
    for key, value in (raw or {}).items():
        if key not in TUNING_DEFAULTS:
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        low, high = TUNING_BOUNDS[key]
        tuning[key] = max(low, min(high, number))
    return tuning


def end_majorities(tuning: dict[str, int] | None = None) -> dict[str, int]:
    t = tuning or TUNING_DEFAULTS
    return {
        HAPPINESS: t["vp_most_happiness"],
        GOLD: t["vp_most_gold"],
        FLIES: t["vp_most_flies"],
    }


def clamp_happiness(value: int) -> int:
    return max(HAPPINESS_MIN, min(HAPPINESS_MAX, value))


def city_from_round(rounds: int) -> int:
    """First round whose slate is drawn from the city deck.

    The village half rounds down, so a 6-round game turns at round 4 and an
    8-round game at round 5. Round 1 is always village.
    """
    return max(2, rounds // 2 + 1)


def development_for_round(round_number: int, rounds: int) -> str:
    return CITY if round_number >= city_from_round(rounds) else VILLAGE


def card_copies(player_count: int) -> dict[str, int]:
    """Copies per card group for the given player count."""
    if player_count <= LOW_COUNT_MAX_PLAYERS:
        return dict(CARD_COPIES_LOW_COUNT)
    return dict(CARD_COPIES_HIGH_COUNT)
