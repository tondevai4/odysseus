let _initialized = false;

function _text(parent, tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value;
  parent.appendChild(node);
  return node;
}

function _label(value) {
  return String(value || '').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function _ensureThemeStyles() {
  if (document.getElementById('command-center-theme-css')) return;
  const link = document.createElement('link');
  link.id = 'command-center-theme-css';
  link.rel = 'stylesheet';
  link.href = '/static/css/command-center-theme.css';
  document.head.appendChild(link);
}

async function _loadCurrentReading({ openReadingDocument, downloadReadingDocument } = {}) {
  const body = document.getElementById('command-reading-body');
  const actions = document.getElementById('command-reading-actions');
  if (!body || !actions) return;
  try {
    const response = await fetch('/api/reading-list/current', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error('Reading List unavailable');
    const payload = await response.json();
    const item = payload.item;
    body.replaceChildren();
    actions.querySelectorAll('[data-reading-document-action]').forEach((node) => node.remove());
    if (!item) {
      _text(body, 'p', 'command-reading-empty', 'No current book. Add one to Reading List.');
      return;
    }

    _text(body, 'strong', 'command-reading-title', item.title);
    if (item.author) _text(body, 'span', 'command-reading-author', item.author);
    const meta = _text(body, 'div', 'command-reading-meta', '');
    ['status', 'progress', 'priority'].forEach((field) => {
      if (!item[field]) return;
      _text(meta, 'span', '', `${_label(field)}: ${_label(item[field])}`);
    });
    if (item.notes) {
      const preview = item.notes.length > 150 ? `${item.notes.slice(0, 147)}...` : item.notes;
      _text(body, 'p', 'command-reading-notes', preview);
    }
    if (item.document?.available) {
      const openButton = _text(actions, 'button', 'command-card-action', 'Open Document');
      openButton.type = 'button';
      openButton.dataset.readingDocumentAction = 'open';
      openButton.addEventListener('click', () => openReadingDocument?.(item));
      const downloadButton = _text(actions, 'button', 'command-card-action', 'Download');
      downloadButton.type = 'button';
      downloadButton.dataset.readingDocumentAction = 'download';
      downloadButton.addEventListener('click', () => downloadReadingDocument?.(item));
    }
  } catch (error) {
    body.replaceChildren();
    _text(body, 'p', 'command-reading-empty', 'Reading List is unavailable right now.');
  }
}

async function _loadLatestWorkout() {
  const body = document.getElementById('command-gym-body');
  if (!body) return;
  body.replaceChildren();
  try {
    const response = await fetch('/api/gym-log/latest', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error('Gym Log unavailable');
    const { entry } = await response.json();
    if (!entry) {
      _text(body, 'p', 'command-reading-empty', 'No gym log yet. Log today’s proof.');
      return;
    }
    _text(body, 'strong', 'command-reading-title', entry.title);
    const meta = _text(body, 'div', 'command-reading-meta', '');
    _text(meta, 'span', '', new Date(`${entry.date}T00:00:00`).toLocaleDateString());
    if (entry.duration) _text(meta, 'span', '', `Duration: ${entry.duration}`);
    if (entry.total_sets !== null) _text(meta, 'span', '', `Sets: ${entry.total_sets}`);
    if (entry.total_reps !== null) _text(meta, 'span', '', `Reps: ${entry.total_reps}`);
    if (entry.active_calories !== null) {
      _text(meta, 'span', '', `Active kcal: ${entry.active_calories}`);
    }
    if (entry.primary_benefit) {
      _text(body, 'p', 'command-reading-notes', entry.primary_benefit);
    }
    let hint = 'Next: recover, then train the next movement with clean form.';
    if (
      Number(entry.max_hr || 0) >= 165
      || Number(entry.body_battery_net_impact || 0) <= -10
      || /anaerobic|high aerobic/i.test(entry.primary_benefit || '')
    ) {
      hint = 'Hard session. Recover first; keep the next effort controlled.';
    }
    _text(body, 'p', 'command-reading-notes', hint);
  } catch (error) {
    _text(body, 'p', 'command-reading-empty', 'Gym Log is unavailable right now.');
  }
}

async function _loadOracleSummary() {
  const body = document.getElementById('command-oracle-body');
  if (!body) return;
  try {
    const response = await fetch('/api/oracle/summary', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error('Oracle unavailable');
    const payload = await response.json();
    body.replaceChildren();
    const parts = [];
    if (payload.birth_profile_saved) parts.push('Birth profile saved');
    if (payload.manifestation_count) parts.push(`${payload.manifestation_count} manifestation${payload.manifestation_count === 1 ? '' : 's'}`);
    if (payload.gratitude_count) parts.push(`${payload.gratitude_count} gratitude entr${payload.gratitude_count === 1 ? 'y' : 'ies'}`);
    if (payload.sign_count) parts.push(`${payload.sign_count} sign${payload.sign_count === 1 ? '' : 's'}`);
    if (payload.life_path) parts.push(`Life Path ${payload.life_path}`);
    if (payload.day_number) parts.push(`Day ${payload.day_number}`);
    if (parts.length) {
      _text(body, 'p', 'command-oracle-summary', parts.join(' · '));
    } else {
      _text(body, 'p', 'command-oracle-empty', 'No Oracle profile yet. Open STRNOS Oracle to add signs, gratitude, or numerology.');
    }
    if (payload.latest_sign?.value) {
      _text(body, 'p', 'command-oracle-note', `Latest sign: ${payload.latest_sign.value}`);
    }
    _text(body, 'p', 'command-oracle-note', 'Vedic engine pending. Numerology runs locally.');
  } catch (error) {
    body.replaceChildren();
    _text(body, 'p', 'command-oracle-empty', 'STRNOS Oracle is unavailable right now.');
  }
}

function init({
  openNotes,
  openHousingBids,
  openReadingList,
  openGymLog,
  openArchive,
  openReadingDocument,
  downloadReadingDocument,
  openBrainHealth,
  openOracle,
  runRoutine,
} = {}) {
  if (_initialized) return;
  _ensureThemeStyles();

  const commandCenter = document.getElementById('command-center');
  if (!commandCenter) return;

  commandCenter.addEventListener('click', (event) => {
    const action = event.target.closest('[data-command-center-action]');
    if (!action || !commandCenter.contains(action)) return;

    if (action.dataset.commandCenterAction === 'notes' && typeof openNotes === 'function') {
      openNotes();
    }
    if (
      action.dataset.commandCenterAction === 'housing-bids'
      && typeof openHousingBids === 'function'
    ) {
      openHousingBids();
    }
    if (
      action.dataset.commandCenterAction === 'reading-list'
      && typeof openReadingList === 'function'
    ) {
      openReadingList();
    }
    if (
      action.dataset.commandCenterAction === 'gym-log'
      && typeof openGymLog === 'function'
    ) {
      openGymLog();
    }
    if (
      action.dataset.commandCenterAction === 'archive'
      && typeof openArchive === 'function'
    ) {
      openArchive();
    }
    if (
      action.dataset.commandCenterAction === 'brain-health'
      && typeof openBrainHealth === 'function'
    ) {
      openBrainHealth();
    }
    if (
      action.dataset.commandCenterAction === 'oracle'
      && typeof openOracle === 'function'
    ) {
      openOracle();
    }
    if (
      action.dataset.commandCenterAction === 'routine'
      && action.dataset.routinePrompt
      && typeof runRoutine === 'function'
    ) {
      runRoutine(action.dataset.routinePrompt);
    }
  });

  const readingOptions = { openReadingDocument, downloadReadingDocument };
  _loadCurrentReading(readingOptions);
  _loadLatestWorkout();
  window.addEventListener('vanta:reading-list-updated', () => {
    _loadCurrentReading(readingOptions);
  });
  window.addEventListener('vanta:gym-log-updated', _loadLatestWorkout);
  _loadOracleSummary();
  window.addEventListener('strnos:oracle-updated', _loadOracleSummary);
  _initialized = true;
}

const commandCenterModule = { init };

export { init };
export default commandCenterModule;
