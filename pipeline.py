"""Browser adapter for the V5 geometric pipeline. No cross-color repair or prefilling."""
def progress(text):
    if 'notify_progress' in globals():notify_progress(text)

@lru_cache(maxsize=24000)
def label_position(poly,max_pt=None,min_pt=None,symbol='D'):
    """Cached, batched ink fitting; geometry and minimum print size are retained."""
    import shapely as sh
    if poly.is_empty or poly.area<.05:return None
    g=GLYPHS[symbol];x0,y0,x1,y1=poly.bounds;em=MIN_PT*25.4/72/MM
    if min(x1-x0,y1-y0)<em*min(g['width'],g['height']) or poly.area<em*em*g['width']*g['height']:return None
    p=polylabel(poly,tolerance=.35);boundary=poly.boundary;clearance=p.distance(boundary)
    sh.prepare(poly)
    for pt in np.arange(MAX_PT,MIN_PT-.01,-.2):
        em=pt*25.4/72/MM;hw=em*g['width']/2+.04/MM;hh=em*g['height']/2+.04/MM
        if poly.covers(box(p.x-hw,p.y-hh,p.x+hw,p.y+hh)):
            return dict(x=p.x,y=p.y,pt=round(float(pt),2),angle=0,clearance=float(clearance))
    step=max(1,math.sqrt((x1-x0)*(y1-y0)/300))
    xx,yy=np.meshgrid(np.arange(x0+.5,x1,step),np.arange(y0+.5,y1,step))
    xy=np.column_stack([xx.ravel(),yy.ravel()]);xy=xy[sh.contains(poly,sh.points(xy))]
    distances=sh.distance(sh.points(xy),boundary)
    xy=xy[np.argsort(-distances,kind='stable')[:45]];xy=np.vstack([[p.x,p.y],xy])
    angles=np.array([0,90,45,-45,*range(-80,90,10)]);a=np.deg2rad(angles)
    rotations=np.array([[np.cos(a),-np.sin(a)],[np.sin(a),np.cos(a)]]).transpose(2,0,1)
    for pt in [v for v in [4.5,4.,3.5,3.] if v>=MIN_PT]:
        em=pt*25.4/72/MM;hw=em*g['width']/2+.025/MM;hh=em*g['height']/2+.025/MM
        corners=np.array([[-hw,-hh],[hw,-hh],[hw,hh],[-hw,hh]])
        rotated=np.einsum('aij,kj->aki',rotations,corners)
        rectangles=sh.polygons((xy[:,None,None,:]+rotated[None,:,:,:]).reshape(-1,4,2))
        hit=np.flatnonzero(sh.covers(poly,rectangles))
        if len(hit):
            qi,ai=divmod(int(hit[0]),len(angles));x,y=xy[qi]
            return dict(x=float(x),y=float(y),pt=pt,angle=int(angles[ai]),clearance=float(Point(x,y).distance(boundary)))
    return None

def rgb_lab(rgb):
    a=rgb.astype(np.float32)/255
    a=np.where(a>.04045,((a+.055)/1.055)**2.4,a/12.92)
    xyz=a@np.array([[.4124564,.2126729,.0193339],[.3575761,.7151522,.1191920],[.1804375,.0721750,.9503041]],np.float32)
    xyz/=np.array([.95047,1,1.08883],np.float32)
    f=np.where(xyz>.008856,np.cbrt(xyz),7.787*xyz+16/116)
    return np.stack([116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])],axis=-1)

def quantize(rgb,k,clean_edges=False,detail_boost=True):
    """Deterministic CIELAB quantization weighted toward small dark features.

    Six-bit-per-channel binning makes palette discovery faster than a unique
    full-resolution RGB sort; the final RGB centroids are computed from the
    source pixels. The feature boost is based on local contrast, not semantics.
    """
    global EDGE_STATS
    EDGE_STATS={'removedPaletteEntries':0,'reassignedPixels':0,'mode':'detail-weighted'}
    raw=rgb.reshape(-1,3)
    codes=((raw[:,0].astype(np.int32)>>2)<<12)|((raw[:,1].astype(np.int32)>>2)<<6)|(raw[:,2].astype(np.int32)>>2)
    count=np.bincount(codes,minlength=64**3)
    bins=np.flatnonzero(count)
    sums=np.stack([np.bincount(codes,weights=raw[:,channel].astype(np.float64),minlength=64**3)[bins] for channel in range(3)],axis=1)
    binned_rgb=sums/count[bins,None]
    centers_lab=rgb_lab(binned_rgb.astype(np.float32))
    weights=count[bins].astype(np.float64)
    if detail_boost:
        lum=rgb_lab(rgb)[...,0]
        surround=ndi.maximum_filter(lum,size=5,mode='nearest')
        dark_detail=np.clip((surround-lum-7)/30,0,1)
        gx=np.zeros_like(lum);gy=np.zeros_like(lum)
        gx[:,1:]=np.abs(lum[:,1:]-lum[:,:-1]);gy[1:,:]=np.abs(lum[1:,:]-lum[:-1,:])
        edge=np.clip((np.maximum(gx,gy)-12)/44,0,1)
        emphasis=(1.+7*dark_detail+2*edge).reshape(-1)
        support=np.bincount(codes,weights=emphasis,minlength=64**3)[bins]
        weights=np.maximum(weights,support)
    k=min(int(k),len(bins));chosen=[int(np.argmax(weights))]
    distance=np.full(len(bins),np.inf,dtype=np.float32)
    # Use weighted, diverse seeds so small dark eyes/eyebrows can survive.
    for _ in range(1,k):
        difference=centers_lab-centers_lab[chosen[-1]]
        distance=np.minimum(distance,np.einsum('ij,ij->i',difference,difference))
        score=distance*np.power(weights,.40)
        score[chosen]=-1
        new=int(np.argmax(score))
        if score[new]<.005:break
        chosen.append(new)
    centers=centers_lab[chosen].copy()
    # Weighted k-means on occupied color bins: far fewer nearest-neighbor queries
    # than repeated full-image (pixels × colors) distance matrices.
    for _ in range(10):
        labels=cKDTree(centers).query(centers_lab)[1]
        total=np.bincount(labels,weights=weights,minlength=len(centers))
        new=centers.copy()
        active=total>0
        for channel in range(3):
            acc=np.bincount(labels,weights=weights*centers_lab[:,channel],minlength=len(centers))
            new[active,channel]=acc[active]/total[active]
        shift=np.linalg.norm(new-centers,axis=1).max()
        centers=new
        if shift<.04:break
    assignments=cKDTree(centers).query(centers_lab)[1]
    lookup=np.zeros(64**3,dtype=np.int32);lookup[bins]=assignments
    ids=lookup[codes];occupied=np.flatnonzero(np.bincount(ids,minlength=len(centers)))
    remap=np.zeros(len(centers),np.int32);remap[occupied]=np.arange(len(occupied))
    ids=remap[ids]
    usage=np.bincount(ids,minlength=len(occupied))
    # Order palette by actual area, not initialization order.
    order=np.argsort(-usage,kind='stable');inverse=np.empty(len(order),dtype=np.int32);inverse[order]=np.arange(len(order))
    ids=inverse[ids]
    palette=np.zeros((len(order),3),dtype=np.uint8)
    totals=np.bincount(ids,minlength=len(order))
    for channel in range(3):
        totals_channel=np.bincount(ids,weights=raw[:,channel],minlength=len(order))
        palette[:,channel]=np.uint8(np.rint(totals_channel/np.maximum(1,totals)))
    return ids.reshape(H,W),palette

def edge_denoise(rgb):
    a=rgb.astype(np.float32)
    for _ in range(2):
        padded=np.pad(a,((1,1),(1,1),(0,0)),mode='edge');total=a.copy();weight=np.ones(a.shape[:2],np.float32)
        for dy,dx in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
            other=padded[1+dy:1+dy+H,1+dx:1+dx+W]
            w=np.exp(-np.sum((other-a)**2,axis=2)/(2*12**2)-(dx*dx+dy*dy)/2)
            total+=other*w[...,None];weight+=w
        a=total/weight[...,None]
    return np.uint8(np.clip(np.rint(a),0,255))

def fast_candidates(c):
    """Minimal legal offsets; expensive GEOS checks only for a small candidate set."""
    import shapely as sh
    poly=c['poly'];old=c['label'];g=GLYPHS[SYMBOLS[c['color']]]
    origin=np.array([old['x'],old['y']]);radius=min(6.,max(2.,1.9/MM))
    offsets=np.array([(0,0),*( (a*radius,b*radius) for a,b in [(-1,0),(1,0),(0,-1),(0,1),(-.7,-.7),(-.7,.7),(.7,-.7),(.7,.7)] ),
                     *( (a*radius*.5,b*radius*.5) for a,b in [(-1,0),(1,0),(0,-1),(0,1)] )],dtype=float)
    positions=origin+offsets
    x0,y0,x1,y1=poly.bounds
    inside=(positions[:,0]>=x0)&(positions[:,0]<=x1)&(positions[:,1]>=y0)&(positions[:,1]<=y1)
    inside[0]=True
    positions=positions[inside]
    points=sh.points(positions);sh.prepare(poly)
    keep=sh.covers(poly,points);keep[0]=True
    positions=positions[keep]
    boundary=poly.boundary
    clear=sh.distance(sh.points(positions),boundary)
    em=old['pt']*25.4/72/MM
    hw=em*g['width']/2+.06/MM;hh=em*g['height']/2+.06/MM
    angle=math.radians(old['angle']);co,si=math.cos(angle),math.sin(angle)
    corners=np.array([[-hw,-hh],[hw,-hh],[hw,hh],[-hw,hh]])@np.array([[co,si],[-si,co]])
    rects=sh.polygons(positions[:,None,:]+corners)
    fit=sh.covers(poly,rects);fit[0]=True
    positions=positions[fit];clear=clear[fit]
    unary=.022*(1-np.minimum(clear/max(clear[0],.01),1))+.002*np.sum((positions-origin)**2,axis=1)/100
    return positions,clear,unary

def spread(cells):
    """Resolve actual code collisions; leave already-separated labels alone."""
    selected=[c for c in cells if c['label']]
    if len(selected)<2:return 0
    xy=np.array([[c['label']['x'],c['label']['y']] for c in selected]);initial=xy.copy()
    colors=np.array([c['color'] for c in selected]);tree=cKDTree(initial)
    same_target=max(3.1/MM,2.2*MIN_PT*25.4/72/MM)
    other_target=max(2.35/MM,1.7*MIN_PT*25.4/72/MM)
    pairs=tree.query_pairs(same_target,output_type='ndarray')
    if not len(pairs):return 0
    distance=np.linalg.norm(xy[pairs[:,0]]-xy[pairs[:,1]],axis=1)
    threshold=np.where(colors[pairs[:,0]]==colors[pairs[:,1]],same_target,other_target)
    crowded=pairs[distance<threshold]
    if not len(crowded):return 0
    active=sorted(set(crowded.ravel().tolist()))
    neighbors={i:np.array([j for j in tree.query_ball_point(initial[i],same_target*3) if j!=i],dtype=int) for i in active}
    candidates={i:fast_candidates(selected[i]) for i in active}
    for sweep in range(3):
        changed=0
        for i in (active if sweep%2==0 else active[::-1]):
            positions,clear,unary=candidates[i];ids=neighbors[i]
            if not len(ids):continue
            distances=np.linalg.norm(positions[:,None,:]-xy[ids][None,:,:],axis=2)
            same=colors[ids]==colors[i];target=np.where(same,same_target,other_target)
            energy=np.sum(np.maximum(0,1-distances/target)**2*np.where(same,3.,1.),axis=1)+unary
            best=int(energy.argmin())
            if np.linalg.norm(positions[best]-xy[i])>.001:
                xy[i]=positions[best];changed+=1
        if not changed:break
    for i,c in enumerate(selected):c['label']['x'],c['label']['y']=map(float,xy[i])
    return int(np.sum(np.linalg.norm(xy-initial,axis=1)>.01))

def serialize_result(cells,palette,settings,metrics,network=None):
    import shapely as sh
    # This is 100x finer than SVG coordinate precision; original cell paths stay intact.
    export_polys=sh.set_precision(np.array([c['poly'] for c in cells],dtype=object),1e-7)
    if network is None:
        progress(f'إخراج {len(cells)} خلية بحدود متجهية مشتركة…')
        net=sh.union_all(sh.boundary(export_polys),grid_size=1e-7)
        if net.geom_type!='LineString':net=linemerge(net)
        progress('كتابة منحنيات SVG…')
        network=line_data(net)
    missing=sum(c['label'] is None for c in cells)
    payload=[]
    for c in cells:
        q=c['poly'].representative_point()
        payload.append({'id':c['id'],'color':int(c['color']),'path':path_data(c['poly']),'label':c['label'],'areaMM2':c['poly'].area*MM*MM,'anchor':[q.x,q.y]})
    metrics.update({'cells':len(cells),'missing':missing,'labeled':len(cells)-missing,'minimumLabelPt':min((c['label']['pt'] for c in cells if c['label']),default=None),'precolored':0})
    def filled_path(g):
        if g.is_empty:return ''
        return path_data(g) if g.geom_type=='Polygon' else ''.join(filled_path(p) for p in g.geoms)
    progress('تجهيز معاينة الحل الملون…')
    solution=[filled_path(sh.union_all(export_polys[np.array([c['color']==i for c in cells])])) for i in range(len(palette))]
    return {'w':W,'h':H,'mm':MM,'palette':palette.tolist(),'cells':payload,'solutionPaths':solution,'network':network,'metrics':metrics,'settings':settings,'glyphs':GLYPHS,'engine':'V5.2-detail-guarded'}

def run_image(raw,width,height,config,glyphs):
    global W,H,MM,MIN_PT,MAX_PT,DENSITY,GLYPHS,LAST,EDGE_GUARD
    start=time.time();W=int(width);H=int(height);GLYPHS=json.loads(glyphs);settings=json.loads(config)
    if W<8 or H<8 or W*H>1100*1100:raise ValueError('أبعاد الصورة خارج حدود المعالجة.')
    pw,ph=settings['paper'];margin=12
    physical_width=min(pw-2*margin,(ph-45)*W/H);MM=physical_width/W
    MIN_PT=float(settings['minFont']);MAX_PT=max(5.5,MIN_PT);DENSITY=float(settings['density']);EDGE_GUARD=float(settings.get('edgeGuard',.32))
    placement.cache_clear();bezier_segments.cache_clear();label_position.cache_clear()
    rgb=np.frombuffer(bytes(raw),dtype=np.uint8).reshape(H,W,4)[...,:3]
    progress('استخراج لوحة الألوان؛ دون حذف المناطق الصغيرة…')
    working=edge_denoise(rgb) if settings.get('denoise',True) else rgb
    labels,palette=quantize(working,int(settings['colors']),settings.get('cleanEdges',False),settings.get('detailBoost',True))
    components=sum(ndi.label(labels==i)[1] for i in range(len(palette)))
    if components>6500:raise ValueError('تفاصيل الصورة تتجاوز قدرة هذه النسخة. جرّب دقة أقل أو عدد ألوان أقل؛ لم تُحذف التفاصيل آليًا.')
    progress('رسم الحدود المشتركة والمنحنيات بأسلوب V5…')
    color_lines=boundary_lines(labels)
    oldw,oldh=W,H;W,H=640,900
    paths=decorative_paths(seed=int(settings.get('seed',99))) if DENSITY>0 else []
    W,H=oldw,oldh
    paths=[scale(p,xfact=W/640,yfact=H/900,origin=(0,0)) for p in paths]
    cells=build_cells(labels,color_lines,paths)
    if len(cells)>12000:raise ValueError('نتجت خلايا كثيرة جدًا. خفّض كثافة التقسيم أو الدقة ثم أعد المحاولة.')
    frozen=[unary_union([c['poly'] for c in cells if c['color']==i]) for i in range(len(palette))]
    progress('معالجة الفواصل الصغيرة داخل اللون نفسه فقط…')
    cells,merged=merge_fragments(cells)
    cells,merged2=reduce_crowding(cells)
    if DENSITY>0:cells,cuts=distribute_large_cells(cells)
    else:cuts=0
    for i,c in enumerate(cells):c['id']=i+1
    progress('توزيع الرموز وفحص اتساعها…')
    spread_start=time.time();moved=spread(cells);spread_seconds=time.time()-spread_start
    progress('التحقق من حفظ حدود الرسم…')
    # Fixed precision on audit copies prevents near-coincident boolean slivers
    # from exploding GEOS overlay work. Output geometry is never rounded here.
    import shapely as sh
    audit_start=time.time();audit_grid=1e-7
    rounded=sh.set_precision(np.array([c['poly'] for c in cells],dtype=object),audit_grid)
    union=sh.union_all(rounded);gap=sh.symmetric_difference(union,box(0,0,W,H),grid_size=audit_grid).area
    errors=[]
    for i,g in enumerate(frozen):
        progress(f'فحص حدود اللون: {i+1} / {len(frozen)}')
        after=sh.union_all(rounded[np.array([c['color']==i for c in cells])])
        before=sh.set_precision(g,audit_grid)
        errors.append(sh.symmetric_difference(before,after,grid_size=audit_grid).area)
    audit_tolerance=max(1e-4,sum(g.length for g in frozen)*audit_grid*2)
    if gap>audit_tolerance or max(errors,default=0)>audit_tolerance:raise ValueError('لم يجتز التقسيم فحص حفظ مناطق الألوان. أعد المحاولة بإعدادات أخرى.')
    audit_seconds=time.time()-audit_start
    metrics={'sameColorMerges':merged+merged2,'balancedCuts':cuts,'labelsMoved':moved,'colorGeometryError':max(errors,default=0),'coverageGap':gap,'sourceComponents':components,'seconds':round(time.time()-start,1),'scope':'Source pixels are quantized to a limited palette. Original class borders are smoothed with bounded displacement; exact photographic identity is not guaranteed. Unlabeled cells remain visible.'}
    metrics['spacingSeconds']=round(spread_seconds,2)
    metrics['auditSeconds']=round(audit_seconds,2)
    metrics['auditGridPixels']=audit_grid
    metrics['edgeCleanup']=dict(EDGE_STATS)
    result=serialize_result(cells,palette,settings,metrics)
    metrics['seconds']=round(time.time()-start,1)
    LAST=(cells,palette,settings,metrics,result['network'])
    return json.dumps(result)

def change_code(cell_id,color):
    if LAST is None:raise ValueError('لا توجد نتيجة قابلة للتعديل.')
    cells,palette,settings,metrics,network=LAST
    if not 0<=int(color)<len(palette):raise ValueError('لون غير صالح.')
    c=next(c for c in cells if c['id']==int(cell_id));c['color']=int(color)
    c['label']=label_position(c['poly'],symbol=SYMBOLS[int(color)])
    metrics['manualCodeChanges']=metrics.get('manualCodeChanges',0)+1
    return json.dumps(serialize_result(cells,palette,settings,metrics,network))
