import assert from 'node:assert/strict';
import {HDRSourceTool} from '../web/studio_hdr.js';
const controls=new Map();
const q=id=>{if(!controls.has(id))controls.set(id,{hidden:true,disabled:true});return controls.get(id);};
const previous={preview:{filename:'previous-preview.mp4',type:'output'},files:[{filename:'previous.mov',type:'output'}]};
let visible;
const tool=Object.assign(Object.create(HDRSourceTool.prototype),{completedResult:previous,hlgResult:previous.files[0],onUseResult(){},storage:{removeItem(){}},$:q,updateRangeSummary(){},loras:{setBusy(){}},showResult(file){visible=file;q('result').hidden=false;}});
tool.finish();assert.equal(tool.completedResult,previous);assert.equal(visible,previous.preview);assert.equal(q('use-result').hidden,false);assert.equal(tool.busy,false);
console.log('HDR failure recovery: prior completed take and use-result action remain available.');
