"""Kingdom of Toads — FastAPI server.

Server-authoritative in the strict sense: the client sends intents and receives
a per-seat view. Every action is validated against the engine before it touches
state, and no unrevealed commitment is ever sent to anyone but its owner.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import cards as card_lib
import config
import engine
import tables as table_lib

STATIC_DIR = Path(__file__).parent / "static"

store = table_lib.TableStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Reload saved games, then run the phase-timer sweeper."""
    restored = store.load()
    if restored:
        print(f"[kot] restored {restored} tables from {store.storage.path}")
    task = asyncio.create_task(sweeper())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Kingdom of Toads", lifespan=lifespan)

# One lock per table: a table mutates in one place at a time, so two players
# committing simultaneously can never interleave inside the engine.
_locks: dict[str, asyncio.Lock] = {}


def lock_for(code: str) -> asyncio.Lock:
    return _locks.setdefault(code, asyncio.Lock())


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------


class Connections:
    """Live sockets per table, each remembering which seat token it holds."""

    def __init__(self) -> None:
        self.by_code: dict[str, list[tuple[WebSocket, str | None]]] = {}

    def add(self, code: str, ws: WebSocket, token: str | None) -> None:
        self.by_code.setdefault(code, []).append((ws, token))

    def remove(self, code: str, ws: WebSocket) -> None:
        self.by_code[code] = [
            entry for entry in self.by_code.get(code, []) if entry[0] is not ws
        ]

    def for_code(self, code: str) -> list[tuple[WebSocket, str | None]]:
        return list(self.by_code.get(code, []))


connections = Connections()


# ---------------------------------------------------------------------------
# Phase timers
# ---------------------------------------------------------------------------

SWEEP_INTERVAL_SECONDS = 1.0
CLEANUP_EVERY_SECONDS = 600


async def tick_table(table: table_lib.Table) -> bool:
    """Advance one table's clocks and tell everyone if anything moved."""
    async with lock_for(table.code):
        changed = table.tick()
    if changed:
        await broadcast(table)
    return changed


async def sweeper() -> None:
    """One task for the whole process, driving every table's clock.

    Deadlines are wall-clock values stored on the table, so this loop can die
    with the process and restart without losing or corrupting a timer.
    """
    last_cleanup = time.time()
    while True:
        try:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            for table in list(store.tables.values()):
                if table.needs_tick():
                    await tick_table(table)
            if time.time() - last_cleanup > CLEANUP_EVERY_SECONDS:
                last_cleanup = time.time()
                store.cleanup()
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - never let the sweeper die
            continue


def payload_for(table: table_lib.Table, token: str | None) -> dict:
    return {
        "type": "state",
        "table": table.public(token),
        "view": table.view_for(token),
    }


async def broadcast(table: table_lib.Table) -> None:
    """Push a freshly computed view to every socket, each seeing only its own."""
    dead = []
    for ws, token in connections.for_code(table.code):
        try:
            await ws.send_json(payload_for(table, token))
        except Exception:
            dead.append(ws)
    for ws in dead:
        connections.remove(table.code, ws)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class SeatSpec(BaseModel):
    index: int
    kind: str = table_lib.HUMAN
    strategy: str | None = None
    name: str | None = None


class CreateTable(BaseModel):
    name: str = Field(default="Host", max_length=20)
    player_count: int = 4
    rounds: int = config.ROUNDS
    auction_mode: str = config.AUCTION_MODE_DEFAULT
    timeout_seconds: int = config.PHASE_TIMEOUT_SECONDS
    tuning: dict[str, int] = Field(default_factory=dict)
    seats: list[SeatSpec] = Field(default_factory=list)
    seed: int | None = None


class JoinTable(BaseModel):
    name: str = Field(default="Player", max_length=20)
    seat_index: int | None = None


class SeatControl(BaseModel):
    index: int
    kind: str
    strategy: str | None = None


def error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


@app.post("/api/tables")
async def create_table(body: CreateTable):
    try:
        table, seat = store.create(
            player_count=body.player_count,
            host_name=body.name,
            rounds=body.rounds,
            auction_mode=body.auction_mode,
            seat_kinds=[s.model_dump() for s in body.seats],
            seed=body.seed,
            timeout_seconds=body.timeout_seconds,
            tuning=body.tuning or None,
        )
    except table_lib.TableError as exc:
        return error(str(exc))
    return {
        "code": table.code,
        "token": seat.token,
        "host_token": table.host_token,
        "player_id": seat.player_id,
    }


@app.get("/api/tables/{code}")
async def get_table(code: str, token: str | None = None):
    try:
        table = store.get(code)
    except table_lib.TableError as exc:
        return error(str(exc), 404)
    return payload_for(table, token)


@app.post("/api/tables/{code}/join")
async def join_table(code: str, body: JoinTable):
    try:
        table = store.get(code)
        seat = table.join(body.name, body.seat_index)
    except table_lib.TableError as exc:
        return error(str(exc))
    await broadcast(table)
    return {"code": table.code, "token": seat.token, "player_id": seat.player_id}


@app.post("/api/tables/{code}/configure")
async def configure_table(code: str, body: CreateTable, token: str | None = None):
    try:
        table = store.get(code)
        if not table.is_host(token):
            return error("only the host can change settings", 403)
        table.configure(
            rounds=body.rounds,
            auction_mode=body.auction_mode,
            seat_kinds=[s.model_dump() for s in body.seats],
            timeout_seconds=body.timeout_seconds,
            tuning=body.tuning or None,
        )
    except table_lib.TableError as exc:
        return error(str(exc))
    await broadcast(table)
    return payload_for(table, token)


@app.post("/api/tables/{code}/seat")
async def set_seat(code: str, body: SeatControl, token: str | None = None):
    """Host control: hand a seat to a bot permanently, or hand it back."""
    try:
        table = store.get(code)
    except table_lib.TableError as exc:
        return error(str(exc), 404)
    if not table.is_host(token):
        return error("only the host can reassign a seat", 403)
    async with lock_for(code):
        try:
            table.set_seat_kind(body.index, body.kind, body.strategy)
        except table_lib.TableError as exc:
            return error(str(exc))
    await broadcast(table)
    return {"ok": True}


@app.post("/api/tables/{code}/start")
async def start_table(code: str, token: str | None = None):
    try:
        table = store.get(code)
    except table_lib.TableError as exc:
        return error(str(exc), 404)
    if not table.is_host(token):
        return error("only the host can start the game", 403)
    async with lock_for(code):
        try:
            table.start()
        except table_lib.TableError as exc:
            return error(str(exc))
    await broadcast(table)
    return {"ok": True}


@app.get("/api/cards")
async def card_catalog():
    """Static card reference, fetched once and cached by the client."""
    return {
        card.id: {
            "name": card.name,
            "group": card.group,
            "vp": card.vp,
            "text": card.describe(),
            "requirement": list(card.requirement) if card.requirement else None,
        }
        for card in card_lib.CARDS.values()
    }


@app.get("/api/config")
async def public_config():
    """The handful of constants the UI needs to render and pre-validate."""
    return {
        "areas": list(config.AREAS),
        "majority_areas": list(config.MAJORITY_AREAS),
        "happiness_min": config.HAPPINESS_MIN,
        "happiness_max": config.HAPPINESS_MAX,
        "recruit_bands": [list(b) for b in config.RECRUIT_COST_BANDS],
        "recruit_cap": config.RECRUIT_CAP,
        "min_bid": config.AUCTION_MIN_BID,
        "eligibility": config.AUCTION_ELIGIBILITY,
        "feed_cost": config.FEED_COST,
        "vp_per_toad": config.VP_PER_TOAD,
        # The per-table balance form: the UI builds itself from this.
        "tuning_defaults": config.tuning_defaults(),
        "tuning_fields": [
            {
                "key": key, "label": label, "help": note,
                "default": default, "min": low, "max": high, "group": group,
            }
            for key, label, note, default, low, high, group in config.TUNING_FIELDS
        ],
        "production": config.PRODUCTION,
        "min_players": config.MIN_PLAYERS,
        "max_players": config.MAX_PLAYERS,
        "default_rounds": config.ROUNDS,
        "keepalive_interval": config.KEEPALIVE_INTERVAL_SECONDS,
        "keepalive_idle_limit": config.KEEPALIVE_IDLE_LIMIT_SECONDS,
        "spindown_estimate": config.SPINDOWN_ESTIMATE_SECONDS,
    }


@app.get("/healthz")
async def healthz():
    return {"ok": True, "tables": len(store.tables)}


STARTED_AT = time.time()


@app.get("/api/keepalive")
async def keepalive():
    """Hold a free Render instance awake.

    The request itself is the whole point — reaching this handler is inbound
    traffic, which resets Render's idle timer. The body just lets the UI show
    what happened: a small ``uptime`` means the instance had spun down and this
    ping is what woke it back up.
    """
    return {
        "ok": True,
        "uptime": round(time.time() - STARTED_AT, 1),
        "tables": len(store.tables),
        "server_time": time.time(),
    }


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@app.websocket("/ws/{code}")
async def game_socket(ws: WebSocket, code: str, token: str | None = None):
    await ws.accept()
    try:
        table = store.get(code)
    except table_lib.TableError as exc:
        # Coded so the client knows not to sit there reconnecting forever.
        await ws.send_json(
            {"type": "error", "code": "no_table", "message": str(exc)}
        )
        await ws.close()
        return

    seat = table.seat_by_token(token)
    if seat is not None:
        seat.connections += 1
    connections.add(code, ws, token)
    # A single broadcast serves both purposes: it hands this socket its opening
    # state and shows the rest of the table that the seat is connected. Sending
    # a separate opening frame as well would leave a stale message queued.
    await broadcast(table)

    try:
        while True:
            message = await ws.receive_json()
            kind = message.get("type")

            if kind == "ping":
                await ws.send_json({"type": "pong"})
                continue

            if kind == "refresh":
                await ws.send_json(payload_for(table, token))
                continue

            if kind not in ("action", "vote", "pause"):
                await ws.send_json({"type": "error", "message": "unknown message"})
                continue

            if seat is None:
                await ws.send_json(
                    {"type": "error", "message": "spectators cannot act"}
                )
                continue

            if kind == "pause":
                async with lock_for(code):
                    table.set_paused(bool(message.get("paused")), by=seat.player_id)
                await broadcast(table)
                continue

            if kind == "vote":
                # The voter is the socket's seat, never anything in the payload.
                async with lock_for(code):
                    try:
                        table.cast_vote(
                            seat.player_id,
                            str(message.get("subject")),
                            bool(message.get("kick")),
                        )
                    except table_lib.TableError as exc:
                        await ws.send_json({"type": "error", "message": str(exc)})
                        continue
                await broadcast(table)
                continue

            action = message.get("action")
            if not isinstance(action, dict):
                await ws.send_json({"type": "error", "message": "malformed action"})
                continue

            async with lock_for(code):
                try:
                    table.act(seat.player_id, action)
                except (engine.InvalidAction, table_lib.TableError) as exc:
                    await ws.send_json({"type": "error", "message": str(exc)})
                    continue
            await broadcast(table)

    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover - a bad frame must not kill the table
        pass
    finally:
        connections.remove(code, ws)
        if seat is not None:
            seat.connections = max(0, seat.connections - 1)
            try:
                await broadcast(table)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Static single-page app
# ---------------------------------------------------------------------------


NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html", headers=NO_CACHE)


@app.get("/t/{code}")
async def table_page(code: str):
    return FileResponse(STATIC_DIR / "index.html", headers=NO_CACHE)


class FreshStatic(StaticFiles):
    """Serve the UI without caching.

    This is a playtest tool that gets edited constantly: a stale app.js after a
    tweak is a confusing bug hunt, and the files are a few KB.
    """

    def is_not_modified(self, *args, **kwargs) -> bool:
        return False

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers.update(NO_CACHE)
        return response


app.mount("/static", FreshStatic(directory=STATIC_DIR), name="static")
