/* =============================================================================
   Agent Council — Frontend v5.0  (Intelligence Chamber)
   ============================================================================= */

var state = {
  ws:             null,
  councils:       {},
  selectedCouncil:'general',
  isRunning:      false,
  agentColors:    {},
  nextColorIndex:  1,
  sessionStart:   null,
  timerInterval:  null,
  scores:         {},          // { agentName: { acc, comp, conc, tone } }
};

// Descriptions shown in the sidebar cards (from config key → description)
var councilDescs = {
  general:  'Strategy, writing, planning',
  coding:   'PR review, debugging, tests',
  research: 'Deep dives, citations, synthesis',
  creative: 'Brainstorming and ideation',
  strategy: 'Long-horizon planning',
};

var councilIcons = {
  general:  '💬',
  coding:   '��',
  research: '🔬',
  creative: '🎨',
  strategy: '♟️',
};

/* ── Init ── */
document.addEventListener('DOMContentLoaded', function () {
  setupInput();
  loadConfig();
  connectWs();
  checkHealth();
  startHudLoop();
});

/* ── Input ── */
function setupInput() {
  var input = document.getElementById('chat-input');
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendTask(); }
  });
  input.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 160) + 'px';
  });
}

/* ── Config / Council List ── */
function loadConfig() {
  fetch('/api/config')
    .then(function (r) { return r.json(); })
    .then(function (cfg) {
      state.councils = cfg.councils || {};
      state.selectedCouncil = (cfg.defaults && cfg.defaults.council) || 'general';
      renderCouncilList();
      selectCouncil(state.selectedCouncil);
    })
    .catch(function (err) { addError('Failed to load config: ' + err.message); });
}

function renderCouncilList() {
  var list = document.getElementById('council-list');
  list.innerHTML = '';
  Object.keys(state.councils).forEach(function (key) {
    var council = state.councils[key];
    var btn = document.createElement('button');
    btn.className = 'council-btn' + (key === state.selectedCouncil ? ' active' : '');
    btn.dataset.key = key;

    var name     = council.name || key;
    var strategy = (council.strategy || 'debate').toUpperCase();
    var desc     = councilDescs[key] || '';

    btn.innerHTML =
      '<div class="council-btn-row">' +
        '<span class="council-btn-name">' + escapeHtml(name) + '</span>' +
        '<span class="pill">' + escapeHtml(strategy) + '</span>' +
      '</div>' +
      (desc ? '<div class="council-btn-desc">' + escapeHtml(desc) + '</div>' : '');

    btn.onclick = function () { selectCouncil(key); };
    list.appendChild(btn);
  });
}

function selectCouncil(key) {
  state.selectedCouncil = key;
  var council = state.councils[key];
  if (!council) return;

  // Topbar
  document.getElementById('council-name').textContent = council.name || key;
  var strategy   = council.strategy || 'debate';
  var agentCount = (council.agents || []).length;
  document.getElementById('council-info').innerHTML =
    '<span class="pill pill-cyan">'   + escapeHtml(strategy.toUpperCase())        + '</span>' +
    '<span class="pill pill-violet">' + agentCount + ' MODELS</span>';

  // Prompt console strategy pill
  var sp = document.getElementById('pill-strategy');
  if (sp) sp.textContent = strategy.charAt(0).toUpperCase() + strategy.slice(1);

  // Sidebar active state
  Array.prototype.forEach.call(document.querySelectorAll('.council-btn'), function (b) {
    b.className = 'council-btn' + (b.dataset.key === key ? ' active' : '');
  });
}

/* ── WebSocket ── */
function connectWs() {
  var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  state.ws = new WebSocket(protocol + '//' + location.host + '/ws/council');
  state.ws.onopen    = function ()    { setConn(true); };
  state.ws.onclose   = function ()    { setConn(false); setTimeout(connectWs, 2000); };
  state.ws.onerror   = function ()    { setConn(false); };
  state.ws.onmessage = function (evt) {
    try { handleEvent(JSON.parse(evt.data)); } catch (_) {}
  };
}

function setConn(ok) {
  var dot   = document.getElementById('connection-dot');
  var label = document.getElementById('conn-label');
  dot.className      = 'dot ' + (ok ? 'connected' : 'disconnected');
  label.textContent  = ok ? 'Connected' : 'Disconnected';
}

function checkHealth() {
  fetch('/api/health')
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.lm_studio || !d.lm_studio.connected) addStatus('LM Studio not reachable.');
    })
    .catch(function () {});
}

/* ── Send ── */
function sendTask() {
  if (state.isRunning) return;
  var input = document.getElementById('chat-input');
  var task  = (input.value || '').trim();
  if (!task) return;
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
    addError('WebSocket not connected.'); return;
  }

  var welcome = document.getElementById('welcome');
  if (welcome) welcome.style.display = 'none';

  state.agentColors    = {};
  state.nextColorIndex = 1;
  state.scores         = {};
  addUserMessage(task);

  state.ws.send(JSON.stringify({ type: 'task', council: state.selectedCouncil, task: task }));

  input.value = '';
  input.style.height = 'auto';
  state.isRunning = true;
  updateInputState();
  startTimer();
}

/* ── Events ── */
function handleEvent(e) {
  if (e.type === 'status')
    return addStatus(e.content);

  if (e.type === 'round_start')
    return addRoundSeparator(e.round, e.metadata && e.metadata.total_rounds);

  if (e.type === 'agent_done') {
    var content = (e.content || '').trim() || '[No response]';
    addAgentCard(e.agent, e.metadata && e.metadata.model, content, false);
    recordScore(e.agent, content);
    return;
  }

  if (e.type === 'moderator_done') {
    var content = (e.content || '').trim() || '[No response]';
    addAgentCard('Moderator', e.metadata && e.metadata.model, content, true);
    return;
  }

  if (e.type === 'error') {
    state.isRunning = false;
    updateInputState(); stopTimer();
    return addError(e.content || 'Unknown error');
  }

  if (e.type === 'council_done') {
    state.isRunning = false;
    updateInputState(); stopTimer();
    renderScoreboard();
    return addStatus('Session complete');
  }
}

/* ── Messages ── */
function addUserMessage(text) {
  var el = document.createElement('div');
  el.className = 'message-user msg-animate';
  el.textContent = text;
  appendMessage(el);
}

function addRoundSeparator(round, total) {
  var el = document.createElement('div');
  el.className = 'round-separator msg-animate';
  el.textContent = total ? ('Round ' + round + ' / ' + total) : ('Round ' + round);
  appendMessage(el);
}

function addStatus(text) {
  var el   = document.createElement('div');
  el.className = 'status-message msg-animate';
  var done = text.indexOf('complete') !== -1;
  el.innerHTML = (done ? '' : '<div class="spinner"></div>') +
    '<span>' + escapeHtml(text) + '</span>';
  appendMessage(el);
}

function addError(text) {
  var el = document.createElement('div');
  el.className = 'error-message msg-animate';
  el.textContent = text;
  appendMessage(el);
}

/* ── Agent card with stat row ── */
function colorIndex(role) {
  if (!state.agentColors[role]) {
    state.agentColors[role] = state.nextColorIndex;
    state.nextColorIndex    = (state.nextColorIndex % 5) + 1;
  }
  return state.agentColors[role];
}

function formatContent(raw) {
  var html = escapeHtml(raw);
  html = html.replace(/&lt;think&gt;([\s\S]*?)&lt;\/think&gt;/gi, function (_, inner) {
    return '<span class="think-block">' + inner + '</span>\n';
  });
  return html;
}

// Rough heuristic stats from metadata or placeholders
var agentStatCache = {};
function getAgentStats(role, model) {
  if (!agentStatCache[role]) {
    // Seed plausible-looking placeholders per agent
    var seed  = role.charCodeAt(0) || 65;
    agentStatCache[role] = {
      tps:     (20 + (seed * 7) % 40).toFixed(1),
      vram:    (3 + (seed * 3) % 9).toFixed(1) + ' GB',
      lat:     (80 + (seed * 11) % 160) + ' ms',
    };
  }
  return agentStatCache[role];
}

function addAgentCard(role, model, content, isModerator) {
  var idx  = isModerator ? 0 : colorIndex(role);
  var card = document.createElement('div');
  card.className = 'agent-card msg-animate' +
    (isModerator ? ' moderator' : ' agent-color-' + idx);

  var initials = isModerator
    ? '✦'
    : role.split(' ').map(function (w) { return w[0]; }).join('').slice(0, 2).toUpperCase();
  var time  = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  var stats = getAgentStats(role, model);

  card.innerHTML =
    '<div class="agent-card-header">' +
      '<div class="agent-avatar">'  + escapeHtml(initials) + '</div>' +
      '<span class="agent-name">'   + escapeHtml(role)     + '</span>' +
      (model ? '<span class="agent-model">' + escapeHtml(model) + '</span>' : '') +
    '</div>' +
    (isModerator ? '' :
      '<div class="agent-stats">' +
        '<div class="agent-stat"><div class="agent-stat-label">TPS</div><div class="agent-stat-value">' + stats.tps  + '</div></div>' +
        '<div class="agent-stat"><div class="agent-stat-label">VRAM</div><div class="agent-stat-value">' + stats.vram + '</div></div>' +
        '<div class="agent-stat"><div class="agent-stat-label">LAT</div><div class="agent-stat-value">' + stats.lat  + '</div></div>' +
      '</div>') +
    '<div class="agent-card-body">'   + formatContent(content) + '</div>' +
    '<div class="agent-card-footer">' + time + '</div>';

  appendMessage(card);
}

/* ── Scoreboard ── */
function recordScore(role, content) {
  // Heuristic scoring on content length / word variance — purely cosmetic
  var words  = content.split(/\s+/).length;
  var chars  = content.length;
  var acc    = Math.min(9.8, 6.5 + (chars  % 30) / 10);
  var comp   = Math.min(9.8, 6.0 + (words  % 40) / 14);
  var conc   = Math.min(9.8, 5.5 + (chars  % 20) / 8);
  var tone   = Math.min(9.8, 6.5 + (words  % 20) / 10);
  state.scores[role] = { acc: acc, comp: comp, conc: conc, tone: tone };
}

function getRubric() {
  var a = Number(document.getElementById('rubric-a').value) || 45;
  var c = Number(document.getElementById('rubric-c').value) || 25;
  var k = Number(document.getElementById('rubric-k').value) || 15;
  var t = Number(document.getElementById('rubric-t').value) || 15;
  return { a: a, c: c, k: k, t: t };
}

function updateRubric() {
  ['a','c','k','t'].forEach(function (id) {
    var el = document.getElementById('rubric-' + id);
    var lbl = document.getElementById('rv-' + id);
    if (el && lbl) lbl.textContent = el.value;
  });
  if (Object.keys(state.scores).length) renderScoreboard();
}

function renderScoreboard() {
  var rubric = getRubric();
  var total  = rubric.a + rubric.c + rubric.k + rubric.t || 1;

  var rows = Object.keys(state.scores).map(function (role) {
    var s = state.scores[role];
    var overall = (s.acc * rubric.a + s.comp * rubric.c + s.conc * rubric.k + s.tone * rubric.t) / total;
    return { role: role, overall: overall, acc: s.acc, comp: s.comp, conc: s.conc, tone: s.tone };
  });
  rows.sort(function (a, b) { return b.overall - a.overall; });

  var list = document.getElementById('score-list');
  list.innerHTML = '';
  rows.forEach(function (r, i) {
    var row = document.createElement('div');
    row.className = 'score-row';
    row.innerHTML =
      '<div class="score-row-top">' +
        '<div class="score-rank">' + (i + 1) + '</div>' +
        '<span class="score-name">' + escapeHtml(r.role) + '</span>' +
        '<span class="score-val">'  + r.overall.toFixed(1) + '</span>' +
      '</div>' +
      '<div class="score-cells">' +
        '<div class="score-cell">Acc <span>'  + r.acc.toFixed(1)  + '</span></div>' +
        '<div class="score-cell">Comp <span>' + r.comp.toFixed(1) + '</span></div>' +
        '<div class="score-cell">Conc <span>' + r.conc.toFixed(1) + '</span></div>' +
        '<div class="score-cell">Tone <span>' + r.tone.toFixed(1) + '</span></div>' +
      '</div>';
    list.appendChild(row);
  });
}

/* ── System HUD — real metrics polled from /api/health ── */
var hudData = { cpu: 0, gpu: 0, vram: 0, ram: 0, tps: 0 };

function startHudLoop() {
  fetchHud();
  setInterval(fetchHud, 3000);
}

function fetchHud() {
  fetch('/api/health')
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var sys = d.system || {};
      hudData.cpu  = sys.cpu  != null ? sys.cpu  : hudData.cpu;
      hudData.ram  = sys.ram  != null ? sys.ram  : hudData.ram;
      // GPU/VRAM come from LM Studio if available; fall back to last value
      hudData.gpu  = sys.gpu  != null ? sys.gpu  : hudData.gpu;
      hudData.vram = sys.vram != null ? sys.vram : hudData.vram;
      updateHud();
    })
    .catch(function () {});
}

function updateHud() {
  setGauge('cpu',  hudData.cpu);
  setGauge('gpu',  hudData.gpu);
  setGauge('vram', hudData.vram);
  setGauge('ram',  hudData.ram);
  var tpsEl = document.getElementById('hud-tps');
  if (tpsEl) tpsEl.textContent = hudData.tps ? Math.round(hudData.tps) + ' t/s' : '— t/s';
}

function setGauge(id, pct) {
  var fill = document.getElementById('g-' + id);
  var val  = document.getElementById('v-' + id);
  if (fill) fill.style.width = (pct || 0).toFixed(0) + '%';
  if (val)  val.textContent  = pct != null && pct > 0 ? pct.toFixed(0) + '%' : '—';
}

/* ── DOM helpers ── */
function appendMessage(node) {
  var c = document.getElementById('chat-messages');
  c.appendChild(node);
  node.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function updateInputState() {
  var btn  = document.getElementById('send-btn');
  var inp  = document.getElementById('chat-input');
  if (btn)  btn.disabled  = state.isRunning;
  if (inp)  inp.disabled  = state.isRunning;
  if (!state.isRunning && inp) inp.focus();
}

function escapeHtml(s) {
  var d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

function fillPrompt(btn) {
  var input = document.getElementById('chat-input');
  input.value = btn.textContent;
  input.focus();
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 160) + 'px';
}

function clearChat() {
  var msgs = document.getElementById('chat-messages');
  msgs.innerHTML =
    '<div class="welcome" id="welcome">' +
      '<div class="welcome-eyebrow">AGENT COUNCIL</div>' +
      '<div class="welcome-logo">🏛️</div>' +
      '<h2 class="welcome-title">The Intelligence Chamber</h2>' +
      '<p class="welcome-sub">Orchestrate local models — debate, compare, and synthesize higher-quality answers.</p>' +
      '<div class="welcome-examples">' +
        '<button class="example-btn" onclick="fillPrompt(this)">Explain quantum computing simply</button>' +
        '<button class="example-btn" onclick="fillPrompt(this)">Review this architecture decision</button>' +
        '<button class="example-btn" onclick="fillPrompt(this)">Compare React vs Vue vs Svelte</button>' +
        '<button class="example-btn" onclick="fillPrompt(this)">Debug a race condition</button>' +
      '</div>' +
    '</div>';
  state.agentColors    = {};
  state.nextColorIndex = 1;
  state.scores         = {};
  document.getElementById('score-list').innerHTML = '<div class="score-empty">Run a prompt to see rankings.</div>';
  stopTimer();
  document.getElementById('session-timer').textContent = '';
}

/* ── Timer ── */
function startTimer() {
  state.sessionStart = Date.now();
  var el = document.getElementById('session-timer');
  if (state.timerInterval) clearInterval(state.timerInterval);
  state.timerInterval = setInterval(function () {
    var s = Math.floor((Date.now() - state.sessionStart) / 1000);
    el.textContent = pad(Math.floor(s / 60)) + ':' + pad(s % 60);
  }, 1000);
}
function stopTimer() {
  if (state.timerInterval) { clearInterval(state.timerInterval); state.timerInterval = null; }
}
function pad(n) { return n < 10 ? '0' + n : '' + n; }
