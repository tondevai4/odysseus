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
def _list_emails_sync(folder, limit, offset, filter_, account_id, from_addr=None, has_attachments_only=False, owner=""):
    """Sync IMAP work — call from async handler via asyncio.to_thread so
    it doesn't block the event loop.

    When `has_attachments_only` is True, IMAP doesn't have a portable
    HASATTACH keyword, so we widen the fetch (up to ~400 most-recent
    UIDs in the folder slice) and post-filter by Content-Type. Total
    count then reflects matches in that scanned window, not the whole
    folder.

    SECURITY: `owner` is propagated so when `account_id` is missing,
    the fallback config lookup is scoped to this user's accounts only.
    """
    conn = None
    try:
        conn = _imap_connect(account_id, owner=owner)
        select_status, _ = conn.select(_q(folder), readonly=True)
        if select_status != "OK":
            return {"emails": [], "total": 0, "folder": folder, "error": f"Folder not found: {folder}"}

        from_clause = ""
        if from_addr:
            # Escape quotes/backslashes for IMAP SEARCH FROM
            _safe = from_addr.replace("\\", "\\\\").replace('"', '\\"')
            from_clause = f' FROM "{_safe}"'

        if filter_ == "unread":
            status, data = _imap_uid_search(conn, f"(UNSEEN{from_clause})")
        elif filter_ == "favorites":
            # Flagged/favorited emails (the star toggle sets the \Flagged flag).
            status, data = _imap_uid_search(conn, f"(FLAGGED{from_clause})")
        elif filter_ == "unanswered":
            status, data = _imap_uid_search(conn, f"(UNSEEN UNANSWERED{from_clause})")
        elif filter_ == "undone":
            # All emails NOT marked as answered/done (read or unread).
            status, data = _imap_uid_search(conn, f"(UNANSWERED{from_clause})")
        elif filter_ == "reminders":
            # Prefer the Odysseus marker header, but include the subject
            # fallback too. The fallback uses a distinct Odysseus prefix
            # so ordinary emails containing "Reminder" don't get mixed in.
            status, data = _imap_uid_search(
                conn,
                f'(OR HEADER X-Odysseus-Kind "reminder" SUBJECT "Reminder (Odysseus):"{from_clause})',
            )
        elif filter_ == "pending_30d":
            # "What's pending in the last month" — UNANSWERED + delivered
            # within the last 30 days. SINCE takes a DD-Mon-YYYY date.
            from datetime import datetime as _dt, timedelta as _td
            _since = (_dt.utcnow() - _td(days=30)).strftime("%d-%b-%Y")
            status, data = _imap_uid_search(conn, f'(UNANSWERED SINCE "{_since}"{from_clause})')
        elif filter_ == "stale_30d":
            # "What's been sitting too long" — UNANSWERED + delivered
            # MORE than 30 days ago. BEFORE excludes the cutoff date itself.
            from datetime import datetime as _dt, timedelta as _td
            _before = (_dt.utcnow() - _td(days=30)).strftime("%d-%b-%Y")
            status, data = _imap_uid_search(conn, f'(UNANSWERED BEFORE "{_before}"{from_clause})')
        elif filter_ and filter_.startswith("tag:"):
            # Tag-based filter — resolve UIDs from email_tags first, then
            # ask IMAP for those messages by Message-ID. `tag:spam` reads
            # spam_verdict=1; any other tag matches JSON-array membership
            # in `tags`.
            _tag_name = filter_[len("tag:"):].strip().lower()
            _tag_message_ids = []
            _tag_seq_fallback = []
            try:
                import sqlite3 as _sql3t
                _ct = _sql3t.connect(SCHEDULED_DB)
                _owner_clause, _owner_params = _email_tag_owner_clause(account_id, owner)
                # SECURITY: owner-scope the lookup (review C2/H8). Without
                # this, user A's `tag:urgent` filter would surface UIDs
                # written by user B and IMAP would return whatever
                # happens to live at those UIDs in A's mailbox. Account
                # mailbox aliases are included because the background
                # urgency task may be owned by the mailbox address while
                # the UI is owned by the app user.
                if _tag_name == "spam":
                    rows_t = _ct.execute(
                        "SELECT message_id, uid FROM email_tags "
                        "WHERE folder=? AND spam_verdict=1 "
                        f"AND {_owner_clause}",
                        (folder, *_owner_params),
                    ).fetchall()
                    for mid, uid in rows_t:
                        if mid:
                            _tag_message_ids.append(str(mid).strip())
                        elif uid:
                            _tag_seq_fallback.append(str(uid).strip())
                else:
                    rows_t = _ct.execute(
                        "SELECT message_id, uid, tags FROM email_tags "
                        "WHERE folder=? AND tags IS NOT NULL AND tags != '' "
                        f"AND {_owner_clause}",
                        (folder, *_owner_params),
                    ).fetchall()
                    for r in rows_t:
                        try:
                            tg = json.loads(r[2] or "[]")
                            wanted = {_tag_name}
                            if _tag_name == "marketing":
                                wanted.add("promo")
                            row_tags = {str(t).strip().lower().replace("_", "-") for t in tg} if isinstance(tg, list) else set()
                            if wanted.intersection(row_tags):
                                if r[0]:
                                    _tag_message_ids.append(str(r[0]).strip())
                                elif r[1]:
                                    _tag_seq_fallback.append(str(r[1]).strip())
                        except Exception:
                            continue
                _ct.close()
            except Exception as _te:
                logger.warning(f"tag filter lookup failed: {_te}")
            if not _tag_message_ids and not _tag_seq_fallback:
                conn.logout()
                return {"emails": [], "total": 0, "folder": folder}
            # Prefer stable Message-ID rows. Older tag rows may have only
            # numeric ids; those were sequence numbers historically, but
            # may be real UIDs for newer rows. Treat them as UIDs only.
            def _imap_search_quote(value: str) -> str:
                return '"' + str(value or "").replace("\\", "\\\\").replace('"', '\\"') + '"'
            _uids = set()
            for _mid in dict.fromkeys(_tag_message_ids):
                if not _mid:
                    continue
                st_m, data_m = _imap_uid_search(conn, f'(HEADER Message-ID {_imap_search_quote(_mid)}{from_clause})')
                if st_m == "OK" and data_m and data_m[0]:
                    _uids.update(data_m[0].split())
            for _uid in _tag_seq_fallback:
                if _uid:
                    _uids.add(str(_uid).encode())
            if not _uids:
                conn.logout()
                return {"emails": [], "total": 0, "folder": folder}
            data = [b" ".join(sorted(_uids, key=lambda x: int(x) if str(x, "ascii", "ignore").isdigit() else 0))]
            status = "OK"
        elif from_clause:
            status, data = _imap_uid_search(conn, f"({from_clause.strip()})")
        else:
            status, data = _imap_uid_search(conn, "ALL")

        if status != "OK" or not data[0]:
            conn.logout()
            return {"emails": [], "total": 0, "folder": folder}

        uid_list = data[0].split()
        total = len(uid_list)
        # Reverse for newest first, apply pagination
        uid_list = list(reversed(uid_list))
        if has_attachments_only:
            # Can't filter via IMAP — widen the window so post-filter
            # still yields enough rows to fill `limit` after dropping
            # rows without attachments.
            scan_window = max(400, offset + limit * 8)
            uid_list = uid_list[:scan_window]
        else:
            uid_list = uid_list[offset:offset + limit]

        # Preload tag rows once — keyed by uid (as str) for the emails we'll render
        _tag_by_uid = {}
        try:
            import sqlite3 as _sql3
            _c = _sql3.connect(SCHEDULED_DB)
            _uid_strs = [u.decode() for u in uid_list]
            if _uid_strs:
                placeholders = ",".join("?" * len(_uid_strs))
                _owner_clause, _owner_params = _email_tag_owner_clause(account_id, owner)
                rows = _c.execute(
                    f"SELECT uid, tags, spam_verdict FROM email_tags "
                    f"WHERE folder=? AND {_owner_clause} AND uid IN ({placeholders})",
                    [folder, *_owner_params, *_uid_strs],
                ).fetchall()
                for r in rows:
                    try:
                        tg = json.loads(r[1] or "[]")
                    except Exception:
                        tg = []
                    if isinstance(tg, list):
                        tg = ["marketing" if str(t).strip().lower().replace("_", "-") == "promo" else t for t in tg]
                    _tag_by_uid[r[0]] = {"tags": tg, "spam": bool(r[2])}
            _c.close()
        except Exception as e:
            logger.warning(f"Tag preload failed: {e}")

        # Batch fetch ALL requested UIDs in a single IMAP round-trip.
        # Per-UID fetch was the dominant cost — N round-trips × (~5-20ms
        # each on localhost) made 50-message lists take 250ms-1s+. The
        # batched form trades a slightly bigger response for one round-trip.
        emails = []
        if uid_list:
            fetch_set = b",".join(uid_list)
            try:
                status, msg_data = _imap_uid_fetch(conn, fetch_set, "(UID FLAGS RFC822.HEADER RFC822.SIZE)")
            except Exception as e:
                logger.warning(f"Batch fetch failed, falling back to per-UID: {e}")
                status, msg_data = "NO", []
            # Group the batched response into per-message (meta, payload)
            # records. Bare bytes parts must be kept: Gmail returns FLAGS
            # after the header literal as a bare element, and dropping it
            # rendered every Gmail message as unread/unflagged.
            grouped = _group_uid_fetch_records(msg_data)

            if status != "OK" and not grouped:
                conn.logout()
                return {"emails": [], "total": total, "folder": folder, "offset": offset}

            _tag_by_message_id = {}
            try:
                header_ids = []
                for _, raw_header in grouped:
                    if not raw_header:
                        continue
                    mid = (email_mod.message_from_bytes(raw_header).get("Message-ID", "") or "").strip()
                    if mid:
                        header_ids.append(mid)
                if header_ids:
                    import sqlite3 as _sql3m
                    _cm = _sql3m.connect(SCHEDULED_DB)
                    _owner_clause_m, _owner_params_m = _email_tag_owner_clause(account_id, owner)
                    _mid_ph = ",".join("?" * len(header_ids))
                    rows_m = _cm.execute(
                        f"SELECT message_id, tags, spam_verdict FROM email_tags "
                        f"WHERE folder=? AND {_owner_clause_m} "
                        f"AND message_id IN ({_mid_ph})",
                        [folder, *_owner_params_m, *header_ids],
                    ).fetchall()
                    _cm.close()
                    for mid, tags_raw, spam_raw in rows_m:
                        try:
                            tags = json.loads(tags_raw or "[]")
                        except Exception:
                            tags = []
                        if isinstance(tags, list):
                            tags = ["marketing" if str(t).strip().lower().replace("_", "-") == "promo" else t for t in tags]
                        _tag_by_message_id[(mid or "").strip()] = {
                            "tags": tags if isinstance(tags, list) else [],
                            "spam": bool(spam_raw),
                        }
            except Exception as e:
                logger.warning(f"Message-ID tag preload failed: {e}")

            for meta_b, raw_header in grouped:
                try:
                    meta = meta_b.decode(errors="replace")
                    uid_num = _uid_from_fetch_meta(meta_b)
                    if not uid_num:
                        continue
                    flag_m = re.search(r'FLAGS \(([^)]*)\)', meta)
                    flags = flag_m.group(1) if flag_m else ""
                    size_m = re.search(r'RFC822\.SIZE (\d+)', meta)
                    size = int(size_m.group(1)) if size_m else 0
                    if not raw_header:
                        continue

                    msg = email_mod.message_from_bytes(raw_header)
                    subject = _decode_header(msg.get("Subject", "(no subject)"))
                    sender = _decode_header(msg.get("From", "unknown"))
                    date_str = msg.get("Date", "")
                    message_id = msg.get("Message-ID", "")
                    sender_name, sender_addr = email.utils.parseaddr(sender)
                    # To/Cc — needed for the from-sender sidebar's
                    # multi-tag filter ("emails involving ALL these
                    # people"). Decoded raw strings; client splits.
                    to_str = _decode_header(msg.get("To", ""))
                    cc_str = _decode_header(msg.get("Cc", ""))
                    parsed_date = email.utils.parsedate_to_datetime(date_str) if date_str else None
                    # Normalise tz-naive parses to UTC so timestamp() is
                    # deterministic across hosts.
                    if parsed_date and parsed_date.tzinfo is None:
                        from datetime import timezone as _tz
                        parsed_date = parsed_date.replace(tzinfo=_tz.utc)
                    iso_date = parsed_date.isoformat() if parsed_date else ""
                    date_epoch = parsed_date.timestamp() if parsed_date else 0.0
                    is_read = "\\Seen" in flags
                    is_answered = "\\Answered" in flags
                    is_flagged = "\\Flagged" in flags
                    ct = msg.get("Content-Type", "")
                    has_attachments = "multipart/mixed" in ct.lower() or "multipart/related" in ct.lower()
                    tag_entry = _tag_by_message_id.get(message_id.strip()) or _tag_by_uid.get(uid_num, {})
                    emails.append({
                        "uid": uid_num,
                        "message_id": message_id.strip(),
                        "subject": subject,
                        "from_name": sender_name or sender_addr,
                        "from_address": sender_addr,
                        "to": to_str,
                        "cc": cc_str,
                        "date": iso_date,
                        "date_display": date_str,
                        "date_epoch": date_epoch,
                        "size": size,
                        "is_read": is_read,
                        "is_answered": is_answered,
                        "is_flagged": is_flagged,
                        "flags": flags,
                        "has_attachments": has_attachments,
                        "tags": tag_entry.get("tags", []),
                        "is_spam_verdict": tag_entry.get("spam", False),
                    })
                except Exception as e:
                    logger.warning(f"Error parsing batched email entry: {e}")
                    continue
            # IMAP returns batched results in seq-set order, not the
            # newest-first order we want. Sort by the parsed UTC epoch
            # so cross-timezone dates compare chronologically (ISO-string
            # sort had `+02:00` beating `+00:00` at the same local time).
            emails.sort(key=lambda x: x.get("date_epoch") or 0.0, reverse=True)

        if has_attachments_only:
            emails = [e for e in emails if e.get("has_attachments")]
            # Total now reflects matches inside the scanned window, not
            # the whole folder — see scan_window above.
            total = len(emails)
            emails = emails[offset:offset + limit]

        # Bulk-attach cached AI summaries by Message-ID so the frontend
        # can show them on hover (avoids a per-card round-trip).
        try:
            ids = [e.get("message_id", "") for e in emails if e.get("message_id")]
            if ids:
                import sqlite3 as _sql3
                _c = _sql3.connect(SCHEDULED_DB)
                placeholders = ",".join("?" * len(ids))
                owner_clause, owner_params = _email_cache_owner_clause(owner)
                rows = _c.execute(
                    f"SELECT message_id, summary FROM email_summaries "
                    f"WHERE message_id IN ({placeholders}) AND {owner_clause}",
                    (*ids, *owner_params),
                ).fetchall()
                _c.close()
                by_id = {r[0]: r[1] for r in rows}
                for e in emails:
                    s = by_id.get(e.get("message_id", ""))
                    if s:
                        e["cached_summary"] = s
        except Exception as _summary_err:
            logger.debug(f"Bulk summary attach skipped: {_summary_err}")

        return {"emails": emails, "total": total, "folder": folder, "offset": offset}
    except Exception as e:
        logger.error(f"Failed to list emails: {e}")
        detail = str(e).strip()
        return {"emails": [], "total": 0, "error": f"Mail operation failed: {detail[:180]}" if detail else "Mail operation failed"}
    finally:
        if conn:
            try:
                conn.logout()
            except Exception:
                pass

@router.get("/list")
async def list_emails(
    folder: str = Query("INBOX"),
    limit: int = Query(50),
    offset: int = Query(0),
    filter: str = Query("all"),  # all, unread, unanswered
    from_addr: str | None = Query(None, alias="from"),
    account_id: str | None = Query(None),
    has_attachments: int = Query(0),
    cache_bust: str | None = Query(None, alias="_"),
    owner: str = Depends(require_owner),
):
    """List emails. Uses an 8s in-memory cache + offloads blocking IMAP
    calls to a worker thread so the event loop never stalls."""
    _deferred = getattr(_start_poller, '_deferred', None)
    if _deferred:
        await _deferred()
    # SECURITY: include `owner` in the cache key so two users with
    # different account scopes don't share a cached list.
    ck = _list_cache_key(account_id, folder, filter, limit, offset, from_addr or "") + (int(bool(has_attachments)), owner)
    if not cache_bust:
        cached = _list_cache_get(ck)
        if cached is not None:
            _schedule_recent_email_warm(cached.get("emails") or [], folder, account_id, owner)
            return cached
    result = await _asyncio.to_thread(
        _list_emails_sync, folder, limit, offset, filter, account_id, from_addr,
        bool(has_attachments), owner,
    )
    if result and not result.get("error"):
        if offset == 0 and not from_addr and not has_attachments and filter in ("all", "unread", "unanswered", "undone"):
            _record_email_received_events(owner, account_id, folder, result.get("emails") or [])
            _schedule_recent_email_warm(result.get("emails") or [], folder, account_id, owner)
        _list_cache_put(ck, result)
    return result

@router.post("/{uid}/unflag-spam")
async def unflag_spam(uid: str, owner: str = Depends(require_owner)):
    """User override — mark email as not spam."""
    try:
        owner_clause, owner_params = _email_tag_owner_clause(None, owner)
        _c = _sql3.connect(SCHEDULED_DB)
        _c.execute(
            f"UPDATE email_tags SET spam_verdict=0, spam_reason='' WHERE uid=? AND {owner_clause}",
            [uid, *owner_params],
        )
        _c.commit()
        _c.close()
        return {"ok": True}
    except Exception as e:
        logger.error(f"unflag-spam failed: {e}")
        return {"ok": False, "error": "Mail operation failed"}

@router.get("/contacts")
async def list_contacts(
    q: str = Query(""),
    limit: int = Query(20),
    owner: str = Depends(require_owner),
):
    """Distinct name/address pairs aggregated from the email_tags table
    — used by the from-sender sidebar's autocomplete to convert typed
    names into chips. Backed by the AI-classification cache so it's a
    cheap SQL read; people you've never received a tagged email from
    won't appear yet."""
    ql = (q or "").strip().lower()
    try:
        conn = _sql3.connect(SCHEDULED_DB)
        owner_clause, owner_params = _email_tag_owner_clause(None, owner)
        rows = conn.execute(
            f"SELECT sender FROM email_tags WHERE sender IS NOT NULL AND sender != '' AND {owner_clause}",
            owner_params,
        ).fetchall()
        conn.close()
        seen = {}
        for (s,) in rows:
            try:
                name, addr = email.utils.parseaddr(s or "")
            except Exception:
                continue
            if not addr:
                continue
            addr_l = addr.lower()
            if ql and ql not in (name or "").lower() and ql not in addr_l:
                continue
            if addr_l in seen:
                continue
            seen[addr_l] = {"name": (name or addr).strip(), "address": addr}
        items = list(seen.values())
        # Prefer entries whose name starts with the query, then alphabetical.
        items.sort(key=lambda c: (
            0 if ql and (c["name"] or "").lower().startswith(ql) else 1,
            (c["name"] or c["address"]).lower(),
        ))
        return {"contacts": items[: max(1, int(limit))]}
    except Exception as e:
        logger.error(f"contacts list failed: {e}")
        return {"contacts": [], "error": "Mail operation failed"}

@router.get("/search")
async def search_emails(
    q: str = Query(""),
    folder: str = Query("INBOX"),
    limit: int = Query(50),
    account_id: str | None = Query(None),
    owner: str = Depends(require_owner),
):
    """Search emails server-side via IMAP SEARCH. Matches subject, from, or body text."""
    if not q or len(q) < 2:
        return {"emails": [], "total": 0, "query": q}
    # CRLF in q would terminate the IMAP command early — reject defensively.
    if "\r" in q or "\n" in q:
        raise HTTPException(400, "Invalid query")
    try:
        with _imap(account_id, owner=owner) as conn:
            conn.select(_q(folder), readonly=True)

            # Escape backslash and quote for the IMAP-SEARCH quoted-string.
            q_escaped = q.replace('\\', '\\\\').replace('"', '\\"')
            search_cmd = f'(OR OR FROM "{q_escaped}" SUBJECT "{q_escaped}" TEXT "{q_escaped}")'

            status, data = _imap_uid_search(conn, search_cmd)
            if status != "OK" or not data[0]:
                return {"emails": [], "total": 0, "query": q}

            uid_list = data[0].split()
            total = len(uid_list)
            uid_list = list(reversed(uid_list))[:limit]

            emails = []
            for uid in uid_list:
                try:
                    status, msg_data = _imap_uid_fetch(conn, uid, "(UID FLAGS RFC822.HEADER)")
                    if status != "OK":
                        continue
                    raw_header = None
                    flags = ""
                    # Same Gmail caveat as the list route: FLAGS may
                    # arrive after the header literal, so group bare
                    # parts back into the message meta before scanning.
                    for meta_b, payload in _group_uid_fetch_records(msg_data):
                        if payload and b"RFC822.HEADER" in meta_b:
                            raw_header = payload
                        flag_match = re.search(rb'FLAGS \(([^)]*)\)', meta_b)
                        if flag_match:
                            flags = flag_match.group(1).decode(errors="replace")
                    if not raw_header:
                        continue
                    msg = email_mod.message_from_bytes(raw_header)
                    subject = _decode_header(msg.get("Subject", "(no subject)"))
                    sender = _decode_header(msg.get("From", "unknown"))
                    date_str = msg.get("Date", "")
                    message_id = msg.get("Message-ID", "")
                    sender_name, sender_addr = email.utils.parseaddr(sender)
                    to_str = _decode_header(msg.get("To", ""))
                    cc_str = _decode_header(msg.get("Cc", ""))
                    parsed_date = email.utils.parsedate_to_datetime(date_str) if date_str else None
                    if parsed_date and parsed_date.tzinfo is None:
                        from datetime import timezone as _tz
                        parsed_date = parsed_date.replace(tzinfo=_tz.utc)
                    iso_date = parsed_date.isoformat() if parsed_date else ""
                    date_epoch = parsed_date.timestamp() if parsed_date else 0.0
                    ct = msg.get("Content-Type", "")
                    has_attachments = "multipart/mixed" in ct.lower() or "multipart/related" in ct.lower()

                    stable_uid = ""
                    for part in msg_data:
                        if isinstance(part, tuple):
                            meta_b = part[0] if isinstance(part[0], bytes) else str(part[0]).encode()
                            stable_uid = _uid_from_fetch_meta(meta_b) or stable_uid
                    if not stable_uid:
                        continue
                    emails.append({
                        "uid": stable_uid,
                        "message_id": message_id.strip(),
                        "subject": subject,
                        "from_name": sender_name or sender_addr,
                        "from_address": sender_addr,
                        "to": to_str,
                        "cc": cc_str,
                        "date": iso_date,
                        "date_display": date_str,
                        "date_epoch": date_epoch,
                        "is_read": "\\Seen" in flags,
                        "is_answered": "\\Answered" in flags,
                        "is_flagged": "\\Flagged" in flags,
                        "flags": flags,
                        "has_attachments": has_attachments,
                    })
                except Exception as e:
                    logger.warning(f"Error parsing search result {uid}: {e}")
                    continue

            return {"emails": emails, "total": total, "query": q}
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return {"emails": [], "total": 0, "error": "Mail operation failed"}

@router.post("/mark-unread/{uid}")
async def mark_unread(uid: str, folder: str = Query("INBOX"), account_id: str | None = Query(None), owner: str = Depends(require_owner)):
    """Mark an email as unread (clear \\Seen flag)."""
    try:
        with _imap(account_id, owner=owner) as conn:
            conn.select(_q(folder))
            if not _store_email_flag(conn, uid, "\\Seen", add=False):
                return {"success": False, "error": "Email not found"}
        _invalidate_list_cache(account_id, folder)
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to mark unread {uid}: {e}")
        return {"success": False, "error": "Mail operation failed"}

@router.post("/mark-read/{uid}")
async def mark_read(uid: str, folder: str = Query("INBOX"), account_id: str | None = Query(None), owner: str = Depends(require_owner)):
    """Mark an email as read (set \\Seen flag)."""
    try:
        with _imap(account_id, owner=owner) as conn:
            conn.select(_q(folder))
            if not _store_email_flag(conn, uid, "\\Seen", add=True):
                return {"success": False, "error": "Email not found"}
        _invalidate_list_cache(account_id, folder)
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to mark read {uid}: {e}")
        return {"success": False, "error": "Mail operation failed"}

@router.post("/archive/{uid}")
async def archive_email(uid: str, folder: str = Query("INBOX"), account_id: str | None = Query(None), owner: str = Depends(require_owner)):
    """Move email to Archive folder."""
    try:
        with _imap(account_id, owner=owner) as conn:
            conn.select(_q(folder))
            if not _move_email_message(conn, uid, "Archive", role="archive"):
                return {"success": False, "error": "Email not found"}
        _invalidate_list_cache(account_id)
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to archive email {uid}: {e}")
        return {"success": False, "error": "Mail operation failed"}

@router.delete("/delete/{uid}")
async def delete_email(uid: str, folder: str = Query("INBOX"), account_id: str | None = Query(None), owner: str = Depends(require_owner)):
    """Move email to Trash."""
    try:
        with _imap(account_id, owner=owner) as conn:
            conn.select(_q(folder))
            if not _move_email_message(conn, uid, "Trash", role="trash"):
                return {"success": False, "error": "Email not found"}
        _invalidate_list_cache(account_id)
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to delete email {uid}: {e}")
        return {"success": False, "error": "Mail operation failed"}

@router.delete("/delete-permanent/{uid}")
async def delete_email_permanent(uid: str, folder: str = Query("INBOX"), account_id: str | None = Query(None), owner: str = Depends(require_owner)):
    """Permanently delete an email (no Trash)."""
    try:
        with _imap(account_id, owner=owner) as conn:
            conn.select(_q(folder))
            if not _store_email_flag(conn, uid, "\\Deleted", add=True):
                return {"success": False, "error": "Email not found"}
            conn.expunge()
        _invalidate_list_cache(account_id, folder)
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to permanently delete email {uid}: {e}")
        return {"success": False, "error": "Mail operation failed"}

@router.delete("/odysseus/reminders")
async def delete_odysseus_reminder_emails(
    account_id: str | None = Query(None),
    permanent: bool = Query(False),
    owner: str = Depends(require_owner),
):
    """Delete email messages stamped as Odysseus reminders."""
    if account_id:
        _assert_owns_account(account_id, owner)
    deleted = 0
    folders_checked = []
    try:
        cfg = _get_email_config(account_id, owner=owner)
        own_addrs = [
            (cfg.get("from_address") or "").strip(),
            (cfg.get("smtp_user") or "").strip(),
            (cfg.get("imap_user") or "").strip(),
        ]
        own_addrs = [a for i, a in enumerate(own_addrs) if a and a not in own_addrs[:i]]

        def _search_quote(value: str) -> str:
            return '"' + (value or "").replace("\\", "\\\\").replace('"', '\\"') + '"'

        def _search_uids(conn, criteria: str):
            st, data = conn.uid("SEARCH", None, criteria)
            return set(data[0].split()) if st == "OK" and data and data[0] else set()

        with _imap(account_id, owner=owner) as conn:
            sent_folder = _detect_sent_folder(conn)
            candidates = ["INBOX", sent_folder, "All Mail", "[Gmail]/All Mail"]
            seen = set()
            for folder_name in candidates:
                if not folder_name or folder_name in seen:
                    continue
                seen.add(folder_name)
                try:
                    st, _ = conn.select(_q(folder_name))
                    if st != "OK":
                        continue
                    folders_checked.append(folder_name)
                    uids = set()
                    # Match the Reminders filter: new messages have the
                    # explicit kind header, and subject fallback catches
                    # clients/providers that stripped custom headers.
                    uids.update(_search_uids(conn, f'(HEADER X-Odysseus-Kind {_search_quote("reminder")})'))
                    uids.update(_search_uids(conn, f'(SUBJECT {_search_quote("Reminder (Odysseus):")})'))
                    for addr in own_addrs:
                        addr_q = _search_quote(addr)
                        uids.update(_search_uids(conn, f'(FROM {addr_q} SUBJECT {_search_quote("Reminder (Odysseus):")})'))
                        # Legacy reminders created before the Odysseus
                        # prefix still came from this mailbox as
                        # "Reminder: ..."; include them in Clear without
                        # sweeping unrelated external reminder emails.
                        uids.update(_search_uids(conn, f'(FROM {addr_q} SUBJECT {_search_quote("Reminder:")})'))
                    if not uids:
                        continue
                    for uid in sorted(uids, key=lambda b: int(b)):
                        if permanent:
                            conn.uid("STORE", uid, "+FLAGS", "\\Deleted")
                        else:
                            copy_st, _ = conn.uid("COPY", uid, _q("Trash"))
                            if copy_st == "OK":
                                conn.uid("STORE", uid, "+FLAGS", "\\Deleted")
                            else:
                                conn.uid("STORE", uid, "+FLAGS", "\\Deleted")
                        deleted += 1
                    conn.expunge()
                except Exception as e:
                    logger.warning(f"Skipped reminder cleanup in {folder_name!r}: {e}")
        _invalidate_list_cache(account_id)
        return {"success": True, "deleted": deleted, "folders_checked": folders_checked}
    except Exception as e:
        logger.error(f"delete_odysseus_reminder_emails failed: {e}")
        return {"success": False, "error": "Mail operation failed"}

@router.post("/move/{uid}")
async def move_email(uid: str, folder: str = Query("INBOX"), dest: str = Query(...), account_id: str | None = Query(None), owner: str = Depends(require_owner)):
    """Move an email to another folder."""
    try:
        with _imap(account_id, owner=owner) as conn:
            conn.select(_q(folder))
            if not _move_email_message(conn, uid, dest):
                return {"success": False, "error": f"Failed to move to {dest}"}
        _invalidate_list_cache(account_id)
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to move email {uid} to {dest}: {e}")
        return {"success": False, "error": "Mail operation failed"}

@router.get("/folders")
async def list_folders(account_id: str | None = Query(None), owner: str = Depends(require_owner)):
    """List IMAP folders."""
    try:
        with _imap(account_id, owner=owner) as conn:
            status, folders = conn.list()
        result = []
        for f in folders:
            decoded = f.decode() if isinstance(f, bytes) else f
            match = re.search(r'"([^"]*)"$|(\S+)$', decoded)
            if match:
                name = match.group(1) or match.group(2)
                result.append(name)
        return {"folders": result}
    except Exception as e:
        logger.error(f"list_folders failed: {e}")
        return {"folders": [], "error": "Mail operation failed"}

@router.post("/mark-answered/{uid}")
async def mark_answered(uid: str, folder: str = Query("INBOX"), account_id: str | None = Query(None), owner: str = Depends(require_owner)):
    """Mark an email as answered (set \\Answered flag)."""
    try:
        with _imap(account_id, owner=owner) as conn:
            conn.select(_q(folder))
            if not _store_email_flag(conn, uid, "\\Answered", add=True):
                return {"success": False, "error": "Email not found"}
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to mark answered {uid}: {e}")
        return {"success": False, "error": "Mail operation failed"}

@router.post("/clear-answered/{uid}")
async def clear_answered(uid: str, folder: str = Query("INBOX"), account_id: str | None = Query(None), owner: str = Depends(require_owner)):
    """Clear the \\Answered flag from an email."""
    try:
        with _imap(account_id, owner=owner) as conn:
            conn.select(_q(folder))
            if not _store_email_flag(conn, uid, "\\Answered", add=False):
                return {"success": False, "error": "Email not found"}
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to clear answered {uid}: {e}")
        return {"success": False, "error": "Mail operation failed"}

