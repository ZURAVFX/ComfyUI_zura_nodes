import {PaintoutModels as StudioModels} from './paintout_models.js';
export class PaintoutModels extends StudioModels {
  videoGroup(){return this.context.pipeline==='hdr_hdr'?'targeted_auto_hdr':'targeted_auto';}
  recommended(){return this.context.phase==='hdr'?'hdr_conversion':this.context.pipeline==='sdr_hdr'?'_sdr_hdr':this.videoGroup();}
  updatePackages(raw){super.updatePackages(raw.filter(model=>['targeted_auto','targeted_auto_hdr','hdr_conversion'].includes(model.id)));}
}
