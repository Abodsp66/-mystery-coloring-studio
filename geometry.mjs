// A single half-edge graph owns every boundary. The same rounded chains are
// reused, in reverse when necessary, by both neighboring colored faces.
const squared=(a,b)=>(a[0]-b[0])**2+(a[1]-b[1])**2;
function segmentDistance(p,a,b){
  const dx=b[0]-a[0],dy=b[1]-a[1],n=dx*dx+dy*dy;
  const t=n?Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/n)):0;
  return (p[0]-a[0]-dx*t)**2+(p[1]-a[1]-dy*t)**2;
}
function simplify(points,tolerance){
  if(points.length<3)return points;
  const keep=new Uint8Array(points.length);keep[0]=keep[points.length-1]=1;
  const stack=[[0,points.length-1]],limit=tolerance*tolerance;
  while(stack.length){const [a,b]=stack.pop();let max=limit,at=-1;
    for(let i=a+1;i<b;i++){const d=segmentDistance(points[i],points[a],points[b]);if(d>max){max=d;at=i;}}
    if(at>=0){keep[at]=1;stack.push([a,at],[at,b]);}
  }
  return points.filter((_,i)=>keep[i]);
}
function rounded(points,closed,tolerance,radius,strength=1){
  // Remove the digital staircase BEFORE fitting curves. Averaging is bounded
  // to .7 source pixels, and junction endpoints remain exactly fixed.
  const raw=points, last=raw.length-1, span=4;
  points=radius?raw.map((p,i)=>{
    if(!closed&&(i===0||i===last))return p;
    let sx=0,sy=0,sw=0;
    for(let d=-span;d<=span;d++){
      const j=closed?((i+d)%last+last)%last:Math.max(0,Math.min(last,i+d));
      const weight=span+1-Math.abs(d);sx+=raw[j][0]*weight;sy+=raw[j][1]*weight;sw+=weight;
    }
    let dx=sx/sw-p[0],dy=sy/sw-p[1];
    const amount=Math.hypot(dx,dy),cap=.7*strength*(closed?1:Math.min(1,i/3,(last-i)/3));
    if(amount>cap){dx*=cap/amount;dy*=cap/amount;}
    return [p[0]+dx,p[1]+dy];
  }):raw;
  if(closed)points[last]=points[0];
  let p;
  if(closed){const mid=Math.floor((points.length-1)/2);
    p=[...simplify(points.slice(0,mid+1),tolerance),...simplify(points.slice(mid),tolerance).slice(1)];p.pop();
  }else p=simplify(points,tolerance);
  const count=p.length,entry=[],exit=[];
  for(let i=0;i<count;i++){
    if(!closed&&(i===0||i===count-1)){entry.push(p[i]);exit.push(p[i]);continue;}
    const prev=p[(i+count-1)%count],next=p[(i+1)%count],lp=Math.sqrt(squared(prev,p[i])),ln=Math.sqrt(squared(next,p[i]));
    const r=Math.min(radius,lp*.42,ln*.42);
    entry.push([p[i][0]+(prev[0]-p[i][0])*r/(lp||1),p[i][1]+(prev[1]-p[i][1])*r/(lp||1)]);
    exit.push([p[i][0]+(next[0]-p[i][0])*r/(ln||1),p[i][1]+(next[1]-p[i][1])*r/(ln||1)]);
  }
  let current=closed?entry[0]:p[0];const start=current,ops=[];
  function line(to){if(squared(current,to)>1e-16){ops.push({op:'L',from:current,to});current=to;}}
  function corner(i){line(entry[i]);const from=current,to=exit[i],q=p[i];
    if(squared(from,to)<1e-16)return;
    const c1=[from[0]+(q[0]-from[0])*2/3,from[1]+(q[1]-from[1])*2/3];
    const c2=[to[0]+(q[0]-to[0])*2/3,to[1]+(q[1]-to[1])*2/3];
    if(radius>0)ops.push({op:'C',from,c1,c2,to});else ops.push({op:'L',from,to});current=to;
  }
  if(closed){for(let i=0;i<count;i++)corner(i);line(start);}
  else {for(let i=1;i<count-1;i++)corner(i);line(p[count-1]);}
  return {start,ops};
}
const point=p=>p.map(v=>Number(v.toFixed(4))).join(',');
const commands=ops=>ops.map(s=>s.op==='L'?'L'+point(s.to):'C'+point(s.c1)+','+point(s.c2)+','+point(s.to)).join('');
const reverseOps=ops=>ops.slice().reverse().map(s=>s.op==='L'?{op:'L',from:s.to,to:s.from}:{op:'C',from:s.to,c1:s.c2,c2:s.c1,to:s.from});

function curveSegments(chain,tolerance){
  const segments=[];
  const add=(a,b)=>{if(squared(a,b)>1e-14)segments.push({a,b,chain:chain.id,index:segments.length});};
  function cubic(a,b,c,d,depth=0){
    if(depth>9||Math.max(segmentDistance(b,a,d),segmentDistance(c,a,d))<=tolerance*tolerance){add(a,d);return;}
    const mid=(a,b)=>[(a[0]+b[0])/2,(a[1]+b[1])/2],ab=mid(a,b),bc=mid(b,c),cd=mid(c,d),abc=mid(ab,bc),bcd=mid(bc,cd),m=mid(abc,bcd);
    cubic(a,ab,abc,m,depth+1);cubic(m,bcd,cd,d,depth+1);
  }
  for(const op of chain.ops){if(op.op==='L')add(op.from,op.to);else cubic(op.from,op.c1,op.c2,op.to);}
  return segments;
}
function intersection(a,b){
  const [p,q,r,s]=[a.a,a.b,b.a,b.b],u=[q[0]-p[0],q[1]-p[1]],v=[s[0]-r[0],s[1]-r[1]],d=[r[0]-p[0],r[1]-p[1]];
  const cross=(a,b)=>a[0]*b[1]-a[1]*b[0],den=cross(u,v),epsilon=1e-8;
  if(Math.abs(den)<epsilon){
    if(Math.abs(cross(d,u))>epsilon)return null;
    const n=u[0]*u[0]+u[1]*u[1];if(!n)return null;
    const t0=(d[0]*u[0]+d[1]*u[1])/n,t1=((s[0]-p[0])*u[0]+(s[1]-p[1])*u[1])/n;
    const lo=Math.max(0,Math.min(t0,t1)),hi=Math.min(1,Math.max(t0,t1));
    if(hi<lo-epsilon)return null;
    return {point:[p[0]+lo*u[0],p[1]+lo*u[1]],overlap:(hi-lo)*Math.sqrt(n)>1e-5};
  }
  const t=cross(d,v)/den,k=cross(d,u)/den;
  if(t<-epsilon||t>1+epsilon||k<-epsilon||k>1+epsilon)return null;
  return {point:[p[0]+t*u[0],p[1]+t*u[1]],overlap:false};
}
function unsafeChains(chains,mm,stride){
  const grid=new Map(),size=Math.max(2,2/mm),bad=new Set();let checks=0;
  const lists=chains.map(c=>curveSegments(c,.012/mm)),all=lists.flat();
  for(let index=0;index<all.length;index++){
    const a=all[index],x0=Math.floor(Math.min(a.a[0],a.b[0])/size),x1=Math.floor(Math.max(a.a[0],a.b[0])/size);
    const y0=Math.floor(Math.min(a.a[1],a.b[1])/size),y1=Math.floor(Math.max(a.a[1],a.b[1])/size),seen=new Set();
    for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){
      const key=x+':'+y,previous=grid.get(key)||[];
      for(const j of previous){
        if(seen.has(j))continue;seen.add(j);const b=all[j];
        if(a.chain===b.chain&&Math.abs(a.index-b.index)<=1)continue;
        checks++;const hit=intersection(a,b);if(!hit)continue;
        const atEnd=(segment,p)=>squared(segment.a,p)<1e-12||squared(segment.b,p)<1e-12;
        if(!hit.overlap&&atEnd(a,hit.point)&&atEnd(b,hit.point)){
          const ca=chains[a.chain],cb=chains[b.chain];
          if(a.chain===b.chain&&ca.a===ca.b&&Math.min(a.index,b.index)===0&&Math.max(a.index,b.index)===lists[a.chain].length-1)continue;
          const shared=[ca.a,ca.b].some(node=>(node===cb.a||node===cb.b)&&squared(hit.point,[node%stride,Math.floor(node/stride)])<1e-12);
          if(a.chain!==b.chain&&shared)continue;
        }
        bad.add(a.chain);bad.add(b.chain);
      }
      previous.push(index);grid.set(key,previous);
    }
  }
  return {bad,checks};
}

export function traceNetwork(ids,w,h,mm,settings){
  const stride=w+1,edges=[],nodes=new Map();
  function add(a,b,left,right){
    if(left===right)return;const id=edges.length;edges.push({a,b,left,right});
    if(!nodes.has(a))nodes.set(a,[]);if(!nodes.has(b))nodes.set(b,[]);nodes.get(a).push(id);nodes.get(b).push(id);
  }
  for(let y=0;y<h;y++)for(let x=0;x<=w;x++)add(y*stride+x,(y+1)*stride+x,x?ids[y*w+x-1]:0,x<w?ids[y*w+x]:0);
  for(let y=0;y<=h;y++)for(let x=0;x<w;x++)add(y*stride+x,y*stride+x+1,y<h?ids[y*w+x]:0,y?ids[(y-1)*w+x]:0);
  const visited=new Uint8Array(edges.length),chains=[],rawChains=[];
  const coords=node=>[node%stride,Math.floor(node/stride)];
  for(let ei=0;ei<edges.length;ei++)if(!visited[ei]){
    const first=edges[ei];let node=nodes.get(first.a).length!==2?first.a:nodes.get(first.b).length!==2?first.b:first.a;
    const a=node,left=first.a===node?first.left:first.right,right=first.a===node?first.right:first.left;
    const points=[coords(node)];let current=ei;
    for(;;){
      const edge=edges[current];visited[current]=1;node=edge.a===node?edge.b:edge.a;points.push(coords(node));
      if(node===a)break;
      const next=nodes.get(node);if(next.length!==2)break;
      const ni=next[0]===current?next[1]:next[0],ne=edges[ni];
      if(visited[ni]||!((ne.left===left&&ne.right===right)||(ne.right===left&&ne.left===right)))break;
      current=ni;
    }
    // A self-loop at a T/X junction is still an OPEN graph edge: its endpoint
    // must stay fixed and the face walk must choose its proper successor.
    const closed=node===a&&nodes.get(a).length===2, border=left===0||right===0;
    const curve=rounded(points,closed,border?.001:.06/mm,border?0:.22/mm);
    const ops=curve.ops,path='M'+point(curve.start)+commands(ops)+(closed?'Z':'');
    const last=points.length-1;
    chains.push({id:chains.length,a,b:node,left,right,closed,start:curve.start,ops,path,
      startDirection:[points[1][0]-points[0][0],points[1][1]-points[0][1]],
      endDirection:[points[last][0]-points[last-1][0],points[last][1]-points[last-1][1]],
      lengthMM:points.slice(1).reduce((sum,p,i)=>sum+Math.sqrt(squared(p,points[i])),0)*mm});
    rawChains.push({points,closed,border,strength:1});
  }
  let crossings=unsafeChains(chains,mm,stride),relaxed=new Set(),rounds=0;
  while(crossings.bad.size&&rounds<9){
    rounds++;
    for(const id of crossings.bad){
      const raw=rawChains[id];raw.strength=raw.strength<=.125?0:raw.strength/2;relaxed.add(id);
      const c=chains[id],factor=raw.strength;
      const curve=rounded(raw.points,raw.closed,raw.border?.001:.06/mm*factor,raw.border?0:.22/mm*factor,factor);
      c.start=curve.start;c.ops=curve.ops;c.path='M'+point(curve.start)+commands(curve.ops)+(c.closed?'Z':'');
    }
    crossings=unsafeChains(chains,mm,stride);
  }
  if(crossings.bad.size)throw Error('تقاطع غير آمن بعد تنعيم الحدود. لم تُعتمد الورقة.');
  const refs=new Map();
  for(const chain of chains)for(const [id,forward] of [[chain.left,true],[chain.right,false]])if(id){
    if(!refs.has(id))refs.set(id,[]);
    refs.get(id).push({chain,forward,from:forward?chain.a:chain.b,to:forward?chain.b:chain.a});
  }
  const cellPaths={},cache=new Map();let cubics=0,lines=0;
  for(const c of chains)for(const s of c.ops){if(s.op==='C')cubics++;else lines++;}
  for(const [id,faces] of refs){
    const outgoing=new Map(),used=new Set();let path='';
    faces.forEach((ref,index)=>{ref.index=index;if(!outgoing.has(ref.from))outgoing.set(ref.from,[]);outgoing.get(ref.from).push(ref);});
    const opsFor=ref=>{if(ref.forward)return ref.chain.ops;
      if(!cache.has(ref.chain.id))cache.set(ref.chain.id,reverseOps(ref.chain.ops));return cache.get(ref.chain.id);};
    for(const first of faces)if(!used.has(first.index)){
      let ref=first,steps=0;const initial=opsFor(ref)[0]?.from||ref.chain.start;
      path+='M'+point(initial);
      for(;;){
        if(used.has(ref.index))throw Error('تعارض في بناء حدود الخلايا.');
        used.add(ref.index);path+=commands(opsFor(ref));steps++;
        if(ref.chain.closed)break;
        const incoming=ref.forward?ref.chain.endDirection:ref.chain.startDirection.map(v=>-v);
        const options=outgoing.get(ref.to)||[];let chosen=null,maximum=-Infinity;
        for(const option of options){
          const dir=option.forward?option.chain.startDirection:option.chain.endDirection.map(v=>-v);
          const turn=Math.atan2(incoming[0]*dir[1]-incoming[1]*dir[0],incoming[0]*dir[0]+incoming[1]*dir[1]);
          if(turn>maximum){maximum=turn;chosen=option;}
        }
        if(!chosen)throw Error('حدود خلية غير مغلقة.');
        if(chosen.index===first.index)break;
        ref=chosen;if(steps>faces.length)throw Error('تعذر إغلاق شبكة التلوين.');
      }
      path+='Z';
    }
    cellPaths[id]=path;
  }
  return {chains,cellPaths,network:chains.map(c=>c.path).join(''),cubics,lines,
    crossingCheck:{unsafeChains:crossings.bad.size,relaxedChains:relaxed.size,rounds,flattenToleranceMM:.012}};
}
