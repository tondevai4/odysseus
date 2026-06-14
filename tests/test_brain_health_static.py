from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_command_center_system_ready_opens_brain_health():
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    command_center = (ROOT / "static" / "js" / "commandCenter.js").read_text(encoding="utf-8")
    brain_health = (ROOT / "static" / "js" / "brainHealth.js").read_text(encoding="utf-8")

    assert 'data-command-center-action="brain-health"' in index
    assert "brainHealthModule.open()" in app
    assert "openBrainHealth" in command_center
    assert "fetch('/api/brain/health'" in brain_health
    assert "fetch('/api/brain/preview'" in brain_health
    assert "Stored schema recognised" in brain_health
    assert "textContent" in brain_health
    assert "index-rebuild" not in brain_health


def test_chat_handles_unified_brain_sources():
    chat = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    renderer = (ROOT / "static" / "js" / "chatRenderer.js").read_text(encoding="utf-8")

    assert "json.type === 'brain_sources'" in chat
    assert "holder._brainSources" in chat
    assert "Vanta Brain (" in chat
    assert "buildBrainSourcesBox" in renderer
    assert "metadata?.brain_sources?.length" in renderer
