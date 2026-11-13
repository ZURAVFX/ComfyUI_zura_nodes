// CPU integration bridge: use the actual JS adapter and source/view descriptors.
import {studioModeAdapter} from '../web/studio_mode_adapters.js';
import {StudioDeliveryControls,studioInputDescription} from '../web/studio_delivery_controls.js';
import {StudioDisplaySettings,studioDisplaySource} from '../web/studio_display_settings.js';
let raw='';for await(const chunk of process.stdin)raw+=chunk;
const source=JSON.parse(raw),controls={},mode=process.argv[2]||'image';
const owner={mode,studio:{},references:[],ripple:{state:{},setSource(info){this.source=this.sourceInfo=info;},save(){},render(){}},show:async function(mode){this.mode=mode;},setImageOperation:async()=>{},clearImageResult(){},save(){},render(){},$:id=>controls[id]??={value:''}};
await studioModeAdapter(mode).acceptInput(owner,source);
const workspace=mode==='image'?owner:owner.ripple,ref=mode==='image'?owner.references[0]:workspace.source,selected=StudioDeliveryControls.prototype.source.call({owner},workspace),description=studioInputDescription(selected);
const delivery={workspace:()=>workspace,source:()=>selected,input:()=>description,inputOverrides:{},sourceKey:()=>ref.filename||ref.path,raw:()=>null,outputFor:()=>null};
const choices=StudioDisplaySettings.prototype.choices.call({owner,delivery});
const config=StudioDeliveryControls.prototype.configure.call({owner,input:()=>description,settings:{exrStorage:()=> 'float32'},output:'sdr',hdrFormat:'acescg_exr'},workspace,{references:owner.references},mode);
process.stdout.write(JSON.stringify({reference:ref,description,selector:studioDisplaySource(selected),preview:choices.original,config}));
