import os

index_path = r"c:\Users\tonde\.gemini\antigravity\scratch\odysseus\static\index.html"
links_path = r"c:\Users\tonde\.gemini\antigravity\scratch\odysseus\css_links.html"

with open(index_path, "r", encoding="utf-8") as f:
    content = f.read()

with open(links_path, "r", encoding="utf-8") as f:
    links = f.read()

content = content.replace('<link rel="stylesheet" href="/static/style.css">', links)

with open(index_path, "w", encoding="utf-8") as f:
    f.write(content)

print("index.html updated")
