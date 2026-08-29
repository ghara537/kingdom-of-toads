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

GROUP_ENGINE = "engine"
GROUP_INSTANT = "instant"
GROUP_FLAT = "flat"
GROUP_CONDITIONAL = "conditional"

# Player counts at or below this use the low-count deck (2 copies of all).
LOW_COUNT_MAX_PLAYERS = 3

CARD_COPIES_HIGH_COUNT = {      # 4-6 players -> 51 cards
    GROUP_ENGINE: 3,
    GROUP_INSTANT: 3,
    GROUP_FLAT: 3,
    GROUP_CONDITIONAL: 2,
}

CARD_COPIES_LOW_COUNT = {       # 2-3 players -> 36 cards
    GROUP_ENGINE: 2,
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
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": (FIELDS, 2),
        "effect": (FLIES, 2),
    },
    "great_marsh": {
        "name": "Great Marsh",
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": (FIELDS, 3),
        "effect": (FLIES, 4),
    },
    "gold_seam": {
        "name": "Gold Seam",
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": (MINE, 2),
        "effect": (GOLD, 3),
    },
    "deep_vein": {
        "name": "Deep Vein",
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": (MINE, 3),
        "effect": (GOLD, 5),
    },
    "lily_gardens": {
        "name": "Lily Gardens",
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": (REST, 2),
        "effect": (HAPPINESS, 2),
    },
    "barracks": {
        "name": "Barracks",
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": None,
        "effect": (MILITARY_STRENGTH, 1),
    },
    "war_college": {
        "name": "War College",
        "group": GROUP_ENGINE,
        "vp": 2,
        "requirement": None,
        "effect": (MILITARY_STRENGTH, 2),
    },

    # --- Instant: fires once, on purchase ----------------------------------
    "festival": {
        "name": "Festival",
        "group": GROUP_INSTANT,
        "vp": 2,
        "effect": (HAPPINESS, 5),
    },
    "public_park": {
        "name": "Public Park",
        "group": GROUP_INSTANT,
        "vp": 2,
        "effect": (HAPPINESS, 3),
    },
    "granary": {
        "name": "Granary",
        "group": GROUP_INSTANT,
        "vp": 2,
        "effect": (FLIES, 8),
    },
    "larder": {
        "name": "Larder",
        "group": GROUP_INSTANT,
        "vp": 2,
        "effect": (FLIES, 5),
    },
    "spawning_pool": {
        "name": "Spawning Pool",
        "group": GROUP_INSTANT,
        "vp": 2,
        "effect": (TOADS, 3),
    },
    "tadpole_pond": {
        "name": "Tadpole Pond",
        "group": GROUP_INSTANT,
        "vp": 2,
        "effect": (TOADS, 2),
    },

    # --- Flat scoring: no effect -------------------------------------------
    "monument": {
        "name": "Monument",
        "group": GROUP_FLAT,
        "vp": 5,
    },
    "grand_monument": {
        "name": "Grand Monument",
        "group": GROUP_FLAT,
        "vp": 10,
    },

    # --- Conditional scoring: evaluated once at final scoring ---------------
    "census": {
        "name": "Census",
        "group": GROUP_CONDITIONAL,
        "vp": 0,
        "conditional": (TOADS, 2, 1),          # 1 VP per 2 toads
    },
    "treasury": {
        "name": "Treasury",
        "group": GROUP_CONDITIONAL,
        "vp": 0,
        "conditional": (GOLD, 3, 1),           # 1 VP per 3 gold
    },
    "hall_of_victories": {
        "name": "Hall of Victories",
        "group": GROUP_CONDITIONAL,
        "vp": 0,
        "conditional": (WAR_TOKENS, 1, 2),     # 2 VP per war token
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


def majority_bonus(area: str, round_number: int) -> tuple[str, int]:
    """(resource, amount) awarded for the majority in `area` this round."""
    curve = MAJORITY_BONUS_CURVES[area]
    raw = curve["base"] + curve["per_round"] * round_number
    return curve["resource"], math.ceil(raw / curve["divisor"])


def war_token_vp(round_number: int) -> int:
    """VP value of the war token won in `round_number`."""
    return WAR_TOKEN_VP_BASE + WAR_TOKEN_VP_PER_ROUND * round_number


def clamp_happiness(value: int) -> int:
    return max(HAPPINESS_MIN, min(HAPPINESS_MAX, value))


def card_copies(player_count: int) -> dict[str, int]:
    """Copies per card group for the given player count."""
    if player_count <= LOW_COUNT_MAX_PLAYERS:
        return dict(CARD_COPIES_LOW_COUNT)
    return dict(CARD_COPIES_HIGH_COUNT)
