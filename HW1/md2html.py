import sys, markdown

src, dst, title = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src, encoding="utf-8") as f:
    text = f.read()

body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])

CSS = """
@page { size: A4; margin: 16mm 18mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Arial, sans-serif; color: #1a1a1a;
       line-height: 1.42; font-size: 11.2px; }
h1 { font-size: 20px; margin: 0 0 10px; border-bottom: 2px solid #333; padding-bottom: 4px; }
h2 { font-size: 15px; margin: 16px 0 6px; color: #14243f; border-bottom: 1px solid #ccc; padding-bottom: 2px; }
h3 { font-size: 13px; margin: 12px 0 4px; }
p { margin: 5px 0; }
ul { margin: 5px 0 5px 0; padding-left: 20px; }
li { margin: 2px 0; }
code { font-family: Consolas, "Courier New", monospace; background: #f2f2f2;
       padding: 1px 4px; border-radius: 3px; font-size: 10.2px; }
pre { background: #f6f8fa; border: 1px solid #ddd; border-radius: 4px;
      padding: 8px 10px; overflow-x: auto; margin: 6px 0; }
pre code { background: none; padding: 0; font-size: 10px; line-height: 1.35; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 10.4px; }
th, td { border: 1px solid #aaa; padding: 4px 8px; text-align: left; vertical-align: top; }
th { background: #eef1f5; }
blockquote { border-left: 3px solid #bbb; margin: 6px 0; padding: 2px 10px; color: #444; }
strong { color: #111; }
hr { border: none; border-top: 1px solid #ccc; margin: 12px 0; }
"""

html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>{title}</title><style>{CSS}</style></head><body>{body}</body></html>"""

with open(dst, "w", encoding="utf-8") as f:
    f.write(html)
print("wrote", dst)
