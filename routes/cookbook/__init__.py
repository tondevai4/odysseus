from fastapi import APIRouter

from . import ssh
from . import download
from . import serve
from . import discovery
from . import setup
from . import gpus
from . import process
from . import state
from . import tasks

def setup_cookbook_routes() -> APIRouter:
    router = APIRouter(tags=['cookbook'])
    router.include_router(ssh.router)
    router.include_router(download.router)
    router.include_router(serve.router)
    router.include_router(discovery.router)
    router.include_router(setup.router)
    router.include_router(gpus.router)
    router.include_router(process.router)
    router.include_router(state.router)
    router.include_router(tasks.router)
    return router
