import ast
import re

def get_ast_nodes(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()
    tree = ast.parse(source)
    
    nodes = []
    for node in tree.body:
        name = ""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    name = t.id
                    break
        elif isinstance(node, ast.Import):
            name = "import_" + "_".join(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = "from_" + node.module.replace('.', '_')
        
        nodes.append({
            'name': name,
            'node': node,
            'start': getattr(node, 'lineno', -1),
            'end': getattr(node, 'end_lineno', -1)
        })
    return nodes, source.split('\n')

nodes, lines = get_ast_nodes('src/agent/loop.py')

# Map elements to files
mapping = {
    'prompts': [
        '_AGENT_PREAMBLE', '_AGENT_RULES', '_API_AGENT_RULES', '_LINK_RULES', 
        '_DOMAIN_RULES', '_DOMAIN_TOOL_MAP', '_domain_rules_for_tools', 
        'TOOL_SECTIONS', 'get_builtin_overrides', '_section_text', 
        '_assemble_prompt', 'AGENT_SYSTEM_PROMPT', '_cached_base_prompt', 
        '_cached_base_prompt_key', 'PLAN_MODE_DIRECTIVE', 'build_active_plan_note'
    ],
    'utils': [
        '_load_mcp_disabled_map', '_API_HOSTS', '_MCP_KEYWORDS', '_ADMIN_SCHEMA_NAMES', 
        '_TOOL_SELECTION_TIMEOUT_SECONDS', '_is_ollama_openai_compat_url', 
        '_endpoint_lookup_keys', '_ADMIN_KEYWORDS', '_detect_admin_intent', 
        '_extract_last_user_message', '_LOW_SIGNAL_RE', '_EXPLICIT_CONTINUATION_RE', 
        '_is_explicit_continuation', '_assistant_requested_followup', 
        '_classify_agent_request', '_recent_context_for_retrieval', 
        '_build_system_prompt', '_ADMIN_TOOLS', '_build_base_prompt'
    ],
    'tool_handlers': [
        '_resolve_tool_blocks', '_append_tool_results', '_compute_final_metrics', 
        '_empty_response_fallback', '_detect_runaway_call'
    ],
    'verifier': [
        '_VERIFIER_EFFECTFUL_TOOLS', '_VERIFIER_MAX_ROUNDS', '_build_actions_snapshot', 
        '_run_verifier_subagent'
    ],
    'streaming': [
        'stream_agent_loop'
    ]
}

# Invert mapping
node_to_file = {}
for file, items in mapping.items():
    for item in items:
        node_to_file[item] = file

# Extract lines for each file
file_lines = {
    'prompts': [],
    'utils': [],
    'tool_handlers': [],
    'verifier': [],
    'streaming': []
}

current_line_idx = 0
for i, node in enumerate(nodes):
    start_idx = node['start'] - 1
    end_idx = node['end']
    
    # We want to include preceding comments/blank lines
    if i > 0:
        prev_end_idx = nodes[i-1]['end']
        start_idx = prev_end_idx
    else:
        start_idx = 0 # include everything up to first node
        
    chunk_lines = lines[start_idx:end_idx]
    
    target_file = node_to_file.get(node['name'])
    if target_file:
        file_lines[target_file].extend(chunk_lines)

# Write to disk
import os
os.makedirs('src/agent', exist_ok=True)
for f, file_content in file_lines.items():
    with open(f'src/agent/{f}.py', 'w', encoding='utf-8') as out:
        out.write('\n'.join(file_content))
        print(f"Wrote {f}.py ({len(file_content)} lines)")
