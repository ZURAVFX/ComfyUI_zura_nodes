import {normalStudioStorage} from './studio_storage.js';

const KEY='zura-studio-display-transform-v2';
export const UNMANAGED_ICC_DISPLAY=Object.freeze({config:'zura-preview://verified-icc',display:'After Effects Viewer',view:'Unmanaged working RGB',label:'AE Viewer (unmanaged working RGB)'});
export const isUnmanagedICCDisplay=preset=>preset?.config===UNMANAGED_ICC_DISPLAY.config&&preset?.display===UNMANAGED_ICC_DISPLAY.display&&preset?.view===UNMANAGED_ICC_DISPLAY.view;
export function verifiedICCPreviewSource(source){
  const colour=source?.colour,processing=source?.processingInput;
  return processing?.conversion==='verified_icc_to_sdr8'&&colour?.management==='icc'&&colour?.encoding==='ae_project_icc'&&
    colour?.sceneLinear===true&&/^[a-f0-9]{64}$/i.test(colour?.profileSha256||'')&&
    processing?.sourceProfileSha256===colour.profileSha256&&processing?.sourceEncoding==='scene_linear_rec709';
}
const inverseLUT=Uint8Array.from({length:256},(_,code)=>{
  const value=code/255,linear=value<=0.04045?value/12.92:Math.pow((value+0.055)/1.055,2.4);
  return Math.max(0,Math.min(255,Math.round(linear*255)));
});
/** Display-only inverse of the exact IEC sRGB model-view encoding. */
export function inverseSRGBPreviewPixels(data){
  for(let i=0;i<data.length;i+=4){data[i]=inverseLUT[data[i]];data[i+1]=inverseLUT[data[i+1]];data[i+2]=inverseLUT[data[i+2]];}
  return data;
}
export const displayPresetKey=preset=>preset?JSON.stringify([preset.config,preset.display,preset.view]):'none';
export const validDisplayPreset=preset=>!!preset&&['config','display','view'].every(key=>typeof preset[key]==='string'&&preset[key].length>0&&preset[key].length<512);
const tuple=preset=>preset?Object.freeze({config:preset.config,display:preset.display,view:preset.view}):null;

/** Global preview choice only. No workspace, frame, media or job data enters it. */
export function createDisplayTransformStore(storage=normalStudioStorage()){
  let choice=null,revision=0,ready=false,catalogue=new Map();const listeners=new Set();
  try{const saved=JSON.parse(storage.getItem(KEY));if(saved?.schemaVersion===2&&saved.explicit===true&&(saved.selection===null||validDisplayPreset(saved.selection)))choice=saved.selection?.view==='Raw'?null:tuple(saved.selection);}catch{}
  const snapshot=()=>Object.freeze({selection:ready?choice:null,revision,label:ready&&choice?(catalogue.get(displayPresetKey(choice))?.label||choice.view):'None'});
  const notify=()=>{const value=snapshot();for(const listener of [...listeners])listener(value);};
  return {
    get:snapshot,
    get requested(){return choice;},
    get catalogueReady(){return ready;},
    subscribe(listener){listeners.add(listener);return()=>listeners.delete(listener);},
    registerCatalogue(presets){
      const next=new Map(presets.filter(validDisplayPreset).map(preset=>[displayPresetKey(preset),{...preset}]));
      if(!next.size)return;
      const before=displayPresetKey(ready?choice:null);if(ready){for(const [key,value]of next)catalogue.set(key,value);}else catalogue=next;ready=true;
      if(choice&&!catalogue.has(displayPresetKey(choice)))choice=null;
      if(before!==displayPresetKey(choice)){revision++;notify();}
    },
    choose(preset){
      if(preset!==null&&(!validDisplayPreset(preset)||!catalogue.has(displayPresetKey(preset))))return false;
      const next=preset?.view==='Raw'?null:tuple(preset);if(displayPresetKey(next)===displayPresetKey(choice)&&ready)return false;
      choice=next;ready=true;revision++;
      try{storage.setItem(KEY,JSON.stringify({schemaVersion:2,explicit:true,selection:choice}));}catch{}
      notify();return true;
    },
    get subscriberCount(){return listeners.size;},
  };
}

// Preview transforms are retired. Ignore old saved choices and never register
// a display transform for ordinary Studio media or the AE source viewer.
export const studioDisplayTransform=Object.freeze({
  get:()=>({selection:null,revision:0,label:'None'}),requested:null,catalogueReady:true,
  subscribe:()=>()=>{},registerCatalogue(){},choose:()=>false,subscriberCount:0,
});

const owners=new WeakMap();
export function registerDisplayPreview(element,viewer){owners.set(element,viewer);return()=>{if(owners.get(element)===viewer)owners.delete(element);};}
export function displayPreviewOwner(element){for(let current=element;current;current=current.parentElement){const owner=owners.get(current);if(owner)return owner;}return null;}
