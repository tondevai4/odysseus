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

function _formatDate(value) {
  if (!value) return '';
  const date = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

function _formatMoney(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return '';
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'GBP',
    maximumFractionDigits: 2,
  }).format(amount);
}

function _summaryRow(parent, label, value) {
  if (!value) return;
  const row = _text(parent, 'div', 'command-summary-row', '');
  _text(row, 'span', '', label);
  _text(row, 'strong', '', value);
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

function _normalizeHousingEntry(entry) {
  if (!entry || typeof entry !== 'object') return null;
  const property = String(
    entry.propertyArea || entry.property || entry.area || entry.address || entry.title || '',
  ).trim();
  const date = String(entry.dateBidded || entry.bidDate || entry.date || '').trim();
  if (!property || !date) return null;
  return {
    property,
    date,
    status: String(entry.status || '').trim(),
    updatedAt: String(entry.updatedAt || entry.updated_at || date),
  };
}

async function _loadHousingSummary() {
  const body = document.getElementById('command-housing-body');
  if (!body) return;
  try {
    const response = await fetch('/api/prefs/housing-bids-v1', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error('Housing tracker unavailable');
    const payload = await response.json();
    const entries = Array.isArray(payload.value?.entries)
      ? payload.value.entries.map(_normalizeHousingEntry).filter(Boolean)
      : [];
    entries.sort((a, b) => (
      b.date.localeCompare(a.date) || b.updatedAt.localeCompare(a.updatedAt)
    ));
    body.replaceChildren();
    if (!entries.length) {
      _text(body, 'p', 'command-data-empty', 'No housing bids saved yet.');
      return;
    }
    const latest = entries[0];
    _summaryRow(body, 'Saved bids', String(entries.length));
    _summaryRow(body, 'Latest', latest.property);
    _summaryRow(body, 'Bidded', _formatDate(latest.date));
    if (latest.status) _summaryRow(body, 'Status', _label(latest.status));
  } catch {
    body.replaceChildren();
    _text(body, 'p', 'command-data-empty', 'Housing tracker is unavailable right now.');
  }
}

function _statementCandidates(documents) {
  const likely = /\b(revolut|bank|statement|account)\b/i;
  return (Array.isArray(documents) ? documents : [])
    .filter((document) => document?.id && document.language === 'pdf')
    .sort((a, b) => Number(likely.test(b.title || '')) - Number(likely.test(a.title || '')))
    .slice(0, 5);
}

function _topLeak(categoryTotals) {
  const ignored = new Set(['income', 'internal_savings_transfer']);
  return Object.entries(categoryTotals || {})
    .filter(([category, value]) => !ignored.has(category) && Number(value) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))[0] || null;
}

async function _loadMoneySummary() {
  const body = document.getElementById('command-money-body');
  const action = document.querySelector('[data-command-center-action="finance"]');
  if (!body || !action) return;
  action.dataset.financeDocumentId = '';
  try {
    const libraryResponse = await fetch('/api/documents/library?sort=recent&limit=50', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!libraryResponse.ok) throw new Error('Library unavailable');
    const library = await libraryResponse.json();
    let statement = null;
    for (const document of _statementCandidates(library.documents)) {
      const response = await fetch('/api/finance/preview-statement', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ document_id: document.id }),
      });
      if (!response.ok) continue;
      statement = { document, payload: await response.json() };
      break;
    }

    body.replaceChildren();
    if (!statement) {
      _text(
        body,
        'p',
        'command-data-empty',
        'Upload a Revolut statement to unlock money analysis.',
      );
      action.firstChild.textContent = 'Open Library ';
      return;
    }

    const summary = statement.payload.summary || {};
    const range = summary.date_range || {};
    const period = range.start && range.end
      ? `${_formatDate(range.start)} - ${_formatDate(range.end)}`
      : _formatDate(range.start || range.end);
    const leak = _topLeak(summary.category_totals);
    _summaryRow(body, 'Statement period', period);
    _summaryRow(
      body,
      'External spend',
      _formatMoney(summary.external_spend_excluding_internal_savings),
    );
    if (leak) _summaryRow(body, 'Top leak', `${_label(leak[0])} · ${_formatMoney(leak[1])}`);
    action.dataset.financeDocumentId = statement.document.id;
    action.firstChild.textContent = 'Open Statement ';
  } catch {
    body.replaceChildren();
    _text(body, 'p', 'command-data-empty', 'Money analysis is unavailable right now.');
  }
}

function init({
  openNotes,
  openHousingBids,
  openReadingList,
  openReadingDocument,
  downloadReadingDocument,
  openFinance,
  openBrainHealth,
  runRoutine,
} = {}) {
  if (_initialized) return;

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
      action.dataset.commandCenterAction === 'finance'
      && typeof openFinance === 'function'
    ) {
      openFinance(action.dataset.financeDocumentId || '');
    }
    if (
      action.dataset.commandCenterAction === 'brain-health'
      && typeof openBrainHealth === 'function'
    ) {
      openBrainHealth();
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
  _loadHousingSummary();
  _loadMoneySummary();
  window.addEventListener('vanta:reading-list-updated', () => {
    _loadCurrentReading(readingOptions);
  });
  window.addEventListener('vanta:housing-bids-updated', _loadHousingSummary);
  _initialized = true;
}

const commandCenterModule = { init };

export { init };
export default commandCenterModule;
