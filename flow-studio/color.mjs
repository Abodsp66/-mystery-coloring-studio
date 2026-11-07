// Independent local color pipeline. No Python, network or legacy engine.
const linear = Float64Array.from({length: 256}, (_, i) => {
  const v = i / 255;
  return v > .04045 ? ((v + .055) / 1.055) ** 2.4 : v / 12.92;
});
export function lab(rgb) {
  const [r, g, b] = rgb.map(v => linear[Math.max(0, Math.min(255, Math.round(v)))]);
  const f = v => v > .008856 ? Math.cbrt(v) : 7.787 * v + 16 / 116;
  const x = f((r * .4124564 + g * .3575761 + b * .1804375) / .95047);
  const y = f(r * .2126729 + g * .7151522 + b * .0721750);
  const z = f((r * .0193339 + g * .1191920 + b * .9503041) / 1.08883);
  return [116 * y - 16, 500 * (x - y), 200 * (y - z)];
}
export const distance2 = (a, b) => (a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2;
export function quantize(rgba, w, h, count, catalog, scan) {
  const n = w*h, size = 32768;
  const counts = new Uint32Array(size), sums = new Float64Array(size*3);
  const codes = new Uint16Array(n);
  // A small bilateral average reduces scan grain without blurring strong edges.
  for (let y=0; y<h; y++) for (let x=0; x<w; x++) {
    const i=y*w+x, p=i*4; let r=rgba[p], g=rgba[p+1], b=rgba[p+2];
    if (scan && x>0 && y>0 && x<w-1 && y<h-1) {
      let sr=r*2, sg=g*2, sb=b*2, weight=2;
      for (const d of [-w,-1,1,w]) {
        const q=(i+d)*4, diff=Math.max(Math.abs(r-rgba[q]),Math.abs(g-rgba[q+1]),Math.abs(b-rgba[q+2]));
        if (diff<32) { const t=1-diff/40; sr+=rgba[q]*t; sg+=rgba[q+1]*t; sb+=rgba[q+2]*t; weight+=t; }
      }
      r=Math.round(sr/weight); g=Math.round(sg/weight); b=Math.round(sb/weight);
    }
    const code=((r>>3)<<10)|((g>>3)<<5)|(b>>3); codes[i]=code;
    counts[code]++; sums[code*3]+=r; sums[code*3+1]+=g; sums[code*3+2]+=b;
  }
  const bins=[];
  const stable=new Uint32Array(size);
  // Learn source inks from flat interiors. Anti-alias blends must not consume
  // entire palette slots and become thousands of one-pixel color islands.
  for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++){
    const i=y*w+x,p=i*4;let support=0;
    for(const d of [-w-1,-w,-w+1,-1,1,w-1,w,w+1]){
      const q=(i+d)*4;if(Math.max(Math.abs(rgba[p]-rgba[q]),Math.abs(rgba[p+1]-rgba[q+1]),Math.abs(rgba[p+2]-rgba[q+2]))<18)support++;
    }
    if(support>=7)stable[codes[i]]++;
  }
  for(let i=0;i<size;i++) if(counts[i]) {
    const rgb=[sums[i*3]/counts[i],sums[i*3+1]/counts[i],sums[i*3+2]/counts[i]];
    bins.push({id:i, count:counts[i], stable:stable[i], rgb, lab:lab(rgb)});
  }
  let palette, centers;
  if(catalog) { palette=catalog.map(c=>c.slice()); centers=palette.map(lab); }
  else {
    let eligible=bins.filter(b=>b.stable>=Math.max(3,n*.00012)||(b.lab[0]<18&&b.stable>=1));
    if(!eligible.length)eligible=bins;
    const allowed=new Set(eligible.map(b=>b.id));
    const k=Math.min(count,eligible.length), first=eligible.reduce((a,b)=>a.stable>b.stable?a:b);
    centers=[first.lab.slice()]; const best=new Float64Array(bins.length).fill(Infinity);
    for(let c=1;c<k;c++) {
      let chosen=-1, maximum=-1;
      for(let i=0;i<bins.length;i++) {
        best[i]=Math.min(best[i],distance2(bins[i].lab,centers[c-1]));
        const score=allowed.has(bins[i].id)?best[i]*Math.max(1,bins[i].stable)**.42*(bins[i].lab[0]<20?1.8:1):-1;
        if(score>maximum){maximum=score;chosen=i;}
      }
      if(best[chosen]<49)break;
      centers.push(bins[chosen].lab.slice());
    }
    for(let pass=0;pass<7;pass++) {
      const total=centers.map(()=>[0,0,0,0]);
      for(const b of bins) {
        let chosen=0,best=Infinity;
        for(let j=0;j<centers.length;j++){const d=distance2(b.lab,centers[j]);if(d<best){best=d;chosen=j;}}
        const weight=b.stable*(b.lab[0]<20?1.5:1), v=total[chosen];
        for(let j=0;j<3;j++)v[j]+=b.lab[j]*weight; v[3]+=weight;
      }
      centers=centers.map((c,i)=>total[i][3]?total[i].slice(0,3).map(v=>v/total[i][3]):c);
    }
  }
  const lookup=new Uint8Array(size), sumsRGB=centers.map(()=>[0,0,0,0]);
  for(const b of bins){
    let chosen=0,best=Infinity;
    for(let j=0;j<centers.length;j++){const d=distance2(b.lab,centers[j]);if(d<best){best=d;chosen=j;}}
    lookup[b.id]=chosen;
    const v=sumsRGB[chosen];for(let j=0;j<3;j++)v[j]+=b.rgb[j]*b.count;v[3]+=b.count;
  }
  if(!catalog) {
    palette=sumsRGB.map((v,i)=>v[3]?v.slice(0,3).map(a=>Math.round(a/v[3])):bins[0].rgb.map(Math.round));
    // Drop empty clusters; catalog order, in contrast, must remain stable.
    const active=sumsRGB.map((v,i)=>i).filter(i=>sumsRGB[i][3]);
    const remap=new Uint8Array(palette.length);active.forEach((v,i)=>remap[v]=i);
    for(const b of bins)lookup[b.id]=remap[lookup[b.id]];
    palette=active.map(i=>palette[i]);
  }
  let labels=Uint8Array.from(codes,code=>lookup[code]);
  if(scan) {
    const labs=palette.map(lab);
    // Only low-contrast local noise changes class. Dark eye/outline contrast
    // cannot be erased by this vote; unprintable details are handled explicitly.
    for(let pass=0;pass<2;pass++) {
      const next=labels.slice();
      for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++){
        const i=y*w+x, old=labels[i], votes=new Map();
        for(const d of [-w-1,-w,-w+1,-1,1,w-1,w,w+1])votes.set(labels[i+d],(votes.get(labels[i+d])||0)+1);
        for(const [color,vote] of votes)if(color!==old&&vote>=6&&distance2(labs[color],labs[old])<18**2){next[i]=color;break;}
      }
      labels=next;
    }
  }
  return {labels,palette};
}
export function colorAudit(rgba, labels, palette) {
  const labs=palette.map(lab), errors=[];let rgbError=0;
  const step=Math.max(1,Math.ceil(labels.length/16000));
  for(let i=0;i<labels.length;i+=step){
    const rgb=[rgba[i*4],rgba[i*4+1],rgba[i*4+2]], target=palette[labels[i]];
    errors.push(Math.sqrt(distance2(lab(rgb),labs[labels[i]])));
    rgbError+=rgb.reduce((sum,v,j)=>sum+Math.abs(v-target[j]),0)/3;
  }
  errors.sort((a,b)=>a-b);
  const q=p=>Math.round(errors[Math.floor((errors.length-1)*p)]*100)/100;
  return {metric:'CIE76',median:q(.5),p95:q(.95),p99:q(.99),sampledPixels:errors.length,
    meanRGB:Math.round(rgbError/errors.length*100)/100,stage:'RGB input versus printable color classes, before vector tracing'};
}
