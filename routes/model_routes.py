"""Backward compatibility shim for model routes.

The monolithic model_routes.py has been refactored into the `routes.model` package.
This file is preserved so that existing imports across the project do not break.
"""

from routes.model import setup_model_routes
from routes.model.shared import _invalidate_models_cache, _visible_models
from routes.model.discovery import _probe_endpoint
from routes.model.config import _load_settings, _normalize_base, build_chat_url

# To aid backward compatibility, we expose the common helpers that were
# identified as being used by other modules like chat_routes.py and copilot_routes.py.
