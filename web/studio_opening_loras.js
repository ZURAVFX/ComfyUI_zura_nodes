// Starting-image adapters are separate from the video sampler's adapters.
export class OpeningLoraControl {
  constructor(studio, host) {
    this.studio=studio;this.host=host;const doc=host.ownerDocument;
    this.el=doc.createElement('details');this.el.className='zc-tool-popup zc-opening-loras';
    this.el.innerHTML='<summary aria-label="Starting image LoRAs">Image LoRAs <span data-count></span></summary><div class="zc-tool-panel"><strong>Starting image LoRAs</strong><p class="gs-note">Optional model-only adapters for the generated image. Video LoRAs are separate.</p><label><span class="gs-label">Installed LoRA</span><select data-picker><option value="">Choose an installed LoRA</option></select></label><button type="button" class="gs-quiet" data-add>Add LoRA</button><div data-list></div><p class="gs-note" data-note></p></div>';
    host.append(this.el);
    this.el.addEventListener('toggle',async()=>{if(this.el.open&&!studio.loraCatalog){await studio.loadCustomLoras();this.sync();}});
    this.el.querySelector('[data-add]').onclick=()=>{const name=this.el.querySelector('[data-picker]').value,items=studio.config.opening_loras||[];if(!name||items.length>=4||items.some(x=>x.name===name))return;this.save([...items,{name,strength:1,confirm_unknown:false}]);};
    this.el.querySelector('[data-list]').addEventListener('click',event=>{const btn=event.target.closest('[data-remove-opening-lora]');if(!btn)return;const items=[...(studio.config.opening_loras||[])];items.splice(Number(btn.dataset.removeOpeningLora),1);this.save(items);});
    this.el.querySelector('[data-list]').addEventListener('change',event=>{const input=event.target,index=Number(input.dataset.openingIndex),items=(studio.config.opening_loras||[]).map(item=>({...item}));if(!Number.isInteger(index)||!items[index])return;if(input.dataset.openingField==='strength')items[index].strength=Number(input.value);if(input.dataset.openingField==='confirm')items[index].confirm_unknown=!!input.checked;this.save(items);});
  }
  family(){const c=this.studio.config;return c.workflow_mode==='camera'?'flux3_klein':({klein9b:'flux2_klein9b',flux3:'flux3_klein',qwen2511:'qwen2511',qwen21:'qwen21'})[c.opening_model||'klein9b'];}
  save(items){const s=this.studio;if(s.busy||s.project?.phase==='working')return;s.perform(async epoch=>{const config={...s.readConfig(),opening_loras:items};if(s.project){const id=s.project.id,updated=await s.requestOpeningLoraConfig(id,config);if(epoch!==s.resetEpoch||s.project?.id!==id)return;s.project=updated;}s.config=config;s.render();});}
  sync(stage){
    const s=this.studio,c=s.config,entries=c.opening_loras||[],busy=s.busy||s.project?.phase==='working',family=this.family(),doc=this.el.ownerDocument;
    this.el.hidden=stage==='video'||s.lookMode==='ready'||s.directViewport?.()||s.headSwap?.();
    this.el.querySelector('[data-count]').textContent=entries.length?`(${entries.length})`:'';
    const picker=this.el.querySelector('[data-picker]'),selection=picker.value;picker.replaceChildren();
    const blank=doc.createElement('option');blank.value='';blank.textContent='Choose an installed LoRA';picker.append(blank);
    for(const entry of s.loraCatalog||[]){const option=doc.createElement('option');option.value=entry.name;option.textContent=entry.name;option.disabled=!entry.usable||/ic[-_]lora/i.test(entry.name)||!!entry.metadata_family&&entry.metadata_family!==family;picker.append(option);}
    picker.value=selection;picker.disabled=busy;this.el.querySelector('[data-add]').disabled=busy||entries.length>=4;
    const list=this.el.querySelector('[data-list]');list.replaceChildren();
    entries.forEach((item,index)=>{const row=doc.createElement('div');row.className='gs-custom-lora-row';const heading=doc.createElement('div'),name=doc.createElement('strong'),remove=doc.createElement('button');name.textContent=item.name;remove.type='button';remove.className='gs-quiet';remove.dataset.removeOpeningLora=String(index);remove.textContent='Remove';remove.disabled=busy;heading.append(name,remove);row.append(heading);
      const label=doc.createElement('label'),title=doc.createElement('span'),strength=doc.createElement('input');title.textContent='Strength';title.className='gs-label';strength.type='number';strength.min='-2';strength.max='2';strength.step='.05';strength.value=String(item.strength);strength.dataset.openingIndex=String(index);strength.dataset.openingField='strength';strength.disabled=busy;label.append(title,strength);row.append(label);
      const info=s.loraCatalog?.find(candidate=>candidate.name===item.name);if(!info?.metadata_family){const label=doc.createElement('label'),check=doc.createElement('input'),text=doc.createElement('span');label.className='gs-checkbox';check.type='checkbox';check.checked=!!item.confirm_unknown;check.disabled=busy;check.dataset.openingIndex=String(index);check.dataset.openingField='confirm';text.textContent='I checked this LoRA matches the image model.';label.append(check,text);row.append(label);}list.append(row);});
    this.el.querySelector('[data-note]').textContent=entries.length?'Changing these settings requires a new starting image.':'';
  }
}
