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
    assert "@media (max-width: 640px)" in css
    assert ".gym-log-content" in css
