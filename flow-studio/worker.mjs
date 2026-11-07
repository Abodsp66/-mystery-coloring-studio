import {generate} from './engine.mjs';
self.onmessage=({data})=>{
  try{
    const result=generate(new Uint8ClampedArray(data.buffer),data.w,data.h,data.settings,data.glyphs,
      text=>self.postMessage({type:'progress',text}));
    self.postMessage({type:'result',result},[result.regionMap.buffer]);
  }catch(error){self.postMessage({type:'error',text:String(error.message||error)});}
};
