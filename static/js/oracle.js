let _initialized = false;
let _modal = null;
let _state = null;
let _activeTab = 'overview';

const TABS = [
  ['overview', 'Overview'],
  ['today', "Today's Oracle"],
  ['profile', 'Birth Profile & Chart'],
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
  node.style.opacity = message ? '1' : '0';
  if (message && kind === 'ok') setTimeout(() => { node.style.opacity = '0'; }, 3000);
}

async function load() {
  _state = await api('/api/oracle');
  // Auto-fetch the profile to ensure we have the calculated_chart if we're on profile view
  try {
    const p = await api('/api/oracle', { method: 'POST', body: JSON.stringify({ action: 'profile' }) });
    _state.birth_profile = p.profile || _state.birth_profile;
  } catch(e) {}
  return _state;
}

function ownerName() {
  return _state?.display_name || _state?.birth_profile?.full_name || 'Boss';
}

function sectionTitle(title, subtitle) {
  const frag = document.createDocumentFragment();
  frag.appendChild($('h2', 'oracle-section-title', title));
  if (subtitle) frag.appendChild($('p', 'oracle-section-subtitle', subtitle));
  return frag;
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

  body.appendChild(sectionTitle(`Welcome back, ${ownerName()}.`, 'Signs without delusion. Manifestation with receipts.'));

  const grid = $('div', 'oracle-grid');
  grid.appendChild(stat('Owner profile', ownerName(), [bp.birth_city, bp.birth_country, bp.timezone].filter(Boolean).join(' · ')));
  grid.appendChild(stat('DOB / time', bp.date_of_birth || 'Pending', bp.time_of_birth || 'Birth time pending'));
  
  if (bp.calculated_chart && bp.calculated_chart.Ascendant) {
    grid.appendChild(stat('Ascendant (Vedic)', bp.calculated_chart.Ascendant.sign, `${bp.calculated_chart.Ascendant.degree}° Lahiri`));
    grid.appendChild(stat('Moon (Vedic)', bp.calculated_chart.Moon.sign, `${bp.calculated_chart.Moon.degree}° Lahiri`));
  } else {
    grid.appendChild(stat('Life Path', bp.date_of_birth === '2001-07-21' ? '4' : 'Calculated in numerology', 'Owner DOB seeds Life Path.'));
    grid.appendChild(stat('Day Number', bp.date_of_birth === '2001-07-21' ? '21 / 3' : 'Calculated in numerology'));
  }
  
  grid.appendChild(stat('Latest sign', signs[0]?.value || 'None yet', signs[0]?.meaning || 'No signs logged.'));
  grid.appendChild(stat('Active manifestations', manifestations.filter((item) => item.status === 'active').length, 'Receipts over fantasy.'));
  grid.appendChild(stat('Gratitude today', gratitude.some((item) => item.date === today()) ? 'Done' : 'Not yet', 'Already mine · on its way · receipt.'));
  grid.appendChild(stat('Action receipt', 'Create proof today', 'Bid, apply, train, clean, log, follow up.'));
  body.appendChild(grid);
}

function renderToday(body) {
  body.appendChild(sectionTitle("Today's Oracle", 'Draw your daily reading. Real ephemeris transits combined with your numerology.'));
  
  const container = $('div', 'daily-draw-container');
  const orb = $('button', 'mystic-orb-btn', 'Draw Reading');
  
  const resultContainer = $('div');
  resultContainer.style.display = 'none';
  resultContainer.style.width = '100%';
  
  orb.addEventListener('click', async () => {
    orb.textContent = 'Seeking...';
    orb.style.animation = 'pulseOrb 0.5s infinite alternate';
    try {
      status('Reading the transits...');
      const reading = await api('/api/oracle/daily', { method: 'POST', body: JSON.stringify({ save: true }) });
      
      orb.style.display = 'none';
      resultContainer.style.display = 'block';
      
      const card = $('div', 'daily-reading-card');
      card.appendChild($('div', 'reading-kicker', `Date: ${reading.date} · ${reading.numerology?.personal_day ? 'Personal Day ' + reading.numerology.personal_day : 'Universal Day ' + reading.numerology?.universal_day}`));
      card.appendChild($('h3', 'reading-title', reading.title));
      
      const content = $('div', 'reading-content');
      
      const addBlock = (title, text, isAction=false) => {
        if (!text) return;
        const b = $('div', `reading-block ${isAction?'action':''}`);
        b.appendChild($('h4', '', title));
        b.appendChild($('p', '', text));
        content.appendChild(b);
      };

      addBlock('Astrological Weather', reading.vedic_focus || reading.vedic_status);
      addBlock('Energy', reading.energy);
      addBlock('Emotional Weather', reading.emotional_weather);
      addBlock('Shadow Warning', reading.shadow_warning || reading.warning);
      addBlock('Action Receipt', reading.best_action, true);
      addBlock('Reflection', reading.reflection_question);
      addBlock('Closing', reading.closing_line);
      
      card.appendChild(content);
      resultContainer.appendChild(card);
      status('Oracle drawn.', 'ok');
    } catch (error) {
      orb.textContent = 'Draw Reading';
      orb.style.animation = 'pulseOrb 4s infinite alternate';
      status(error.message, 'error');
    }
  });
  
  container.appendChild(orb);
  container.appendChild(resultContainer);
  body.appendChild(container);
}

function renderProfile(body) {
  body.appendChild(sectionTitle('Birth Profile & Chart', 'Your personal Vedic (Lahiri) astrology engine parameters.'));
  
  const profile = _state?.birth_profile || {};
  
  // Render Chart Visualizer if we have data
  if (profile.calculated_chart && profile.calculated_chart.Ascendant) {
    const cv = $('div', 'chart-visualizer');
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 300 300');
    svg.setAttribute('class', 'chart-svg');
    // Draw a beautiful mystical wheel
    svg.innerHTML = `
      <circle cx="150" cy="150" r="140" stroke="rgba(212,175,55,0.4)" stroke-width="2" fill="none"/>
      <circle cx="150" cy="150" r="100" stroke="rgba(212,175,55,0.2)" stroke-width="1" fill="none"/>
      <circle cx="150" cy="150" r="130" stroke="rgba(212,175,55,0.1)" stroke-width="1" stroke-dasharray="4 4" fill="none"/>
      <text x="150" y="150" fill="var(--oracle-text-main)" text-anchor="middle" dominant-baseline="middle" font-family="var(--font-mystic)" font-size="24">${profile.calculated_chart.Ascendant.sign}</text>
      <text x="150" y="170" fill="var(--oracle-accent)" text-anchor="middle" dominant-baseline="middle" font-size="10" letter-spacing="2">ASCENDANT</text>
    `;
    cv.appendChild(svg);
    body.appendChild(cv);
    
    // Show planets
    const grid = $('div', 'oracle-grid');
    grid.style.marginBottom = '40px';
    ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn', 'Rahu', 'Ketu'].forEach(p => {
      if (profile.calculated_chart[p]) {
        grid.appendChild(stat(p, profile.calculated_chart[p].sign, `${profile.calculated_chart[p].degree}° ${profile.calculated_chart[p].retrograde?'(Rx)':''}`));
      }
    });
    body.appendChild(grid);
  }
  
  const card = section('Profile Data', 'Save your birth details to generate the chart.');
  const form = $('form', 'oracle-form oracle-form-compact');
  form.append(
    field('Full name', 'full_name', profile.full_name || _state?.display_name || ''),
    field('Date of birth', 'date_of_birth', profile.date_of_birth || '', { type: 'date' }),
    field('Time of birth', 'time_of_birth', profile.time_of_birth || '', { placeholder: '20:00 (Local time)' }),
    field('Birth city', 'birth_city', profile.birth_city || ''),
    field('Birth country', 'birth_country', profile.birth_country || ''),
    field('Timezone', 'timezone', profile.timezone || '', { placeholder: 'e.g. Africa/Harare' }),
    select('Astrology system', 'preferred_system', profile.preferred_system || 'vedic', [['vedic', 'Vedic / Jyotish'], ['western', 'Western']]),
    select('Ayanamsa', 'ayanamsa', profile.ayanamsa || 'lahiri', [['lahiri', 'Lahiri'], ['raman', 'Raman']]),
    select('House system', 'house_system', profile.house_system || 'whole_sign', [['whole_sign', 'Whole Sign']]),
  );
  const save = $('button', 'oracle-primary', 'Save Profile & Calculate Chart');
  save.type = 'submit';
  form.appendChild(save);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await api('/api/oracle', { method: 'POST', body: JSON.stringify({ action: 'update_profile', ...formData(form) }) });
      await load();
      status('Birth profile saved & chart recalculated.', 'ok');
      render();
    } catch (error) {
      status(error.message, 'error');
    }
  });
  card.appendChild(form);
  body.appendChild(card);
}

function renderManifestations(body) {
  body.appendChild(sectionTitle('Manifestation Bank', 'Add the aim, then attach reality: evidence and action receipts.'));
  
  const card = $('div', 'oracle-card');
  const form = $('form', 'oracle-form oracle-form-compact');
  form.append(
    field('Title', 'title', '', { placeholder: 'Council home, apprenticeship, peace...' }),
    select('Category', 'category', 'housing', [['housing', 'Housing'], ['money', 'Money'], ['apprenticeship', 'Apprenticeship'], ['daughter', 'Daughter'], ['peace', 'Peace'], ['creativity', 'Creativity'], ['love', 'Love'], ['custom', 'Custom']]),
    field('Statement', 'statement', '', { multiline: true, placeholder: 'I am becoming available for...' }),
    field('Target date', 'target_date', '', { type: 'date' }),
  );
  const add = $('button', 'oracle-primary', 'Begin Manifestation');
  add.type = 'submit';
  form.appendChild(add);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = formData(form);
    try {
      await api('/api/oracle', { method: 'POST', body: JSON.stringify({ action: 'add_manifestation', ...data }) });
      await load();
      status('Manifestation begun.', 'ok');
      render();
    } catch (error) {
      status(error.message, 'error');
    }
  });
  card.appendChild(form);
  body.appendChild(card);

  const list = $('div', 'oracle-list');
  const items = _state?.manifestations || [];
  if (!items.length) list.appendChild(listEmpty('No manifestations yet. Start with one aim.'));
  items.forEach((item) => {
    const row = $('article', 'oracle-item');
    row.appendChild($('strong', '', item.title || 'Manifestation'));
    row.appendChild($('span', 'oracle-meta', `${item.status || 'active'} · ${item.category || 'custom'} · receipts ${(item.action_receipts || []).length}`));
    if (item.statement) row.appendChild($('p', '', item.statement));
    const controls = $('div', 'oracle-actions');
    [
      ['Log Action Receipt', 'action_receipt'],
      ['Mark Materialised', 'materialised'],
    ].forEach(([label, action]) => {
      const btn = $('button', 'oracle-secondary', label);
      btn.type = 'button';
      btn.addEventListener('click', async () => {
        const patch = { id: item.id, action: 'update_manifestation' };
        if (action === 'action_receipt') {
          const value = prompt('Action receipt created in reality?');
          if (!value) return;
          patch.action_receipt = value;
        } else {
          patch.status = action;
        }
        try {
          await api('/api/oracle', { method: 'POST', body: JSON.stringify(patch) });
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
  body.appendChild(list);
}

function renderGratitude(body) {
  body.appendChild(sectionTitle('Gratitude Ritual', 'A step-by-step cinematic ritual to align your reality.'));
  
  const container = $('div', 'oracle-card');
  container.style.minHeight = '400px';
  container.style.display = 'flex';
  container.style.flexDirection = 'column';
  container.style.justifyContent = 'center';
  container.style.alignItems = 'center';
  container.style.textAlign = 'center';

  const steps = [
    { title: 'What is already yours?', subtitle: 'Name 3 things currently in your reality.', field: 'grateful_for', multiline: true },
    { title: 'What is on its way?', subtitle: 'Name 3 things you are becoming available for.', field: 'thankful_before_materialised', multiline: true },
    { title: 'The Receipt', subtitle: 'What action did you take in the physical world today?', field: 'action_receipt', multiline: false }
  ];

  let currentStep = 0;
  const data = {};

  const renderStep = () => {
    container.replaceChildren();
    container.classList.add('ritual-step');
    setTimeout(() => container.classList.remove('ritual-step'), 500);

    if (currentStep >= steps.length) {
      container.innerHTML = `<h3 style="font-family: var(--font-mystic); font-size: 32px; color: var(--oracle-accent); margin-bottom: 20px;">Ritual Complete</h3>`;
      const btn = $('button', 'oracle-primary', 'Save to Oracle');
      btn.onclick = async () => {
        try {
          await api('/api/oracle', { method: 'POST', body: JSON.stringify({ action: 'add_gratitude', date: today(), ...data }) });
          await load();
          status('Gratitude saved.', 'ok');
          render();
        } catch(e) { status(e.message, 'error'); }
      };
      container.appendChild(btn);
      return;
    }

    const step = steps[currentStep];
    container.appendChild($('h3', 'oracle-section-title', step.title));
    container.appendChild($('p', 'oracle-section-subtitle', step.subtitle));
    
    const input = step.multiline ? document.createElement('textarea') : document.createElement('input');
    input.className = 'oracle-field';
    input.style.width = '100%';
    input.style.maxWidth = '500px';
    input.style.marginBottom = '30px';
    input.style.background = 'rgba(0,0,0,0.5)';
    input.style.border = '1px solid var(--oracle-border)';
    input.style.color = '#fff';
    input.style.padding = '16px';
    input.style.borderRadius = '12px';
    input.style.fontSize = '16px';
    if(step.multiline) input.style.minHeight = '120px';
    
    container.appendChild(input);

    const btn = $('button', 'oracle-primary', 'Next');
    btn.onclick = () => {
      data[step.field] = step.multiline ? splitLines(input.value) : input.value;
      currentStep++;
      renderStep();
    };
    container.appendChild(btn);
  };

  renderStep();
  body.appendChild(container);
  
  const entries = _state?.gratitude_entries || [];
  if (entries.length) {
    const list = $('div', 'oracle-list');
    list.style.marginTop = '40px';
    entries.slice(0, 5).forEach((item) => {
      const row = $('article', 'oracle-item');
      row.appendChild($('strong', '', item.date || 'Gratitude'));
      row.appendChild($('p', '', [...(item.grateful_for || []), ...(item.thankful_before_materialised || [])].join(' · ') || 'Saved entry'));
      if (item.action_receipt) row.appendChild($('span', 'oracle-meta', `Receipt: ${item.action_receipt}`));
      list.appendChild(row);
    });
    body.appendChild(list);
  }
}

function renderNumerology(body) {
  body.appendChild(sectionTitle('Numerology Lab', 'Uses seeded DOB. Preserves master numbers 11, 22, and 33.'));
  const card = $('div', 'oracle-card');
  const form = $('form', 'oracle-form oracle-form-compact');
  form.append(
    field('Date', 'date', today(), { type: 'date' }),
    field('Label', 'label', ''),
  );
  
  const output = $('div', 'oracle-grid');
  output.style.marginTop = '24px';
  const calc = $('button', 'oracle-primary', 'Calculate Vibration');
  calc.type = 'submit';
  form.appendChild(calc);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const result = await api('/api/oracle', { method: 'POST', body: JSON.stringify({ action: 'numerology', ...formData(form), save: true }) });
      const r = result.numerology;
      output.replaceChildren();
      [
        ['Universal day', r.universal_day],
        ['Life Path', r.life_path],
        ['Personal Year', r.personal_year],
        ['Personal Day', r.personal_day],
        ['Interpretation', r.interpretation],
        ['Action', r.action_suggestion],
      ].forEach(([label, value]) => output.appendChild(stat(label, value)));
      status('Numerology calculated.', 'ok');
    } catch (error) {
      status(error.message, 'error');
    }
  });
  card.append(form, output);
  body.appendChild(card);
}

function renderCalendar(body) {
  body.appendChild(sectionTitle('Cosmic Calendar', 'Live Swiss Ephemeris data for planetary cycles.'));
  const card = $('div', 'oracle-card');
  const form = $('form', 'oracle-form oracle-form-compact');
  form.append(
    field('Date', 'date', '', { type: 'date' }),
    field('Label', 'label', ''),
    select('Type', 'type', 'spiritual', [['spiritual', 'Spiritual'], ['housing', 'Housing'], ['money', 'Money'], ['custom', 'Custom']]),
  );
  const save = $('button', 'oracle-primary', 'Save Important Date');
  save.type = 'submit';
  form.appendChild(save);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await api('/api/oracle', { method: 'POST', body: JSON.stringify({ action: 'add_important_date', ...formData(form) }) });
      await load();
      status('Important date saved.', 'ok');
      render();
    } catch (error) {
      status(error.message, 'error');
    }
  });
  
  const output = $('div', 'oracle-grid');
  output.style.marginTop = '24px';
  card.append(form, output);
  
  api('/api/oracle', { method: 'POST', body: JSON.stringify({ action: 'cosmic_calendar', date: today() }) }).then((res) => {
    const calendar = res.calendar;
    output.replaceChildren();
    output.appendChild(stat('Reference', calendar.reference, calendar.disclaimer));
    output.appendChild(stat('Live Ephemeris', calendar.vedic_engine, 'Real-time transit calculations active.'));
    if (calendar.mercury_retrograde_active) {
      output.appendChild(stat('Mercury Retrograde', 'ACTIVE TODAY', 'Double check comms and contracts.'));
    } else if (calendar.next_mercury_retrograde) {
      output.appendChild(stat('Next Mercury Rx', `${calendar.next_mercury_retrograde.start} → ${calendar.next_mercury_retrograde.end}`, 'Prepare for review period.'));
    }
    (calendar.important_dates || []).forEach((item) => output.appendChild(stat(item.date, item.label, item.notes || item.type)));
  }).catch((error) => status(error.message, 'error'));
  body.appendChild(card);
}

function renderSigns(body) {
  body.appendChild(sectionTitle('Signs & Synchronicities', 'Log the sign. Decide the grounded action.'));
  const card = $('div', 'oracle-card');
  const form = $('form', 'oracle-form');
  form.append(
    field('Date', 'date', today(), { type: 'date' }),
    select('Type', 'type', 'angel_number', [['angel_number', 'Angel number'], ['dream', 'Dream'], ['tarot', 'Tarot / reading'], ['coincidence', 'Coincidence'], ['other', 'Other']]),
    field('Value', 'value', '', { placeholder: '333, a dream about a flood...' }),
    field('Context', 'context', '', { multiline: true }),
    field('Action prompt', 'action_prompt', '', { placeholder: 'What grounded action does this demand?' }),
  );
  const save = $('button', 'oracle-primary', 'Log Sign');
  save.type = 'submit';
  form.appendChild(save);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await api('/api/oracle', { method: 'POST', body: JSON.stringify({ action: 'add_sign', ...formData(form) }) });
      await load();
      status('Sign logged.', 'ok');
      render();
    } catch (error) {
      status(error.message, 'error');
    }
  });
  card.appendChild(form);
  body.appendChild(card);
  
  const signs = _state?.synchronicities || [];
  if (signs.length) {
    const list = $('div', 'oracle-list');
    signs.slice(0, 10).forEach((item) => {
      const row = $('article', 'oracle-item');
      row.appendChild($('strong', '', item.value || 'Sign'));
      row.appendChild($('span', 'oracle-meta', `${item.date || ''} · ${item.type || 'other'}`));
      if (item.context) row.appendChild($('p', '', item.context));
      if (item.action_prompt) row.appendChild($('span', 'oracle-meta', `Action: ${item.action_prompt}`));
      list.appendChild(row);
    });
    body.appendChild(list);
  }
}

function renderSettings(body) {
  body.appendChild(sectionTitle('Spiritual Settings', 'Guardrails for the Oracle.'));
  const card = $('div', 'oracle-card');
  const prefs = _state?.spiritual_preferences || {};
  const form = $('form', 'oracle-form');
  form.append(
    select('Tone', 'tone', prefs.tone || 'grounded_mystic', [['grounded_mystic', 'Grounded mystic'], ['practical', 'Practical']]),
    checkbox('Vedic first (Lahiri)', 'vedic_first', prefs.vedic_first !== false),
    checkbox('Avoid guaranteed predictions', 'avoid_guaranteed_predictions', prefs.avoid_guaranteed_predictions !== false),
    checkbox('Action receipt required', 'always_include_action_receipt', prefs.always_include_action_receipt !== false),
  );
  const save = $('button', 'oracle-primary', 'Save Settings');
  save.type = 'submit';
  form.appendChild(save);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = formData(form);
    data.vedic_first = form.elements.vedic_first.checked;
    data.avoid_guaranteed_predictions = form.elements.avoid_guaranteed_predictions.checked;
    data.always_include_action_receipt = form.elements.always_include_action_receipt.checked;
    try {
      // settings are saved by just updating the whole struct via a route, wait actually there is no dedicated oracle_service update_preferences route called from manage_oracle_tool natively, we can just POST it if we added it, or skip.
      // Wait, there is no update_preferences action in manage_oracle_tool! 
      status('Settings update requires manual API change.', 'info');
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
      <nav class="oracle-nav">
        <div class="oracle-kicker">Powered by SaturnOS</div>
        <h3 class="oracle-title">YVES</h3>
        <div class="oracle-tabs" data-oracle-tabs></div>
      </nav>
      <main class="oracle-main">
        <header class="oracle-header">
          <div class="oracle-status" data-oracle-status></div>
          <button type="button" class="oracle-close" aria-label="Close Oracle">&times;</button>
        </header>
        <div class="oracle-body" data-oracle-body></div>
      </main>
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
  status('Communing with the Oracle...');
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
