import { makeWindowDraggable } from './windowDrag.js';

let _modal = null;
let _escapeHandler = null;

function _el(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function _sourceName(key) {
  return {
    memory: 'Memory',
    notes: 'Notes',
    documents: 'Library documents',
    housing: 'Housing preferences',
    rag: 'Personal RAG',
  }[key] || key;
}

function _createModal() {
  const modal = _el('div', 'modal brain-health-modal');
  modal.id = 'brain-health-modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-labelledby', 'brain-health-title');
  modal.innerHTML = `
    <div class="modal-content brain-health-content">
      <div class="modal-header brain-health-header">
        <div>
          <span class="brain-health-kicker">Vanta Brain // Read only</span>
          <h4 id="brain-health-title">Brain Health</h4>
        </div>
        <button type="button" class="modal-close brain-health-close" aria-label="Close Brain Health">&times;</button>
      </div>
      <div class="brain-health-body">
        <div id="brain-health-summary" class="brain-health-summary"></div>
        <div id="brain-health-sources" class="brain-health-sources"></div>
        <form id="brain-health-preview-form" class="brain-health-preview">
          <label for="brain-health-query">Test retrieval</label>
          <div class="brain-health-query-row">
            <input id="brain-health-query" type="search" maxlength="1000" placeholder="Ask what Vanta should retrieve..." required>
            <button type="submit">Preview</button>
          </div>
          <p>Preview is private, user-scoped, and does not change your data.</p>
        </form>
        <div id="brain-health-results" class="brain-health-results" aria-live="polite"></div>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  const content = modal.querySelector('.brain-health-content');
  const header = modal.querySelector('.brain-health-header');
  makeWindowDraggable(modal, {
    content,
    header,
    skipSelector: 'button, input',
    enableResize: false,
    enableDock: false,
  });

  modal.querySelector('.brain-health-close').addEventListener('click', close);
  modal.addEventListener('click', (event) => {
    if (event.target === modal) close();
  });
  modal.querySelector('#brain-health-preview-form').addEventListener('submit', _preview);
  return modal;
}

function _renderHealth(payload) {
  const summary = document.getElementById('brain-health-summary');
  const sources = document.getElementById('brain-health-sources');
  summary.replaceChildren();
  sources.replaceChildren();

  const overall = payload && payload.overall === 'ok' ? 'All sources ready' : 'Brain operating in degraded mode';
  summary.append(
    _el('span', `brain-health-orb ${payload && payload.overall === 'ok' ? 'is-ready' : 'is-degraded'}`),
    _el('div', '', overall),
  );

  const sourcePayload = payload && payload.sources ? payload.sources : {};
  ['memory', 'notes', 'documents', 'housing', 'rag'].forEach((key) => {
    const source = sourcePayload[key] || {};
    const row = _el('section', 'brain-health-source');
    const heading = _el('div', 'brain-health-source-heading');
    heading.append(
      _el('strong', '', _sourceName(key)),
      _el('span', source.ready ? 'is-ready' : 'is-degraded', source.ready ? 'Ready' : 'Degraded'),
    );
    row.appendChild(heading);

    if (key === 'rag') {
      row.appendChild(_el(
        'p',
        '',
        `${Number(source.chunk_count || 0)} owner-visible chunks // ${Number(source.listed_document_count || 0)} listed documents`,
      ));
      if (Number(source.likely_unindexed_count || 0) > 0) {
        row.appendChild(_el('p', 'brain-health-warning', `${source.likely_unindexed_count} listed document(s) may be unindexed.`));
      }
      const lanes = Array.isArray(source.embedding_lanes) ? source.embedding_lanes : [];
      lanes.forEach((lane) => {
        row.appendChild(_el(
          'div',
          'brain-health-lane',
          `${lane.name || 'lane'} // ${lane.model || 'model unknown'} // ${Number(lane.count || 0)} chunks`,
        ));
      });
    } else {
      row.appendChild(_el('p', '', `${Number(source.count || 0)} available`));
      if (key === 'housing') {
        row.appendChild(_el(
          'div',
          'brain-health-lane',
          source.schema_recognized ? 'Stored schema recognised' : 'Stored schema not recognised',
        ));
      }
    }
    sources.appendChild(row);
  });

  const errors = Array.isArray(payload && payload.errors) ? payload.errors : [];
  errors.forEach((error) => {
    sources.appendChild(_el('div', 'brain-health-error', error.detail || 'A source is degraded.'));
  });
}

function _renderPreview(payload) {
  const results = document.getElementById('brain-health-results');
  results.replaceChildren();
  const sources = Array.isArray(payload && payload.sources) ? payload.sources : [];
  if (!sources.length) {
    results.appendChild(_el('div', 'brain-health-empty', 'No matching private context was found.'));
    return;
  }
  sources.forEach((source) => {
    const item = _el('article', 'brain-health-result');
    const heading = _el('div', 'brain-health-result-heading');
    heading.append(
      _el('span', '', String(source.source || 'source').toUpperCase()),
      _el('strong', '', source.label || 'Untitled'),
    );
    item.append(heading, _el('p', '', source.text || ''));
    results.appendChild(item);
  });
}

async function _loadHealth() {
  const summary = document.getElementById('brain-health-summary');
  summary.replaceChildren(_el('div', 'brain-health-loading', 'Running private source checks...'));
  try {
    const response = await fetch('/api/brain/health', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error(`Health request failed (${response.status})`);
    _renderHealth(await response.json());
  } catch (error) {
    console.error('Brain health failed:', error);
    summary.replaceChildren(_el('div', 'brain-health-error', 'Brain health is unavailable. No data was changed.'));
  }
}

async function _preview(event) {
  event.preventDefault();
  const input = document.getElementById('brain-health-query');
  const button = event.currentTarget.querySelector('button');
  const query = input.value.trim();
  if (!query) return;

  button.disabled = true;
  button.textContent = 'Checking...';
  const results = document.getElementById('brain-health-results');
  results.replaceChildren(_el('div', 'brain-health-loading', 'Retrieving bounded snippets...'));
  try {
    const response = await fetch('/api/brain/preview', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });
    if (!response.ok) throw new Error(`Preview request failed (${response.status})`);
    _renderPreview(await response.json());
  } catch (error) {
    console.error('Brain preview failed:', error);
    results.replaceChildren(_el('div', 'brain-health-error', 'Preview is unavailable. No data was changed.'));
  } finally {
    button.disabled = false;
    button.textContent = 'Preview';
  }
}

function open() {
  _modal = _modal || _createModal();
  _modal.style.display = 'flex';
  _escapeHandler = (event) => {
    if (event.key === 'Escape') close();
  };
  document.addEventListener('keydown', _escapeHandler);
  _loadHealth();
}

function close() {
  if (_modal) _modal.style.display = 'none';
  if (_escapeHandler) document.removeEventListener('keydown', _escapeHandler);
  _escapeHandler = null;
}

const brainHealthModule = { open, close };

export { open, close };
export default brainHealthModule;
