
from fastapi import APIRouter
from routes.email_pollers import _start_poller
from routes.email_helpers import _POOL_HOOKS
from .state import _pooled_connect, _pooled_release

from .inbox import router as inbox_router
from .read import router as read_router
from .compose import router as compose_router
from .ai import router as ai_router
from .settings import router as settings_router

def setup_email_routes() -> APIRouter:
    _start_poller()
    
    _POOL_HOOKS["connect"] = _pooled_connect
    _POOL_HOOKS["release"] = _pooled_release

    router = APIRouter(prefix="/api/email", tags=["email"])
    
    router.include_router(inbox_router)
    router.include_router(read_router)
    router.include_router(compose_router)
    router.include_router(ai_router)
    router.include_router(settings_router)
    
    return router
