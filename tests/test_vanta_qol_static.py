from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_home_branding_is_time_aware_and_randomised():
    branding = (ROOT / "static" / "branding.js").read_text(encoding="utf-8")

    assert "hour >= 5 && hour < 12" in branding
    assert "hour >= 12 && hour < 17" in branding
    assert "hour >= 17 && hour < 22" in branding
    assert "Night, Boss." in branding
    assert "Math.random()" in branding
    assert "No speeches. Evidence." in branding


def test_chat_timestamps_include_local_date_and_time():
    renderer = (ROOT / "static" / "js" / "chatRenderer.js").read_text(encoding="utf-8")
    chat = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")

    assert "formatMessageTimestamp" in renderer
    assert "day: 'numeric'" in renderer
    assert "month: 'short'" in renderer
    assert "year: 'numeric'" in renderer
    assert "hour12: true" in renderer
    assert "toLocaleTimeString([], {hour: '2-digit'" not in chat


def test_chat_note_rules_are_explicit_and_incognito_stays_blocked():
    agent = (ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8")
    routes = (ROOT / "routes" / "chat_routes.py").read_text(encoding="utf-8")
    execution = (ROOT / "src" / "tool_execution.py").read_text(encoding="utf-8")

    assert "action=append with its exact title" in agent
    assert "Done, Boss. Saved to Notes." in agent
    assert '"manage_notes",       # private notes' in routes
    assert "Notes cannot be deleted from chat." in execution
    assert "Chat will not overwrite, replace, rename, or archive note content." in execution
