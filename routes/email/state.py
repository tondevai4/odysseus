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
_LIST_CACHE = {}  # key → (expires_at, response_dict)
_LIST_TTL = 8.0
_READ_CACHE = {}  # key → (expires_at, response_dict)
_READ_TTL = 30 * 60.0
_IMAP_POOL = {}   # account_id → (conn, last_used_at)
_IMAP_IDLE_MAX = 60.0
_WARMING_READS = set()
_WARM_READ_LIMIT = 1
_WARM_MAX_BYTES = 128 * 1024
_WARM_RECENT_SECONDS = 7 * 24 * 60 * 60
_pool_lock = _threading.Lock()

def _pooled_connect(account_id, owner=""):
    """Reuse a live IMAP connection if one is in the pool and still
    responsive. Otherwise open fresh and store it. Caller must release
    via _pooled_release after use (not strictly required — the pool
    holds the same conn handle, and we lock to serialize access).

    SECURITY: `owner` is forwarded to `_imap_connect` so the fallback
    config lookup (when `account_id` is None) is scoped to this user's
    accounts only. The pool key is (account_id, owner) so two users
    with `account_id=None` don't share a pooled connection.
    """
    pool_key = (account_id, owner)
    now = _time.monotonic()
    with _pool_lock:
        entry = _IMAP_POOL.get(pool_key)
        if entry:
            conn, last_used = entry
            if (now - last_used) < _IMAP_IDLE_MAX:
                try:
                    conn.noop()
                    # Pop it out of the pool while we use it (serialize)
                    del _IMAP_POOL[pool_key]
                    return conn, True  # reused
                except Exception:
                    try: conn.logout()
                    except Exception: pass
                    del _IMAP_POOL[pool_key]
            else:
                try: conn.logout()
                except Exception: pass
                del _IMAP_POOL[pool_key]
    # Fresh connection
    return _imap_connect(account_id, owner=owner), False

def _pooled_release(account_id, conn, ok=True, owner=""):
    # SECURITY: match the (account_id, owner) key used by _pooled_connect
    # so a pooled handle is returned to the same per-user slot.
    if not ok:
        try: conn.logout()
        except Exception: pass
        return
    with _pool_lock:
        _IMAP_POOL[(account_id, owner)] = (conn, _time.monotonic())

def _list_cache_key(account_id, folder, filter_, limit, offset, from_addr=""):
    return (account_id or "", folder, filter_, int(limit), int(offset), from_addr or "")

def _read_cache_key(account_id, folder, uid, owner=""):
    # SECURITY: include owner so two users with `account_id == ""` /
    # None (i.e. resolved through the per-user default) don't share
    # a cached message body.
    return (account_id or "", folder, str(uid), owner)

def _list_cache_get(key):
    v = _LIST_CACHE.get(key)
    if not v: return None
    if v[0] < _time.monotonic():
        _LIST_CACHE.pop(key, None)
        return None
    return v[1]

def _list_cache_put(key, value):
    _LIST_CACHE[key] = (_time.monotonic() + _LIST_TTL, value)
    # Cap size
    if len(_LIST_CACHE) > 64:
        for k in list(_LIST_CACHE.keys())[:-32]:
            _LIST_CACHE.pop(k, None)

def _invalidate_list_cache(account_id=None, folder=None):
    """Drop list cache entries that the caller's mutation may have stale-ed.

    Called from flag-mutating endpoints (mark-read/unread/answered, archive,
    delete, move) so the UI doesn't show stale read/unread counts for up to
    the 8s TTL after a manual flag change. With no args, clears everything.
    """
    if account_id is None and folder is None:
        _LIST_CACHE.clear()
        return
    for k in list(_LIST_CACHE.keys()):
        k_acct = k[0] if len(k) > 0 else ""
        k_folder = k[1] if len(k) > 1 else ""
        if (account_id is None or k_acct == (account_id or "")) and \
           (folder is None or k_folder == folder):
            _LIST_CACHE.pop(k, None)

def _read_cache_get(key):
    v = _READ_CACHE.get(key)
    if not v: return None
    if v[0] < _time.monotonic():
        _READ_CACHE.pop(key, None)
        return None
    return v[1]

def _read_cache_put(key, value):
    _READ_CACHE[key] = (_time.monotonic() + _READ_TTL, value)
    if len(_READ_CACHE) > 256:
        for k in list(_READ_CACHE.keys())[:-128]:
            _READ_CACHE.pop(k, None)

