import uiModule from './ui.js';
import { makeWindowDraggable } from './windowDrag.js';

const API = '/api/gym-log';
let entries = [];
let editingId = null;
let openState = false;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path = '', options = {}) {
  const response = await fetch(`${API}${path}`, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error || 'Gym Log request failed.');
  return data;
}

function modal() {
  return document.getElementById('gym-log-modal');
}

function createModal() {
  const shell = el('div', 'modal gym-log-modal');
  shell.id = 'gym-log-modal';
  shell.setAttribute('role', 'dialog');
  shell.setAttribute('aria-modal', 'true');
  shell.innerHTML = `
    <div class="modal-content gym-log-content">
      <div class="modal-header gym-log-header">
        <div><span class="gym-log-kicker">Private body proof</span><h4>Gym / Body</h4></div>
        <button type="button" class="modal-close gym-log-close" aria-label="Close Gym Log">&times;</button>
      </div>
      <div class="gym-log-toolbar">
        <p>Track the work. Keep the evidence.</p>
        <button type="button" class="gym-log-primary" id="gym-log-add">Add Workout</button>
      </div>
      <div class="gym-log-body" id="gym-log-body"></div>
    </div>`;
  document.body.appendChild(shell);
  makeWindowDraggable(shell, {
    content: shell.querySelector('.gym-log-content'),
    header: shell.querySelector('.gym-log-header'),
    enableResize: false,
    enableDock: false,
  });
  shell.querySelector('.gym-log-close').addEventListener('click', close);
  shell.querySelector('#gym-log-add').addEventListener('click', () => {
    editingId = '';
    render();
  });
  shell.addEventListener('click', (event) => {
    if (event.target === shell) close();
  });
  return shell;
}

function formatDate(value) {
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric',
  });
}

function workoutCard(entry) {
  const card = el('article', 'gym-log-card');
  const top = el('div', 'gym-log-card-top');
  const heading = el('div');
  heading.append(el('h3', '', entry.title), el('span', 'gym-log-date', formatDate(entry.date)));
  const edit = el('button', 'gym-log-secondary', 'Edit');
  edit.type = 'button';
  edit.addEventListener('click', () => {
    editingId = entry.id;
    render();
  });
  top.append(heading, edit);
  card.appendChild(top);

  const stats = el('div', 'gym-log-stats');
  [
    ['Duration', entry.duration],
    ['Sets', entry.total_sets],
    ['Reps', entry.total_reps],
    ['Active kcal', entry.active_calories],
  ].forEach(([label, value]) => {
    if (value === null || value === undefined || value === '') return;
    const stat = el('div', 'gym-log-stat');
    stat.append(el('span', '', label), el('strong', '', String(value)));
    stats.appendChild(stat);
  });
  card.appendChild(stats);

  if (entry.exercises?.length) {
    const exercises = el('div', 'gym-log-exercises');
    entry.exercises.slice(0, 5).forEach((exercise) => {
      const reps = exercise.sets.map((set) => `${set.weight} × ${set.reps}`).join(', ');
      exercises.append(el('p', '', `${exercise.name}${reps ? ` — ${reps}` : ''}`));
    });
    card.appendChild(exercises);
  }
  if (entry.win) card.append(el('p', 'gym-log-win', `Win: ${entry.win}`));
  if (entry.notes) card.append(el('p', 'gym-log-notes', entry.notes));
  return card;
}

function field(form, label, name, value = '', type = 'text', wide = false) {
  const wrap = el('label', `gym-log-field${wide ? ' wide' : ''}`);
  wrap.appendChild(el('span', '', label));
  const input = type === 'textarea' ? el('textarea') : el('input');
  input.name = name;
  if (type !== 'textarea') input.type = type;
  input.value = value ?? '';
  if (type === 'textarea') input.rows = 5;
  wrap.appendChild(input);
  form.appendChild(wrap);
  return input;
}

function renderForm() {
  const body = document.getElementById('gym-log-body');
  const existing = entries.find((row) => row.id === editingId);
  const form = el('form', 'gym-log-form');
  const dateInput = field(form, 'Date', 'date', existing?.date || new Date().toISOString().slice(0, 10), 'date');
  const titleInput = field(form, 'Workout title', 'title', existing?.title || 'Workout');
  field(form, 'Duration', 'duration', existing?.duration || '');
  field(form, 'Total sets', 'total_sets', existing?.total_sets ?? '', 'number');
  field(form, 'Total reps', 'total_reps', existing?.total_reps ?? '', 'number');
  field(form, 'Active calories', 'active_calories', existing?.active_calories ?? '', 'number');
  field(form, 'Average HR', 'avg_hr', existing?.avg_hr ?? '', 'number');
  field(form, 'Max HR', 'max_hr', existing?.max_hr ?? '', 'number');
  field(form, 'Primary benefit', 'primary_benefit', existing?.primary_benefit || '', 'text', true);
  field(form, 'Workout details / exercises', 'raw_log', existing?.raw_log || '', 'textarea', true);
  field(form, 'Notes', 'notes', existing?.notes || '', 'textarea', true);
  field(form, 'Today’s win', 'win', existing?.win || '', 'textarea', true);
  const error = el('p', 'gym-log-error');
  const actions = el('div', 'gym-log-form-actions');
  const cancel = el('button', 'gym-log-secondary', 'Cancel');
  cancel.type = 'button';
  cancel.addEventListener('click', () => {
    editingId = null;
    render();
  });
  const save = el('button', 'gym-log-primary', existing ? 'Save Workout' : 'Log Workout');
  save.type = 'submit';
  actions.append(cancel, save);
  form.append(error, actions);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    error.textContent = '';
    if (!dateInput.value || !titleInput.value.trim()) {
      error.textContent = 'Date and workout title are required.';
      return;
    }
    save.disabled = true;
    const values = Object.fromEntries(new FormData(form).entries());
    ['total_sets', 'total_reps', 'active_calories', 'avg_hr', 'max_hr'].forEach((name) => {
      values[name] = values[name] === '' ? null : Number(values[name]);
    });
    try {
      if (existing) {
        await api(`/${encodeURIComponent(existing.id)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(values),
        });
      } else {
        await api('', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(values),
        });
      }
      editingId = null;
      await load();
      uiModule.showToast(existing ? 'Workout updated.' : 'Workout logged.', 'success');
      window.dispatchEvent(new CustomEvent('vanta:gym-log-updated'));
    } catch (caught) {
      error.textContent = caught.message;
      save.disabled = false;
    }
  });
  body.replaceChildren(form);
}

function render() {
  const body = document.getElementById('gym-log-body');
  if (!body) return;
  if (editingId !== null) {
    renderForm();
    return;
  }
  body.replaceChildren();
  if (!entries.length) {
    const empty = el('div', 'gym-log-empty');
    empty.append(el('span', 'gym-log-kicker', 'PROOF READY'), el('h3', '', 'No gym log yet'), el('p', '', 'Log today’s proof.'));
    body.appendChild(empty);
    return;
  }
  const grid = el('div', 'gym-log-grid');
  entries.forEach((entry) => grid.appendChild(workoutCard(entry)));
  body.appendChild(grid);
}

async function load() {
  const body = document.getElementById('gym-log-body');
  body?.replaceChildren(el('div', 'gym-log-empty', 'Loading gym log...'));
  try {
    const data = await api();
    entries = Array.isArray(data.entries) ? data.entries : [];
    render();
  } catch (error) {
    body?.replaceChildren(el('div', 'gym-log-empty gym-log-error', error.message));
  }
}

async function open() {
  const shell = modal() || createModal();
  shell.style.display = 'flex';
  openState = true;
  document.getElementById('tool-gym-log-btn')?.classList.add('active');
  editingId = null;
  await load();
}

function close() {
  const shell = modal();
  if (shell) shell.style.display = 'none';
  openState = false;
  editingId = null;
  document.getElementById('tool-gym-log-btn')?.classList.remove('active');
}

const gymLogModule = { open, close, isOpen: () => openState };
export default gymLogModule;
