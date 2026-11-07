import {PaintoutModels as StudioModels} from './paintout_models.js';
export class PaintoutModels extends StudioModels {
  videoGroup(){return this.context.removalMethod==='subtitles'?(this.context.subtitleVariant==='joyfox'?'subtitles':'subtitles_zarxrax'):this.context.pipeline==='hdr_hdr'?'targeted_auto_hdr':'targeted_auto';}
  recommended(){return this.context.phase==='hdr'?'hdr_conversion':this.context.pipeline==='sdr_hdr'?'_sdr_hdr':this.videoGroup();}
  updatePackages(raw){super.updatePackages(raw.filter(model=>['targeted_auto','targeted_auto_hdr','hdr_conversion','subtitles','subtitles_zarxrax'].includes(model.id)));}
  setContext(context){const changed=this.context?.removalMethod!==context?.removalMethod||this.context?.subtitleVariant!==context?.subtitleVariant;super.setContext(context);if(changed){this.pendingInstall=null;this.generation++;const id=this.recommended();if(this.models.some(model=>model.id===id))this.$('package').value=id;this.render();}}
}
