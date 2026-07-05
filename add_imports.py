import os

base_imports = """import asyncio
import collections
import json
import re
import time
import logging
from typing import AsyncGenerator, List, Dict, Optional, Set, Any
from urllib.parse import urlparse

from src.llm_core import stream_llm, stream_llm_with_fallback, _is_ollama_native_url
from src.model_context import estimate_tokens
from src.settings import get_setting
from src.prompt_security import untrusted_context_message
from src.tool_security import blocked_tools_for_owner, plan_mode_disabled_tools
from src.tool_policy import GUIDE_ONLY_DIRECTIVE, ToolPolicy
from src.tool_utils import _truncate, get_mcp_manager
from src.agent_tools import (
    parse_tool_blocks, strip_tool_blocks, execute_tool_block, format_tool_result,
    set_active_document, set_active_model, function_call_to_tool_block,
    FUNCTION_TOOL_SCHEMAS, TOOL_TAGS, ToolBlock, MAX_AGENT_ROUNDS
)

logger = logging.getLogger(__name__)

"""

internal_imports = {
    'prompts': [],
    'utils': [
        "from .prompts import *"
    ],
    'tool_handlers': [
        "from .prompts import *",
        "from .utils import *"
    ],
    'verifier': [
        "from .prompts import *",
        "from .utils import *",
        "from .tool_handlers import *"
    ],
    'streaming': [
        "from .prompts import *",
        "from .utils import *",
        "from .tool_handlers import *",
        "from .verifier import *"
    ]
}

files = ['prompts', 'utils', 'tool_handlers', 'verifier', 'streaming']
for f in files:
    filepath = f"src/agent/{f}.py"
    with open(filepath, 'r', encoding='utf-8') as file:
        content = file.read()
    
    imports_to_add = base_imports + "\n".join(internal_imports[f]) + "\n\n"
    
    with open(filepath, 'w', encoding='utf-8') as file:
        file.write(imports_to_add + content)
        print(f"Added imports to {f}.py")
