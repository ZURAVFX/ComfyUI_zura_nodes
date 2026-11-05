/** Image 1 is the editable plate. Extra images guide its appearance.
 * UI craft follows Unslop by Damir Sokolovsky (@heydamir), CC BY 4.0.
 * https://github.com/heydamir/unslop
 */
import {PreviewZoom} from './studio_preview_zoom.js';
const imageIcon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="8" cy="9" r="1.5"/><path d="m3 16 5-4 4 4 3-3 6 5"/></svg>';

export class ImageEditInputs {
  constructor(owner){
    this.owner=owner;const doc=owner.root.ownerDocument;
    owner.root.classList.add('image-composer-refined');
    this.heading=doc.createElement('strong');this.heading.className='zi-composer-heading zc-sr-only';owner.root.querySelector('.zc-image-composer').prepend(this.heading);
    this.source=doc.createElement('div');this.source.className='zc-image-source zc-gallery';this.source.hidden=true;owner.$('gallery').before(this.source);
    this.toggle=doc.createElement('button');this.toggle.type='button';this.toggle.textContent='View main image';this.toggle.hidden=true;owner.root.querySelector('.zc-image-tools').prepend(this.toggle);
    this.toggle.onclick=()=>{this.showSource=!this.showSource;this.sync();};
    this.clear=doc.createElement('button');this.clear.type='button';this.clear.textContent='Clear result';this.clear.title='Remove this generation from the canvas. It stays in History and on disk.';
    this.clear.onclick=()=>owner.clearImageResult();owner.root.querySelector('.zc-image-tools').prepend(this.clear);
    this.file=doc.createElement('input');this.file.type='file';this.file.accept='image/png,image/jpeg,image/webp';this.file.hidden=true;owner.$('reference-drop').append(this.file);
    this.file.onchange=()=>{const file=this.file.files?.[0];this.file.value='';if(file)void owner.uploadReferences([file],{main:true});};
    this.addReferences=owner.$('add-references');this.addLabel=this.addReferences.innerHTML;this.addHome=this.addReferences.parentElement;
  }
  mountControls(){
    const o=this.owner,doc=o.root.ownerDocument,bottom=o.root.querySelector('.zc-composer-bottom');
    const tools=doc.createElement('div');tools.className='zi-output-tools zc-prompt-tools';
    const workflow=doc.createElement('div');workflow.className='zc-tool-group zc-workflow-controls';workflow.setAttribute('role','group');workflow.setAttribute('aria-label','Model and workflow');
    workflow.append(bottom.querySelector('.zc-model-control'),o.imageTask);
    const output=doc.createElement('div');output.className='zc-tool-group';output.setAttribute('role','group');output.setAttribute('aria-label','Image size and settings');
    output.append(o.$('quick-settings').closest('details'),o.$('settings-toggle'));tools.append(workflow,output);bottom.prepend(tools);
    // Keep the existing action buttons and handlers, with a native fallback
    // that also works before optional web components finish loading.
    const menu=doc.createElement('details');menu.className='zc-tool-popup zi-image-actions';
    menu.innerHTML='<summary aria-label="Image actions">More</summary><div class="zc-tool-panel"></div>';
    for(const id of ['new','clear-history']){const button=o.$(id);button.classList.remove('zc-menu-fallback');menu.lastElementChild.append(button);button.addEventListener('click',()=>menu.open=false);}
    o.$('history-menu')?.remove();o.root.querySelector('.zc-image-tools').append(menu);
  }
  sync(){
    const o=this.owner,doc=o.root.ownerDocument,edit=o.imageOperation==='edit',main=edit&&!o.editMainMissing?o.references[0]:null,busy=!!o.job||!!o.pendingSubmission||o.submitting||o.uploading;
    this.heading.textContent=edit?'Edit your image':'Create an image';
    o.root.querySelector('.zc-image-heading h2').textContent=edit?'Edit image':'Create image';
    const key=main?JSON.stringify([main.file||main.filename,main.subfolder||'']):'',item=o.items[o.selectedImage||0],resultKey=JSON.stringify(item?.file||null);
    if(key!==this.key){this.key=key;this.showSource=!!main;this.resultKey=resultKey;}
    else if(resultKey!==this.resultKey){this.resultKey=resultKey;this.showSource=!item&&!!main;}
    const list=o.$('reference-list');list.classList.toggle('zc-edit-inputs',edit);this.addHome.hidden=edit;
    let groups=list.querySelector('.zc-edit-main');
    if(edit){
      if(!groups){
        groups=doc.createElement('div');groups.className='zc-edit-main zi-attachments';groups.setAttribute('aria-label','Image inputs');list.prepend(groups);
        const refs=doc.createElement('details');refs.className='zc-tool-popup zi-references';
        refs.innerHTML='<summary class="zc-attachment">'+imageIcon+'<span>References</span></summary><div class="zc-tool-panel zi-reference-panel"><strong>Edit references</strong><p>The main image stays Image 1. Extra images guide its appearance.</p><div class="zc-edit-guides"></div><p data-reference-status role="status"></p><button type="button" data-clear-images>Clear all images</button></div>';
        refs.querySelector('[data-clear-images]').onclick=()=>o.$('clear-references').click();
        groups.append(refs);
      }
      const picker=groups.querySelector('.zi-references'),refs=picker.querySelector('.zc-edit-guides'),cards=[...list.querySelectorAll('.zc-reference')];
      for(const card of cards){
        const remove=card.querySelector('[data-remove-ref]'),index=Number(remove.dataset.removeRef),isMain=!!main&&index===0;
        (isMain?groups:refs).append(card);card.classList.toggle('zi-main-chip',isMain);
        remove.setAttribute('aria-label',isMain?'Remove main image':`Remove edit reference ${index+(main?0:1)}`);
        const move=card.querySelector('[data-move-ref]');if(move)move.hidden=!!main&&index===1;
        if(isMain){
          let add=card.querySelector('[data-add-main]');
          if(!add){add=doc.createElement('button');add.type='button';add.dataset.addMain='';add.className='zc-attachment has-media zi-main-button';add.onclick=()=>this.file.click();const image=card.querySelector('img');card.querySelector('span')?.remove();add.append(image);const label=doc.createElement('span');label.textContent='Main image';add.append(label);card.prepend(add);}
          add.disabled=busy;add.setAttribute('aria-label','Replace main image');add.title='The image being edited · Image 1';
        }else card.querySelector('span').textContent=`Image ${index+(main?1:2)}`;
      }
      let empty=groups.querySelector('.zi-add-main');
      if(!main&&!empty){empty=doc.createElement('button');empty.type='button';empty.className='zc-attachment zi-add-main';empty.dataset.addMain='';empty.innerHTML=imageIcon+'<span>Add main image</span>';empty.onclick=()=>this.file.click();groups.prepend(empty);}
      if(main)empty?.remove();else if(empty)empty.disabled=busy;
      const mainCard=groups.querySelector('.zi-main-chip');if(mainCard)groups.prepend(mainCard);
      refs.after(this.addReferences);this.addReferences.classList.add('zc-attachment');this.addReferences.innerHTML=imageIcon+'<span>Add reference images</span>';this.addReferences.disabled||=!main;
      picker.querySelector('[data-reference-status]').textContent=o.$('reference-hint').textContent;
      picker.querySelector('[data-clear-images]').disabled=busy||!o.references.length;
      picker.querySelector('summary').setAttribute('aria-label',`${refs.children.length} edit reference images`);
      if(!main)o.$('generate').disabled=true;
    }else{
      this.addHome.prepend(this.addReferences);this.addReferences.innerHTML=this.addLabel;this.addReferences.classList.add('zc-attachment');
      if(groups){const cards=[...list.querySelectorAll('.zc-reference')];list.replaceChildren(...cards);o.referenceFingerprint=null;}
    }
    this.clear.hidden=!item;this.clear.disabled=busy;
    this.toggle.hidden=!edit||!main||!item;this.toggle.textContent=this.showSource?'View result':'View main image';
    this.toggle.setAttribute('aria-label',this.showSource?'View generated result':'View main image');
    const visible=edit&&!!main&&this.showSource;this.source.hidden=!visible;
    if(visible){
      let image=this.source.querySelector('img');if(!image){const figure=doc.createElement('figure');image=doc.createElement('img');image.alt='Main image being edited';figure.append(image);this.source.append(figure);this.sourceZoom=new PreviewZoom(figure,()=>image);}
      const url=o.api.apiURL('/view?'+new URLSearchParams({filename:main.filename,subfolder:main.subfolder||'',type:'input'}));
      if(image.getAttribute('src')!==url)image.src=url;
      this.sourceZoom?.update(key);
      o.$('gallery').hidden=true;o.$('image-empty').hidden=true;if(o.imageComparison?.host)o.imageComparison.host.hidden=true;
    }else{ o.imageComparison?.render();o.$('image-empty').hidden=!!item; }
  }
}
