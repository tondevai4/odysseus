from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_command_center_is_part_of_the_existing_welcome_screen():
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    welcome_start = index.index('<div id="welcome-screen">')
    welcome_end = index.index('<div id="chat-history"', welcome_start)
    welcome = index[welcome_start:welcome_end]

    assert 'id="command-center"' in welcome
    assert "data-brand-greeting" in welcome
    assert "data-brand-home-tagline" in welcome
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
    assert "fetch('/api/reading-list/current'" in module


def test_command_center_exposes_four_chat_routines():
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    module = (ROOT / "static" / "js" / "commandCenter.js").read_text(encoding="utf-8")

    assert index.count('data-command-center-action="routine"') == 4
    for prompt in (
        "Start my Morning Command Brief.",
        "Start my Night Shutdown Review.",
        "I'm overwhelmed. Start Panic / Brain Shutdown Mode.",
        "Start Urge Reset Mode.",
    ):
        assert prompt in index
    assert "chatForm.requestSubmit()" in app
    assert "routinePrompt" in module


def test_command_center_uses_compact_routine_labels():
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

    for label in ("Morning Brief", "Shutdown Review", "Brain Shutdown", "Urge Reset"):
        assert f"<span>{label}</span>" in index
    assert "border-radius: 999px" in styles
