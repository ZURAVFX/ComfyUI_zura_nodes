import vm from 'node:vm';
import {normalStudioStorage} from '../web/studio_storage.js';
import {aeFrameConfig,assertAEFrameConfig} from '../web/studio_ae_frame_contract.js';
import {navigateStudioMode} from '../web/studio_mode_adapters.js';
import {scopedStudioAPI} from '../web/studio_ae_lifecycle.js';

// These fixtures remove ESM import declarations to evaluate the Studio class in
// an isolated VM. Restore its real dependencies and resolve module-relative URLs
// using the real source location; no application methods are replaced.
export function runStudioVMInContext(source,context,...options){
  Object.assign(context,{normalStudioStorage,aeFrameConfig,assertAEFrameConfig,navigateStudioMode,scopedStudioAPI});
  // The real module imports Comfy's API. Import-stripped constructor fixtures
  // must supply one, but must never make an accidental real request.
  context.api??={fetchApi(){throw Error('Provide a fixture API before making requests');}};
  // Linkedom omits HTMLFormControlsCollection. Restore the named controls used
  // by the real media-import form without replacing application methods.
  const form=context.document?.createElement?.('form');
  if(form?.localName==='form'&&typeof form.querySelectorAll==='function'&&form.elements===undefined){
    const prototype=Object.getPrototypeOf(form);
    if(!Object.getOwnPropertyDescriptor(prototype,'elements'))Object.defineProperty(prototype,'elements',{configurable:true,get(){
      if(this.localName!=='form')return undefined;
      const fields=[...this.querySelectorAll('input,select,textarea,button')],named={};
      for(const [index,field] of fields.entries()){named[index]=field;for(const key of [field.getAttribute('name'),field.id])if(key&&!Object.hasOwn(named,key))named[key]=field;}
      named.length=fields.length;named.item=index=>fields[index]||null;named.namedItem=name=>named[name]||null;return named;
    }});
  }
  const dialog=context.document?.createElement?.('dialog');
  if(dialog&&typeof dialog.close!=='function'){
    const proto=Object.getPrototypeOf(dialog);
    proto.close=function(){this.removeAttribute('open');};
    proto.showModal=function(){this.setAttribute('open','');};
  }
  if(context.localStorage)globalThis.localStorage=context.localStorage;
  const moduleURL=JSON.stringify(new URL('../web/studio.js',import.meta.url).href);
  return vm.runInContext(source.replaceAll('import.meta.url',moduleURL),context,...options);
}
