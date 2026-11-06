"""Native tests of the SAME three Python files loaded by the browser worker.

Fixtures are original geometric images; no reference artwork is used.
Run: python3 -m unittest discover -s tests -p 'test_print_engine.py' -v
"""
import json
from pathlib import Path
import unittest

import numpy as np
from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen

ROOT=Path(__file__).resolve().parents[1]


def engine():
    scope={}
    for file in ['v5-core.py','pipeline.py','print-studio.py']:
        path=ROOT/'dist'/file
        exec(compile(path.read_text(),str(path),'exec'),scope)
    return scope


def glyphs():
    font=TTFont(ROOT/'dist/fonts/StudioDigits.ttf')
    units=font['head'].unitsPerEm;glyphset=font.getGlyphSet();cmap=font.getBestCmap();out={}
    for code in map(str,range(1,49)):
        offset=0;bounds=[]
        for ch in code:
            name=cmap[ord(ch)];pen=BoundsPen(glyphset);glyphset[name].draw(pen)
            a,b,c,d=pen.bounds;bounds.append((a+offset,b,c+offset,d))
            offset+=font['hmtx'][name][0]
        xmin=min(p[0] for p in bounds);xmax=max(p[2] for p in bounds)
        ymin=min(p[1] for p in bounds);ymax=max(p[3] for p in bounds)
        out[code]={'width':(xmax-xmin)/units,'height':(ymax-ymin)/units,
                   'cx':(xmax+xmin)/(2*units),'cy':-(ymax+ymin)/(2*units)}
    return out


def settings(**changes):
    out={'paper':[210,297],'colors':12,'minFont':5,'density':.7,'lineWidth':.16,
         'denoise':False,'cleanEdges':False,'detailBoost':True,'edgeGuard':.3,'seed':99}
    out.update(changes);return out


def run(scope,image,**changes):
    h,w=image.shape[:2]
    return json.loads(scope['run_image'](image.tobytes(),w,h,json.dumps(settings(**changes)),json.dumps(glyphs())))


def solid(size,color=(85,128,160)):
    image=np.zeros((size,size,4),dtype=np.uint8);image[:,:,:3]=color;image[:,:,3]=255
    return image


class PrintEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.e=engine()

    def test_delta_e00_published_pairs(self):
        pairs=[([50,2.6772,-79.7751],[50,0,-82.7485],2.0425),
               ([50,3.1571,-77.2803],[50,0,-82.7485],2.8615),
               ([50,2.8361,-74.0200],[50,0,-82.7485],3.4412),
               ([50,-1.3802,-84.2814],[50,0,-82.7485],1.0000)]
        for a,b,expected in pairs:self.assertAlmostEqual(float(self.e['delta_e00'](a,b)),expected,places=4)

    def test_physical_density_is_independent_of_pixel_resolution(self):
        results=[run(self.e,solid(size),density=.45) for size in [80,160,320]]
        counts=[r['metrics']['cells'] for r in results]
        self.assertGreater(min(counts),10)
        self.assertLessEqual(max(counts)/min(counts),1.10)
        for r in results:
            m=r['metrics'];qa=m['printQA']
            self.assertEqual(qa['status'],'passed')
            self.assertEqual(m['missing'],0)
            self.assertEqual(m['precolored'],0)
            self.assertLess(m['colorGeometryError'],.001)
            self.assertGreaterEqual(m['minimumLabelPt'],5)
            self.assertEqual(m['sourceColorError']['deltaE00P95'],0)
            self.assertTrue(all(c['label']['inkClearanceMM']+.00001 >= .26 for c in r['cells']))

    def test_thin_original_region_is_preserved_and_marked_for_review(self):
        image=solid(160);image[70:71,50:110,:3]=[0,0,0]
        r=run(self.e,image,density=0)
        self.assertEqual(len(r['palette']),2)
        self.assertGreater(r['metrics']['missing'],0)
        self.assertEqual(r['metrics']['printQA']['status'],'review')
        self.assertEqual(r['metrics']['precolored'],0)
        self.assertTrue(any(c['label'] is None for c in r['cells']))
        self.assertLess(r['metrics']['coverageGap'],.001)

    def test_fixed_catalog_colors_and_recode_preserve_geometry(self):
        image=solid(96,(230,50,40));image[:,48:,:3]=[20,80,180]
        catalog=[[220,40,40],[20,80,190],[250,250,240]]
        r=run(self.e,image,fixedPalette=catalog,colors=3,density=0)
        self.assertEqual(r['palette'],catalog)
        before=[c['path'] for c in r['cells']]
        cell=r['cells'][0]
        changed=json.loads(self.e['change_code'](cell['id'],2))
        self.assertEqual([c['path'] for c in changed['cells']],before)
        self.assertEqual(changed['cells'][0]['color'],2)
        self.assertEqual(changed['metrics']['manualCodeChanges'],1)
        self.assertEqual(changed['metrics']['printQA']['status'],'passed')

    def test_invalid_palette_and_print_parameters_are_rejected(self):
        image=solid(16)
        for changes in [{'colors':64},{'minFont':3},{'density':float('nan')},
                        {'fixedPalette':[[0,0,0],[0,0,0]]},{'fixedPalette':[[256,0,0]]},
                        {'paper':[200,200]},{'lineWidth':1}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):run(self.e,image,**changes)

    def test_scan_bins_do_not_erase_a_high_contrast_eye(self):
        image=solid(96,(230,210,180));image[43:53,43:53,:3]=[15,15,15]
        r=run(self.e,image,colors=2,density=0,cleanEdges=True)
        self.assertEqual(len(r['palette']),2)
        self.assertLess(min(sum(c) for c in r['palette']),90)
        self.assertEqual(r['metrics']['sourceComponents'],2)

    def test_scan_cleanup_preserves_single_pixel_black_feature(self):
        image=solid(192,(230,210,180));image[96,96,:3]=[0,0,0]
        r=run(self.e,image,colors=2,density=0,cleanEdges=True)
        self.assertEqual(len(r['palette']),2)
        self.assertEqual(r['metrics']['sourceComponents'],2)
        self.assertGreater(r['metrics']['missing'],0)
        self.assertEqual(r['metrics']['printQA']['status'],'review')

    def test_single_pencil_catalog_is_supported(self):
        r=run(self.e,solid(16),fixedPalette=[[50,100,150]],colors=1,density=0)
        self.assertEqual(r['palette'],[[50,100,150]])

    def test_two_digit_ink_is_not_forced_into_a_one_digit_slot(self):
        image=solid(256);image[100:120,100:102,:3]=[0,0,0]
        middle=[[200+i,60,40] for i in range(10)]
        one=run(self.e,image,fixedPalette=[[0,0,0],[85,128,160]]+middle,colors=12,density=0)
        two=run(self.e,image,fixedPalette=[[85,128,160]]+middle+[[0,0,0]],colors=12,density=0)
        self.assertTrue(next(c for c in one['cells'] if c['color']==0)['label'])
        self.assertIsNone(next(c for c in two['cells'] if c['color']==11)['label'])
        self.assertEqual(two['metrics']['printQA']['status'],'review')
        self.assertEqual(two['metrics']['precolored'],0)

    def test_audit_detects_small_inter_label_gap(self):
        e=engine();e.update(MM=1.,GLYPHS=glyphs())
        label={'x':5.,'y':5.,'pt':5.,'angle':0}
        first={'id':1,'color':0,'poly':e['box'](0,0,20,20),'label':label}
        width=5*25.4/72*glyphs()['1']['width']
        second={'id':2,'color':0,'poly':e['box'](0,0,20,20),
                'label':dict(label,x=5+width+.12)}
        qa=e['print_audit']([first,second],settings())
        self.assertEqual(qa['labelConflictIds'],[1,2])

    def test_same_color_merge_and_undo(self):
        r=run(self.e,solid(48),density=.45)
        before=[c['path'] for c in r['cells']]
        merged=json.loads(self.e['merge_same_color'](r['cells'][0]['id']))
        self.assertEqual(merged['metrics']['cells'],len(before)-1)
        self.assertEqual(merged['metrics']['printQA']['status'],'passed')
        self.assertEqual(merged['metrics']['historyDepth'],1)
        restored=json.loads(self.e['undo_edit']())
        self.assertEqual([c['path'] for c in restored['cells']],before)
        self.assertEqual(restored['metrics']['historyDepth'],0)

    def test_merge_cannot_recolor_a_neighbor(self):
        image=solid(48);image[:,24:,:3]=[230,140,90]
        r=run(self.e,image,density=0,colors=2)
        with self.assertRaises(ValueError):self.e['merge_same_color'](r['cells'][0]['id'])
        self.assertEqual(len(self.e['UNDO']),0)
        self.assertEqual(len(self.e['LAST'][0]),len(r['cells']))


if __name__=='__main__':unittest.main()
