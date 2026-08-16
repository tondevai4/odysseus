# core/exceptions.py
"""
Custom exceptions and global self-healing runtime exception handler for YVES.
Captures route crashes and logs self-repair jobs to the repair queue.
"""
import logging
import traceback
import uuid
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class SessionNotFoundError(Exception):
    """Raised when a requested session is not found."""
    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session '{session_id}' not found")


class InvalidFileUploadError(Exception):
    """Raised when a file upload fails validation."""
    def __init__(self, message: str, filename: str = None):
        self.filename = filename
        self.message = message
        super().__init__(message)


class LLMServiceError(Exception):
    """Raised when there is an error communicating with the LLM service."""
    def __init__(self, message: str, endpoint: str = None):
        self.endpoint = endpoint
        self.message = message
        super().__init__(message)


class WebSearchError(Exception):
    """Raised when there is an error with web search functionality."""
    def __init__(self, message: str, query: str = None):
        self.query = query
        self.message = message
        super().__init__(message)


def handle_system_exception(
    endpoint: str,
    method: str,
    exc: Exception,
    stack_trace: Optional[str] = None,
    owner: Optional[str] = None,
) -> Optional[str]:
    """Capture a 500 runtime crash and register an auto-repair job in the database.

    Args:
        endpoint: HTTP path where exception occurred.
        method: HTTP method.
        exc: Exception instance.
        stack_trace: Full error traceback string.
        owner: Optional user identifier.

    Returns:
        The generated repair job ID.
    """
    job_id = f"srj-{uuid.uuid4().hex[:10]}"
    err_type = type(exc).__name__
    trace = stack_trace or traceback.format_exc()

    logger.error(f"[Self-Healing Trap] Caught unhandled exception at {method} {endpoint}: {err_type} - {exc}")

    try:
        from core.database import SessionLocal, SystemRepairJob
        with SessionLocal() as db:
            # Check if pending job already exists for this exact endpoint & error
            existing = db.query(SystemRepairJob).filter(
                SystemRepairJob.endpoint == endpoint,
                SystemRepairJob.error_type == err_type,
                SystemRepairJob.status == "pending",
            ).first()

            if not existing:
                job = SystemRepairJob(
                    id=job_id,
                    endpoint=f"{method} {endpoint}",
                    error_type=err_type,
                    stack_trace=trace,
                    status="pending",
                    owner=owner,
                )
                db.add(job)
                db.commit()
                logger.info(f"Registered new self-repair job '{job_id}' for {method} {endpoint}")
                return job_id
            return existing.id
    except Exception as db_err:
        logger.warning(f"Failed to record SystemRepairJob: {db_err}")
        return None
