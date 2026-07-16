import sys, markdown

src, dst, title = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src, encoding="utf-8") as f:
    text = f.read()

body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])

# One font family throughout. The title (h1) gets its own larger size; every
# section heading (h2/h3) shares one header size; everything else (body
# text, list items, table cells, inline code, code blocks) shares one
# paragraph size.
CSS = """
@page { size: A4; margin: 16mm 18mm; }
* { box-sizing: border-box; font-family: Arial, sans-serif; }
body { color: #1a1a1a; line-height: 1.42; font-size: 11px; }
h1 { font-size: 22px; font-weight: bold; margin: 0 0 10px; }
h2, h3 { font-size: 16px; font-weight: bold; margin: 14px 0 6px; }
p, li, td, th, code, pre, blockquote { font-size: 11px; }
p { margin: 5px 0; }
ul { margin: 5px 0 5px 0; padding-left: 20px; }
li { margin: 2px 0; }
pre { border: 1px solid #ddd; border-radius: 4px; padding: 8px 10px; overflow-x: auto; margin: 6px 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; }
th, td { border: 1px solid #aaa; padding: 4px 8px; text-align: left; vertical-align: top; }
blockquote { border-left: 3px solid #bbb; margin: 6px 0; padding: 2px 10px; }
img { max-width: 78%; display: block; margin: 8px auto; }
"""

html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>{title}</title><style>{CSS}</style></head><body>{body}</body></html>"""

with open(dst, "w", encoding="utf-8") as f:
    f.write(html)
print("wrote", dst)
