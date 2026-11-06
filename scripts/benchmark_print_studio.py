#!/usr/bin/env python3
"""Compare V6 with a local historical commit on ORIGINAL, repeatable SVGs.

Optional native-development dependencies: requirements-engine-test.txt.
No reference PDF artwork, external images or mocked engine outputs are used.
"""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

import fitz
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_print_engine import engine, glyphs, settings


def summary(result):
    m=result['metrics'];qa=m['printQA']
    return {'cells':m['cells'],'unnumbered':m['missing'],'colors':len(result['palette']),
        'sourceComponents':m['sourceComponents'],'seconds':m['seconds'],
        'strokeConflicts':len(qa['strokeConflictIds']),'labelConflicts':len(qa['labelConflictIds']),
        'printStatus':qa['status'],'sourceColorError':m['sourceColorError'],
        'coverageGapPixels2':m['coverageGap'],'colorGeometryErrorPixels2':m['colorGeometryError'],
        'balancedCuts':m['balancedCuts'],'unresolvedBeforeSplitting':m.get('unresolvedBeforeSplitting')}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'test-results'/'benchmark')
    p.add_argument('--baseline',default='6798673')
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    report={'baselineCommit':args.baseline,'fixtureLicense':'Original project artwork, CC0',
            'inputRasterSize':[512,672],'config':settings(cleanEdges=True,denoise=True,colors=18),
            'nativeEngineSHA256':{name:hashlib.sha256((ROOT/'dist'/name).read_bytes()).hexdigest()
                for name in ['v5-core.py','pipeline.py','print-studio.py']},'fixtures':[]}
    for name in ['original-attic','original-courtyard']:
        path=ROOT/'tests'/'fixtures'/(name+'.svg')
        # Exact integer canvas, same aspect ratio: avoid a fractional white
        # overscan column being mistaken for a real color in the source artwork.
        source=path.read_text().replace('width="640" height="840"','width="512" height="672"',1)
        document=fitz.open(stream=source.encode(),filetype='svg')
        pix=document[0].get_pixmap(alpha=True)
        rgba=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,4).copy()
        assert rgba.shape==(672,512,4) and np.all(rgba[:,:,3]==255)
        pix.save(str(args.output/(name+'.png')))
        e=engine();cfg=json.dumps(settings(cleanEdges=True,denoise=True,colors=18));font=json.dumps(glyphs())
        print('V6:',name,flush=True)
        current=json.loads(e['run_image'](rgba.tobytes(),512,672,cfg,font))
        entry={'fixture':name,'sourceSHA256':hashlib.sha256(path.read_bytes()).hexdigest(),'v6':summary(current)}
        old={};captured={}
        for file in ['v5-core.py','pipeline.py']:
            code=subprocess.check_output(['git','show',f'{args.baseline}:dist/{file}'],cwd=ROOT).decode()
            exec(compile(code,f'{args.baseline}/{file}','exec'),old)
        quantize=old['quantize']
        def record_quantize(*a,**kw):
            labels,palette=quantize(*a,**kw)
            captured.update(labels=labels.copy(),palette=palette.copy())
            return labels,palette
        old['quantize']=record_quantize
        print('Baseline:',name,flush=True)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                previous=json.loads(old['run_image'](rgba.tobytes(),512,672,cfg,font))
            e.update(W=512,H=672,MM=old['MM'],GLYPHS=old['GLYPHS'])
            previous['metrics']['printQA']=e['print_audit'](old['LAST'][0],settings())
            previous['metrics']['sourceColorError']=e['color_audit'](rgba[:,:,:3],captured['labels'],captured['palette'])
            entry['baseline']=summary(previous)
        except Exception as error:
            entry['baseline']={'status':'failed','error':str(error)}
        report['fixtures'].append(entry)
        print(json.dumps(entry,ensure_ascii=False),flush=True)
    (args.output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
