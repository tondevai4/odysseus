let _initialized = false;

function init({ openNotes } = {}) {
  if (_initialized) return;

  const commandCenter = document.getElementById('command-center');
  if (!commandCenter) return;

  commandCenter.addEventListener('click', (event) => {
    const action = event.target.closest('[data-command-center-action]');
    if (!action || !commandCenter.contains(action)) return;

    if (action.dataset.commandCenterAction === 'notes' && typeof openNotes === 'function') {
      openNotes();
    }
  });

  _initialized = true;
}

const commandCenterModule = { init };

export { init };
export default commandCenterModule;
