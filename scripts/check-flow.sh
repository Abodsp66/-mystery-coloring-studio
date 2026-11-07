#!/usr/bin/env sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
for file in flow-studio/*.mjs; do node --check "$file"; done
python3 - <<'PY'
import hashlib,json,re
from pathlib import Path
from html.parser import HTMLParser
root=Path('flow-studio')
class Assets(HTMLParser):
    def handle_starttag(self,tag,attrs):
        for key,value in attrs:
            if key in ['src','href'] and value and not value.startswith(('#','https:','http:','data:')):
                assert (root/value).exists(),value
Assets().feed((root/'index.html').read_text())
for file in root.glob('*.mjs'):
    for dependency in re.findall(r"(?:from\s+|import\s*)['\"](\.[^'\"]+)['\"]",file.read_text()):
        assert (file.parent/dependency).is_file(),dependency
for file in ['worker.mjs','demo.svg','fonts/FlowSymbols.ttf','fonts/metrics.json','fonts/LICENSE.txt','vendor/jsPDF-LICENSE.txt']:
    assert (root/file).is_file(),file
vendor=json.loads((root/'vendor/manifest.json').read_text())['jspdf']
assert hashlib.sha256((root/'vendor'/vendor['file']).read_bytes()).hexdigest()==vendor['sha256']
for file in ['engine.mjs','raster.mjs','geometry.mjs','color.mjs','worker.mjs','app.mjs']:
    text=(root/file).read_text()
    assert not re.search(r"(?:https?://|importScripts\(|runPython|loadPyodide)",text),file
print('Flow Studio: module syntax, local assets, vendor integrity and independent local engine: passed')
PY
