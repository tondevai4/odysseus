from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_command_center_is_part_of_the_existing_welcome_screen():
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    welcome_start = index.index('<div id="welcome-screen">')
    welcome_end = index.index('<div id="chat-history"', welcome_start)
    welcome = index[welcome_start:welcome_end]

    assert 'id="command-center"' in welcome
    assert "Morning, Boss. What are we handling today?" in welcome
    for title in (
        "Today&rsquo;s Tasks",
        "Career / Labouring Mission",
        "Money",
        "Habits",
        "Housing Bids",
    ):
        assert title in welcome


def test_command_center_navigation_and_actions_are_frontend_only():
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    module = (ROOT / "static" / "js" / "commandCenter.js").read_text(encoding="utf-8")

    assert 'id="sidebar-command-center-btn"' in index
    assert 'id="rail-command-center"' in index
    assert "sidebar-command-center-btn" in app
    assert "rail-command-center" in app
    assert "notesModule.openPanel()" in app
    assert "fetch(" not in module
