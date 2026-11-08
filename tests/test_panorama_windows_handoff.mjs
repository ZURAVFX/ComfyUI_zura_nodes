import assert from 'node:assert/strict';
import {PanoramaCameraWorkspace} from '../web/studio_panorama.js';

const ui=Object.create(PanoramaCameraWorkspace.prototype);
const saved={filename:'warp_reviewed_00001_.mp4',subfolder:'genj\\panorama',type:'output'};
let request;
Object.assign(ui,{
  state:{source:{id:'source'},camera:'reviewed-camera',warp:saved},
  config:()=>({start:0,duration:2,width:1920,height:1080}),
  $:()=>({value:'Keep the performance'}),
  fetch:async(path,body)=>{request={path,body};return {};}
});
await ui.requestGraph('render');
assert.equal(request.body.warp.subfolder,'genj/panorama','Persisted Windows previews reach the validated render route');
assert.equal(request.body.warp.filename,saved.filename);
assert.equal(request.body.state,'reviewed-camera');
assert.equal(saved.subfolder,'genj\\panorama','Normalising the request does not mutate saved history');
ui.state.warp={...saved,subfolder:'genj/panorama'};
await ui.requestGraph('render');
assert.equal(request.body.warp.subfolder,'genj/panorama');
ui.state.warp=null;
await ui.requestGraph('geometry');
assert.equal(request.body.warp,null);
const elements=Object.fromEntries(['result','empty','media-label'].map(name=>[name,{pause(){}}]));
ui.$=name=>elements[name];
ui.state.source={file:'genj_studio\\clip-id\\reference.mp4',thumbnail_url:'/view?thumbnail',name:'My clip.mov'};
ui.showMedia('source');
const inputURL=new URL(elements.result.src,'http://localhost');
assert.equal(inputURL.searchParams.get('filename'),'reference.mp4');
assert.equal(inputURL.searchParams.get('subfolder'),'genj_studio/clip-id');
assert.equal(inputURL.searchParams.get('type'),'input');
assert.equal(elements.result.poster,'/view?thumbnail');
assert.equal(elements.result.hidden,false);
assert.equal(elements.empty.hidden,true);
assert.equal(elements['media-label'].textContent,'Source · My clip.mov');
ui.state.source.preview_url='/compatible-prores-proxy.mp4';
ui.showMedia('source');
assert.equal(elements.result.src,'/compatible-prores-proxy.mp4','Use browser-compatible proxies when available');
ui.state.warp=saved;ui.showMedia('warp');
assert.equal(elements.result.poster,'','Do not retain source poster over a generated preview');

const configured=Object.create(PanoramaCameraWorkspace.prototype);
configured.state={config:{start:.5,duration:1},geometryMode:'stable_scene',source:{duration:2}};
configured.$=name=>({size:{value:'768,432'},width:{value:'768'},height:{value:'432'}}[name]);
assert.equal(configured.config().geometry_mode,'stable_scene');
assert.deepEqual(
  [configured.config().width,configured.config().height,configured.config().start,configured.config().duration],
  [768,432,.5,1]
);
configured.state.geometryMode=undefined;
assert.equal(configured.config().geometry_mode,'per_frame','Legacy saved state must keep per-frame geometry');
console.log('Panorama Windows output handoff, geometry mode contract and restored history pass.');
