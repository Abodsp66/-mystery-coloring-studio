'use strict';
const $=id=>document.getElementById(id),symbols=Array.from({length:48},(_,i)=>String(i+1));
let source=null,result=null,worker=null,busy=false,dirty=false,view='outline',selected=null,sourceURL=null,clientQA=null;
let elapsedTimer=null,runStarted=0;
function trackElapsed(){if(busy&&!elapsedTimer){runStarted=performance.now();elapsedTimer=setInterval(()=>{$('elapsed').textContent=Math.floor((performance.now()-runStarted)/1000);},1000);}else if(!busy&&elapsedTimer){clearInterval(elapsedTimer);elapsedTimer=null;}}
let glyphs={},fontLoaded=false,fixedPalette=null;
Studio.fontReady.then(()=>{
 const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');ctx.font='1000px "Studio Digits"';
 glyphs=Object.fromEntries(symbols.map(ch=>{const m=ctx.measureText(ch);return[ch,{width:(m.actualBoundingBoxLeft+m.actualBoundingBoxRight)/1000,height:(m.actualBoundingBoxAscent+m.actualBoundingBoxDescent)/1000,cx:(m.actualBoundingBoxRight-m.actualBoundingBoxLeft)/2000,cy:(m.actualBoundingBoxDescent-m.actualBoundingBoxAscent)/2000}];}));
 fontLoaded=true;controls();
}).catch(e=>{status('تعذر بدء خط الرموز. افتح الموقع عبر HTTP وأعد التحميل. '+e.message,true);controls();});
function strokeMM(){return Math.max(.06,Math.min(.25,+$('lineWidth').value||.16));}
function exportQA(){return Studio.exportCheck(result,strokeMM());}
function updatePrintReadiness(){
 if(!result)return;
 if(dirty){$('printState').textContent='تغيّرت الإعدادات؛ أعد الإنشاء لتحديث فحص الطباعة.';$('printState').classList.add('review');return;}
 const check=exportQA(),qa=result.metrics.printQA;
 const reasons=[];
 if(check.unresolvedCells)reasons.push(check.unresolvedCells+' خلية أصلية لا تتسع لرمز');
 if(qa.labelConflictIds.length)reasons.push('تداخل رموز يحتاج مراجعة');
 if(!check.strokeSafe)reasons.push('سماكة الخط تقلل الفراغ الآمن حول الرموز؛ خفّضها أو أعد الإنشاء');
 $('printState').textContent=check.ready?'اجتازت الورقة فحص اتساع الرموز والفراغات. راجع مطابقة الحل والغموض قبل الطباعة.':'مسودة تحتاج مراجعة: '+reasons.join(' · ');
 $('printState').classList.toggle('review',!check.ready);$('pdf').textContent=check.ready?'تنزيل PDF':'تنزيل مسودة PDF';
 $('svg').textContent=['solution','compare','overlay'].includes(view)?'تنزيل الحل SVG':check.ready?'تنزيل SVG':'تنزيل مسودة SVG';
}
function markSettingsDirty(){if(result){dirty=true;updatePrintReadiness();status('تغيّرت الخيارات. أعد الإنشاء لتطبيقها على النتيجة.',true);}controls();}
$('paletteFile').onchange=async()=>{
 const file=$('paletteFile').files[0];if(!file)return;
 try{
  if(file.size>65536)throw Error('ملف اللوحة أكبر من 64 كيلوبايت.');
  const parsed=Studio.parsePalette(JSON.parse(await file.text()));parsed.previousColorLimit=fixedPalette?.previousColorLimit||$('colors').value;fixedPalette=parsed;if(!$('catalogOption')){const option=new Option('لوحة الأقلام','catalog');option.id='catalogOption';$('colors').append(option);}$('catalogOption').textContent=parsed.colors.length+' · لوحة الأقلام';$('colors').value='catalog';
  $('paletteName').textContent=parsed.name+' · '+parsed.colors.length+' لونًا';$('clearPalette').hidden=false;markSettingsDirty();
 }catch(e){status('تعذر قراءة لوحة الأقلام: '+e.message,true);}
};
$('clearPalette').onclick=()=>{const limit=fixedPalette?.previousColorLimit||'18';fixedPalette=null;$('catalogOption')?.remove();$('colors').value=limit;$('paletteFile').value='';$('paletteName').textContent='استخراج الألوان من الصورة';$('clearPalette').hidden=true;markSettingsDirty();};
function status(t,w=false){$('status').textContent=t;$('status').classList.toggle('warn',w);}
function controls(){trackElapsed();const ok=!!result&&!busy&&!dirty;document.querySelectorAll('.setting').forEach(e=>e.disabled=busy);$('process').disabled=!source||busy||!fontLoaded;$('colors').disabled=busy||!!fixedPalette;if(fixedPalette)$('colors').value='catalog';$('paletteFile').disabled=busy;$('clearPalette').disabled=busy;$('colorsVal').textContent=fixedPalette?fixedPalette.colors.length:$('colors').value;$('cancel').hidden=!busy;for(const id of ['svg','pdf','print','report'])$(id).disabled=!ok;$('recode').disabled=!ok||selected===null;$('recodeColor').disabled=$('recode').disabled;$('merge').disabled=$('recode').disabled;$('undo').disabled=!ok||!result?.metrics.historyDepth;$('reviewCells').disabled=!ok||!result?.metrics.missing;}
function config(){const detail=$('detailMode').value;let paper=$('paper').value==='A3'?[297,420]:[210,297];if($('orientation').value==='landscape')paper.reverse();return{paper,colors:fixedPalette?fixedPalette.colors.length:+$('colors').value,fixedPalette:fixedPalette?.colors||null,paletteNames:fixedPalette?.names||null,paletteName:fixedPalette?.name||null,minFont:Math.max(4.5,Math.min(9,+$('font').value||5)),lineWidth:strokeMM(),density:+$('density').value,denoise:$('denoise').value==='light',cleanEdges:$('cleanEdges').value==='on',detailBoost:detail!=='quick',edgeGuard:detail==='maximum'?.30:detail==='balanced'?.43:.55,seed:99};}
function stop(){worker?.terminate();worker=null;busy=false;controls();}
// Handle startup failures explicitly: file:// cannot load a Web Worker in most browsers.
function sendWorker(payload,transfers=[]){
  try{
    if(location.protocol==='file:')throw new Error('فُتحت الأداة من ملف محلي (file://). افتح RUN-WINDOWS.cmd الموجود بجوار مجلد dist، أو شغّل خادم localhost، ثم افتح الصفحة من http://127.0.0.1.');
    const active=getWorker();
    active.postMessage(payload,transfers);
  }catch(e){
    busy=false;
    const reason=String(e?.message||e);
    status('لم تبدأ المعالجة: '+reason,true);
    controls();
  }
}
function getWorker(){if(worker)return worker;worker=new Worker('worker.js');const own=worker;worker.onmessage=({data})=>{if(own!==worker)return;if(data.type==='progress')status(data.text);else if(data.type==='error'){busy=false;status('تعذرت المعالجة: '+data.text,true);controls();}else if(data.type==='result'){result=data.result;busy=false;dirty=false;selected=null;$('selection').textContent='انقر خلية في المعاينة لعرض معلوماتها.';render();status(data.action==='undo'?'استُعيدت الحالة السابقة. راجع النتيجة قبل التصدير.':data.action==='merge'?'تم الدمج داخل اللون نفسه. حُدّث فحص الطباعة.':data.action==='recode'?'تغيّر الرمز يدويًا. راجع مطابقة الحل بالأصل.':result.metrics.missing?`اكتمل التحويل. توجد ${result.metrics.missing} منطقة صغيرة دون رمز؛ راجعها في الفحص قبل الطباعة.`:'اكتمل إنشاء الورقة. افحص الملامح بالتراكب الشفاف قبل الطباعة.');controls();auditSourceFidelity(result);}};worker.onerror=e=>{busy=false;status('تعذر تشغيل المحرك. تحقق من الاتصال وأعد المحاولة. '+(e.message||''),true);worker.terminate();worker=null;controls();};return worker;}
function setSource(im,url){stop();source=im;sourceURL=url;result=null;clientQA=null;dirty=false;selected=null;$('palette').replaceChildren();for(const id of ['regionCount','colorCount','badCount','elapsed','colorError','edgeRecall'])$(id).textContent='—';$('printState').textContent='يظهر فحص الطباعة بعد إنشاء الورقة.';$('art').replaceChildren();const el=document.createElement('img');el.src=url;el.alt='الصورة الأصلية';$('art').append(el);$('selection').textContent='أنشئ الورقة لتحديد الخلايا.';$('reviewCells').replaceChildren(new Option('لا توجد نتيجة',''));status('الصورة جاهزة. اضبط الخيارات ثم اضغط إنشاء ورقة التلوين.');controls();}
$('file').onchange=async()=>{const f=$('file').files[0];if(!f)return;if(f.size>40*1024*1024){status('اختر صورة أصغر من 40 ميغابايت.',true);return;}const url=URL.createObjectURL(f);try{const im=new Image();im.src=url;await im.decode();if(!im.naturalWidth||!im.naturalHeight)throw Error();if(sourceURL?.startsWith('blob:'))URL.revokeObjectURL(sourceURL);setSource(im,url);}catch{URL.revokeObjectURL(url);status('تعذر قراءة الصورة. استخدم PNG أو JPG أو WEBP.',true);}};
$('demo').onclick=()=>{$('colors').value=8;$('colorsVal').textContent='8';const c=document.createElement('canvas');c.width=420;c.height=560;const x=c.getContext('2d');x.fillStyle='#e8d7b7';x.fillRect(0,0,420,560);x.fillStyle='#8eb7ad';x.beginPath();x.arc(210,245,170,Math.PI,0);x.lineTo(380,560);x.lineTo(40,560);x.fill();x.fillStyle='#506d52';x.lineWidth=14;x.strokeStyle='#506d52';x.beginPath();x.moveTo(210,530);x.bezierCurveTo(230,400,170,290,210,200);x.stroke();for(const[cx,cy,a]of [[170,400,-.6],[252,350,.5]]){x.save();x.translate(cx,cy);x.rotate(a);x.beginPath();x.ellipse(0,0,66,24,0,0,Math.PI*2);x.fill();x.restore();}for(let i=0;i<7;i++){const a=i*Math.PI*2/7;x.fillStyle=i%2?'#d58c78':'#c86558';x.beginPath();x.ellipse(210+64*Math.cos(a),205+64*Math.sin(a),53,32,a,0,Math.PI*2);x.fill();}x.fillStyle='#d9af55';x.beginPath();x.arc(210,205,35,0,Math.PI*2);x.fill();const im=new Image(),url=c.toDataURL();im.onload=()=>setSource(im,url);im.src=url;};
$('process').onclick=()=>{if(!source||busy||!fontLoaded)return;busy=true;dirty=true;selected=null;controls();const max=+$('resolution').value,ratio=Math.min(1,max/Math.max(source.naturalWidth,source.naturalHeight)),w=Math.max(8,Math.round(source.naturalWidth*ratio)),h=Math.max(8,Math.round(source.naturalHeight*ratio));const c=document.createElement('canvas');c.width=w;c.height=h;const x=c.getContext('2d',{willReadFrequently:true});x.fillStyle='white';x.fillRect(0,0,w,h);x.drawImage(source,0,0,w,h);const buffer=x.getImageData(0,0,w,h).data.buffer;status('بدء المعالجة… يمكنك إلغاؤها دون فقد الصورة.');sendWorker({type:'process',w,h,buffer,settings:config(),glyphs},[buffer]);};
$('cancel').onclick=()=>{stop();dirty=true;status('أُلغيت المعالجة. الصورة محفوظة ويمكن إعادة المحاولة.');controls();};
document.querySelectorAll('.setting').forEach(e=>e.oninput=markSettingsDirty);
const rgb=a=>'rgb('+a.join(',')+')';
function svgCroppedSolution(r){return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${r.w} ${r.h}" width="${r.w}" height="${r.h}"><rect width="100%" height="100%" fill="white"/>${r.solutionPaths.map((path,i)=>`<path d="${path}" fill="${rgb(r.palette[i])}" stroke="${rgb(r.palette[i])}" stroke-width=".04" fill-rule="evenodd"/>`).join('')}</svg>`;}
function svgText(mode='outline',interactive=false){if(!result)return '';const r=result,[pw,ph]=r.settings.paper,ox=(pw-r.w*r.mm)/2,scale=r.mm;
const s=[`<svg xmlns="http://www.w3.org/2000/svg" width="${pw}mm" height="${ph}mm" viewBox="0 0 ${pw} ${ph}">${Studio.fontStyle()}<rect width="100%" height="100%" fill="white"/><g transform="translate(${ox} 12) scale(${scale})">`];
if(mode==='solution')r.solutionPaths.forEach((path,i)=>s.push(`<path d="${path}" fill="${rgb(r.palette[i])}" stroke="${rgb(r.palette[i])}" stroke-width=".05" fill-rule="evenodd"/>`));
else{s.push(`<path d="${r.network}" fill="none" stroke="${$('lineTone').value}" stroke-width="${strokeMM()/scale}" stroke-linejoin="round" stroke-linecap="round"/>`);for(const c of r.cells){const p=c.label;if(p){const g=r.glyphs[symbols[c.color]],size=p.pt*25.4/72/scale;s.push(`<text transform="translate(${p.x} ${p.y}) rotate(${p.angle})" x="${-size*g.cx}" y="${-size*g.cy}" font-family="Studio Digits,sans-serif" font-size="${size}" fill="#4e5752" pointer-events="none">${symbols[c.color]}</text>`);}else if(mode==='audit')s.push(`<path d="${c.path}" fill="#ee5b5022" stroke="#d34f45" stroke-width="${.18/scale}"/><circle cx="${c.anchor[0]}" cy="${c.anchor[1]}" r="${1/scale}" fill="none" stroke="#d34f45" stroke-width="${.2/scale}"/>`);}}
if(interactive)for(const c of r.cells)s.push(`<path data-id="${c.id}" d="${c.path}" fill="transparent" stroke="${c.id===selected?'#167bba':'none'}" stroke-width="${.35/scale}" fill-rule="evenodd" pointer-events="all"/>`);
s.push('</g>');const rowSize=24,rows=Math.ceil(r.palette.length/rowSize),sw=Math.min(10,(pw-24)/Math.min(rowSize,r.palette.length)),start=(pw-sw*Math.min(rowSize,r.palette.length))/2;r.palette.forEach((color,i)=>{const col=i%rowSize,row=Math.floor(i/rowSize),x=start+col*sw,y=ph-(rows>1?38:28)+row*10;s.push(`<rect x="${x+1}" y="${y}" width="${sw-2}" height="5" fill="${rgb(color)}" stroke="#bbb" stroke-width=".1"/><text x="${x+sw/2}" y="${y+9}" font-family="Studio Digits,sans-serif" font-size="2.7" text-anchor="middle" fill="#333">${symbols[i]}</text>`)});s.push(`<text x="${pw/2}" y="${ph-12}" font-family="Studio Digits,sans-serif" font-size="2" fill="#555" text-anchor="middle">V6 | ${exportQA().ready?'GEOMETRY CHECKED':'DRAFT - REVIEW'} | ${r.metrics.cells} cells | ${r.metrics.missing} unnumbered | Print 100%</text></svg>`);return s.join('');}
function render(){if(!result)return;const r=result;$('regionCount').textContent=r.metrics.cells;$('colorCount').textContent=r.palette.length;$('badCount').textContent=r.metrics.missing;$('elapsed').textContent=r.metrics.seconds;$('palette').replaceChildren();r.palette.forEach((color,i)=>{const span=document.createElement('span');span.className='swatch';const box=document.createElement('i');box.style.cssText=`background:${rgb(color)};display:block;width:28px;height:28px;border:1px solid #ccc;border-radius:5px`;span.append(box,document.createTextNode(symbols[i]));$('palette').append(span);});$('recodeColor').replaceChildren(...r.palette.map((c,i)=>new Option(symbols[i],i)));$('reviewCells').replaceChildren(new Option(r.metrics.missing?'اختر خلية غير مرقمة':'كل الخلايا مرقمة',''),...r.cells.filter(c=>!c.label).map(c=>new Option('الخلية '+c.id+' · الرمز '+symbols[c.color]+' · '+c.areaMM2.toFixed(2)+' مم²',String(c.id))));$('quality').textContent=r.metrics.missing?`النتيجة تحتاج مراجعة: ${r.metrics.missing} خلية دون رمز. التصدير لا يزيلها.`:'الرموز تتسع هندسيًا؛ راجع تفاصيل الحل قبل الطباعة.';renderArt();}
function renderArt(){if(!result)return;updatePrintReadiness();const a=$('art');a.style.width=$('zoom').value==='fit'?'100%':`${600*+$('zoom').value}px`;a.style.maxWidth=$('zoom').value==='fit'?'100%':'none';if(view==='overlay'){a.innerHTML=`<div class="overlayCompare"><img class="overlaySource" src="${sourceURL}" alt="الصورة الأصلية"><div id="overlaySolution">${svgCroppedSolution(result)}</div></div>`;$('overlaySolution').style.opacity=(+$('compareBlend').value/100);}else if(view==='compare'){a.innerHTML='<div class="compare"><figure><figcaption>الأصل</figcaption><img id="originalCompare" alt="الصورة الأصلية"></figure><figure><figcaption>الحل الملون</figcaption>'+svgText('solution')+'</figure></div>';$('originalCompare').src=sourceURL;}else a.innerHTML=svgText(view,true);}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{view=b.dataset.view;document.querySelectorAll('[data-view]').forEach(e=>e.classList.toggle('active',e===b));renderArt();});$('zoom').onchange=renderArt;$('compareBlend').oninput=()=>{const el=$('overlaySolution');if(el)el.style.opacity=(+$('compareBlend').value/100);};
function selectCell(id){
 if(!result||busy||dirty)return;const c=result.cells.find(c=>c.id===id);if(!c)return;
 selected=id;$('selection').textContent=`الخلية ${id} · الرمز ${symbols[c.color]} · ${c.areaMM2.toFixed(2)} مم² · ${c.label?c.label.pt+' نقطة':'لا تتسع لرمز داخلي'}`;
 $('recodeColor').value=String(c.color);controls();renderArt();
}
$('art').onclick=e=>{const hit=e.target.closest?.('[data-id]');if(hit)selectCell(+hit.dataset.id);};
$('reviewCells').onchange=()=>{if(!$('reviewCells').value)return;view='audit';document.querySelectorAll('[data-view]').forEach(e=>e.classList.toggle('active',e.dataset.view===view));selectCell(+$('reviewCells').value);};
$('merge').onclick=()=>{if(selected===null||busy||dirty)return;busy=true;controls();status('دمج خليتين متجاورتين من اللون نفسه، دون تغيير اتحاد اللون…');sendWorker({type:'merge',id:selected});};
$('undo').onclick=()=>{if(busy||dirty||!result?.metrics.historyDepth)return;busy=true;controls();status('استعادة الحالة السابقة للتعديل…');sendWorker({type:'undo'});};
$('recode').onclick=()=>{if(selected===null||busy||dirty)return;busy=true;controls();status('تغيير رمز الخلية وفحص اتساعه، دون تغيير حدودها…');sendWorker({type:'recode',id:selected,color:+$('recodeColor').value});};
function download(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),5000);}
$('svg').onclick=()=>{if(result&&!busy&&!dirty)download(new Blob([svgText(['compare','overlay'].includes(view)?'solution':view)],{type:'image/svg+xml;charset=utf-8'}),'mystery-v6-'+(['compare','overlay'].includes(view)?'solution':view)+'.svg');};
$('pdf').onclick=async()=>{
 if(!result||busy||dirty)return;const own=result,mode=['compare','overlay'].includes(view)?'solution':view;
 $('pdf').disabled=true;
 try{const blob=await StudioPDF.create(own,mode,strokeMM(),$('lineTone').value,exportQA());if(own===result&&!busy&&!dirty)download(blob,'mystery-v6-'+mode+'.pdf');}
 catch(e){status('تعذر إنشاء PDF: '+String(e.message||e),true);}finally{controls();}
};
$('report').onclick=()=>{if(result&&!busy&&!dirty)download(new Blob([JSON.stringify({engine:result.engine,settings:result.settings,metrics:result.metrics,palette:result.palette,clientFidelity:clientQA,exportQA:exportQA(),unresolved:result.cells.filter(c=>!c.label).map(c=>({id:c.id,code:symbols[c.color],areaMM2:c.areaMM2,anchor:c.anchor}))},null,2)],{type:'application/json'}),'mystery-v6-report.json');};
$('print').onclick=()=>{if(!result||busy||dirty)return;const win=window.open('','_blank');if(!win){status('اسمح بفتح نافذة الطباعة ثم أعد المحاولة.',true);return;}const[pw,ph]=result.settings.paper;win.document.write(`<!doctype html><html><meta charset="utf-8"><title>مرسم الأرقام — طباعة</title><style>@page{size:${pw}mm ${ph}mm;margin:0}body{margin:0}svg{display:block;width:${pw}mm;height:${ph}mm}.help{direction:rtl;padding:16px;font:16px Arial;background:#eee}@media print{.help{display:none}}</style><div class="help"><button onclick="window.print()">طباعة / حفظ PDF</button> اختر الحجم الفعلي 100% وألغِ الرأس والتذييل. ${result.metrics.missing?'تنبيه: '+result.metrics.missing+' خلية دون رمز.':''}</div>${svgText(['compare','overlay'].includes(view)?'solution':view)}</html>`);win.document.close();};
$('reference').onclick=()=>$('referenceDialog').showModal();$('closeReference').onclick=()=>$('referenceDialog').close();controls();if(location.protocol==='file:')status('طريقة التشغيل الحالية (file://) تمنع محرك التقسيم. شغّل RUN-WINDOWS.cmd بدل فتح index.html مباشرة.',true);

$('lineWidth').oninput=()=>{renderArt();updatePrintReadiness();};$('lineTone').onchange=renderArt;

// Independent client-side visual audit: compare the actual SVG solution rendering
// against the input, rather than only asserting that polygons cover the page.
async function auditSourceFidelity(r){
  try{
    const factor=Math.min(1,440/Math.max(r.w,r.h)),w=Math.max(16,Math.round(r.w*factor)),h=Math.max(16,Math.round(r.h*factor));
    const a=document.createElement('canvas'),b=document.createElement('canvas');a.width=b.width=w;a.height=b.height=h;
    const ca=a.getContext('2d',{willReadFrequently:true}),cb=b.getContext('2d',{willReadFrequently:true});
    ca.fillStyle='#fff';ca.fillRect(0,0,w,h);ca.drawImage(source,0,0,w,h);
    const body=svgCroppedSolution(r);
    const blob=new Blob([body],{type:'image/svg+xml'}),url=URL.createObjectURL(blob);
    try{
      const im=new Image();im.src=url;await im.decode();cb.drawImage(im,0,0,w,h);
    }finally{URL.revokeObjectURL(url);}
    if(r!==result)return;
    const A=ca.getImageData(0,0,w,h).data,B=cb.getImageData(0,0,w,h).data;
    let err=0,strong=0,matched=0;const l1=new Float32Array(w*h),l2=new Float32Array(w*h);
    for(let i=0,j=0;i<A.length;i+=4,j++){
      err+=Math.abs(A[i]-B[i])+Math.abs(A[i+1]-B[i+1])+Math.abs(A[i+2]-B[i+2]);
      l1[j]=.2126*A[i]+.7152*A[i+1]+.0722*A[i+2];
      l2[j]=.2126*B[i]+.7152*B[i+1]+.0722*B[i+2];
    }
    // A one-pixel tolerance is used because the output is vector antialiased.
    for(let y=2;y<h-2;y++)for(let x=2;x<w-2;x++){
      const i=y*w+x,gs=Math.max(Math.abs(l1[i]-l1[i-1]),Math.abs(l1[i]-l1[i-w]));
      if(gs<43)continue;strong++;let found=false;
      for(let dy=-1;dy<=1&&!found;dy++)for(let dx=-1;dx<=1;dx++){
        const j=i+dy*w+dx;
        if(Math.max(Math.abs(l2[j]-l2[j-1]),Math.abs(l2[j]-l2[j-w]))>=24){found=true;break;}
      }
      if(found)matched++;
    }
    clientQA={meanAbsoluteRGBError:Math.round(err/(3*w*h)*10)/10,strongEdgeRecallPct:strong?Math.round(matched/strong*100):null,sampleWidth:w,sampleHeight:h,note:'Approximate visual comparison after color reduction; not a guarantee of exact geometry or facial recognition.'};
    $('colorError').textContent=clientQA.meanAbsoluteRGBError.toFixed(1);
    $('edgeRecall').textContent=clientQA.strongEdgeRecallPct===null?'—':clientQA.strongEdgeRecallPct+'%';
    $('quality').textContent=`اختلاف اللون الوسطي ${clientQA.meanAbsoluteRGBError.toFixed(1)}/255 · استعادة الحواف القوية ${clientQA.strongEdgeRecallPct??'—'}% (تقدير بصري). ${r.metrics.missing?' توجد '+r.metrics.missing+' منطقة دون رمز.':'جميع الخلايا قابلة للترميز هندسيًا.'}${r.metrics.missing/r.metrics.cells>.2?' ⚠ الصورة غير جاهزة للطباعة بهذا التقسيم؛ خفف التعقيد أو استخدم رسمًا مبسطًا.':''}`;
  }catch(e){if(r===result){$('colorError').textContent='—';$('edgeRecall').textContent='—';}}
}
