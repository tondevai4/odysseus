import uiModule from './ui.js';
import sessionModule from './sessions.js';
import markdownModule from './markdown.js';
import { makeWindowDraggable } from './windowDrag.js';

const API = '/api/archive';
let history = [];
let latestAnswer = '';
let latestSources = [];
let openState = false;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error || 'The Archive is unavailable.');
  return data;
}

function modal() {
  return document.getElementById('archive-modal');
}

function createModal() {
  const shell = el('div', 'modal archive-modal');
  shell.id = 'archive-modal';
  shell.setAttribute('role', 'dialog');
  shell.setAttribute('aria-modal', 'true');
  shell.innerHTML = `
    <div class="modal-content archive-content">
      <header class="archive-header">
        <div>
          <span class="archive-kicker">Clean-room investigation</span>
          <h4>The Archive</h4>
          <p>No Vanta Brain. No personal context. Evidence first.</p>
        </div>
        <button type="button" class="modal-close archive-close" aria-label="Close The Archive">&times;</button>
      </header>
      <div class="archive-layout">
        <aside class="archive-dossiers">
          <div class="archive-section-heading">
            <span>Dossiers</span>
            <button type="button" class="archive-quiet" id="archive-refresh-dossiers">Refresh</button>
          </div>
          <div id="archive-dossier-list" class="archive-dossier-list"></div>
        </aside>
        <section class="archive-room">
          <div class="archive-toolbar">
            <label><input type="checkbox" id="archive-use-web" checked> Search web</label>
            <span>Fact / claim / inference / unknown</span>
          </div>
          <div class="archive-answer-area" id="archive-answer-area">
            <div class="archive-empty">
              <span class="archive-kicker">CASE FILE READY</span>
              <h3>What are we investigating?</h3>
              <p>Ask for a claim origin, timeline, evidence table, source trail, or current confidence.</p>
            </div>
          </div>
          <div class="archive-save-panel" id="archive-save-panel" hidden>
            <input id="archive-save-title" maxlength="200" placeholder="Dossier title">
            <button type="button" class="archive-secondary" id="archive-save-confirm">Save dossier</button>
          </div>
          <form class="archive-composer" id="archive-form">
            <textarea id="archive-input" rows="3" maxlength="30000" placeholder="Investigate a claim..."></textarea>
            <div class="archive-composer-actions">
              <button type="button" class="archive-secondary" id="archive-save-current" disabled>Save dossier</button>
              <button type="submit" class="archive-primary" id="archive-send">Investigate</button>
            </div>
          </form>
        </section>
      </div>
    </div>`;
  document.body.appendChild(shell);
  makeWindowDraggable(shell, {
    content: shell.querySelector('.archive-content'),
    header: shell.querySelector('.archive-header'),
    enableResize: false,
    enableDock: false,
  });
  shell.querySelector('.archive-close').addEventListener('click', close);
  shell.querySelector('#archive-form').addEventListener('submit', send);
  shell.querySelector('#archive-refresh-dossiers').addEventListener('click', loadDossiers);
  shell.querySelector('#archive-save-current').addEventListener('click', showSavePanel);
  shell.querySelector('#archive-save-confirm').addEventListener('click', saveCurrentDossier);
  shell.addEventListener('click', (event) => {
    if (event.target === shell) close();
  });
  return shell;
}

function renderSources(parent, sources) {
  if (!sources?.length) return;
  const section = el('section', 'archive-source-section');
  section.appendChild(el('h4', '', 'Source trail'));
  const grid = el('div', 'archive-source-grid');
  sources.forEach((source, index) => {
    const card = el('a', 'archive-source-card');
    card.href = source.url;
    card.target = '_blank';
    card.rel = 'noopener noreferrer';
    card.append(
      el('span', 'archive-source-index', String(index + 1).padStart(2, '0')),
      el('strong', '', source.title || source.url),
      el('small', '', source.quality || 'web source'),
    );
    grid.appendChild(card);
  });
  section.appendChild(grid);
  parent.appendChild(section);
}

function renderTurn(role, content, sources = []) {
  const area = document.getElementById('archive-answer-area');
  if (area.querySelector('.archive-empty')) area.replaceChildren();
  const article = el('article', `archive-turn archive-turn-${role}`);
  article.appendChild(el('span', 'archive-turn-role', role === 'user' ? 'INVESTIGATOR' : 'ARCHIVE'));
  const body = el('div', 'archive-turn-body');
  if (role === 'assistant') {
    body.innerHTML = markdownModule.renderContent(content);
  } else {
    body.textContent = content;
  }
  article.appendChild(body);
  renderSources(article, sources);
  area.appendChild(article);
  area.scrollTop = area.scrollHeight;
}

function currentSessionId() {
  return sessionModule.getCurrentSessionId?.() || '';
}

function incognitoActive() {
  const toggle = document.getElementById('incognito-toggle');
  const indicator = document.getElementById('incognito-indicator');
  return Boolean(toggle?.checked || (indicator && indicator.style.display !== 'none'));
}

async function send(event) {
  event.preventDefault();
  const input = document.getElementById('archive-input');
  const button = document.getElementById('archive-send');
  const message = input.value.trim();
  if (!message) return;
  const session = currentSessionId();
  if (!session) {
    uiModule.showToast('Select a model chat before using The Archive.', 'error');
    return;
  }
  renderTurn('user', message);
  input.value = '';
  button.disabled = true;
  button.textContent = 'Investigating...';
  try {
    const data = await api('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        session,
        history,
        use_web: document.getElementById('archive-use-web').checked,
        incognito: incognitoActive(),
      }),
    });
    latestAnswer = data.answer || '';
    latestSources = data.sources || [];
    history.push({ role: 'user', content: message }, { role: 'assistant', content: latestAnswer });
    history = history.slice(-12);
    renderTurn('assistant', latestAnswer, latestSources);
    document.getElementById('archive-save-current').disabled = !latestAnswer;
    if (data.action?.startsWith('dossier_')) loadDossiers();
  } catch (error) {
    renderTurn('assistant', `Search room error: ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = 'Investigate';
    input.focus();
  }
}

function showSavePanel() {
  if (!latestAnswer) return;
  const panel = document.getElementById('archive-save-panel');
  panel.hidden = false;
  const title = document.getElementById('archive-save-title');
  const lastQuestion = [...history].reverse().find((item) => item.role === 'user');
  title.value = (lastQuestion?.content || 'Archive investigation').slice(0, 120);
  title.focus();
}

async function saveCurrentDossier() {
  if (incognitoActive()) {
    uiModule.showToast('Archive dossier actions are disabled in incognito/private mode.', 'error');
    return;
  }
  const title = document.getElementById('archive-save-title').value.trim();
  if (!title || !latestAnswer) return;
  try {
    await api('/dossiers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title,
        topic: title,
        summary: latestAnswer,
        sources: latestSources,
        confidence: 'unknown',
      }),
    });
    document.getElementById('archive-save-panel').hidden = true;
    uiModule.showToast('Archive dossier saved.', 'success');
    loadDossiers();
  } catch (error) {
    uiModule.showToast(error.message, 'error');
  }
}

function renderDossier(dossier) {
  const button = el('button', 'archive-dossier-card');
  button.type = 'button';
  button.append(
    el('strong', '', dossier.title),
    el('span', '', dossier.topic || 'Investigation'),
    el('small', '', dossier.confidence || 'unknown'),
  );
  button.addEventListener('click', () => {
    latestAnswer = dossier.summary;
    latestSources = dossier.sources || [];
    const area = document.getElementById('archive-answer-area');
    area.replaceChildren();
    renderTurn('assistant', `# ${dossier.title}\n\n${dossier.summary}\n\n**Current confidence:** ${dossier.confidence}`, latestSources);
    document.getElementById('archive-save-current').disabled = false;
  });
  return button;
}

async function loadDossiers() {
  const list = document.getElementById('archive-dossier-list');
  if (!list) return;
  list.replaceChildren(el('p', 'archive-muted', 'Loading dossiers...'));
  try {
    const data = await api('/dossiers');
    list.replaceChildren();
    if (!data.dossiers?.length) {
      list.appendChild(el('p', 'archive-muted', 'No dossiers saved.'));
      return;
    }
    data.dossiers.forEach((dossier) => list.appendChild(renderDossier(dossier)));
  } catch (error) {
    list.replaceChildren(el('p', 'archive-muted', error.message));
  }
}

async function open() {
  const shell = modal() || createModal();
  shell.style.display = 'flex';
  openState = true;
  document.getElementById('tool-investigation-archive-btn')?.classList.add('active');
  await loadDossiers();
  document.getElementById('archive-input')?.focus();
}

function close() {
  const shell = modal();
  if (shell) shell.style.display = 'none';
  openState = false;
  document.getElementById('tool-investigation-archive-btn')?.classList.remove('active');
}

export default { open, close, isOpen: () => openState };
