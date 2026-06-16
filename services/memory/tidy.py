"""Deterministic memory tidy helpers.

These helpers are deliberately conservative and LLM-free. They are used as the
safe backend fallback for Brain Tidy when a model cannot return a full audit
within its completion-token limit.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple


def normalize_memory_text(value: Any) -> str:
    """Collapse whitespace without rewriting the actual memory fact."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def canonical_memory_text(value: Any) -> str:
    """Stable duplicate key for exact-ish memory matching."""
    return (
        normalize_memory_text(value)
        .lower()
        .replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )


def _token_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", canonical_memory_text(value)).strip()


def _token_set(value: Any) -> set[str]:
    return {token for token in _token_key(value).split() if token}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _is_manual(memory: Dict[str, Any]) -> bool:
    return memory.get("source") not in {"auto", "unknown", None, ""}


def choose_memory_to_keep(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """Prefer pinned/manual/richer memories when duplicates are found."""
    if bool(left.get("pinned")) != bool(right.get("pinned")):
        return left if left.get("pinned") else right
    if _is_manual(left) != _is_manual(right):
        return left if _is_manual(left) else right
    if len(str(left.get("text") or "")) != len(str(right.get("text") or "")):
        return left if len(str(left.get("text") or "")) >= len(str(right.get("text") or "")) else right
    return left


def plan_local_tidy(memories: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a conservative tidy plan without mutating the input.

    The plan contains:
    - ``final_entries``: cleaned memory list ready to save for one owner.
    - ``removed_ids``: IDs removed because they were empty or high-confidence duplicates.
    - ``edited_ids``: IDs whose text/category was lightly cleaned.
    - ``before`` / ``after`` counts.
    """
    cleaned: List[Dict[str, Any]] = []
    removed_ids: set[str] = set()
    edited_ids: set[str] = set()
    exact_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}

    input_rows = [row for row in memories if isinstance(row, dict)]

    for row in input_rows:
        memory = dict(row)
        memory_id = str(memory.get("id") or "")
        text = normalize_memory_text(memory.get("text"))
        category = normalize_memory_text(memory.get("category") or "fact") or "fact"
        if not text:
            if memory_id:
                removed_ids.add(memory_id)
            continue
        if text != memory.get("text") or category != memory.get("category"):
            if memory_id:
                edited_ids.add(memory_id)
        memory["text"] = text
        memory["category"] = category
        key = (category, canonical_memory_text(text))
        existing = exact_by_key.get(key)
        if existing:
            keep = choose_memory_to_keep(existing, memory)
            drop = memory if keep is existing else existing
            if drop.get("id"):
                removed_ids.add(str(drop["id"]))
            exact_by_key[key] = keep
            if keep is memory:
                cleaned = [memory if item is existing else item for item in cleaned]
            continue
        exact_by_key[key] = memory
        cleaned.append(memory)

    # High-confidence near-duplicates only. This intentionally avoids broad
    # semantic merging; if there is any doubt, both facts survive.
    final_entries: List[Dict[str, Any]] = []
    seen: List[Tuple[Dict[str, Any], set[str], str]] = []
    for memory in cleaned:
        if str(memory.get("id") or "") in removed_ids:
            continue
        tokens = _token_set(memory.get("text"))
        canon = _token_key(memory.get("text"))
        duplicate_of = None
        for existing, existing_tokens, existing_canon in seen:
            if existing.get("category") != memory.get("category"):
                continue
            score = _jaccard(tokens, existing_tokens)
            close_subset = len(canon) > 30 and len(existing_canon) > 30 and (
                canon in existing_canon or existing_canon in canon
            )
            if score >= 0.94 or (close_subset and score >= 0.82):
                duplicate_of = existing
                break
        if duplicate_of is None:
            final_entries.append(memory)
            seen.append((memory, tokens, canon))
            continue

        keep = choose_memory_to_keep(duplicate_of, memory)
        drop = memory if keep is duplicate_of else duplicate_of
        if drop.get("id"):
            removed_ids.add(str(drop["id"]))
        if keep is memory:
            final_entries = [memory if item is duplicate_of else item for item in final_entries]
            seen = [
                (memory, tokens, canon) if item[0] is duplicate_of else item
                for item in seen
            ]

    return {
        "before": len(input_rows),
        "after": len(final_entries),
        "final_entries": final_entries,
        "removed_ids": sorted(removed_ids),
        "edited_ids": sorted(edited_ids - removed_ids),
    }


def apply_local_tidy(memory_manager, memory_vector=None, owner: str | None = None) -> Dict[str, Any]:
    """Apply deterministic tidy to one owner, preserving other owners' rows."""
    target_entries = memory_manager.load(owner=owner)
    plan = plan_local_tidy(target_entries)
    before = plan["before"]
    final_entries = plan["final_entries"]

    if owner:
        all_entries = memory_manager.load_all()
        other_entries = [entry for entry in all_entries if entry.get("owner") != owner]
        saved_entries = final_entries + other_entries
    else:
        saved_entries = final_entries

    if plan["removed_ids"] or plan["edited_ids"]:
        memory_manager.save(saved_entries)
        if memory_vector and getattr(memory_vector, "healthy", False):
            memory_vector.rebuild(saved_entries)

    return {
        "before": before,
        "after": len(final_entries),
        "removed": before - len(final_entries),
        "edited": len(plan["edited_ids"]),
        "removed_ids": plan["removed_ids"],
        "edited_ids": plan["edited_ids"],
        "mode": "local",
    }
