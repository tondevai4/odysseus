from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
COMMAND_CENTER = (ROOT / "static" / "js" / "commandCenter.js").read_text(encoding="utf-8")
HOUSING_BIDS = (ROOT / "static" / "js" / "housingBids.js").read_text(encoding="utf-8")


def test_housing_bids_is_reachable_from_command_center_and_tools():
    assert 'id="tool-housing-bids-btn"' in INDEX
    assert 'data-command-center-action="housing-bids"' in INDEX
    assert "openHousingBids" in COMMAND_CENTER
    assert "housingBidsModule.open()" in APP


def test_housing_bids_uses_authenticated_preferences_without_local_storage():
    assert "const PREF_KEY = 'housing-bids-v1'" in HOUSING_BIDS
    assert "method: 'GET'" in HOUSING_BIDS
    assert "method: 'PUT'" in HOUSING_BIDS
    assert "credentials: 'same-origin'" in HOUSING_BIDS
    assert "localStorage" not in HOUSING_BIDS


def test_housing_bids_has_versioned_fields_and_statuses():
    for field in (
        "propertyArea",
        "dateBidded",
        "description",
        "status",
        "priorityBand",
        "notes",
        "outcome",
        "createdAt",
        "updatedAt",
    ):
        assert field in HOUSING_BIDS

    for status in ("Pending", "Shortlisted", "Offered", "Unsuccessful", "Withdrawn"):
        assert status in HOUSING_BIDS

    assert "version: 1" in HOUSING_BIDS


def test_housing_bids_uses_safe_text_and_confirmed_delete():
    assert ".textContent =" in HOUSING_BIDS
    assert "uiModule.styledConfirm" in HOUSING_BIDS
    assert "Delete the bid for" in HOUSING_BIDS
    assert "Add First Bid" in HOUSING_BIDS
