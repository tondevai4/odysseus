import asyncio
import sqlite3 as _sql3
import email as email_mod
import email.header
import email.utils
import smtplib
import json
import re
import html
from html.parser import HTMLParser as _HTMLParser
import logging
import uuid
from datetime import datetime
from pathlib import Path
import time as _time
import threading as _threading

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fastapi import APIRouter, Query, UploadFile, File, BackgroundTasks, HTTPException, Depends, Request
from fastapi.responses import FileResponse
from src.constants import DATA_DIR

from src.llm_core import llm_call_async
from src.upload_limits import read_upload_limited, EMAIL_COMPOSE_UPLOAD_MAX_BYTES

from routes.email_helpers import (
    _strip_think, _extract_reply, _apply_email_style_mechanics, require_owner, require_user, _assert_owns_account,
    _q, _attach_compose_uploads, _cleanup_compose_uploads,
    _load_settings, _save_settings, _get_email_config,
    _send_smtp_message, _smtp_security_mode,
    _IMAP_TIMEOUT_SECONDS, _open_imap_connection,
    _imap_connect, _imap, _decode_header, _detect_sent_folder, _detect_drafts_folder,
    _extract_attachment_text, _list_attachments_from_msg,
    _extract_attachment_to_disk, _extract_html, _extract_text,
    _fetch_sender_thread_context, _pre_retrieve_context,
    _EMAIL_REPLY_SYS_PROMPT_BASE, _POOL_HOOKS,
    _friendly_email_auth_error,
    SendEmailRequest, ExtractStyleRequest,
    ATTACHMENTS_DIR, COMPOSE_UPLOADS_DIR, SCHEDULED_DB,
    attachment_extract_dir, _email_cache_owner_clause,
)
from routes.email_pollers import _start_poller

logger = logging.getLogger(__name__)
ODYSSEUS_MAIL_ORIGIN = "odysseus-ui"
from .utils import *
from .state import *

router = APIRouter()
@router.get("/style")
async def get_writing_style(owner: str = Depends(require_user)):
    """Get the current writing style prompt."""
    settings = _load_settings()
    return {"style": settings.get("email_writing_style", "")}

@router.put("/style")
async def update_writing_style(data: dict, owner: str = Depends(require_user)):
    """Manually update the writing style prompt."""
    settings = _load_settings()
    settings["email_writing_style"] = data.get("style", "")
    _save_settings(settings)
    return {"success": True}

@router.get("/config")
async def get_email_config(owner: str = Depends(require_user)):
    """Get email configuration (passwords masked)."""
    cfg = _get_email_config(owner=owner)
    cfg["smtp_password"] = "***" if cfg["smtp_password"] else ""
    cfg["imap_password"] = "***" if cfg["imap_password"] else ""
    # Include preferences from settings.json
    settings = _load_settings()
    cfg["email_auto_summarize"] = bool(settings.get("email_auto_summarize", False))
    cfg["email_auto_reply"] = bool(settings.get("email_auto_reply", False))
    cfg["email_auto_tag"] = bool(settings.get("email_auto_tag", False))
    cfg["email_auto_spam"] = bool(settings.get("email_auto_spam", False))
    cfg["email_auto_calendar"] = bool(settings.get("email_auto_calendar", False))
    return cfg

@router.put("/config")
async def update_email_config(data: dict, owner: str = Depends(require_owner)):
    """Update email configuration.

    Automation flags (email_auto_*) still live in settings.json. Credentials
    are written to the default EmailAccount row. Passwords are only
    overwritten when a non-empty value is provided, so saving the form
    without retyping the password no longer wipes it.
    """
    # Automation flags stay in settings.json (they're global, not per-account)
    settings = _load_settings()
    for key in ["email_auto_summarize", "email_auto_reply", "email_auto_tag", "email_auto_spam", "email_auto_calendar"]:
        if key in data:
            settings[key] = data[key]
    _save_settings(settings)

    # Credentials go into the default account row
    from core.database import SessionLocal, EmailAccount
    import uuid as _uuid
    db = SessionLocal()
    try:
        q = db.query(EmailAccount).filter(EmailAccount.is_default == True)  # noqa: E712
        if owner:
            q = q.filter(EmailAccount.owner == owner)
        row = q.first()
        if row is None:
            row = EmailAccount(id=_uuid.uuid4().hex, owner=owner, name="Default", is_default=True, enabled=True)
            db.add(row)
        field_map = {
            "smtp_host": "smtp_host", "smtp_port": "smtp_port", "smtp_user": "smtp_user",
            "smtp_security": "smtp_security", "imap_host": "imap_host", "imap_port": "imap_port", "imap_user": "imap_user",
            "imap_starttls": "imap_starttls", "email_from": "from_address",
        }
        for in_key, col_name in field_map.items():
            if in_key in data:
                val = data[in_key]
                if col_name.endswith("_port") and val in (None, ""):
                    continue
                if col_name.endswith("_port"):
                    val = int(val)
                setattr(row, col_name, val)
        # Passwords: only update when a non-empty value is given.
        # Stored encrypted; see src/secret_storage.py.
        from src.secret_storage import encrypt as _enc
        if data.get("imap_password"):
            row.imap_password = _enc(data["imap_password"])
        if data.get("smtp_password"):
            row.smtp_password = _enc(data["smtp_password"])
        clear_q = db.query(EmailAccount).filter(EmailAccount.id != row.id)
        if owner:
            clear_q = clear_q.filter(EmailAccount.owner == owner)
        clear_q.update({EmailAccount.is_default: False})
        db.commit()
    finally:
        db.close()
    return {"success": True}

# ═══════════════ Urgency state ═══════════════
# Read-only state file written by `action_check_email_urgency`. The UI
# uses this to color the unread email dot by urgency tier (3=red,
# 2=orange, otherwise default blue) and per-row dots in the inbox list.

@router.get("/urgency-state")
async def get_email_urgency_state(owner: str = Depends(require_user)):
    from pathlib import Path as _P
    import json as _json
    _slug = "".join(c if (c.isalnum() or c in "-_.@") else "_" for c in (owner or "default"))
    path = _P(DATA_DIR) / f"email_urgency_state_{_slug}.json"
    if not path.exists():
        return {"total_unread": 0, "total_urgent": 0, "max_score": 0, "per_uid": {}}
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"total_unread": 0, "total_urgent": 0, "max_score": 0, "per_uid": {}}
    # Drop `notified_uids` from the payload — it's an internal scheduler
    # debounce, not UI-relevant.
    data.pop("notified_uids", None)
    return data

# ═══════════════ Email Accounts CRUD ═══════════════
# Multi-account support. Each row is an independent IMAP/SMTP config.
# Exactly one row has is_default=True; that account is used when callers
# don't specify an account_id.

@router.get("/accounts")
async def list_email_accounts(owner: str = Depends(require_user)):
    """List all email accounts with credentials masked."""
    from core.database import SessionLocal, EmailAccount
    from sqlalchemy import and_, or_
    db = SessionLocal()
    try:
        out = []
        # SECURITY: scope to this user's accounts. Previously returned
        # every row in the EmailAccount table, leaking IMAP/SMTP hosts +
        # usernames across users. Also show legacy unowned rows that match
        # the logged-in mailbox; _get_email_config already accepts those,
        # so Settings should not hide the active account.
        q = db.query(EmailAccount)
        if owner:
            unowned = or_(EmailAccount.owner == None, EmailAccount.owner == "")  # noqa: E711
            same_mailbox = or_(EmailAccount.imap_user == owner, EmailAccount.from_address == owner)
            q = q.filter(or_(EmailAccount.owner == owner, and_(unowned, same_mailbox)))
        for r in q.order_by(
            EmailAccount.is_default.desc(), EmailAccount.created_at.asc()
        ).all():
            out.append({
                "id": r.id,
                "name": r.name,
                "is_default": bool(r.is_default),
                "enabled": bool(r.enabled),
                "imap_host": r.imap_host or "",
                "imap_port": int(r.imap_port or 993),
                "imap_user": r.imap_user or "",
                "imap_starttls": bool(r.imap_starttls),
                "smtp_host": r.smtp_host or "",
                "smtp_port": int(r.smtp_port or 465),
                "smtp_security": _smtp_security_mode({"smtp_security": getattr(r, "smtp_security", ""), "smtp_port": r.smtp_port}),
                "smtp_user": r.smtp_user or "",
                "from_address": r.from_address or "",
                "has_imap_password": bool(r.imap_password),
                "has_smtp_password": bool(r.smtp_password),
            })
        return {"accounts": out}
    finally:
        db.close()

@router.post("/accounts")
async def create_email_account(data: dict, owner: str = Depends(require_owner)):
    """Create a new email account."""
    from core.database import SessionLocal, EmailAccount
    from src.secret_storage import encrypt as _enc
    import uuid as _uuid
    name = (data.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name required"}
    db = SessionLocal()
    try:
        row = EmailAccount(
            id=_uuid.uuid4().hex,
            name=name,
            is_default=bool(data.get("is_default", False)),
            enabled=bool(data.get("enabled", True)),
            imap_host=(data.get("imap_host") or "").strip(),
            imap_port=int(data.get("imap_port") or 993),
            imap_user=(data.get("imap_user") or "").strip(),
            imap_password=_enc(data.get("imap_password") or ""),
            imap_starttls=bool(data.get("imap_starttls", True)),
            smtp_host=(data.get("smtp_host") or "").strip(),
            smtp_port=int(data.get("smtp_port") or 465),
            smtp_security=_smtp_security_mode({"smtp_security": data.get("smtp_security"), "smtp_port": data.get("smtp_port") or 465}),
            smtp_user=(data.get("smtp_user") or "").strip(),
            smtp_password=_enc(data.get("smtp_password") or ""),
            from_address=(data.get("from_address") or "").strip(),
            # SECURITY: stamp the creator so all subsequent reads / mutations
            # can filter by user. Without this every new account leaks to
            # every other user.
            owner=owner,
        )
        # If there are no accounts yet OR caller asked for default, enforce
        # the one-default invariant — but scope it to THIS user's accounts,
        # otherwise creating a default would clear every other user's
        # default flag too.
        scope_q = db.query(EmailAccount)
        if owner:
            scope_q = scope_q.filter(EmailAccount.owner == owner)
        existing_count = scope_q.count()
        if row.is_default or existing_count == 0:
            scope_q.update({EmailAccount.is_default: False})
            row.is_default = True
        db.add(row)
        db.commit()
        return {"ok": True, "id": row.id}
    finally:
        db.close()

@router.put("/accounts/{account_id}")
async def update_email_account(account_id: str, data: dict, owner: str = Depends(require_user)):
    """Update an email account. Passwords only overwrite if non-empty."""
    # Path param account_id — dep validated via Query, re-check the path-param value.
    _assert_owns_account(account_id, owner)
    from core.database import SessionLocal, EmailAccount
    db = SessionLocal()
    try:
        row = db.get(EmailAccount, account_id)
        if not row:
            return {"ok": False, "error": "Account not found"}
        # Simple fields
        for key in ("name", "imap_host", "imap_user", "smtp_host", "smtp_user", "from_address"):
            if key in data:
                setattr(row, key, (data[key] or "").strip())
        for key in ("imap_port", "smtp_port"):
            if data.get(key) not in (None, ""):
                setattr(row, key, int(data[key]))
        if "smtp_security" in data:
            row.smtp_security = _smtp_security_mode({"smtp_security": data.get("smtp_security"), "smtp_port": data.get("smtp_port") or row.smtp_port})
        for key in ("imap_starttls", "enabled"):
            if key in data:
                setattr(row, key, bool(data[key]))
        # Passwords — only overwrite when a non-empty value is
        # provided. Stored encrypted; see src/secret_storage.py.
        from src.secret_storage import encrypt as _enc
        if data.get("imap_password"):
            row.imap_password = _enc(data["imap_password"])
        if data.get("smtp_password"):
            row.smtp_password = _enc(data["smtp_password"])
        db.commit()
        return {"ok": True, "id": row.id}
    finally:
        db.close()

@router.delete("/accounts/{account_id}")
async def delete_email_account(account_id: str, owner: str = Depends(require_user)):
    _assert_owns_account(account_id, owner)
    from core.database import SessionLocal, EmailAccount
    db = SessionLocal()
    try:
        row = db.get(EmailAccount, account_id)
        if not row:
            return {"ok": False, "error": "Account not found"}
        was_default = bool(row.is_default)
        db.delete(row)
        db.commit()
        # If the deleted row was default, promote the next-oldest enabled
        # row owned by THIS user. Without the owner filter we'd promote
        # another user's account and the deleter would silently inherit
        # it as their default.
        if was_default:
            promote_q = db.query(EmailAccount).filter(EmailAccount.enabled == True)  # noqa: E712
            if owner:
                promote_q = promote_q.filter(EmailAccount.owner == owner)
            promote = promote_q.order_by(EmailAccount.created_at.asc()).first()
            if promote:
                promote.is_default = True
                db.commit()
        return {"ok": True}
    finally:
        db.close()

@router.post("/accounts/test")
async def test_account_config(req: Request, owner: str = Depends(require_user)):
    """Try to actually connect to the provided IMAP (and optionally SMTP)
    server with the given credentials. Lets the user verify a config
    BEFORE saving it. Returns per-protocol status so the UI can show
    which half failed.

    If `account_id` is provided (instead of inline credentials), load
    the saved row's stored creds and test those — used by the
    clickable test-dot in the integrations list, where the form has
    no live values."""
    try:
        body = await req.json()
    except Exception:
        return {"ok": False, "imap": {"ok": False, "error": "invalid request body"}}

    # Saved-account shortcut — hydrate missing credentials from the DB row,
    # while keeping any edited form fields from the request. This lets the UI
    # test unsaved host/port changes without forcing the user to retype the
    # stored password.
    # `imap_password` / `smtp_password` are Fernet-encrypted at rest
    # (see _migrate_encrypt_email_passwords); decrypt before use so
    # the test actually sends the real password to the server.
    acc_id = body.get("account_id")
    if acc_id:
        _assert_owns_account(acc_id, owner)
        from core.database import SessionLocal, EmailAccount
        from src.secret_storage import decrypt as _decrypt
        db = SessionLocal()
        try:
            row = db.get(EmailAccount, acc_id)
            if not row:
                return {"ok": False, "imap": {"ok": False, "error": "Account not found"}}
            saved_body = {
                "imap_host": row.imap_host or "",
                "imap_port": row.imap_port or 993,
                "imap_user": row.imap_user or "",
                "imap_password": _decrypt(row.imap_password or ""),
                "imap_starttls": bool(row.imap_starttls),
                "smtp_host": row.smtp_host or "",
                "smtp_port": row.smtp_port or 465,
                "smtp_security": _smtp_security_mode({"smtp_security": getattr(row, "smtp_security", ""), "smtp_port": row.smtp_port}),
                "smtp_user": row.smtp_user or "",
                "smtp_password": _decrypt(row.smtp_password or ""),
            }
            for key, value in body.items():
                if key == "account_id":
                    continue
                if value not in (None, ""):
                    saved_body[key] = value
            body = saved_body
        finally:
            db.close()

    imap_result = {"ok": False}
    smtp_result = None

    imap_host = (body.get("imap_host") or "").strip()
    imap_port = int(body.get("imap_port") or 993)
    imap_user = (body.get("imap_user") or "").strip()
    imap_pass = body.get("imap_password") or ""
    imap_starttls = bool(body.get("imap_starttls"))

    if not (imap_host and imap_user and imap_pass):
        imap_result = {"ok": False, "error": "Need IMAP host, username, and password"}
    else:
        # Connection mode resolution:
        #   STARTTLS on  → plain IMAP4 + .starttls() (upgrade)
        #   STARTTLS off + port 993 → IMAP4_SSL (implicit SSL, "IMAPS")
        #   STARTTLS off + any other port → plain IMAP4 (no encryption)
        # Without the last branch, local servers exposed on a non-993
        # port (Dovecot on 31143, etc.) would always fail the SSL
        # handshake because they're not actually wrapped in TLS.
        try:
            conn = _open_imap_connection(
                imap_host,
                imap_port,
                starttls=imap_starttls,
                timeout=_IMAP_TIMEOUT_SECONDS,
            )
            try:
                conn.login(imap_user, imap_pass)
                imap_result = {"ok": True}
            finally:
                try: conn.logout()
                except Exception: pass
        except Exception as e:
            imap_result = {"ok": False, "error": _friendly_email_auth_error("IMAP", imap_host, e)}

    smtp_host = (body.get("smtp_host") or "").strip()
    if smtp_host:
        smtp_port = int(body.get("smtp_port") or 465)
        smtp_security = _smtp_security_mode({"smtp_security": body.get("smtp_security"), "smtp_port": smtp_port})
        smtp_user = (body.get("smtp_user") or imap_user).strip()
        smtp_pass = body.get("smtp_password") or imap_pass
        try:
            if smtp_security == "ssl":
                smtp = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
            else:
                smtp = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
                if smtp_security == "starttls":
                    smtp.starttls()
            try:
                smtp.login(smtp_user, smtp_pass)
                smtp_result = {"ok": True}
            finally:
                try: smtp.quit()
                except Exception: pass
        except Exception as e:
            smtp_result = {"ok": False, "error": _friendly_email_auth_error("SMTP", smtp_host, e)}

    return {
        "ok": imap_result["ok"] and (smtp_result is None or smtp_result["ok"]),
        "imap": imap_result,
        "smtp": smtp_result,
    }

@router.post("/accounts/{account_id}/set-default")
async def set_default_account(account_id: str, owner: str = Depends(require_user)):
    _assert_owns_account(account_id, owner)
    from core.database import SessionLocal, EmailAccount
    db = SessionLocal()
    try:
        row = db.get(EmailAccount, account_id)
        if not row:
            return {"ok": False, "error": "Account not found"}
        # SECURITY: scope the "clear other defaults" sweep to this user's
        # accounts so we don't unset another user's default flag.
        clear_q = db.query(EmailAccount)
        if owner:
            clear_q = clear_q.filter(EmailAccount.owner == owner)
        clear_q.update({EmailAccount.is_default: False})
        row.is_default = True
        db.commit()
        return {"ok": True}
    finally:
        db.close()

