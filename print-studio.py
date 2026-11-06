"""Print-aware operations for V6; executed after the core and pipeline in Pyodide.

All added separators are confined to a single existing color region. Original
thin features may remain unresolved; they are never prefilled or recolored.
"""
import heapq
import copy

LABEL_PAD_MM = .26
EXPORT_GUARD_PX = .02 / MM
EXPORT_SIMPLIFY_PX = .01 / MM
UNDO=[]


def remember_edit():
    cells,palette,settings,metrics,network=LAST
    snapshot=[dict(c,label=dict(c['label']) if c['label'] else None) for c in cells]
    UNDO.append((snapshot,palette.copy(),dict(settings),copy.deepcopy(metrics),network))
    if len(UNDO)>8:UNDO.pop(0)


def undo_edit():
    global LAST
    if not UNDO:raise ValueError('لا يوجد تعديل قابل للتراجع.')
    LAST=UNDO.pop()
    cells,palette,settings,metrics,network=LAST
    return json.dumps(serialize_result(cells,palette,settings,metrics,network))


def merge_same_color(cell_id):
    global LAST
    cells,palette,settings,metrics,network=LAST
    selected=next((c for c in cells if c['id']==int(cell_id)),None)
    if selected is None:raise ValueError('الخلية المحددة غير موجودة.')
    choices=[]
    for other in cells:
        if other is selected or other['color']!=selected['color']:continue
        shared=selected['poly'].boundary.intersection(other['poly'].boundary).length
        if shared<1e-6:continue
        joined=selected['poly'].union(other['poly'])
        if joined.geom_type!='Polygon' or not joined.is_valid:continue
        label=label_position(joined,symbol=SYMBOLS[selected['color']])
        if label is not None:choices.append((shared,other,joined,label))
    if not choices:
        raise ValueError('لا يوجد جار باللون نفسه يتسع لرمز بعد الدمج. تغيير اللون يدويًا يؤثر في الحل؛ راجع المقارنة قبل اعتماده.')
    _,other,joined,label=max(choices,key=lambda value:value[0])
    remember_edit()
    merged=dict(selected,poly=joined,label=label)
    cells=[merged if c is selected else c for c in cells if c is not other]
    metrics=copy.deepcopy(metrics)
    metrics['manualSameColorMerges']=metrics.get('manualSameColorMerges',0)+1
    result=serialize_result(cells,palette,settings,metrics)
    LAST=(cells,palette,settings,metrics,result['network'])
    return json.dumps(result)


def validate_settings(settings):
    paper = settings.get('paper')
    if paper not in ([210,297], [297,210], [297,420], [420,297]):
        raise ValueError('مقاس الورقة غير صالح.')
    colors = settings.get('colors', 18)
    if not isinstance(colors, int) or isinstance(colors, bool) or not 1 <= colors <= 48:
        raise ValueError('اختر من 1 إلى 48 لونًا.')
    for key, low, high, default in [('minFont',4.5,9,5),('density',0,1,.7),('lineWidth',.06,.25,.16)]:
        value=settings.get(key,default)
        if not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError('قيمة غير صالحة في إعدادات الطباعة: '+key)
        settings[key]=float(value)
    palette=settings.get('fixedPalette')
    if palette is not None:
        if not isinstance(palette,list) or not 1<=len(palette)<=48:
            raise ValueError('لوحة الأقلام يجب أن تحتوي على 1–48 لونًا.')
        for color in palette:
            if not isinstance(color,list) or len(color)!=3 or any(type(v) is not int or not 0<=v<=255 for v in color):
                raise ValueError('ألوان لوحة الأقلام غير صالحة.')
        if len({tuple(c) for c in palette})!=len(palette):
            raise ValueError('توجد ألوان مكررة في لوحة الأقلام.')


def restore_edge_classification(rgb,labels,palette):
    """Resolve ambiguous scanner/anti-alias edge pixels from nearby evidence.

    A blend between two source inks can be closest to an unrelated third ink.
    Stable interiors, exact palette matches and dark/white features are anchors.
    Only uncertain pixels within a bounded physical neighbourhood are reassigned.
    This optional scan approximation is included in the measured color error.
    """
    value=rgb.astype(np.int16);support=np.zeros((H,W),np.uint8)
    for dy,dx in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
        neighbor=np.roll(value,(dy,dx),axis=(0,1))
        close=np.max(np.abs(value-neighbor),axis=2)<8
        if dy<0:close[-1]=False
        if dy>0:close[0]=False
        if dx<0:close[:,-1]=False
        if dx>0:close[:,0]=False
        support+=close
    lum=rgb_lab(rgb)[...,0]
    # A narrow component with no stable interior can be a third-palette-color
    # accident along an anti-aliased A/B edge. Require TWO other local colors
    # and an actual RGB blend fit; an isolated real dot in a uniform field is
    # preserved, as are dark details. Never use a generic area-based recolor.
    unsupported=np.zeros((H,W),bool)
    for color in np.unique(labels):
        mask=labels==color;components,_=ndi.label(mask)
        evidence=np.bincount(components.ravel(),weights=(support>=7).ravel())
        unsupported|=mask&(evidence[components]==0)
    candidates=unsupported&(lum>=15)&(lum<=98)
    corrected=labels.copy();best_error=np.full((H,W),np.inf)
    neighbors=[np.roll(labels,offset,axis=(0,1)) for offset in [(0,-1),(0,1),(-1,0),(1,0)]]
    for i in range(4):
        for j in range(i+1,4):
            a,b=neighbors[i],neighbors[j]
            eligible=candidates&(a!=labels)&(b!=labels)&(a!=b)
            eligible[[0,-1],:]=False;eligible[:,[0,-1]]=False
            if not np.any(eligible):continue
            rows,cols=np.nonzero(eligible)
            av=palette[a[rows,cols]].astype(float);bv=palette[b[rows,cols]].astype(float)
            vector=bv-av;raw=value[rows,cols].astype(float)
            t=np.sum((raw-av)*vector,axis=1)/np.maximum(np.sum(vector*vector,axis=1),1)
            error=np.max(np.abs(raw-(av+t[:,None]*vector)),axis=1)
            valid=(t>.05)&(t<.95)&(error<6)&(error<best_error[rows,cols])
            rr,cc=rows[valid],cols[valid]
            corrected[rr,cc]=np.where(t[valid]<.5,a[rr,cc],b[rr,cc])
            best_error[rr,cc]=error[valid]
    error=np.max(np.abs(value-palette[corrected].astype(np.int16)),axis=2)
    anchors=(support>=7)|(error<=3)|(lum<15)|(lum>98)
    if not np.any(anchors):return labels
    distance,indices=ndi.distance_transform_edt(~anchors,return_indices=True)
    candidates=(~anchors)&(distance<=min(2.5,.6/MM))
    out=corrected.copy();out[candidates]=corrected[tuple(axis[candidates] for axis in indices)]
    EDGE_STATS['reassignedPixels']=int(np.sum(out!=labels))
    EDGE_STATS['maximumAnchorSearchMM']=.6
    EDGE_STATS['mode']+='-spatial-anchors'
    return out


def physical_cells(cells, settings):
    """Adaptive curved bisection with legal labels on BOTH children, in mm.

    Failed candidates leave the original region intact. No global cut crosses
    a narrow feature merely to reach a requested cell count.
    """
    density=settings['density']
    for c in cells:
        c['label']=label_position(c['poly'],symbol=SYMBOLS[c['color']])
    if density==0:return cells,0
    target=88-(density-.45)/.55*54
    target=max(34.,min(88.,target))
    minimum=max(6.,target*.13)
    queue=[];serial=0;out=[];cuts=0
    for c in cells:
        heapq.heappush(queue,(-c['poly'].area*MM*MM,serial,c));serial+=1
    while queue:
        _,_,c=heapq.heappop(queue);poly=c['poly'];area=poly.area*MM*MM
        if area<=target or c['label'] is None or cuts>=2200:
            out.append(c);continue
        cx,cy=c['label']['x']*MM,c['label']['y']*MM
        phase=(cx/23+cy/31+int(settings.get('seed',99))*.13)%(2*math.pi)
        angle0=math.atan2(math.sin(cy/27+phase),math.cos(cx/34-phase))
        # Prefer crossing the long axis: area balance alone can repeatedly
        # produce long wedges. Near-square cells keep the smooth direction field.
        rectangle=np.asarray(poly.minimum_rotated_rectangle.exterior.coords)[:4]*MM
        edges=np.roll(rectangle,-1,axis=0)-rectangle
        lengths=np.linalg.norm(edges,axis=1)
        if max(lengths)>1.4*min(lengths):
            long_axis=edges[int(np.argmax(lengths))]
            angle0=math.atan2(long_axis[1],long_axis[0])+math.pi/2+.25*math.sin(phase)
        x0,y0,x1,y1=poly.bounds
        span=math.hypot(x1-x0,y1-y0)*MM*1.3
        # Sample in physical units inside THIS region. A page-wide sample grid
        # made small separators almost straight even when their route was curved.
        travel=np.linspace(-span,span,max(33,min(513,int(2*span/.5)+1)))
        wave_size=min(13.,max(3.,math.sqrt(area)*.45))
        best=None
        for offset in [0.,math.sqrt(area)*.18,-math.sqrt(area)*.18]:
            for delta in [0,math.pi/6,-math.pi/6,math.pi/2]:
                angle=angle0+delta
                axis=np.array([math.cos(angle),math.sin(angle)])
                normal=np.array([-axis[1],axis[0]])
                bend=wave_size*.32*(np.sin(travel/(wave_size*.65)+phase)-math.sin(phase))+offset
                points=(np.array([cx,cy])+travel[:,None]*axis+bend[:,None]*normal)/MM
                pieces=list(split(poly,LineString(points)).geoms)
                if not 2<=len(pieces)<=4 or any(p.geom_type!='Polygon' or not p.is_valid for p in pieces):continue
                areas=[p.area*MM*MM for p in pieces]
                if min(areas)<minimum or min(areas)/area<.12:continue
                labels=[label_position(p,symbol=SYMBOLS[c['color']]) for p in pieces]
                if any(p is None for p in labels):continue
                score=min(areas)/area
                if best is None or score>best[0]:best=(score,pieces,labels)
                if score>.43:break
            if best is not None and best[0]>.43:break
        if best is None:
            out.append(c);continue
        for p,lab in zip(best[1],best[2]):
            heapq.heappush(queue,(-p.area*MM*MM,serial,{'poly':p,'color':c['color'],'label':lab}));serial+=1
        cuts+=1
        if cuts%100==0:progress(f'تقسيم مدرك للطباعة: {cuts} فاصل، مع فحص اتساع الرموز…')
    return out,cuts


def ink_rectangle(cell):
    lab=cell['label'];g=GLYPHS[SYMBOLS[cell['color']]]
    em=lab['pt']*25.4/72/MM
    rect=box(lab['x']-em*g['width']/2,lab['y']-em*g['height']/2,
             lab['x']+em*g['width']/2,lab['y']+em*g['height']/2)
    return rotate(rect,lab['angle'],origin=(lab['x'],lab['y']))


def print_audit(cells,settings):
    import shapely as sh
    indexed=[c for c in cells if c['label'] is not None]
    inks=[ink_rectangle(c) for c in indexed]
    collision_ids=set();outside=[];clearances=[]
    allowance=.03+.001*MM
    required=settings['lineWidth']/2+.15+allowance
    for c,ink in zip(indexed,inks):
        clearance=ink.distance(c['poly'].boundary)*MM if c['poly'].covers(ink) else 0.
        c['label']['inkClearanceMM']=float(clearance)
        clearances.append(clearance)
        if clearance+1e-5<required:outside.append(c['id'])
    if inks:
        tree=sh.STRtree(inks)
        for i,ink in enumerate(inks):
            for j in tree.query(ink.buffer(.15/MM),predicate='intersects'):
                j=int(j)
                if j>i and ink.distance(inks[j])*MM < .15-1e-5:
                    collision_ids.update([indexed[i]['id'],indexed[j]['id']])
    minimum=min(clearances,default=0.)
    missing=[c['id'] for c in cells if c['label'] is None]
    return {'status':'passed' if not missing and not outside and not collision_ids else 'review',
            'missingIds':missing,'strokeConflictIds':outside,'labelConflictIds':sorted(collision_ids),
            'minimumInkClearanceMM':float(minimum),'requiredGapMM':.15,'exportAllowanceMM':allowance,
            'maximumSafeStrokeMM':max(0.,float(2*(minimum-.15-allowance))),
            'lineWidthMM':settings['lineWidth'],'minimumFontPt':settings['minFont'],
            'scope':'Geometry and label fit only; visual mystery, physical pencil colors and paper printing require review.'}


def delta_e00(lab1,lab2):
    """CIEDE2000, kL=kC=kH=1, vectorized; validated with published pairs."""
    L1,a1,b1=np.moveaxis(np.asarray(lab1,dtype=float),-1,0)
    L2,a2,b2=np.moveaxis(np.asarray(lab2,dtype=float),-1,0)
    C1=np.hypot(a1,b1);C2=np.hypot(a2,b2);mean=(C1+C2)/2
    G=.5*(1-np.sqrt(mean**7/(mean**7+25**7)))
    ap1=(1+G)*a1;ap2=(1+G)*a2
    cp1=np.hypot(ap1,b1);cp2=np.hypot(ap2,b2)
    hp1=np.degrees(np.arctan2(b1,ap1))%360;hp2=np.degrees(np.arctan2(b2,ap2))%360
    dh=hp2-hp1;dh=np.where(dh>180,dh-360,np.where(dh < -180,dh+360,dh))
    dh=np.where(cp1*cp2==0,0,dh)
    dH=2*np.sqrt(cp1*cp2)*np.sin(np.radians(dh/2))
    meanL=(L1+L2)/2;meanC=(cp1+cp2)/2
    meanH=np.where(np.abs(hp1-hp2)<=180,(hp1+hp2)/2,
          np.where(hp1+hp2<360,(hp1+hp2+360)/2,(hp1+hp2-360)/2))
    meanH=np.where(cp1*cp2==0,hp1+hp2,meanH)
    T=1-.17*np.cos(np.radians(meanH-30))+.24*np.cos(np.radians(2*meanH))+.32*np.cos(np.radians(3*meanH+6))-.20*np.cos(np.radians(4*meanH-63))
    SL=1+.015*(meanL-50)**2/np.sqrt(20+(meanL-50)**2)
    SC=1+.045*meanC;SH=1+.015*meanC*T
    RT=-2*np.sqrt(meanC**7/(meanC**7+25**7))*np.sin(np.radians(60*np.exp(-((meanH-275)/25)**2)))
    x=(L2-L1)/SL;y=(cp2-cp1)/SC;z=dH/SH
    return np.sqrt(np.maximum(0,x*x+y*y+z*z+RT*y*z))


def color_audit(rgb,labels,palette):
    step=max(1,math.ceil(W*H/16384))
    original=rgb.reshape(-1,3)[::step]
    reduced=palette[labels.reshape(-1)[::step]]
    differences=delta_e00(rgb_lab(original),rgb_lab(reduced))
    return {'deltaE00Median':round(float(np.median(differences)),3),
            'deltaE00P95':round(float(np.percentile(differences,95)),3),
            'deltaE00P99':round(float(np.percentile(differences,99)),3),
            'sampledPixels':len(original),'stage':'Input RGB versus cleaned/quantized palette, before contour smoothing/export'}
