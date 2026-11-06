#!/usr/bin/env python3
"""Read-only measurements of the five supplied reference pages.

Requires PyMuPDF, numpy, scipy, shapely >= 2, fonttools. No OCR, artwork export,
application imports or application changes. Geometry is an approximation of the
grey PDF stroke centre-lines, not a claim about the publisher's source cells.
Local previews, when requested, must remain outside the repository.
"""
import argparse
from collections import Counter
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import platform

import fitz
import fontTools
from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen
import numpy as np
from scipy import ndimage as ndi
import scipy
import shapely as sh
from shapely.geometry import LineString, Polygon, box
from shapely.ops import polygonize_full

MM = 25.4 / 72
CODES = set('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZØ')
# Crop-relative MuPDF coordinates, points. Vector ROIs come from CADRE/clip
# rectangles. The raster ROI is a manually selected visible frame approximation.
ROI = {
    'Pixar_82.pdf': [(4.0, 2.0, 580.0, 800.0)],
    'Coloriage_6_et_35.pdf': [(10.828, 10.29004, 586.028, 807.65002)] * 2,
    'Coloriage_98_Grands_Classiques_tome_2.pdf': [(29.1443, 31.96503, 592.83337, 813.375)],
    '100_nouveaux_coloriages_myst_res_21.pdf': [(86.7, 62.09894, 640.86603, 846.37897)],
}


def quantiles(values):
    if not len(values):
        return None
    return dict(zip(['min', 'p10', 'p25', 'p50', 'p75', 'p90', 'max'],
                    map(float, np.percentile(values, [0, 10, 25, 50, 75, 90, 100]))))


def mm_rect(rect):
    return [float(v) * MM for v in rect]


def drawing_selected(drawing, roi):
    color = drawing.get('color')
    return ('s' in drawing['type'] and color is not None
            and .55 < np.mean(color) < .86 and max(color) - min(color) < .06
            and (drawing.get('width') or 0) > .2
            and fitz.Rect(drawing['rect']).intersects(fitz.Rect(roi)))


def font_resources(doc, page):
    result, programs = [], {}
    seen = set()
    for xref, ext, kind, name, *_ in page.get_fonts(full=True):
        if xref in seen:
            continue
        seen.add(xref)
        _, _, _, data = doc.extract_font(xref)
        result.append({'xref': xref, 'type': kind, 'extension': ext, 'name': name,
                       'embedded_bytes': len(data), 'subset': '+' in name})
        if ext == 'ttf' and data:
            font = TTFont(io.BytesIO(data))
            programs[name.split('+')[-1]] = font
    return result, programs


def labels_and_legend(page, roi, programs):
    labels, legend, glyph_cache = [], [], {}
    art = box(*roi)
    for span in page.get_texttrace():
        if span.get('opacity', 1) <= 0 or span.get('type') == 3:
            continue
        size = float(span['size'])
        dx, dy = span['dir']
        font = programs.get(span['font'])
        for codepoint, gid, origin, fallback_bbox in span['chars']:
            char = chr(codepoint)
            if char not in CODES or 'Arial' not in span['font']:
                continue
            ox, oy = origin
            if size >= 8 and oy > roi[3]:
                legend.append(char)
            if size >= 8 or not art.covers(sh.Point(ox, oy)):
                continue
            key = (span['font'], gid)
            if font is not None and key not in glyph_cache:
                glyphs = font.getGlyphSet()
                name = font.getGlyphOrder()[gid]
                pen = BoundsPen(glyphs)
                glyphs[name].draw(pen)
                glyph_cache[key] = pen.bounds
            bounds = glyph_cache.get(key)
            if bounds:
                xmin, ymin, xmax, ymax = bounds
                factor = size / font['head'].unitsPerEm
                # Uniform size + the rotation recorded by MuPDF. This ink box
                # is conservative; it is not an outline-to-outline overlap test.
                points = [(ox + (x*dx + y*dy)*factor,
                           oy + (x*dy - y*dx)*factor)
                          for x, y in [(xmin,ymin),(xmax,ymin),(xmax,ymax),(xmin,ymax)]]
                ink = Polygon(points)
                ink_height = (ymax-ymin)*factor*MM
            else:
                ink = box(*fallback_bbox)
                ink_height = (fallback_bbox[3]-fallback_bbox[1])*MM
            labels.append({'code': char, 'point': [float(ox), float(oy)],
                           'size_pt': size, 'ink_height_mm': ink_height,
                           'ink': ink, 'font_bounds': bool(bounds),
                           'direction': [float(dx), float(dy)]})
    return labels, legend


def bezier_points(points, tolerance):
    a, b, c, d = map(np.asarray, points)
    chord = d-a
    length = np.linalg.norm(chord)
    if length < 1e-10:
        deviation = max(np.linalg.norm(b-a), np.linalg.norm(c-a))
    else:
        def cross(vector):
            return abs(chord[0]*vector[1]-chord[1]*vector[0])
        deviation = max(cross(b-a), cross(c-a)) / length
    if deviation <= tolerance:
        return [tuple(a), tuple(d)]
    ab=(a+b)/2;bc=(b+c)/2;cd=(c+d)/2;abc=(ab+bc)/2;bcd=(bc+cd)/2;mid=(abc+bcd)/2
    return bezier_points([a,ab,abc,mid], tolerance)[:-1] + bezier_points([mid,bcd,cd,d], tolerance)


def stroke_lines(drawings, tolerance):
    lines, curves, straights = [], 0, 0
    curve_length = straight_length = 0.
    def add(points):
        if len(points)>1 and len(set(points))>1:
            lines.append(LineString(points))
    for drawing in drawings:
        path=[]
        for item in drawing['items']:
            kind=item[0]
            if kind=='c':
                points=bezier_points([tuple(v) for v in item[1:]], tolerance)
                curves+=1;curve_length+=LineString(points).length
            elif kind=='l':
                points=[tuple(item[1]),tuple(item[2])]
                straights+=1;straight_length+=math.dist(*points)
            elif kind=='re':
                if path:add(path);path=[]
                r=item[1];points=[(r.x0,r.y0),(r.x1,r.y0),(r.x1,r.y1),(r.x0,r.y1),(r.x0,r.y0)]
                add(points);continue
            elif kind=='qu':
                if path:add(path);path=[]
                q=item[1];add([tuple(q.ul),tuple(q.ur),tuple(q.lr),tuple(q.ll),tuple(q.ul)])
                continue
            else:
                raise ValueError('Unsupported PDF path operator: '+kind)
            if path and math.dist(path[-1],points[0]) < 1e-4:
                path.extend(points[1:])
            else:
                if path:add(path)
                path=points
        if path:
            if drawing.get('closePath') and path[-1]!=path[0]:path.append(path[0])
            add(path)
    return lines, {'cubic_operators': curves, 'line_operators': straights,
                   'cubic_arclength_share_excluding_rectangles': curve_length/max(curve_length+straight_length,1e-9)}


def geometry_metrics(drawings, roi, labels, tolerance=.03, grid=.001):
    lines, stats=stroke_lines(drawings,tolerance)
    frame=box(*roi)
    network=sh.union_all(lines,grid_size=grid).intersection(frame)
    # ROI border closes a cropped illustration; intersections/slivers are
    # diagnostic, not silently discarded or presented as authored cells.
    network=sh.union_all([network,frame.boundary],grid_size=grid)
    pieces=list(sh.get_parts(network))
    polygons,cuts,dangles,invalid=polygonize_full(pieces)
    cells=list(polygons.geoms)
    areas=np.array([p.area*MM*MM for p in cells])
    substantial=[p for p in cells if p.area*MM*MM >= .25]
    tree=sh.STRtree(substantial)
    assignments=[[] for _ in substantial]
    unassigned=ambiguous=0
    for i,label in enumerate(labels):
        # Use ink-box centre, not baseline: a baseline can lie outside a thin cell.
        point=label['ink'].centroid
        ids=tree.query(point,predicate='within')
        if len(ids)==1:assignments[int(ids[0])].append(i)
        elif len(ids)==0:unassigned+=1
        else:ambiguous+=1
    codes=[]
    for ids in assignments:
        found={labels[i]['code'] for i in ids}
        codes.append(next(iter(found)) if len(found)==1 else None)
    pair_count=same_pairs=0
    total_shared=same_shared=0.
    for i,poly in enumerate(substantial):
        if codes[i] is None:continue
        for j in tree.query(poly,predicate='intersects'):
            j=int(j)
            if j<=i or codes[j] is None:continue
            length=poly.boundary.intersection(substantial[j].boundary).length
            if length <= .1:continue
            pair_count+=1;total_shared+=length
            if codes[i]==codes[j]:same_pairs+=1;same_shared+=length
    if labels:
        inks=[a['ink'] for a in labels];itree=sh.STRtree(inks)
        overlapping=set();overlap_pairs=0
        for i,ink in enumerate(inks):
            for j in itree.query(ink,predicate='intersects'):
                j=int(j)
                if j>i and ink.intersection(inks[j]).area*MM*MM > .01:
                    overlapping.update([i,j]);overlap_pairs+=1
        clearance=np.array([a.distance(network)*MM for a in inks])
        width=float(np.median([d['width'] for d in drawings]))*MM
        conflicts=clearance < width/2
        outside=sum(not frame.covers(a) for a in inks)
        stats.update({'ink_box_overlap_pairs': overlap_pairs,
                      'labels_in_ink_box_overlap':len(overlapping),
                      'ink_box_overlap_label_pct':100*len(overlapping)/len(labels),
                      'ink_box_outside_roi_count':outside,
                      'ink_box_to_stroke_centre_mm':quantiles(clearance),
                      'ink_box_stroke_conflict_candidates':int(conflicts.sum()),
                      'ink_box_stroke_conflict_candidate_pct':float(100*np.mean(conflicts)),
                      'stroke_conflict_review_examples':[
                          {'code':labels[int(i)]['code'],'baseline_pt':labels[int(i)]['point']}
                          for i in np.flatnonzero(conflicts)[:5]]})
    degrees=Counter()
    for line in pieces:
        if line.geom_type=='LineString':
            points=list(line.coords)
            for x,y in [points[0],points[-1]]:degrees[(round(x/grid),round(y/grid))]+=1
    substantial_areas=areas[areas>=.25]
    stats.update({'flattening_tolerance_pt':tolerance,'snap_grid_pt':grid,
        'faces_all_including_slivers':len(cells),'faces_ge_0_25_mm2':len(substantial),
        'faces_lt_0_25_mm2':int(np.sum(areas<.25)),
        'face_area_mm2_ge_0_25':quantiles(substantial_areas),
        'face_pct_lt_4_mm2_ge_0_25':float(100*np.mean(substantial_areas<4)) if len(substantial_areas) else None,
        'face_pct_gt_100_mm2_ge_0_25':float(100*np.mean(substantial_areas>100)) if len(substantial_areas) else None,
        'area_coverage_fraction':float(sum(p.area for p in cells)/frame.area),
        'cut_length_pt':cuts.length,'dangle_length_pt':dangles.length,'invalid_rings':len(invalid.geoms),
        'labels_not_assigned':unassigned,'labels_ambiguously_assigned':ambiguous,
        'faces_with_no_label':sum(not ids for ids in assignments),
        'faces_with_multiple_labels':sum(len(ids)>1 for ids in assignments),
        'faces_with_mixed_codes':sum(len({labels[i]['code'] for i in ids})>1 for ids in assignments),
        'known_code_adjacent_pairs':pair_count,'same_code_adjacent_pairs':same_pairs,
        'same_code_shared_length_fraction':same_shared/total_shared if total_shared else None,
        'junction_degree_histogram':dict(Counter(degrees.values())),
    })
    return stats


def raster_components(page,roi,roi_source='manual visible raster frame; approximate'):
    pix=page.get_pixmap(matrix=fitz.Matrix(300/72,300/72),colorspace=fitz.csGRAY,clip=fitz.Rect(roi),alpha=False)
    gray=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width)
    output=[]
    for threshold in [205,220,235]:
        # Glyph holes are deliberately not called cells. Report sensitivity and
        # separate the effect of the 1 mm² cutoff; no OCR/inpainting is used.
        foreground=gray < threshold
        regions,count=ndi.label(~foreground)
        border=set(np.unique(np.r_[regions[0],regions[-1],regions[:,0],regions[:,-1]]))
        areas=np.bincount(regions.ravel())*(25.4/300)**2
        interior=np.array([a for i,a in enumerate(areas) if i and i not in border])
        filtered=interior[interior>=1]
        output.append({'threshold':threshold,'components_all_closed':len(interior),
                       'components_ge_1_mm2':len(filtered),'area_mm2_ge_1':quantiles(filtered),
                       'pct_lt_4_mm2_of_components_ge_1':float(100*np.mean(filtered<4)),
                       'pct_gt_100_mm2_of_components_ge_1':float(100*np.mean(filtered>100))})
    # Horizontal/vertical run widths are only an orientation-biased proxy for
    # apparent line width, contaminated by letters and curves, not PDF stroke.
    runs=[]
    for row in gray[::40]:
        z=np.r_[False,row<220,False].astype(np.int8)
        starts=np.flatnonzero(np.diff(z)==1);ends=np.flatnonzero(np.diff(z)==-1)
        runs.extend((ends-starts)[((ends-starts)>=1)&((ends-starts)<=6)].tolist())
    return {'render_dpi':300,'roi_selection':roi_source,
            'threshold_sensitivity':output,
            'short_horizontal_dark_runs_mm':quantiles(np.array(runs)*25.4/300)}


def page_metrics(doc,page,path,index,sensitivity):
    roi=ROI[path.name][index]
    drawings=page.get_drawings()
    fonts,programs=font_resources(doc,page)
    labels,legend=labels_and_legend(page,roi,programs)
    nominal_sizes=[]
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines',[]):
            for span in line['spans']:
                if ('Arial' in span['font'] and span['size']<8
                    and fitz.Rect(roi).contains(fitz.Point(span['origin']))):
                    nominal_sizes.extend([span['size']]*sum(c in CODES for c in span['text']))
    chosen=[d for d in drawings if drawing_selected(d,roi)]
    images=[]
    for image in page.get_image_info(xrefs=True):
        bbox=image['bbox'];transform=image['transform']
        images.append({'xref':image['xref'],'width_px':image['width'],'height_px':image['height'],
                       'bits_per_component':image['bpc'],'color_space':image['cs-name'],'bbox_pt':list(bbox),
                       'filter':doc.xref_get_key(image['xref'],'Filter')[1],
                       'effective_dpi_x':72*image['width']/math.hypot(transform[0],transform[1]),
                       'effective_dpi_y':72*image['height']/math.hypot(transform[2],transform[3])})
    rect=page.rect
    scale=min(210/(rect.width*MM),297/(rect.height*MM))
    safe_scale=min(190/(rect.width*MM),277/(rect.height*MM))
    sizes=nominal_sizes
    rgb_pix=page.get_pixmap(matrix=fitz.Matrix(150/72,150/72),clip=fitz.Rect(roi),colorspace=fitz.csRGB,alpha=False)
    rgb=np.frombuffer(rgb_pix.samples,dtype=np.uint8).reshape(-1,3).astype(np.int16)
    stats={'file':path.name,'page':index+1,'page_count':len(doc),
        'media_box_pt':list(page.mediabox),'crop_box_pt':list(page.cropbox),'trim_box_pt':list(page.trimbox),
        'bleed_box_pt':list(page.bleedbox),'rotation':page.rotation,
        'crop_width_mm':rect.width*MM,'crop_height_mm':rect.height*MM,
        'roi_pt':list(roi),'roi_width_mm':(roi[2]-roi[0])*MM,'roi_height_mm':(roi[3]-roi[1])*MM,
        'art_margins_from_crop_mm':mm_rect([roi[0],roi[1],rect.width-roi[2],rect.height-roi[3]]),
        'a4_fit_whole_crop_scale':scale,'a4_fit_crop_with_10mm_margin_scale':safe_scale,
        'content_type':'raster' if images and not drawings and not fonts else 'vector_with_live_text',
        'drawing_records_raw_not_cells':len(drawings),'path_type_histogram':dict(Counter(d['type'] for d in drawings)),
        'drawing_layer_histogram':dict(Counter(d.get('layer','') for d in drawings)),
        'white_fill_records_by_layer':dict(Counter(d.get('layer','') for d in drawings if d.get('fill') and min(d['fill'])>.98)),
        'nonwhite_fill_records_by_layer':dict(Counter(d.get('layer','') for d in drawings if d.get('fill') and min(d['fill'])<=.98)),
        'visible_chromatic_pixels_pct_at_150dpi':float(100*np.mean((rgb.max(axis=1)-rgb.min(axis=1)>=20)&(rgb.min(axis=1)<245))),
        'fonts':fonts,'images':images,
        'selected_grey_stroke_records':len(chosen),
        'stroke_histogram':[{'width_pt':key[0],'width_mm':key[0]*MM,'rgb':list(key[1]),'layer':key[2],'records':n}
            for key,n in Counter((round(d['width'],6),tuple(round(v,6) for v in d['color']),d.get('layer','')) for d in chosen).most_common()],
        'live_art_label_glyphs':len(labels),'art_code_histogram':dict(sorted(Counter(a['code'] for a in labels).items())),
        'legend_codes_extracted':legend,'legend_unique_codes':len(set(legend)),
        'label_font_size_pt':quantiles(sizes),
        'trace_font_size_pt':quantiles([a['size_pt'] for a in labels]),
        'label_ink_height_mm_uniform_trace_model':quantiles([a['ink_height_mm'] for a in labels]),
        'font_ink_bounds_labels':sum(a['font_bounds'] for a in labels),
        'rotated_labels_count':sum(abs(a['direction'][1])>.001 for a in labels),
        'a4_fit_min_label_pt':min(sizes)*scale if sizes else None,
        'a4_safe_min_label_pt':min(sizes)*safe_scale if sizes else None,
        'art_code_missing_from_legend':sorted({a['code'] for a in labels}-set(legend))}
    if chosen:
        stats['geometry']=geometry_metrics(chosen,roi,labels)
        if sensitivity:
            other=geometry_metrics(chosen,roi,[],tolerance=.015,grid=.001)
            stats['geometry_sensitivity']={k:other[k] for k in ['flattening_tolerance_pt','faces_all_including_slivers','faces_ge_0_25_mm2','face_area_mm2_ge_0_25','area_coverage_fraction','dangle_length_pt']}
        stats['render_components']=raster_components(page,roi,roi_source='PDF CADRE/clip rectangle')
    else:
        stats['raster_analysis']=raster_components(page,roi)
    return stats


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--references',type=Path,default=Path('references'))
    parser.add_argument('--output',type=Path,default=Path('docs'))
    parser.add_argument('--sensitivity',action='store_true',help='Repeat geometry at half the flattening tolerance')
    parser.add_argument('--local-previews',type=Path,help='Private inspection output OUTSIDE the checkout only')
    args=parser.parse_args()
    checkout=Path(__file__).resolve().parents[1]
    if args.local_previews:
        target=args.local_previews.resolve()
        if target.is_relative_to(checkout):
            parser.error('Copyrighted page previews must stay outside the checkout')
        target.mkdir(parents=True,exist_ok=True)
    args.output.mkdir(parents=True,exist_ok=True)
    report={'versions':{'python':platform.python_version(),'pymupdf':fitz.VersionBind,'fonttools':fontTools.__version__,
                        'numpy':np.__version__,'scipy':scipy.__version__,'shapely':sh.__version__},
            'units':{'pdf_points_to_mm':MM,'area_cutoff_mm2':.25},'files':[]}
    expected=set(ROI)
    for name in sorted(expected):
        path=args.references/name
        if not path.is_file():raise FileNotFoundError(path)
        with fitz.open(path) as doc:
            assert len(doc)==len(ROI[name]),f'Changed page inventory: {name}'
            file={'file':name,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                  'page_count':len(doc),'metadata':doc.metadata,'ocgs':doc.get_ocgs(),'pages':[]}
            for index,page in enumerate(doc):
                print(f'Analyzing {name}, PDF page {index+1}',flush=True)
                stats=page_metrics(doc,page,path,index,args.sensitivity)
                file['pages'].append(stats)
                print(f"  labels={stats['live_art_label_glyphs']}, model_faces={stats.get('geometry',{}).get('faces_ge_0_25_mm2','n/a')}",flush=True)
                if args.local_previews:
                    page.get_pixmap(matrix=fitz.Matrix(1.4,1.4),alpha=False).save(str(args.local_previews/f'{path.stem}_p{index+1}.png'))
                    roi=stats['roi_pt'];cx=(roi[0]+roi[2])/2;cy=(roi[1]+roi[3])/2
                    clip=fitz.Rect(cx-36,cy-36,cx+36,cy+36)
                    for factor in [2,4]:
                        page.get_pixmap(matrix=fitz.Matrix(factor,factor),clip=clip,alpha=False).save(str(args.local_previews/f'{path.stem}_p{index+1}_{factor*100}pct.png'))
            report['files'].append(file)
    (args.output/'pdf_reference_metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    fields=['file','pdf_page','page_count','content_type','crop_width_mm','crop_height_mm',
            'raw_drawing_records_not_cells','image_count','embedded_font_count','art_label_glyphs',
            'legend_codes','stroke_mode_mm','font_p50_pt','font_min_pt','a4_fit_scale','a4_fit_min_label_pt',
            'reconstructed_faces_ge_0_25_mm2','faces_p50_mm2','ink_box_overlap_candidate_pct',
            'ink_box_stroke_conflict_candidate_pct','same_code_shared_length_fraction',
            'render_components_ge_1_mm2_min','render_components_ge_1_mm2_max']
    with (args.output/'pdf_reference_metrics.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
        for file in report['files']:
            for p in file['pages']:
                geo=p.get('geometry',{});sizes=p['label_font_size_pt'] or {};areas=geo.get('face_area_mm2_ge_0_25') or {}
                rendered=p.get('render_components',p.get('raster_analysis',{}))['threshold_sensitivity']
                writer.writerow(dict(zip(fields,[file['file'],p['page'],file['page_count'],p['content_type'],
                    round(p['crop_width_mm'],4),round(p['crop_height_mm'],4),p['drawing_records_raw_not_cells'],len(p['images']),sum(a['embedded_bytes']>0 for a in p['fonts']),
                    p['live_art_label_glyphs'],p['legend_unique_codes'] if p['fonts'] else None,round(p['stroke_histogram'][0]['width_mm'],6) if p['stroke_histogram'] else None,
                    sizes.get('p50'),sizes.get('min'),p['a4_fit_whole_crop_scale'],p['a4_fit_min_label_pt'],
                    geo.get('faces_ge_0_25_mm2'),areas.get('p50'),geo.get('ink_box_overlap_label_pct'),geo.get('ink_box_stroke_conflict_candidate_pct'),geo.get('same_code_shared_length_fraction'),
                    min(v['components_ge_1_mm2'] for v in rendered),max(v['components_ge_1_mm2'] for v in rendered)])))
    print('Wrote measured JSON and CSV; no reference images are included in them.',flush=True)


if __name__=='__main__':
    main()
