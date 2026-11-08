import {WatermarkWorkspace} from './watermark_workspace.js';
import {PaintoutWorkspace} from './studio_paintout.js';
let workspace;

export function getPaintoutWorkspace(owner){
  if(!workspace)workspace=new PaintoutWorkspace(owner,{paintoutOnly:true});
  else if(workspace.owner!==owner){
    workspace.close();
    Object.assign(workspace,{owner,studio:owner.studio,api:owner.api,app:owner.app});
  }
  if(workspace.page.parentNode!==owner.root)owner.root.append(workspace.page);
  workspace.page.hidden=false;
  return workspace;
}

let watermarkWorkspace;
export function getWatermarkWorkspace(owner){
  if(!watermarkWorkspace)watermarkWorkspace=new WatermarkWorkspace(owner);
  else if(watermarkWorkspace.owner!==owner){watermarkWorkspace.close();Object.assign(watermarkWorkspace,{owner,studio:owner.studio,api:owner.api,app:owner.app});}
  if(watermarkWorkspace.page.parentNode!==owner.root)owner.root.append(watermarkWorkspace.page);
  watermarkWorkspace.page.hidden=false;return watermarkWorkspace;
}
