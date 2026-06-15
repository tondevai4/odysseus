import asyncio

from routes import archive_routes, prefs_routes
from services import archive_service
from src.archive_prompt import ARCHIVE_SYSTEM_PROMPT


def _prefs_file(tmp_path, monkeypatch):
    target = tmp_path / "prefs.json"
    monkeypatch.setattr(prefs_routes, "PREFS_FILE", str(target))
    return target


class _Session:
    endpoint_url = "http://model.test/v1"
    model = "test-model"
    headers = {}


class _Sessions:
    def get_session(self, session_id):
        if session_id != "session-1":
            raise KeyError(session_id)
        return _Session()


class _Request:
    app = type("App", (), {"state": type("State", (), {})()})()


def _endpoint(router, path, method):
    return next(
        route.endpoint for route in router.routes
        if route.path == path and method in route.methods
    )


def test_archive_dossiers_are_versioned_and_owner_scoped(tmp_path, monkeypatch):
    _prefs_file(tmp_path, monkeypatch)
    alice = archive_service.add_dossier("alice", {
        "title": "Signal theory",
        "summary": "Current evidence is unclear.",
        "confidence": "unclear",
        "sources": [{"title": "Official record", "url": "https://example.test"}],
    })
    archive_service.add_dossier("bob", {
        "title": "Bob private dossier",
        "summary": "Private",
    })
    updated = archive_service.append_claim("alice", alice["id"], "The claim began in 2012.")

    assert archive_service.PREF_KEY == "archive-dossiers-v1"
    assert updated["claims"] == ["The claim began in 2012."]
    assert archive_service.load_dossiers("alice")["dossiers"][0]["title"] == "Signal theory"
    assert archive_service.load_dossiers("bob")["dossiers"][0]["title"] == "Bob private dossier"


def test_archive_chat_is_clean_room_with_only_web_evidence(monkeypatch):
    captured = {}

    async def fake_llm(url, model, messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return "## Claim\nUnclear.\n\n## Verdict / Current Confidence\nunknown"

    monkeypatch.setattr(archive_routes, "_verify_session_owner", lambda *args, **kwargs: None)
    monkeypatch.setattr(archive_routes, "_enforce_chat_privileges", lambda *args, **kwargs: None)
    monkeypatch.setattr(archive_routes, "get_current_user", lambda request: "alice")
    monkeypatch.setattr(archive_routes, "llm_call_async", fake_llm)
    monkeypatch.setattr(
        archive_routes,
        "comprehensive_web_search",
        lambda query, **kwargs: (
            "Evidence block from search.",
            [{"title": "Primary document", "url": "https://example.test/source"}],
        ),
    )
    router = archive_routes.setup_archive_routes(_Sessions())
    endpoint = _endpoint(router, "/api/archive/chat", "POST")
    body = archive_routes.ArchiveChatBody(
        message="Find where this claim started.",
        session="session-1",
        history=[{"role": "assistant", "content": "Prior Archive answer."}],
        use_web=True,
    )
    result = asyncio.run(endpoint(_Request(), body))

    assert result["isolation"] == "clean-room"
    assert result["sources"][0]["title"] == "Primary document"
    assert captured["messages"][0] == {"role": "system", "content": ARCHIVE_SYSTEM_PROMPT}
    joined = "\n".join(message["content"] for message in captured["messages"])
    assert "Archive web evidence" in joined
    assert "Vanta Brain retrieval" not in joined
    assert "saved memory" not in joined
    assert captured["kwargs"]["prompt_type"] == "archive"
    assert captured["kwargs"]["session_id"] is None


def test_archive_reports_search_unavailable(monkeypatch):
    captured = {}

    async def fake_llm(url, model, messages, **kwargs):
        captured["messages"] = messages
        return "Live search is unavailable for this request."

    monkeypatch.setattr(archive_routes, "_verify_session_owner", lambda *args, **kwargs: None)
    monkeypatch.setattr(archive_routes, "_enforce_chat_privileges", lambda *args, **kwargs: None)
    monkeypatch.setattr(archive_routes, "get_current_user", lambda request: "alice")
    monkeypatch.setattr(archive_routes, "llm_call_async", fake_llm)
    monkeypatch.setattr(
        archive_routes,
        "comprehensive_web_search",
        lambda query, **kwargs: ("No search results found.", []),
    )
    endpoint = _endpoint(
        archive_routes.setup_archive_routes(_Sessions()),
        "/api/archive/chat",
        "POST",
    )
    result = asyncio.run(endpoint(_Request(), archive_routes.ArchiveChatBody(
        message="Deep dive this claim.",
        session="session-1",
    )))

    assert result["search_status"] == "unavailable"
    assert any(
        "Live search returned no usable sources" in message["content"]
        for message in captured["messages"]
    )


def test_archive_dossier_commands_and_incognito(tmp_path, monkeypatch):
    _prefs_file(tmp_path, monkeypatch)
    archive_service.add_dossier("alice", {
        "title": "Case One",
        "summary": "Evidence remains weak.",
        "confidence": "weak",
    })
    monkeypatch.setattr(archive_routes, "_verify_session_owner", lambda *args, **kwargs: None)
    monkeypatch.setattr(archive_routes, "_enforce_chat_privileges", lambda *args, **kwargs: None)
    monkeypatch.setattr(archive_routes, "get_current_user", lambda request: "alice")
    endpoint = _endpoint(
        archive_routes.setup_archive_routes(_Sessions()),
        "/api/archive/chat",
        "POST",
    )

    listed = asyncio.run(endpoint(_Request(), archive_routes.ArchiveChatBody(
        message="Show my Archive dossiers.",
        session="session-1",
    )))
    opened = asyncio.run(endpoint(_Request(), archive_routes.ArchiveChatBody(
        message="Open dossier Case One",
        session="session-1",
    )))
    blocked = asyncio.run(endpoint(_Request(), archive_routes.ArchiveChatBody(
        message="Save this as an Archive dossier.",
        session="session-1",
        incognito=True,
    )))
    refused = asyncio.run(endpoint(_Request(), archive_routes.ArchiveChatBody(
        message="Delete Archive dossier Case One",
        session="session-1",
    )))

    assert "Case One" in listed["answer"]
    assert "Evidence remains weak" in opened["answer"]
    assert blocked["action"] == "blocked"
    assert "incognito/private mode" in blocked["answer"]
    assert refused["action"] == "blocked"


def test_normal_vanta_brain_does_not_load_archive_dossiers():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "services" / "vanta_brain.py"
    ).read_text(encoding="utf-8")
    assert "archive-dossiers-v1" not in source

