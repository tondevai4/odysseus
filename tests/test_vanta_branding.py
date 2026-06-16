import json
from pathlib import Path

from src.preset_manager import PresetManager


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_uses_yves_brand():
    manifest = json.loads((ROOT / "static" / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "YVES"
    assert manifest["short_name"] == "YVES"
    assert "strnos" in manifest["description"].lower()


def test_brand_config_contains_core_copy():
    branding = (ROOT / "static" / "branding.js").read_text(encoding="utf-8")

    assert "name: 'YVES'" in branding
    assert "wordmark: 'YVES'" in branding
    assert "Powered by STRNOS" in branding
    assert "Morning, Boss. Yves is online." in branding
    assert "currentMeta.textContent = `${brand.name} Chat`" in branding


def test_yves_theme_and_persona_are_built_in_with_vanta_compat_key():
    theme = (ROOT / "static" / "js" / "theme.js").read_text(encoding="utf-8")
    persona = PresetManager.DEFAULT_PRESETS["vanta"]

    assert "vanta:" in theme
    assert persona["name"] == "YVES"
    assert "STRNOS" in persona["system_prompt"]
    assert "private personal AI command center" in persona["system_prompt"]
    assert "explicit approval" in persona["system_prompt"]
