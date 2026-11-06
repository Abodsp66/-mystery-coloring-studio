import json,math,time
from functools import lru_cache
import numpy as np
from scipy import ndimage as ndi
from scipy.interpolate import CubicSpline
from scipy.spatial import cKDTree
from shapely.geometry import LineString,Polygon,box,Point
from shapely.ops import unary_union,polygonize,polylabel,linemerge,split
from shapely.strtree import STRtree
from shapely.affinity import rotate,scale
W,H=640,900
MM=273/640
WHITE=-1
MIN_PT=4.0
MAX_PT=5.5
DENSITY=1.0
EDGE_GUARD=.32
SYMBOLS=[str(i) for i in range(1,65)]
GLYPHS={}
LAST=None
def boundary_lines(labels):
    """Create common boundaries once, with bounded, detail-safe vector smoothing.

    Smooth printing is distinct from modifying the classified colors.  Every
    junction remains fixed, and no non-junction vertex may move more than
    EDGE_GUARD work pixels.  Tiny islands and short high-curvature paths stay
    exactly where the source classification puts them.
    """
    edges=[];adj={};stride=W+1
    def add(a,b):
        i=len(edges);edges.append((a,b));adj.setdefault(a,[]).append(i);adj.setdefault(b,[]).append(i)
    for y in range(H+1):
        xs=range(W) if y in (0,H) else np.flatnonzero(labels[y-1]!=labels[y])
        for x in xs:add(int(y*stride+x),int(y*stride+x+1))
    for x in range(W+1):
        ys=range(H) if x in (0,W) else np.flatnonzero(labels[:,x-1]!=labels[:,x])
        for y in ys:add(int(y*stride+x),int((y+1)*stride+x))
    seen=set();lines=[]
    def walk(start,eid):
        nodes=[start];v=start
        while eid not in seen:
            seen.add(eid);a,b=edges[eid];v=b if a==v else a;nodes.append(v)
            if len(adj[v])!=2:break
            nxt=[e for e in adj[v] if e not in seen]
            if not nxt:break
            eid=nxt[0]
        pts=np.array([(n%stride,n//stride) for n in nodes],dtype=np.float64)
        if len(pts)<2:return None
        closed=np.array_equal(pts[0],pts[-1]);length=len(pts)-1
        on_frame=np.all((pts[:,0]==0)|(pts[:,0]==W)|(pts[:,1]==0)|(pts[:,1]==H))
        # Never blur a 1-4 px eye glint, eyebrow notch, finger gap, or thin island.
        if length>=22 and not on_frame:
            base=pts[:-1] if closed else pts
            smooth=ndi.gaussian_filter1d(base,sigma=.90,axis=0,mode='wrap' if closed else 'nearest')
            if closed:smooth=np.vstack([smooth,smooth[0]])
            else:
                smooth[0]=pts[0];smooth[-1]=pts[-1]
            move=smooth-pts
            magnitude=np.linalg.norm(move,axis=1)
            guard=EDGE_GUARD*(.60 if length<44 else 1.)
            factor=np.minimum(1.,guard/np.maximum(magnitude,1e-12))
            pts=pts+move*factor[:,None]
            if closed:pts[-1]=pts[0]
            else:pts[0]=base[0];pts[-1]=base[-1]
            # Small guarded displacements prevent contours from jumping over a
            # neighboring one-pixel structure.  Do not fit a new free spline here.
            pts[:,0]=np.clip(pts[:,0],0,W)
            pts[:,1]=np.clip(pts[:,1],0,H)
        line=LineString(pts)
        if not line.is_simple:
            line=LineString(np.array([(n%stride,n//stride) for n in nodes],dtype=float))
        return line.simplify(.016,preserve_topology=True)
    for v,es in adj.items():
        if len(es)!=2:
            for eid in es:
                if eid not in seen:
                    line=walk(v,eid)
                    if line is not None:lines.append(line)
    for eid,(a,b) in enumerate(edges):
        if eid not in seen:
            line=walk(a,eid)
            if line is not None:lines.append(line)
    return lines

def decorative_paths(seed=99):
    """Long nonperiodic spline cuts plus a few extended diagonals and curls."""
    rng=np.random.default_rng(seed); paths=[]
    # Unequal spacing, independently perturbed control points; no rectangular tiles.
    for horizontal,count in [(True,max(3,round(22*DENSITY))),(False,max(3,round(15*DENSITY)))]:
        span=W if horizontal else H; cross=H if horizontal else W
        positions=np.linspace(0,cross,count+2)[1:-1]+rng.normal(0,8,count)
        for j,base in enumerate(positions):
            ts=np.linspace(-35,span+35,7)
            amplitude=rng.uniform(18,48)
            vals=base+rng.normal(0,amplitude,7)
            spline=CubicSpline(ts,vals,bc_type='natural')
            tt=np.linspace(-35,span+35,550)
            if j%2==0:
                wave=tt/rng.uniform(11,19)+rng.uniform(0,6)
                travel=tt+rng.uniform(16,28)*np.sin(wave)
                lateral=spline(tt)*.35+base*.65+rng.uniform(20,34)*np.cos(wave)
            else:
                travel=tt;lateral=spline(tt)
            pts=np.column_stack([travel,lateral]) if horizontal else np.column_stack([lateral,travel])
            paths.append(LineString(pts))
    # Long oblique routes interrupt any remaining row/column rhythm.
    for offset in np.linspace(-H*.65,H*.85,max(2,round(10*DENSITY))):
        xs=np.linspace(-40,W+40,250)
        ys=.78*xs+offset+22*np.sin(xs/130+rng.uniform(0,6))
        paths.append(LineString(np.column_stack([xs,ys])))
    # A small number of non-circular ornamental closed paths.
    for _ in range(max(2,round(14*DENSITY))):
        cx,cy=rng.uniform(20,W-20),rng.uniform(20,H-20)
        rx,ry=rng.uniform(25,65),rng.uniform(40,100)
        t=np.linspace(0,2*math.pi,200)
        r=1+.20*np.cos(3*t+rng.uniform(0,6))
        paths.append(LineString(np.column_stack([cx+rx*r*np.cos(t),cy+ry*r*np.sin(t)])))
    domain=box(0,0,W,H)
    return [p.intersection(domain) for p in paths if not p.intersection(domain).is_empty]

def raw_label_position(poly,max_pt=5.5,min_pt=3.0,symbol='D'):
    if poly.is_empty or poly.area<.05:return None
    p=polylabel(poly,tolerance=.35)
    clearance=p.distance(poly.boundary)
    # Actual Arial ink bounds; the advance width includes blank side bearings.
    glyph=GLYPHS[symbol];factor=glyph['width']
    for pt in np.arange(max_pt,min_pt-.01,-.2):
        em=pt*25.4/72/MM;height=em*glyph['height'];width=em*factor;pad=.04/MM
        r=box(p.x-width/2-pad,p.y-height/2-pad,p.x+width/2+pad,p.y+height/2+pad)
        if poly.covers(r):return dict(x=p.x,y=p.y,pt=round(float(pt),2),angle=0,clearance=float(clearance))
    # Search rectangle placement and orientation in narrow curved color strokes.
    xmin,ymin,xmax,ymax=poly.bounds
    step=max(1,math.sqrt((xmax-xmin)*(ymax-ymin)/300))
    points=[Point(x,y) for y in np.arange(ymin+.5,ymax,step) for x in np.arange(xmin+.5,xmax,step)]
    points=[q for q in points if poly.contains(q)]
    points=sorted(points,key=lambda q:q.distance(poly.boundary),reverse=True)[:45]
    for pt in [4.5,4.0,3.5,3.0]:
        em=pt*25.4/72/MM;height=em*glyph['height'];width=em*factor;pad=.025/MM
        for q in [p,*points]:
            r=box(q.x-width/2-pad,q.y-height/2-pad,q.x+width/2+pad,q.y+height/2+pad)
            for angle in [0,90,45,-45,*range(-80,90,10)]:
                if poly.covers(rotate(r,angle,origin=(q.x,q.y))):
                    return dict(x=q.x,y=q.y,pt=pt,angle=angle,clearance=float(q.distance(poly.boundary)))
    return None

def build_cells(labels,color_lines,decorative):
    network=unary_union(color_lines+decorative)
    cells=[]
    for p in polygonize(network):
        if p.area<1e-8:continue
        q=p.representative_point();x=min(W-1,max(0,int(q.x)));y=min(H-1,max(0,int(q.y)))
        cells.append({'poly':p,'color':int(labels[y,x])})
    return cells

def merge_fragments(cells):
    """Remove only introduced same-color separators; retain color boundaries."""
    merges=0
    for iteration in range(6):
        geoms=[c['poly'] for c in cells];tree=STRtree(geoms)
        removed=set();targets=set();changed=False
        order=sorted(range(len(cells)),key=lambda i:geoms[i].area)
        for i in order:
            if i in removed or i in targets:continue
            c=cells[i]
            if c['color']==WHITE or label_position(c['poly'],symbol=SYMBOLS[c['color']]) is not None:continue
            candidates=[]
            for j in tree.query(geoms[i],predicate='intersects'):
                j=int(j)
                if j==i or j in removed or cells[j]['color']!=c['color']:continue
                length=c['poly'].boundary.intersection(cells[j]['poly'].boundary).length
                if length>1e-5:candidates.append((length,j))
            if not candidates:continue
            j=max(candidates)[1];joined=c['poly'].union(cells[j]['poly'])
            if joined.geom_type!='Polygon':continue
            cells[j]['poly']=joined;removed.add(i);targets.add(j);merges+=1;changed=True
        cells=[c for i,c in enumerate(cells) if i not in removed]
        if not changed:break
    for i,c in enumerate(cells):
        c['id']=i+1;c['label']=None if c['color']==WHITE else label_position(c['poly'],symbol=SYMBOLS[c['color']])
    return cells,merges

def path_data(poly):
    def ring(coords):
        xy=list(coords)
        return 'M'+'L'.join(f'{x:.2f},{y:.2f}' for x,y in xy)+'Z'
    return ring(poly.exterior.coords)+''.join(ring(r.coords) for r in poly.interiors)

def line_data(geom):
    """Fast vector strokes using small, bounded cubic handles.

    We only smooth the SVG stroke, never cell geometry.  Handles are capped to
    EXPORT_GUARD_PX away from the source line (0.02 mm in V6; legacy default 0.12 px).
    """
    if geom.geom_type in ('MultiLineString','GeometryCollection'):
        return ''.join(line_data(g) for g in geom.geoms)
    if geom.geom_type not in ('LineString','LinearRing'):return ''
    pts=np.asarray(geom.coords,dtype=np.float64)
    if len(pts)<2:return ''
    # Preserve short motifs, corner notches, eye glints, and common junctions.
    if len(pts)>16:
        pts=np.asarray(LineString(pts).simplify(globals().get('EXPORT_SIMPLIFY_PX',.075),preserve_topology=False).coords)
    out=[f'M{pts[0,0]:.3f},{pts[0,1]:.3f}']
    # An almost-straight segment is better expressed compactly with L.
    for i in range(len(pts)-1):
        a,b=pts[i],pts[i+1];d=b-a;length=np.linalg.norm(d)
        if length<1e-8:continue
        prev=pts[max(i-1,0)];nxt=pts[min(i+2,len(pts)-1)]
        t1=(b-prev)/6;t2=(nxt-a)/6
        c1=a+t1;c2=b-t2
        straight1=a+d/3;straight2=b-d/3
        dv1=c1-straight1;dv2=c2-straight2
        n1=np.linalg.norm(dv1);n2=np.linalg.norm(dv2)
        guard=globals().get('EXPORT_GUARD_PX',.12)
        if n1>guard:c1=straight1+dv1*(guard/n1)
        if n2>guard:c2=straight2+dv2*(guard/n2)
        if max(np.linalg.norm(c1-straight1),np.linalg.norm(c2-straight2))<.006:
            out.append(f'L{b[0]:.3f},{b[1]:.3f}')
        else:
            out.append(f'C{c1[0]:.3f},{c1[1]:.3f} {c2[0]:.3f},{c2[1]:.3f} {b[0]:.3f},{b[1]:.3f}')
    return ''.join(out)

@lru_cache(maxsize=20000)
def bezier_segments(line,tolerance=.025):
    """C2 interpolating spline, adaptively bounded against the sampled geometry.

    All cells share this single exported network. The polygon topology uses its
    dense linear approximation; export deviation is limited to 0.025 work pixels.
    """
    pts=np.asarray(line.coords,dtype=float)
    keep=np.r_[True,np.linalg.norm(np.diff(pts,axis=0),axis=1)>1e-9];pts=pts[keep]
    if len(pts)<2:return pts[0],[]
    on_frame=np.all((pts[:,0]==0)|(pts[:,0]==W)|(pts[:,1]==0)|(pts[:,1]==H))
    if on_frame:
        return pts[0],[(a+(b-a)/3,b-(b-a)/3,b) for a,b in zip(pts[:-1],pts[1:])]
    t=np.r_[0,np.cumsum(np.linalg.norm(np.diff(pts,axis=0),axis=1))]
    if len(pts)==2:
        d=(pts[1]-pts[0])/3
        return pts[0],[(pts[0]+d,pts[1]-d,pts[1])]
    closed=np.linalg.norm(pts[-1]-pts[0])<1e-8
    ids=np.unique(np.r_[0,np.searchsorted(t,np.arange(3,t[-1],3)),len(t)-1])
    if closed and len(ids)<4:ids=np.arange(len(t))
    original_pts=pts.copy()
    error=np.array([np.inf])
    for _ in range(8):
        if len(pts)>4096:break
        cs=CubicSpline(t[ids],pts[ids],bc_type='periodic' if closed else 'natural')
        # Test original vertices and midpoints, not just interpolation knots.
        probes=np.sort(np.r_[t,(t[:-1]+t[1:])/2])
        truth=np.column_stack([np.interp(probes,t,pts[:,i]) for i in range(2)])
        error=np.linalg.norm(cs(probes)-truth,axis=1)
        bad=probes[error>tolerance]
        if not len(bad):break
        more=np.searchsorted(t,bad);more=np.clip(more,1,len(t)-1)
        updated=np.unique(np.r_[ids,more,more-1])
        if len(updated)==len(ids):
            # Add geometry samples where a sharp junction exceeds the bound.
            # This does not move the polygon; it bounds the export approximation.
            pts=truth;t=probes;ids=np.arange(len(t))
            continue
        ids=updated
    if np.max(error)>tolerance:
        return original_pts[0],[(a+(b-a)/3,b-(b-a)/3,b) for a,b in zip(original_pts[:-1],original_pts[1:])]
    segments=[]
    for a,b in zip(t[ids][:-1],t[ids][1:]):
        d=(b-a)/3
        segments.append((cs(a)+d*cs(a,1),cs(b)-d*cs(b,1),cs(b)))
    return pts[0],segments

def label_position(poly,max_pt=None,min_pt=None,symbol='D'):
    if poly.is_empty:return None
    x0,y0,x1,y1=poly.bounds;g=GLYPHS[symbol];em=MIN_PT*25.4/72/MM
    if min(x1-x0,y1-y0)<em*min(g['width'],g['height']) or poly.area<em*em*g['width']*g['height']:return None
    p=raw_label_position(poly,max_pt=MAX_PT,min_pt=MIN_PT,symbol=symbol)
    return p if p and p['pt']>=MIN_PT else None

@lru_cache(maxsize=12000)
def placement(poly,color):
    return label_position(poly,symbol=SYMBOLS[color]) if color!=WHITE else None

def pt(c):return c['label']['pt'] if c.get('label') else 0

def reduce_crowding(cells):
    merges=0
    for iteration in range(6):
        geoms=[c['poly'] for c in cells];tree=STRtree(geoms);used=set();deleted=set()
        for i in sorted(range(len(cells)),key=lambda i:(pt(cells[i]),geoms[i].area)):
            c=cells[i]
            if i in used or c['color']==WHITE or pt(c)>=max(4.5,MIN_PT):continue
            candidates=[]
            for j in tree.query(geoms[i],predicate='intersects'):
                j=int(j)
                if j==i or j in used or cells[j]['color']!=c['color']:continue
                shared=geoms[i].boundary.intersection(geoms[j].boundary).length
                if shared<.05:continue
                # Prefer broad adjacency, not a narrow neck between cells.
                score=shared/min(geoms[i].length,geoms[j].length)
                candidates.append((score,j))
            options=[]
            for _,j in sorted(candidates,reverse=True)[:5]:
                joined=geoms[i].union(geoms[j])
                if joined.geom_type!='Polygon' or not joined.is_valid or joined.area>1600:continue
                label=placement(joined,c['color'])
                if label is None:continue
                # A neighbor's existing label must not be made smaller.
                if label['pt']+1e-6<max(pt(c)+.35,pt(cells[j])):continue
                options.append((label['pt'],-joined.area,j,joined,label))
            if not options:continue
            _,_,j,joined,label=max(options,key=lambda a:a[:2])
            cells[j]={'poly':joined,'color':c['color'],'label':label}
            used.update((i,j));deleted.add(i);merges+=1
        cells=[c for i,c in enumerate(cells) if i not in deleted]
        print(f'Crowding pass {iteration+1}: {len(deleted)} merges',flush=True)
        if not deleted:break
    return cells,merges

def balanced_cut(c,index):
    poly=c['poly'];center=polylabel(poly,tolerance=.4)
    # Gentle long S curves: no high-frequency loops or local trembling.
    best=None
    span=max(25,min(120,math.sqrt(poly.area)))
    phase=(index*2.399963229728653)%(2*math.pi)
    for angle in [0,35,70,105,140,175]:
        theta=math.radians(angle+12*math.sin(phase));axis=np.array([math.cos(theta),math.sin(theta)])
        normal=np.array([-axis[1],axis[0]])
        t=np.linspace(-1200,1200,1201)
        # Scale curvature with cell size, avoiding rows of nearly straight cuts.
        amplitude=.30*span
        wave=amplitude*(np.sin(t/(.8*span)+phase)-math.sin(phase))
        points=np.array([center.x,center.y])+t[:,None]*axis+wave[:,None]*normal
        route=LineString(points)
        pieces=list(split(poly,route).geoms)
        if len(pieces)!=2 or min(p.area for p in pieces)<100:continue
        if min(p.area for p in pieces)/poly.area<.25:continue
        new=[]
        for p in pieces:
            label=placement(p,c['color'])
            if label is None or label['pt']<max(4.5,MIN_PT):break
            new.append({'poly':p,'color':c['color'],'label':label})
        if len(new)!=2:continue
        clearance=min(x['label']['clearance'] for x in new)
        balance=min(p.area for p in pieces)/poly.area
        score=balance+.025*min(clearance,12)
        if best is None or score>best[0]:best=(score,new)
    return best[1] if best else None

def distribute_large_cells(cells):
    count=0
    for iteration in range(3):
        out=[];n=0
        for i,c in enumerate(cells):
            if c['color']!=WHITE and c['poly'].area>700:
                children=balanced_cut(c,i+iteration*17)
                if children:
                    out.extend(children);n+=1;continue
            out.append(c)
        cells=out;count+=n
        print(f'Large-cell pass {iteration+1}: {n} balanced cuts',flush=True)
        if not n:break
    return cells,count
def candidates(c):
    poly=c['poly'];old=c['label'];glyph=GLYPHS[SYMBOLS[c['color']]]
    em=old['pt']*25.4/72/MM;ww=em*glyph['width'];hh=em*glyph['height']
    xmin,ymin,xmax,ymax=poly.bounds
    pool=[(old['x'],old['y'])]
    for y in np.linspace(ymin,ymax,12)[1:-1]:
        for x in np.linspace(xmin,xmax,12)[1:-1]:
            if math.hypot(x-old['x'],y-old['y'])<22:pool.append((x,y))
    for dy in [-6,-3,0,3,6]:
        for dx in [-6,-3,0,3,6]:pool.append((old['x']+dx,old['y']+dy))
    positions=[];clear=[]
    oldclear=Point(old['x'],old['y']).distance(poly.boundary)
    for k,(x,y) in enumerate(pool):
        q=Point(x,y);distance=q.distance(poly.boundary)
        if k:
            if not poly.contains(q) or distance<.55*oldclear:continue
            pad=.08/MM
            rect=box(x-ww/2-pad,y-hh/2-pad,x+ww/2+pad,y+hh/2+pad)
            if not poly.covers(rotate(rect,old['angle'],origin=(x,y))):continue
        positions.append((x,y));clear.append(distance)
    positions=np.array(positions);clear=np.array(clear)
    # Small regularization keeps each code visibly inside its own cell.
    unary=.035*(1-np.minimum(clear/max(oldclear,.01),1))
    unary+=.002*np.sum((positions-positions[0])**2,axis=1)/100
    return positions,clear,unary
