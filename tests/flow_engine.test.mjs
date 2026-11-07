import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {generate,SYMBOLS} from '../flow-studio/engine.mjs';
import {distances,components,fitsInk} from '../flow-studio/raster.mjs';
import {traceNetwork} from '../flow-studio/geometry.mjs';
const glyphs=JSON.parse(fs.readFileSync(new URL('../flow-studio/fonts/metrics.json',import.meta.url)));
const config=extra=>({colors:18,paper:[210,297],font:5,stroke:.16,density:.7,detailMM2:2.5,budget:.025,scan:false,seed:37,...extra});
function image(size,fn=()=>[74,132,146]){const a=new Uint8ClampedArray(size*size*4);for(let y=0;y<size;y++)for(let x=0;x<size;x++)a.set([...fn(x,y),255],(y*size+x)*4);return a;}

test('all flow cells have real printable codes and preserve the color map',()=>{
  const size=320,a=image(size,(x,y)=>x>90&&x<230&&y>50&&y<270?[200,90,80]:[74,132,146]);
  const r=generate(a,size,size,config({catalog:[[74,132,146],[200,90,80]]}),glyphs);
  assert.ok(r.cells.length>100);assert.equal(r.metrics.missing,0);assert.equal(r.metrics.flowColorChanges,0);
  assert.equal(r.metrics.precolored,0);assert.ok(r.metrics.vector.cubicSegments>100);
  for(let i=0;i<size*size;i++){const c=r.cells[r.regionMap[i]-1];assert.deepEqual(r.palette[c.color],Array.from(a.slice(i*4,i*4+3)));}
  for(const c of r.cells){assert.ok(c.label);assert.ok(c.label.pt>=5);assert.match(c.path,/^M.*Z$/);assert.ok(!c.path.includes('NaN'));}
});
test('density is measured on paper at three useful raster resolutions',()=>{
  const counts=[320,480,640].map(size=>generate(image(size),size,size,config(),glyphs).metrics.cells);
  assert.ok(Math.max(...counts)/Math.min(...counts)<1.10,JSON.stringify(counts));
});
test('fine-detail simplification is explicit and bounded',()=>{
  const a=image(256);a.set([0,0,0,255],(128*256+128)*4);
  const r=generate(a,256,256,config({density:0,catalog:[[74,132,146],[0,0,0]]}),glyphs);
  assert.ok(r.metrics.smallDetailsMerged>0);assert.ok(r.metrics.detailChangedPixels>0);
  assert.ok(r.metrics.detailChangedPct<=2.5);assert.equal(r.metrics.missing,0);
});
test('a large dark feature survives instead of being treated as a small island',()=>{
  const a=image(256,(x,y)=>x>90&&x<150&&y>90&&y<150?[0,0,0]:[74,132,146]);
  const r=generate(a,256,256,config({density:0,catalog:[[74,132,146],[0,0,0]]}),glyphs);
  assert.equal(r.metrics.detailChangedPixels,0);assert.ok(r.cells.some(c=>c.color===1));
});
test('actual single-character palette order reaches 32 colors',()=>{
  const palette=Array.from({length:32},(_,i)=>[20+(i%8)*30,25+Math.floor(i/8)*55,120]);
  const a=image(320,(x,y)=>palette[Math.floor(y/80)*8+Math.floor(x/40)]);
  const r=generate(a,320,320,config({colors:32,density:0,catalog:palette}),glyphs);
  assert.deepEqual(r.palette,palette);assert.equal(new Set(r.cells.map(c=>c.label.code)).size,32);
  assert.ok(r.cells.every(c=>c.label.code.length===1));assert.ok(r.cells.some(c=>c.label.code===SYMBOLS[31]));
});
test('invalid settings and incomplete buffers are rejected',()=>{
  for(const change of [{colors:48},{font:3},{stroke:.5},{density:NaN},{paper:[200,200]},
    {catalog:[[0,0,0],[0,0,0]]},{catalog:[[300,0,0]]},{budget:.9}]){
    assert.throws(()=>generate(image(32),32,32,config(change),glyphs));
  }
  assert.throws(()=>generate(new Uint8Array(5),32,32,config(),glyphs));
});
test('a pathological noisy input is rejected rather than exported with missing labels',()=>{
  const a=image(128,(x,y)=>(x+y)%2?[255,255,255]:[0,0,0]);
  assert.throws(()=>generate(a,128,128,config({density:0,catalog:[[0,0,0],[255,255,255]]}),glyphs),/ضجيج|التفاصيل|تفاصيل/);
});
test('the EDT agrees with an independent brute-force boundary distance',()=>{
  const w=13,h=11,ids=Int32Array.from({length:w*h},(_,i)=>i%w<6?1:2),d=distances(ids,w,h),boundaries=[];
  for(let y=0;y<h;y++)for(let x=0;x<w;x++)if(!x||!y||x===w-1||y===h-1||x===5||x===6)boundaries.push([x,y]);
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){
    const expected=Math.min(...boundaries.map(([a,b])=>Math.hypot(x-a,y-b)));
    assert.ok(Math.abs(d[y*w+x]-expected)<1e-6);
  }
});
test('holes, diagonal contacts and the outer border form closed shared faces',()=>{
  const w=14,h=14,a=new Uint8Array(w*h);
  for(let y=0;y<h;y++)for(let x=0;x<w;x++)a[y*w+x]=(x>2&&x<11&&y>2&&y<11)?1:0;
  a[6*w+6]=0;a[7*w+7]=0;
  const t=components(a,w,h),v=traceNetwork(t.ids,w,h,1,{curveBoundMM:.92});
  assert.equal(Object.keys(v.cellPaths).length,t.cells.length-1);
  assert.ok(v.chains.every(c=>c.left!==c.right));
  assert.ok(Object.values(v.cellPaths).every(p=>p.startsWith('M')&&p.endsWith('Z')));
  for(const c of v.chains.filter(c=>!c.left||!c.right)){
    for(const op of c.ops)assert.ok(op.to[0]===0||op.to[0]===w||op.to[1]===0||op.to[1]===h);
  }
});
test('ink fitting tests the full rotated rectangle, not only its center',()=>{
  const ids=new Int32Array(20*20).fill(1);ids[10*20+11]=2;
  assert.equal(fitsInk(ids,20,20,1,10,10,3,3,45),false);
  assert.equal(fitsInk(ids,20,20,1,5,5,1,1,45),true);
});
