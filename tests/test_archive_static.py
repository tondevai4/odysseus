from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_archive_ui_and_isolation_wiring():
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    command = (ROOT / "static" / "js" / "commandCenter.js").read_text(encoding="utf-8")
    panel = (ROOT / "static" / "js" / "archive.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

    assert 'id="tool-investigation-archive-btn"' in index
    assert 'data-command-center-action="archive"' in index
    assert "import archiveModule from './js/archive.js';" in app
    assert "openArchive: () => archiveModule.open()" in app
    assert "'/archive-room'" in app
    assert "action.dataset.commandCenterAction === 'archive'" in command
    assert "No Vanta Brain. No personal context." in panel
    assert "'/chat'" in panel
    assert "'/dossiers'" in panel
    assert "archive-dossiers-v1" not in panel
    assert "@media (max-width: 700px)" in css
    assert ".archive-content" in css

