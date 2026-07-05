"""routes/system_routes.py — Lightweight system/infra API endpoints.

Extracted from app.py. Covers:
  GET /api/version   — app version string
  GET /api/health    — liveness probe
  GET /api/ready     — readiness / integrity probe
  GET /api/runtime   — runtime environment info
  GET /api/generated-image/{filename} — serve generated images

Page routes (SPA deep-links) and the login redirect remain in app.py to
keep the startup logic self-contained.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()


@router.get("/api/version")
async def get_version():
    from core.constants import APP_VERSION
    return {"version": APP_VERSION}


@router.get("/api/health")
async def health_check() -> Dict[str, str]:
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/api/ready")
async def readiness_check() -> JSONResponse:
    """Readiness / integrity self-check — DB, data dir, local-first storage.

    Unlike /api/health (liveness), this returns 503 unless every critical
    subsystem is whole, so an orchestrator can gate traffic on real readiness.
    """
    from src.readiness import check_readiness
    result = check_readiness()
    return JSONResponse(status_code=200 if result.get("ready") else 503, content=result)


@router.get("/api/runtime")
async def runtime_info() -> Dict[str, object]:
    in_docker = os.path.exists("/.dockerenv")
    if not in_docker:
        try:
            with open("/proc/1/cgroup", "r", encoding="utf-8", errors="ignore") as fh:
                cg = fh.read()
            in_docker = any(marker in cg for marker in ("docker", "containerd", "kubepods"))
        except Exception:
            in_docker = False
    ollama_url = (
        os.getenv("OLLAMA_BASE_URL")
        or os.getenv("OLLAMA_URL")
        or ("http://host.docker.internal:11434/v1" if in_docker else "http://127.0.0.1:11434/v1")
    )
    return {
        "in_docker": in_docker,
        "ollama_base_url": ollama_url,
    }


@router.get("/api/generated-image/{filename}")
async def serve_generated_image(filename: str, request: Request):
    """Serve generated images from the data directory with owner-scoped access."""
    from src.generated_images import GENERATED_IMAGE_HEADERS, resolve_generated_image_path
    img_path = resolve_generated_image_path(filename)
    try:
        from src.auth_helpers import get_current_user
        from core.database import SessionLocal as _SL, GalleryImage as _GI
        _user = get_current_user(request)
        if _user:
            _db = _SL()
            try:
                _row = _db.query(_GI).filter(_GI.filename == filename).first()
                # Generated-but-not-yet-imported images have no row → allow.
                # Row with a different owner → 404 (don't confirm existence).
                if _row is not None and _row.owner and _row.owner != _user:
                    raise HTTPException(status_code=404, detail="Image not found")
            finally:
                _db.close()
    except HTTPException:
        raise
    except Exception:
        pass
    ext = filename.rsplit(".", 1)[-1].lower()
    mime = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "gif": "image/gif",
        "mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
        "mkv": "video/x-matroska", "m4v": "video/mp4",
    }.get(ext, "application/octet-stream")
    return FileResponse(
        str(img_path),
        media_type=mime,
        headers=GENERATED_IMAGE_HEADERS,
    )
