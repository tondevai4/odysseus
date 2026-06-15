import uiModule from './ui.js';
import { makeWindowDraggable } from './windowDrag.js';

const PREF_KEY = 'housing-bids-v1';
const PREF_URL = `/api/prefs/${PREF_KEY}`;
const STATUS_OPTIONS = ['Pending', 'Shortlisted', 'Offered', 'Unsuccessful', 'Withdrawn'];
const EMPTY_STATE = { version: 1, entries: [] };

let _state = { ...EMPTY_STATE, entries: [] };
let _isOpen = false;
let _loading = false;
let _saving = false;
let _loadError = '';
let _editingId = null;
let _showForm = false;
let _escapeHandler = null;

function _string(value, maxLength) {
  return typeof value === 'string' ? value.trim().slice(0, maxLength) : '';
}

function _normalizeEntry(entry) {
  if (!entry || typeof entry !== 'object') return null;

  const propertyArea = _string(entry.propertyArea, 160);
  const dateBidded = _string(entry.dateBidded, 10);
  if (!propertyArea || !dateBidded) return null;

  const status = STATUS_OPTIONS.includes(entry.status) ? entry.status : 'Pending';
  const now = new Date().toISOString();

  return {
    id: _string(entry.id, 100) || _createId(),
    propertyArea,
    dateBidded,
    description: _string(entry.description, 300),
    status,
    priorityBand: _string(entry.priorityBand, 120),
    notes: _string(entry.notes, 2000),
    outcome: _string(entry.outcome, 500),
    createdAt: _string(entry.createdAt, 40) || now,
    updatedAt: _string(entry.updatedAt, 40) || now,
  };
}

function _normalizeState(value) {
  if (!value || typeof value !== 'object' || value.version !== 1 || !Array.isArray(value.entries)) {
    return { ...EMPTY_STATE, entries: [] };
  }

  return {
    version: 1,
    entries: value.entries.map(_normalizeEntry).filter(Boolean),
  };
}

function _createId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }
  return `housing-bid-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function _sortEntries(entries) {
  return [...entries].sort((a, b) => {
    const dateOrder = b.dateBidded.localeCompare(a.dateBidded);
    if (dateOrder !== 0) return dateOrder;
    return b.updatedAt.localeCompare(a.updatedAt);
  });
}

function _formatDate(value) {
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

function _statusClass(status) {
  return status.toLowerCase().replace(/[^a-z]+/g, '-');
}

function _setText(element, value) {
  element.textContent = value;
  return element;
}

function _element(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) _setText(element, text);
  return element;
}

async function _load() {
  _loading = true;
  _loadError = '';
  _render();

  try {
    const response = await fetch(PREF_URL, {
      method: 'GET',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error(`Unable to load housing bids (${response.status})`);

    const payload = await response.json();
    _state = _normalizeState(payload.value);
  } catch (error) {
    console.error('Failed to load housing bids:', error);
    _loadError = 'Housing bids could not be loaded. Your existing data has not been changed.';
  } finally {
    _loading = false;
    _render();
  }
}

async function _save(nextState) {
  const response = await fetch(PREF_URL, {
    method: 'PUT',
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ value: nextState }),
  });
  if (!response.ok) throw new Error(`Unable to save housing bids (${response.status})`);

  const payload = await response.json();
  return _normalizeState(payload.value);
}

function _modal() {
  return document.getElementById('housing-bids-modal');
}

function _body() {
  return document.getElementById('housing-bids-body');
}

function _setSidebarActive(active) {
  const button = document.getElementById('tool-housing-bids-btn');
  if (button) button.classList.toggle('active', active);
}

function _createModal() {
  const modal = document.createElement('div');
  modal.id = 'housing-bids-modal';
  modal.className = 'modal housing-bids-modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-labelledby', 'housing-bids-title');
  modal.innerHTML = `
    <div class="modal-content housing-bids-modal-content">
      <div class="modal-header housing-bids-header">
        <div>
          <span class="housing-bids-kicker">Private tracker</span>
          <h4 id="housing-bids-title">Housing Bids <span id="housing-bids-count"></span></h4>
        </div>
        <button type="button" class="modal-close housing-bids-close" id="housing-bids-close" aria-label="Close Housing Bids">&times;</button>
      </div>
      <div class="housing-bids-toolbar">
        <p>Saved to your authenticated Vanta preferences.</p>
        <button type="button" class="housing-bids-primary-btn" id="housing-bids-add-btn">Add Bid</button>
      </div>
      <div class="housing-bids-body" id="housing-bids-body"></div>
    </div>
  `;
  document.body.appendChild(modal);

  const content = modal.querySelector('.housing-bids-modal-content');
  const header = modal.querySelector('.housing-bids-header');
  makeWindowDraggable(modal, {
    content,
    header,
    enableResize: false,
    enableDock: false,
  });

  modal.querySelector('#housing-bids-close').addEventListener('click', close);
  modal.querySelector('#housing-bids-add-btn').addEventListener('click', () => _openForm());
  modal.addEventListener('click', (event) => {
    if (event.target === modal) close();
  });

  return modal;
}

function _render() {
  const body = _body();
  if (!body) return;

  const count = document.getElementById('housing-bids-count');
  if (count) count.textContent = _state.entries.length ? `(${_state.entries.length})` : '';

  const addButton = document.getElementById('housing-bids-add-btn');
  if (addButton) {
    addButton.hidden = _showForm;
    addButton.disabled = _saving;
  }

  body.replaceChildren();

  if (_loading) {
    const loading = _element('div', 'housing-bids-state');
    loading.append(
      _element('span', 'housing-bids-state-mark', 'SYNC'),
      _element('h3', '', 'Loading housing bids'),
      _element('p', '', 'Reading your private tracker.'),
    );
    body.appendChild(loading);
    return;
  }

  if (_loadError) {
    const errorState = _element('div', 'housing-bids-state');
    errorState.append(
      _element('span', 'housing-bids-state-mark', 'OFFLINE'),
      _element('h3', '', 'Tracker unavailable'),
      _element('p', '', _loadError),
    );
    const retry = _element('button', 'housing-bids-primary-btn', 'Retry');
    retry.type = 'button';
    retry.addEventListener('click', _load);
    errorState.appendChild(retry);
    body.appendChild(errorState);
    return;
  }

  if (_showForm) {
    _renderForm();
    return;
  }

  if (!_state.entries.length) {
    const empty = _element('div', 'housing-bids-state housing-bids-empty');
    empty.append(
      _element('span', 'housing-bids-state-mark', 'READY'),
      _element('h3', '', 'No housing bids recorded'),
      _element('p', '', 'Add your first property or area to begin a private manual bid history.'),
    );
    const addFirst = _element('button', 'housing-bids-primary-btn', 'Add First Bid');
    addFirst.type = 'button';
    addFirst.addEventListener('click', () => _openForm());
    empty.appendChild(addFirst);
    body.appendChild(empty);
    return;
  }

  const list = _element('div', 'housing-bids-list');
  _sortEntries(_state.entries).forEach((entry) => list.appendChild(_renderEntry(entry)));
  body.appendChild(list);
}

function _renderEntry(entry) {
  const card = _element('article', 'housing-bid-card');

  const heading = _element('div', 'housing-bid-heading');
  const titleGroup = _element('div', 'housing-bid-title-group');
  titleGroup.append(
    _element('span', 'housing-bid-date', `Bidded ${_formatDate(entry.dateBidded)}`),
    _element('h3', '', entry.propertyArea),
  );
  const status = _element('span', `housing-bid-status status-${_statusClass(entry.status)}`, entry.status);
  heading.append(titleGroup, status);
  card.appendChild(heading);

  if (entry.description) card.appendChild(_element('p', 'housing-bid-description', entry.description));

  const details = _element('dl', 'housing-bid-details');
  if (entry.priorityBand) _appendDetail(details, 'Priority / band', entry.priorityBand);
  if (entry.notes) _appendDetail(details, 'Notes', entry.notes);
  if (entry.outcome) _appendDetail(details, 'Outcome', entry.outcome);
  if (details.children.length) card.appendChild(details);

  const actions = _element('div', 'housing-bid-actions');
  const edit = _element('button', 'housing-bids-secondary-btn', 'Edit');
  edit.type = 'button';
  edit.addEventListener('click', () => _openForm(entry.id));
  const remove = _element('button', 'housing-bids-danger-btn', 'Delete');
  remove.type = 'button';
  remove.addEventListener('click', () => _deleteEntry(entry));
  actions.append(edit, remove);
  card.appendChild(actions);

  return card;
}

function _appendDetail(list, label, value) {
  const wrapper = _element('div', 'housing-bid-detail');
  wrapper.append(_element('dt', '', label), _element('dd', '', value));
  list.appendChild(wrapper);
}

function _openForm(id = null) {
  _editingId = id;
  _showForm = true;
  _render();
}

function _renderForm() {
  const body = _body();
  if (!body) return;

  const existing = _editingId ? _state.entries.find((entry) => entry.id === _editingId) : null;
  const form = document.createElement('form');
  form.className = 'housing-bid-form';
  form.noValidate = true;
  form.innerHTML = `
    <div class="housing-bid-form-heading">
      <div>
        <span class="housing-bids-kicker">${existing ? 'Update record' : 'New record'}</span>
        <h3>${existing ? 'Edit Housing Bid' : 'Add Housing Bid'}</h3>
      </div>
      <p>Required fields are marked with an asterisk.</p>
    </div>
    <div class="housing-bid-form-grid">
      <label class="housing-bid-field housing-bid-field-wide">
        <span>Property / area *</span>
        <input id="housing-bid-property" name="propertyArea" type="text" maxlength="160" required autocomplete="off">
      </label>
      <label class="housing-bid-field">
        <span>Date bidded *</span>
        <input id="housing-bid-date" name="dateBidded" type="date" required>
      </label>
      <label class="housing-bid-field">
        <span>Status</span>
        <select id="housing-bid-status" name="status"></select>
      </label>
      <label class="housing-bid-field housing-bid-field-wide">
        <span>Short description</span>
        <textarea id="housing-bid-description" name="description" maxlength="300" rows="2"></textarea>
      </label>
      <label class="housing-bid-field housing-bid-field-wide">
        <span>Priority / band info</span>
        <input id="housing-bid-priority" name="priorityBand" type="text" maxlength="120" autocomplete="off">
      </label>
      <label class="housing-bid-field housing-bid-field-wide">
        <span>Notes</span>
        <textarea id="housing-bid-notes" name="notes" maxlength="2000" rows="4"></textarea>
      </label>
      <label class="housing-bid-field housing-bid-field-wide">
        <span>Outcome</span>
        <textarea id="housing-bid-outcome" name="outcome" maxlength="500" rows="2"></textarea>
      </label>
    </div>
    <div class="housing-bid-form-error" id="housing-bid-form-error" role="alert"></div>
    <div class="housing-bid-form-actions">
      <button type="button" class="housing-bids-secondary-btn" id="housing-bid-cancel">Cancel</button>
      <button type="submit" class="housing-bids-primary-btn" id="housing-bid-save">${existing ? 'Save Changes' : 'Save Bid'}</button>
    </div>
  `;

  const statusSelect = form.querySelector('#housing-bid-status');
  STATUS_OPTIONS.forEach((option) => {
    const element = document.createElement('option');
    element.value = option;
    element.textContent = option;
    statusSelect.appendChild(element);
  });

  if (existing) {
    form.querySelector('#housing-bid-property').value = existing.propertyArea;
    form.querySelector('#housing-bid-date').value = existing.dateBidded;
    statusSelect.value = existing.status;
    form.querySelector('#housing-bid-description').value = existing.description;
    form.querySelector('#housing-bid-priority').value = existing.priorityBand;
    form.querySelector('#housing-bid-notes').value = existing.notes;
    form.querySelector('#housing-bid-outcome').value = existing.outcome;
  } else {
    statusSelect.value = 'Pending';
  }

  form.querySelector('#housing-bid-cancel').addEventListener('click', () => {
    _editingId = null;
    _showForm = false;
    _render();
  });
  form.addEventListener('submit', _submitForm);
  body.appendChild(form);
  requestAnimationFrame(() => form.querySelector('#housing-bid-property').focus());
}

function _formValue(form, selector, maxLength) {
  return _string(form.querySelector(selector).value, maxLength);
}

function _isValidDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function _setFormError(form, message, field) {
  const error = form.querySelector('#housing-bid-form-error');
  error.textContent = message;
  if (field) field.focus();
}

async function _submitForm(event) {
  event.preventDefault();
  if (_saving) return;

  const form = event.currentTarget;
  const propertyArea = _formValue(form, '#housing-bid-property', 160);
  const dateBidded = _formValue(form, '#housing-bid-date', 10);
  const propertyField = form.querySelector('#housing-bid-property');
  const dateField = form.querySelector('#housing-bid-date');

  if (!propertyArea) {
    _setFormError(form, 'Property / area is required.', propertyField);
    return;
  }
  if (!_isValidDate(dateBidded)) {
    _setFormError(form, 'Enter a valid date bidded.', dateField);
    return;
  }

  const existing = _editingId ? _state.entries.find((entry) => entry.id === _editingId) : null;
  const now = new Date().toISOString();
  const entry = {
    id: existing ? existing.id : _createId(),
    propertyArea,
    dateBidded,
    description: _formValue(form, '#housing-bid-description', 300),
    status: STATUS_OPTIONS.includes(form.querySelector('#housing-bid-status').value)
      ? form.querySelector('#housing-bid-status').value
      : 'Pending',
    priorityBand: _formValue(form, '#housing-bid-priority', 120),
    notes: _formValue(form, '#housing-bid-notes', 2000),
    outcome: _formValue(form, '#housing-bid-outcome', 500),
    createdAt: existing ? existing.createdAt : now,
    updatedAt: now,
  };

  const entries = existing
    ? _state.entries.map((item) => (item.id === existing.id ? entry : item))
    : [..._state.entries, entry];
  const nextState = { version: 1, entries };

  _saving = true;
  const saveButton = form.querySelector('#housing-bid-save');
  saveButton.disabled = true;
  saveButton.textContent = 'Saving...';

  try {
    _state = await _save(nextState);
    _editingId = null;
    _showForm = false;
    window.dispatchEvent(new CustomEvent('vanta:housing-bids-updated'));
    uiModule.showToast(existing ? 'Housing bid updated.' : 'Housing bid added.', 'success');
  } catch (error) {
    console.error('Failed to save housing bid:', error);
    _setFormError(form, 'Could not save this bid. Please try again.', null);
    saveButton.disabled = false;
    saveButton.textContent = existing ? 'Save Changes' : 'Save Bid';
  } finally {
    _saving = false;
    if (!_showForm) _render();
  }
}

async function _deleteEntry(entry) {
  if (_saving) return;

  const confirmed = await uiModule.styledConfirm(
    `Delete the bid for "${entry.propertyArea}"? This cannot be undone.`,
    { confirmText: 'Delete Bid', danger: true },
  );
  if (!confirmed) return;

  _saving = true;
  const nextState = {
    version: 1,
    entries: _state.entries.filter((item) => item.id !== entry.id),
  };

  try {
    _state = await _save(nextState);
    window.dispatchEvent(new CustomEvent('vanta:housing-bids-updated'));
    uiModule.showToast('Housing bid deleted.', 'success');
  } catch (error) {
    console.error('Failed to delete housing bid:', error);
    uiModule.showToast('Could not delete this bid. Please try again.', 'error');
  } finally {
    _saving = false;
    _render();
  }
}

function open() {
  let modal = _modal();
  if (!modal) modal = _createModal();

  _isOpen = true;
  _setSidebarActive(true);
  modal.style.display = 'flex';
  requestAnimationFrame(() => modal.classList.add('show'));

  _escapeHandler = (event) => {
    if (event.key === 'Escape') close();
  };
  document.addEventListener('keydown', _escapeHandler);
  _load();
}

function close() {
  const modal = _modal();
  if (!modal) return;

  _isOpen = false;
  _setSidebarActive(false);
  _editingId = null;
  _showForm = false;
  modal.classList.remove('show');
  if (_escapeHandler) {
    document.removeEventListener('keydown', _escapeHandler);
    _escapeHandler = null;
  }
  window.setTimeout(() => {
    modal.remove();
  }, 180);
}

function isOpen() {
  return _isOpen;
}

const housingBidsModule = { open, close, isOpen };

export { open, close, isOpen };
export default housingBidsModule;
