"""从插件页面里抽出 <script> 块做语法检查。

页面的脚本是内联在 index.html 里的，node --check 只能查 .js 文件，
所以先抽出来写到临时文件再查。用法：

    python tools/check-page-js.py [页面路径]
"""
import pathlib
import re
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
page = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'plugins' / 'e5-emulator' / 'index.html'

html = page.read_text(encoding='utf-8')
blocks = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S)
if not blocks:
    print('%s 里没有内联脚本' % page)
    raise SystemExit(1)

tmp = pathlib.Path(tempfile.gettempdir()) / 'e5-page-check.js'
tmp.write_text('\n;\n'.join(blocks), encoding='utf-8')
print('抽出 %d 段脚本，%d 字符 -> %s' % (len(blocks), sum(len(b) for b in blocks), tmp))

proc = subprocess.run(['node', '--check', str(tmp)], capture_output=True, text=True,
                      encoding='utf-8', errors='replace')
if proc.returncode == 0:
    print('语法通过')
    raise SystemExit(0)
print('语法错误：')
print((proc.stderr or proc.stdout)[:2000])
raise SystemExit(proc.returncode)
