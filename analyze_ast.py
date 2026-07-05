import ast

def analyze(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    tree = ast.parse(content)
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
            name = ", ".join(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = f"{node.module} ({', '.join(alias.name for alias in node.names)})"
        
        node_type = type(node).__name__
        start = getattr(node, 'lineno', -1)
        end = getattr(node, 'end_lineno', -1)
        
        print(f"{node_type:<15} | {start:>5}-{end:<5} | {name}")

analyze('src/agent/loop.py')
