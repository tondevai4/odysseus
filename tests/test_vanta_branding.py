import json
from pathlib import Path

from src.preset_manager import PresetManager


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_uses_vanta_brand():
    manifest = json.loads((ROOT / "static" / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "Vanta"
    assert manifest["short_name"] == "Vanta"
    assert "better you every day" in manifest["description"].lower()


def test_brand_config_contains_core_copy():
    branding = (ROOT / "static" / "branding.js").read_text(encoding="utf-8")

    assert "name: 'Vanta'" in branding
    assert "wordmark: 'VANTA'" in branding
    assert "A better you every day" in branding
    assert "Morning, Boss. What are we handling today?" in branding
    assert "currentMeta.textContent = `${brand.name} Chat`" in branding


def test_vanta_theme_and_persona_are_built_in():
    theme = (ROOT / "static" / "js" / "theme.js").read_text(encoding="utf-8")
    persona = PresetManager.DEFAULT_PRESETS["vanta"]

    assert "vanta:" in theme
    assert persona["name"] == "Vanta"
    assert "private personal AI command center" in persona["system_prompt"]
    assert "explicit approval" in persona["system_prompt"]
