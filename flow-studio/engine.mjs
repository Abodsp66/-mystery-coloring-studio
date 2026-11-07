import {quantize,lab,distance2,colorAudit} from './color.mjs';
import {components,placeLabels,adjacency,mergeFlowFragments,fitsInk} from './raster.mjs';
import {traceNetwork} from './geometry.mjs';

export const SYMBOLS=[...'123456789ABCDEFGHJKLMNPQRSTUVWXYZ'];
export function validate(settings,w,h,glyphs){
  if(!Number.isInteger(w)||!Number.isInteger(h)||w<16||h<16||w*h>1600000)throw Error('أبعاد الصورة غير مدعومة.');
  if(![12,15,18,24,32].includes(settings.colors))throw Error('عدد الألوان غير صالح.');
  if(![[210,297],[297,210],[297,420],[420,297]].some(p=>p.every((v,i)=>settings.paper?.[i]===v)))throw Error('مقاس الورقة غير صالح.');
  for(const [name,lo,hi] of [['font',4.5,7],['stroke',.10,.22],['density',0,1],['detailMM2',.5,5],['budget',.005,.06]])
    if(!Number.isFinite(settings[name])||settings[name]<lo||settings[name]>hi)throw Error('إعداد غير صالح: '+name);
  if(settings.angle!==undefined&&(!Number.isFinite(settings.angle)||Math.abs(settings.angle)>180))throw Error('اتجاه التدفق غير صالح.');
  if(settings.seed!==undefined&&(!Number.isInteger(settings.seed)||settings.seed<0||settings.seed>4294967295))throw Error('بذرة التمويه غير صالحة.');
  if(settings.catalog){
    if(!Array.isArray(settings.catalog)||!settings.catalog.length||settings.catalog.length>32)throw Error('لوحة الأقلام يجب أن تحتوي 1–32 لونًا.');
    for(const c of settings.catalog)if(!Array.isArray(c)||c.length!==3||c.some(v=>!Number.isInteger(v)||v<0||v>255))throw Error('ألوان الأقلام غير صالحة.');
    if(new Set(settings.catalog.map(c=>c.join(','))).size!==settings.catalog.length)throw Error('توجد ألوان مكررة في لوحة الأقلام.');
  }
  for(const symbol of SYMBOLS){const g=glyphs[symbol];if(!g||['width','height','cx','cy'].some(k=>!Number.isFinite(g[k]))||g.width<=0||g.height<=0)throw Error('تعذر قياس خط الرموز.');}
}

function repairDetails(input,palette,w,h,mm,settings,glyphs,progress){
  let colors=input.slice(),topology;
  const labs=palette.map(lab),n=w*h,maxChanged=Math.floor(n*settings.budget);
  let removed=0,expanded=0,changed=0;
  for(let pass=0;pass<8;pass++){
    topology=components(colors,w,h);
    if(topology.cells.length>6500)throw Error('الصورة تحتوي ضجيجًا وتفاصيل كثيرة. قصّي رسمًا واحدًا وفعّلي تنظيف المسح.');
    const bad=placeLabels(topology,w,h,mm,settings,glyphs,SYMBOLS);
    if(!bad.length)return {colors,topology,removed,expanded,changedPixels:changed};
    progress(`تهيئة التفاصيل للطباعة: ${bad.length} منطقة ضيقة…`);
    const {ids,cells}=topology,pairs=adjacency(ids,w,h),neighbors=new Map();
    for(const [key,length] of pairs){const [a,b]=key.split(':').map(Number);
      if(!neighbors.has(a))neighbors.set(a,[]);if(!neighbors.has(b))neighbors.set(b,[]);
      neighbors.get(a).push([b,length]);neighbors.get(b).push([a,length]);
    }
    const replacement=new Map();let edits=0;
    for(const c of bad){
      const candidates=(neighbors.get(c.id)||[]).filter(([id])=>cells[id].area>c.area||(cells[id].area===c.area&&id<c.id));
      candidates.sort((a,b)=>{
        const score=([id,len])=>distance2(labs[c.color],labs[cells[id].color])/(1+Math.min(len,10)*.04)+(cells[id].label?0:50);
        return score(a)-score(b);
      });
      if(candidates.length){
        const neighbor=cells[candidates[0][0]],similar=distance2(labs[c.color],labs[neighbor.color])<10**2;
        if(c.area*mm*mm<=settings.detailMM2||similar){replacement.set(c.id,neighbor.color);removed++;edits++;}
      }
    }
    for(let i=0;i<n;i++)if(replacement.has(ids[i]))colors[i]=replacement.get(ids[i]);
    // A long, thin original stroke cannot be discarded as a tiny island.
    // Widen only a local symbol-sized anchor, within the user's explicit budget.
    for(const c of bad){
      if(replacement.has(c.id))continue;
      const g=glyphs[SYMBOLS[c.color]],em=settings.font*25.4/72/mm;
      const pad=(settings.stroke/2+.15+settings.curveBoundMM)/mm+1.6;
      const hw=Math.ceil(Math.SQRT2*(em*g.width/2+pad)),hh=Math.ceil(Math.SQRT2*(em*g.height/2+pad));
      const [ax,ay]=c.anchor;let best=null;
      for(const angle of [0,90]){
        const rx=angle?hh:hw,ry=angle?hw:hh;
        if(2*rx+1>w||2*ry+1>h)continue;
        const cx=Math.max(rx,Math.min(w-rx-1,Math.round(ax))),cy=Math.max(ry,Math.min(h-ry-1,Math.round(ay)));
        // The printable patch must touch this region, rather than inventing a
        // detached colored dot elsewhere on the image.
        let touches=false,cost=0,count=0;
        for(let y=cy-ry;y<=cy+ry;y++)for(let x=cx-rx;x<=cx+rx;x++){
          if(((x-cx)/rx)**2+((y-cy)/ry)**2>1)continue;
          const i=y*w+x;if(ids[i]===c.id)touches=true;
          if(colors[i]!==c.color){cost+=distance2(labs[colors[i]],labs[c.color]);count++;}
        }
        if(touches&&(!best||cost<best.cost))best={cx,cy,rx,ry,cost,count};
      }
      if(!best||best.count*mm*mm>Math.max(18,settings.detailMM2*5))continue;
      for(let y=best.cy-best.ry;y<=best.cy+best.ry;y++)for(let x=best.cx-best.rx;x<=best.cx+best.rx;x++)
        if(((x-best.cx)/best.rx)**2+((y-best.cy)/best.ry)**2<=1)colors[y*w+x]=c.color;
      expanded++;edits++;
    }
    changed=0;for(let i=0;i<n;i++)if(colors[i]!==input[i])changed++;
    if(changed>maxChanged)throw Error('التفاصيل تحتاج تبسيطًا يتجاوز الحد المختار. اختاري A3 أو ارفعي حد التبسيط، ثم راجعي الحل. لم تُنتج ورقة بخلايا فارغة.');
    if(!edits)break;
  }
  throw Error('بقيت تفاصيل لا تتسع للرمز بعد التبسيط المحدود. اختاري ورقة أكبر أو صورة أوضح. لم تُعتمد النتيجة.');
}

function contourContinuations(topology,w,h,mm,settings,palette){
  const graph=traceNetwork(topology.ids,w,h,mm,settings),candidates=[],labs=palette.map(lab);
  for(const chain of graph.chains){
    if(!chain.left||!chain.right||chain.lengthMM<14)continue;
    const contrast=Math.sqrt(distance2(labs[topology.cells[chain.left].color],labs[topology.cells[chain.right].color]));
    if(contrast<12)continue;
    // Arc-length samples of the ACTUAL source contour, not random grid seeds.
    const points=[chain.start];let last=chain.start;
    for(const op of chain.ops){
      const length=Math.hypot(op.to[0]-op.from[0],op.to[1]-op.from[1])*mm;
      const count=Math.max(1,Math.ceil(length/.6));
      for(let j=1;j<=count;j++){
        const t=j/count,s=1-t;
        const p=op.op==='L'?op.from.map((v,k)=>v+(op.to[k]-v)*t):[0,1].map(k=>s**3*op.from[k]+3*s*s*t*op.c1[k]+3*s*t*t*op.c2[k]+t**3*op.to[k]);
        if(Math.hypot(p[0]-last[0],p[1]-last[1])*mm>=.45){points.push(p);last=p;}
      }
    }
    const arm=7;
    for(let i=arm;i<points.length-arm;i+=12){
      const before=points[i-arm],p=points[i],after=points[i+arm];
      if(p[0]*mm<10||p[1]*mm<10||(w-p[0])*mm<10||(h-p[1])*mm<10)continue;
      const a=[p[0]-before[0],p[1]-before[1]],b=[after[0]-p[0],after[1]-p[1]];
      const la=Math.hypot(...a),lb=Math.hypot(...b),lc=Math.hypot(after[0]-before[0],after[1]-before[1]);
      if(!la||!lb||!lc)continue;
      const curvature=Math.max(-.065,Math.min(.065,2*(a[0]*b[1]-a[1]*b[0])/(la*lb*lc*mm)));
      const angle=Math.atan2(after[1]-before[1],after[0]-before[0]);
      const score=Math.sqrt(chain.lengthMM)*(.3+Math.min(Math.abs(curvature)*60,1.8))*Math.min(contrast/30,2);
      candidates.push({x:(p[0]-w/2)*mm,y:(p[1]-h/2)*mm,angle,curvature,score});
    }
  }
  candidates.sort((a,b)=>b.score-a.score);const chosen=[];
  for(const c of candidates){
    if(chosen.some(p=>Math.hypot(p.x-c.x,p.y-c.y)<16))continue;
    chosen.push({...c,co:Math.cos(c.angle),si:Math.sin(c.angle)});if(chosen.length===8)break;
  }
  return chosen;
}
function flowBands(w,h,mm,settings,seed,topology,palette){
  const out=new Int32Array(w*h),spacing=8-settings.density*4.3;
  const guides=contourContinuations(topology,w,h,mm,settings,palette);
  // Nonlinear coordinates produce page-spanning contour ribbons. No seeds,
  // Voronoi diagram, triangles, binary polygon cuts or local tessellation.
  const a=(settings.angle??-32)*Math.PI/180,co=Math.cos(a),si=Math.sin(a),phase=seed*.173;
  const limit=Math.hypot(w,h)*mm*3,thresholds=[-limit];
  let random=(seed||1)>>>0;const rand=()=>{random=(1664525*random+1013904223)>>>0;return random/4294967296;};
  for(let t=-limit;t<limit;) {t+=spacing*(.80+rand()*.44);thresholds.push(t);}
  // Precompute the field once; searching thresholds via a lookup avoids a
  // curves × pixels geometry loop.
  const lutScale=8,lut=new Uint16Array(Math.ceil(limit*2*lutScale)+2);let band=0;
  for(let j=0;j<lut.length;j++){const value=j/lutScale-limit;while(band+1<thresholds.length&&value>=thresholds[band+1])band++;lut[j]=band;}
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){
    const px=(x-w/2)*mm,py=(y-h/2)*mm,u=px*co+py*si,v=-px*si+py*co;
    const bend=17*Math.sin(u/29+phase+.28*Math.sin(v/37))+9*Math.sin(u/61-v/79+phase*.7)+4*Math.sin(u/13+v/91);
    const f=v+bend;
    const primary=lut[Math.max(0,Math.min(lut.length-1,Math.round((f+limit)*lutScale)))];
    // Sparse long cross-curves terminate long ribbons, rather than chopping
    // them into a dense field of similar little polygons.
    const cross=Math.floor((u+22*Math.sin(v/44+phase)+13*Math.sin(v/19-u/110)+limit)/34);
    let mask=0;
    for(let j=0;j<guides.length;j++){
      const g=guides[j],dx=px-g.x,dy=py-g.y,along=dx*g.co+dy*g.si,normal=-dx*g.si+dy*g.co;
      // Match the source tangent and curvature at the anchor, then extend a
      // smooth arc into other colors. Its second derivative at zero is kappa.
      const extension=.5*g.curvature*along*along/(1+along*along/3600);
      if(normal>extension)mask|=1<<j;
    }
    out[y*w+x]=(primary*1024+cross)*256+mask;
  }
  return {bands:out,spacing,guides,field:'source-contour-continuations-and-nonlinear-isolines',thresholds:thresholds.length};
}

export function generate(rgba,w,h,inputSettings,glyphs,progress=()=>{}){
  const start=performance.now(),timings={},settings={...inputSettings};
  validate(settings,w,h,glyphs);
  if(!(rgba instanceof Uint8Array)&&!(rgba instanceof Uint8ClampedArray))throw Error('بيانات الصورة غير صالحة.');
  if(rgba.length!==w*h*4)throw Error('بيانات الصورة ناقصة.');
  const [pw,ph]=settings.paper,margin=15;
  const mm=Math.min((pw-2*margin)/w,(ph-margin-39)/h);
  settings.curveBoundMM=.20+.72*mm;
  const mark=(name,t)=>timings[name]=Math.round((performance.now()-t)*10)/10;
  progress('استخراج ألوان الرسم وتنظيف ضجيج المسح…');let t=performance.now();
  const q=quantize(rgba,w,h,settings.colors,settings.catalog,settings.scan);mark('colorsMS',t);
  progress('ضبط التفاصيل والرموز على حجم الورقة…');t=performance.now();
  const repaired=repairDetails(q.labels,q.palette,w,h,mm,settings,glyphs,progress);mark('detailsMS',t);
  progress('مدّ خطوط التمويه الانسيابية عبر المشهد…');t=performance.now();
  const field=settings.density?flowBands(w,h,mm,settings,settings.seed??37,repaired.topology,q.palette):null;
  const split=field?components(repaired.colors,w,h,field.bands):repaired.topology;
  const before=split.cells.length-1;
  const topology=mergeFlowFragments(split,w,h,mm,settings,glyphs,SYMBOLS,repaired.colors);mark('flowMS',t);
  progress('رسم شبكة متجهية مشتركة وفحص جميع الرموز…');t=performance.now();
  const vector=traceNetwork(topology.ids,w,h,mm,settings);
  const {cells,ids}=topology;
  let wrong=0;for(let i=0;i<ids.length;i++)if(!ids[i]||cells[ids[i]].color!==repaired.colors[i])wrong++;
  const missing=cells.slice(1).filter(c=>!c.label).map(c=>c.id),invalid=[];
  const pad=(settings.stroke/2+.15+settings.curveBoundMM)/mm+.72;
  for(const c of cells.slice(1))if(c.label){const p=c.label,g=glyphs[p.code],em=p.pt*25.4/72/mm;
    if(!fitsInk(ids,w,h,c.id,p.x,p.y,em*g.width/2+pad,em*g.height/2+pad,p.angle))invalid.push(c.id);
  }
  if(missing.length||invalid.length||wrong)throw Error('لم تجتز الورقة فحص التغطية والترقيم. لم يُسمح بتصديرها.');
  mark('vectorMS',t);
  const colorError=colorAudit(rgba,repaired.colors,q.palette);
  return {engine:'Flow Studio 1.0 — independent JavaScript',w,h,mm,paper:settings.paper,
    offset:[(pw-w*mm)/2,margin],palette:q.palette,symbols:SYMBOLS.slice(0,q.palette.length),glyphs,settings,
    cells:cells.slice(1).map(c=>({...c,path:vector.cellPaths[c.id],areaMM2:c.area*mm*mm})),
    chains:vector.chains,network:vector.network,regionMap:ids,
    metrics:{cells:cells.length-1,missing:missing.length,invalidInk:invalid.length,flowColorChanges:wrong,
      precolored:0,printReady:true,baseRegions:repaired.topology.cells.length-1,initialFlowCells:before,
      rejectedSlivers:topology.merges,smallDetailsMerged:repaired.removed,thinDetailsWidened:repaired.expanded,
      detailChangedPixels:repaired.changedPixels,detailChangedPct:100*repaired.changedPixels/(w*h),
      colorError,field:field?.field||'source-only',spacingMM:field?.spacing||null,
      contourContinuations:field?.guides.length||0,
      vector:{sharedChains:vector.chains.length,cubicSegments:vector.cubics,straightSegments:vector.lines,crossingCheck:vector.crossingCheck},
      timings,totalMS:Math.round((performance.now()-start)*10)/10,
      scope:'Print geometry and complete region codes; not a human mystery score or a physical pencil calibration.'}};
}
