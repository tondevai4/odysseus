/* Oracle module — redesigned. 9 tabs → 4. Editorial Today hero. No window.prompt(). */

let _initialized = false;
let _modal = null;
let _state = null;
let _activeTab = 'today';

const TABS = [
  ['today', 'Today'],
  ['journal', 'Journal'],
  ['manifestations', 'Manifestations'],
  ['cosmos', 'Cosmos'],
];

const $ = (tag, className = '', text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
};

const today = () => new Date().toISOString().slice(0, 10);

const fmt = (dateStr) => {
  try {
    return new Date(dateStr + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  } catch { return dateStr || ''; }
};

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

// ─── Today Tab ───────────────────────────────────────────────────────────────

function renderToday(body) {
  body.classList.add('oracle-body--today');

  const wrapper = $('div', 'oracle-today-wrapper');

  // Hero card
  const hero = $('div', 'oracle-today-hero');
  const loadingDate = $('div', 'oracle-today-date', fmt(today()));
  const loadingTitle = $('h2', 'oracle-today-title', 'Loading today\u2019s reading\u2026');
  const loadingEnergy = $('p', 'oracle-today-energy', '');
  const receiptCta = $('div', 'oracle-receipt-cta');
  receiptCta.innerHTML = '<span class="oracle-receipt-label">Action Receipt</span><p class="oracle-receipt-text">Generating\u2026</p>';
  hero.append(loadingDate, loadingTitle, loadingEnergy, receiptCta);
  wrapper.appendChild(hero);

  // Enrich button row
  const enrichWrap = $('div', 'oracle-enrich-wrap');
  const enrichBtn = $('button', 'oracle-enrich-btn', '\u2728 Enrich with YVES');
  enrichBtn.type = 'button';
  enrichBtn.disabled = true;
  const enrichOutput = $('div', 'oracle-enriched-reading');
  enrichOutput.hidden = true;
  enrichWrap.append(enrichBtn, enrichOutput);
  wrapper.appendChild(enrichWrap);

  // Insights row
  const insightsRow = $('div', 'oracle-insights-row');
  const insightBestAction = makeInsightCard('Best Action', '', false);
  const insightShadow = makeInsightCard('Shadow Warning', '', false);
  const insightReflection = makeInsightCard('Reflection', '', true);
  insightsRow.append(insightBestAction.card, insightShadow.card, insightReflection.card);
  wrapper.appendChild(insightsRow);

  // Numerology strip
  const numStrip = $('div', 'oracle-numerology-strip');
  wrapper.appendChild(numStrip);

  // Secondary prompts
  const secondary = $('div', 'oracle-today-secondary');
  const manPrompt = makePromptCard('Manifestation Prompt', '');
  const gratPrompt = makePromptCard('Gratitude Prompt', '');
  secondary.append(manPrompt.card, gratPrompt.card);
  wrapper.appendChild(secondary);

  // Bridge to chat button
  const bridgeBtn = $('button', 'oracle-bridge-btn', 'Ask YVES about today\u2019s reading \u2192');
  bridgeBtn.type = 'button';
  bridgeBtn.addEventListener('click', () => bridgeToChat());
  wrapper.appendChild(bridgeBtn);

  body.appendChild(wrapper);

  let _currentReading = null;

  const renderReading = (reading) => {
    _currentReading = reading;
    loadingDate.textContent = fmt(reading.date || today());
    loadingTitle.textContent = reading.title || 'Today\u2019s Oracle';
    loadingEnergy.textContent = reading.energy || '';
    receiptCta.querySelector('.oracle-receipt-text').textContent = reading.action_receipt_prompt || reading.best_action || '';
    insightBestAction.setText(reading.best_action || '');
    insightShadow.setText(reading.shadow_warning || reading.warning || '');
    insightReflection.setText(reading.reflection_question || '');
    if (reading.numerology) {
      const n = reading.numerology;
      numStrip.replaceChildren();
      [
        ['Life Path', n.life_path],
        ['Personal Day', n.personal_day],
        ['Universal Day', n.universal_day],
        ['Day Number', n.day_number],
        ['Personal Year', n.personal_year],
      ].filter(([, v]) => v !== undefined && v !== null && v !== '').forEach(([lbl, val]) => {
        numStrip.appendChild(makeNumPill(lbl, val));
      });
    }
    manPrompt.setText(reading.manifestation_prompt || '');
    gratPrompt.setText(reading.gratitude_prompt || '');
    enrichBtn.disabled = false;
  };

  status('Reading the day\u2026');
  api('/api/oracle/daily', { method: 'POST', body: JSON.stringify({ date: today(), save: true }) })
    .then((reading) => { renderReading(reading); status('Oracle ready.', 'ok'); })
    .catch((error) => { status(error.message, 'error'); loadingTitle.textContent = 'Couldn\u2019t load reading'; });

  enrichBtn.addEventListener('click', async () => {
    if (!_currentReading) return;
    enrichBtn.disabled = true;
    enrichBtn.textContent = 'Asking YVES\u2026';
    enrichBtn.dataset.loading = 'true';
    enrichOutput.hidden = false;
    enrichOutput.innerHTML = '<span class="oracle-enriched-label">YVES \u00b7 Enriched Reading</span><p class="oracle-enriched-text">Thinking\u2026</p>';
    try {
      const result = await api('/api/oracle/daily/enrich', { method: 'POST', body: JSON.stringify({ date: today() }) });
      const text = result.enriched || result.text || '';
      enrichOutput.innerHTML = '<span class="oracle-enriched-label">YVES \u00b7 Enriched Reading</span>';
      enrichOutput.appendChild($('p', 'oracle-enriched-text', text));
      status('Enriched.', 'ok');
    } catch (error) {
      enrichOutput.innerHTML = `<span class="oracle-enriched-label">YVES \u00b7 Enriched Reading</span><p class="oracle-enriched-text" style="color:var(--red)">Enrichment unavailable: ${error.message}</p>`;
      status(error.message, 'error');
    } finally {
      enrichBtn.disabled = false;
      enrichBtn.textContent = '\u2728 Enrich with YVES';
      delete enrichBtn.dataset.loading;
    }
  });
}

function makeInsightCard(label, text, italic) {
  const card = $('div', 'oracle-insight-card');
  card.appendChild($('span', 'oracle-insight-label', label));
  const textEl = $('p', italic ? 'oracle-insight-text oracle-insight-italic' : 'oracle-insight-text', text);
  card.appendChild(textEl);
  return { card, setText: (t) => { textEl.textContent = t || ''; } };
}

function makePromptCard(label, text) {
  const card = $('div', 'oracle-prompt-card');
  card.appendChild($('span', 'oracle-prompt-label', label));
  const textEl = $('p', 'oracle-prompt-text', text);
  card.appendChild(textEl);
  return { card, setText: (t) => { textEl.textContent = t || ''; } };
}

function makeNumPill(label, value) {
  const pill = $('div', 'oracle-num-pill');
  pill.appendChild($('span', 'oracle-num-pill-label', label));
  pill.appendChild($('strong', 'oracle-num-pill-value', value));
  return pill;
}

function bridgeToChat() {
  const signs = _state?.synchronicities || [];
  const mans = (_state?.manifestations || []).filter((m) => m.status === 'active');
  const parts = ["What's my Oracle today?"];
  if (mans.length) parts.push(`(Active: ${mans.map((m) => m.title).slice(0, 2).join(', ')})`);
  if (signs[0]) parts.push(`(Latest sign: ${signs[0].value})`);
  const message = parts.join(' ');
  window.dispatchEvent(new CustomEvent('oracle:bridge-to-chat', { detail: { message } }));
  closeModal();
}

// ─── Journal Tab ──────────────────────────────────────────────────────────────

function renderJournal(body) {
  body.classList.add('oracle-body--journal');

  // Gratitude section
  const gratSection = $('div', 'oracle-journal-section-wrap');
  gratSection.appendChild($('h4', 'oracle-journal-section', 'Gratitude Ritual'));
  const gratForm = $('form', 'oracle-journal-form');
  gratForm.append(
    field('3 already mine', 'grateful_for', '', { multiline: true, placeholder: 'One per line' }),
    field('3 on its way', 'thankful_before_materialised', '', { multiline: true, placeholder: 'One per line' }),
    field('Receipt I created', 'action_receipt', '', { placeholder: 'One real action taken today' }),
    field('Sign seen', 'signs_seen', '', { placeholder: '333, dream, repeated date\u2026' }),
    field('Scripting (optional)', 'scripting', '', { multiline: true }),
  );
  const gratSave = $('button', 'oracle-primary', 'Save Gratitude');
  gratSave.type = 'submit';
  gratForm.appendChild(gratSave);
  gratForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = formData(gratForm);
    data.grateful_for = splitLines(data.grateful_for);
    data.thankful_before_materialised = splitLines(data.thankful_before_materialised);
    data.signs_seen = splitLines(data.signs_seen);
    try {
      await api('/api/oracle/gratitude', { method: 'POST', body: JSON.stringify(data) });
      await load(); status('Gratitude saved.', 'ok'); render();
    } catch (error) { status(error.message, 'error'); }
  });
  gratSection.appendChild(gratForm);

  const entries = _state?.gratitude_entries || [];
  if (entries.length) {
    const feed = $('div', 'oracle-feed');
    entries.slice(0, 10).forEach((item) => {
      const row = $('div', 'oracle-feed-item');
      row.appendChild($('span', 'oracle-feed-date', fmt(item.date)));
      const items = [...(item.grateful_for || []), ...(item.thankful_before_materialised || [])];
      if (items.length) row.appendChild($('p', 'oracle-feed-body', items.join(' \u00b7 ')));
      if (item.action_receipt) row.appendChild($('p', 'oracle-feed-receipt', `\u2713 ${item.action_receipt}`));
      feed.appendChild(row);
    });
    gratSection.appendChild(feed);
  }
  body.appendChild(gratSection);

  // Signs section
  const signsSection = $('div', 'oracle-journal-section-wrap');
  signsSection.appendChild($('h4', 'oracle-journal-section', 'Signs \u0026 Synchronicities'));
  const signForm = $('form', 'oracle-journal-form');
  signForm.append(
    field('Date', 'date', today(), { type: 'date' }),
    select('Type', 'type', 'angel_number', [
      ['angel_number', 'Angel number'], ['date', 'Date'], ['dream', 'Dream'],
      ['tarot', 'Tarot / reading'], ['coincidence', 'Coincidence'], ['other', 'Other'],
    ]),
    field('Value', 'value', '', { placeholder: '333, repeated address, dream symbol\u2026' }),
    field('Context', 'context', '', { placeholder: 'Where/when you saw it' }),
    field('Meaning (your interpretation)', 'meaning', ''),
    field('Action prompt', 'action_prompt', '', { placeholder: 'What real action does this call for?' }),
  );
  const signSave = $('button', 'oracle-primary', 'Log Sign');
  signSave.type = 'submit';
  signForm.appendChild(signSave);
  signForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = formData(signForm);
    if (String(data.value).trim() === '333' && !data.meaning) {
      data.meaning = 'Symbolically: support, growth, guidance, creative expression.';
      data.action_prompt = data.action_prompt || 'Turn the sign into a receipt: create, bid, apply, train, or document evidence.';
    }
    try {
      await api('/api/oracle/signs', { method: 'POST', body: JSON.stringify(data) });
      await load(); status('Sign logged.', 'ok'); render();
    } catch (error) { status(error.message, 'error'); }
  });
  signsSection.appendChild(signForm);

  const signs = _state?.synchronicities || [];
  if (signs.length) {
    const signFeed = $('div', 'oracle-feed');
    signs.slice(0, 10).forEach((item) => {
      const row = $('div', 'oracle-feed-item');
      row.appendChild($('span', 'oracle-feed-date', `${fmt(item.date)} \u00b7 ${item.type || 'sign'}`));
      row.appendChild($('p', 'oracle-feed-title', item.value || 'Sign'));
      if (item.meaning) row.appendChild($('p', 'oracle-feed-body', item.meaning));
      if (item.action_prompt) row.appendChild($('p', 'oracle-feed-receipt', `\u21a3 ${item.action_prompt}`));
      signFeed.appendChild(row);
    });
    signsSection.appendChild(signFeed);
  } else {
    signsSection.appendChild($('p', 'oracle-empty', 'No signs logged yet.'));
  }
  body.appendChild(signsSection);
}

// ─── Manifestations Tab ───────────────────────────────────────────────────────

function renderManifestations(body) {
  body.classList.add('oracle-body--manifestations');

  const formCard = $('div', 'oracle-manifest-form');
  formCard.appendChild($('h4', 'oracle-journal-section', 'Add Manifestation'));
  const form = $('form', 'oracle-form oracle-form-compact');
  form.append(
    field('Title', 'title', '', { placeholder: 'Council home, apprenticeship, peace\u2026' }),
    select('Category', 'category', 'housing', [
      ['housing', 'Housing'], ['money', 'Money'], ['apprenticeship', 'Apprenticeship'],
      ['daughter', 'Daughter'], ['peace', 'Peace'], ['creativity', 'Creativity'],
      ['love', 'Love'], ['custom', 'Custom'],
    ]),
    field('Statement', 'statement', '', { multiline: true, placeholder: 'I am becoming the man who\u2026' }),
    field('Target date', 'target_date', '', { type: 'date' }),
    field('First action receipt', 'action_receipts', '', { placeholder: 'One real action taken' }),
  );
  const addBtn = $('button', 'oracle-primary', 'Add Manifestation');
  addBtn.type = 'submit';
  form.appendChild(addBtn);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = formData(form);
    data.action_receipts = splitLines(data.action_receipts);
    try {
      await api('/api/oracle/manifestations', { method: 'POST', body: JSON.stringify(data) });
      await load(); status('Manifestation saved.', 'ok'); render();
    } catch (error) { status(error.message, 'error'); }
  });
  formCard.appendChild(form);
  body.appendChild(formCard);

  const items = _state?.manifestations || [];
  if (!items.length) {
    body.appendChild($('p', 'oracle-empty', 'No manifestations yet. Start with one aim and one receipt you can prove today.'));
    return;
  }

  const list = $('div', 'oracle-manifest-list');
  items.forEach((item) => {
    const card = $('div', 'oracle-manifest-card');
    card.appendChild($('strong', 'oracle-manifest-title', item.title || 'Manifestation'));
    const metaRow = $('div', 'oracle-manifest-meta');
    const badge = $('span', 'oracle-manifest-badge', item.status || 'active');
    badge.dataset.status = item.status || 'active';
    const catBadge = $('span', 'oracle-manifest-badge oracle-manifest-badge--cat', item.category || 'custom');
    const stats = $('span', 'oracle-manifest-stats', `${(item.evidence || []).length} evidence \u00b7 ${(item.action_receipts || []).length} receipts`);
    metaRow.append(badge, catBadge, stats);
    card.appendChild(metaRow);
    if (item.statement) card.appendChild($('p', 'oracle-manifest-statement', item.statement));

    if ((item.evidence || []).length) {
      const evList = $('ul', 'oracle-manifest-items-list');
      item.evidence.forEach((ev) => evList.appendChild($('li', 'oracle-manifest-item-row', `\u2713 ${ev}`)));
      card.appendChild(evList);
    }
    if ((item.action_receipts || []).length) {
      const recList = $('ul', 'oracle-manifest-items-list');
      item.action_receipts.slice(-3).forEach((rec) => recList.appendChild($('li', 'oracle-manifest-item-row oracle-manifest-item-receipt', `\u21a3 ${rec}`)));
      card.appendChild(recList);
    }

    const evidenceInline = makeInlineInput('Evidence from reality?', async (value) => {
      await api(`/api/oracle/manifestations/${encodeURIComponent(item.id)}`, { method: 'PATCH', body: JSON.stringify({ evidence: value }) });
      await load(); status('Evidence added.', 'ok'); render();
    });
    card.appendChild(evidenceInline.container);

    const receiptInline = makeInlineInput('Action receipt you created?', async (value) => {
      await api(`/api/oracle/manifestations/${encodeURIComponent(item.id)}`, { method: 'PATCH', body: JSON.stringify({ action_receipt: value }) });
      await load(); status('Receipt added.', 'ok'); render();
    });
    card.appendChild(receiptInline.container);

    const controls = $('div', 'oracle-manifest-controls');
    const addEvidenceBtn = $('button', 'oracle-manifest-ctrl-btn', '+ Evidence');
    addEvidenceBtn.type = 'button';
    addEvidenceBtn.addEventListener('click', () => { receiptInline.close(); evidenceInline.toggle(); });
    const addReceiptBtn = $('button', 'oracle-manifest-ctrl-btn', '+ Receipt');
    addReceiptBtn.type = 'button';
    addReceiptBtn.addEventListener('click', () => { evidenceInline.close(); receiptInline.toggle(); });
    controls.append(addEvidenceBtn, addReceiptBtn);

    [['Active', 'active'], ['Paused', 'paused'], ['Materialised', 'materialised'], ['Released', 'released']].forEach(([label, s]) => {
      const btn = $('button', `oracle-manifest-ctrl-btn${item.status === s ? ' oracle-manifest-ctrl-btn--active' : ''}`, label);
      btn.type = 'button';
      btn.addEventListener('click', async () => {
        try {
          await api(`/api/oracle/manifestations/${encodeURIComponent(item.id)}`, { method: 'PATCH', body: JSON.stringify({ status: s }) });
          await load(); status('Status updated.', 'ok'); render();
        } catch (error) { status(error.message, 'error'); }
      });
      controls.appendChild(btn);
    });
    card.appendChild(controls);
    list.appendChild(card);
  });
  body.appendChild(list);
}

function makeInlineInput(placeholder, onSave) {
  const container = $('div', 'oracle-manifest-inline-input');
  const textarea = document.createElement('textarea');
  textarea.placeholder = placeholder;
  textarea.className = 'oracle-manifest-inline-textarea';
  const saveBtn = $('button', 'oracle-primary oracle-manifest-inline-save', 'Save');
  saveBtn.type = 'button';
  saveBtn.addEventListener('click', async () => {
    const value = textarea.value.trim();
    if (!value) return;
    try {
      saveBtn.disabled = true;
      await onSave(value);
    } catch (error) {
      status(error.message, 'error');
    } finally {
      saveBtn.disabled = false;
    }
  });
  container.append(textarea, saveBtn);
  return {
    container,
    toggle() {
      const isOpen = container.dataset.open === 'true';
      if (isOpen) { delete container.dataset.open; textarea.value = ''; }
      else { container.dataset.open = 'true'; setTimeout(() => textarea.focus(), 50); }
    },
    close() { delete container.dataset.open; textarea.value = ''; },
  };
}

// ─── Cosmos Tab (accordion) ───────────────────────────────────────────────────

function renderCosmos(body) {
  body.classList.add('oracle-body--cosmos');
  const sections = [
    { id: 'profile', label: 'Birth & Vedic Profile', render: renderCosmosProfile },
    { id: 'numerology', label: 'Numerology Lab', render: renderCosmosNumerology },
    { id: 'calendar', label: 'Cosmic Calendar', render: renderCosmosCalendar },
    { id: 'settings', label: 'Spiritual Settings', render: renderCosmosSettings },
  ];
  sections.forEach(({ label, render: renderFn }) => {
    const section = $('div', 'oracle-cosmos-section');
    const toggle = $('button', 'oracle-cosmos-toggle');
    toggle.type = 'button';
    const labelSpan = $('span', '', label);
    const chevron = $('span', 'oracle-cosmos-chevron', '\u25be');
    toggle.append(labelSpan, chevron);
    const sectionBody = $('div', 'oracle-cosmos-body');
    renderFn(sectionBody);
    toggle.addEventListener('click', () => {
      const isOpen = toggle.dataset.open === 'true';
      if (isOpen) { delete toggle.dataset.open; delete sectionBody.dataset.open; }
      else { toggle.dataset.open = 'true'; sectionBody.dataset.open = 'true'; }
    });
    section.append(toggle, sectionBody);
    body.appendChild(section);
  });
}

function renderCosmosProfile(body) {
  const profile = _state?.birth_profile || {};
  body.appendChild($('p', 'oracle-muted', 'Owner seed fills empty fields only. Vedic placements stored manually.'));
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
      await load(); status('Birth profile saved.', 'ok'); render();
    } catch (error) { status(error.message, 'error'); }
  });
  body.appendChild(form);
}

function renderCosmosNumerology(body) {
  body.appendChild($('p', 'oracle-muted', 'Uses seeded DOB. Preserves master numbers 11, 22, and 33.'));
  const form = $('form', 'oracle-form oracle-form-compact');
  form.append(
    field('Date', 'date', today(), { type: 'date' }),
    field('Label', 'label', ''),
    select('Type', 'type', 'personal', [
      ['personal', 'Personal'], ['spiritual', 'Spiritual'],
      ['housing', 'Housing'], ['money', 'Money'], ['custom', 'Custom'],
    ]),
  );
  const quick = $('div', 'oracle-actions');
  const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
  [['Today', today()], ['Tomorrow', tomorrow.toISOString().slice(0, 10)], ['Birthday', `${new Date().getFullYear()}-07-21`]].forEach(([label, value]) => {
    const btn = $('button', 'oracle-secondary', label);
    btn.type = 'button';
    btn.addEventListener('click', () => { form.elements.date.value = value; form.dispatchEvent(new Event('submit', { cancelable: true })); });
    quick.appendChild(btn);
  });
  const output = $('div', 'oracle-num-results');
  const calc = $('button', 'oracle-primary', 'Calculate');
  calc.type = 'submit';
  form.appendChild(calc);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const result = await api('/api/oracle/numerology', { method: 'POST', body: JSON.stringify({ ...formData(form), save: true }) });
      output.replaceChildren();
      const numStrip = $('div', 'oracle-numerology-strip');
      [['Life Path', result.life_path], ['Personal Day', result.personal_day], ['Universal Day', result.universal_day], ['Personal Year', result.personal_year], ['Personal Month', result.personal_month]]
        .filter(([, v]) => v !== undefined && v !== null)
        .forEach(([l, v]) => numStrip.appendChild(makeNumPill(l, v)));
      output.appendChild(numStrip);
      if (result.interpretation) output.appendChild($('p', 'oracle-muted', result.interpretation));
      if (result.best_use) output.appendChild($('p', '', `Best use: ${result.best_use}`));
      if (result.caution) output.appendChild($('p', '', `Caution: ${result.caution}`));
      if (result.action_suggestion) output.appendChild($('p', '', `Action: ${result.action_suggestion}`));
      status('Numerology calculated.', 'ok');
    } catch (error) { status(error.message, 'error'); }
  });
  body.append(form, quick, output);
}

function renderCosmosCalendar(body) {
  body.appendChild($('p', 'oracle-muted', 'Local Mercury retrograde reference. No live ephemeris.'));
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
      await load(); status('Important date saved.', 'ok'); render();
    } catch (error) { status(error.message, 'error'); }
  });
  body.appendChild(form);
  const output = $('div', 'oracle-calendar-output');
  body.appendChild(output);
  api('/api/oracle/cosmic-calendar').then((calendar) => {
    output.replaceChildren();
    const next = calendar.next_mercury_retrograde;
    if (next) {
      const nextCard = $('div', 'oracle-insight-card');
      nextCard.appendChild($('span', 'oracle-insight-label', 'Next Mercury Retrograde'));
      nextCard.appendChild($('p', 'oracle-insight-text', `${next.start} \u2192 ${next.end}`));
      output.appendChild(nextCard);
    }
    if ((calendar.important_dates || []).length) {
      output.appendChild($('h4', 'oracle-journal-section', 'Your Important Dates'));
      calendar.important_dates.forEach((item) => {
        const row = $('div', 'oracle-feed-item');
        row.appendChild($('span', 'oracle-feed-date', fmt(item.date)));
        row.appendChild($('p', 'oracle-feed-title', item.label));
        if (item.notes) row.appendChild($('p', 'oracle-feed-body', item.notes));
        output.appendChild(row);
      });
    }
    (calendar.upcoming_mercury_retrogrades || []).slice(0, 4).forEach((period) => {
      const row = $('div', 'oracle-feed-item');
      row.appendChild($('span', 'oracle-feed-date', `${period.start} \u2192 ${period.end}`));
      row.appendChild($('p', 'oracle-feed-title', period.label || 'Mercury Retrograde'));
      output.appendChild(row);
    });
  }).catch((error) => status(error.message, 'error'));
}

function renderCosmosSettings(body) {
  const prefs = _state?.spiritual_preferences || {};
  body.appendChild($('p', 'oracle-muted', 'Tone and guardrails.'));
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
      await load(); status('Oracle settings saved.', 'ok'); render();
    } catch (error) { status(error.message, 'error'); }
  });
  body.appendChild(form);
}

// ─── Render orchestration ─────────────────────────────────────────────────────

function render() {
  if (!_modal) return;
  const tabs = _modal.querySelector('[data-oracle-tabs]');
  const body = _modal.querySelector('[data-oracle-body]');
  tabs.replaceChildren();
  body.replaceChildren();
  body.className = 'oracle-body';

  TABS.forEach(([id, label]) => {
    const button = $('button', 'oracle-tab', label);
    button.type = 'button';
    button.dataset.active = id === _activeTab ? 'true' : 'false';
    button.addEventListener('click', () => { _activeTab = id; render(); });
    tabs.appendChild(button);
  });

  const map = { today: renderToday, journal: renderJournal, manifestations: renderManifestations, cosmos: renderCosmos };
  (map[_activeTab] || renderToday)(body);
}

// ─── Modal lifecycle ──────────────────────────────────────────────────────────

function build() {
  ensureStyles();
  _modal = $('div', 'oracle-modal');
  _modal.id = 'oracle-modal';
  _modal.hidden = true;
  _modal.innerHTML = `
    <div class="oracle-content" role="dialog" aria-modal="true" aria-labelledby="oracle-title">
      <header class="oracle-header">
        <h3 id="oracle-title" class="oracle-header-title">Oracle</h3>
        <button type="button" class="oracle-close" aria-label="Close Oracle">&times;</button>
      </header>
      <nav class="oracle-tabs" data-oracle-tabs></nav>
      <div class="oracle-status" data-oracle-status></div>
      <main class="oracle-body" data-oracle-body></main>
    </div>
  `;
  _modal.querySelector('.oracle-close')?.addEventListener('click', () => closeModal());
  _modal.addEventListener('click', (event) => { if (event.target === _modal) closeModal(); });
  document.body.appendChild(_modal);
}

async function open(tab = 'today') {
  if (!_initialized) init();
  _activeTab = tab || 'today';
  _modal.hidden = false;
  document.body.classList.add('modal-open');
  status('Loading Oracle\u2026');
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

function closeModal() {
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

export { init, open, closeModal as close };
export default { init, open, close: closeModal };
