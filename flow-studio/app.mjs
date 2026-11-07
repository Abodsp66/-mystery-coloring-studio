import {SYMBOLS} from './engine.mjs';
import {fitsInk} from './raster.mjs';
import {colorAudit} from './color.mjs';
import {loadFont,pageSVG,pagePDF,croppedSolution} from './export.mjs';
const $=id=>document.getElementById(id);
let source=null,sourceURL='',result=null,worker=null,busy=false,dirty=false,view='outline',glyphs=null,catalog=null;
let selected=null,seed=37,analysisRGBA=null,history=[];
function status(message,error=false){$('status').textContent=message;$('status').classList.toggle('error',error);}
function controls(){
  const valid=!!result&&!dirty&&!busy;
  document.querySelectorAll('.setting').forEach(n=>n.disabled=busy);
  $('catalog').disabled=busy;$('clearCatalog').disabled=busy;$('colors').disabled=busy||!!catalog;
  $('process').disabled=!source||!glyphs||busy;$('variant').disabled=!source||!glyphs||busy;$('cancel').hidden=!busy;
  for(const id of ['svg','pdf','print','report'])$(id).disabled=!valid;
  $('code').disabled=$('recode').disabled=!valid||selected===null;$('undo').disabled=!valid||!history.length;
  $('badge').textContent=busy?'جارٍ الإنشاء':dirty?'تحتاج إعادة إنشاء':valid?'كل الخلايا مرقمة':source?'الصورة جاهزة':'بانتظار الصورة';
}
function cancel(){worker?.terminate();worker=null;busy=false;controls();}
function settings(){let paper=$('paper').value==='A4'?[210,297]:[297,420];if($('orientation').value==='landscape')paper.reverse();
  return {paper,colors:+$('colors').value,font:+$('font').value,stroke:+$('stroke').value,density:+$('density').value,
    angle:+$('angle').value,scan:$('scan').checked,detailMM2:+$('detail').value,budget:+$('budget').value,
    catalog:catalog?.colors||null,paletteName:catalog?.name||null,paletteNames:catalog?.names||null,seed};
}
function setView(mode){view=mode;document.querySelectorAll('[data-view]').forEach(n=>n.classList.toggle('active',n.dataset.view===mode));render();}
async function setSource(url){
  const image=new Image();image.src=url;await image.decode();
  if(image.naturalWidth*image.naturalHeight>36000000)throw Error('الصورة كبيرة جدًا. استخدمي نسخة أصغر من36 مليون بكسل.');
  cancel();if(sourceURL.startsWith('blob:'))URL.revokeObjectURL(sourceURL);
  source=image;sourceURL=url;result=null;history=[];selected=null;dirty=false;analysisRGBA=null;
  for(const id of ['time','cells','missing','changed'])$(id).textContent='—';$('palette').replaceChildren();
  $('selection').textContent='بعد الإنشاء، انقري خلية لفحص رمزها ومساحتها.';
  $('qa').textContent='تُتاح ملفات الطباعة بعد اجتياز اتساع جميع الرموز.';
  setView('source');status('الصورة جاهزة. اضبطي الخيارات ثم أنشئي الورقة.');controls();
}
$('file').onchange=async()=>{
  const file=$('file').files[0];if(!file)return;let url='';
  try{if(file.size>35*1024*1024)throw Error('اختاري ملفًا أصغر من35 ميغابايت.');url=URL.createObjectURL(file);await setSource(url);}
  catch(e){if(url)URL.revokeObjectURL(url);status('تعذر فتح الصورة: '+e.message,true);}
};
$('demo').onclick=()=>setSource('demo.svg').catch(e=>status(e.message,true));
function process(){
  if(!source||busy||!glyphs)return;
  cancel();busy=true;dirty=true;selected=null;controls();
  const max=+$('resolution').value,scale=Math.min(1,max/Math.max(source.naturalWidth,source.naturalHeight));
  const w=Math.max(16,Math.round(source.naturalWidth*scale)),h=Math.max(16,Math.round(source.naturalHeight*scale));
  const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;
  const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.fillStyle='#fff';ctx.fillRect(0,0,w,h);ctx.drawImage(source,0,0,w,h);
  const pixels=ctx.getImageData(0,0,w,h).data;analysisRGBA=pixels.slice();
  status('بدء المحرك المحلي…');
  try{
    worker=new Worker(new URL('./worker.mjs',import.meta.url),{type:'module'});const active=worker;
    worker.onmessage=({data})=>{
      if(active!==worker)return;
      if(data.type==='progress')status(data.text);
      else if(data.type==='error'){busy=false;dirty=true;status(data.text,true);$('qa').textContent='لم تُعتمد ورقة ناقصة الترقيم. غيّري الإعدادات وأعيدي الإنشاء.';controls();}
      else if(data.type==='result'){
        result=data.result;history=[];busy=false;dirty=false;selected=null;
        $('time').textContent=(result.metrics.totalMS/1000).toFixed(2);$('cells').textContent=result.metrics.cells;
        $('missing').textContent=result.metrics.missing;$('changed').textContent=result.metrics.detailChangedPct.toFixed(2)+'%';
        $('palette').replaceChildren(...result.palette.map((color,i)=>{const el=document.createElement('span');el.className='swatch';
          const swatch=document.createElement('i');swatch.style.background='rgb('+color.join(',')+')';const code=document.createElement('b');code.textContent=result.symbols[i];
          el.append(swatch,code);el.title=catalog?.names[i]||color.join(',');return el;}));
        $('code').replaceChildren(...result.symbols.map((symbol,i)=>new Option(symbol,i)));
        $('selection').textContent='انقري خلية لفحص رمزها ومساحتها.';
        $('qa').textContent=`اجتازت ${result.metrics.cells} خلية فحص الرموز والتغطية. دُمج ${result.metrics.smallDetailsMerged} تفصيل صغير، ووُسّع ${result.metrics.thinDetailsWidened} موضع رفيع. راجعي الحل والتراكب قبل اعتماد الطباعة.`;
        setView('outline');status('اكتملت الورقة. كل خلية تحتوي رمزًا؛ راجعي مطابقة الحل والغموض البصري.');controls();
        if(innerWidth<740)$('status').scrollIntoView({block:'start',behavior:'smooth'});
      }
    };
    worker.onerror=e=>{if(active!==worker)return;busy=false;dirty=true;status('تعذر بدء العامل الخلفي. افتحي الأداة عبر HTTP(S). '+e.message,true);controls();};
    worker.postMessage({buffer:pixels.buffer,w,h,settings:settings(),glyphs},[pixels.buffer]);
  }catch(e){busy=false;dirty=true;status(e.message,true);controls();}
}
$('process').onclick=process;$('variant').onclick=()=>{seed+=13;process();};
$('cancel').onclick=()=>{cancel();dirty=true;status('أُلغيت المعالجة. الصورة محفوظة ويمكن إعادة المحاولة.');controls();};
document.querySelectorAll('.setting').forEach(n=>n.oninput=()=>{if(result){dirty=true;status('تغيّرت الإعدادات. أعيدي الإنشاء لتحديث الورقة.');}controls();});
document.querySelectorAll('[data-view]').forEach(n=>n.onclick=()=>setView(n.dataset.view));
function render(){
  const art=$('art');$('overlayControl').hidden=view!=='overlay'||!result;
  if(!source)return;
  if(view==='source'||!result){art.replaceChildren();const img=new Image();img.src=sourceURL;img.alt='الصورة الأصلية';img.className='source';art.append(img);return;}
  if(view==='compare'){
    art.innerHTML='<div class="compare"><figure><figcaption>الصورة الأصلية</figcaption><img alt="الصورة الأصلية"></figure><figure><figcaption>الحل الناتج</figcaption>'+pageSVG(result,'solution')+'</figure></div>';
    art.querySelector('img').src=sourceURL;
  }else if(view==='overlay'){
    art.innerHTML='<div class="overlay"><img alt="الصورة الأصلية"><div class="solution">'+croppedSolution(result)+'</div></div>';
    art.querySelector('img').src=sourceURL;art.querySelector('.solution').style.opacity=+$('opacity').value/100;
  }else art.innerHTML=pageSVG(result,view,true,selected);
}
$('opacity').oninput=()=>{const node=$('art').querySelector('.solution');if(node)node.style.opacity=+$('opacity').value/100;};
function select(id){
  if(!result||busy||dirty)return;const c=result.cells.find(c=>c.id===id);if(!c)return;
  selected=id;$('selection').textContent=`الخلية ${id} · الرمز ${c.label.code} · ${c.areaMM2.toFixed(2)} مم² · ${c.label.pt} نقطة`;
  $('code').selectedIndex=c.color;controls();render();
}
$('art').onclick=e=>{const target=e.target.closest?.('[data-region]');if(target)select(+target.dataset.region);};
$('art').onkeydown=e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('[data-region]')){e.preventDefault();select(+e.target.dataset.region);}};
function updateColorAudit(){
  const colors=new Uint8Array(result.cells.length+1);for(const c of result.cells)colors[c.id]=c.color;
  const labels=Uint8Array.from(result.regionMap,id=>colors[id]);result.metrics.colorError=colorAudit(analysisRGBA,labels,result.palette);
  result.metrics.manualCodeChanges=history.length;
}
$('recode').onclick=()=>{
  if(selected===null||busy||dirty)return;const cell=result.cells.find(c=>c.id===selected),color=$('code').selectedIndex;if(color===cell.color)return;
  const code=result.symbols[color],g=result.glyphs[code],p=cell.label,em=p.pt*25.4/72/result.mm;
  const pad=(result.settings.stroke/2+.15+result.settings.curveBoundMM)/result.mm+.72;
  const angle=[p.angle,0,90,45,-45].find(a=>fitsInk(result.regionMap,result.w,result.h,cell.id,p.x,p.y,em*g.width/2+pad,em*g.height/2+pad,a));
  if(angle===undefined){status('الرمز الجديد أعرض من المكان المتاح. لم يتغير اللون؛ اختاري رمزًا آخر.',true);return;}
  history.push({id:cell.id,color:cell.color,label:{...p}});if(history.length>8)history.shift();cell.color=color;cell.label={...p,angle,code};
  updateColorAudit();render();controls();status('تغيّر الرمز ولون الحل يدويًا. راجعي المقارنة.');
};
$('undo').onclick=()=>{const previous=history.pop();if(!previous||busy||dirty)return;const c=result.cells.find(c=>c.id===previous.id);c.color=previous.color;c.label=previous.label;selected=null;updateColorAudit();render();controls();status('استُعيد اللون والرمز السابقان.');};
$('catalog').onchange=async()=>{
  const file=$('catalog').files[0];if(!file)return;
  try{
    if(file.size>65536)throw Error('حجم الملف أكبر من64 كيلوبايت.');
    const value=JSON.parse(await file.text());if(!Array.isArray(value.colors)||!value.colors.length||value.colors.length>32)throw Error('يلزم1–32 لونًا.');
    const colors=value.colors.map(item=>{const hex=typeof item==='string'?item:item.hex;if(!/^#[\da-f]{6}$/i.test(hex))throw Error('استخدمي #RRGGBB.');return [1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));});
    if(new Set(colors.map(c=>c.join(','))).size!==colors.length)throw Error('توجد ألوان مكررة.');
    catalog={name:String(value.name||'لوحة الأقلام').slice(0,60),colors,names:value.colors.map((c,i)=>String(typeof c==='object'?c.name||SYMBOLS[i]:SYMBOLS[i]).slice(0,60))};
    $('catalogName').textContent=catalog.name+' · '+colors.length+' لونًا';$('clearCatalog').hidden=false;if(result)dirty=true;controls();
  }catch(e){status('تعذر استيراد اللوحة: '+e.message,true);}
};
$('clearCatalog').onclick=()=>{catalog=null;$('catalog').value='';$('catalogName').textContent='استخراج الألوان من الصورة';$('clearCatalog').hidden=true;if(result)dirty=true;controls();};
function download(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),3000);}
const exportMode=()=>['solution','compare','overlay','source'].includes(view)?'solution':'outline';
$('svg').onclick=()=>{if(result&&!dirty&&!busy)download(new Blob([pageSVG(result,exportMode())],{type:'image/svg+xml'}),'flow-studio-'+exportMode()+'.svg');};
$('pdf').onclick=()=>{if(!result||dirty||busy)return;try{download(pagePDF(result,exportMode()),'flow-studio-'+exportMode()+'.pdf');}catch(e){status('تعذر إنشاء PDF: '+e.message,true);}};
$('report').onclick=()=>{if(result&&!dirty&&!busy)download(new Blob([JSON.stringify({engine:result.engine,settings:result.settings,palette:result.palette,symbols:result.symbols,metrics:result.metrics},null,2)],{type:'application/json'}),'flow-studio-report.json');};
$('print').onclick=()=>{
  if(!result||dirty||busy)return;const popup=window.open('','_blank');if(!popup){status('اسمحي بفتح نافذة الطباعة ثم أعيدي المحاولة.',true);return;}
  const [w,h]=result.paper;popup.document.write(`<!doctype html><html><meta charset="utf-8"><title>Flow Studio</title><style>@page{size:${w}mm ${h}mm;margin:0}body{margin:0}svg{display:block;width:${w}mm;height:${h}mm}.help{padding:15px;direction:rtl;font:14px Arial}@media print{.help{display:none}}</style><div class="help"><button onclick="window.print()">طباعة</button> الحجم الفعلي100%، دون رأس أو تذييل.</div>${pageSVG(result,exportMode())}</html>`);popup.document.close();
};
loadFont().then(value=>{glyphs=value;controls();}).catch(e=>status('تعذر تحميل خط الرموز؛ أعيدي تحميل الموقع. '+e.message,true));
controls();if(location.protocol==='file:')status('شغّلي الموقع عبر HTTP(S)؛ فتح index.html مباشرة لا يشغّل العامل الخلفي.',true);
