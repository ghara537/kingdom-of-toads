/* Kingdom of Toads — playtest client.
 *
 * The client is a renderer plus an intent sender. It holds no rules: every
 * decision is validated by the server, and it only ever receives the view its
 * own seat is entitled to.
 */

const S = {
  code: null, token: null, hostToken: null,
  table: null, view: null, catalog: {}, cfg: null,
  ws: null, draft: null, draftKey: null, retry: null,
  // Phase countdown, anchored to when the message arrived rather than to a
  // server timestamp, so clock skew between machines does not matter.
  timer: { left: null, at: 0 },
};

function isHost() {
  return Boolean((S.table && S.table.is_host) || S.hostToken);
}

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};
const AREA_LABEL = { fields: 'Fields', mine: 'Mine', military: 'Military', rest: 'Rest' };

/* -------------------------------------------------------------- keepalive
 *
 * Render's free plan spins an instance down after ~15 minutes with no inbound
 * traffic, which kills every table in memory. While this tab is open and its
 * player is around, we poke the server on a timer; the request reaching the
 * server is the whole mechanism. Pinging stops once you have been idle a
 * while, so a forgotten tab does not hold the instance up by itself — and the
 * button forces a ping and restarts the clock.
 *
 * This cannot help when nobody has the page open. Nothing client-side can.
 */

const KA = { lastPing: 0, lastSeen: Date.now(), uptime: null, waking: false };

function keepaliveInit() {
  $('keepalive-button').addEventListener('click', () => {
    KA.lastSeen = Date.now();
    pingServer();
  });
  for (const ev of ['pointerdown', 'keydown', 'wheel']) {
    window.addEventListener(ev, () => { KA.lastSeen = Date.now(); }, { passive: true });
  }
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) { KA.lastSeen = Date.now(); pingServer(); }
  });
  pingServer();
  setInterval(keepaliveTick, 1000);
}

async function pingServer() {
  KA.waking = true;
  renderKeepalive();
  try {
    const res = await fetch('/api/keepalive', { cache: 'no-store' });
    const data = await res.json();
    KA.uptime = data.uptime;
    KA.lastPing = Date.now();
  } catch (e) {
    KA.lastPing = 0;
  }
  KA.waking = false;
  renderKeepalive();
}

function keepaliveTick() {
  const idleFor = (Date.now() - KA.lastSeen) / 1000;
  const since = (Date.now() - KA.lastPing) / 1000;
  if (idleFor < S.cfg.keepalive_idle_limit && since >= S.cfg.keepalive_interval) {
    pingServer();
  }
  renderKeepalive();
}

function clock(seconds) {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function renderKeepalive() {
  const box = $('keepalive');
  const text = $('keepalive-text');
  if (!S.cfg) return;
  const idleFor = (Date.now() - KA.lastSeen) / 1000;
  const since = (Date.now() - KA.lastPing) / 1000;
  box.classList.toggle('idle', idleFor >= S.cfg.keepalive_idle_limit);
  box.classList.toggle('waking', KA.waking);

  if (KA.waking) {
    text.textContent = 'waking server…';
  } else if (!KA.lastPing) {
    text.textContent = 'server unreachable';
  } else if (idleFor >= S.cfg.keepalive_idle_limit) {
    text.textContent = `idle ${clock(idleFor)} — sleeps in ${clock(S.cfg.spindown_estimate - since)}`;
  } else {
    text.textContent = `awake · next ping ${clock(S.cfg.keepalive_interval - since)}`;
  }
  $('keepalive-button').title =
    'Send a signal to keep the server from sleeping. It does nothing to the game.';
}

/* ------------------------------------------------------------------ rules
 *
 * Opened in its own tab so it can sit beside the game. The text is built
 * server-side from the table's own settings, so a table that has changed the
 * toad's VP or how gold behaves reads rules that say so.
 */

async function renderRules() {
  const code = new URLSearchParams(location.search).get('code');
  const res = await fetch('/api/rules' + (code ? '?code=' + encodeURIComponent(code) : ''));
  const data = await res.json();
  showScreen('rules');
  if (data.error) {
    $('rules-title').textContent = 'Rules';
    $('rules-summary').textContent = data.error;
    return;
  }
  document.title = 'Rules — Kingdom of Toads';
  $('rules-title').textContent = data.title;
  $('rules-summary').textContent = data.summary;

  const changed = $('rules-changed');
  changed.innerHTML = '';
  if (data.changed.length) {
    changed.appendChild(el('h3', null, 'Changed from the defaults'));
    const list = el('ul', 'rules-changed-list');
    for (const c of data.changed) {
      list.appendChild(el('li', null, `${c.label}: ${c.value} (default ${c.default})`));
    }
    changed.appendChild(list);
  }

  const body = $('rules-body');
  body.innerHTML = '';
  for (const section of data.sections) {
    body.appendChild(el('h3', 'rules-heading', section.heading));
    for (const block of section.blocks) {
      if (block.kind === 'p') {
        body.appendChild(el('p', null, block.text));
      } else if (block.kind === 'ul') {
        const list = el('ul');
        block.items.forEach((i) => list.appendChild(el('li', null, i)));
        body.appendChild(list);
      } else if (block.kind === 'table') {
        const table = el('table', 'scoreboard rules-table');
        const head = el('tr');
        block.head.forEach((h) => head.appendChild(el('th', null, h)));
        table.appendChild(head);
        for (const row of block.rows) {
          const tr = el('tr');
          row.forEach((c) => tr.appendChild(el('td', null, c)));
          table.appendChild(tr);
        }
        body.appendChild(table);
      }
    }
  }
}

/* ------------------------------------------------------------------ boot */

async function boot() {
  if (location.pathname === '/rules') return renderRules();
  S.cfg = await (await fetch('/api/config')).json();
  S.catalog = await (await fetch('/api/cards')).json();
  keepaliveInit();
  cardTipInit();
  setInterval(tickTimer, 1000);
  renderSeatConfig();
  renderTuningForm();

  $('player-count').addEventListener('change', renderSeatConfig);
  $('rounds').addEventListener('input', renderTuningPreview);
  $('tuning-reset').addEventListener('click', resetTuning);
  $('create-table').addEventListener('click', createTable);
  $('join-table').addEventListener('click', joinTable);
  $('start-game').addEventListener('click', startGame);

  const code = codeFromUrl();
  if (code) {
    $('join-code').value = code;
    const token = localStorage.getItem('kot:token:' + code);
    if (token) {
      S.code = code;
      S.token = token;
      S.hostToken = localStorage.getItem('kot:host:' + code);
      connect();
    } else {
      $('home-error').textContent = 'Enter your name to take a seat at table ' + code + '.';
    }
  }
}

function codeFromUrl() {
  const m = location.pathname.match(/^\/t\/([A-Za-z0-9]+)/);
  if (m) return m[1].toUpperCase();
  const q = new URLSearchParams(location.search).get('code');
  return q ? q.toUpperCase() : null;
}

/* ------------------------------------------------------------- home form */

function renderSeatConfig() {
  const n = parseInt($('player-count').value, 10);
  const host = $('seat-config');
  host.innerHTML = '';
  for (let i = 1; i < n; i++) {
    const row = el('div', 'seat-row');
    row.appendChild(el('span', 'seat-name', 'Seat ' + (i + 1)));
    const kind = el('select');
    kind.dataset.seat = String(i);
    kind.className = 'seat-kind';
    for (const [v, t] of [['bot', 'Bot'], ['human', 'Human (join by link)']]) {
      const o = el('option', null, t); o.value = v; kind.appendChild(o);
    }
    const strat = el('select');
    strat.className = 'seat-strategy';
    for (const name of ['farmer', 'miner', 'warlord', 'balanced']) {
      const o = el('option', null, name[0].toUpperCase() + name.slice(1));
      o.value = name;
      strat.appendChild(o);
    }
    strat.value = ['farmer', 'miner', 'warlord', 'balanced'][(i - 1) % 4];
    kind.addEventListener('change', () => { strat.hidden = kind.value !== 'bot'; });
    row.appendChild(kind);
    row.appendChild(strat);
    host.appendChild(row);
  }
}

/* ------------------------------------------------------------ tuning form
 *
 * The balance numbers are per-table, not global: they are stored with the game
 * so a finished table keeps the values it was played with, and two tables can
 * run different ones at once. The form builds itself from /api/config, so
 * adding a field to config.TUNING_FIELDS is all it takes to expose it here.
 *
 * Values are also remembered in localStorage, so the next table you create
 * starts from the numbers you last used rather than the defaults.
 */

const TUNING_STORE = 'kot:tuning';
const GROUP_LABEL = {
  start: 'Starting resources',
  recruit: 'Recruiting',
  auction: 'Auction floor',
  scoring: 'End-game scoring',
  fields: 'Fields majority',
  mine: 'Mine majority',
  rest: 'Rest majority',
  war: 'War token',
};

function savedTuning() {
  try {
    return JSON.parse(localStorage.getItem(TUNING_STORE)) || {};
  } catch (e) {
    return {};
  }
}

function renderTuningForm() {
  const host = $('tuning-groups');
  host.innerHTML = '';
  const saved = savedTuning();
  const groups = [];
  for (const f of S.cfg.tuning_fields) {
    if (!groups.includes(f.group)) groups.push(f.group);
  }
  for (const group of groups) {
    const box = el('div', 'tuning-group');
    box.appendChild(el('h4', null, GROUP_LABEL[group] || group));
    const row = el('div', 'form-row');
    for (const f of S.cfg.tuning_fields.filter((x) => x.group === group)) {
      const label = el('label', null, f.label);
      label.title = f.help;
      const input = el('input');
      input.type = 'number';
      input.min = String(f.min);
      input.max = String(f.max);
      input.dataset.tuning = f.key;
      input.value = String(saved[f.key] !== undefined ? saved[f.key] : f.default);
      input.addEventListener('input', renderTuningPreview);
      label.appendChild(input);
      row.appendChild(label);
    }
    box.appendChild(row);
    host.appendChild(box);
  }
  renderTuningPreview();
}

function tuningValues() {
  const out = {};
  document.querySelectorAll('[data-tuning]').forEach((input) => {
    const n = parseInt(input.value, 10);
    if (!Number.isNaN(n)) out[input.dataset.tuning] = n;
  });
  return out;
}

/* The curves are (base + step x round) / divisor rounded up, which is hard to
 * hold in your head. Show what the numbers actually produce, round by round. */
function renderTuningPreview() {
  const t = tuningValues();
  const rounds = Math.max(1, Math.min(10, parseInt($('rounds').value, 10) || 6));
  const host = $('tuning-preview');
  host.innerHTML = '';
  const table = el('table', 'scoreboard');
  const head = el('tr');
  ['Round', 'Fields', 'Mine', 'Rest', 'War token'].forEach((h) => {
    head.appendChild(el('th', null, h));
  });
  table.appendChild(head);
  const curve = (area, r) => Math.ceil(
    (t[`${area}_bonus_base`] + t[`${area}_bonus_per_round`] * r)
    / Math.max(1, t[`${area}_bonus_divisor`]));
  for (let r = 1; r <= rounds; r++) {
    const tr = el('tr');
    tr.appendChild(el('td', null, 'R' + r));
    tr.appendChild(el('td', null, '+' + curve('fields', r)));
    tr.appendChild(el('td', null, '+' + curve('mine', r)));
    tr.appendChild(el('td', null, '+' + curve('rest', r)));
    tr.appendChild(el('td', null, (t.war_token_base + t.war_token_per_round * r) + ' VP'));
    table.appendChild(tr);
  }
  host.appendChild(el('h4', null, 'What that produces'));
  host.appendChild(table);
  host.appendChild(el('p', 'hint',
    `A toad scores ${t.vp_per_toad} VP. End-game majorities: `
    + `${t.vp_most_happiness} happiness / ${t.vp_most_gold} gold / `
    + `${t.vp_most_flies} flies.`));
}

function resetTuning() {
  localStorage.removeItem(TUNING_STORE);
  renderTuningForm();
}

function seatSpecs() {
  const specs = [{ index: 0, kind: 'human' }];
  document.querySelectorAll('.seat-kind').forEach((sel) => {
    const i = parseInt(sel.dataset.seat, 10);
    const strat = sel.parentElement.querySelector('.seat-strategy').value;
    specs.push(sel.value === 'bot'
      ? { index: i, kind: 'bot', strategy: strat }
      : { index: i, kind: 'human' });
  });
  return specs;
}

async function createTable() {
  const body = {
    name: $('host-name').value || 'Player 1',
    player_count: parseInt($('player-count').value, 10),
    rounds: parseInt($('rounds').value, 10),
    auction_mode: $('auction-mode').value,
    timeout_seconds: parseInt($('timer').value, 10),
    tuning: tuningValues(),
    seats: seatSpecs(),
  };
  localStorage.setItem(TUNING_STORE, JSON.stringify(body.tuning));
  const res = await fetch('/api/tables', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (data.error) { $('home-error').textContent = data.error; return; }
  S.code = data.code; S.token = data.token; S.hostToken = data.host_token;
  localStorage.setItem('kot:token:' + S.code, S.token);
  localStorage.setItem('kot:host:' + S.code, S.hostToken);
  history.replaceState({}, '', '/t/' + S.code);
  connect();
}

async function joinTable() {
  const code = ($('join-code').value || '').trim().toUpperCase();
  if (!code) return;
  const res = await fetch('/api/tables/' + code + '/join', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: $('join-name').value || 'Player' }),
  });
  const data = await res.json();
  if (data.error) { $('home-error').textContent = data.error; return; }
  S.code = data.code; S.token = data.token;
  localStorage.setItem('kot:token:' + S.code, S.token);
  history.replaceState({}, '', '/t/' + S.code);
  connect();
}

async function setSeatKind(index, kind) {
  const res = await fetch(
    '/api/tables/' + S.code + '/seat?token=' + encodeURIComponent(S.hostToken || ''),
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ index, kind }),
    });
  const data = await res.json();
  if (data.error) $('action-error').textContent = data.error;
}

async function startGame() {
  const res = await fetch(
    '/api/tables/' + S.code + '/start?token=' + encodeURIComponent(S.hostToken || ''),
    { method: 'POST' });
  const data = await res.json();
  if (data.error) $('lobby-error').textContent = data.error;
}

/* -------------------------------------------------------------- socket */

/* An idle WebSocket is fair game for any proxy in between — Render will drop
 * one after about a minute of silence — so the socket has to say something
 * periodically even when nobody is playing. The server answers with a pong we
 * can safely ignore. */
const WS_PING_SECONDS = 25;
const RECONNECT_MAX_SECONDS = 10;

function connect() {
  if (S.ws) { try { S.ws.close(); } catch (e) { /* ignore */ } }
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${proto}://${location.host}/ws/${S.code}?token=${encodeURIComponent(S.token || '')}`;
  const ws = new WebSocket(url);
  S.ws = ws;

  ws.onopen = () => {
    S.attempts = 0;
    clearInterval(S.heartbeat);
    S.heartbeat = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, WS_PING_SECONDS * 1000);
  };

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'state') {
      S.table = msg.table;
      S.view = msg.view;
      S.timer = { left: msg.table.seconds_left, at: Date.now() };
      render();
      tickTimer();
    } else if (msg.type === 'error') {
      if (msg.code === 'no_table') {
        // Retrying cannot help: this table is gone for good.
        S.gone = true;
        $('status-line').innerHTML = '<span class="waiting">This table no longer '
          + 'exists — it expired, or the server was restarted and lost it.</span>';
        return;
      }
      $('action-error').textContent = msg.message;
      $('lobby-error').textContent = msg.message;
    }
  };

  ws.onclose = () => {
    clearInterval(S.heartbeat);
    if (S.gone) return;
    S.attempts = (S.attempts || 0) + 1;
    const wait = Math.min(RECONNECT_MAX_SECONDS, 2 ** (S.attempts - 1));
    $('status-line').innerHTML =
      `<span class="waiting">Disconnected — reconnecting in ${wait}s `
      + `(attempt ${S.attempts})</span>`;
    clearTimeout(S.retry);
    S.retry = setTimeout(connect, wait * 1000);
  };
}

function wsSend(message) {
  // Clicking before the socket is up used to fail silently, which looks
  // exactly like a broken button.
  if (!S.ws || S.ws.readyState !== WebSocket.OPEN) {
    $('action-error').textContent = 'Not connected yet — try again in a moment.';
    return false;
  }
  S.ws.send(JSON.stringify(message));
  return true;
}

function send(action) {
  $('action-error').textContent = '';
  wsSend({ type: 'action', action });
}

/* --------------------------------------------------------- pause & votes
 *
 * Nobody is ever replaced by a timer alone. When a phase clock runs out the
 * table is asked about the player holding it up — one question per player, so
 * two people going quiet produce two independent decisions. One yes replaces
 * that seat with a bot; everybody saying no restarts the clock. Pausing turns
 * the whole mechanism off.
 */

function renderPause() {
  const btn = $('pause-button');
  const t = S.table;
  const seated = t && t.you;
  btn.hidden = !(seated && t.status === 'in_progress');
  if (btn.hidden) return;
  btn.dataset.paused = String(Boolean(t.paused));
  btn.textContent = t.paused ? '▶ Resume' : '⏸ Pause';
  btn.title = t.paused
    ? 'Restart the phase clock'
    : 'Stop the clock — nobody can be voted out while paused';
  btn.onclick = () => wsSend({ type: 'pause', paused: !t.paused });
}

function renderVotes() {
  const overlay = $('vote-overlay');
  const host = $('vote-cards');
  const t = S.table;
  const v = S.view;
  const votes = (t && t.votes) || [];
  if (!votes.length || !v) {
    overlay.hidden = true;
    host.innerHTML = '';
    return;
  }

  host.innerHTML = '';
  let shown = 0;
  for (const vote of votes) {
    const iAmSubject = vote.subject === t.you;
    const canVote = vote.eligible.includes(t.you) && !vote.declined.includes(t.you);
    const waited = vote.declined.includes(t.you);
    if (!iAmSubject && !canVote && !waited) continue;
    shown += 1;

    const card = el('div', 'vote-card' + (iAmSubject ? ' subject' : ''));
    if (iAmSubject) {
      card.appendChild(el('h3', null, 'The table is waiting on you'));
      const p = el('p');
      p.innerHTML = 'They are deciding whether to hand your seat to a bot. '
        + '<b>Commit your move and this goes away.</b>';
      card.appendChild(p);
    } else {
      card.appendChild(el('h3', null, `Replace ${nameOf(v, vote.subject)} with a bot?`));
      const p = el('p');
      p.innerHTML = `<span class="who">${nameOf(v, vote.subject)}</span> has not `
        + 'committed and the clock ran out. If anyone says yes, their seat becomes '
        + 'a bot for the rest of the game. If everyone says no, the clock restarts.';
      card.appendChild(p);
      if (canVote) {
        const buttons = el('div', 'buttons');
        const yes = el('button', 'danger', 'Yes, replace them');
        yes.onclick = () => sendVote(vote.subject, true);
        const no = el('button', 'primary', 'No, keep waiting');
        no.onclick = () => sendVote(vote.subject, false);
        buttons.appendChild(no);
        buttons.appendChild(yes);
        card.appendChild(buttons);
      } else {
        card.appendChild(el('p', 'hint', 'You said keep waiting. Waiting on the others…'));
      }
    }
    const tally = el('div', 'tally');
    const outstanding = vote.eligible.filter((p) => !vote.declined.includes(p));
    tally.innerHTML = `<span class="countdown" data-vote="${vote.subject}"></span>`
      + (outstanding.length
        ? ` · still to answer: ${outstanding.map((p) => nameOf(v, p)).join(', ')}`
        : '');
    card.appendChild(tally);
    host.appendChild(card);
  }
  overlay.hidden = shown === 0;
  tickVotes();
}

function sendVote(subject, kick) {
  wsSend({ type: 'vote', subject, kick });
}

function tickVotes() {
  const votes = (S.table && S.table.votes) || [];
  for (const vote of votes) {
    const box = document.querySelector(`[data-vote="${vote.subject}"]`);
    if (!box) continue;
    const left = vote.seconds_left - (Date.now() - S.timer.at) / 1000;
    box.textContent = left > 0
      ? `${clock(left)} to decide`
      : 'deciding…';
  }
}

/* -------------------------------------------------------------- render */

function render() {
  const t = S.table;
  if (!t) return;
  $('table-code').textContent = 'Table ' + t.code;
  $('rules-link').href = '/rules?code=' + encodeURIComponent(t.code);
  showScreen(t.status === 'lobby' ? 'lobby' : 'game');
  if (t.status === 'lobby') renderLobby();
  else renderGame();
  renderPause();
  renderVotes();
}

function showScreen(which) {
  for (const name of ['home', 'lobby', 'game', 'rules']) {
    $('screen-' + name).hidden = name !== which;
  }
}

function renderLobby() {
  const t = S.table;
  $('share-url').textContent = location.origin + '/t/' + t.code;
  const body = $('lobby-seats');
  body.innerHTML = '';
  for (const seat of t.seats) {
    const tr = el('tr');
    tr.appendChild(el('td', null, String(seat.index + 1)));
    const who = el('td');
    who.textContent = seat.kind === 'bot'
      ? `${seat.name} (${seat.strategy})`
      : (seat.claimed ? seat.name : '— open —');
    if (seat.player_id === t.you) who.appendChild(el('span', 'pill', ' you'));
    tr.appendChild(who);
    const st = el('td');
    if (seat.kind === 'bot') st.textContent = 'bot';
    else if (!seat.claimed) st.textContent = 'waiting for a player';
    else st.appendChild(el('span', seat.connected ? 'pill ready' : 'pill', seat.connected ? 'connected' : 'away'));
    tr.appendChild(st);
    body.appendChild(tr);
  }
  const tune = t.tuning || {};
  $('lobby-settings').textContent =
    `${t.rounds} rounds · ${t.auction_mode} auction · ${t.seats.length} players`
    + ` · ${t.timeout_seconds}s per phase`
    + ` · ${tune.vp_per_toad} VP a toad`
    + ` · majorities ${tune.vp_most_happiness}/${tune.vp_most_gold}/${tune.vp_most_flies}`;
  // The socket only carries our seat token, so the server cannot tell from it
  // whether we are the host. Holding the host token locally is the signal; the
  // server still checks it for real when /start is called.
  const open = t.seats.filter((s) => s.kind === 'human' && !s.claimed).length;
  const start = $('start-game');
  start.hidden = !(t.is_host || S.hostToken);
  start.disabled = open > 0;
  start.textContent = open
    ? `Waiting for ${open} more player${open > 1 ? 's' : ''}…`
    : 'Start game';
  $('status-line').textContent = 'Lobby';
}

function renderGame() {
  const v = S.view;
  if (!v) return;
  const me = v.players.find((p) => p.id === v.you) || v.players[0];

  renderStatus(v);
  renderResources(me, v);
  renderHappiness(me);
  renderMat(me, v);
  renderMyCards(me, v);
  renderOpponents(v);
  renderAuction(v);
  renderAction(v, me);
  renderLog(v);
}

function renderStatus(v) {
  const names = (ids) => ids.map((id) => nameOf(v, id)).join(', ');
  const phase = {
    recruit: 'Recruitment', auction: 'Auction',
    placement: 'Placement', feed: 'Feeding', finished: 'Finished',
  }[v.phase] || v.phase;
  let text = `Round <b class="num">${v.round}</b> / ${v.rounds} · <span class="phase">${phase}</span>`;
  if (v.phase !== 'finished') {
    text += v.waiting_on.length
      ? ` · <span class="waiting">waiting on ${names(v.waiting_on)}</span>`
      : ' · resolving…';
  }
  if (v.development) {
    const stage = v.development === 'city' ? 'City' : 'Village';
    text += ` \u00b7 <span class="stage ${v.development}">${stage}</span>`;
  }
  text += ' <span id="phase-timer"></span>';
  $('status-line').innerHTML = text;
}

/* The countdown updates on its own interval and touches only its own element:
 * re-rendering the whole board every second would wipe out whatever the player
 * is halfway through typing into a bid or recruit box. */
function tickTimer() {
  tickVotes();
  const box = $('phase-timer');
  if (!box) return;
  if (S.table && S.table.paused) {
    box.textContent = '· PAUSED';
    box.className = 'paused';
    return;
  }
  if ((S.table && S.table.votes && S.table.votes.length)) {
    box.textContent = '· the table is deciding';
    box.className = 'timer urgent';
    return;
  }
  if (S.timer.left === null || S.timer.left === undefined) {
    box.textContent = '';
    box.className = '';
    return;
  }
  const left = S.timer.left - (Date.now() - S.timer.at) / 1000;
  if (left <= 0) {
    box.textContent = '· time up';
    box.className = 'timer urgent';
    return;
  }
  box.textContent = `· ${clock(left)} left`;
  box.className = left <= 15 ? 'timer urgent' : 'timer';
}

function renderResources(me, v) {
  const box = $('my-resources');
  box.innerHTML = '';
  const items = [
    ['flies', 'flies', me.flies], ['gold', 'gold', me.gold],
    ['toads', 'toads', me.toads], ['happiness', 'happy', me.happiness],
  ];
  for (const [cls, label, value] of items) {
    const d = el('div', 'res ' + cls);
    d.appendChild(el('div', 'v', String(value)));
    d.appendChild(el('div', 'k', label));
    box.appendChild(d);
  }
}

function bandOf(h) {
  return S.cfg.recruit_bands.find(([lo, hi]) => h >= lo && h <= hi);
}

function renderHappiness(me) {
  const host = $('happiness-track');
  host.innerHTML = '';
  const wrap = el('div', 'track');
  const cells = el('div', 'track-cells');
  const bands = S.cfg.recruit_bands.slice().sort((a, b) => a[0] - b[0]);
  for (let h = S.cfg.happiness_min; h <= S.cfg.happiness_max; h++) {
    const idx = bands.findIndex(([lo, hi]) => h >= lo && h <= hi);
    const c = el('div', 'cell b' + (idx + 1), h % 5 === 0 || h === 1 ? String(h) : '');
    if (bands[idx][0] === h) c.classList.add('band-start');
    if (h === me.happiness) { c.classList.add('here'); c.textContent = String(h); }
    c.title = `${h} happiness — ${bands[idx][2]} flies per toad`;
    cells.appendChild(c);
  }
  wrap.appendChild(cells);

  const legend = el('div', 'track-legend');
  for (const [lo, hi, cost] of bands) {
    const s = el('span', null, `${lo}–${hi}: ${cost}`);
    s.style.flex = String(hi - lo + 1);
    legend.appendChild(s);
  }
  wrap.appendChild(legend);

  const band = bandOf(me.happiness);
  const cap = S.cfg.happiness_max;
  const caption = el('div', 'track-caption');
  let text = `Recruiting costs <b>${band[2]}</b> ${band[2] === 1 ? 'fly' : 'flies'} per toad.`;
  if (band[1] < cap) {
    const need = band[1] + 1 - me.happiness;
    const next = bandOf(band[1] + 1);
    text += ` <b>+${need}</b> happiness reaches the ${next[0]}–${next[1]} band (${next[2]}).`;
  } else {
    text += ' You are in the cheapest band.';
  }
  if (me.happiness > S.cfg.happiness_min) {
    const drop = me.happiness - band[0] + 1;
    text += ` <span class="muted">−${drop} drops a band.</span>`;
  }
  caption.innerHTML = text;
  wrap.appendChild(caption);
  host.appendChild(wrap);
}

function currentPlacement(me, v) {
  const key = `${v.round}:${v.phase}:${me.toads}`;
  if (v.phase === 'placement' && !v.your_commitment) {
    if (S.draftKey !== key) {
      S.draftKey = key;
      S.draft = { fields: 0, mine: 0, military: 0, rest: 0 };
    }
    return S.draft;
  }
  if (v.phase === 'placement' && v.your_commitment) return v.your_commitment.placement;
  return me.last_placement || {};
}

function renderMat(me, v) {
  const host = $('my-mat');
  host.innerHTML = '';
  const placement = currentPlacement(me, v);
  const editable = v.phase === 'placement' && !v.your_commitment
    && v.waiting_on.includes(v.you);

  const rates = {
    fields: '+2 flies / toad', mine: '+2 gold / toad',
    rest: '+1 happiness / toad', military: 'no production',
  };
  const bonuses = {
    fields: `Majority <b>+${v.bonuses.fields}</b> flies`,
    mine: `Majority <b>+${v.bonuses.mine}</b> gold`,
    rest: `Majority <b>+${v.bonuses.rest}</b> happiness`,
    military: `War token <b>${v.bonuses.war_token_vp}</b> VP`,
  };

  for (const area of ['fields', 'mine', 'military', 'rest']) {
    const box = el('div', 'area ' + area);
    box.appendChild(el('div', 'name', AREA_LABEL[area]));
    box.appendChild(el('div', 'count', String(placement[area] || 0)));
    box.appendChild(el('div', 'rate', rates[area]));
    const b = el('div', 'bonus');
    b.innerHTML = bonuses[area];
    box.appendChild(b);
    const rules = v.tuning || {};
    if (area === 'rest' && rules.rest_empty_penalty && !(placement.rest || 0)) {
      const warn = el('div', 'bonus warn');
      warn.innerHTML = `Empty: <b>\u2212${rules.rest_empty_penalty}</b> happiness`;
      box.appendChild(warn);
    }
    if (area === 'military' && rules.war_tribute) {
      const note = el('div', 'bonus');
      note.innerHTML = `Losers pay <b>${rules.war_tribute}</b> to the winner`;
      box.appendChild(note);
    }
    if (editable) {
      const st = el('div', 'stepper');
      const minus = el('button', null, '−');
      const plus = el('button', null, '+');
      const placed = Object.values(S.draft).reduce((a, b2) => a + b2, 0);
      minus.disabled = !(S.draft[area] > 0);
      plus.disabled = placed >= me.toads;
      minus.onclick = () => { S.draft[area]--; renderGame(); };
      plus.onclick = () => { S.draft[area]++; renderGame(); };
      st.appendChild(minus); st.appendChild(plus);
      box.appendChild(st);
    }
    host.appendChild(box);
  }
}

function cardChip(id) {
  const c = S.catalog[id] || { name: id, group: '', vp: 0, text: '' };
  const chip = el('span', 'card-chip ' + c.group, c.name);
  chip.appendChild(el('span', 'vp', c.vp ? c.vp + 'vp' : '★'));
  // The tooltip is wired by delegation, so it survives every re-render.
  chip.dataset.card = id;
  chip.tabIndex = 0;
  return chip;
}

/* ------------------------------------------------------------ card tooltip
 *
 * Every card on the table is public, including the ones your opponents have
 * already bought — so any card anywhere should explain itself on hover, not
 * just your own. Native title tooltips took a second to appear and dropped the
 * VP value and the toad requirement, both of which you need in order to read
 * what a rival's engine actually does.
 */

const KIND_NOTE = {
  engine: 'Fires every round during placement, while the requirement is met.',
  activated: 'Yours to use, or not, in any feeding phase.',
  instant: 'Fired once, at the moment it was bought.',
  flat: 'No effect. Just points.',
  conditional: 'Counted once, at the end of the game.',
};
const KIND_LABEL = {
  engine: 'Engine', instant: 'Instant', activated: 'Activated',
  flat: 'Scoring', conditional: 'Scoring — conditional',
};

function showCardTip(target) {
  const c = S.catalog[target.dataset.card];
  if (!c) return;
  const tip = $('card-tip');
  tip.innerHTML = '';

  const head = el('div', 'tip-head');
  head.appendChild(el('span', 'tip-name', c.name));
  // Conditional scorers have no printed VP — the effect line carries it.
  head.appendChild(el('span', 'tip-vp', c.vp ? `${c.vp} VP` : 'VP varies'));
  tip.appendChild(head);
  const stage = c.development === 'city' ? 'City' : 'Village';
  tip.appendChild(el('div', 'tip-kind',
    `${stage} \u00b7 ${KIND_LABEL[c.group] || c.group}`));

  if (c.requirement) {
    const [area, count] = c.requirement;
    tip.appendChild(el('div', 'tip-needs',
      `Needs ${count} toads in ${AREA_LABEL[area]}`));
  }
  tip.appendChild(el('div', 'tip-effect', c.text));
  tip.appendChild(el('div', 'tip-when', KIND_NOTE[c.group] || ''));

  tip.hidden = false;
  const box = target.getBoundingClientRect();
  const size = tip.getBoundingClientRect();
  const gap = 8;
  // Above by preference, below if the top of the window is in the way.
  let top = box.top - size.height - gap;
  if (top < gap) top = box.bottom + gap;
  const left = Math.max(
    gap, Math.min(box.left, window.innerWidth - size.width - gap));
  tip.style.top = `${top}px`;
  tip.style.left = `${left}px`;
}

function hideCardTip() {
  $('card-tip').hidden = true;
}

function cardTipInit() {
  // Delegated: chips are rebuilt on every state push, and rebinding each one
  // would leak listeners.
  document.addEventListener('mouseover', (e) => {
    const target = e.target.closest('[data-card]');
    if (target) showCardTip(target);
  });
  document.addEventListener('mouseout', (e) => {
    if (e.target.closest('[data-card]')) hideCardTip();
  });
  document.addEventListener('focusin', (e) => {
    const target = e.target.closest('[data-card]');
    if (target) showCardTip(target);
  });
  document.addEventListener('focusout', hideCardTip);
  window.addEventListener('scroll', hideCardTip, { passive: true });
}

function renderMyCards(me, v) {
  const host = $('my-cards');
  host.innerHTML = '';
  if (!me.cards.length) host.appendChild(el('span', 'hint', 'No property yet.'));
  me.cards.forEach((id) => host.appendChild(cardChip(id)));
  $('my-vp').textContent = `· ${v.projected_scores[me.id]} VP projected`;
}

function nameOf(v, id) {
  const p = v.players.find((x) => x.id === id);
  return p ? p.name : id;
}

function seatOf(id) {
  return (S.table.seats || []).find((s) => s.player_id === id);
}

function renderOpponents(v) {
  const host = $('opponents');
  host.innerHTML = '';
  const order = v.seat_order || v.players.map((p) => p.id);
  for (const pid of order) {
    const p = v.players.find((x) => x.id === pid);
    const seat = seatOf(pid) || {};
    const box = el('div', 'opponent' + (pid === v.you ? ' self' : ''));

    const head = el('div', 'head');
    if (pid === v.first_player) head.appendChild(el('span', 'marker', '★'));
    head.appendChild(el('span', 'who', p.name + (seat.kind === 'bot' ? ' 🤖' : '')));
    if (seat.kind === 'human') {
      head.appendChild(el('span', 'dot ' + (seat.connected ? 'on' : 'off')));
    }
    if (v.phase !== 'finished') {
      if (p.committed) head.appendChild(el('span', 'pill ready', 'ready'));
      else if (p.waiting_on) head.appendChild(el('span', 'pill thinking', 'deciding'));
    }
    if (isHost() && v.phase !== 'finished' && seat.index !== undefined) {
      // If someone has gone for good, the host can hand their seat to a bot
      // permanently. Their token is kept, so it can be handed back.
      const flip = el('button', 'ghost tiny',
        seat.kind === 'bot' ? '→ human' : '→ bot');
      flip.title = seat.kind === 'bot'
        ? 'Give this seat back to its player'
        : 'Hand this seat to a bot for the rest of the game';
      flip.onclick = () => setSeatKind(seat.index, seat.kind === 'bot' ? 'human' : 'bot');
      head.appendChild(flip);
    }
    box.appendChild(head);

    const stats = el('div', 'stats');
    stats.appendChild(el('span', 'f', p.flies + ' fly'));
    stats.appendChild(el('span', 'g', p.gold + ' gold'));
    stats.appendChild(el('span', 't', p.toads + ' toad'));
    stats.appendChild(el('span', 'h', p.happiness + ' hap'));
    stats.appendChild(el('span', 'vp', v.projected_scores[pid] + ' VP'));
    box.appendChild(stats);

    const mini = el('div', 'minitrack');
    const bands = S.cfg.recruit_bands.slice().sort((a, b) => a[0] - b[0]);
    for (let h = S.cfg.happiness_min; h <= S.cfg.happiness_max; h++) {
      const idx = bands.findIndex(([lo, hi]) => h >= lo && h <= hi);
      const c = el('div', 'cell b' + (idx + 1));
      if (h === p.happiness) c.classList.add('here');
      mini.appendChild(c);
    }
    box.appendChild(mini);

    const detail = el('div', 'hint');
    const lp = p.last_placement || {};
    const placed = ['fields', 'mine', 'military', 'rest']
      .filter((a) => lp[a]).map((a) => `${AREA_LABEL[a]} ${lp[a]}`).join(' · ');
    detail.textContent = `${p.recruit_cost} flies/toad` +
      (p.war_tokens.length ? ` · ${p.war_tokens.length} war token(s)` : '') +
      (placed ? ` · last round: ${placed}` : '');
    box.appendChild(detail);

    if (p.cards.length) {
      const cards = el('div', 'cards');
      p.cards.forEach((id) => cards.appendChild(cardChip(id)));
      box.appendChild(cards);
    }
    host.appendChild(box);
  }
}

function renderAuction(v) {
  const host = $('auction-panel');
  host.innerHTML = '';
  if (v.phase !== 'auction' || !v.auction) return renderUpcoming(v, host);
  const a = v.auction;

  const head = el('h3', null, `This round's slate — ${a.slate.length} cards, auctioned in order`);
  host.appendChild(head);

  const row = el('div', 'slate');
  a.slate.forEach((entry, i) => {
    const c = S.catalog[entry.card] || { name: entry.card, text: '', vp: 0, group: '' };
    const box = el('div', 'slate-card '
      + (i === a.index ? 'current' : '')
      + (entry.status === 'sold' ? ' done' : '')
      + (entry.status.startsWith('burned') ? ' burned' : ''));
    box.dataset.card = entry.card;
    const title = el('div', 'title', c.name);
    title.appendChild(el('span', 'order', '#' + (i + 1)));
    box.appendChild(title);
    box.appendChild(el('div', 'text', c.text));
    const out = el('div', 'outcome');
    if (entry.status === 'sold') {
      out.textContent = `${nameOf(v, entry.winner)} — ${entry.price} gold`;
    } else if (entry.status === 'burned_tie') {
      out.textContent = 'tied twice — removed';
    } else if (entry.status === 'burned_unsold') {
      out.textContent = 'no bids — removed';
    } else {
      out.textContent = i === a.index ? '◀ on the block' : 'upcoming';
    }
    box.appendChild(out);
    if (entry.status === 'sold' && Object.keys(entry.bids).length > 1) {
      const bids = Object.entries(entry.bids)
        .map(([pid, amt]) => `${nameOf(v, pid)} ${amt}`).join(', ');
      box.appendChild(el('div', 'outcome muted', bids));
    }
    row.appendChild(box);
  });
  host.appendChild(row);
}

/* Next round's slate, revealed the moment this round's auction ends. It is the
 * reason to think about Mine before you place: you already know what is coming
 * up for sale and roughly what it will cost you. */
function renderUpcoming(v, host) {
  if (!v.upcoming || !v.upcoming.length) return;
  host.appendChild(el('h3', null,
    `Next round's slate — ${v.upcoming.length} cards, in this order`));
  const row = el('div', 'slate');
  v.upcoming.forEach((id, i) => {
    const c = S.catalog[id] || { name: id, text: '', vp: 0 };
    const box = el('div', 'slate-card upcoming');
    box.dataset.card = id;
    const title = el('div', 'title', c.name);
    title.appendChild(el('span', 'order', '#' + (i + 1)));
    box.appendChild(title);
    box.appendChild(el('div', 'text', c.text));
    box.appendChild(el('div', 'outcome', `${c.vp} VP · next round`));
    row.appendChild(box);
  });
  host.appendChild(row);
  host.appendChild(el('p', 'hint',
    'Gold you want for these has to be mined this round.'));
}

/* The action panel is the only part of the board with typed input in it, and
 * a state push arrives every time ANY player or bot does anything. Rebuilding
 * it blindly threw away half-typed bids. So rebuild only when something the
 * form actually depends on has changed — which also means a bid you are
 * midway through typing survives a reconnect. */
function actionSignature(v, me) {
  const a = v.auction || {};
  const mine = v.waiting_on.includes(v.you);
  const placed = S.draft
    ? Object.values(S.draft).reduce((x, y) => x + y, 0)
    : -1;
  const parts = [
    v.phase, v.round, mine, Boolean(v.your_commitment),
    me.toads, me.gold, me.flies, me.recruit_cost,
    a.index, a.stage, a.high_bid, a.tied_amount, a.turn, placed,
    S.tribute,
  ];
  // While we are waiting on other people, the panel lists who — so it has to
  // keep up. While it is our turn it must not twitch under our fingers.
  if (!mine) parts.push(v.waiting_on.join(','));
  return parts.join('|');
}

function renderAction(v, me) {
  const host = $('action-panel');
  const signature = actionSignature(v, me);
  if (signature === S.actionSig && host.childElementCount) return;
  S.actionSig = signature;

  host.innerHTML = '';
  const title = $('action-title');
  const myTurn = v.waiting_on.includes(v.you);

  if (v.phase === 'finished') {
    title.textContent = 'Final score';
    host.appendChild(scoreboard(v));
    return;
  }

  if (!myTurn) {
    title.textContent = 'Waiting';
    const done = v.your_commitment;
    host.appendChild(el('p', null, done
      ? 'Your decision is locked in. Waiting for: ' + v.waiting_on.map((id) => nameOf(v, id)).join(', ')
      : 'Waiting for: ' + v.waiting_on.map((id) => nameOf(v, id)).join(', ')));
    if (done) host.appendChild(el('p', 'hint', describeCommitment(done)));
    const floorRules = v.tuning || S.cfg.tuning_defaults;
    if (v.phase === 'auction' && me.gold < floorRules.auction_eligibility) {
      host.appendChild(el('p', 'hint',
        `You hold ${me.gold} gold — ${floorRules.auction_eligibility} is needed `
        + 'to bid at all.'));
    }
    return;
  }

  if (v.phase === 'recruit') return renderRecruit(host, title, me, v);
  if (v.phase === 'auction') return renderBid(host, title, v, me);
  if (v.phase === 'placement') return renderPlacement(host, title, v, me);
  if (v.phase === 'feed') return renderFeed(host, title, me, v);
}

function describeCommitment(c) {
  if (c.type === 'recruit') return `Recruiting ${c.count}.`;
  if (c.type === 'bid') return c.amount ? `Bid ${c.amount} gold.` : 'Passed.';
  if (c.type === 'place') {
    return 'Placement: ' + Object.entries(c.placement)
      .filter(([, n]) => n).map(([a, n]) => `${AREA_LABEL[a]} ${n}`).join(', ');
  }
  if (c.type === 'feed') return `Feeding ${c.keep}.`;
  return '';
}

function renderRecruit(host, title, me, v) {
  title.textContent = 'Recruit toads';
  const rules = v.tuning || {};
  const mode = rules.gold_mode || 0;
  const cost = me.recruit_cost;
  const cap = S.cfg.recruit_cap;
  const goldCost = cost + (rules.recruit_gold_premium || 0);
  const rate = rules.gold_per_fly || 2;

  const maxFlies = Math.min(cap, Math.floor(me.flies / cost));
  const maxGold = mode === 1 ? Math.min(cap, Math.floor(me.gold / goldCost)) : 0;
  const maxTrade = mode === 2 ? Math.floor(me.gold / rate) : 0;

  const row = el('div', 'form-row');
  const input = el('input');
  input.type = 'number'; input.min = '0'; input.value = '0';
  input.max = String(mode === 2 ? cap : maxFlies);
  const label = el('label', null, `With flies, ${cost} each`
    + (mode === 2 ? '' : ` (max ${maxFlies})`));
  label.appendChild(input);
  row.appendChild(label);

  let goldInput = null;
  let tradeInput = null;
  if (mode === 1) {
    goldInput = el('input');
    goldInput.type = 'number'; goldInput.min = '0';
    goldInput.max = String(maxGold); goldInput.value = '0';
    const goldLabel = el('label', null, `With gold, ${goldCost} each (max ${maxGold})`);
    goldLabel.title = 'Priced off your happiness band, plus a premium — the same '
      + 'track that prices flies.';
    goldLabel.appendChild(goldInput);
    row.appendChild(goldLabel);
  } else if (mode === 2) {
    tradeInput = el('input');
    tradeInput.type = 'number'; tradeInput.min = '0';
    tradeInput.max = String(maxTrade); tradeInput.value = '0';
    const tradeLabel = el('label', null, `Buy flies, ${rate} gold each (max ${maxTrade})`);
    tradeLabel.title = 'Converted before you pay, so these flies can buy toads.';
    tradeLabel.appendChild(tradeInput);
    row.appendChild(tradeLabel);
  }

  const preview = el('span', 'hint');
  const read = () => {
    const traded = tradeInput
      ? Math.max(0, Math.min(maxTrade, parseInt(tradeInput.value || '0', 10))) : 0;
    const pool = me.flies + traded;
    const byFlies = Math.max(0, Math.min(
      mode === 2 ? Math.floor(pool / cost) : maxFlies,
      parseInt(input.value || '0', 10)));
    const byGold = goldInput
      ? Math.max(0, Math.min(maxGold, parseInt(goldInput.value || '0', 10))) : 0;
    return { byFlies, byGold, traded, total: byFlies + byGold };
  };
  const update = () => {
    const { byFlies, byGold, traded, total } = read();
    const bits = [];
    if (byFlies) bits.push(`${byFlies * cost} flies`);
    if (byGold) bits.push(`${byGold * goldCost} gold`);
    if (traded) bits.push(`${traded * rate} gold traded for ${traded} flies`);
    preview.textContent = `${total} toads for ${bits.join(' + ') || 'nothing'}`
      + ` — you hold ${me.flies} flies and ${me.gold} gold, and will need `
      + `${me.toads + total} flies to feed everyone.`
      + (total > cap ? `  Over the cap of ${cap}.` : '');
  };
  for (const box of [input, goldInput, tradeInput]) {
    if (box) box.addEventListener('input', update);
  }

  const go = el('button', 'primary', 'Commit');
  go.onclick = () => {
    const { byGold, traded, total } = read();
    send({
      type: 'recruit', count: total,
      gold_count: byGold, exchange: traded * rate,
    });
  };
  row.appendChild(go);
  host.appendChild(row);
  host.appendChild(preview);
  update();
  host.appendChild(el('p', 'hint',
    'Everyone commits secretly and reveals together. Cap is ' + cap
    + ' toads a round.'));
}

function renderBid(host, title, v, me) {
  const a = v.auction;
  const entry = a.slate[a.index];
  const card = S.catalog[entry.card] || { name: entry.card, text: '' };

  if (a.stage === 'live') {
    title.textContent = `Live auction — ${card.name}`;
    const floor = Math.max((v.tuning || S.cfg.tuning_defaults).auction_min_bid, a.high_bid + 1);
    host.appendChild(el('p', null, a.high_bidder
      ? `Standing bid: ${a.high_bid} gold from ${nameOf(v, a.high_bidder)}.`
      : 'No bids yet.'));
    const row = el('div', 'form-row');
    const input = el('input');
    input.type = 'number'; input.min = String(floor); input.max = String(me.gold);
    input.value = String(Math.min(floor, me.gold));
    const label = el('label', null, `Raise to (min ${floor}, you hold ${me.gold})`);
    label.appendChild(input);
    row.appendChild(label);
    const bid = el('button', 'primary', 'Raise');
    bid.disabled = me.gold < floor;
    bid.onclick = () => send({ type: 'bid', amount: parseInt(input.value || '0', 10) });
    const pass = el('button', null, 'Pass');
    pass.onclick = () => send({ type: 'pass' });
    row.appendChild(bid); row.appendChild(pass);
    host.appendChild(row);
    return;
  }

  const rules = v.tuning || S.cfg.tuning_defaults;
  const rebid = a.stage === 'rebid';
  title.textContent = rebid ? `Re-bid — ${card.name}` : `Bid — ${card.name}`;
  if (rebid) {
    host.appendChild(el('p', null,
      `Tied at ${a.tied_amount} gold with `
      + a.tied_players.filter((p) => p !== v.you).map((p) => nameOf(v, p)).join(', ')
      + `. One re-bid only: equal or higher. If you tie again you each pay `
      + `${rules.auction_tie_penalty} gold and the card leaves the game.`));
  }
  const min = rebid ? a.tied_amount : rules.auction_min_bid;
  const row = el('div', 'form-row');
  const input = el('input');
  input.type = 'number'; input.min = String(min); input.max = String(me.gold);
  input.value = String(Math.min(min, me.gold));
  const label = el('label', null, `Bid (min ${min}, you hold ${me.gold})`);
  label.appendChild(input);
  row.appendChild(label);
  const go = el('button', 'primary', rebid ? 'Commit re-bid' : 'Commit bid');
  go.onclick = () => send({ type: 'bid', amount: parseInt(input.value || '0', 10) });
  row.appendChild(go);
  if (!rebid) {
    const pass = el('button', null, 'Pass');
    pass.onclick = () => send({ type: 'bid', amount: 0 });
    row.appendChild(pass);
  }
  host.appendChild(row);
  host.appendChild(el('p', 'hint', card.text));
}

function renderPlacement(host, title, v, me) {
  title.textContent = 'Place your toads';
  const placed = Object.values(S.draft || {}).reduce((a, b) => a + b, 0);
  const left = me.toads - placed;
  const summary = el('p', 'placement-summary');
  summary.innerHTML = left === 0
    ? `All <b>${me.toads}</b> toads placed.`
    : `<b>${left}</b> of <b>${me.toads}</b> toads still to place — use the + buttons on the mat.`;
  host.appendChild(summary);

  const rules = v.tuning || {};
  if (rules.war_tribute) {
    const label = el('label', null,
      `If you lose the war, pay ${rules.war_tribute} in`);
    label.title = 'Declared now, before the war resolves. If the resource you '
      + 'pick runs short, the balance comes out of the other one.';
    const pick = el('select');
    pick.id = 'tribute-pick';
    for (const [value, text] of [['gold', 'Gold'], ['flies', 'Flies']]) {
      const o = el('option', null, text); o.value = value; pick.appendChild(o);
    }
    pick.value = S.tribute || 'gold';
    pick.onchange = () => { S.tribute = pick.value; };
    label.appendChild(pick);
    const wrap = el('div', 'form-row');
    wrap.appendChild(label);
    host.appendChild(wrap);
  }

  const row = el('div', 'form-row');
  const go = el('button', 'primary', 'Commit placement');
  go.disabled = left !== 0;
  go.onclick = () => send({
    type: 'place', placement: S.draft, tribute: S.tribute || 'gold',
  });
  row.appendChild(go);
  const allFields = el('button', null, 'All to Fields');
  allFields.onclick = () => {
    S.draft = { fields: me.toads, mine: 0, military: 0, rest: 0 };
    renderGame();
  };
  const clear = el('button', null, 'Clear');
  clear.onclick = () => {
    S.draft = { fields: 0, mine: 0, military: 0, rest: 0 };
    renderGame();
  };
  row.appendChild(allFields); row.appendChild(clear);
  host.appendChild(row);
  host.appendChild(el('p', 'hint',
    'Ties award no bonus at all — matching a rival exactly is the worst result '
    + 'for both of you, except in Military where a tie also spares the table its '
    + 'happiness loss.'));
}

function renderFeed(host, title, me, v) {
  title.textContent = 'Feed your toads';
  const rules = (v && v.tuning) || {};
  const rate = rules.gold_per_fly || 2;
  const canTrade = rules.gold_mode === 2;
  const traded = canTrade ? Math.min(
    Math.floor(me.gold / rate),
    Math.max(0, me.toads - Math.floor(me.flies / S.cfg.feed_cost))) : 0;
  const max = Math.min(me.toads, Math.floor((me.flies + traded) / S.cfg.feed_cost));
  if (traded) {
    host.appendChild(el('p', 'hint',
      `${traded * rate} gold will be traded for ${traded} flies so that `
      + `${max} toads can eat.`));
  }

  if (me.austerity_cost !== null && me.austerity_cost !== undefined) {
    const box = el('div', 'austerity');
    const go = el('button', 'danger', `Declare austerity (\u2212${me.austerity_cost} happiness)`);
    go.onclick = () => send({ type: 'feed', keep: me.toads, austerity: true });
    box.appendChild(go);
    box.appendChild(el('p', 'hint',
      `Nobody eats and nobody starves: all ${me.toads} toads survive for free, `
      + `and you drop to ${Math.max(1, me.happiness - me.austerity_cost)} happiness.`));
    host.appendChild(box);
  }
  const row = el('div', 'form-row');
  const input = el('input');
  input.type = 'number'; input.min = '0'; input.max = String(max); input.value = String(max);
  const label = el('label', null, `Toads to keep (max ${max})`);
  label.appendChild(input);
  row.appendChild(label);
  const preview = el('p', 'hint');
  const update = () => {
    const keep = Math.max(0, Math.min(max, parseInt(input.value || '0', 10)));
    const starved = me.toads - keep;
    preview.textContent = `Costs ${keep} flies of your ${me.flies}. `
      + (starved
        ? `${starved} toads starve: −${starved} happiness, −${starved * 2} VP.`
        : 'Nobody starves.');
  };
  input.addEventListener('input', update);
  const go = el('button', 'primary', 'Commit');
  go.onclick = () => send({
    type: 'feed', keep: parseInt(input.value || '0', 10),
    exchange: traded * rate,
  });
  row.appendChild(go);
  host.appendChild(row);
  host.appendChild(preview);
  update();
}

function scoreboard(v) {
  const s = v.scores;
  const wrap = el('div');
  const t = el('table', 'scoreboard');
  const head = el('tr');
  const columns = [
    ['', ''],
    ['Toads', `${S.cfg.vp_per_toad} VP each, after the final feeding`],
    ['War', 'War tokens, worth the round they were won in'],
    ['Cards', 'Printed VP on every property you own'],
    ['Conditional', 'Census, Treasury and Hall of Victories, counted at the end'],
    ['Majorities', 'Most happiness, most gold, most flies — 5 VP each, ties award nothing'],
    ['Total', ''],
  ];
  for (const [label, why] of columns) {
    const th = el('th', null, label);
    if (why) th.title = why;
    head.appendChild(th);
  }
  t.appendChild(head);
  for (const pid of s.ranking) {
    const b = s.breakdown[pid];
    const tr = el('tr', s.winners.includes(pid) ? 'winner' : '');
    tr.appendChild(el('td', null, nameOf(v, pid)));
    [b.toads, b.war_tokens, b.cards, b.conditional, b.majorities, b.total]
      .forEach((n) => tr.appendChild(el('td', null, String(n))));
    t.appendChild(tr);
  }
  wrap.appendChild(t);
  const maj = Object.entries(s.end_majorities)
    .map(([k, pid]) => `${k}: ${pid ? nameOf(v, pid) : 'tied — nobody'}`)
    .join(' · ');
  wrap.appendChild(el('p', 'hint', 'End-game majorities — ' + maj));
  return wrap;
}

function renderLog(v) {
  const host = $('log');
  const atBottom = host.scrollTop + host.clientHeight >= host.scrollHeight - 20;
  host.innerHTML = '';
  for (const e of v.log.slice(-80)) {
    if (!e.text) continue;
    const d = el('div', 'entry ' + e.type);
    d.appendChild(el('span', 'r', 'R' + e.round));
    d.appendChild(document.createTextNode(e.text));
    host.appendChild(d);
  }
  if (atBottom) host.scrollTop = host.scrollHeight;
}

boot();
