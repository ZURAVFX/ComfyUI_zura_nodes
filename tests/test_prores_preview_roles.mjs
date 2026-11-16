import assert from 'node:assert/strict';
import {parseHTML} from '../../ui-check/node_modules/linkedom/esm/index.js';
import {FrameVideoWorkspace} from '../web/studio_frames.js';
import {ReferenceVideoWorkspace} from '../web/studio_references.js';
import {DirectorWorkspace} from '../web/studio_director.js';
import {PaintVFXWorkspace} from '../web/studio_paint_vfx.js';
import {ArtistStudio} from '../web/studio_core.js';
import {studioModeAdapter} from '../web/studio_mode_adapters.js';
import {paintoutOutputRoles} from '../web/paintout_studio/paintout_outputs.js';
const {document,window}=parseHTML('<html><body></body></html>');Object.assign(globalThis,{document,window});
const preview={filename:'clip_preview.mp4',subfolder:'zura/results',type:'output'};
const master={filename:'clip.mov',subfolder:'zura/results',type:'output',preview,colour:{encoding:'srgb_display',sceneLinear:false}};
const api={apiURL:p=>p};
const dom=()=>{const page=document.createElement('section');page.innerHTML='<header class="zf-heading"></header>';document.body.append(page);const fields=new Map();return {page,fields,$:key=>fields.get(key)||null};};
for(const Class of [FrameVideoWorkspace,ReferenceVideoWorkspace]){
 const f=dom();for(const key of ['empty','image-slot','result','history'])f.fields.set(key,document.createElement(key==='result'?'video':'div'));
 Object.assign(f,{api,owner:{},items:[{file:master,config:{engine:'h3'}}]});Class.prototype.showResult.call(f,master);
 assert.equal(f.selectedResult,master);assert.match(f.$('result').src,/clip_preview\.mp4/);assert.match(f.masterDownload.href,/clip\.mov/);
 const mode=Class===FrameVideoWorkspace?'frames':'references',key=mode==='frames'?'frames':'referencesVideo';const selected=studioModeAdapter(mode).getSelectedOutput({mode,studio:{},[key]:f});
 assert.equal(selected.master.filename,'clip.mov');assert.equal(selected.preview.filename,'clip_preview.mp4');assert.deepEqual(selected.colour,master.colour);
}
{
 const f=dom();for(const key of ['result','download'])f.fields.set(key,document.createElement(key==='result'?'video':'a'));f.render=()=>{};f.api=api;
 const item={file:master};PaintVFXWorkspace.prototype.showResult.call(f,item);assert.equal(f.result,item);assert.match(f.$('result').src,/clip_preview\.mp4/);assert.match(f.$('download').href,/clip\.mov/);
}
{
 const f=dom();for(const key of ['stage','preview','result','result-meta','result-name','download'])f.fields.set(key,document.createElement(key==='result'?'video':key==='download'?'a':'div'));
 Object.assign(f,{api,resultView:true,selectedResult:{file:master},draft:{clips:[]},clip:()=>null,view:DirectorWorkspace.prototype.view,resultFile:DirectorWorkspace.prototype.resultFile});DirectorWorkspace.prototype.renderStage.call(f);
 assert.match(f.$('result').src,/clip_preview\.mp4/);assert.match(f.$('download').href,/clip\.mov/);assert.equal(f.selectedResult.file,master);
}
const take={asset:master,url:'legacy-master-url'};
assert.match(ArtistStudio.prototype.resultPlaybackURL.call({api},take),/clip_preview\.mp4/);assert.match(ArtistStudio.prototype.resultMasterURL.call({api},take),/clip\.mov/);
const roles=paintoutOutputRoles({files:[master],config:{outputMode:'SDR video'}});assert.equal(roles.master,master);assert.equal(roles.preview,preview);
console.log('ProRes previews: frame/reference/Director/Paint VFX/main Studio play returned MP4 companions while Download and AE retain MOV masters.');
