export const EXR_STORAGE_KEY='zura-studio-exr-storage';
export const normaliseEXRStorage=value=>value==='float32'?'float32':'half';
export const hasEXROutput=output=>['hlg_and_exr','acescg_exr'].includes(output);
export function selectedEXRStorage(settings,output){return normaliseEXRStorage(settings?.exrStorage?.(output));}
export class EXRExportPreference {
  constructor(storage){this.storage=storage;this.sourceBitDepth=null;let saved;try{saved=storage.getItem(EXR_STORAGE_KEY);}catch{}this.explicit=['half','float32'].includes(saved)?saved:null;}
  set(value){this.explicit=normaliseEXRStorage(value);try{this.storage.setItem(EXR_STORAGE_KEY,this.explicit);}catch{}return this.explicit;}
  preferSource(bitDepth){this.sourceBitDepth=bitDepth===32?32:null;}
  value(output){if(this.explicit)return this.explicit;return this.sourceBitDepth===32&&hasEXROutput(output)?'float32':'half';}
}
