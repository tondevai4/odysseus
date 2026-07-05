import os
import ast

src_dir = r"c:\Users\tonde\.gemini\antigravity\scratch\odysseus\src"
agent_tools_dir = os.path.join(src_dir, "agent_tools")

impls_path = os.path.join(src_dir, "tool_implementations.py")
with open(impls_path, "r", encoding="utf-8") as f:
    impls_content = f.read()

impls_tree = ast.parse(impls_content)

functions = {}
for node in impls_tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name.startswith("do_"):
            tool_name = node.name[3:]
            functions[tool_name] = ast.get_source_segment(impls_content, node)

schemas_path = os.path.join(src_dir, "tool_schemas.py")
with open(schemas_path, "r", encoding="utf-8") as f:
    schemas_content = f.read()
    
schemas_tree = ast.parse(schemas_content)
schemas = {}
for node in schemas_tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], "id", "") == "FUNCTION_TOOL_SCHEMAS":
        for el in node.value.elts:
            if isinstance(el, ast.Dict):
                tool_name = None
                for k, v in zip(el.keys, el.values):
                    if getattr(k, "value", "") == "function" and isinstance(v, ast.Dict):
                        for k2, v2 in zip(v.keys, v.values):
                            if getattr(k2, "value", "") == "name" and isinstance(v2, ast.Constant):
                                tool_name = v2.value
                if tool_name:
                    schemas[tool_name] = ast.get_source_segment(schemas_content, el)

groups = {
    "chat": ["search_chats"],
    "skill": ["manage_skills"],
    "task": ["manage_tasks"],
    "endpoint": ["manage_endpoints", "manage_webhooks", "manage_tokens"],
    "settings": ["manage_settings"],
    "api": ["api_call", "app_api"],
    "note": ["manage_notes"],
    "calendar": ["manage_calendar"],
    "mcp": ["manage_mcp"],
    "cookbook": ["download_model", "serve_model", "list_served_models", "stop_served_model", "tail_serve_output", "list_downloads", "cancel_download", "search_hf_models", "adopt_served_model", "list_cookbook_servers", "list_serve_presets", "serve_preset", "list_cached_models"],
    "image": ["edit_image"],
    "research": ["manage_research", "trigger_research"],
    "contact": ["resolve_contact", "manage_contact"],
    "vault": ["vault_search", "vault_get", "vault_unlock"],
}

for group, tool_names in groups.items():
    file_path = os.path.join(agent_tools_dir, f"{group}_tools.py")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("from typing import Dict, Optional, Any, List\n")
        f.write("import json\nimport asyncio\nimport httpx\nimport os\n")
        f.write("from .tool_helpers import *\n\n")
        f.write("import logging\nlogger = logging.getLogger(__name__)\n\n")
        
        for t in tool_names:
            if t in functions:
                f.write(f"{functions[t]}\n\n")
            if t in schemas:
                f.write(f"{t.upper()}_SCHEMA = {schemas[t]}\n\n")

print("Created new tool files with helper imports.")
