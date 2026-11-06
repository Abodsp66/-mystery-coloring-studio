/* Real Python V5 geometry runs in this worker, never on the UI thread. */
let runtime;
async function boot(){
 if(runtime)return runtime;
 postMessage({type:'progress',text:'تحميل محرك الهندسة لأول مرة… قد يستغرق نحو دقيقة حسب الاتصال.'});
 importScripts('https://cdn.jsdelivr.net/pyodide/v0.27.7/full/pyodide.js');
 const py=await loadPyodide({indexURL:'https://cdn.jsdelivr.net/pyodide/v0.27.7/full/'});
 await py.loadPackage(['numpy','scipy','shapely']);
 py.globals.set('notify_progress',text=>postMessage({type:'progress',text:String(text)}));
 for(const file of ['v5-core.py','pipeline.py','print-studio.py']){const r=await fetch(file);if(!r.ok)throw Error('تعذر تحميل ملفات المحرك.');await py.runPythonAsync(await r.text());}
 runtime=py;return py;
}
self.onmessage=async({data})=>{
 try{
  const py=await boot();let json;
  if(data.type==='process'){
   py.globals.set('input_bytes',new Uint8Array(data.buffer));py.globals.set('input_width',data.w);py.globals.set('input_height',data.h);
   py.globals.set('input_config',JSON.stringify(data.settings));py.globals.set('input_glyphs',JSON.stringify(data.glyphs));
   json=await py.runPythonAsync('run_image(input_bytes.to_py(),input_width,input_height,input_config,input_glyphs)');
   py.globals.delete('input_bytes');
  }else if(data.type==='recode'){
   py.globals.set('edit_cell',data.id);py.globals.set('edit_color',data.color);json=await py.runPythonAsync('change_code(edit_cell,edit_color)');
  }else if(data.type==='merge'){
   py.globals.set('edit_cell',data.id);json=await py.runPythonAsync('merge_same_color(edit_cell)');
  }else if(data.type==='undo'){
   json=await py.runPythonAsync('undo_edit()');
  }else throw Error('طلب غير معروف');
  postMessage({type:'result',action:data.type,result:JSON.parse(json)});
 }catch(e){postMessage({type:'error',text:String(e.message||e).slice(-1800)});}
};
