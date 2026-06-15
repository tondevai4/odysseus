import uiModule from './ui.js';
import { makeWindowDraggable } from './windowDrag.js';

const API = '/api/gym-log';
const GARMIN_FIELDS = [
  ['total_time', 'Total time', 'text'],
  ['work_time', 'Work time', 'text'],
  ['rest_time', 'Rest time', 'text'],
  ['avg_hr', 'Average HR', 'number'],
  ['max_hr', 'Max HR', 'number'],
  ['primary_benefit', 'Primary benefit', 'text'],
  ['resting_calories', 'Resting calories', 'number'],
  ['active_calories', 'Active calories', 'number'],
  ['total_calories', 'Total calories', 'number'],
  ['estimated_sweat_loss_ml', 'Sweat loss (ml)', 'number'],
  ['total_reps', 'Total reps', 'number'],
  ['total_sets', 'Total sets', 'number'],
  ['avg_time_per_set', 'Average time / set', 'text'],
  ['total_volume', 'Total volume', 'number'],
  ['intensity_minutes_moderate', 'Moderate minutes', 'number'],
  ['intensity_minutes_vigorous', 'Vigorous minutes', 'number'],
  ['intensity_minutes_total', 'Total intensity minutes', 'number'],
  ['body_battery_net_impact', 'Body Battery impact', 'number'],
  ['muscle_primary', 'Primary muscles', 'text'],
  ['muscle_secondary', 'Secondary muscles', 'text'],
  ['muscle_untargeted', 'Untargeted muscles', 'text'],
];

let entries = [];
let activeSession = null;
let editingId = null;
let editingSet = null;
let screen = 'history';
let openState = false;
let restRemaining = 0;
let restTimer = null;

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

function jsonOptions(method, body) {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
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
        <p>Fast sets now. Garmin detail after.</p>
        <div class="gym-log-toolbar-actions">
          <button type="button" class="gym-log-secondary" id="gym-log-add">Manual Log</button>
          <button type="button" class="gym-log-primary" id="gym-log-start">Start Workout</button>
        </div>
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
    screen = 'form';
    render();
  });
  shell.querySelector('#gym-log-start').addEventListener('click', () => {
    screen = 'start';
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

function metric(stats, label, value) {
  if (value === null || value === undefined || value === '') return;
  const stat = el('div', 'gym-log-stat');
  stat.append(el('span', '', label), el('strong', '', String(value)));
  stats.appendChild(stat);
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
    screen = 'form';
    render();
  });
  top.append(heading, edit);
  card.appendChild(top);

  const stats = el('div', 'gym-log-stats');
  metric(stats, 'Duration', entry.duration || entry.total_time);
  metric(stats, 'Sets', entry.total_sets);
  metric(stats, 'Reps', entry.total_reps);
  metric(stats, 'Active kcal', entry.active_calories);
  metric(stats, 'Average HR', entry.avg_hr);
  metric(stats, 'Max HR', entry.max_hr);
  card.appendChild(stats);

  if (entry.primary_benefit) card.append(el('p', 'gym-log-benefit', entry.primary_benefit));
  if (entry.exercises?.length) {
    const exercises = el('div', 'gym-log-exercises');
    entry.exercises.slice(0, 5).forEach((exercise) => {
      const reps = exercise.sets.map((set) => `${set.weight} x ${set.reps}`).join(', ');
      exercises.append(el('p', '', `${exercise.name}${reps ? ` - ${reps}` : ''}`));
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

function addGarminFields(form, existing = {}) {
  const details = el('details', 'gym-log-garmin wide');
  const summary = el('summary', '', 'Garmin stats');
  const grid = el('div', 'gym-log-garmin-grid');
  GARMIN_FIELDS.forEach(([name, label, type]) => {
    field(grid, label, name, existing[name] ?? '', type);
  });
  field(grid, 'Paste Garmin summary', 'raw_garmin_text', existing.raw_garmin_text || '', 'textarea', true);
  details.append(summary, grid);
  form.appendChild(details);
}

function numericValues(values) {
  GARMIN_FIELDS.filter(([, , type]) => type === 'number').forEach(([name]) => {
    values[name] = values[name] === '' ? null : Number(values[name]);
  });
  return values;
}

function renderForm() {
  const body = document.getElementById('gym-log-body');
  const existing = entries.find((row) => row.id === editingId);
  const form = el('form', 'gym-log-form');
  const dateInput = field(form, 'Date', 'date', existing?.date || new Date().toISOString().slice(0, 10), 'date');
  const titleInput = field(form, 'Workout title', 'title', existing?.title || 'Workout');
  field(form, 'Workout details / exercises', 'raw_log', existing?.raw_log || '', 'textarea', true);
  field(form, 'Notes', 'notes', existing?.notes || '', 'textarea', true);
  field(form, "Today's win", 'win', existing?.win || '', 'textarea', true);
  addGarminFields(form, existing);
  const error = el('p', 'gym-log-error');
  const actions = el('div', 'gym-log-form-actions');
  const cancel = el('button', 'gym-log-secondary', 'Cancel');
  cancel.type = 'button';
  cancel.addEventListener('click', () => {
    editingId = null;
    screen = 'history';
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
    const values = numericValues(Object.fromEntries(new FormData(form).entries()));
    try {
      if (existing) {
        await api(`/${encodeURIComponent(existing.id)}`, jsonOptions('PUT', values));
      } else {
        await api('', jsonOptions('POST', values));
      }
      editingId = null;
      screen = 'history';
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

function stepper(label, value, step, minimum = 0) {
  const wrap = el('div', 'gym-live-stepper');
  wrap.appendChild(el('span', 'gym-live-stepper-label', label));
  const controls = el('div', 'gym-live-stepper-controls');
  const minus = el('button', 'gym-log-secondary', '-');
  const input = el('input');
  const plus = el('button', 'gym-log-secondary', '+');
  input.type = 'number';
  input.min = String(minimum);
  input.step = String(step);
  input.value = String(value);
  minus.type = plus.type = 'button';
  minus.addEventListener('click', () => {
    input.value = String(Math.max(minimum, Number(input.value || 0) - step));
  });
  plus.addEventListener('click', () => {
    input.value = String(Number(input.value || 0) + step);
  });
  controls.append(minus, input, plus);
  wrap.appendChild(controls);
  return { wrap, input };
}

function sessionSets() {
  return (activeSession?.exercises || []).flatMap((exercise) => (
    exercise.sets.map((set, index) => ({ exercise: exercise.name, index, ...set }))
  ));
}

function previousSet() {
  const rows = sessionSets();
  return rows.length ? rows[rows.length - 1] : null;
}

function startRestTimer(seconds = 90) {
  clearInterval(restTimer);
  restRemaining = seconds;
  const tick = () => {
    const node = document.getElementById('gym-rest-time');
    if (node) {
      const minutes = Math.floor(restRemaining / 60);
      node.textContent = `${minutes}:${String(restRemaining % 60).padStart(2, '0')}`;
    }
    if (restRemaining <= 0) {
      clearInterval(restTimer);
      restTimer = null;
      return;
    }
    restRemaining -= 1;
  };
  tick();
  restTimer = setInterval(tick, 1000);
}

function renderRestTimer(parent) {
  const timer = el('div', 'gym-rest-timer');
  timer.append(el('span', '', 'REST'), el('strong', '', '0:00'));
  timer.querySelector('strong').id = 'gym-rest-time';
  const reset = el('button', 'gym-log-secondary', 'Reset 90s');
  const skip = el('button', 'gym-log-secondary', 'Skip');
  reset.type = skip.type = 'button';
  reset.addEventListener('click', () => startRestTimer());
  skip.addEventListener('click', () => {
    clearInterval(restTimer);
    restTimer = null;
    restRemaining = 0;
    timer.querySelector('strong').textContent = '0:00';
  });
  timer.append(reset, skip);
  parent.appendChild(timer);
  if (restRemaining > 0) startRestTimer(restRemaining);
}

function renderLiveSession() {
  const body = document.getElementById('gym-log-body');
  const panel = el('section', 'gym-live-session');
  const heading = el('div', 'gym-live-heading');
  heading.append(
    el('span', 'gym-log-kicker', 'LIVE SESSION'),
    el('h3', '', activeSession.title),
    el('p', 'gym-log-date', formatDate(activeSession.date)),
  );
  panel.appendChild(heading);
  renderRestTimer(panel);

  const latest = previousSet();
  const exerciseField = field(panel, 'Current exercise', 'exercise', latest?.exercise || '');
  const parsedWeight = Number.parseFloat(latest?.weight || '0') || 0;
  const weight = stepper('Weight (kg)', parsedWeight, 2.5);
  const reps = stepper('Reps', latest?.reps || 10, 1, 1);
  const steppers = el('div', 'gym-live-steppers');
  steppers.append(weight.wrap, reps.wrap);
  panel.appendChild(steppers);

  const add = el('button', 'gym-log-primary gym-live-add', 'Add Set');
  add.type = 'button';
  const error = el('p', 'gym-log-error');
  add.addEventListener('click', async () => {
    error.textContent = '';
    if (!exerciseField.value.trim()) {
      error.textContent = 'Exercise name is required.';
      return;
    }
    add.disabled = true;
    try {
      activeSession = await api('/session/set', jsonOptions('POST', {
        exercise: exerciseField.value.trim(),
        weight: `${weight.input.value}kg`,
        reps: Number(reps.input.value),
      }));
      startRestTimer();
      render();
    } catch (caught) {
      error.textContent = caught.message;
      add.disabled = false;
    }
  });
  panel.append(add, error);

  const list = el('div', 'gym-live-set-list');
  (activeSession.exercises || []).forEach((exercise) => {
    const group = el('section', 'gym-live-exercise');
    group.appendChild(el('h4', '', exercise.name));
    exercise.sets.forEach((set, index) => {
      const row = el('div', 'gym-live-set-row');
      const isEditing = (
        editingSet?.exercise === exercise.name && editingSet?.setIndex === index
      );
      if (isEditing) {
        const weightInput = el('input', 'gym-live-inline-input');
        const repsInput = el('input', 'gym-live-inline-input');
        weightInput.value = set.weight;
        repsInput.type = 'number';
        repsInput.min = '1';
        repsInput.value = String(set.reps);
        const saveEdit = el('button', 'gym-live-edit-set', 'Save');
        saveEdit.type = 'button';
        saveEdit.addEventListener('click', async () => {
          try {
            activeSession = await api('/session/set', jsonOptions('PUT', {
              exercise: exercise.name,
              set_index: index,
              weight: weightInput.value,
              reps: Number(repsInput.value),
            }));
            editingSet = null;
            render();
          } catch (error) {
            uiModule.showToast(error.message, 'error');
          }
        });
        row.append(el('span', '', `Set ${index + 1}`), weightInput, repsInput, saveEdit);
      } else {
        const edit = el('button', 'gym-live-edit-set', 'Edit');
        edit.type = 'button';
        edit.addEventListener('click', () => {
          editingSet = { exercise: exercise.name, setIndex: index };
          render();
        });
        row.append(
          el('span', '', `Set ${index + 1}`),
          el('strong', '', `${set.weight} x ${set.reps}`),
          edit,
        );
      }
      group.appendChild(row);
    });
    list.appendChild(group);
  });
  if (!list.childElementCount) list.append(el('p', 'gym-log-notes', 'Your sets will appear here.'));
  panel.appendChild(list);

  const actions = el('div', 'gym-live-actions');
  const remove = el('button', 'gym-log-secondary', 'Delete Last Set');
  const next = el('button', 'gym-log-secondary', 'Next Exercise');
  const finish = el('button', 'gym-log-primary', 'Finish Workout');
  remove.type = next.type = finish.type = 'button';
  remove.disabled = !sessionSets().length;
  remove.addEventListener('click', async () => {
    try {
      activeSession = await api('/session/set/last', { method: 'DELETE' });
      render();
    } catch (error) {
      uiModule.showToast(error.message, 'error');
    }
  });
  next.addEventListener('click', () => {
    exerciseField.value = '';
    exerciseField.focus();
  });
  finish.addEventListener('click', () => {
    screen = 'finish';
    render();
  });
  actions.append(remove, next, finish);
  panel.appendChild(actions);
  body.replaceChildren(panel);
}

function renderFinishSummary() {
  const body = document.getElementById('gym-log-body');
  const form = el('form', 'gym-log-form gym-finish-form');
  form.append(el('span', 'gym-log-kicker wide', 'REVIEW BEFORE SAVE'));
  const stats = el('div', 'gym-log-stats wide');
  const allSets = sessionSets();
  metric(stats, 'Workout', activeSession.title);
  metric(stats, 'Exercises', activeSession.exercises.length);
  metric(stats, 'Sets', allSets.length);
  metric(stats, 'Reps', allSets.reduce((sum, set) => sum + Number(set.reps || 0), 0));
  form.appendChild(stats);
  field(form, 'Duration', 'duration', '');
  field(form, 'Notes', 'notes', activeSession.notes || '', 'textarea', true);
  field(form, "Today's win", 'win', activeSession.win || '', 'textarea', true);
  addGarminFields(form);
  const error = el('p', 'gym-log-error');
  const actions = el('div', 'gym-log-form-actions');
  const back = el('button', 'gym-log-secondary', 'Back to Sets');
  const save = el('button', 'gym-log-primary', 'Save Workout');
  back.type = 'button';
  save.type = 'submit';
  back.addEventListener('click', () => {
    screen = 'live';
    render();
  });
  actions.append(back, save);
  form.append(error, actions);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    save.disabled = true;
    try {
      const values = numericValues(Object.fromEntries(new FormData(form).entries()));
      await api('/session/finish', jsonOptions('POST', values));
      activeSession = null;
      screen = 'history';
      clearInterval(restTimer);
      restTimer = null;
      await load();
      uiModule.showToast('Workout saved.', 'success');
      window.dispatchEvent(new CustomEvent('vanta:gym-log-updated'));
    } catch (caught) {
      error.textContent = caught.message;
      save.disabled = false;
    }
  });
  body.replaceChildren(form);
}

function renderStartForm() {
  const body = document.getElementById('gym-log-body');
  const form = el('form', 'gym-log-form gym-live-start-form');
  form.append(el('span', 'gym-log-kicker wide', 'START SESSION'));
  const title = field(form, 'Workout title', 'title', 'Full-body workout', 'text', true);
  const error = el('p', 'gym-log-error');
  const actions = el('div', 'gym-log-form-actions');
  const cancel = el('button', 'gym-log-secondary', 'Cancel');
  const start = el('button', 'gym-log-primary', 'Start Logging');
  cancel.type = 'button';
  start.type = 'submit';
  cancel.addEventListener('click', () => {
    screen = 'history';
    render();
  });
  actions.append(cancel, start);
  form.append(error, actions);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!title.value.trim()) {
      error.textContent = 'Workout title is required.';
      return;
    }
    start.disabled = true;
    await startWorkout(title.value.trim(), error);
    start.disabled = false;
  });
  body.replaceChildren(form);
  title.focus();
}

async function startWorkout(title, errorNode) {
  try {
    activeSession = await api('/session/start', jsonOptions('POST', {
      title: title || 'Workout',
    }));
    screen = 'live';
    render();
  } catch (error) {
    if (errorNode) errorNode.textContent = error.message;
    else uiModule.showToast(error.message, 'error');
  }
}

function renderHistory() {
  const body = document.getElementById('gym-log-body');
  body.replaceChildren();
  if (activeSession) {
    const resume = el('button', 'gym-live-resume', `Resume ${activeSession.title}`);
    resume.type = 'button';
    resume.addEventListener('click', () => {
      screen = 'live';
      render();
    });
    body.appendChild(resume);
  }
  if (!entries.length) {
    const empty = el('div', 'gym-log-empty');
    empty.append(
      el('span', 'gym-log-kicker', 'PROOF READY'),
      el('h3', '', 'No gym log yet'),
      el('p', '', "Log today's proof."),
    );
    body.appendChild(empty);
    return;
  }
  const grid = el('div', 'gym-log-grid');
  entries.forEach((entry) => grid.appendChild(workoutCard(entry)));
  body.appendChild(grid);
}

function render() {
  const body = document.getElementById('gym-log-body');
  if (!body) return;
  if (screen === 'form') renderForm();
  else if (screen === 'start') renderStartForm();
  else if (screen === 'live' && activeSession) renderLiveSession();
  else if (screen === 'finish' && activeSession) renderFinishSummary();
  else renderHistory();
}

async function load() {
  const body = document.getElementById('gym-log-body');
  body?.replaceChildren(el('div', 'gym-log-empty', 'Loading gym log...'));
  try {
    const data = await api();
    entries = Array.isArray(data.entries) ? data.entries : [];
    activeSession = data.active_session || null;
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
  editingSet = null;
  screen = activeSession ? 'live' : 'history';
  await load();
  if (activeSession) screen = 'live';
  render();
}

function close() {
  const shell = modal();
  if (shell) shell.style.display = 'none';
  openState = false;
  editingId = null;
  editingSet = null;
  screen = 'history';
  clearInterval(restTimer);
  restTimer = null;
  document.getElementById('tool-gym-log-btn')?.classList.remove('active');
}

const gymLogModule = { open, close, isOpen: () => openState };
export default gymLogModule;
