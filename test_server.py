"""Server and table-layer tests: routing, seats, and the information barrier."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
import engine
import server
import tables as table_lib


@pytest.fixture(autouse=True)
def fresh_store():
    # storage=None: these tests are about routing, not durability, and must not
    # write into the real data directory. Persistence lives in test_multiplayer.
    server.store = table_lib.TableStore(storage=None)
    server.connections = server.Connections()
    yield


@pytest.fixture
def client():
    with TestClient(server.app) as c:
        yield c


def create(client, players=4, humans=1, **kw):
    seats = [{"index": 0, "kind": "human"}]
    for i in range(1, players):
        seats.append(
            {"index": i, "kind": "human"} if i < humans
            else {"index": i, "kind": "bot", "strategy": "balanced"}
        )
    body = {"name": "Host", "player_count": players, "seats": seats, "seed": 7}
    body.update(kw)
    res = client.post("/api/tables", json=body)
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# Lobby
# ---------------------------------------------------------------------------


def test_create_join_and_start(client):
    made = create(client, players=3, humans=2)
    code = made["code"]

    lobby = client.get(f"/api/tables/{code}").json()
    assert lobby["table"]["status"] == "lobby"
    assert [s["kind"] for s in lobby["table"]["seats"]] == ["human", "human", "bot"]

    # Cannot start with an unclaimed human seat.
    blocked = client.post(f"/api/tables/{code}/start?token={made['host_token']}")
    assert "must be filled" in blocked.json()["error"]

    joined = client.post(f"/api/tables/{code}/join", json={"name": "Bea"}).json()
    assert joined["player_id"] == "p2"

    started = client.post(f"/api/tables/{code}/start?token={made['host_token']}")
    assert started.json() == {"ok": True}
    state = client.get(f"/api/tables/{code}?token={made['token']}").json()
    assert state["table"]["status"] == "in_progress"
    assert state["view"]["round"] == 1


def test_a_player_can_rename_their_own_seat_in_the_lobby(client):
    made = create(client, players=3, humans=2)
    code = made["code"]
    joined = client.post(f"/api/tables/{code}/join", json={"name": "Bea"}).json()

    res = client.post(f"/api/tables/{code}/name?token={joined['token']}",
                      json={"name": "  Beatrix  "})
    assert res.json() == {"ok": True, "name": "Beatrix"}
    seats = client.get(f"/api/tables/{code}").json()["table"]["seats"]
    assert [s["name"] for s in seats][:2] == ["Host", "Beatrix"]

    # Not your seat, and not a blank name.
    assert "not your seat" in client.post(
        f"/api/tables/{code}/name?token=nonsense", json={"name": "Mallory"}
    ).json()["error"]
    assert "blank" in client.post(
        f"/api/tables/{code}/name?token={joined['token']}", json={"name": "   "}
    ).json()["error"]

    # And the name is locked once the game is under way.
    client.post(f"/api/tables/{code}/seat?token={made['host_token']}",
                json={"index": 1, "kind": "bot", "strategy": "balanced"})
    client.post(f"/api/tables/{code}/start?token={made['host_token']}")
    assert "locked" in client.post(
        f"/api/tables/{code}/name?token={made['token']}", json={"name": "Late"}
    ).json()["error"]


def test_only_the_host_may_start_or_configure(client):
    made = create(client, players=2)
    assert client.post(f"/api/tables/{made['code']}/start?token=nonsense").status_code == 403
    res = client.post(
        f"/api/tables/{made['code']}/configure?token=nonsense",
        json={"player_count": 2, "rounds": 3, "seats": []},
    )
    assert res.status_code == 403


def test_settings_lock_once_the_game_starts(client):
    made = create(client, players=2)
    client.post(f"/api/tables/{made['code']}/start?token={made['host_token']}")
    res = client.post(
        f"/api/tables/{made['code']}/configure?token={made['host_token']}",
        json={"player_count": 2, "rounds": 9, "seats": []},
    )
    assert "locked" in res.json()["error"]


def test_a_full_table_cannot_be_joined(client):
    made = create(client, players=2, humans=1)   # seat 2 is a bot
    res = client.post(f"/api/tables/{made['code']}/join", json={"name": "Late"})
    assert "full" in res.json()["error"]


def test_unknown_table(client):
    assert client.get("/api/tables/ZZZZZ").status_code == 404


def test_bad_player_count_is_rejected(client):
    res = client.post("/api/tables", json={"name": "H", "player_count": 9, "seats": []})
    assert "player count" in res.json()["error"]


def test_seat_tokens_are_distinct_and_unguessable(client):
    made = create(client, players=3, humans=3)
    a = client.post(f"/api/tables/{made['code']}/join", json={"name": "A"}).json()
    b = client.post(f"/api/tables/{made['code']}/join", json={"name": "B"}).json()
    tokens = {made["token"], a["token"], b["token"]}
    assert len(tokens) == 3
    assert all(len(t) > 16 for t in tokens)


# ---------------------------------------------------------------------------
# Play over the socket
# ---------------------------------------------------------------------------


def test_playing_a_round_against_bots_over_the_socket(client):
    made = create(client, players=4, humans=1)
    client.post(f"/api/tables/{made['code']}/start?token={made['host_token']}")

    with client.websocket_connect(f"/ws/{made['code']}?token={made['token']}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "state"
        view = msg["view"]
        # The bots have already acted; we are the only seat still to commit.
        assert view["phase"] == engine.PHASE_RECRUIT
        assert view["waiting_on"] == ["p1"]

        ws.send_json({"type": "action", "action": {"type": "recruit", "count": 1}})
        view = ws.receive_json()["view"]
        assert view["phase"] in (engine.PHASE_AUCTION, engine.PHASE_PLACEMENT)
        assert view["players"][0]["toads"] == config.START_TOADS + 1


def test_the_server_rejects_an_illegal_action_and_keeps_the_state(client):
    made = create(client, players=2, humans=1)
    client.post(f"/api/tables/{made['code']}/start?token={made['host_token']}")
    with client.websocket_connect(f"/ws/{made['code']}?token={made['token']}") as ws:
        ws.receive_json()
        ws.send_json({"type": "action", "action": {"type": "recruit", "count": 99}})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "capped" in err["message"]

        ws.send_json({"type": "action", "action": {"type": "feed", "keep": 1}})
        assert ws.receive_json()["type"] == "error"

        ws.send_json({"type": "action", "action": "not-a-dict"})
        assert ws.receive_json()["type"] == "error"

        ws.send_json({"type": "refresh"})
        view = ws.receive_json()["view"]
        assert view["phase"] == engine.PHASE_RECRUIT
        assert view["players"][0]["toads"] == config.START_TOADS


def test_a_client_can_never_act_for_another_seat(client):
    """The seat is taken from the socket's token, never from the message."""
    made = create(client, players=3, humans=3)
    other = client.post(f"/api/tables/{made['code']}/join", json={"name": "B"}).json()
    client.post(f"/api/tables/{made['code']}/join", json={"name": "C"})
    client.post(f"/api/tables/{made['code']}/start?token={made['host_token']}")

    with client.websocket_connect(f"/ws/{made['code']}?token={made['token']}") as ws:
        ws.receive_json()
        # A forged player_id in the payload is simply ignored.
        ws.send_json({
            "type": "action",
            "action": {"type": "recruit", "count": 1},
            "player_id": other["player_id"],
        })
        view = ws.receive_json()["view"]
        committed = {p["id"]: p["committed"] for p in view["players"]}
        assert committed == {"p1": True, "p2": False, "p3": False}


def test_a_spectator_can_watch_but_not_act(client):
    made = create(client, players=2, humans=1)
    client.post(f"/api/tables/{made['code']}/start?token={made['host_token']}")
    with client.websocket_connect(f"/ws/{made['code']}") as ws:
        view = ws.receive_json()["view"]
        assert view["you"] is None
        assert view["your_commitment"] is None
        ws.send_json({"type": "action", "action": {"type": "recruit", "count": 0}})
        assert "spectators" in ws.receive_json()["message"]


def test_each_socket_receives_only_its_own_commitment(client):
    made = create(client, players=3, humans=3)
    b = client.post(f"/api/tables/{made['code']}/join", json={"name": "B"}).json()
    client.post(f"/api/tables/{made['code']}/join", json={"name": "C"})
    client.post(f"/api/tables/{made['code']}/start?token={made['host_token']}")

    with client.websocket_connect(f"/ws/{made['code']}?token={made['token']}") as ws_a, \
         client.websocket_connect(f"/ws/{made['code']}?token={b['token']}") as ws_b:
        ws_a.receive_json()
        ws_b.receive_json()
        ws_a.receive_json()  # b's arrival rebroadcasts to the table

        ws_a.send_json({"type": "action", "action": {"type": "recruit", "count": 3}})
        mine = ws_a.receive_json()["view"]
        theirs = ws_b.receive_json()["view"]

        assert mine["your_commitment"] == {"type": "recruit", "count": 3}
        assert theirs["your_commitment"] is None
        # B can see that A is ready, but nothing about what A did.
        assert [p["committed"] for p in theirs["players"]] == [True, False, False]
        assert not _contains(theirs, {"type": "recruit", "count": 3})


def _contains(node, needle):
    if node == needle:
        return True
    if isinstance(node, dict):
        return any(_contains(v, needle) for v in node.values())
    if isinstance(node, list):
        return any(_contains(v, needle) for v in node)
    return False


def test_connection_status_is_visible_to_the_table(client):
    made = create(client, players=2, humans=2)
    b = client.post(f"/api/tables/{made['code']}/join", json={"name": "B"}).json()
    with client.websocket_connect(f"/ws/{made['code']}?token={b['token']}"):
        table = client.get(f"/api/tables/{made['code']}").json()["table"]
        assert [s["connected"] for s in table["seats"]] == [False, True]
    table = client.get(f"/api/tables/{made['code']}").json()["table"]
    assert [s["connected"] for s in table["seats"]] == [False, False]


def test_reconnecting_with_the_same_token_returns_to_the_same_seat(client):
    made = create(client, players=2, humans=1)
    client.post(f"/api/tables/{made['code']}/start?token={made['host_token']}")
    with client.websocket_connect(f"/ws/{made['code']}?token={made['token']}") as ws:
        ws.receive_json()
        ws.send_json({"type": "action", "action": {"type": "recruit", "count": 2}})
        ws.receive_json()
    with client.websocket_connect(f"/ws/{made['code']}?token={made['token']}") as ws:
        view = ws.receive_json()["view"]
        assert view["you"] == "p1"
        assert view["players"][0]["toads"] == config.START_TOADS + 2


def test_a_solo_game_against_bots_can_be_played_to_the_end(client):
    made = create(client, players=4, humans=1, rounds=2)
    client.post(f"/api/tables/{made['code']}/start?token={made['host_token']}")
    with client.websocket_connect(f"/ws/{made['code']}?token={made['token']}") as ws:
        view = ws.receive_json()["view"]
        guard = 0
        while view["phase"] != engine.PHASE_FINISHED:
            guard += 1
            assert guard < 200
            if "p1" not in view["waiting_on"]:
                view = ws.receive_json()["view"]
                continue
            ws.send_json({"type": "action", "action": _simple_action(view)})
            reply = ws.receive_json()
            if reply["type"] == "error":
                raise AssertionError(reply["message"])
            view = reply["view"]
    assert view["scores"]["winners"]
    assert client.get(f"/api/tables/{made['code']}").json()["table"]["status"] == "finished"


def _simple_action(view):
    me = next(p for p in view["players"] if p["id"] == view["you"])
    phase = view["phase"]
    if phase == engine.PHASE_RECRUIT:
        return {"type": "recruit", "count": min(1, me["flies"] // me["recruit_cost"])}
    if phase == engine.PHASE_AUCTION:
        if view["auction"]["stage"] == engine.STAGE_REBID:
            return {"type": "bid", "amount": view["auction"]["tied_amount"]}
        return {"type": "bid", "amount": 0}
    if phase == engine.PHASE_PLACEMENT:
        return {"type": "place", "placement": {"fields": me["toads"]}}
    if phase == engine.PHASE_TRIBUTE:
        return {"type": "tribute", "resource": me["tribute_options"][0]}
    return {"type": "feed", "keep": min(me["toads"], me["flies"])}


# ---------------------------------------------------------------------------
# Static assets and reference endpoints
# ---------------------------------------------------------------------------


def test_the_app_and_its_assets_are_served(client):
    assert b"Kingdom of Toads" in client.get("/").content
    assert b"Kingdom of Toads" in client.get("/t/ABCDE").content
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/healthz").json()["ok"] is True


def test_a_table_can_be_created_with_its_own_scoring_values(client):
    made = create(client, players=2, tuning={"vp_per_toad": 4, "vp_most_gold": 11})
    code = made["code"]
    lobby = client.get(f"/api/tables/{code}").json()["table"]
    assert lobby["tuning"]["vp_per_toad"] == 4
    assert lobby["tuning"]["vp_most_gold"] == 11
    # Untouched fields keep their defaults.
    assert lobby["tuning"]["war_token_base"] == config.TUNING_DEFAULTS["war_token_base"]

    client.post(f"/api/tables/{code}/start?token={made['host_token']}")
    view = client.get(f"/api/tables/{code}?token={made['token']}").json()["view"]
    assert view["scoring"]["vp_per_toad"] == 4


def test_a_second_table_is_unaffected_by_the_first(client):
    tuned = create(client, players=2, tuning={"vp_per_toad": 9})
    plain = create(client, players=2)
    assert client.get(f"/api/tables/{tuned['code']}").json()["table"]["tuning"]["vp_per_toad"] == 9
    assert (
        client.get(f"/api/tables/{plain['code']}").json()["table"]["tuning"]["vp_per_toad"]
        == config.VP_PER_TOAD
    )


def test_scoring_values_lock_when_the_game_starts(client):
    made = create(client, players=2, tuning={"vp_per_toad": 3})
    client.post(f"/api/tables/{made['code']}/start?token={made['host_token']}")
    res = client.post(
        f"/api/tables/{made['code']}/configure?token={made['host_token']}",
        json={"player_count": 2, "seats": [], "tuning": {"vp_per_toad": 20}},
    )
    assert "locked" in res.json()["error"]


def test_the_tuning_form_is_published_for_the_ui(client):
    cfg = client.get("/api/config").json()
    keys = {f["key"] for f in cfg["tuning_fields"]}
    assert keys == set(cfg["tuning_defaults"])
    assert "vp_per_toad" in keys
    assert {"vp_most_happiness", "vp_most_gold", "vp_most_flies"} <= keys
    for field in cfg["tuning_fields"]:
        assert field["min"] <= field["default"] <= field["max"]
        assert field["label"] and field["help"] and field["group"]


def test_keepalive_reports_uptime_so_a_cold_start_is_visible(client):
    first = client.get("/api/keepalive").json()
    assert first["ok"] is True
    assert first["uptime"] >= 0
    second = client.get("/api/keepalive").json()
    assert second["uptime"] >= first["uptime"]


def test_card_catalog_and_config_are_published(client):
    catalog = client.get("/api/cards").json()
    assert len(catalog) == len(config.CARD_DEFS)
    assert {c["development"] for c in catalog.values()} == set(config.DEVELOPMENTS)
    assert catalog["grand_monument"]["vp"] == 10
    assert catalog["great_marsh"]["requirement"] == ["fields", 3]

    cfg = client.get("/api/config").json()
    assert cfg["recruit_cap"] == config.RECRUIT_CAP
    assert cfg["min_bid"] == config.AUCTION_MIN_BID
    assert len(cfg["recruit_bands"]) == 4


# ---------------------------------------------------------------------------
# Table store
# ---------------------------------------------------------------------------


def test_join_codes_are_readable_and_unique():
    store = table_lib.TableStore(storage=None)
    codes = set()
    for _ in range(50):
        table, _ = store.create(2, "Host", seat_kinds=[{"index": 1, "kind": "bot"}])
        codes.add(table.code)
        assert not set(table.code) & set("IO01")
    assert len(codes) == 50


def test_idle_tables_are_cleaned_up():
    store = table_lib.TableStore(storage=None)
    table, _ = store.create(2, "Host", seat_kinds=[{"index": 1, "kind": "bot"}])
    assert store.cleanup() == 0
    table.updated_at -= config.TABLE_IDLE_CLEANUP_HOURS * 3600 + 60
    assert store.cleanup() == 1
    assert store.tables == {}


def test_an_unknown_bot_strategy_is_rejected():
    store = table_lib.TableStore(storage=None)
    with pytest.raises(table_lib.TableError):
        store.create(2, "Host", seat_kinds=[{"index": 1, "kind": "bot", "strategy": "wizard"}])


# ---------------------------------------------------------------------------
# The rules page
# ---------------------------------------------------------------------------


def test_the_rules_describe_the_defaults_without_a_table(client):
    data = client.get("/api/rules").json()
    assert data["changed"] == []
    headings = [s["heading"] for s in data["sections"]]
    assert "Phase 1 — Recruitment" in headings
    assert "Scoring" in headings
    assert "gold bids only" in data["summary"]


def test_the_rules_follow_a_tables_own_settings(client):
    made = create(client, players=3, rounds=8, tuning={
        "vp_per_toad": 4, "gold_mode": 2, "gold_per_fly": 3,
        "start_gold": 25, "rest_empty_penalty": 0,
    })
    data = client.get(f"/api/rules?code={made['code']}").json()

    assert "3 players" in data["summary"] and "8 rounds" in data["summary"]
    assert "gold buys flies" in data["summary"]
    changed = {c["label"]: c["value"] for c in data["changed"]}
    assert changed["VP per toad"] == 4
    assert changed["Starting gold"] == 25

    flat = _flatten(data)
    assert "3 gold each" in flat          # the exchange rate it actually uses
    assert "4 VP" in flat                 # the toad's value at this table
    assert "25" in flat                   # the starting purse
    assert "nobody in Rest" not in flat   # that penalty is switched off here


def test_the_rules_track_the_gold_mode(client):
    recruits = create(client, players=2, tuning={"gold_mode": 1})
    flat = _flatten(client.get(f"/api/rules?code={recruits['code']}").json())
    assert "Gold per toad" in flat        # the band table gains a column
    assert "more than the fly price" in flat

    plain = create(client, players=2)
    flat = _flatten(client.get(f"/api/rules?code={plain['code']}").json())
    assert "paid for in flies only" in flat
    assert "Gold per toad" not in flat


def test_the_rules_describe_every_rule_the_engine_actually_applies(client):
    """A changed rule that the rules page does not mention is a trap.

    One assertion per rule added or changed since the page was written, so a
    future change to the engine that forgets this file fails here.
    """
    made = create(client, players=4)
    flat = _flatten(client.get(f"/api/rules?code={made['code']}").json())

    # Austerity is one use per copy, and the spent card still counts.
    assert "only once: using it consumes the card" in flat
    assert "still counting as property" in flat
    assert "once per copy for the whole game" in flat

    # The recruitment cap, and what sits outside it.
    assert f"up to {config.recruit_cap()} toads a round" in flat
    assert "from a card or from the Rest majority are on top of it" in flat

    # Starting resources and where the happiness track starts.
    assert f"{config.START_FLIES}" in flat
    assert f"track from {config.HAPPINESS_MIN} to {config.HAPPINESS_MAX}" in flat
    assert "recruitment band at 3 flies a toad" in flat

    # Per-toad production, which is a table setting now.
    assert "+2 flies" in flat and "+2 gold" in flat

    # The Rest majority pays twice.
    assert "happiness and a free toad" in flat
    assert "+1 happy +1 toad" in flat

    # A toad scores nothing per head; the awards do the scoring, at the end.
    assert "nothing per head" in flat
    assert "5 one-off awards" in flat
    assert "Most toads — 5 VP" in flat
    assert "Most property cards — 5 VP" in flat
    assert "none of them is counted before the final feeding" in flat
    assert "straight trade between two awards" in flat

    # Where the points come from at all, said up front.
    assert "Points come from" in flat

    # The war token's real value, not "the round it was won in".
    assert "2–7 VP, by the round it was won in" in flat


def test_the_rules_describe_the_bonus_structure_in_use(client):
    ladder = create(client, players=2)
    flat = _flatten(client.get(f"/api/rules?code={ladder['code']}").json())
    assert "pays ladder bonuses" in flat
    assert "two-phase" not in flat
    assert "Round 1" in flat and "Round 6" in flat

    two = create(client, players=2, tuning={"bonus_mode": 1})
    flat = _flatten(client.get(f"/api/rules?code={two['code']}").json())
    assert "pays two-phase bonuses" in flat
    assert "Round 3 (village)" in flat and "Round 4 (city)" in flat
    # The village and city rates, and the war that turns with them.
    assert "+1 happy +1 toad" in flat and "+2 happy +2 toads" in flat
    assert "3 VP from a village round, 6 VP from a city round" in flat
    assert "1 in the village rounds and 2 in the city rounds" in flat
    # And the ladder's language is gone.
    assert "pays ladder bonuses" not in flat

    changed = {c["label"]: c for c in
               client.get(f"/api/rules?code={two['code']}").json()["changed"]}
    # A setting that names a choice reads by name, not as a bare number.
    assert changed["Bonus structure"]["value_label"] == "two-phase"
    assert changed["Bonus structure"]["default_label"] == "ladder"


def test_the_rules_describe_buying_flies_as_its_own_action(client):
    """Mode 2 only, and it is a separate action rather than part of a commit."""
    trade = create(client, players=2, tuning={"gold_mode": 2})
    flat = _flatten(client.get(f"/api/rules?code={trade['code']}").json())
    assert "Buying flies is its own action" in flat
    assert "not part of your secret commitment" in flat
    assert "settled before you commit how many toads to keep" in flat

    plain = _flatten(client.get("/api/rules").json())
    assert "Buying flies is its own action" not in plain


def test_the_rules_only_claim_there_is_no_turn_order_when_there_is_none(client):
    blind = _flatten(client.get("/api/rules").json())
    assert "no turn order at all" in blind

    live = create(client, players=2, auction_mode="live")
    flat = _flatten(client.get(f"/api/rules?code={live['code']}").json())
    assert "no turn order in any simultaneous phase" in flat
    assert "only sets who opens the bidding" in flat


def test_an_unknown_table_is_reported_not_guessed(client):
    assert client.get("/api/rules?code=ZZZZZ").status_code == 404


def test_the_rules_page_is_served(client):
    assert b"Kingdom of Toads" in client.get("/rules").content


def _flatten(data) -> str:
    parts = [data["summary"]]
    for section in data["sections"]:
        parts.append(section["heading"])
        for block in section["blocks"]:
            if block["kind"] == "p":
                parts.append(block["text"])
            elif block["kind"] == "ul":
                parts.extend(block["items"])
            else:
                parts.extend(block["head"])
                for row in block["rows"]:
                    parts.extend(row)
    return " | ".join(parts)
