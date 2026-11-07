"""Package the independent static app, including its local Windows launcher."""
import argparse,hashlib,json,subprocess,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,default=root/'test-results'/'Flow-Studio-1.0.zip')
args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
files=[p for p in sorted((root/'flow-studio').rglob('*')) if p.is_file() and '__pycache__' not in p.parts]
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
metadata={'application':'Flow Studio 1.0','repositoryCommit':commit,
    'files':{str(p.relative_to(root/'flow-studio')):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
with zipfile.ZipFile(args.output,'w',zipfile.ZIP_DEFLATED) as archive:
    for path in files:archive.write(path,'Flow-Studio/'+str(path.relative_to(root/'flow-studio')))
    archive.writestr('Flow-Studio/BUILD_SOURCE.json',json.dumps(metadata,indent=2)+'\n')
with zipfile.ZipFile(args.output) as archive:
    assert archive.testzip() is None
    for file in ['index.html','worker.mjs','engine.mjs','fonts/FlowSymbols.ttf','vendor/jspdf.umd.min.js']:
        assert 'Flow-Studio/'+file in archive.namelist()
print(args.output)
