import asyncio
import json
import os

import core.database as cdb
from core.database import Note
from src.tool_execution import _guard_chat_note_action
from src.tool_implementations import do_manage_notes
from tests.helpers.sqlite_db import make_temp_sqlite


def test_append_uses_exact_title_and_preserves_owner_isolation(monkeypatch):
    session_local, engine, tmpfile = make_temp_sqlite(cdb.Base.metadata)
    monkeypatch.setattr(cdb, "SessionLocal", session_local)
    db = session_local()
    try:
        db.add(Note(
            id="alice-note",
            owner="alice",
            title="Work Leads",
            content="Agency A",
            note_type="note",
            archived=False,
        ))
        db.add(Note(
            id="bob-note",
            owner="bob",
            title="Work Leads",
            content="Private Bob data",
            note_type="note",
            archived=False,
        ))
        db.commit()
    finally:
        db.close()

    result = asyncio.run(do_manage_notes(json.dumps({
        "action": "append",
        "title": "Work Leads",
        "content": "Agency B",
    }), owner="alice"))

    db = session_local()
    try:
        assert result["response"] == "Done, Boss. Saved to Notes."
        assert db.query(Note).filter(Note.id == "alice-note").one().content == "Agency A\n\nAgency B"
        assert db.query(Note).filter(Note.id == "bob-note").one().content == "Private Bob data"
    finally:
        db.close()
        engine.dispose()
        tmpfile.close()
        os.unlink(tmpfile.name)


def test_chat_note_guard_blocks_destructive_mutations():
    delete = _guard_chat_note_action('{"action":"delete","id":"abc"}')
    update = _guard_chat_note_action('{"action":"update","id":"abc","content":"replace"}')

    assert delete[0] == "manage_notes: BLOCKED"
    assert "cannot be deleted from chat" in delete[1]["error"]
    assert update[0] == "manage_notes: CONFIRMATION_REQUIRED"
    assert "will not overwrite" in update[1]["error"]
    assert _guard_chat_note_action('{"action":"append","title":"Work Leads","content":"Agency B"}') is None
