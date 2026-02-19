var state = {
  ws: null,
  councils: {},
  selectedCouncil: 'general',
  isRunning: false,
  agentColors: {},
  nextColorIndex: 1,
};

document.addEventListener('DOMContentLoaded', function () {
  setupInput();
  loadConfig();
  connectWs();
  checkHealth();
});

function setupInput() {
  var input = document.getElementById('chat-input');
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendTask();
    }
  });
}

function loadConfig() {
  fetch('/api/config')
    .then(function (res) { return res.json(); })
    .then(function (cfg) {
      state.councils = cfg.councils || {};
      state.selectedCouncil = (cfg.defaults && cfg.defaults.council) || 'general';
      renderCouncilList();
      selectCouncil(state.selectedCouncil);
    })
    .catch(function (err) {
      addError('Failed to load config: ' + err.message);
    });
}

function renderCouncilList() {
  var list = document.getElementById('council-list');
  list.innerHTML = '';
  Object.keys(state.councils).forEach(function (key) {
    var btn = document.createElement('button');
    btn.className = 'council-btn' + (key === state.selectedCouncil ? ' active' : '');
    btn.dataset.key = key;
    btn.textContent = state.councils[key].name || key;
    btn.onclick = function () { selectCouncil(key); };
    list.appendChild(btn);
  });
}

function selectCouncil(key) {
  state.selectedCouncil = key;
  var council = state.councils[key];
  if (!council) return;
  document.getElementById('council-name').textContent = council.name;
  document.getElementById('council-info').innerHTML =
    '<span>' + (council.strategy || 'debate') + '</span><span>•</span><span>' +
    ((council.agents || []).length) + ' agents</span>';
  Array.prototype.forEach.call(document.querySelectorAll('.council-btn'), function (b) {
    b.className = 'council-btn' + (b.dataset.key === key ? ' active' : '');
  });
}

function connectWs() {
  var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  state.ws = new WebSocket(protocol + '//' + location.host + '/ws/council');
  state.ws.onopen = function () {
    setConn(true);
  };
  state.ws.onclose = function () {
    setConn(false);
    setTimeout(connectWs, 2000);
  };
  state.ws.onerror = function () {
    setConn(false);
  };
  state.ws.onmessage = function (evt) {
    var data;
    try { data = JSON.parse(evt.data); } catch (_) { return; }
    handleEvent(data);
  };
}

function setConn(ok) {
  var dot = document.getElementById('connection-dot');
  var text = document.querySelector('#connection-status span');
  dot.className = 'dot ' + (ok ? 'connected' : 'disconnected');
  text.textContent = ok ? 'Connected' : 'Disconnected';
}

function checkHealth() {
  fetch('/api/health').then(function (r) { return r.json(); }).then(function (d) {
    if (!d.lm_studio || !d.lm_studio.connected) {
      addStatus('LM Studio is not reachable.');
    }
  }).catch(function () {});
}

function sendTask() {
  if (state.isRunning) return;
  var input = document.getElementById('chat-input');
  var task = (input.value || '').trim();
  if (!task) return;
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
    addError('WebSocket not connected.');
    return;
  }

  document.getElementById('welcome') && (document.getElementById('welcome').style.display = 'none');
  state.agentColors = {};
  state.nextColorIndex = 1;
  addUserMessage(task);

  state.ws.send(JSON.stringify({
    type: 'task',
    council: state.selectedCouncil,
    task: task,
  }));

  input.value = '';
  state.isRunning = true;
  updateInputState();
}

function handleEvent(e) {
  if (e.type === 'status') return addStatus(e.content);
  if (e.type === 'round_start') return addRoundSeparator(e.round, e.metadata && e.metadata.total_rounds);
  if (e.type === 'agent_done') {
    var agentContent = ((e.content || '').trim() || '[No content returned by model]');
    return addAgentCard(e.agent, e.metadata && e.metadata.model, agentContent, false);
  }
  if (e.type === 'moderator_done') {
    var moderatorContent = ((e.content || '').trim() || '[No content returned by moderator]');
    return addAgentCard('Moderator', e.metadata && e.metadata.model, moderatorContent, true);
  }
  if (e.type === 'error') {
    state.isRunning = false;
    updateInputState();
    return addError(e.content || 'Unknown error');
  }
  if (e.type === 'council_done') {
    state.isRunning = false;
    updateInputState();
    return addStatus('Session complete');
  }
}

function addUserMessage(text) {
  var el = document.createElement('div');
  el.className = 'message-user';
  el.textContent = text;
  appendMessage(el);
}

function addRoundSeparator(round, total) {
  var el = document.createElement('div');
  el.className = 'round-separator';
  el.textContent = total ? ('Round ' + round + ' of ' + total) : ('Round ' + round);
  appendMessage(el);
}

function addStatus(text) {
  var el = document.createElement('div');
  el.className = 'status-message';
  el.innerHTML = '<div class="spinner"></div><span>' + escapeHtml(text) + '</span>';
  appendMessage(el);
}

function addError(text) {
  var el = document.createElement('div');
  el.className = 'error-message';
  el.textContent = text;
  appendMessage(el);
}

function colorIndex(role) {
  if (!state.agentColors[role]) {
    state.agentColors[role] = state.nextColorIndex;
    state.nextColorIndex = (state.nextColorIndex % 5) + 1;
  }
  return state.agentColors[role];
}

function addAgentCard(role, model, content, isModerator) {
  var idx = isModerator ? 0 : colorIndex(role);
  var card = document.createElement('div');
  card.className = 'agent-card' + (isModerator ? ' moderator' : (' agent-color-' + idx));

  var initials = isModerator ? 'M' : role.split(' ').map(function (w) { return w[0]; }).join('').slice(0, 2).toUpperCase();
  card.innerHTML =
    '<div class="agent-card-header">' +
      '<div class="agent-avatar">' + escapeHtml(initials) + '</div>' +
      '<span class="agent-name">' + escapeHtml(role) + '</span>' +
      (model ? ('<span class="agent-model">' + escapeHtml(model) + '</span>') : '') +
    '</div>' +
    '<div class="agent-card-body">' + escapeHtml(content) + '</div>';
  appendMessage(card);
}

function appendMessage(node) {
  var c = document.getElementById('chat-messages');
  var shouldStickToBottom = (c.scrollHeight - c.scrollTop - c.clientHeight) < 80;
  c.appendChild(node);
  if (shouldStickToBottom) {
    c.scrollTop = c.scrollHeight;
  }
}

function updateInputState() {
  document.getElementById('send-btn').disabled = state.isRunning;
  document.getElementById('chat-input').disabled = state.isRunning;
}

function escapeHtml(s) {
  var div = document.createElement('div');
  div.textContent = s || '';
  return div.innerHTML;
}
