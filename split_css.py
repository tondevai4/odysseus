import os
import re

css_path = r"c:\Users\tonde\.gemini\antigravity\scratch\odysseus\static\style.css"
out_dir = r"c:\Users\tonde\.gemini\antigravity\scratch\odysseus\static\css"

os.makedirs(out_dir, exist_ok=True)
os.makedirs(os.path.join(out_dir, "components"), exist_ok=True)

with open(css_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern looks for something like /* ── Section Name ── */
# Let's split by that pattern.
sections = re.split(r'/\*\s*──\s*(.+?)\s*──\s*\*/', content)

# sections[0] is the content before the first header, which contains variables.
files_created = {}
with open(os.path.join(out_dir, "variables.css"), "w", encoding="utf-8") as f:
    f.write("/* ── Variables ── */\n" + sections[0])
files_created[os.path.join(out_dir, "variables.css")] = True

for i in range(1, len(sections), 2):
    header = sections[i].strip()
    section_content = sections[i+1]
    
    # Clean up header to make a filename
    filename = re.sub(r'[^a-z0-9]+', '-', header.lower()).strip('-') + '.css'
    
    if filename in ["variables.css", "reset-base.css", "density-overrides.css", "background-patterns.css", "layout.css"]:
        # Keep these at root css
        out_path = os.path.join(out_dir, filename)
    else:
        # Move to components
        out_path = os.path.join(out_dir, "components", filename)
        
    full_content = f"/* ── {header} ── */\n" + section_content
    
    if out_path in files_created:
        with open(out_path, 'a', encoding='utf-8') as f:
            f.write(full_content)
    else:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(full_content)
        files_created[out_path] = True

print(f"Split style.css into {len(files_created)} files.")

links = []
for f in files_created:
    rel_path = f.replace(r"c:\Users\tonde\.gemini\antigravity\scratch\odysseus", "").replace("\\", "/")
    links.append(f'  <link rel="stylesheet" href="{rel_path}" />')

with open(r"c:\Users\tonde\.gemini\antigravity\scratch\odysseus\css_links.html", "w") as f:
    f.write("\n".join(links))
