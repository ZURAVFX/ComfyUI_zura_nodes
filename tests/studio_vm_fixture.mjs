import vm from 'node:vm';
import {normalStudioStorage} from '../web/studio_storage.js';
import {aeFrameConfig,assertAEFrameConfig} from '../web/studio_ae_frame_contract.js';
import {navigateStudioMode} from '../web/studio_mode_adapters.js';

// These fixtures remove ESM import declarations to evaluate the Studio class in
// an isolated VM. Restore its real dependencies and resolve module-relative URLs
// using the real source location; no application methods are replaced.
export function runStudioVMInContext(source,context,...options){
  Object.assign(context,{normalStudioStorage,aeFrameConfig,assertAEFrameConfig,navigateStudioMode});
  if(context.localStorage)globalThis.localStorage=context.localStorage;
  const moduleURL=JSON.stringify(new URL('../web/studio.js',import.meta.url).href);
  return vm.runInContext(source.replaceAll('import.meta.url',moduleURL),context,...options);
}
