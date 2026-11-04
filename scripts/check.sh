#!/usr/bin/env sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
python3 -m py_compile dist/v5-core.py dist/pipeline.py
node --check dist/app.js
node --check dist/worker.js
node --check dist/engine.js
python3 - <<'PY'
from pathlib import Path
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
import zipfile

root = Path('dist')
class LocalAssets(HTMLParser):
    def handle_starttag(self, tag, attributes):
        for name, value in attributes:
            if name in ('src', 'href') and value and not value.startswith(('https:', 'http:', '#', 'data:')):
                assert (root / value).is_file(), f'Missing asset: {value}'

LocalAssets().feed((root / 'index.html').read_text())
with zipfile.ZipFile('Mystery-Coloring-Studio-V5.2.1-Local-Launch.zip') as archive:
    assert archive.testzip() is None, 'Original archive is damaged'
    for name in archive.namelist():
        assert Path(name).exists(), f'Missing original project file: {name}'
    assert (root / 'reference.svg').read_bytes() == archive.read('dist/reference.svg'), 'Reference graphic changed'
assert ET.parse(root / 'reference.svg').getroot().tag == '{http://www.w3.org/2000/svg}svg'
print('Python/JavaScript syntax, original file inventory, HTML assets, archive and reference SVG: passed')
PY
