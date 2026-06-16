let _initialized = false;
let _modal = null;
let _state = null;
let _activeTab = 'overview';

const TABS = [
  ['overview', 'Overview'],
  ['today', "Today's Oracle"],
  ['profile', 'Birth / Vedic Profile'],
  ['manifestations', 'Manifestation Bank'],
  ['gratitude', 'Gratitude Ritual'],
  ['numerology', 'Numerology Lab'],
  ['calendar', 'Cosmic Calendar'],
  ['signs', 'Signs & Synchronicities'],
  ['settings', 'Spiritual Settings'],
];

const $ = (tag, className = '', text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
};

const today = () => new Date().toISOString().slice(0, 10);

function futureMonthDay(month, day) {
  const now = new Date();
  let year = now.getFullYear();
  const value = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  return value < today() ? `${year + 1}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}` : value;
}

function emptyState() {
  return {
    display_name: '',
    preferred_names: [],
    birth_profile: {},
    spiritual_preferences: {},
    manifestation_categories: [],
    manifestations: [],
    gratitude_entries: [],
    synchronicities: [],
    important_dates: [],
    numerology_calculations: [],
  };
}

function field(label, name, value = '', attrs = {}) {
  const wrap = $('label', 'oracle-field');
  wrap.appendChild($('span', '', label));
  const input = attrs.multiline ? document.createElement('textarea') : document.createElement('input');
  input.name = name;
  input.value = value || '';
  if (attrs.type) input.type = attrs.type;
  if (attrs.placeholder) input.placeholder = attrs.placeholder;
  wrap.appendChild(input);
  return wrap;
}

function select(label, name, value, options) {
  const wrap = $('label', 'oracle-field');
  wrap.appendChild($('span', '', label));
  const input = document.createElement('select');
  input.name = name;
  options.forEach(([val, text]) => {
    const option = document.createElement('option');
    option.value = val;
    option.textContent = text;
    if (val === value) option.selected = true;
    input.appendChild(option);
  });
  wrap.appendChild(input);
  return wrap;
}

function checkbox(label, name, checked) {
  const wrap = $('label', 'oracle-check');
  const input = document.createElement('input');
  input.type = 'checkbox';
  input.name = name;
  input.checked = !!checked;
  wrap.append(input, $('span', '', label));
  return wrap;
}

function formData(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function splitLines(value) {
  return String(value || '').split(/\r?\n|,/).map((part) => part.trim()).filter(Boolean);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = 'Oracle request failed.';
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

function ensureStyles() {
  if (document.getElementById('oracle-theme-css')) return;
  const link = document.createElement('link');
  link.id = 'oracle-theme-css';
  link.rel = 'stylesheet';
  link.href = '/static/css/oracle.css';
  document.head.appendChild(link);
}

function status(message, kind = 'info') {
  const node = _modal?.querySelector('[data-oracle-status]');
  if (!node) return;
  node.textContent = message || '';
  node.dataset.kind = kind;
}

async function load() {
  _state = await api('/api/oracle');
  return _state;
}

function ownerName() {
  return _state?.display_name || _state?.birth_profile?.full_name || 'Boss';
}

function section(title, subtitle) {
  const card = $('section', 'oracle-card');
  card.appendChild($('h4', '', title));
  if (subtitle) card.appendChild($('p', 'oracle-muted', subtitle));
  return card;
}

function stat(label, value, note = '') {
  const card = $('article', 'oracle-stat');
  card.appendChild($('span', 'oracle-stat-label', label));
  card.appendChild($('strong', 'oracle-stat-value', value === undefined || value === null || value === '' ? '—' : value));
  if (note) card.appendChild($('small', '', note));
  return card;
}

function listEmpty(text) {
  return $('p', 'oracle-empty', text);
}

function renderOverview(body) {
  const bp = _state?.birth_profile || {};
  const signs = _state?.synchronicities || [];
  const manifestations = _state?.manifestations || [];
  const gratitude = _state?.gratitude_entries || [];
  const important = (_state?.important_dates || []).slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const upcoming = important.find((item) => item.date >= today()) || important[0];

  const hero = $('section', 'oracle-hero-card');
  hero.appendChild($('span', 'oracle-kicker', 'YVES · Powered by STRNOS · SaturnOS'));
  hero.appendChild($('h3', '', `Boss — I’m Yves.`));
  hero.appendChild($('p', '', 'Signs without delusion. Manifestation with receipts. Symbolic guidance, practical execution.'));
  const heroActions = $('div', 'oracle-actions');
  [
    ['Generate today', 'today'],
    ['Log sign', 'signs'],
    ['Manifestation bank', 'manifestations'],
    ['Gratitude ritual', 'gratitude'],
    ['11 July', 'calendar'],
  ].forEach(([label, tab]) => {
    const button = $('button', 'oracle-primary', label);
    button.type = 'button';
    button.addEventListener('click', () => { _activeTab = tab; render(); });
    heroActions.appendChild(button);
  });
  hero.appendChild(heroActions);
  body.appendChild(hero);

  const grid = $('div', 'oracle-grid');
  grid.appendChild(stat('Owner profile', ownerName(), [bp.birth_city, bp.birth_country, bp.timezone].filter(Boolean).join(' · ')));
  grid.appendChild(stat('DOB / time', bp.date_of_birth || 'Pending', bp.time_of_birth || 'Birth time pending'));
  grid.appendChild(stat('Life Path', bp.date_of_birth === '2001-07-21' ? '4' : 'Calculated in numerology', 'Owner DOB 2001-07-21 seeds Life Path 4.'));
  grid.appendChild(stat('Day Number', bp.date_of_birth === '2001-07-21' ? '21 / 3' : 'Calculated in numerology'));
  grid.appendChild(stat('Latest sign', signs[0]?.value || 'None yet', signs[0]?.meaning || '333 seeds automatically when Oracle is empty.'));
  grid.appendChild(stat('Active manifestations', manifestations.filter((item) => item.status === 'active').length, 'Receipts over fantasy.'));
  grid.appendChild(stat('Gratitude today', gratitude.some((item) => item.date === today()) ? 'Done' : 'Not yet', 'Already mine · on its way · receipt.'));
  grid.appendChild(stat('Important date', upcoming?.date || 'None', upcoming?.label || '11 July appears when seed is empty.'));
  grid.appendChild(stat('Action receipt', 'Create proof today', 'Bid, apply, train, clean, log, follow up.'));
  body.appendChild(grid);

  api('/api/oracle/cosmic-calendar').then((calendar) => {
    const next = calendar.next_mercury_retrograde;
    if (next) grid.appendChild(stat('Next Mercury retrograde', `${next.start} → ${next.end}`, 'Local reference data, not live ephemeris.'));
  }).catch(() => {});
}

function renderToday(body) {
  const card = section("Today's Oracle", 'Rich daily reading: symbolic guidance, practical action, no guaranteed predictions.');
  const output = $('div', 'oracle-grid');
  const button = $('button', 'oracle-primary', 'Generate Today');
  button.type = 'button';
  button.addEventListener('click', async () => {
    try {
      status('Reading the day...');
      const reading = await api('/api/oracle/daily', { method: 'POST', body: JSON.stringify({ save: true }) });
      output.replaceChildren();
      [
        ['Date', reading.date],
        ['Title', reading.title],
        ['Energy', reading.energy],
        ['Vedic reflection', reading.vedic_focus || reading.vedic_status],
        ['Vedic limitation', reading.vedic_status],
        ['Numerology', reading.numerology_focus],
        ['Emotional weather', reading.emotional_weather],
        ['Shadow warning', reading.shadow_warning || reading.warning],
        ['Best action', reading.best_action],
        ['Do not do', reading.do_not_do],
        ['Reflection', reading.reflection_question],
        ['Manifestation prompt', reading.manifestation_prompt],
        ['Gratitude prompt', reading.gratitude_prompt],
        ['Action receipt', reading.action_receipt_prompt],
        ['Closing line', reading.closing_line],
      ].forEach(([label, value]) => output.appendChild(stat(label, value || 'Pending')));
      if (reading.numerology) {
        output.appendChild(stat('Life Path', reading.numerology.life_path));
        output.appendChild(stat('Day Number', reading.numerology.day_number));
        output.appendChild(stat('Personal Day', reading.numerology.personal_day));
      }
      status('Oracle ready.', 'ok');
    } catch (error) {
      status(error.message, 'error');
    }
  });
  card.append(button, output);
  body.appendChild(card);
  button.click();
}

function renderProfile(body) {
  const profile = _state?.birth_profile || {};
  const card = section('Birth / Vedic Profile', 'Owner seed fills empty fields only. Vedic placements are stored manually until a real ephemeris exists.');
  const form = $('form', 'oracle-form oracle-form-compact');
  form.append(
    field('Full name', 'full_name', profile.full_name || _state?.display_name || ''),
    field('Date of birth', 'date_of_birth', profile.date_of_birth || '', { type: 'date' }),
    field('Time of birth', 'time_of_birth', profile.time_of_birth || '', { placeholder: '20:00' }),
    field('Birth city', 'birth_city', profile.birth_city || ''),
    field('Birth country', 'birth_country', profile.birth_country || ''),
    field('Timezone', 'timezone', profile.timezone || ''),
    select('Astrology system', 'preferred_system', profile.preferred_system || 'vedic', [['vedic', 'Vedic / Jyotish'], ['western', 'Western']]),
    select('Ayanamsa', 'ayanamsa', profile.ayanamsa || 'lahiri', [['lahiri', 'Lahiri'], ['pending', 'Pending']]),
    select('House system', 'house_system', profile.house_system || 'whole_sign', [['whole_sign', 'Whole Sign'], ['pending', 'Pending']]),
    field('Manual placements', 'manual_placements', profile.manual_placements || '', { multiline: true }),
    field('Notes', 'notes', profile.notes || '', { multiline: true }),
  );
  const save = $('button', 'oracle-primary', 'Save Profile');
  save.type = 'submit';
  form.appendChild(save);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await api('/api/oracle/profile', { method: 'POST', body: JSON.stringify(formData(form)) });
      await load();
      status('Birth profile saved.', 'ok');
      render();
    } catch (error) {
      status(error.message, 'error');
    }
  });
  card.appendChild(form);
  body.appendChild(card);
}

function renderManifestations(body) {
  const card = section('Manifestation Bank', 'Add the aim, then attach reality: evidence and action receipts.');
  const form = $('form', 'oracle-form oracle-form-compact');
  form.append(
    field('Title', 'title', '', { placeholder: 'Council home, apprenticeship, peace...' }),
    select('Category', 'category', 'housing', [['housing', 'Housing'], ['money', 'Money'], ['apprenticeship', 'Apprenticeship'], ['daughter', 'Daughter'], ['peace', 'Peace'], ['creativity', 'Creativity'], ['love', 'Love'], ['custom', 'Custom']]),
    field('Statement', 'statement', '', { multiline: true }),
    field('Target date', 'target_date', '', { type: 'date' }),
    field('Action receipt', 'action_receipts', '', { placeholder: 'One real action taken' }),
  );
  const add = $('button', 'oracle-primary', 'Add Manifestation');
  add.type = 'submit';
  form.appendChild(add);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = formData(form);
    data.action_receipts = splitLines(data.action_receipts);
    try {
      await api('/api/oracle/manifestations', { method: 'POST', body: JSON.stringify(data) });
      await load();
      status('Manifestation saved.', 'ok');
      render();
    } catch (error) {
      status(error.message, 'error');
    }
  });
  card.appendChild(form);

  const list = $('div', 'oracle-list');
  const items = _state?.manifestations || [];
  if (!items.length) list.appendChild(listEmpty('No manifestations yet. Start with one aim and one receipt you can prove today.'));
  items.forEach((item) => {
    const row = $('article', 'oracle-item');
    row.appendChild($('strong', '', item.title || 'Manifestation'));
    row.appendChild($('span', 'oracle-meta', `${item.status || 'active'} · ${item.category || 'custom'} · evidence ${(item.evidence || []).length} · receipts ${(item.action_receipts || []).length}`));
    if (item.statement) row.appendChild($('p', '', item.statement));
    const controls = $('div', 'oracle-actions');
    [
      ['Add evidence', 'evidence'],
      ['Add receipt', 'action_receipt'],
      ['Active', 'active'],
      ['Paused', 'paused'],
      ['Materialised', 'materialised'],
      ['Released', 'released'],
    ].forEach(([label, action]) => {
      const btn = $('button', 'oracle-secondary', label);
      btn.type = 'button';
      btn.addEventListener('click', async () => {
        const patch = {};
        if (action === 'evidence') {
          const value = prompt('Evidence from reality?');
          if (!value) return;
          patch.evidence = value;
        } else if (action === 'action_receipt') {
          const value = prompt('Action receipt created?');
          if (!value) return;
          patch.action_receipt = value;
        } else {
          patch.status = action;
        }
        try {
          await api(`/api/oracle/manifestations/${encodeURIComponent(item.id)}`, { method: 'PATCH', body: JSON.stringify(patch) });
          await load();
          status('Manifestation updated.', 'ok');
          render();
        } catch (error) {
          status(error.message, 'error');
        }
      });
      controls.appendChild(btn);
    });
    row.appendChild(controls);
    list.appendChild(row);
  });
  card.appendChild(list);
  body.appendChild(card);
}

function renderGratitude(body) {
  const card = section('Gratitude Ritual', 'Three already mine. Three on the way. One receipt created.');
  const form = $('form', 'oracle-form');
  form.append(
    field('3 already mine', 'grateful_for', '', { multiline: true, placeholder: 'One per line' }),
    field('3 on its way', 'thankful_before_materialised', '', { multiline: true, placeholder: 'One per line' }),
    field('Sign seen', 'signs_seen', '', { placeholder: '333, dream, repeated date...' }),
    field('Receipt I created', 'action_receipt', ''),
    field('Scripting text', 'scripting', '', { multiline: true }),
  );
  const save = $('button', 'oracle-primary', 'Save Gratitude');
  save.type = 'submit';
  form.appendChild(save);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = formData(form);
    data.grateful_for = splitLines(data.grateful_for);
    data.thankful_before_materialised = splitLines(data.thankful_before_materialised);
    data.signs_seen = splitLines(data.signs_seen);
    try {
      await api('/api/oracle/gratitude', { method: 'POST', body: JSON.stringify(data) });
      await load();
      status('Gratitude saved.', 'ok');
      render();
    } catch (error) {
      status(error.message, 'error');
    }
  });
  card.appendChild(form);

  const entries = _state?.gratitude_entries || [];
  if (!entries.length) card.appendChild(listEmpty('No gratitude entries yet.'));
  entries.slice(0, 8).forEach((item) => {
    const row = $('article', 'oracle-item');
    row.appendChild($('strong', '', item.date || 'Gratitude'));
    row.appendChild($('p', '', [...(item.grateful_for || []), ...(item.thankful_before_materialised || [])].join(' · ') || 'Saved entry'));
    if (item.action_receipt) row.appendChild($('span', 'oracle-meta', `Receipt: ${item.action_receipt}`));
    card.appendChild(row);
  });
  body.appendChild(card);
}

function renderNumerology(body) {
  const card = section('Numerology Lab', 'Uses seeded DOB. Preserves master numbers 11, 22, and 33.');
  const form = $('form', 'oracle-form oracle-form-compact');
  form.append(
    field('Date', 'date', today(), { type: 'date' }),
    field('Label', 'label', ''),
    select('Type', 'type', 'personal', [['personal', 'Personal'], ['spiritual', 'Spiritual'], ['housing', 'Housing'], ['money', 'Money'], ['custom', 'Custom']]),
  );
  const quick = $('div', 'oracle-actions');
  [
    ['Today', today()],
    ['Tomorrow', (() => { const d = new Date(); d.setDate(d.getDate() + 1); return d.toISOString().slice(0, 10); })()],
    ['22 June', futureMonthDay(6, 22)],
    ['11 July', '2026-07-11'],
    ['Birthday', futureMonthDay(7, 21)],
  ].forEach(([label, value]) => {
    const btn = $('button', 'oracle-secondary', label);
    btn.type = 'button';
    btn.addEventListener('click', () => {
      form.elements.date.value = value;
      form.dispatchEvent(new Event('submit', { cancelable: true }));
    });
    quick.appendChild(btn);
  });
  const output = $('div', 'oracle-grid');
  const calc = $('button', 'oracle-primary', 'Calculate');
  calc.type = 'submit';
  form.appendChild(calc);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const result = await api('/api/oracle/numerology', { method: 'POST', body: JSON.stringify({ ...formData(form), save: true }) });
      output.replaceChildren();
      [
        ['Date', result.date],
        ['Universal day', result.universal_day],
        ['Date reduction', result.date_reduction],
        ['Life Path', result.life_path],
        ['Day Number', result.day_number],
        ['Personal Year', result.personal_year],
        ['Personal Month', result.personal_month],
        ['Personal Day', result.personal_day],
        ['Interpretation', result.interpretation],
        ['Best use', result.best_use],
        ['Caution', result.caution],
        ['Action', result.action_suggestion],
      ].forEach(([label, value]) => output.appendChild(stat(label, value)));
      status('Numerology saved.', 'ok');
    } catch (error) {
      status(error.message, 'error');
    }
  });
  card.append(form, quick, output);
  body.appendChild(card);
}

function renderCalendar(body) {
  const card = section('Cosmic Calendar', 'Local Mercury retrograde reference data. Important dates are owner-scoped. No fake Vedic placements.');
  const form = $('form', 'oracle-form oracle-form-compact');
  form.append(
    field('Date', 'date', '', { type: 'date' }),
    field('Label', 'label', ''),
    select('Type', 'type', 'spiritual', [['spiritual', 'Spiritual'], ['housing', 'Housing'], ['money', 'Money'], ['relationship', 'Relationship'], ['work', 'Work'], ['custom', 'Custom']]),
    field('Notes', 'notes', '', { multiline: true }),
  );
  const save = $('button', 'oracle-primary', 'Save Important Date');
  save.type = 'submit';
  form.appendChild(save);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await api('/api/oracle/important-dates', { method: 'POST', body: JSON.stringify(formData(form)) });
      await load();
      status('Important date saved.', 'ok');
      render();
    } catch (error) {
      status(error.message, 'error');
    }
  });
  const output = $('div', 'oracle-grid');
  card.append(form, output);
  api('/api/oracle/cosmic-calendar').then((calendar) => {
    output.replaceChildren();
    const next = calendar.next_mercury_retrograde;
    output.appendChild(stat('Reference', calendar.reference || 'local_reference_data', calendar.disclaimer || 'Symbolic guidance only.'));
    output.appendChild(stat('Vedic engine', calendar.vedic_engine || 'pending', 'No fake placements.'));
    if (next) output.appendChild(stat('Next Mercury retrograde', `${next.start} → ${next.end}`, 'Local reference data.'));
    (calendar.important_dates || []).forEach((item) => output.appendChild(stat(item.date, item.label, item.notes || item.type)));
    (calendar.upcoming_mercury_retrogrades || []).slice(0, 4).forEach((period) => output.appendChild(stat(`${period.start} → ${period.end}`, period.label, period.source)));
  }).catch((error) => status(error.message, 'error'));
  body.appendChild(card);
}

function renderSigns(body) {
  const card = section('Signs & Synchronicities', 'Log what happened. Then decide the grounded action.');
  const form = $('form', 'oracle-form');
  form.append(
    field('Date', 'date', today(), { type: 'date' }),
    select('Type', 'type', 'angel_number', [['angel_number', 'Angel number'], ['date', 'Date'], ['dream', 'Dream'], ['tarot', 'Tarot / reading'], ['coincidence', 'Coincidence'], ['other', 'Other']]),
    field('Value', 'value', '', { placeholder: '333, repeated address, dream...' }),
    field('Context', 'context', '', { multiline: true }),
    field('Meaning', 'meaning', '', { multiline: true }),
    field('Action prompt', 'action_prompt', ''),
  );
  const save = $('button', 'oracle-primary', 'Log Sign');
  save.type = 'submit';
  form.appendChild(save);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = formData(form);
    if (String(data.value).trim() === '333' && !data.meaning) {
      data.meaning = 'Symbolically: support, growth, guidance, creative expression.';
      data.action_prompt = data.action_prompt || 'Turn the sign into a receipt: create, bid, apply, train, or document evidence.';
    }
    try {
      await api('/api/oracle/signs', { method: 'POST', body: JSON.stringify(data) });
      await load();
      status('Sign logged.', 'ok');
      render();
    } catch (error) {
      status(error.message, 'error');
    }
  });
  card.appendChild(form);
  const signs = _state?.synchronicities || [];
  if (!signs.length) card.appendChild(listEmpty('No signs yet. 333 appears automatically when Oracle is empty.'));
  signs.slice(0, 12).forEach((item) => {
    const row = $('article', 'oracle-item');
    row.appendChild($('strong', '', item.value || 'Sign'));
    row.appendChild($('span', 'oracle-meta', `${item.date || ''} · ${item.type || 'other'}`));
    if (item.context) row.appendChild($('p', '', item.context));
    if (item.meaning) row.appendChild($('p', '', item.meaning));
    if (item.action_prompt) row.appendChild($('span', 'oracle-meta', `Action: ${item.action_prompt}`));
    card.appendChild(row);
  });
  body.appendChild(card);
}

function renderSettings(body) {
  const prefs = _state?.spiritual_preferences || {};
  const card = section('Spiritual Settings', 'Tone and guardrails. Defaults stay grounded, direct, and action-based.');
  const form = $('form', 'oracle-form');
  form.append(
    field('Belief style', 'belief_style', (prefs.belief_style || []).join(', ')),
    select('Tone', 'tone', prefs.tone || 'grounded_mystic', [['grounded_mystic', 'Grounded mystic'], ['practical', 'Practical'], ['soft', 'Soft']]),
    field('Strictness', 'strictness', prefs.strictness || 'direct'),
    field('Manifestation style', 'manifestation_style', (prefs.manifestation_style || []).join(', ')),
    field('Avoid tone', 'avoid_tone', (prefs.avoid_tone || []).join(', ')),
    checkbox('Vedic first', 'vedic_first', prefs.vedic_first !== false),
    checkbox('Avoid guaranteed predictions', 'avoid_guaranteed_predictions', prefs.avoid_guaranteed_predictions !== false),
    checkbox('Include numerology', 'include_numerology', prefs.include_numerology !== false),
    checkbox('Action receipt required', 'always_include_action_receipt', prefs.always_include_action_receipt !== false),
  );
  const save = $('button', 'oracle-primary', 'Save Settings');
  save.type = 'submit';
  form.appendChild(save);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = formData(form);
    data.belief_style = splitLines(data.belief_style);
    data.manifestation_style = splitLines(data.manifestation_style);
    data.avoid_tone = splitLines(data.avoid_tone);
    data.vedic_first = form.elements.vedic_first.checked;
    data.avoid_guaranteed_predictions = form.elements.avoid_guaranteed_predictions.checked;
    data.include_numerology = form.elements.include_numerology.checked;
    data.always_include_action_receipt = form.elements.always_include_action_receipt.checked;
    try {
      await api('/api/oracle/settings', { method: 'POST', body: JSON.stringify(data) });
      await load();
      status('Oracle settings saved.', 'ok');
      render();
    } catch (error) {
      status(error.message, 'error');
    }
  });
  card.appendChild(form);
  body.appendChild(card);
}

function render() {
  if (!_modal) return;
  const tabs = _modal.querySelector('[data-oracle-tabs]');
  const body = _modal.querySelector('[data-oracle-body]');
  tabs.replaceChildren();
  body.replaceChildren();
  TABS.forEach(([id, label]) => {
    const button = $('button', 'oracle-tab', label);
    button.type = 'button';
    button.dataset.active = id === _activeTab ? 'true' : 'false';
    button.addEventListener('click', () => { _activeTab = id; render(); });
    tabs.appendChild(button);
  });
  const map = {
    overview: renderOverview,
    today: renderToday,
    profile: renderProfile,
    manifestations: renderManifestations,
    gratitude: renderGratitude,
    numerology: renderNumerology,
    calendar: renderCalendar,
    signs: renderSigns,
    settings: renderSettings,
  };
  (map[_activeTab] || renderOverview)(body);
}

function build() {
  ensureStyles();
  _modal = $('div', 'oracle-modal');
  _modal.id = 'oracle-modal';
  _modal.hidden = true;
  _modal.innerHTML = `
    <div class="oracle-content" role="dialog" aria-modal="true" aria-labelledby="oracle-title">
      <header class="oracle-header">
        <div>
          <span class="oracle-kicker">YVES · Powered by STRNOS · SaturnOS</span>
          <h3 id="oracle-title">STRNOS Oracle</h3>
          <p>Boss — I’m Yves. Signs, dates, gratitude, numerology and action receipts.</p>
        </div>
        <button type="button" class="oracle-close" aria-label="Close Oracle">&times;</button>
      </header>
      <div class="oracle-tabs" data-oracle-tabs></div>
      <div class="oracle-status" data-oracle-status></div>
      <main class="oracle-body" data-oracle-body></main>
    </div>
  `;
  _modal.querySelector('.oracle-close')?.addEventListener('click', close);
  _modal.addEventListener('click', (event) => { if (event.target === _modal) close(); });
  document.body.appendChild(_modal);
}

async function open(tab = 'overview') {
  if (!_initialized) init();
  _activeTab = tab || 'overview';
  _modal.hidden = false;
  document.body.classList.add('modal-open');
  status('Loading Oracle...');
  try {
    await load();
    render();
    status('Oracle ready.', 'ok');
  } catch (error) {
    _state = emptyState();
    render();
    status(error.message, 'error');
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
  build();
  _initialized = true;
}

export { init, open, close };
export default { init, open, close };
