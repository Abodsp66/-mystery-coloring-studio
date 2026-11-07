let fontData='';
export async function loadFont(){
  const response=await fetch('fonts/FlowSymbols.ttf');if(!response.ok)throw Error('تعذر تحميل خط الرموز.');
  const bytes=await response.arrayBuffer(),face=await new FontFace('Flow Symbols',bytes).load();document.fonts.add(face);
  fontData=btoa(String.fromCharCode(...new Uint8Array(bytes)));
  await document.fonts.load('1000px "Flow Symbols"','123456789ABCDEFGHJKLMNPQRSTUVWXYZ');
  const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');ctx.font='1000px "Flow Symbols"';
  return Object.fromEntries([...'123456789ABCDEFGHJKLMNPQRSTUVWXYZ'].map(code=>{
    const m=ctx.measureText(code);return [code,{width:(m.actualBoundingBoxLeft+m.actualBoundingBoxRight)/1000,
      height:(m.actualBoundingBoxAscent+m.actualBoundingBoxDescent)/1000,
      cx:(m.actualBoundingBoxRight-m.actualBoundingBoxLeft)/2000,cy:(m.actualBoundingBoxDescent-m.actualBoundingBoxAscent)/2000}];
  }));
}
const rgb=c=>'rgb('+c.join(',')+')';
export const groups=r=>r.palette.map((_,i)=>r.cells.filter(c=>c.color===i).map(c=>c.path).join(''));
export function croppedSolution(r){
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${r.w} ${r.h}" width="${r.w}" height="${r.h}">${groups(r).map((path,i)=>`<path d="${path}" fill="${rgb(r.palette[i])}" fill-rule="evenodd"/>`).join('')}</svg>`;
}
export function pageSVG(r,mode='outline',interactive=false,selected=null){
  if(!r.metrics.printReady||r.metrics.missing)throw Error('الورقة لم تجتز فحص الترقيم.');
  const [pw,ph]=r.paper,[ox,oy]=r.offset,scale=r.mm;
  const out=[`<svg xmlns="http://www.w3.org/2000/svg" width="${pw}mm" height="${ph}mm" viewBox="0 0 ${pw} ${ph}" role="img" aria-label="ورقة انسياب"><defs><style>@font-face{font-family:'Flow Symbols';src:url(data:font/ttf;base64,${fontData}) format('truetype')}</style></defs><rect width="${pw}" height="${ph}" fill="white"/><g transform="translate(${ox} ${oy}) scale(${scale})">`];
  if(mode==='solution')groups(r).forEach((path,i)=>out.push(`<path d="${path}" fill="${rgb(r.palette[i])}" fill-rule="evenodd"/>`));
  else{
    out.push(`<path d="${r.network}" fill="none" stroke="#919b98" stroke-width="${r.settings.stroke/scale}" stroke-linejoin="round" stroke-linecap="round"/>`);
    for(const cell of r.cells){const p=cell.label,g=r.glyphs[p.code],em=p.pt*25.4/72/scale;
      out.push(`<text data-code="${p.code}" transform="translate(${p.x} ${p.y}) rotate(${p.angle})" x="${-em*g.cx}" y="${-em*g.cy}" font-family="Flow Symbols" font-size="${em}" fill="#626d67" pointer-events="none">${p.code}</text>`);
    }
  }
  if(interactive)for(const c of r.cells)out.push(`<path data-region="${c.id}" d="${c.path}" fill="transparent" fill-rule="evenodd" stroke="${c.id===selected?'#2178a0':'none'}" stroke-width="${.3/scale}" pointer-events="all" tabindex="0" role="button" aria-label="الخلية ${c.id}، الرمز ${c.label.code}"/>`);
  out.push('</g>');
  const perRow=16,rows=Math.ceil(r.palette.length/perRow),n=Math.min(perRow,r.palette.length),sw=Math.min(11,(pw-30)/n),start=(pw-sw*n)/2;
  r.palette.forEach((c,i)=>{const x=start+(i%perRow)*sw,y=ph-(rows>1?38:28)+Math.floor(i/perRow)*10;
    out.push(`<rect x="${x+1}" y="${y}" width="${sw-2}" height="4.5" fill="${rgb(c)}" stroke="#b0b8b2" stroke-width=".1"/><text x="${x+sw/2}" y="${y+8}" text-anchor="middle" font-family="Flow Symbols" font-size="2.6" fill="#334d48">${r.symbols[i]}</text>`);
  });
  out.push(`<text x="${pw/2}" y="${ph-11}" font-family="Arial,sans-serif" font-size="1.9" fill="#73817a" text-anchor="middle">FLOW STUDIO 1.0 | ${r.metrics.cells} CELLS | ALL REGIONS CODED | PRINT 100%</text></svg>`);
  return out.join('');
}
function pdfPath(doc,data,mm,ox,oy){
  const tokens=data.match(/[MLCZ]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?/g)||[],ops=[];
  for(let i=0;i<tokens.length;){const op=tokens[i++],n={M:2,L:2,C:6,Z:0}[op];if(n===undefined)throw Error('مسار غير صالح.');
    const c=tokens.slice(i,i+n).map(Number);i+=n;if(c.length!==n||!c.every(Number.isFinite))throw Error('إحداثيات غير صالحة.');
    ops.push({op:{M:'m',L:'l',C:'c',Z:'h'}[op],c:c.map((v,j)=>v*mm+(j%2?oy:ox))});
  }
  doc.path(ops);
}
export function pagePDF(r,mode='outline'){
  if(!r.metrics.printReady||r.metrics.missing)throw Error('الورقة غير مكتملة الترقيم.');
  const [pw,ph]=r.paper,[ox,oy]=r.offset;
  const doc=new globalThis.jspdf.jsPDF({unit:'mm',format:[pw,ph],orientation:pw>ph?'landscape':'portrait',precision:6,compress:true,putOnlyUsedFonts:true});
  doc.addFileToVFS('FlowSymbols.ttf',fontData);doc.addFont('FlowSymbols.ttf','FlowSymbols','normal');doc.setFont('FlowSymbols','normal');
  doc.setProperties({title:'Flow Studio — '+mode,subject:'Independent continuous-flow coloring; all regions coded'});
  doc.setLineCap('round');doc.setLineJoin('round');
  if(mode==='solution')groups(r).forEach((path,i)=>{if(path){doc.setFillColor(...r.palette[i]);pdfPath(doc,path,r.mm,ox,oy);doc.fillEvenOdd();}});
  else{
    doc.setDrawColor('#919b98');doc.setLineWidth(r.settings.stroke);pdfPath(doc,r.network,r.mm,ox,oy);doc.stroke();
    for(const c of r.cells){const p=c.label,g=r.glyphs[p.code],em=p.pt*25.4/72,a=p.angle*Math.PI/180;
      const x=ox+p.x*r.mm-em*g.cx*Math.cos(a)+em*g.cy*Math.sin(a);
      const y=oy+p.y*r.mm-em*g.cx*Math.sin(a)-em*g.cy*Math.cos(a);
      doc.setFont('FlowSymbols','normal');doc.setFontSize(p.pt);doc.setTextColor('#626d67');doc.text(p.code,x,y,{angle:-p.angle,baseline:'alphabetic'});
    }
  }
  const perRow=16,rows=Math.ceil(r.palette.length/perRow),n=Math.min(perRow,r.palette.length),sw=Math.min(11,(pw-30)/n),start=(pw-sw*n)/2;
  r.palette.forEach((color,i)=>{const x=start+(i%perRow)*sw,y=ph-(rows>1?38:28)+Math.floor(i/perRow)*10;
    doc.setFillColor(...color);doc.setDrawColor('#b0b8b2');doc.setLineWidth(.1);doc.rect(x+1,y,sw-2,4.5,'FD');
    doc.setFont('FlowSymbols','normal');doc.setFontSize(2.6*72/25.4);doc.setTextColor('#334d48');doc.text(r.symbols[i],x+sw/2,y+8,{align:'center'});
  });
  doc.setFont('helvetica','normal');doc.setFontSize(1.9*72/25.4);doc.setTextColor('#73817a');
  doc.text(`FLOW STUDIO 1.0 | ${r.metrics.cells} CELLS | ALL REGIONS CODED | PRINT 100%`,pw/2,ph-11,{align:'center'});
  return doc.output('blob');
}
