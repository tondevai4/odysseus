let _initialized = false;
let _modal = null;
let _state = null;
let _activeTab = 'today';

const TABS = [
  ['today', "Today's Oracle"],
  ['profile', 'Birth Profile'],
  ['manifestations', 'Manifestation Bank'],
  ['gratitude', 'Gratitude'],
  ['numerology', 'Numerology Lab'],
  ['calendar', 'Cosmic Calendar'],
  ['signs', 'Signs & Synchronicities'],
  ['settings', 'Spiritual Settings'],
];

function _emptyState() {
  return {
    birth_profile: {},
    spiritual_preferences: {},
    manifestations: [],
    gratitude_entries: [],
    synchronicities: [],
    important_dates: [],
    numerology_calculations: [],
  };
}

function _el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function _field(label, name, value = '', attrs = {}) {
  const wrap = _el('label', 'oracle-field');
  wrap.appendChild(_el('span', '', label));
  const input = attrs.multiline ? document.createElement('textarea') : document.createElement('input');
  input.name = name;
  input.value = value || '';
  if (attrs.type) input.type = attrs.type;
  if (attrs.placeholder) input.placeholder = attrs.placeholder;
  if (attrs.maxLength) input.maxLength = attrs.maxLength;
  wrap.appendChild(input);
  return wrap;
}

function _select(label, name, value, options) {
  const wrap = _el('label', 'oracle-field');
  wrap.appendChild(_el('span', '', label));
  const select = document.createElement('select');
  select.name = name;
  options.forEach(([optionValue, optionLabel]) => {
    const option = document.createElement('option');
    option.value = optionValue;
    option.textContent = optionLabel;
    if (optionValue === value) option.selected = true;
    select.appendChild(option);
  });
  wrap.appendChild(select);
  return wrap;
}

function _formData(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function _lines(value) {
  return String(value || '').split(/\r?\n|,/).map((part) => part.trim()).filter(Boolean);
}

async function _api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    let detail = 'Oracle request failed.';
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

async function _load() {
  _state = await _api('/api/oracle');
  return _state;
}

function _section(title, subtitle) {
  const card = _el('section', 'oracle-card');
  card.appendChild(_el('h4', '', title));
  if (subtitle) card.appendChild(_el('p', 'oracle-muted', subtitle));
  return card;
}

function _status(message, kind = 'info') {
  const node = _modal?.querySelector('[data-oracle-status]');
  if (!node) return;
  node.textContent = message || '';
  node.dataset.kind = kind;
}

function _renderToday(body) {
  const card = _section("Today's Oracle", 'Symbolic insight, grounded action.');
  const output = _el('div', 'oracle-stack');
  card.appendChild(output);
  const button = _el('button', 'oracle-primary', 'Generate Today');
  button.type = 'button';
  button.addEventListener('click', async () => {
    try {
      _status('Reading the day...');
      const reading = await _api('/api/oracle/daily', { method: 'POST', body: '{}' });
      output.replaceChildren();
      [
        ['Date', reading.date],
        ['Energy', reading.energy],
        ['Best action', reading.best_action],
        ['Reflection', reading.reflection_question],
        ['Manifestation prompt', reading.manifestation_prompt],
        ['Action receipt', reading.action_receipt_prompt],
        ['Vedic/Jyotish', reading.vedic_status],
      ].forEach(([label, value]) => output.appendChild(_el('p', 'oracle-line', `${label}: ${value || 'Pending'}`)));
      if (reading.numerology) {
        output.appendChild(_el('p', 'oracle-line', `Universal day: ${reading.numerology.universal_day}`));
      }
      _status('Oracle ready.', 'ok');
    } catch (error) {
      _status(error.message, 'error');
    }
  });
  card.appendChild(button);
  body.appendChild(card);
}

function _renderProfile(body) {
  const profile = _state?.birth_profile || {};
  const card = _section('Birth Profile', 'No private birth details are assumed. Save them only when you want Oracle to use them.');
  const form = _el('form', 'oracle-form');
  form.append(
    _field('Full name', 'full_name', profile.full_name, { maxLength: 160 }),
    _field('Date of birth', 'date_of_birth', profile.date_of_birth, { type: 'date' }),
    _field('Time of birth', 'time_of_birth', profile.time_of_birth, { placeholder: 'HH:MM' }),
    _field('Birth city', 'birth_city', profile.birth_city),
    _field('Birth country', 'birth_country', profile.birth_country),
    _select('Astrology system', 'preferred_system', profile.preferred_system || 'vedic', [['vedic', 'Vedic / Jyotish'], ['western', 'Western']]),
    _select('Ayanamsa', 'ayanamsa', profile.ayanamsa || 'lahiri', [['lahiri', 'Lahiri'], ['pending', 'Pending']]),
    _select('House system', 'house_system', profile.house_system || 'whole_sign', [['whole_sign', 'Whole sign'], ['pending', 'Pending']]),
    _field('Manual placements', 'manual_placements', profile.manual_placements, { multiline: true }),
    _field('Notes', 'notes', profile.notes, { multiline: true }),
  );
  const save = _el('button', 'oracle-primary', 'Save Profile');
  save.type = 'submit';
  form.appendChild(save);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await _api('/api/oracle/profile', { method: 'POST', body: JSON.stringify(_formData(form)) });
      await _load();
      _status('Birth profile saved.', 'ok');
    } catch (error) {
      _status(error.message, 'error');
    }
  });
  card.appendChild(form);
  card.appendChild(_el('p', 'oracle-muted', 'Vedic planetary placements are not calculated yet. Manual placements are stored as owner-provided notes.'));
  body.appendChild(card);
}

function _renderManifestations(body) {
  const card = _section('Manifestation Bank', 'Receipts over fantasy. Save the aim, then record evidence and action.');
  const form = _el('form', 'oracle-form oracle-form-compact');
  form.append(
    _field('Title', 'title', '', { placeholder: 'Council home, apprenticeship, peace...' }),
    _select('Category', 'category', 'custom', [['housing', 'Housing'], ['money', 'Money'], ['apprenticeship', 'Apprenticeship'], ['daughter', 'Daughter'], ['peace', 'Peace'], ['creativity', 'Creativity'], ['love', 'Love'], ['custom', 'Custom']]),
    _field('Statement', 'statement', '', { multiline: true }),
    _field('Action receipt', 'action_receipts', '', { placeholder: 'One real action taken' }),
  );
  const add = _el('button', 'oracle-primary', 'Add Manifestation');
  add.type = 'submit';
  form.appendChild(add);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = _formData(form);
    data.action_receipts = _lines(data.action_receipts);
    try {
      await _api('/api/oracle/manifestations', { method: 'POST', body: JSON.stringify(data) });
      await _load();
      _status('Manifestation saved.', 'ok');
      _render();
    } catch (error) {
      _status(error.message, 'error');
    }
  });
  card.appendChild(form);
  (_state?.manifestations || []).forEach((item) => {
    const row = _el('article', 'oracle-item');
    row.appendChild(_el('strong', '', item.title || 'Manifestation'));
    row.appendChild(_el('span', '', `${item.status || 'active'} · ${item.category || 'custom'}`));
    if (item.statement) row.appendChild(_el('p', '', item.statement));
    const controls = _el('div', 'oracle-actions');
    ['active', 'paused', 'materialised', 'released'].forEach((status) => {
      const btn = _el('button', 'oracle-secondary', status);
      btn.type = 'button';
      btn.addEventListener('click', async () => {
        try {
          await _api(`/api/oracle/manifestations/${encodeURIComponent(item.id)}`, {
            method: 'PATCH',
            body: JSON.stringify({ status }),
          });
          await _load();
          _render();
        } catch (error) {
          _status(error.message, 'error');
        }
      });
      controls.appendChild(btn);
    });
    row.appendChild(controls);
    card.appendChild(row);
  });
  body.appendChild(card);
}

function _renderGratitude(body) {
  const card = _section('Gratitude', 'Present thanks, future thanks, then one action receipt.');
  const form = _el('form', 'oracle-form');
  form.append(
    _field('Grateful for', 'grateful_for', '', { multiline: true, placeholder: 'One per line' }),
    _field('Thankful before materialised', 'thankful_before_materialised', '', { multiline: true }),
    _field('Scripting', 'scripting', '', { multiline: true }),
    _field('Action receipt', 'action_receipt', ''),
  );
  const save = _el('button', 'oracle-primary', 'Save Gratitude');
  save.type = 'submit';
  form.appendChild(save);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = _formData(form);
    data.grateful_for = _lines(data.grateful_for);
    data.thankful_before_materialised = _lines(data.thankful_before_materialised);
    try {
      await _api('/api/oracle/gratitude', { method: 'POST', body: JSON.stringify(data) });
      await _load();
      _status('Gratitude saved.', 'ok');
      _render();
    } catch (error) {
      _status(error.message, 'error');
    }
  });
  card.appendChild(form);
  (_state?.gratitude_entries || []).slice(0, 5).forEach((item) => {
    const row = _el('article', 'oracle-item');
    row.appendChild(_el('strong', '', item.date || 'Gratitude'));
    row.appendChild(_el('p', '', [...(item.grateful_for || []), ...(item.thankful_before_materialised || [])].join(' · ') || 'Saved entry'));
    card.appendChild(row);
  });
  body.appendChild(card);
}

function _renderNumerology(body) {
  const card = _section('Numerology Lab', 'Deterministic local numerology. Master numbers 11, 22, and 33 are preserved at final reduction.');
  const form = _el('form', 'oracle-form oracle-form-compact');
  form.append(
    _field('Date', 'date', new Date().toISOString().slice(0, 10), { type: 'date' }),
    _field('Label', 'label', ''),
    _select('Type', 'type', 'personal', [['personal', 'Personal'], ['important', 'Important date'], ['cosmic', 'Cosmic']]),
  );
  const output = _el('div', 'oracle-stack');
  const calc = _el('button', 'oracle-primary', 'Calculate');
  calc.type = 'submit';
  form.appendChild(calc);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const result = await _api('/api/oracle/numerology', {
        method: 'POST',
        body: JSON.stringify({ ..._formData(form), save: true }),
      });
      output.replaceChildren();
      Object.entries(result).forEach(([key, value]) => {
        if (typeof value === 'object') return;
        output.appendChild(_el('p', 'oracle-line', `${key.replaceAll('_', ' ')}: ${value}`));
      });
      _status('Numerology saved.', 'ok');
    } catch (error) {
      _status(error.message, 'error');
    }
  });
  card.append(form, output);
  body.appendChild(card);
}

function _renderCalendar(body) {
  const card = _section('Cosmic Calendar', 'Local Mercury retrograde reference data only. No scraping, no API keys, no fake planetary placements.');
  const output = _el('div', 'oracle-stack');
  card.appendChild(output);
  _api('/api/oracle/cosmic-calendar').then((calendar) => {
    const next = calendar.next_mercury_retrograde;
    output.replaceChildren();
    output.appendChild(_el('p', 'oracle-line', `Reference: ${calendar.reference || 'local'}`));
    output.appendChild(_el('p', 'oracle-line', `Vedic engine: ${calendar.vedic_engine || 'pending'}`));
    if (next) output.appendChild(_el('p', 'oracle-line', `Next Mercury retrograde: ${next.start} to ${next.end}`));
    (calendar.mercury_retrograde_periods || []).slice(0, 8).forEach((period) => {
      output.appendChild(_el('p', 'oracle-line', `${period.start} to ${period.end} · ${period.label}`));
    });
  }).catch((error) => _status(error.message, 'error'));
  body.appendChild(card);
}

function _renderSigns(body) {
  const card = _section('Signs & Synchronicities', 'Log what happened. Then decide the grounded action.');
  const form = _el('form', 'oracle-form');
  form.append(
    _field('Date', 'date', new Date().toISOString().slice(0, 10), { type: 'date' }),
    _select('Type', 'type', 'other', [['angel_number', 'Angel number'], ['date', 'Date'], ['dream', 'Dream'], ['tarot', 'Tarot'], ['coincidence', 'Coincidence'], ['other', 'Other']]),
    _field('Value', 'value', '', { placeholder: '333, repeated address, dream...' }),
    _field('Context', 'context', '', { multiline: true }),
    _field('Meaning', 'meaning', '', { multiline: true }),
    _field('Action prompt', 'action_prompt', ''),
  );
  const save = _el('button', 'oracle-primary', 'Log Sign');
  save.type = 'submit';
  form.appendChild(save);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await _api('/api/oracle/signs', { method: 'POST', body: JSON.stringify(_formData(form)) });
      await _load();
      _status('Sign logged.', 'ok');
      _render();
    } catch (error) {
      _status(error.message, 'error');
    }
  });
  card.appendChild(form);
  (_state?.synchronicities || []).slice(0, 8).forEach((item) => {
    const row = _el('article', 'oracle-item');
    row.appendChild(_el('strong', '', item.value || 'Sign'));
    row.appendChild(_el('span', '', `${item.date || ''} · ${item.type || 'other'}`));
    if (item.context) row.appendChild(_el('p', '', item.context));
    card.appendChild(row);
  });
  body.appendChild(card);
}

function _renderSettings(body) {
  const prefs = _state?.spiritual_preferences || {};
  const card = _section('Spiritual Settings', 'Keep the tone grounded, useful, and yours.');
  const form = _el('form', 'oracle-form');
  form.append(
    _field('Belief style', 'belief_style', (prefs.belief_style || []).join(', ')),
    _select('Tone', 'tone', prefs.tone || 'grounded_mystic', [['grounded_mystic', 'Grounded mystic'], ['practical', 'Practical'], ['soft', 'Soft']]),
    _field('Manifestation style', 'manifestation_style', (prefs.manifestation_style || []).join(', ')),
    _field('Avoid tone', 'avoid_tone', (prefs.avoid_tone || []).join(', ')),
  );
  const save = _el('button', 'oracle-primary', 'Save Settings');
  save.type = 'submit';
  form.appendChild(save);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = _formData(form);
    data.belief_style = _lines(data.belief_style);
    data.manifestation_style = _lines(data.manifestation_style);
    data.avoid_tone = _lines(data.avoid_tone);
    try {
      await _api('/api/oracle/settings', { method: 'POST', body: JSON.stringify(data) });
      await _load();
      _status('Oracle settings saved.', 'ok');
    } catch (error) {
      _status(error.message, 'error');
    }
  });
  card.appendChild(form);
  body.appendChild(card);
}

function _render() {
  if (!_modal) return;
  const tabs = _modal.querySelector('[data-oracle-tabs]');
  const body = _modal.querySelector('[data-oracle-body]');
  tabs.replaceChildren();
  body.replaceChildren();
  TABS.forEach(([id, label]) => {
    const button = _el('button', 'oracle-tab', label);
    button.type = 'button';
    button.dataset.active = id === _activeTab ? 'true' : 'false';
    button.addEventListener('click', () => {
      _activeTab = id;
      _render();
    });
    tabs.appendChild(button);
  });
  if (_activeTab === 'today') _renderToday(body);
  if (_activeTab === 'profile') _renderProfile(body);
  if (_activeTab === 'manifestations') _renderManifestations(body);
  if (_activeTab === 'gratitude') _renderGratitude(body);
  if (_activeTab === 'numerology') _renderNumerology(body);
  if (_activeTab === 'calendar') _renderCalendar(body);
  if (_activeTab === 'signs') _renderSigns(body);
  if (_activeTab === 'settings') _renderSettings(body);
}

function _build() {
  _modal = _el('div', 'oracle-modal');
  _modal.id = 'oracle-modal';
  _modal.hidden = true;
  _modal.innerHTML = `
    <div class="oracle-content" role="dialog" aria-modal="true" aria-labelledby="oracle-title">
      <header class="oracle-header">
        <div>
          <span class="oracle-kicker">STRNOS Oracle</span>
          <h3 id="oracle-title">YVES Oracle</h3>
          <p>SaturnOS spiritual layer. Insight with receipts.</p>
        </div>
        <button type="button" class="oracle-close" aria-label="Close Oracle">&times;</button>
      </header>
      <div class="oracle-tabs" data-oracle-tabs></div>
      <div class="oracle-status" data-oracle-status></div>
      <main class="oracle-body" data-oracle-body></main>
    </div>
  `;
  _modal.querySelector('.oracle-close')?.addEventListener('click', close);
  _modal.addEventListener('click', (event) => {
    if (event.target === _modal) close();
  });
  document.body.appendChild(_modal);
}

async function open(tab = 'today') {
  if (!_initialized) init();
  _activeTab = tab || 'today';
  _modal.hidden = false;
  document.body.classList.add('modal-open');
  _status('Loading Oracle...');
  try {
    await _load();
    _render();
    _status('Oracle ready.', 'ok');
  } catch (error) {
    _state = _emptyState();
    _render();
    _status(error.message, 'error');
  }
}

function close() {
  if (!_modal) return;
  _modal.hidden = true;
  document.body.classList.remove('modal-open');
  window.dispatchEvent(new CustomEvent('strnos:oracle-updated'));
}

function init() {
  if (_initialized) return;
  _build();
  _initialized = true;
}

export { init, open, close };
export default { init, open, close };
