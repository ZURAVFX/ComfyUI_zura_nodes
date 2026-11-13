import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const code=fs.readFileSync(new URL('../web/studio_image_compare.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace('export class','class');
const polishCss=fs.readFileSync(new URL('../web/studio_polish.css',import.meta.url),'utf8');
assert.match(polishCss,/--zc-image-width:1040px/,'Image workbench surfaces share one responsive maximum width');
assert.match(polishCss,/:is\(\.zc-image-scroll,\.zc-image-heading,\.zc-image-composer,\.zc-image-status\)\{width:100%;max-width:var\(--zc-image-width\);margin-inline:auto;box-sizing:border-box\}/,'Preview, prompt, result/empty/compare and progress states stay centred at the same width');
assert.match(polishCss,/#zc-progress\{width:100%;max-width:none\}/,'Generation progress cannot exceed its shared status container');
class Comparison {
  constructor(host){this.host=host;}
  show(...args){this.args=args;this.host.hidden=false;}
  hide(){this.host.hidden=true;}
}
const context={ShotComparison:Comparison,URLSearchParams};vm.createContext(context);
vm.runInContext(code+'\nthis.ImageResultComparison=ImageResultComparison;',context);
const attributes={},button={setAttribute:(name,value)=>attributes[name]=value},host={id:'comparison'},gallery={};
const view=new context.ImageResultComparison(host,button,gallery,{apiURL:url=>'http://comfy'+url});
view.update(null,[]);assert.ok(button.disabled);assert.ok(host.hidden);assert.equal(gallery.hidden,false);
const item={file:{filename:'result.png',subfolder:'zura_images'},references:[{filename:'original.png',subfolder:'refs'}]};
view.update(item,[{filename:'new-draft.png'}]);assert.equal(button.disabled,false);assert.ok(host.hidden,'Off by default');
button.onclick();assert.equal(attributes['aria-pressed'],'true');assert.equal(gallery.hidden,true);
assert.equal(view.comparison.args[0],'http://comfy/view?filename=original.png&subfolder=refs&type=input');
assert.equal(view.comparison.args[1],'http://comfy/view?filename=result.png&subfolder=zura_images&type=output');
assert.equal(view.comparison.args[3].sourceKind,'image');assert.equal(view.comparison.args[3].sourceLabel,'Image 1');
view.update({...item,file:{filename:'another-result.png'}},[{filename:'new-draft.png'}]);
assert.ok(view.comparison.args[1].includes('another-result.png'),'Selected history result updates');
view.comparison.onClose();assert.ok(host.hidden);assert.equal(gallery.hidden,false);assert.equal(attributes['aria-pressed'],'false');
view.update({...item,references:[]},[{filename:'unrelated.png'}]);assert.ok(button.disabled,'A text-only result must not compare against an unrelated draft');
view.update({file:item.file},[{filename:'legacy-source.png'}]);assert.equal(button.disabled,false,'Older saved results may use the visible Image 1');
button.onclick();view.update(null,[]);assert.ok(host.hidden);assert.equal(gallery.hidden,false,'Clearing history restores the normal viewport');
console.log('Optional image comparison, per-take Image 1, history selection and close/reset states pass.');
