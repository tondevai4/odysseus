import uiModule from './ui.js';
import { makeWindowDraggable } from './windowDrag.js';

const API_URL = '/api/reading-list';
const STATUSES = ['want_to_read', 'reading', 'finished', 'paused'];
const PRIORITIES = ['low', 'normal', 'high'];
const CATEGORIES = [
  'body', 'money', 'discipline', 'work', 'fatherhood', 'spiritual',
  'reference', 'other',
];

let items = [];
let documents = [];
let openState = false;
let editingId = '';
let escapeHandler = null;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function modal() {
  return document.getElementById('reading-list-modal');
}

function setSidebarActive(active) {
  document.getElementById('tool-reading-list-btn')?.classList.toggle('active', active);
}

async function api(path = '', options = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error || 'Reading List request failed.');
  return data;
}

async function load() {
  const body = document.getElementById('reading-list-body');
  if (body) body.replaceChildren(element('div', 'reading-list-state', 'Loading your shelf...'));
  try {
    const [reading, library] = await Promise.all([
      api(),
      fetch('/api/documents/library?limit=50', {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      }).then((response) => response.ok ? response.json() : { documents: [] }),
    ]);
    items = Array.isArray(reading.items) ? reading.items : [];
    documents = Array.isArray(library.documents) ? library.documents : (
      Array.isArray(library) ? library : []
    );
    render();
  } catch (error) {
    body?.replaceChildren(element('div', 'reading-list-state reading-list-error', error.message));
  }
}

function createModal() {
  const shell = element('div', 'modal reading-list-modal');
  shell.id = 'reading-list-modal';
  shell.setAttribute('role', 'dialog');
  shell.setAttribute('aria-modal', 'true');
  shell.innerHTML = `
    <div class="modal-content reading-list-content">
      <div class="modal-header reading-list-header">
        <div>
          <span class="reading-list-kicker">Private Library shelf</span>
          <h4>Reading List <span id="reading-list-count"></span></h4>
        </div>
        <button type="button" class="modal-close reading-list-close" aria-label="Close Reading List">&times;</button>
      </div>
      <div class="reading-list-toolbar">
        <p>Track books and link owner-visible Library documents.</p>
        <button type="button" class="reading-list-primary" id="reading-list-add">Add Item</button>
      </div>
      <div class="reading-list-body" id="reading-list-body"></div>
    </div>`;
  document.body.appendChild(shell);
  makeWindowDraggable(shell, {
    content: shell.querySelector('.reading-list-content'),
    header: shell.querySelector('.reading-list-header'),
    enableResize: false,
    enableDock: false,
  });
  shell.querySelector('.reading-list-close').addEventListener('click', close);
  shell.querySelector('#reading-list-add').addEventListener('click', () => openForm());
  shell.addEventListener('click', (event) => {
    if (event.target === shell) close();
  });
  return shell;
}

function render() {
  const body = document.getElementById('reading-list-body');
  if (!body) return;
  body.replaceChildren();
  const count = document.getElementById('reading-list-count');
  if (count) count.textContent = items.length ? `(${items.length})` : '';
  if (editingId !== null) {
    renderForm();
    return;
  }
  if (!items.length) {
    const empty = element('div', 'reading-list-state');
    empty.append(
      element('span', 'reading-list-state-mark', 'SHELF READY'),
      element('h3', '', 'Nothing queued yet'),
      element('p', '', 'Add a book, or link a document already in Library.'),
    );
    const add = element('button', 'reading-list-primary', 'Add First Item');
    add.type = 'button';
    add.addEventListener('click', () => openForm());
    empty.appendChild(add);
    body.appendChild(empty);
    return;
  }
  const list = element('div', 'reading-list-grid');
  items.forEach((item) => list.appendChild(renderCard(item)));
  body.appendChild(list);
}

function labelFor(value) {
  return String(value || '').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function selectControl(values, selected, ariaLabel) {
  const select = element('select', 'reading-list-select');
  select.setAttribute('aria-label', ariaLabel);
  values.forEach((value) => {
    const option = element('option', '', labelFor(value));
    option.value = value;
    option.selected = value === selected;
    select.appendChild(option);
  });
  return select;
}

function renderCard(item) {
  const card = element('article', 'reading-list-card');
  const top = element('div', 'reading-list-card-top');
  const title = element('div', '');
  title.append(element('h3', '', item.title));
  if (item.author) title.append(element('p', 'reading-list-author', item.author));
  top.append(title, element('span', `reading-list-priority priority-${item.priority}`, item.priority));
  card.appendChild(top);

  const controls = element('div', 'reading-list-inline-controls');
  const status = selectControl(STATUSES, item.status, `Status for ${item.title}`);
  const progress = element('input', 'reading-list-progress');
  progress.type = 'text';
  progress.maxLength = 160;
  progress.value = item.progress || '';
  progress.placeholder = 'Page, chapter, percent...';
  progress.setAttribute('aria-label', `Progress for ${item.title}`);
  const notes = element('textarea', 'reading-list-notes');
  notes.rows = 2;
  notes.maxLength = 3000;
  notes.value = item.notes || '';
  notes.placeholder = 'Notes';
  notes.setAttribute('aria-label', `Notes for ${item.title}`);
  const save = element('button', 'reading-list-secondary', 'Save');
  save.type = 'button';
  save.addEventListener('click', async () => {
    save.disabled = true;
    try {
      const updated = await api(`/${encodeURIComponent(item.id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          status: status.value,
          progress: progress.value,
          notes: notes.value,
        }),
      });
      items = items.map((row) => row.id === item.id ? updated : row);
      uiModule.showToast('Reading item updated.', 'success');
      render();
    } catch (error) {
      uiModule.showToast(error.message, 'error');
      save.disabled = false;
    }
  });
  controls.append(status, progress, notes, save);
  card.appendChild(controls);

  const meta = element('div', 'reading-list-meta');
  meta.append(
    element('span', '', labelFor(item.category)),
    element('span', '', `Updated ${new Date(item.updated_at).toLocaleDateString()}`),
  );
  card.appendChild(meta);

  const actions = element('div', 'reading-list-actions');
  const edit = element('button', 'reading-list-secondary', 'Edit details');
  edit.type = 'button';
  edit.addEventListener('click', () => openForm(item.id));
  actions.appendChild(edit);
  if (item.document?.available) {
    const openDocument = element('button', 'reading-list-secondary', 'Open document');
    openDocument.type = 'button';
    openDocument.addEventListener('click', () => {
      if (item.document.is_pdf) {
        window.open(`/api/document/${encodeURIComponent(item.document.id)}/render-pdf`, '_blank', 'noopener');
        return;
      }
      close();
      window.documentModule?.loadDocument(item.document.id);
    });
    const download = element('button', 'reading-list-secondary', 'Download');
    download.type = 'button';
    download.addEventListener('click', () => {
      if (item.document.is_pdf) {
        window.location.assign(`/api/document/${encodeURIComponent(item.document.id)}/export-pdf`);
      } else {
        downloadDocument(item.document.id);
      }
    });
    actions.append(openDocument, download);
  } else if (item.document_id) {
    actions.appendChild(element('span', 'reading-list-unavailable', 'Linked document unavailable'));
  }
  card.appendChild(actions);
  return card;
}

async function downloadDocument(documentId) {
  try {
    const response = await fetch(`/api/document/${encodeURIComponent(documentId)}`, {
      credentials: 'same-origin',
    });
    if (!response.ok) throw new Error('Document download failed.');
    const documentData = await response.json();
    const blob = new Blob([documentData.current_content || ''], { type: 'text/plain' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${documentData.title || 'document'}.txt`;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (error) {
    uiModule.showToast(error.message, 'error');
  }
}

function openForm(id = '') {
  editingId = id;
  render();
}

function optionList(select, values, selected) {
  values.forEach((value) => {
    const option = element('option', '', labelFor(value));
    option.value = value;
    option.selected = value === selected;
    select.appendChild(option);
  });
}

function renderForm() {
  const body = document.getElementById('reading-list-body');
  const existing = items.find((item) => item.id === editingId);
  const form = element('form', 'reading-list-form');
  const grid = element('div', 'reading-list-form-grid');
  const fields = {};
  const field = (name, label, node) => {
    const wrapper = element('label', name === 'notes' ? 'reading-list-field wide' : 'reading-list-field');
    wrapper.append(element('span', '', label), node);
    fields[name] = node;
    grid.appendChild(wrapper);
  };
  field('title', 'Title *', Object.assign(element('input'), { maxLength: 200, required: true }));
  field('author', 'Author', Object.assign(element('input'), { maxLength: 160 }));
  const category = element('select');
  optionList(category, CATEGORIES, existing?.category || 'other');
  field('category', 'Category', category);
  const status = element('select');
  optionList(status, STATUSES, existing?.status || 'want_to_read');
  field('status', 'Status', status);
  const priority = element('select');
  optionList(priority, PRIORITIES, existing?.priority || 'normal');
  field('priority', 'Priority', priority);
  field('progress', 'Progress', Object.assign(element('input'), { maxLength: 160 }));
  const documentSelect = element('select');
  documentSelect.appendChild(Object.assign(element('option', '', 'No linked document'), { value: '' }));
  documents.forEach((documentData) => {
    const option = element('option', '', documentData.title || 'Untitled');
    option.value = documentData.id;
    option.selected = documentData.id === existing?.document_id;
    documentSelect.appendChild(option);
  });
  field('document_id', 'Library document', documentSelect);
  field('notes', 'Notes', Object.assign(element('textarea'), { rows: 4, maxLength: 3000 }));

  Object.entries(fields).forEach(([name, node]) => {
    if (existing && name !== 'category' && name !== 'status' && name !== 'priority' && name !== 'document_id') {
      node.value = existing[name] || '';
    }
  });
  const error = element('div', 'reading-list-form-error');
  const actions = element('div', 'reading-list-form-actions');
  const cancel = element('button', 'reading-list-secondary', 'Cancel');
  cancel.type = 'button';
  cancel.addEventListener('click', () => {
    editingId = null;
    render();
  });
  const save = element('button', 'reading-list-primary', existing ? 'Save details' : 'Add to shelf');
  save.type = 'submit';
  actions.append(cancel, save);
  form.append(grid, error, actions);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(
      Object.entries(fields).map(([name, node]) => [name, node.value.trim()]),
    );
    if (!payload.title) {
      error.textContent = 'Title is required.';
      fields.title.focus();
      return;
    }
    save.disabled = true;
    try {
      const result = await api(existing ? `/${encodeURIComponent(existing.id)}` : '', {
        method: existing ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      items = existing
        ? items.map((item) => item.id === existing.id ? result : item)
        : [result, ...items];
      editingId = null;
      uiModule.showToast(existing ? 'Reading item updated.' : 'Added to Reading List.', 'success');
      render();
    } catch (requestError) {
      error.textContent = requestError.message;
      save.disabled = false;
    }
  });
  body.appendChild(form);
  requestAnimationFrame(() => fields.title.focus());
}

function open() {
  const shell = modal() || createModal();
  openState = true;
  editingId = null;
  setSidebarActive(true);
  shell.style.display = 'flex';
  requestAnimationFrame(() => shell.classList.add('show'));
  escapeHandler = (event) => {
    if (event.key === 'Escape') close();
  };
  document.addEventListener('keydown', escapeHandler);
  load();
}

function close() {
  const shell = modal();
  if (!shell) return;
  openState = false;
  setSidebarActive(false);
  shell.classList.remove('show');
  if (escapeHandler) document.removeEventListener('keydown', escapeHandler);
  escapeHandler = null;
  window.setTimeout(() => shell.remove(), 180);
}

function isOpen() {
  return openState;
}

export { open, close, isOpen };
export default { open, close, isOpen };
