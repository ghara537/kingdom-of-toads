"""Persistence, phase timeouts and table lifecycle — the session layer.

Sessions are where a playtest actually breaks: someone walks away mid-phase,
Render restarts the process, a player rejoins from a different browser.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import config
import engine
import server
import storage as storage_lib
import tables as table_lib


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "tables"


@pytest.fixture
def store(data_dir):
    return table_lib.TableStore(storage_lib.TableStorage(data_dir))


@pytest.fixture
def client(store):
    server.store = store
    server.connections = server.Connections()
    with TestClient(server.app) as c:
        yield c


def make_table(store, players=3, humans=1, **kw):
    seats = [{"index": 0, "kind": "human"}]
    for i in range(1, players):
        seats.append(
            {"index": i, "kind": "human"} if i < humans
            else {"index": i, "kind": "bot", "strategy": "balanced"}
        )
    return store.create(players, "Host", seat_kinds=seats, seed=5, **kw)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_a_table_is_written_to_disk_as_it_is_played(store, data_dir):
    table, seat = make_table(store)
    saved = data_dir / f"{table.code}.json"
    assert saved.exists()

    table.start()
    table.act(seat.player_id, {"type": "recruit", "count": 2})
    before = saved.stat().st_mtime_ns
    table.act(seat.player_id, {"type": "bid", "amount": 0})
    assert saved.stat().st_mtime_ns >= before


def test_a_game_in_progress_survives_a_restart_unchanged(store, data_dir):
    table, seat = make_table(store, players=3, humans=1)
    table.start()
    table.act(seat.player_id, {"type": "recruit", "count": 3})
    original = table.to_dict()

    # A whole new process: nothing in memory, everything read from disk.
    revived = table_lib.TableStore(storage_lib.TableStorage(data_dir))
    assert revived.load() == 1
    restored = revived.get(table.code)

    assert restored.to_dict()["state"] == original["state"]
    assert restored.status == original["status"]
    assert restored.rounds == table.rounds
    assert [s.token for s in restored.seats] == [s.token for s in table.seats]
    assert engine.pending_players(restored.state) == engine.pending_players(table.state)

    # And play continues from exactly where it left off.
    pending = engine.pending_players(restored.state)
    if seat.player_id in pending:
        restored.act(seat.player_id, {"type": "bid", "amount": 0})


def test_an_in_flight_commitment_survives_a_restart(store, data_dir):
    table, seat = make_table(store, players=3, humans=3)
    other = table.join("Bea")
    table.join("Cal")
    table.start()
    table.act(other.player_id, {"type": "recruit", "count": 1})

    revived = table_lib.TableStore(storage_lib.TableStorage(data_dir))
    revived.load()
    restored = revived.get(table.code)

    # Bea's committed choice comes back to Bea, and to nobody else.
    assert restored.view_for(other.token)["your_commitment"] == {
        "type": "recruit", "count": 1,
    }
    assert restored.view_for(seat.token)["your_commitment"] is None


def test_a_finished_game_keeps_its_scoreboard_across_a_restart(store, data_dir):
    table, seat = make_table(store, players=2, humans=1, rounds=1)
    table.start()
    guard = 0
    while table.status != table_lib.FINISHED:
        guard += 1
        assert guard < 100
        pending = engine.pending_players(table.state)
        if seat.player_id not in pending:
            break
        table.act(seat.player_id, engine.default_action(table.state, seat.player_id))

    revived = table_lib.TableStore(storage_lib.TableStorage(data_dir))
    revived.load()
    restored = revived.get(table.code)
    assert restored.status == table_lib.FINISHED
    assert restored.view_for(seat.token)["scores"] == table.view_for(seat.token)["scores"]


def test_a_corrupt_or_foreign_save_file_is_skipped_not_fatal(store, data_dir):
    table, _ = make_table(store)
    (data_dir / "GARBAGE.json").write_text("{not json")
    (data_dir / "OLDVER.json").write_text('{"code": "OLDVER"}')

    revived = table_lib.TableStore(storage_lib.TableStorage(data_dir))
    assert revived.load() == 1
    assert list(revived.tables) == [table.code]


def test_a_read_only_data_directory_degrades_instead_of_crashing(tmp_path):
    blocked = tmp_path / "nope"
    blocked.write_text("i am a file, not a directory")
    storage = storage_lib.TableStorage(blocked)
    assert storage.enabled is False
    store = table_lib.TableStore(storage)
    table, seat = make_table(store)      # the game still runs
    table.start()
    assert table.status == table_lib.IN_PROGRESS
    assert storage.load_all() == []


def test_cleanup_removes_the_file_as_well_as_the_table(store, data_dir):
    table, _ = make_table(store)
    saved = data_dir / f"{table.code}.json"
    assert saved.exists()
    table.updated_at -= config.TABLE_IDLE_CLEANUP_HOURS * 3600 + 60
    assert store.cleanup() == 1
    assert not saved.exists()
    assert store.tables == {}


# ---------------------------------------------------------------------------
# Phase timeouts
# ---------------------------------------------------------------------------


def test_a_timer_starts_only_when_a_human_is_holding_things_up(store):
    table, seat = make_table(store, players=3, humans=1)
    assert table.deadline is None            # lobby: no timer
    table.start()
    assert table.seconds_left() == pytest.approx(table.timeout_seconds, abs=2)
    assert engine.pending_players(table.state) == [seat.player_id]


def test_the_deadline_does_not_restart_each_time_someone_commits(store):
    table, host = make_table(store, players=3, humans=3)
    bea = table.join("Bea")
    table.join("Cal")
    table.start()
    first = table.deadline
    time.sleep(0.02)
    table.act(host.player_id, {"type": "recruit", "count": 0})
    assert table.deadline == first           # same phase, same clock
    table.act(bea.player_id, {"type": "recruit", "count": 0})
    assert table.deadline == first


def test_a_new_phase_starts_a_new_timer(store):
    table, seat = make_table(store, players=3, humans=1)
    table.start()
    first = table.deadline
    table.deadline -= 5                      # pretend some time passed
    table.act(seat.player_id, {"type": "recruit", "count": 0})
    assert table.state.phase != engine.PHASE_RECRUIT
    assert table.deadline > first - 5


def test_a_lapsed_timer_opens_a_vote_rather_than_replacing_anyone(store):
    table, host = make_table(store, players=3, humans=3)
    bea = table.join("Bea")
    table.join("Cal")
    table.start()
    assert table.state.phase == engine.PHASE_RECRUIT

    table.deadline = time.time() - 1
    table.tick()

    # Everyone is late, so there is one question per late player.
    assert sorted(table.votes) == ["p1", "p2", "p3"]
    assert table.votes["p2"].eligible == ["p1", "p3"]     # never themselves
    assert table.deadline is None                         # the phase clock waits
    assert all(s.kind == table_lib.HUMAN for s in table.seats)
    assert table.state.phase == engine.PHASE_RECRUIT      # nothing was played
    assert any(e["type"] == "kick_vote" for e in table.state.log)


def test_one_yes_replaces_that_seat_with_a_bot(store):
    table, host = make_table(store, players=3, humans=3)
    bea = table.join("Bea")
    cal = table.join("Cal")
    table.start()
    table.act(host.player_id, {"type": "recruit", "count": 0})
    table.deadline = time.time() - 1
    table.tick()
    assert sorted(table.votes) == ["p2", "p3"]   # the host already committed

    assert table.cast_vote(host.player_id, bea.player_id, kick=True) == "kicked"

    assert table.seat_by_player(bea.player_id).kind == table_lib.BOT
    assert bea.player_id not in table.votes
    assert bea.player_id not in engine.pending_players(table.state)  # bot moved
    assert cal.player_id in table.votes          # the other vote is untouched
    assert any(e["type"] == "kicked" for e in table.state.log)


def test_a_kicked_seat_keeps_its_token_so_it_can_be_handed_back(store):
    table, host = make_table(store, players=2, humans=2)
    bea = table.join("Bea")
    table.start()
    table.act(host.player_id, {"type": "recruit", "count": 0})
    table.deadline = time.time() - 1
    table.tick()
    table.cast_vote(host.player_id, bea.player_id, kick=True)

    assert table.seat_by_token(bea.token).player_id == bea.player_id
    table.set_seat_kind(1, table_lib.HUMAN)
    assert table.seat_by_player(bea.player_id).kind == table_lib.HUMAN


def test_everyone_saying_no_restarts_the_clock(store):
    table, host = make_table(store, players=3, humans=3)
    bea = table.join("Bea")
    cal = table.join("Cal")
    table.start()
    table.act(host.player_id, {"type": "recruit", "count": 0})
    table.act(cal.player_id, {"type": "recruit", "count": 0})
    table.deadline = time.time() - 1
    table.tick()
    assert list(table.votes) == [bea.player_id]

    assert table.cast_vote(host.player_id, bea.player_id, kick=False) == "noted"
    assert bea.player_id in table.votes          # still waiting on Cal
    assert table.cast_vote(cal.player_id, bea.player_id, kick=False) == "kept"

    assert table.votes == {}
    assert table.seat_by_player(bea.player_id).kind == table_lib.HUMAN
    assert table.seconds_left() == pytest.approx(table.timeout_seconds, abs=2)
    assert any(e["type"] == "kick_declined" for e in table.state.log)


def test_a_vote_that_nobody_answers_lapses_into_more_waiting(store):
    table, host = make_table(store, players=2, humans=2)
    bea = table.join("Bea")
    table.start()
    table.act(host.player_id, {"type": "recruit", "count": 0})
    table.deadline = time.time() - 1
    table.tick()
    assert list(table.votes) == [bea.player_id]

    table.votes[bea.player_id].deadline = time.time() - 1
    table.tick()

    assert table.votes == {}
    assert table.seat_by_player(bea.player_id).kind == table_lib.HUMAN
    assert table.seconds_left() == pytest.approx(table.timeout_seconds, abs=2)
    assert any(e["type"] == "kick_lapsed" for e in table.state.log)


def test_coming_back_and_acting_cancels_the_vote(store):
    table, host = make_table(store, players=2, humans=2)
    bea = table.join("Bea")
    table.start()
    table.act(host.player_id, {"type": "recruit", "count": 0})
    table.deadline = time.time() - 1
    table.tick()
    assert list(table.votes) == [bea.player_id]

    table.act(bea.player_id, {"type": "recruit", "count": 1})

    assert table.votes == {}
    assert table.seat_by_player(bea.player_id).kind == table_lib.HUMAN
    assert any(e["type"] == "kick_cancelled" for e in table.state.log)


def test_you_cannot_vote_on_yourself_or_on_a_seat_with_no_open_vote(store):
    table, host = make_table(store, players=3, humans=3)
    bea = table.join("Bea")
    table.join("Cal")
    table.start()
    table.deadline = time.time() - 1
    table.tick()

    with pytest.raises(table_lib.TableError):
        table.cast_vote(bea.player_id, bea.player_id, kick=True)
    with pytest.raises(table_lib.TableError):
        table.cast_vote(host.player_id, "nobody", kick=True)


def test_a_solo_game_against_bots_is_never_voted_on(store):
    """With no other humans there is nobody to ask, so the table just waits."""
    table, seat = make_table(store, players=4, humans=1)
    table.start()
    table.deadline = time.time() - 1
    table.tick()

    assert table.votes == {}
    assert table.seat_by_player(seat.player_id).kind == table_lib.HUMAN
    assert table.state.phase == engine.PHASE_RECRUIT
    assert table.seconds_left() == pytest.approx(table.timeout_seconds, abs=2)


# ---------------------------------------------------------------------------
# Pause
# ---------------------------------------------------------------------------


def test_pausing_stops_the_clock_entirely(store):
    table, host = make_table(store, players=2, humans=2)
    table.join("Bea")
    table.start()
    assert table.deadline is not None

    table.set_paused(True, by=host.player_id)
    assert table.paused is True
    assert table.deadline is None
    assert table.seconds_left() is None

    table.tick()
    assert table.votes == {}
    assert any(e["type"] == "paused" for e in table.state.log)

    table.set_paused(False, by=host.player_id)
    assert table.seconds_left() == pytest.approx(table.timeout_seconds, abs=2)


def test_pausing_cancels_any_vote_in_flight(store):
    table, host = make_table(store, players=2, humans=2)
    bea = table.join("Bea")
    table.start()
    table.act(host.player_id, {"type": "recruit", "count": 0})
    table.deadline = time.time() - 1
    table.tick()
    assert list(table.votes) == [bea.player_id]

    table.set_paused(True, by=host.player_id)
    assert table.votes == {}
    assert table.seat_by_player(bea.player_id).kind == table_lib.HUMAN


def test_pause_survives_a_restart(store, data_dir):
    table, host = make_table(store, players=2, humans=2)
    table.join("Bea")
    table.start()
    table.set_paused(True, by=host.player_id)

    revived = table_lib.TableStore(storage_lib.TableStorage(data_dir))
    revived.load()
    restored = revived.get(table.code)
    assert restored.paused is True
    assert restored.deadline is None


def test_pause_and_votes_travel_to_the_client(client, store):
    table, host = make_table(store, players=2, humans=2)
    bea = table.join("Bea")
    table.start()
    with client.websocket_connect(f"/ws/{table.code}?token={host.token}") as ws:
        ws.receive_json()
        ws.send_json({"type": "pause", "paused": True})
        payload = ws.receive_json()
        assert payload["table"]["paused"] is True
        assert payload["table"]["seconds_left"] is None

        ws.send_json({"type": "pause", "paused": False})
        ws.receive_json()

        table.act(host.player_id, {"type": "recruit", "count": 0})
        table.deadline = time.time() - 0.1
        pushed = ws.receive_json()          # the sweeper opens the vote
        votes = pushed["table"]["votes"]
        assert [v["subject"] for v in votes] == [bea.player_id]
        assert votes[0]["eligible"] == [host.player_id]

        ws.send_json({"type": "vote", "subject": bea.player_id, "kick": True})
        after = ws.receive_json()
        assert after["table"]["votes"] == []
        assert [s["kind"] for s in after["table"]["seats"]] == ["human", "bot"]


def test_a_vote_cannot_be_cast_by_a_forged_seat(client, store):
    table, host = make_table(store, players=3, humans=3)
    bea = table.join("Bea")
    table.join("Cal")
    table.start()
    table.act(host.player_id, {"type": "recruit", "count": 0})
    table.deadline = time.time() - 1
    table.tick()

    # Bea's own socket cannot vote Bea out, whatever the payload claims.
    with client.websocket_connect(f"/ws/{table.code}?token={bea.token}") as ws:
        ws.receive_json()
        ws.send_json({
            "type": "vote", "subject": bea.player_id, "kick": True,
            "voter": host.player_id,
        })
        assert "not eligible" in ws.receive_json()["message"]
    assert table.seat_by_player(bea.player_id).kind == table_lib.HUMAN


def test_the_timer_restarts_after_a_process_restart(store, data_dir):
    table, seat = make_table(store, players=3, humans=1)
    table.start()
    table.deadline = time.time() - 500       # would fire the instant we reload
    store.save(table)

    revived = table_lib.TableStore(storage_lib.TableStorage(data_dir))
    revived.load()
    restored = revived.get(table.code)
    # Players should not be timed out for downtime they had no part in.
    assert not restored.expired()
    assert restored.seconds_left() == pytest.approx(restored.timeout_seconds, abs=2)


def test_the_sweeper_never_plays_a_solo_game_for_you(client, store):
    table, seat = make_table(store, players=3, humans=1)
    table.start()
    with client.websocket_connect(f"/ws/{table.code}?token={seat.token}") as ws:
        view = ws.receive_json()["view"]
        assert view["waiting_on"] == [seat.player_id]

        table.deadline = time.time() - 0.1   # the sweeper ticks once a second
        pushed = ws.receive_json()
        assert pushed["table"]["votes"] == []      # nobody to ask
        assert pushed["view"]["phase"] == engine.PHASE_RECRUIT
        assert pushed["view"]["waiting_on"] == [seat.player_id]
        assert 0 < pushed["table"]["seconds_left"] <= table.timeout_seconds


def test_a_vote_opened_in_one_phase_does_not_haunt_the_next(store):
    table, host = make_table(store, players=2, humans=2)
    bea = table.join("Bea")
    table.start()
    table.act(host.player_id, {"type": "recruit", "count": 0})
    table.deadline = time.time() - 1
    table.tick()
    assert list(table.votes) == [bea.player_id]

    # Bea commits, recruitment resolves, and the auction opens — where she owes
    # a decision again. That must be a clean slate, not the old vote.
    table.act(bea.player_id, {"type": "recruit", "count": 0})
    assert table.state.phase != engine.PHASE_RECRUIT
    assert table.votes == {}


def test_the_countdown_is_published_to_the_client(client, store):
    table, seat = make_table(store, players=3, humans=1)
    table.start()
    with client.websocket_connect(f"/ws/{table.code}?token={seat.token}") as ws:
        payload = ws.receive_json()
        assert payload["table"]["timeout_seconds"] == config.PHASE_TIMEOUT_SECONDS
        assert 0 < payload["table"]["seconds_left"] <= config.PHASE_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# Rejoining
# ---------------------------------------------------------------------------


def test_a_reconnecting_player_gets_their_own_committed_choice_back(client, store):
    table, host = make_table(store, players=3, humans=3)
    bea = table.join("Bea")
    table.join("Cal")
    table.start()
    table.act(bea.player_id, {"type": "recruit", "count": 2})

    # Bea's browser died; she opens the link again with the same seat token.
    with client.websocket_connect(f"/ws/{table.code}?token={bea.token}") as ws:
        view = ws.receive_json()["view"]
        assert view["you"] == bea.player_id
        assert view["your_commitment"] == {"type": "recruit", "count": 2}

    # The host reconnecting sees that Bea is ready, and nothing more.
    with client.websocket_connect(f"/ws/{table.code}?token={host.token}") as ws:
        view = ws.receive_json()["view"]
        assert view["your_commitment"] is None
        committed = {p["id"]: p["committed"] for p in view["players"]}
        assert committed[bea.player_id] is True
        assert not _contains(view, {"type": "recruit", "count": 2})


def _contains(node, needle):
    if node == needle:
        return True
    if isinstance(node, dict):
        return any(_contains(v, needle) for v in node.values())
    if isinstance(node, list):
        return any(_contains(v, needle) for v in node)
    return False


def test_a_disconnected_seat_stays_reserved(client, store):
    table, host = make_table(store, players=2, humans=2)
    bea = table.join("Bea")
    assert table.open_seats == []
    with pytest.raises(table_lib.TableError):
        table.join("Interloper")          # cannot take an occupied seat
    table.start()
    # Still hers after the game is under way, and her token still works.
    assert table.seat_by_token(bea.token).player_id == "p2"
    with pytest.raises(table_lib.TableError):
        table.join("Interloper")


def test_a_stale_token_cannot_act(client, store):
    table, seat = make_table(store, players=2, humans=1)
    table.start()
    with client.websocket_connect(f"/ws/{table.code}?token=not-a-real-token") as ws:
        view = ws.receive_json()["view"]
        assert view["you"] is None        # treated as a spectator
        ws.send_json({"type": "action", "action": {"type": "recruit", "count": 4}})
        assert ws.receive_json()["type"] == "error"


# ---------------------------------------------------------------------------
# Host controls
# ---------------------------------------------------------------------------


def test_the_host_can_hand_a_seat_to_a_bot_for_good(client, store):
    table, host = make_table(store, players=3, humans=3)
    bea = table.join("Bea")
    table.join("Cal")
    table.start()

    res = client.post(
        f"/api/tables/{table.code}/seat?token={table.host_token}",
        json={"index": 1, "kind": "bot", "strategy": "warlord"},
    )
    assert res.json() == {"ok": True}
    assert table.seat_by_player(bea.player_id).kind == table_lib.BOT
    # The new bot immediately takes over the decision it owed.
    assert bea.player_id not in engine.pending_players(table.state)
    # Her token is kept, so the host can hand the seat back if she returns.
    assert table.seat_by_token(bea.token) is not None

    client.post(
        f"/api/tables/{table.code}/seat?token={table.host_token}",
        json={"index": 1, "kind": "human"},
    )
    assert table.seat_by_player(bea.player_id).kind == table_lib.HUMAN


def test_only_the_host_can_reassign_a_seat(client, store):
    table, host = make_table(store, players=2, humans=1)
    table.start()
    res = client.post(
        f"/api/tables/{table.code}/seat?token={host.token}",   # a seat token
        json={"index": 0, "kind": "bot"},
    )
    assert res.status_code == 403


def test_a_bot_seat_never_holds_the_table_up(store):
    """With every human done, there is nothing left to time out."""
    table, seat = make_table(store, players=4, humans=1)
    table.start()
    table.set_seat_kind(0, table_lib.BOT, "farmer")
    assert table.status == table_lib.FINISHED   # the bots played the whole game
    assert table.deadline is None
