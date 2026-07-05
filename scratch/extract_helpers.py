import os
import ast

src_dir = r"c:\Users\tonde\.gemini\antigravity\scratch\odysseus\src"
agent_tools_dir = os.path.join(src_dir, "agent_tools")
impls_path = os.path.join(src_dir, "tool_implementations.py")

with open(impls_path, "r", encoding="utf-8") as f:
    content = f.read()

tree = ast.parse(content)

helpers = []
imports = []

for node in tree.body:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        imports.append(ast.get_source_segment(content, node))
    elif isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], "id", "") == "_INTERNAL_BASE":
        helpers.append(ast.get_source_segment(content, node))
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if not node.name.startswith("do_"):
            helpers.append(ast.get_source_segment(content, node))

with open(os.path.join(agent_tools_dir, "tool_helpers.py"), "w", encoding="utf-8") as f:
    f.write("\n".join(imports) + "\n\nlogger = logging.getLogger(__name__)\n\n" + "\n\n".join(helpers) + "\n")

print("Created tool_helpers.py")
