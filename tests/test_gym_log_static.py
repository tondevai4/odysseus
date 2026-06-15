from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_gym_panel_and_command_center_wiring():
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    command = (ROOT / "static" / "js" / "commandCenter.js").read_text(encoding="utf-8")
    panel = (ROOT / "static" / "js" / "gymLog.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

    assert 'id="tool-gym-log-btn"' in index
    assert 'id="command-gym-body"' in index
    assert 'data-command-center-action="gym-log"' in index
    assert "import gymLogModule from './js/gymLog.js';" in app
    assert "openGymLog: () => gymLogModule.open()" in app
    assert "'/api/gym-log/latest'" in command
    assert "No gym log yet. Log today’s proof." in command
    assert "textContent" in panel
    assert "innerHTML" in panel  # fixed application-owned modal shell only
    assert "Start Workout" in panel
    assert "Add Set" in panel
    assert "Delete Last Set" in panel
    assert "Finish Workout" in panel
    assert "Reset 90s" in panel
    assert "Garmin stats" in panel
    assert "window.prompt" not in panel
    assert "Start Logging" in panel
    assert "'/session/start'" in panel
    assert "'/session/set'" in panel
    assert "'/session/finish'" in panel
    assert "entry.active_calories" in command
    assert "entry.primary_benefit" in command
    assert "@media (max-width: 640px)" in css
    assert ".gym-log-content" in css
    assert ".gym-live-stepper-controls" in css
    assert ".gym-rest-timer" in css
