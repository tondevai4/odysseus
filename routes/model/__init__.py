from fastapi import APIRouter
from .discovery import setup_discovery_routes
from .management import setup_management_routes
from .models import setup_models_routes
from .config import setup_config_routes
from .tools import setup_tools_routes

def setup_model_routes(model_discovery) -> APIRouter:
    router = APIRouter(tags=["model"])
    
    setup_discovery_routes(router, model_discovery)
    setup_management_routes(router)
    setup_models_routes(router)
    setup_config_routes(router)
    setup_tools_routes(router)
    
    return router
