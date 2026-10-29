// Optional user-selected model-only adapters for standalone LTX workflows.
// These are independent of the workflow's required video-guide IC LoRA.
export class LTXLoras {
  constructor(host,request,isBusy=()=>false,family=()=> 'ltx25',compact=false,label='Custom LoRAs'){
    this.request=request;this.isBusy=isBusy;this.family=family;this.items=[];this.catalog=null;const doc=host.ownerDocument;
    this.root=doc.createElement('details');this.root.className='gs-custom-loras'+(compact?' zc-tool-popup':'');
    this.root.innerHTML='<summary>Custom LoRAs <span data-count></span></summary><div class="gs-advanced-body'+(compact?' zc-tool-panel':'')+'"><p class="gs-note">Optional model-only adapters. Choose LoRAs for the selected model; required workflow adapters are separate.</p><label><span class="gs-label">Installed LoRA</span><select data-picker><option value="">Choose an installed LoRA</option></select></label><button type="button" data-custom-lora-add>Add LoRA</button><div data-list></div><p class="gs-note" data-error role="status"></p></div>';
    this.root.querySelector('summary').firstChild.textContent=label+' ';
    host.append(this.root);
    this.root.addEventListener('toggle',()=>{if(this.root.open && !this.catalog)this.load();});
    this.root.querySelector('[data-custom-lora-add]').onclick=()=>{if(this.isBusy()||!this.family())return;const name=this.root.querySelector('[data-picker]').value;if(!name||this.items.length>=4||this.items.some(x=>x.name===name))return;const info=this.catalog?.find(x=>x.name===name);if(!info?.usable||info.metadata_family&&info.metadata_family!==this.baseFamily()||/ic[-_]lora/i.test(name))return;this.items.push({name,strength:1,confirm_unknown:false});this.render();this.onchange?.();};
    this.root.querySelector('[data-list]').addEventListener('click',e=>{const button=e.target.closest('[data-remove]');if(!button||this.isBusy())return;this.items.splice(Number(button.dataset.remove),1);this.render();this.onchange?.();});
    this.root.querySelector('[data-list]').addEventListener('change',e=>{if(this.isBusy())return;const input=e.target,index=Number(input.dataset.index),item=this.items[index];if(!item)return;if(input.dataset.field==='strength')item.strength=Number(input.value);if(input.dataset.field==='confirm')item.confirm_unknown=!!input.checked;this.onchange?.();});
  }
  async load(){try{const data=await this.request('/zura/studio/loras');this.catalog=Array.isArray(data.loras)?data.loras:[];this.root.querySelector('[data-error]').textContent='';this.render();}catch(error){this.root.querySelector('[data-error]').textContent=error.message||'Could not load installed LoRAs.';}}
  value(){return this.items.map(item=>({...item}));}
  baseFamily(){return (this.family()||'').replace(/^wan22_(high|low)$/,'wan22');}
  setValue(items){this.items=Array.isArray(items)?items.slice(0,4).map(item=>({...item})):[];this.render();}
  async patch(graph,items=this.value()){
    if(!items.length)return graph;
    if(!this.family())throw new Error('Custom LoRAs are not available for this model. Remove them or choose a compatible model.');
    const data=await this.request('/zura/studio/loras/apply',{family:this.family(),graph,loras:items});
    if(!data?.graph)throw new Error('Could not apply the selected LoRAs.');return data.graph;
  }
  setBusy(busy){this.root.querySelectorAll('select,button,input').forEach(el=>el.disabled=busy);if(!busy)this.render();}
  render(){
    const doc=this.root.ownerDocument,busy=this.isBusy(),picker=this.root.querySelector('[data-picker]'),selected=picker.value;
    if(!this.family())this.root.querySelector('[data-error]').textContent='Custom LoRAs are unavailable for this model. Remove selections or choose another model.';
    else if(this.root.querySelector('[data-error]').textContent.startsWith('Custom LoRAs are unavailable'))this.root.querySelector('[data-error]').textContent='';
    picker.replaceChildren();const placeholder=doc.createElement('option');placeholder.value='';placeholder.textContent='Choose an installed LoRA';picker.append(placeholder);
    for(const item of this.catalog||[]){const option=doc.createElement('option');option.value=item.name;option.textContent=item.name;option.disabled=!item.usable||!!item.metadata_family&&item.metadata_family!==this.baseFamily()||/ic[-_]lora/i.test(item.name);picker.append(option);}picker.value=selected;picker.disabled=busy||!this.family();
    this.root.querySelector('[data-count]').textContent=this.items.length?`(${this.items.length})`:'';this.root.querySelector('[data-custom-lora-add]').disabled=busy||!this.family()||this.items.length>=4;
    const list=this.root.querySelector('[data-list]');list.replaceChildren();
    this.items.forEach((item,index)=>{const row=doc.createElement('div');row.className='gs-custom-lora-row';const heading=doc.createElement('div'),name=doc.createElement('strong'),remove=doc.createElement('button');name.textContent=item.name;remove.type='button';remove.dataset.remove=String(index);remove.textContent='Remove';remove.disabled=busy;heading.append(name,remove);row.append(heading);
      const label=doc.createElement('label'),title=doc.createElement('span'),strength=doc.createElement('input');title.textContent='Strength';strength.type='number';strength.min='-2';strength.max='2';strength.step='.05';strength.value=String(item.strength);strength.dataset.index=String(index);strength.dataset.field='strength';strength.disabled=busy;label.append(title,strength);row.append(label);
      if(!this.catalog?.find(candidate=>candidate.name===item.name)?.metadata_family){const confirm=doc.createElement('label'),check=doc.createElement('input'),text=doc.createElement('span');confirm.className='gs-checkbox';check.type='checkbox';check.checked=!!item.confirm_unknown;check.dataset.index=String(index);check.dataset.field='confirm';check.disabled=busy;text.textContent='I checked this LoRA matches the selected model.';confirm.append(check,text);row.append(confirm);}list.append(row);});
  }
}
