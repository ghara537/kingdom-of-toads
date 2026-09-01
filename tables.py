"""Kingdom of Toads — tables, seats and the bot driver.

The session layer between the pure engine and the web server. It knows about
seats, join codes and tokens; it knows nothing about HTTP or WebSockets.

Persistence, phase timers and host controls arrive in the next step; the
``_touch`` and ``save``/``load`` hooks below are where they will land.
"""

from __future__ import annotations

import random
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Any

import bots
import config
import engine
import storage as storage_lib

LOBBY = "lobby"
IN_PROGRESS = "in_progress"
FINISHED = "finished"

HUMAN = "human"
BOT = "bot"

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1


class TableError(Exception):
    """Something the caller did wrong: bad code, taken seat, wrong phase."""


def make_code(length: int = config.JOIN_CODE_LENGTH) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


@dataclass
class Seat:
    index: int
    player_id: str          # the engine's id for this seat: p1, p2, ...
    name: str
    kind: str = HUMAN       # HUMAN or BOT
    strategy: str | None = None
    token: str | None = None
    claimed: bool = False
    connections: int = 0

    @property
    def connected(self) -> bool:
        return self.connections > 0

    def public(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "player_id": self.player_id,
            "name": self.name,
            "kind": self.kind,
            "strategy": self.strategy,
            "claimed": self.claimed,
            "connected": self.connected,
        }

    def to_dict(self) -> dict[str, Any]:
        """Everything needed to restore this seat, tokens included.

        The token has to survive a restart — it is the only thing that puts a
        returning player back in their own seat. ``connections`` deliberately
        does not: sockets do not survive a process restart.
        """
        return {
            "index": self.index,
            "player_id": self.player_id,
            "name": self.name,
            "kind": self.kind,
            "strategy": self.strategy,
            "token": self.token,
            "claimed": self.claimed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Seat:
        return cls(**data)


@dataclass
class KickVote:
    """The table deciding whether to hand a slow player's seat to a bot.

    A yes never needs storing: one is enough, and it resolves the vote on the
    spot. So ``declined`` is the whole tally — everyone who has said "keep
    waiting". One vote per late player, running independently.
    """

    subject: str
    eligible: list[str]
    deadline: float
    # The commitment round this was about. Once the phase moves on the question
    # is moot, even though the same player may owe a decision again straight
    # away in the next phase.
    phase_key: str | None = None
    declined: list[str] = field(default_factory=list)

    def seconds_left(self, now: float | None = None) -> float:
        return max(0.0, self.deadline - (time.time() if now is None else now))

    def public(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "eligible": list(self.eligible),
            "declined": list(self.declined),
            "seconds_left": self.seconds_left(),
        }


@dataclass
class Table:
    code: str
    host_token: str
    seats: list[Seat]
    rounds: int = config.ROUNDS
    auction_mode: str = config.AUCTION_MODE_DEFAULT
    # Per-table scoring and bonus values; see config.TUNING_FIELDS.
    tuning: dict[str, int] = field(default_factory=config.tuning_defaults)
    status: str = LOBBY
    state: engine.GameState | None = None
    seed: int | None = None
    timeout_seconds: int = config.PHASE_TIMEOUT_SECONDS
    # Wall-clock deadline for the phase in progress, so a timer survives a
    # process restart rather than living in a background task that dies with it.
    deadline: float | None = None
    phase_key: str | None = None
    # While paused, no phase timer runs and nobody can be voted out.
    paused: bool = False
    # Open kick votes, keyed by the player being voted on.
    votes: dict[str, KickVote] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # Set by the store; not part of the saved data. A plain attribute rather
    # than a callback so the persisted dict stays trivially serialisable.
    store: Any = field(default=None, repr=False, compare=False)

    # -- lookups ------------------------------------------------------------

    def seat_by_token(self, token: str | None) -> Seat | None:
        if not token:
            return None
        return next((s for s in self.seats if s.token == token), None)

    def seat_by_player(self, player_id: str) -> Seat:
        return next(s for s in self.seats if s.player_id == player_id)

    def is_host(self, token: str | None) -> bool:
        return bool(token) and token == self.host_token

    @property
    def bot_strategies(self) -> dict[str, str]:
        return {
            s.player_id: (s.strategy or bots.DEFAULT_STRATEGY)
            for s in self.seats
            if s.kind == BOT
        }

    @property
    def open_seats(self) -> list[Seat]:
        return [s for s in self.seats if s.kind == HUMAN and not s.claimed]

    # -- lifecycle ----------------------------------------------------------

    def join(self, name: str, seat_index: int | None = None) -> Seat:
        if self.status != LOBBY:
            raise TableError("this game has already started")
        candidates = self.open_seats
        if seat_index is not None:
            candidates = [s for s in candidates if s.index == seat_index]
            if not candidates:
                raise TableError("that seat is taken")
        if not candidates:
            raise TableError("the table is full")
        seat = candidates[0]
        seat.name = name.strip()[:20] or seat.name
        seat.claimed = True
        seat.token = secrets.token_urlsafe(16)
        self._touch()
        return seat

    def configure(
        self,
        rounds: int | None = None,
        auction_mode: str | None = None,
        seat_kinds: list[dict] | None = None,
        timeout_seconds: int | None = None,
        tuning: dict | None = None,
    ) -> None:
        if self.status != LOBBY:
            raise TableError("settings are locked once the game starts")
        if rounds is not None:
            self.rounds = max(1, min(20, int(rounds)))
        if timeout_seconds is not None:
            self.timeout_seconds = max(10, min(3600, int(timeout_seconds)))
        if tuning is not None:
            self.tuning = config.clean_tuning(tuning)
        if auction_mode is not None:
            if auction_mode not in (config.AUCTION_MODE_BLIND, config.AUCTION_MODE_LIVE):
                raise TableError("unknown auction mode")
            self.auction_mode = auction_mode
        for spec in seat_kinds or []:
            seat = self.seats[int(spec["index"])]
            if seat.claimed and seat.kind == HUMAN:
                continue  # never evict a seated human
            kind = spec.get("kind", seat.kind)
            if kind not in (HUMAN, BOT):
                raise TableError("unknown seat kind")
            seat.kind = kind
            if kind == BOT:
                strategy = spec.get("strategy") or bots.DEFAULT_STRATEGY
                if strategy not in bots.STRATEGIES:
                    raise TableError(f"unknown bot strategy: {strategy}")
                seat.strategy = strategy
                seat.name = spec.get("name") or f"{strategy.title()} bot"
            else:
                seat.strategy = None
        self._touch()

    def start(self) -> None:
        if self.status != LOBBY:
            raise TableError("the game is already under way")
        if any(s.kind == HUMAN and not s.claimed for s in self.seats):
            raise TableError("every human seat must be filled or set to a bot")
        self.seed = self.seed if self.seed is not None else random.randrange(2**31)
        self.state = engine.new_game(
            [(s.player_id, s.name) for s in self.seats],
            engine.Settings(
                rounds=self.rounds,
                auction_mode=self.auction_mode,
                tuning=dict(self.tuning),
            ),
            seed=self.seed,
        )
        self.status = IN_PROGRESS
        self.run_bots()
        self._touch()

    # -- play ---------------------------------------------------------------

    def act(self, player_id: str, action: dict) -> None:
        """Apply a human action, then let the bots catch up."""
        if self.status != IN_PROGRESS or self.state is None:
            raise TableError("the game is not running")
        self.state = engine.submit_action(self.state, player_id, action)
        # Acting is how you answer a vote about yourself.
        self.close_settled_votes()
        self.run_bots()
        self._touch()

    def run_bots(self) -> None:
        if self.state is None:
            return
        strategies = self.bot_strategies
        if strategies:
            self.state = bots.play_out(self.state, strategies, random.Random())
        if self.state.finished:
            self.status = FINISHED
            self.deadline = None
        self.refresh_deadline()
        self._touch()

    def set_seat_kind(self, index: int, kind: str, strategy: str | None = None) -> Seat:
        """Host control: hand a seat to a bot for good, or hand it back.

        Used when someone leaves permanently. Unlike a phase timeout, this
        sticks — but the seat token is kept, so if they do come back the host
        can flip it to human again and their link still works.
        """
        if not 0 <= index < len(self.seats):
            raise TableError("no such seat")
        if kind not in (HUMAN, BOT):
            raise TableError("unknown seat kind")
        seat = self.seats[index]
        if kind == BOT:
            strategy = strategy or seat.strategy or bots.DEFAULT_STRATEGY
            if strategy not in bots.STRATEGIES:
                raise TableError(f"unknown bot strategy: {strategy}")
            seat.strategy = strategy
        seat.kind = kind
        if self.status == IN_PROGRESS:
            self.close_settled_votes()
            self.run_bots()   # the new bot may owe a decision right now
        self._touch()
        return seat

    # -- phase timers -------------------------------------------------------

    def _current_phase_key(self) -> str | None:
        """Identifies one commitment round, so a timer resets exactly once.

        Deliberately excludes who is still pending: a shared phase deadline
        must not restart every time one player commits. Live auctions do turn
        on whose turn it is, so the turn is part of the key there.
        """
        if self.state is None:
            return None
        auction = self.state.auction
        parts = [str(self.state.round), self.state.phase]
        if auction is not None and self.state.phase == engine.PHASE_AUCTION:
            parts += [str(auction.index), auction.stage, str(auction.turn)]
        return ":".join(parts)

    def refresh_deadline(self, now: float | None = None) -> None:
        """Start a fresh timer when a new commitment round opens."""
        now = time.time() if now is None else now
        if self.status != IN_PROGRESS or self.state is None:
            self.deadline = None
            self.phase_key = None
            return
        if self.paused or self.votes:
            # Paused, or the table is already deciding what to do about
            # someone: either way the phase clock does not run.
            self.deadline = None
            return
        pending = engine.pending_players(self.state)
        humans = [p for p in pending if self.seat_by_player(p).kind == HUMAN]
        key = self._current_phase_key()
        if not humans:
            # Only bots outstanding: they act immediately, so there is nothing
            # to wait for and no timer to run.
            self.deadline = None
            self.phase_key = key
            return
        if key != self.phase_key or self.deadline is None:
            self.phase_key = key
            self.deadline = now + self.timeout_seconds

    def seconds_left(self, now: float | None = None) -> float | None:
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - (time.time() if now is None else now))

    def expired(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return self.deadline is not None and now >= self.deadline

    def needs_tick(self, now: float | None = None) -> bool:
        """Cheap filter so the sweeper skips tables with nothing to do."""
        if self.status != IN_PROGRESS:
            return False
        now = time.time() if now is None else now
        return (
            self.expired(now)
            or any(now >= v.deadline for v in self.votes.values())
            or (self.paused and self.deadline is not None)
        )

    def restart_phase_timer(self, now: float | None = None) -> None:
        """Give the current phase a clean, full-length clock."""
        self.phase_key = None
        self.deadline = None
        self.refresh_deadline(now)

    def set_paused(self, paused: bool, by: str | None = None) -> None:
        """Stop the clock. Nobody can be voted out while a table is paused."""
        if self.paused == paused:
            return
        self.paused = paused
        if paused:
            self.votes.clear()
        if self.state is not None:
            who = self.seat_by_player(by).name if by else "The table"
            engine.note(
                self.state,
                "paused" if paused else "resumed",
                f"{who} {'paused' if paused else 'resumed'} the game."
                + (" Timers are off." if paused else ""),
                player=by,
            )
        self.restart_phase_timer()
        self._touch()

    # -- kick votes ---------------------------------------------------------

    def voters_for(self, subject: str) -> list[str]:
        """Human seats entitled to vote on someone: everyone but them."""
        return [
            s.player_id
            for s in self.seats
            if s.kind == HUMAN and s.claimed and s.player_id != subject
        ]

    def open_kick_votes(self, now: float | None = None) -> list[str]:
        """Ask the table about everyone currently holding the phase up.

        One vote per late player, so two people going quiet produce two
        separate questions rather than one muddled one. If there is nobody to
        ask — a solo game against bots — no vote opens and the table simply
        keeps waiting.
        """
        now = time.time() if now is None else now
        if self.status != IN_PROGRESS or self.state is None or self.paused:
            return []
        opened = []
        for pid in engine.pending_players(self.state):
            seat = self.seat_by_player(pid)
            if seat.kind != HUMAN or pid in self.votes:
                continue
            voters = self.voters_for(pid)
            if not voters:
                continue
            self.votes[pid] = KickVote(
                subject=pid,
                eligible=voters,
                deadline=now + config.KICK_VOTE_SECONDS,
                phase_key=self._current_phase_key(),
            )
            opened.append(pid)
            engine.note(
                self.state,
                "kick_vote",
                f"{seat.name} has gone quiet. The table is deciding whether to "
                "hand their seat to a bot.",
                player=pid,
            )
        if opened:
            self.deadline = None    # hold the phase clock while they decide
        else:
            self.restart_phase_timer(now)
        self._touch()
        return opened

    def cast_vote(self, voter: str, subject: str, kick: bool) -> str:
        """Record one vote. Returns 'kicked', 'kept' or 'noted'."""
        vote = self.votes.get(subject)
        if vote is None:
            raise TableError("there is no open vote for that seat")
        if voter not in vote.eligible:
            raise TableError("you are not eligible to vote on that seat")

        if kick:
            # One yes is enough: the table has someone who wants to move on.
            del self.votes[subject]
            seat = self.seat_by_player(subject)
            engine.note(
                self.state,
                "kicked",
                f"{seat.name}'s seat was handed to a bot "
                f"({self.seat_by_player(voter).name} called it).",
                player=subject,
                by=voter,
            )
            self.set_seat_kind(seat.index, BOT)
            self.restart_phase_timer()
            return "kicked"

        if voter not in vote.declined:
            vote.declined.append(voter)
        if self._settled(vote):
            del self.votes[subject]
            engine.note(
                self.state,
                "kick_declined",
                f"The table gave {self.seat_by_player(subject).name} more time.",
                player=subject,
            )
            self.restart_phase_timer()
            self._touch()
            return "kept"
        self._touch()
        return "noted"

    def _settled(self, vote: KickVote) -> bool:
        """True once everyone who could answer has said 'keep waiting'.

        Only voters who are actually connected are counted, so one absent
        player cannot leave a question hanging for the people who are here.
        """
        present = [
            pid for pid in vote.eligible if self.seat_by_player(pid).connected
        ]
        answerable = present or vote.eligible
        return bool(vote.declined) and all(p in vote.declined for p in answerable)

    def close_settled_votes(self) -> bool:
        """Drop votes about players who have since acted, or become bots."""
        if self.state is None:
            return False
        pending = engine.pending_players(self.state)
        key = self._current_phase_key()
        stale = [
            subject
            for subject, vote in self.votes.items()
            if subject not in pending
            or vote.phase_key != key          # the phase moved on without them
            or self.seat_by_player(subject).kind != HUMAN
        ]
        for subject in stale:
            del self.votes[subject]
            engine.note(
                self.state,
                "kick_cancelled",
                f"{self.seat_by_player(subject).name} is back — vote cancelled.",
                player=subject,
            )
        if stale:
            self.restart_phase_timer()
        return bool(stale)

    def tick(self, now: float | None = None) -> bool:
        """One pass of the clock. Returns True if anything changed."""
        now = time.time() if now is None else now
        if self.status != IN_PROGRESS or self.state is None:
            return False
        changed = self.close_settled_votes()
        if self.paused:
            if self.deadline is not None:
                self.deadline = None
                changed = True
            return changed
        for subject, vote in list(self.votes.items()):
            if now >= vote.deadline:
                del self.votes[subject]
                engine.note(
                    self.state,
                    "kick_lapsed",
                    f"Nobody called it on {self.seat_by_player(subject).name} — "
                    "the table keeps waiting.",
                    player=subject,
                )
                self.restart_phase_timer(now)
                changed = True
        if self.expired(now):
            self.open_kick_votes(now)
            changed = True
        if changed:
            self._touch()
        return changed

    # -- persistence --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "host_token": self.host_token,
            "seats": [s.to_dict() for s in self.seats],
            "rounds": self.rounds,
            "auction_mode": self.auction_mode,
            "status": self.status,
            "seed": self.seed,
            "timeout_seconds": self.timeout_seconds,
            "tuning": dict(self.tuning),
            "deadline": self.deadline,
            "phase_key": self.phase_key,
            "paused": self.paused,
            # Open votes are deliberately not saved: after a restart the phase
            # clock starts fresh, so any question the table was answering is
            # moot and would only be confusing to restore.
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "state": engine.serialize(self.state) if self.state else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Table:
        state = data.get("state")
        return cls(
            code=data["code"],
            host_token=data["host_token"],
            seats=[Seat.from_dict(s) for s in data["seats"]],
            rounds=data["rounds"],
            auction_mode=data["auction_mode"],
            status=data["status"],
            state=engine.deserialize(state) if state else None,
            seed=data.get("seed"),
            timeout_seconds=data.get("timeout_seconds", config.PHASE_TIMEOUT_SECONDS),
            tuning=config.clean_tuning(data.get("tuning")),
            deadline=data.get("deadline"),
            phase_key=data.get("phase_key"),
            paused=data.get("paused", False),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )

    def view_for(self, token: str | None) -> dict[str, Any] | None:
        """The per-seat view. Unknown tokens get the spectator view."""
        if self.state is None:
            return None
        seat = self.seat_by_token(token)
        return engine.player_view(self.state, seat.player_id if seat else None)

    def public(self, token: str | None = None) -> dict[str, Any]:
        seat = self.seat_by_token(token)
        return {
            "code": self.code,
            "status": self.status,
            "rounds": self.rounds,
            "auction_mode": self.auction_mode,
            "seats": [s.public() for s in self.seats],
            "you": seat.player_id if seat else None,
            "your_seat": seat.index if seat else None,
            "is_host": self.is_host(token),
            "strategies": sorted(bots.STRATEGIES),
            "timeout_seconds": self.timeout_seconds,
            "tuning": dict(self.tuning),
            # Seconds rather than a timestamp, so the client counts down from
            # when the message arrived and clock skew never matters.
            "seconds_left": self.seconds_left(),
            "paused": self.paused,
            "votes": [v.public() for v in self.votes.values()],
        }

    def _touch(self) -> None:
        self.updated_at = time.time()
        if self.store is not None:
            self.store.save(self)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class TableStore:
    """In-memory registry, written through to disk after every change.

    Memory is the read path; disk exists so a restart does not destroy every
    game in progress. Pass ``storage=None`` for a purely in-memory store.
    """

    def __init__(self, storage: storage_lib.TableStorage | None = ...) -> None:
        self.tables: dict[str, Table] = {}
        self.storage = (
            storage_lib.TableStorage() if storage is ... else storage
        )

    # -- persistence --------------------------------------------------------

    def save(self, table: Table) -> None:
        if self.storage is not None:
            self.storage.save(table.to_dict())

    def load(self) -> int:
        """Restore saved tables at startup. Returns how many came back."""
        if self.storage is None:
            return 0
        for data in self.storage.load_all():
            try:
                table = Table.from_dict(data)
            except (KeyError, TypeError, ValueError):
                continue  # a file from an older schema: skip, do not crash
            # Sockets did not survive the restart, and the phase timer should
            # not punish players for the downtime.
            for seat in table.seats:
                seat.connections = 0
            if table.status == IN_PROGRESS:
                table.deadline = None
                table.phase_key = None
                table.refresh_deadline()
            table.store = self
            self.tables[table.code] = table
        return len(self.tables)

    def create(
        self,
        player_count: int,
        host_name: str,
        rounds: int = config.ROUNDS,
        auction_mode: str = config.AUCTION_MODE_DEFAULT,
        seat_kinds: list[dict] | None = None,
        seed: int | None = None,
        timeout_seconds: int | None = None,
        tuning: dict | None = None,
    ) -> tuple[Table, Seat]:
        if not config.MIN_PLAYERS <= player_count <= config.MAX_PLAYERS:
            raise TableError(
                f"player count must be {config.MIN_PLAYERS}-{config.MAX_PLAYERS}"
            )
        code = make_code()
        while code in self.tables:
            code = make_code()
        seats = [
            Seat(index=i, player_id=f"p{i + 1}", name=f"Seat {i + 1}")
            for i in range(player_count)
        ]
        table = Table(
            code=code,
            host_token=secrets.token_urlsafe(16),
            seats=seats,
            seed=seed,
        )
        self.tables[code] = table
        table.store = self
        table.configure(
            rounds=rounds,
            auction_mode=auction_mode,
            seat_kinds=seat_kinds,
            timeout_seconds=timeout_seconds,
            tuning=tuning,
        )
        host_seat = table.join(host_name, seat_index=0)
        return table, host_seat

    def get(self, code: str) -> Table:
        table = self.tables.get((code or "").strip().upper())
        if table is None:
            raise TableError("no table with that code")
        return table

    def cleanup(self, max_age_hours: float = config.TABLE_IDLE_CLEANUP_HOURS) -> int:
        """Drop tables with no activity for a day, from memory and from disk."""
        cutoff = time.time() - max_age_hours * 3600
        stale = [c for c, t in self.tables.items() if t.updated_at < cutoff]
        for code in stale:
            del self.tables[code]
            if self.storage is not None:
                self.storage.delete(code)
        return len(stale)
