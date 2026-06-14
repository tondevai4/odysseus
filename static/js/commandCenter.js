let _initialized = false;

function init({ openNotes, openHousingBids, openBrainHealth, runRoutine } = {}) {
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

  _initialized = true;
}

const commandCenterModule = { init };

export { init };
export default commandCenterModule;
