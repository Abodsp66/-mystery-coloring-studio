// Typed-array topology and physical ink fitting. Independent of the V5/V6 code.
export function components(colors,w,h,bands=null) {
  const n=w*h, ids=new Int32Array(n), queue=new Int32Array(n), cells=[null];
  for(let seed=0;seed<n;seed++)if(!ids[seed]){
    const id=cells.length,color=colors[seed],band=bands?bands[seed]:0;
    let head=0,tail=1,area=0,x0=w,y0=h,x1=0,y1=0;queue[0]=seed;ids[seed]=id;
    while(head<tail){
      const i=queue[head++],x=i%w,y=(i-x)/w;area++;x0=Math.min(x0,x);y0=Math.min(y0,y);x1=Math.max(x1,x);y1=Math.max(y1,y);
      for(const j of [x?i-1:-1,x<w-1?i+1:-1,y?i-w:-1,y<h-1?i+w:-1])
        if(j>=0&&!ids[j]&&colors[j]===color&&(!bands||bands[j]===band)){ids[j]=id;queue[tail++]=j;}
    }
    cells.push({id,color,area,bounds:[x0,y0,x1+1,y1+1],label:null});
  }
  return {ids,cells};
}

// Exact squared Euclidean distance transform, Felzenszwalb/Huttenlocher 1D
// lower envelope of parabolas, applied along rows and columns.
function edt1d(f,n,d,v,z) {
  let k=0;v[0]=0;z[0]=-Infinity;z[1]=Infinity;
  for(let q=1;q<n;q++){
    let s=((f[q]+q*q)-(f[v[k]]+v[k]*v[k]))/(2*q-2*v[k]);
    while(s<=z[k]){k--;s=((f[q]+q*q)-(f[v[k]]+v[k]*v[k]))/(2*q-2*v[k]);}
    v[++k]=q;z[k]=s;z[k+1]=Infinity;
  }
  k=0;for(let q=0;q<n;q++){while(z[k+1]<q)k++;d[q]=(q-v[k])**2+f[v[k]];}
}
export function distances(ids,w,h) {
  const n=w*h,out=new Float32Array(n),max=Math.max(w,h);
  const f=new Float64Array(max),d=new Float64Array(max),v=new Int32Array(max),z=new Float64Array(max+1);
  for(let y=0;y<h;y++){
    for(let x=0;x<w;x++){const i=y*w+x,c=ids[i];f[x]=!x||!y||x===w-1||y===h-1||ids[i-1]!==c||ids[i+1]!==c||ids[i-w]!==c||ids[i+w]!==c?0:1e12;}
    edt1d(f,w,d,v,z);for(let x=0;x<w;x++)out[y*w+x]=d[x];
  }
  for(let x=0;x<w;x++){
    for(let y=0;y<h;y++)f[y]=out[y*w+x];
    edt1d(f,h,d,v,z);for(let y=0;y<h;y++)out[y*w+x]=Math.sqrt(d[y]);
  }
  return out;
}
export function fitsInk(ids,w,h,id,cx,cy,hw,hh,angle=0) {
  const a=angle*Math.PI/180,co=Math.cos(a),si=Math.sin(a);
  const bx=Math.abs(co)*hw+Math.abs(si)*hh,by=Math.abs(si)*hw+Math.abs(co)*hh;
  if(cx-bx<0||cy-by<0||cx+bx>w||cy+by>h)return false;
  for(let y=Math.floor(cy-by);y<Math.ceil(cy+by);y++)for(let x=Math.floor(cx-bx);x<Math.ceil(cx+bx);x++){
    const dx=x+.5-cx,dy=y+.5-cy,rx=dx*co+dy*si,ry=-dx*si+dy*co;
    if(Math.abs(rx)<=hw&&Math.abs(ry)<=hh&&ids[y*w+x]!==id)return false;
  }
  return true;
}
export function placeLabels(topology,w,h,mm,settings,glyphs,symbols) {
  const {ids,cells}=topology,dist=distances(ids,w,h),best=new Float32Array(cells.length).fill(-1);
  const seeds=new Int32Array(cells.length), candidates=cells.map(()=>[]);
  for(let i=0;i<ids.length;i++){
    const id=ids[i];if(dist[i]>best[id]){best[id]=dist[i];seeds[id]=i;}
    // Spatially spread samples avoid 32 almost-identical pixels at a plateau.
    if((i%w)%3===1&&Math.floor(i/w)%3===1){
      const list=candidates[id];if(list.length<18)list.push(i);
      else {let j=0;for(let k=1;k<list.length;k++)if(dist[list[k]]<dist[list[j]])j=k;if(dist[i]>dist[list[j]])list[j]=i;}
    }
  }
  const pad=(settings.stroke/2+.15+settings.curveBoundMM)/mm+.72;
  for(let id=1;id<cells.length;id++){
    const cell=cells[id],g=glyphs[symbols[cell.color]],em=settings.font*25.4/72/mm;
    const hw=em*g.width/2+pad,hh=em*g.height/2+pad;
    cell.anchor=[seeds[id]%w+.5,Math.floor(seeds[id]/w)+.5];cell.radius=best[id];cell.label=null;
    const list=[seeds[id],...candidates[id].sort((a,b)=>dist[b]-dist[a])];
    for(const i of list){
      const x=i%w+.5,y=Math.floor(i/w)+.5;
      for(const angle of [0,90,45,-45]) if(fitsInk(ids,w,h,id,x,y,hw,hh,angle)){
        cell.label={x,y,angle,pt:settings.font,code:symbols[cell.color]};break;
      }
      if(cell.label)break;
    }
  }
  return cells.slice(1).filter(c=>!c.label);
}
export function adjacency(ids,w,h) {
  const pairs=new Map();
  function add(a,b){if(a===b)return;const key=a<b?a+':'+b:b+':'+a;pairs.set(key,(pairs.get(key)||0)+1);}
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){const i=y*w+x;if(x+1<w)add(ids[i],ids[i+1]);if(y+1<h)add(ids[i],ids[i+w]);}
  return pairs;
}
export function mergeFlowFragments(topology,w,h,mm,settings,glyphs,symbols,colors) {
  let current=topology,merges=0;
  for(let pass=0;pass<24;pass++){
    const bad=placeLabels(current,w,h,mm,settings,glyphs,symbols);
    if(!bad.length)return {...current,merges};
    const {ids,cells}=current,pairs=adjacency(ids,w,h),parent=Int32Array.from({length:cells.length},(_,i)=>i);
    const root=i=>{while(parent[i]!==i){parent[i]=parent[parent[i]];i=parent[i];}return i;};
    const options=new Map();
    for(const [key,length] of pairs){const [a,b]=key.split(':').map(Number);if(cells[a].color!==cells[b].color)continue;
      if(!options.has(a)||length>options.get(a)[1])options.set(a,[b,length]);
      if(!options.has(b)||length>options.get(b)[1])options.set(b,[a,length]);
    }
    let changed=0;
    for(const c of bad){const option=options.get(c.id);if(!option)continue;const a=root(c.id),b=root(option[0]);if(a!==b){parent[a]=b;changed++;}}
    if(!changed)throw Error('لا يمكن ترقيم جميع التفاصيل بهذا المقاس. جرّبي A3 أو زيادة تبسيط التفاصيل. لم تُصدّر خلايا فارغة.');
    const groups=Int32Array.from(ids,id=>root(id));
    current=components(colors,w,h,groups);merges+=changed;
  }
  throw Error('توقّف إنشاء الورقة لأن بعض الخلايا لا تتسع للرموز. جرّبي تمويهًا أخف.');
}
