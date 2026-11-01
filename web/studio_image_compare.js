import {ShotComparison} from './studio_compare.js';

/** Compare a selected take with its own first reference, independent of model. */
export class ImageResultComparison {
  constructor(host, button, gallery, api) {
    this.host=host;this.button=button;this.gallery=gallery;this.api=api;this.active=false;
    this.comparison=new ShotComparison(host);
    this.button.setAttribute('aria-controls',host.id);
    this.button.onclick=()=>{this.active=!this.active;this.render();};
    this.comparison.onClose=()=>{this.active=false;this.render();};
  }
  update(item, references=[]) {
    this.item=item;
    // New drafts must not change the source used for an existing generation.
    this.reference=(Array.isArray(item?.references)?item.references:references)[0];
    this.render();
  }
  render() {
    const available=!!this.item?.file?.filename&&!!this.reference?.filename;
    this.button.disabled=!available;
    this.button.title=available?'Compare Image 1 with this result':'Add Image 1 and generate a result to compare';
    const visible=available&&this.active;
    this.button.setAttribute('aria-pressed',String(visible));
    this.gallery.hidden=visible;
    if(!visible){this.comparison.hide();return;}
    const url=(asset,type)=>this.api.apiURL('/view?'+new URLSearchParams({filename:asset.filename,subfolder:asset.subfolder||'',type}));
    this.comparison.show(url(this.reference,'input'),url(this.item.file,'output'),0,
      {kind:'image',sourceKind:'image',sourceLabel:'Image 1',resultLabel:'Result'});
  }
}
